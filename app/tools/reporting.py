"""Git status and diff reporting for agent reports and PR descriptions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.tools.workspace import _run_git_command, _safe_path

MAX_DIFF_CHARS = 8000


def _gather_status(workspace_root: Path) -> list[str]:
    """Return porcelain status lines for the workspace."""
    try:
        result = _run_git_command(["status", "--porcelain"], cwd=workspace_root)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _gather_diff(workspace_root: Path, staged: bool = False) -> str:
    """Return diff text for the workspace, truncated if too large."""
    try:
        args = ["diff", "--stat"]
        if staged:
            args.append("--staged")
        stat_result = _run_git_command(args, cwd=workspace_root)

        args_full = ["diff"]
        if staged:
            args_full.append("--staged")
        full_result = _run_git_command(args_full, cwd=workspace_root)

        stat_text = stat_result.stdout.strip() if stat_result.returncode == 0 else ""
        full_text = full_result.stdout.strip() if full_result.returncode == 0 else ""

        if len(full_text) > MAX_DIFF_CHARS:
            full_text = full_text[:MAX_DIFF_CHARS] + "\n... [diff truncated]"

        return f"{stat_text}\n\n{full_text}".strip() if stat_text else full_text
    except Exception:
        return ""


def _gather_branch(workspace_root: Path) -> str:
    """Return the current branch name."""
    try:
        result = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace_root)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def format_git_report(workspace_root: Path) -> str:
    """Format a complete git report section as Markdown.

    Combines branch, status, and diff information into a structured
    report section suitable for final agent reports and PR descriptions.
    """
    branch = _gather_branch(workspace_root)
    status_lines = _gather_status(workspace_root)
    unstaged_diff = _gather_diff(workspace_root, staged=False)
    staged_diff = _gather_diff(workspace_root, staged=True)

    sections: list[str] = ["## Git Changes"]

    if branch:
        sections.append(f"\n**Branch:** `{branch}`")

    if not status_lines and not unstaged_diff and not staged_diff:
        sections.append("\nWorking tree is clean — no uncommitted changes.")
        return "\n".join(sections)

    if status_lines:
        sections.append("\n### Modified Files")
        sections.append("")
        for line in status_lines:
            sections.append(f"- `{line.strip()}`")

    if staged_diff:
        sections.append("\n### Staged Changes")
        sections.append(f"\n```diff\n{staged_diff}\n```")

    if unstaged_diff:
        sections.append("\n### Unstaged Changes")
        sections.append(f"\n```diff\n{unstaged_diff}\n```")

    return "\n".join(sections)


async def git_report_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Tool handler: generate a formatted git changes report."""
    work_dir = args.get("work_dir", str(settings.paths.workspace_root))
    safe = _safe_path(Path(work_dir), settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {work_dir!r} is outside workspace root"

    return format_git_report(safe)


def get_tool_specs() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool specifications for reporting tools."""
    return [
        {
            "name": "git_report",
            "description": (
                "Generate a formatted Markdown report of current git changes "
                "including branch, modified files, staged and unstaged diffs. "
                "Use this to summarize repository state for reports or PR descriptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "work_dir": {
                        "type": "string",
                        "description": "Working directory (default: workspace root).",
                    },
                },
            },
        },
    ]
