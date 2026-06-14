"""Tests for app.tools.repo_analyzer module."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppPaths, AppSettings
from app.tools.repo_analyzer import analyze_ml_repo_handler, build_repo_analysis, get_tool_specs


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def _write_minimal_repo(root: Path) -> None:
    (root / "app" / "api").mkdir(parents=True)
    (root / "app" / "storage").mkdir(parents=True)
    (root / "app" / "tools").mkdir(parents=True)
    (root / "app" / "evals").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "scripts").mkdir()
    (root / "tests" / "unit").mkdir(parents=True)

    (root / "pyproject.toml").write_text(
        """
[project]
name = "sample-repo"
dependencies = [
    "fastapi>=0.121.0,<0.122.0",
    "httpx>=0.28.0,<0.29.0",
    "whoosh>=2.7.4,<3.0.0",
    "beautifulsoup4>=4.12.0,<5.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0,<9.0.0",
    "ruff>=0.11.0,<0.12.0",
]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Sample Repo\n", encoding="utf-8")
    (root / "app" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "app" / "api" / "app.py").write_text("", encoding="utf-8")
    (root / "app" / "storage" / "repository.py").write_text("", encoding="utf-8")
    (root / "app" / "tools" / "datasets.py").write_text("", encoding="utf-8")
    (root / "app" / "tools" / "docs.py").write_text("", encoding="utf-8")
    (root / "app" / "tools" / "papers.py").write_text("", encoding="utf-8")
    (root / "app" / "evals" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "unit" / "test_sample.py").write_text("", encoding="utf-8")


def test_build_repo_analysis_detects_expected_gaps(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)

    analysis = build_repo_analysis(tmp_path)

    assert analysis.repo_name == tmp_path.name
    assert "fastapi" in analysis.core_dependencies
    assert "app/tools/datasets.py" in analysis.data_pipeline_files
    assert analysis.training_files == []
    assert analysis.eval_files == []
    assert any("uv.lock" in gap for gap in analysis.reproducibility_gaps)


@pytest.mark.asyncio
async def test_analyze_ml_repo_handler_formats_report(tmp_path: Path) -> None:
    _write_minimal_repo(tmp_path)
    result = await analyze_ml_repo_handler({}, _settings(tmp_path))

    assert "ML Repo Analysis" in result
    assert "FastAPI backend" in result
    assert "app/tools/datasets.py" in result
    assert "No training entrypoint was found" in result
    assert "No standalone eval runner was found" in result
    assert "No `uv.lock`" in result


@pytest.mark.asyncio
async def test_analyze_ml_repo_handler_rejects_outside_workspace(tmp_path: Path) -> None:
    result = await analyze_ml_repo_handler({"path": "../../etc"}, _settings(tmp_path))

    assert "outside workspace root" in result.lower()


def test_get_tool_specs() -> None:
    specs = get_tool_specs()

    assert len(specs) == 1
    assert specs[0]["name"] == "analyze_ml_repo"
    assert "path" in specs[0]["parameters"]["properties"]
