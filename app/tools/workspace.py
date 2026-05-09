"""Read-only workspace tools: list files, read file, search text, git status, git diff."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.config import AppSettings

MAX_READ_LINES = 2000
MAX_LINE_LENGTH = 4000
MAX_OUTPUT_LINES = 500


def _safe_path(path: Path, workspace_root: Path) -> Path | None:
    """Resolve path and ensure it stays within workspace root. Returns None if unsafe."""
    try:
        resolved = path.resolve()
        # Normalize the path comparison - make sure both are absolute and resolved
        try:
            resolved.relative_to(workspace_root.resolve())
            return resolved
        except ValueError:
            # Path is outside workspace_root
            return None
    except (OSError, RuntimeError):
        return None


def _format_lines(lines: list[str], offset: int = 1) -> list[str]:
    """Add line numbers to lines."""
    result = []
    for i, line in enumerate(lines, start=offset):
        if len(line) > MAX_LINE_LENGTH:
            line = line[:MAX_LINE_LENGTH] + f"... [truncated {len(line) - MAX_LINE_LENGTH} chars]"
        result.append(f"{i:>6}\t{line}")
    return result


# ── Tool Handlers ──────────────────────────────────────────────────────────────


async def list_files_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """List files in workspace, optionally matching a pattern."""
    dir_path = args.get("path", str(settings.paths.workspace_root))
    pattern = args.get("pattern", "*")

    base = Path(dir_path)
    safe = _safe_path(base, settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {dir_path!r} is outside workspace root {settings.paths.workspace_root}"

    if not safe.exists():
        return f"Error: Directory does not exist: {dir_path}"

    if not safe.is_dir():
        return f"Error: Not a directory: {dir_path}"

    try:
        files = sorted(
            f.name for f in safe.iterdir() if re.match(pattern.replace("*", ".*"), f.name)
        )
    except re.error as e:
        return f"Error: Invalid pattern {pattern!r}: {e}"

    if not files:
        return f"No files matching {pattern!r} in {dir_path}"

    output_lines = [f"Contents of {safe.relative_to(settings.paths.workspace_root)} ({len(files)} items):"]
    for f in files[:MAX_OUTPUT_LINES]:
        full_path = safe / f
        marker = "/" if full_path.is_dir() else ""
        output_lines.append(f"  {f}{marker}")
    if len(files) > MAX_OUTPUT_LINES:
        output_lines.append(f"  ... and {len(files) - MAX_OUTPUT_LINES} more files")
    return "\n".join(output_lines)


async def read_file_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Read a file with line numbers, supporting offset and limit."""
    file_path = args.get("path", "")
    if not file_path:
        return "Error: No path provided."

    path = Path(file_path)
    safe = _safe_path(path, settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {file_path!r} is outside workspace root {settings.paths.workspace_root}"

    if not safe.exists():
        return f"Error: File not found: {file_path}"

    if safe.is_dir():
        return "Error: Cannot read a directory. Use list_files instead."

    try:
        content = safe.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    lines = content.splitlines()
    total_lines = len(lines)

    # Parse offset (1-based) and limit
    offset = max(args.get("offset", 1), 1)
    limit = args.get("limit", MAX_READ_LINES)

    # Adjust for file boundaries
    offset = min(offset, total_lines)
    if offset < 1:
        offset = 1

    # Get the selected lines (offset is 1-based in user API)
    start_idx = offset - 1
    end_idx = min(start_idx + limit, total_lines)
    selected = lines[start_idx:end_idx]

    numbered = _format_lines(selected, offset=offset)

    header = f"--- {safe.relative_to(settings.paths.workspace_root)} ({total_lines} lines total, showing {offset}-{end_idx}) ---"
    footer = "--- End of file ---"

    if len(numbered) < MAX_OUTPUT_LINES:
        return header + "\n" + "\n".join(numbered) + "\n" + footer
    else:
        return header + "\n" + "\n".join(numbered[:MAX_OUTPUT_LINES]) + f"\n... [{len(numbered) - MAX_OUTPUT_LINES} more lines] ...\n" + footer


async def search_text_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Search for text pattern in files using regex."""
    pattern = args.get("pattern", "")
    if not pattern:
        return "Error: No pattern provided."

    path_filter = args.get("path", None)
    file_type = args.get("type", None)
    max_results = args.get("max_results", 100)

    if path_filter:
        base = Path(path_filter)
        safe = _safe_path(base, settings.paths.workspace_root)
        if safe is None:
            return f"Error: Path {path_filter!r} is outside workspace root"
    else:
        safe = settings.paths.workspace_root

    if not safe.exists():
        return f"Error: Search path does not exist: {path_filter or 'workspace'}"

    # Build file extension filter if provided
    extension_filter = None
    if file_type:
        # Common file type mappings
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
        extension_filter = type_map.get(file_type.lower(), f".{file_type.lower()}")

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern {pattern!r}: {e}"

    matches: list[str] = []
    count = 0

    def _search_dir(dir_path: Path) -> None:
        nonlocal count
        if count >= max_results:
            return
        try:
            for item in dir_path.iterdir():
                if count >= max_results:
                    return
                # Skip hidden files and common ignore patterns
                if item.name.startswith("."):
                    continue
                if item.name in {".git", "__pycache__", "node_modules", ".pytest_cache"}:
                    continue

                if item.is_dir():
                    _search_dir(item)
                elif item.is_file():
                    # Apply extension filter if set
                    if extension_filter and not item.suffix.lower() == extension_filter:
                        continue

                    try:
                        # Read file in small chunks to find matches
                        content = item.read_text(encoding="utf-8", errors="replace")
                        lines = content.splitlines()
                        for line_num, line in enumerate(lines, start=1):
                            if regex.search(line):
                                rel_path = item.relative_to(settings.paths.workspace_root)
                                # Truncate long lines
                                display_line = line[:200] + ("..." if len(line) > 200 else "")
                                matches.append(f"{rel_path}:{line_num}: {display_line}")
                                count += 1
                                if count >= max_results:
                                    return
                    except (OSError, UnicodeDecodeError):
                        continue
        except PermissionError:
            pass

    _search_dir(safe)

    if not matches:
        return f"No matches found for pattern {pattern!r}"

    output = [f"Found {len(matches)} matches for {pattern!r}:"]
    output.extend(matches)
    return "\n".join(output)


async def git_status_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Show git status of the workspace."""
    work_dir = args.get("work_dir", str(settings.paths.workspace_root))
    base = Path(work_dir)
    safe = _safe_path(base, settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {work_dir!r} is outside workspace root"

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(safe),
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        if not output:
            return "Git working tree is clean."
        return "Git status:\n" + output
    except subprocess.TimeoutExpired:
        return "Error: Git status command timed out."
    except FileNotFoundError:
        return "Error: Git is not installed or not in PATH."
    except Exception as e:
        return f"Error running git status: {e}"


async def git_diff_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Show git diff of the workspace."""
    work_dir = args.get("work_dir", str(settings.paths.workspace_root))
    file_path = args.get("path", None)
    staged = args.get("staged", False)

    base = Path(work_dir)
    safe = _safe_path(base, settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {work_dir!r} is outside workspace root"

    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")
    if file_path:
        # Validate the file path is within workspace
        file_full = (safe / file_path).resolve()
        if _safe_path(file_full, settings.paths.workspace_root) is None:
            return f"Error: File path {file_path!r} is outside workspace root"
        cmd.append("--")
        cmd.append(file_path)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(safe),
            capture_output=True,
            text=True,
            timeout=30,
        )
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
    except Exception as e:
        return f"Error running git diff: {e}"


# ── Tool Specifications ──────────────────────────────────────────────────────────


def get_tool_specs() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool specifications."""
    return [
        {
            "name": "list_files",
            "description": "List files in a directory. Shows files and folders with optional pattern matching. Cannot escape workspace root.",
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
            "description": "Read a file with line numbers. Supports offset and limit for large files. Must read a file before editing it.",
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
            "description": "Search for a regex pattern in files within the workspace. Returns matching lines with file paths and line numbers.",
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
            "description": "Show the current git status of the workspace, listing all modified, added, and deleted files.",
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
            "description": "Show uncommitted or staged changes. Use staged=true to see staged changes.",
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
    ]
