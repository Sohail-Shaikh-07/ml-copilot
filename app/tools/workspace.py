"""Workspace tools for reading, searching, git inspection, and safe patch edits."""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import os
import re
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Any, Iterator

from app.config import AppSettings

# Bandit B404 is expected here because this module exposes reviewed subprocess wrappers.

IGNORED_PATH_NAMES = {".git", "__pycache__", "node_modules", ".pytest_cache"}
MAX_READ_LINES = 2000
MAX_LINE_LENGTH = 4000
MAX_OUTPUT_LINES = 500
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_TIMEOUT_SECONDS = 3600
MAX_COMMAND_OUTPUT_CHARS = 20_000
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07")
_DANGEROUS_COMMAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brm\s+-[^\n]*\brf\b", re.IGNORECASE), "recursive deletion via rm"),
    (re.compile(r"\bdel\b[^\n]*\s/[sqf]", re.IGNORECASE), "recursive deletion via del"),
    (
        re.compile(r"\bremove-item\b[^\n]*\s-recurse\b", re.IGNORECASE),
        "recursive deletion via Remove-Item",
    ),
    (re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE), "hard reset of the git worktree"),
    (re.compile(r"\bgit\s+clean\b[^\n]*\s-f", re.IGNORECASE), "forced git clean"),
    (re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b", re.IGNORECASE), "filesystem formatting"),
    (re.compile(r"\bdiskpart\b", re.IGNORECASE), "disk partitioning"),
    (re.compile(r"\bdd\s+if=", re.IGNORECASE), "raw disk overwrite via dd"),
    (re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE), "disk formatting command"),
)


def _safe_path(path: Path, workspace_root: Path) -> Path | None:
    """Resolve path and ensure it stays within workspace root. Returns None if unsafe."""
    try:
        resolved = path.resolve()
        try:
            resolved.relative_to(workspace_root.resolve())
            return resolved
        except ValueError:
            return None
    except (OSError, RuntimeError):
        return None


def _format_workspace_relative(path: Path, workspace_root: Path) -> str:
    """Return a workspace-relative display path."""
    return str(path.relative_to(workspace_root))


def _workspace_error(path_value: str, workspace_root: Path) -> str:
    """Return a consistent workspace boundary error."""
    return f"Error: Path {path_value!r} is outside workspace root {workspace_root}"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return de-duplicated values while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _format_lines(lines: list[str], offset: int = 1) -> list[str]:
    """Add line numbers to lines."""
    result = []
    for i, line in enumerate(lines, start=offset):
        if len(line) > MAX_LINE_LENGTH:
            truncated = len(line) - MAX_LINE_LENGTH
            line = line[:MAX_LINE_LENGTH] + f"... [truncated {truncated} chars]"
        result.append(f"{i:>6}\t{line}")
    return result


def _resolve_search_root(
    path_filter: str | None,
    workspace_root: Path,
) -> Path | None:
    """Resolve the search root inside the workspace."""
    if not path_filter:
        return workspace_root
    return _safe_path(Path(path_filter), workspace_root)


def _extract_patch_paths(patch_text: str) -> list[str]:
    """Extract referenced file paths from a unified diff patch."""
    paths: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"^diff --git a/(.+) b/(.+)$", line)
            if not match:
                raise ValueError(f"Unsupported diff header: {line}")
            left_path, right_path = match.groups()
            if left_path != "/dev/null":
                paths.append(left_path)
            if right_path != "/dev/null":
                paths.append(right_path)
            continue
        if line.startswith("--- "):
            candidate = line[4:].strip()
            if candidate.startswith("a/"):
                candidate = candidate[2:]
            if candidate != "/dev/null":
                paths.append(candidate)
            continue
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate.startswith("b/"):
                candidate = candidate[2:]
            if candidate != "/dev/null":
                paths.append(candidate)
    return _dedupe_preserve_order(paths)


def _validate_patch_targets(
    patch_paths: list[str],
    workspace_root: Path,
) -> list[Path]:
    """Resolve patch paths and ensure every target stays inside the workspace."""
    if not patch_paths:
        raise ValueError("Patch does not reference any files.")

    safe_targets: list[Path] = []
    for patch_path in patch_paths:
        candidate = Path(patch_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(f"Patch path {patch_path!r} escapes the workspace root.")
        safe_target = _safe_path(workspace_root / candidate, workspace_root)
        if safe_target is None:
            raise ValueError(f"Patch path {patch_path!r} escapes the workspace root.")
        safe_targets.append(safe_target)
    return safe_targets


def _format_subprocess_error(prefix: str, result: subprocess.CompletedProcess[str]) -> str:
    """Return a readable error message for a failed subprocess."""
    details = result.stderr.strip() or result.stdout.strip() or "Unknown error."
    return f"Error: {prefix} {details}"


def _normalize_timeout(value: Any) -> int:
    """Return a bounded timeout for command execution."""
    if value in (None, ""):
        return DEFAULT_COMMAND_TIMEOUT_SECONDS

    timeout = int(value)
    timeout = max(timeout, 1)
    return min(timeout, MAX_COMMAND_TIMEOUT_SECONDS)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from command output."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _truncate_command_output(output: str) -> str:
    """Trim oversized command output while keeping the start and end."""
    if len(output) <= MAX_COMMAND_OUTPUT_CHARS:
        return output

    head_budget = MAX_COMMAND_OUTPUT_CHARS // 3
    tail_budget = MAX_COMMAND_OUTPUT_CHARS - head_budget
    omitted = len(output) - MAX_COMMAND_OUTPUT_CHARS
    return (
        output[:head_budget]
        + (f"\n\n... [{omitted} chars omitted, showing first {head_budget} and last {tail_budget}] ...\n\n")
        + output[-tail_budget:]
    )


def _resolve_command_shell() -> list[str]:
    """Return the shell executable and flags used for approved commands."""
    if os.name == "nt":
        resolved = os.environ.get("ComSpec") or shutil.which("cmd")
        if resolved:
            return [resolved, "/d", "/s", "/c"]
        raise FileNotFoundError("cmd.exe not found in PATH.")

    for executable in ("bash", "sh"):
        resolved = shutil.which(executable)
        if resolved:
            return [resolved, "-lc"]
    raise FileNotFoundError("No compatible shell executable found in PATH.")


def _prepare_shell_command(command: str) -> str:
    """Normalize command text for the platform shell."""
    stripped = command.lstrip()
    if os.name == "nt" and stripped.startswith('"'):
        return f"call {command}"
    return command


def _find_dangerous_command_reason(command: str) -> str | None:
    """Return the matching dangerous-command reason, if any."""
    for pattern, reason in _DANGEROUS_COMMAND_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def _format_command_result(
    *,
    command: str,
    work_dir: Path,
    workspace_root: Path,
    timeout: int,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    timed_out: bool = False,
) -> str:
    """Format command execution details for the agent."""
    cleaned_stdout = _truncate_command_output(_strip_ansi(stdout).strip())
    cleaned_stderr = _truncate_command_output(_strip_ansi(stderr).strip())
    output_lines = [
        f"Command: {command}",
        f"Working directory: {_format_workspace_relative(work_dir, workspace_root)}",
        f"Timeout: {timeout}s",
    ]
    if exit_code is not None:
        output_lines.append(f"Exit code: {exit_code}")
    if timed_out:
        output_lines.append("Status: timed out")

    if cleaned_stdout:
        output_lines.extend(["", "Stdout:", cleaned_stdout])
    if cleaned_stderr:
        output_lines.extend(["", "Stderr:", cleaned_stderr])
    if not cleaned_stdout and not cleaned_stderr:
        output_lines.extend(["", "(no output)"])
    return "\n".join(output_lines)


def _decode_process_output(value: bytes | str | None) -> str:
    """Decode subprocess pipe output."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(encoding="utf-8", errors="replace")
    return value


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    """Terminate a child process, escalating to kill if it does not exit."""
    if process.returncode is not None:
        return

    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def _run_shell_command(
    command_parts: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> tuple[str, str, int | None, bool]:
    """Run a shell command asynchronously with timeout and cancellation support."""
    process = await asyncio.create_subprocess_exec(
        *command_parts,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    communicate_task = asyncio.create_task(process.communicate())

    try:
        done, _pending = await asyncio.wait({communicate_task}, timeout=timeout)
        timed_out = communicate_task not in done
        if timed_out:
            await _stop_process(process)
        stdout, stderr = await communicate_task
        return (
            _decode_process_output(stdout),
            _decode_process_output(stderr),
            process.returncode,
            timed_out,
        )
    except asyncio.CancelledError:
        await _stop_process(process)
        communicate_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await communicate_task
        raise


def _resolve_git_executable() -> str:
    """Return an absolute path to the git executable."""
    git_executable = shutil.which("git")
    if not git_executable:
        raise FileNotFoundError("Git executable not found in PATH.")
    return git_executable


def _run_git_command(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with a resolved executable inside the workspace."""
    git_executable = _resolve_git_executable()
    command = [git_executable, *args]
    return subprocess.run(  # nosec B603
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _extension_for(file_type: str | None) -> str | None:
    """Normalize an optional file-type filter to an extension."""
    if not file_type:
        return None

    type_map = {
        "py": ".py",
        "python": ".py",
        "js": ".js",
        "ts": ".ts",
        "tsx": ".tsx",
        "jsx": ".jsx",
        "md": ".md",
        "json": ".json",
        "yaml": ".yaml",
        "yml": ".yml",
        "toml": ".toml",
        "txt": ".txt",
    }
    return type_map.get(file_type.lower(), f".{file_type.lower()}")


def _should_skip_search_path(path: Path, search_root: Path) -> bool:
    """Return True when a candidate path should be skipped during search."""
    relative_parts = path.relative_to(search_root).parts
    return any(part.startswith(".") or part in IGNORED_PATH_NAMES for part in relative_parts)


def _iter_search_files(
    search_root: Path,
    extension_filter: str | None,
) -> Iterator[Path]:
    """Yield searchable files within the workspace."""
    for item in sorted(search_root.rglob("*")):
        if not item.is_file():
            continue
        if _should_skip_search_path(item, search_root):
            continue
        if extension_filter and item.suffix.lower() != extension_filter:
            continue
        yield item


def _read_search_matches(
    file_path: Path,
    regex: re.Pattern[str],
    workspace_root: Path,
    remaining: int,
) -> list[str]:
    """Collect up to `remaining` matches from a single file."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []

    matches: list[str] = []
    rel_path = _format_workspace_relative(file_path, workspace_root)
    for line_num, line in enumerate(content.splitlines(), start=1):
        if not regex.search(line):
            continue
        display_line = line[:200] + ("..." if len(line) > 200 else "")
        matches.append(f"{rel_path}:{line_num}: {display_line}")
        if len(matches) >= remaining:
            break
    return matches


async def list_files_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """List files in workspace, optionally matching a pattern."""
    dir_path = args.get("path", str(settings.paths.workspace_root))
    pattern = args.get("pattern", "*")

    safe = _safe_path(Path(dir_path), settings.paths.workspace_root)
    if safe is None:
        return _workspace_error(dir_path, settings.paths.workspace_root)

    if not safe.exists():
        return f"Error: Directory does not exist: {dir_path}"

    if not safe.is_dir():
        return f"Error: Not a directory: {dir_path}"

    files = sorted(f.name for f in safe.iterdir() if fnmatch.fnmatch(f.name, pattern))

    if not files:
        return f"No files matching {pattern!r} in {dir_path}"

    display_path = _format_workspace_relative(safe, settings.paths.workspace_root)
    output_lines = [f"Contents of {display_path} ({len(files)} items):"]
    for name in files[:MAX_OUTPUT_LINES]:
        full_path = safe / name
        marker = "/" if full_path.is_dir() else ""
        output_lines.append(f"  {name}{marker}")
    if len(files) > MAX_OUTPUT_LINES:
        output_lines.append(f"  ... and {len(files) - MAX_OUTPUT_LINES} more files")
    return "\n".join(output_lines)


async def read_file_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Read a file with line numbers, supporting offset and limit."""
    file_path = args.get("path", "")
    if not file_path:
        return "Error: No path provided."

    safe = _safe_path(Path(file_path), settings.paths.workspace_root)
    if safe is None:
        return _workspace_error(file_path, settings.paths.workspace_root)

    if not safe.exists():
        return f"Error: File not found: {file_path}"

    if safe.is_dir():
        return "Error: Cannot read a directory. Use list_files instead."

    try:
        content = safe.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Error reading file: {exc}"

    lines = content.splitlines()
    total_lines = len(lines)
    offset = max(args.get("offset", 1), 1)
    limit = args.get("limit", MAX_READ_LINES)

    offset = min(offset, total_lines)
    if offset < 1:
        offset = 1

    start_idx = offset - 1
    end_idx = min(start_idx + limit, total_lines)
    numbered = _format_lines(lines[start_idx:end_idx], offset=offset)

    display_path = _format_workspace_relative(safe, settings.paths.workspace_root)
    header = f"--- {display_path} ({total_lines} lines total, showing {offset}-{end_idx}) ---"
    footer = "--- End of file ---"

    if len(numbered) < MAX_OUTPUT_LINES:
        return header + "\n" + "\n".join(numbered) + "\n" + footer

    omitted = len(numbered) - MAX_OUTPUT_LINES
    return header + "\n" + "\n".join(numbered[:MAX_OUTPUT_LINES]) + f"\n... [{omitted} more lines] ...\n" + footer


async def search_text_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Search for text pattern in files using regex."""
    pattern = args.get("pattern", "")
    if not pattern:
        return "Error: No pattern provided."

    path_filter = args.get("path")
    file_type = args.get("type")
    max_results = args.get("max_results", 100)

    safe = _resolve_search_root(path_filter, settings.paths.workspace_root)
    if safe is None:
        return _workspace_error(path_filter or "", settings.paths.workspace_root)

    if not safe.exists():
        return f"Error: Search path does not exist: {path_filter or 'workspace'}"

    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: Invalid regex pattern {pattern!r}: {exc}"

    extension_filter = _extension_for(file_type)
    matches: list[str] = []

    for item in _iter_search_files(safe, extension_filter):
        remaining = max_results - len(matches)
        if remaining <= 0:
            break
        matches.extend(
            _read_search_matches(
                item,
                regex,
                settings.paths.workspace_root,
                remaining,
            )
        )

    if not matches:
        return f"No matches found for pattern {pattern!r}"

    output = [f"Found {len(matches)} matches for {pattern!r}:"]
    output.extend(matches)
    return "\n".join(output)


async def git_status_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Show git status of the workspace."""
    work_dir = args.get("work_dir", str(settings.paths.workspace_root))
    safe = _safe_path(Path(work_dir), settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {work_dir!r} is outside workspace root"

    try:
        result = _run_git_command(["status", "--porcelain"], cwd=safe)
        output = result.stdout.strip()
        if not output:
            return "Git working tree is clean."
        return "Git status:\n" + output
    except subprocess.TimeoutExpired:
        return "Error: Git status command timed out."
    except FileNotFoundError:
        return "Error: Git is not installed or not in PATH."
    except Exception as exc:
        return f"Error running git status: {exc}"


async def git_diff_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Show git diff of the workspace."""
    work_dir = args.get("work_dir", str(settings.paths.workspace_root))
    file_path = args.get("path")
    staged = args.get("staged", False)

    safe = _safe_path(Path(work_dir), settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {work_dir!r} is outside workspace root"

    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")
    if file_path:
        file_full = (safe / file_path).resolve()
        if _safe_path(file_full, settings.paths.workspace_root) is None:
            return f"Error: File path {file_path!r} is outside workspace root"
        cmd.extend(["--", file_path])

    try:
        result = _run_git_command(cmd[1:], cwd=safe)
        output = result.stdout.strip()
        if not output:
            if staged:
                return "No staged changes."
            return "No uncommitted changes."
        return output
    except subprocess.TimeoutExpired:
        return "Error: Git diff command timed out."
    except FileNotFoundError:
        return "Error: Git is not installed or not in PATH."
    except Exception as exc:
        return f"Error running git diff: {exc}"


async def run_command_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Run an approved shell command within the workspace root."""
    command = args.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return "Error: No command provided."

    work_dir = args.get("work_dir", str(settings.paths.workspace_root))
    safe = _safe_path(Path(work_dir), settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {work_dir!r} is outside workspace root"
    if not safe.exists():
        return f"Error: Working directory does not exist: {work_dir}"
    if not safe.is_dir():
        return f"Error: Working directory is not a directory: {work_dir}"

    try:
        timeout = _normalize_timeout(args.get("timeout"))
    except (TypeError, ValueError):
        return "Error: timeout must be an integer number of seconds."

    if not settings.safety.allow_destructive_commands:
        reason = _find_dangerous_command_reason(command)
        if reason:
            return (
                "Error: Command blocked by safety policy. "
                f"Detected {reason}. Set ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS=true "
                "to override explicitly."
            )

    try:
        shell_command = _resolve_command_shell()
        prepared_command = _prepare_shell_command(command)
        stdout, stderr, exit_code, timed_out = await _run_shell_command(
            [*shell_command, prepared_command],
            cwd=safe,
            timeout=timeout,
        )
    except asyncio.CancelledError:
        raise
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Error running command: {exc}"

    if timed_out:
        return _format_command_result(
            command=command,
            work_dir=safe,
            workspace_root=settings.paths.workspace_root,
            timeout=timeout,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=True,
        )

    return _format_command_result(
        command=command,
        work_dir=safe,
        workspace_root=settings.paths.workspace_root,
        timeout=timeout,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
    )


async def apply_patch_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Apply an approved unified diff patch within the workspace root."""
    patch_text = args.get("patch", "")
    if not isinstance(patch_text, str) or not patch_text.strip():
        return "Error: No patch provided."

    try:
        patch_paths = _extract_patch_paths(patch_text)
        safe_targets = _validate_patch_targets(
            patch_paths,
            settings.paths.workspace_root,
        )
    except ValueError as exc:
        return f"Error: {exc}"

    patch_file_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".patch",
            delete=False,
            encoding="utf-8",
        ) as patch_file:
            patch_file.write(patch_text)
            patch_file_path = Path(patch_file.name)

        check_result = _run_git_command(
            ["apply", "--check", "--recount", str(patch_file_path)],
            cwd=settings.paths.workspace_root,
        )
        if check_result.returncode != 0:
            return _format_subprocess_error("Patch validation failed.", check_result)

        apply_result = _run_git_command(
            ["apply", "--recount", str(patch_file_path)],
            cwd=settings.paths.workspace_root,
        )
        if apply_result.returncode != 0:
            return _format_subprocess_error("Failed to apply patch.", apply_result)
    except subprocess.TimeoutExpired:
        return "Error: Patch application timed out."
    except FileNotFoundError:
        return "Error: Git is not installed or not in PATH."
    except Exception as exc:
        return f"Error applying patch: {exc}"
    finally:
        if patch_file_path is not None:
            patch_file_path.unlink(missing_ok=True)

    changed_files = [_format_workspace_relative(path, settings.paths.workspace_root) for path in safe_targets]
    file_lines = "\n".join(f"  - {path}" for path in changed_files)
    return f"Patch applied successfully.\nChanged files:\n{file_lines}"


def get_tool_specs() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool specifications."""
    return [
        {
            "name": "list_files",
            "description": (
                "List files in a directory. Shows files and folders with "
                "optional pattern matching. Cannot escape workspace root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list (default: workspace root).",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files (default: *).",
                    },
                },
            },
        },
        {
            "name": "read_file",
            "description": (
                "Read a file with line numbers. Supports offset and limit for "
                "large files. Must read a file before editing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file to read.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-based, default: 1).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (default: 2000).",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "search_text",
            "description": (
                "Search for a regex pattern in files within the workspace. "
                "Returns matching lines with file paths and line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: workspace root).",
                    },
                    "type": {
                        "type": "string",
                        "description": "File type extension to filter by (e.g., 'py', 'js', 'md').",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 100).",
                    },
                },
                "required": ["pattern"],
            },
        },
        {
            "name": "git_status",
            "description": (
                "Show the current git status of the workspace, listing all modified, added, and deleted files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory for git command (default: workspace root).",
                    },
                },
            },
        },
        {
            "name": "git_diff",
            "description": ("Show uncommitted or staged changes. Use staged=true to see staged changes."),
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory for git command (default: workspace root).",
                    },
                    "path": {
                        "type": "string",
                        "description": "Specific file path to diff (relative to work_dir).",
                    },
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged changes instead of unstaged (default: false).",
                    },
                },
            },
        },
        {
            "name": "run_command",
            "description": (
                "Run an approved shell command inside the workspace root with "
                "timeouts, output limits, and dangerous-command blocking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute inside the workspace.",
                    },
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory for the command (default: workspace root).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": (
                            "Optional timeout in seconds "
                            f"(default: {DEFAULT_COMMAND_TIMEOUT_SECONDS}, max: {MAX_COMMAND_TIMEOUT_SECONDS})."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
        {
            "name": "apply_patch",
            "description": (
                "Apply a unified diff patch inside the workspace root. "
                "Use only after reading the target files and getting approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": ("Unified diff patch text using workspace-relative paths in the diff headers."),
                    },
                },
                "required": ["patch"],
            },
        },
    ]
