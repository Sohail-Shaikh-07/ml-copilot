"""Tests for app.tools.reporting module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.reporting import (
    MAX_DIFF_CHARS,
    _gather_branch,
    _gather_diff,
    _gather_status,
    format_git_report,
    get_tool_specs,
    git_report_handler,
)


def _make_completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestGatherStatus:
    def test_returns_lines(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.return_value = _make_completed("M  file.py\nA  new.py\n")
            lines = _gather_status(tmp_path)
        assert lines == ["M  file.py", "A  new.py"]

    def test_clean_repo(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.return_value = _make_completed("")
            lines = _gather_status(tmp_path)
        assert lines == []

    def test_git_failure(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.return_value = _make_completed("", returncode=128)
            lines = _gather_status(tmp_path)
        assert lines == []

    def test_exception(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command", side_effect=FileNotFoundError):
            lines = _gather_status(tmp_path)
        assert lines == []


class TestGatherDiff:
    def test_returns_diff(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.side_effect = [
                _make_completed(" file.py | 2 +-"),
                _make_completed("-old\n+new"),
            ]
            result = _gather_diff(tmp_path)
        assert "file.py" in result
        assert "+new" in result

    def test_empty_diff(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.side_effect = [_make_completed(""), _make_completed("")]
            result = _gather_diff(tmp_path)
        assert result == ""

    def test_truncates_large_diff(self, tmp_path: Path) -> None:
        large = "x" * (MAX_DIFF_CHARS + 500)
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.side_effect = [_make_completed(""), _make_completed(large)]
            result = _gather_diff(tmp_path)
        assert "[diff truncated]" in result
        assert len(result) < MAX_DIFF_CHARS + 100

    def test_exception(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command", side_effect=OSError):
            result = _gather_diff(tmp_path)
        assert result == ""


class TestGatherBranch:
    def test_returns_branch(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.return_value = _make_completed("feature/test\n")
            assert _gather_branch(tmp_path) == "feature/test"

    def test_failure(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._run_git_command") as mock:
            mock.return_value = _make_completed("", returncode=128)
            assert _gather_branch(tmp_path) == ""


class TestFormatGitReport:
    def test_clean_workspace(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._gather_branch", return_value="main"):
            with patch("app.tools.reporting._gather_status", return_value=[]):
                with patch("app.tools.reporting._gather_diff", return_value=""):
                    report = format_git_report(tmp_path)
        assert "## Git Changes" in report
        assert "clean" in report
        assert "`main`" in report

    def test_with_changes(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._gather_branch", return_value="feature/x"):
            with patch("app.tools.reporting._gather_status", return_value=["M file.py"]):
                with patch("app.tools.reporting._gather_diff", side_effect=["unstaged-diff", ""]):
                    report = format_git_report(tmp_path)
        assert "## Git Changes" in report
        assert "`feature/x`" in report
        assert "### Modified Files" in report
        assert "`M file.py`" in report
        assert "### Unstaged Changes" in report
        assert "unstaged-diff" in report

    def test_staged_only(self, tmp_path: Path) -> None:
        with patch("app.tools.reporting._gather_branch", return_value="main"):
            with patch("app.tools.reporting._gather_status", return_value=["A new.py"]):
                with patch("app.tools.reporting._gather_diff", side_effect=["", "staged-diff"]):
                    report = format_git_report(tmp_path)
        assert "### Staged Changes" in report
        assert "staged-diff" in report
        assert "### Unstaged Changes" not in report


class TestGitReportHandler:
    @pytest.mark.asyncio
    async def test_default_workspace(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        with patch("app.tools.reporting.format_git_report", return_value="## Git Changes\nclean"):
            result = await git_report_handler({}, settings)
        assert "Git Changes" in result

    @pytest.mark.asyncio
    async def test_workspace_escape(self, tmp_path: Path) -> None:
        settings = _make_settings(tmp_path)
        result = await git_report_handler({"work_dir": "/etc/secrets"}, settings)
        assert "Error" in result
        assert "outside workspace" in result


class TestGetToolSpecs:
    def test_returns_git_report(self) -> None:
        specs = get_tool_specs()
        assert len(specs) == 1
        assert specs[0]["name"] == "git_report"
        assert "parameters" in specs[0]


def _make_settings(workspace_root: Path):
    """Create minimal AppSettings for testing."""
    from app.config import AppPaths, AppSettings

    return AppSettings.from_paths(AppPaths.from_workspace_root(workspace_root))
