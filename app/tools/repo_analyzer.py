"""ML repo analyzer helper for summarizing a workspace."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.tools.workspace import _safe_path

IGNORED_DIRS = {
    ".git",
    ".kiro",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
}

TRAINING_HINTS = ("train", "finetune", "fine_tune", "sft", "dpo", "grpo")
EVAL_HINTS = ("eval", "benchmark", "score", "leaderboard")
DATA_HINTS = ("dataset", "datasets", "data", "pipeline", "preprocess", "loader")
ML_RUNTIME_DEPS = ("torch", "transformers", "datasets", "trl", "accelerate", "peft")
MAX_SECTION_ITEMS = 8


@dataclass(frozen=True)
class RepoAnalysisResult:
    """Structured summary of an ML repo."""

    root: Path
    repo_name: str
    top_level_dirs: list[str]
    core_files: list[str]
    core_dependencies: list[str]
    dev_dependencies: list[str]
    framework_summary: list[str]
    data_pipeline_files: list[str]
    training_files: list[str]
    eval_files: list[str]
    reproducibility_gaps: list[str]


def _dependency_name(spec: str) -> str:
    """Extract the import/package name from a dependency specifier."""
    return re.split(r"[<>=\[\s]", spec, maxsplit=1)[0].strip().lower()


def _walk_files(root: Path) -> list[Path]:
    """Return all non-ignored files under a repository root."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        for filename in filenames:
            files.append(Path(dirpath) / filename)
    return sorted(files)


def _relative_paths(root: Path, files: list[Path]) -> list[str]:
    return [path.relative_to(root).as_posix() for path in files]


def _filter_paths(paths: list[str], hints: tuple[str, ...]) -> list[str]:
    matched: list[str] = []
    for path in paths:
        lower = path.lower()
        if any(hint in lower for hint in hints):
            matched.append(path)
    return matched


def _find_top_level_dirs(root: Path) -> list[str]:
    dirs = []
    for item in sorted(root.iterdir()):
        if item.is_dir() and item.name not in IGNORED_DIRS:
            dirs.append(item.name)
    return dirs


def _parse_pyproject(root: Path) -> tuple[list[str], list[str]]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return [], []

    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return [], []

    project = data.get("project", {})
    core = [_dependency_name(dep) for dep in project.get("dependencies", []) if isinstance(dep, str) and dep.strip()]
    dev = [
        _dependency_name(dep)
        for dep in project.get("optional-dependencies", {}).get("dev", [])
        if isinstance(dep, str) and dep.strip()
    ]

    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    return _dedupe(core), _dedupe(dev)


def _infer_framework_summary(core_dependencies: list[str], repo_files: list[str]) -> list[str]:
    summary = [
        "Python package with FastAPI backend endpoints and an OpenAI-compatible agent loop.",
        "SQLite-backed session, message, event, and approval persistence.",
        "Tooling stack for workspace, reporting, dataset inspection, docs, and paper analysis.",
    ]

    if "fastapi" in core_dependencies:
        summary.append("FastAPI is the main web framework.")
    if "httpx" in core_dependencies:
        summary.append("httpx handles external API calls and fetches.")
    if "whoosh" in core_dependencies and "beautifulsoup4" in core_dependencies:
        summary.append("Whoosh + BeautifulSoup4 power the docs search/fetch helper.")

    if any(path.endswith("app/tools/datasets.py") for path in repo_files):
        summary.append("Dataset inspection lives in the tools layer rather than a training pipeline.")

    if not any(dep in core_dependencies for dep in ML_RUNTIME_DEPS):
        summary.append("No ML training runtime libraries are declared yet.")

    return summary


def _find_training_files(repo_files: list[str]) -> list[str]:
    candidates = []
    for path in repo_files:
        lower = path.lower()
        if not lower.endswith(".py"):
            continue
        if "/tests/" in lower or lower.startswith("tests/"):
            continue
        if any(hint in lower for hint in TRAINING_HINTS):
            candidates.append(path)
    return candidates[:MAX_SECTION_ITEMS]


def _find_eval_files(repo_files: list[str]) -> list[str]:
    candidates = []
    for path in repo_files:
        lower = path.lower()
        if not lower.endswith(".py"):
            continue
        if "/tests/" in lower or lower.startswith("tests/"):
            continue
        if lower.endswith("app/evals/__init__.py") or lower.endswith("app\\evals\\__init__.py"):
            continue
        if lower.startswith("app/evals/") and not lower.endswith("__init__.py"):
            candidates.append(path)
            continue
        if any(hint in lower for hint in EVAL_HINTS):
            candidates.append(path)
    return candidates[:MAX_SECTION_ITEMS]


def _find_data_pipeline_files(repo_files: list[str]) -> list[str]:
    candidates = []
    for path in repo_files:
        lower = path.lower()
        if not lower.endswith(".py"):
            continue
        if "datasets.py" in lower:
            candidates.append(path)
            continue
        if "/tests/" in lower or lower.startswith("tests/"):
            continue
        if any(hint in lower for hint in DATA_HINTS):
            candidates.append(path)
    return candidates[:MAX_SECTION_ITEMS]


def _missing_reproducibility_gaps(
    root: Path,
    core_dependencies: list[str],
    training_files: list[str],
    eval_files: list[str],
) -> list[str]:
    gaps = []

    if not (root / "uv.lock").exists():
        gaps.append("No `uv.lock` is checked in, so dependency resolution is not fully pinned.")

    if not training_files:
        gaps.append("No training entrypoint was found, so there is no executable training pipeline yet.")

    if not eval_files:
        gaps.append("No standalone eval runner was found under `app/evals/` or `scripts/`.")

    if not any(dep in core_dependencies for dep in ML_RUNTIME_DEPS):
        gaps.append("No ML runtime dependencies such as `torch`, `transformers`, `trl`, or `accelerate` are declared.")

    if not any(path.endswith(".seed") or "seed" in path.lower() for path in _relative_paths(root, _walk_files(root))):
        gaps.append("No obvious seed/config convention was found for reproducible experiments.")

    return gaps[:MAX_SECTION_ITEMS]


def build_repo_analysis(root: Path, max_items: int = MAX_SECTION_ITEMS) -> RepoAnalysisResult:
    """Build a structured analysis for the repository rooted at `root`."""
    repo_files = _relative_paths(root, _walk_files(root))
    core_dependencies, dev_dependencies = _parse_pyproject(root)

    top_level_dirs = _find_top_level_dirs(root)[:max_items]
    core_files = [
        path
        for path in (
            "README.md",
            "pyproject.toml",
            "app/main.py",
            "app/agent/loop.py",
            "app/api/app.py",
            "app/storage/repository.py",
            "app/tools/datasets.py",
            "app/tools/docs.py",
            "app/tools/papers.py",
        )
        if path in repo_files
    ]

    training_files = _find_training_files(repo_files)
    eval_files = _find_eval_files(repo_files)
    data_pipeline_files = _find_data_pipeline_files(repo_files)
    reproducibility_gaps = _missing_reproducibility_gaps(
        root,
        core_dependencies,
        training_files,
        eval_files,
    )

    return RepoAnalysisResult(
        root=root,
        repo_name=root.name,
        top_level_dirs=top_level_dirs,
        core_files=core_files[:max_items],
        core_dependencies=core_dependencies[:max_items],
        dev_dependencies=dev_dependencies[:max_items],
        framework_summary=_infer_framework_summary(core_dependencies, repo_files)[:max_items],
        data_pipeline_files=data_pipeline_files,
        training_files=training_files,
        eval_files=eval_files,
        reproducibility_gaps=reproducibility_gaps,
    )


def _format_section(title: str, items: list[str], empty_message: str) -> list[str]:
    lines = [f"## {title}"]
    if not items:
        lines.append(f"- {empty_message}")
        return lines

    for item in items:
        lines.append(f"- `{item}`")
    return lines


def _format_repo_analysis(result: RepoAnalysisResult) -> str:
    lines = [f"# ML Repo Analysis: {result.repo_name}"]
    lines.append(f"**Root:** `{result.root}`")
    lines.append("")
    lines.append(
        "This is an inference from the current workspace layout: the repo is a backend agent scaffold, "
        "not a training-first ML project yet."
    )
    lines.append("")

    lines.extend(_format_section("Repository Shape", result.top_level_dirs, "No top-level directories found."))
    lines.append("")
    lines.extend(_format_section("Core Files", result.core_files, "No key files matched."))
    lines.append("")
    lines.extend(_format_section("Framework", result.framework_summary, "No framework signals found."))
    lines.append("")
    lines.extend(
        _format_section(
            "Data Pipeline",
            result.data_pipeline_files,
            "No dedicated data pipeline scripts were found.",
        )
    )
    lines.append("")
    lines.extend(
        _format_section(
            "Training Scripts",
            result.training_files,
            "No training entrypoint was found.",
        )
    )
    lines.append("")
    lines.extend(
        _format_section(
            "Eval Scripts",
            result.eval_files,
            "No standalone eval runner was found.",
        )
    )
    lines.append("")
    lines.append("## Dependencies")
    lines.append(f"- **Core:** {', '.join(result.core_dependencies) if result.core_dependencies else 'none declared'}")
    lines.append(f"- **Dev:** {', '.join(result.dev_dependencies) if result.dev_dependencies else 'none declared'}")
    lines.append("")
    lines.extend(
        _format_section(
            "Reproducibility Gaps",
            result.reproducibility_gaps,
            "No obvious gaps detected.",
        )
    )
    return "\n".join(lines)


async def analyze_ml_repo_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Analyze the current ML repository and summarize the implementation shape."""
    target = args.get("path") or str(settings.paths.workspace_root)
    max_items = args.get("max_items", MAX_SECTION_ITEMS)

    try:
        max_items = max(1, min(int(max_items), 20))
    except (TypeError, ValueError):
        return "Error: max_items must be an integer."

    safe = _safe_path(Path(target), settings.paths.workspace_root)
    if safe is None:
        return f"Error: Path {target!r} is outside workspace root."
    if not safe.exists():
        return f"Error: Path not found: {target}"
    if not safe.is_dir():
        return f"Error: Path is not a directory: {target}"

    result = build_repo_analysis(safe, max_items=max_items)
    return _format_repo_analysis(result)


def get_tool_specs() -> list[dict[str, Any]]:
    """Return the tool specification for the ML repo analyzer helper."""
    return [
        {
            "name": "analyze_ml_repo",
            "description": (
                "Analyze a workspace or repository and summarize the framework, data pipeline, "
                "training scripts, eval scripts, dependencies, and reproducibility gaps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional workspace-relative path to analyze (default: workspace root).",
                    },
                    "max_items": {
                        "type": "integer",
                        "description": "Maximum items to list in each section (default: 8).",
                    },
                },
            },
        }
    ]
