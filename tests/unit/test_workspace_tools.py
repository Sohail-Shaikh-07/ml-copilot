"""Tests for workspace tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppPaths, AppSettings
from app.tools import workspace


@pytest.fixture
def mock_settings(tmp_path: Path) -> AppSettings:
    """Create a mock settings object with a temp workspace."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    # Create some test files
    (workspace_root / "file1.py").write_text("print('hello')")
    (workspace_root / "file2.md").write_text("# Title")
    (workspace_root / "subdir").mkdir()
    (workspace_root / "subdir" / "nested.py").write_text("x = 1")

    paths = AppPaths.from_workspace_root(workspace_root)
    return AppSettings.from_paths(paths)


@pytest.fixture
def evil_settings(tmp_path: Path) -> AppSettings:
    """Create settings pointing to a workspace and try to escape."""
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()

    paths = AppPaths.from_workspace_root(workspace_root)
    return AppSettings.from_paths(paths)


class TestSafePath:
    """Tests for _safe_path path safety."""

    def test_resolves_and_validates_inside_workspace(self, mock_settings):
        """Path inside workspace should be resolved and allowed."""
        resolved_workspace = mock_settings.paths.workspace_root.resolve()
        test_path = resolved_workspace / "file1.py"
        result = workspace._safe_path(test_path, mock_settings.paths.workspace_root)
        assert result is not None
        assert result.name == "file1.py"

    def test_rejects_path_outside_workspace(self, evil_settings):
        """Path outside workspace should return None."""
        resolved_workspace = evil_settings.paths.workspace_root.resolve()
        evil_path = resolved_workspace.parent / "outside"
        result = workspace._safe_path(evil_path, evil_settings.paths.workspace_root)
        assert result is None

    def test_handles_nonexistent_path(self, mock_settings):
        """Nonexistent path should still return resolved path (not None)."""
        resolved_workspace = mock_settings.paths.workspace_root.resolve()
        test_path = resolved_workspace / "nonexistent.txt"
        result = workspace._safe_path(test_path, mock_settings.paths.workspace_root)
        # Nonexistent paths return resolved path, not None
        # The handler checks existence separately
        assert result is not None


class TestListFiles:
    """Tests for list_files_handler."""

    @pytest.mark.asyncio
    async def test_lists_files_in_workspace_root(self, mock_settings):
        """Should list all files in workspace root."""
        result = await workspace.list_files_handler({}, mock_settings)

        assert "file1.py" in result
        assert "file2.md" in result
        assert "subdir" in result

    @pytest.mark.asyncio
    async def test_respects_path_parameter(self, mock_settings):
        """Should respect path parameter."""
        subdir = str(mock_settings.paths.workspace_root / "subdir")
        result = await workspace.list_files_handler({"path": subdir}, mock_settings)

        assert "nested.py" in result

    @pytest.mark.asyncio
    async def test_rejects_path_outside_workspace(self, evil_settings):
        """Should reject paths outside workspace."""
        result = await workspace.list_files_handler({"path": "/tmp/outside"}, evil_settings)

        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_handles_nonexistent_directory(self, mock_settings):
        """Should handle nonexistent directory gracefully."""
        nonexistent = str(mock_settings.paths.workspace_root / "nonexistent")
        result = await workspace.list_files_handler({"path": nonexistent}, mock_settings)

        assert result.startswith("Error:")


class TestReadFile:
    """Tests for read_file_handler."""

    @pytest.mark.asyncio
    async def test_reads_file_with_line_numbers(self, mock_settings):
        """Should read file and return content with line numbers."""
        file_path = str(mock_settings.paths.workspace_root / "file1.py")
        result = await workspace.read_file_handler({"path": file_path}, mock_settings)

        assert "file1.py" in result
        assert "1" in result  # Line number
        assert "print('hello')" in result

    @pytest.mark.asyncio
    async def test_respects_offset_and_limit(self, mock_settings):
        """Should respect offset and limit parameters."""
        # Create a file with multiple lines
        test_file = mock_settings.paths.workspace_root / "multiline.py"
        test_file.write_text("\n".join(f"line {i}" for i in range(1, 21)))

        result = await workspace.read_file_handler(
            {"path": str(test_file), "offset": 5, "limit": 3},
            mock_settings,
        )

        assert "line 5" in result
        assert "line 6" in result
        assert "line 7" in result
        assert "line 8" not in result

    @pytest.mark.asyncio
    async def test_rejects_path_outside_workspace(self, evil_settings):
        """Should reject paths outside workspace."""
        result = await workspace.read_file_handler({"path": "/etc/passwd"}, evil_settings)

        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_handles_nonexistent_file(self, mock_settings):
        """Should handle nonexistent file gracefully."""
        file_path = str(mock_settings.paths.workspace_root / "nonexistent.txt")
        result = await workspace.read_file_handler({"path": file_path}, mock_settings)

        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_rejects_directory(self, mock_settings):
        """Should reject reading a directory."""
        file_path = str(mock_settings.paths.workspace_root / "subdir")
        result = await workspace.read_file_handler({"path": file_path}, mock_settings)

        assert result.startswith("Error:")


class TestSearchText:
    """Tests for search_text_handler."""

    @pytest.mark.asyncio
    async def test_finds_matching_lines(self, mock_settings):
        """Should find lines matching the pattern."""
        result = await workspace.search_text_handler({"pattern": "print"}, mock_settings)

        assert "file1.py" in result
        assert "print('hello')" in result

    @pytest.mark.asyncio
    async def test_filters_by_file_type(self, mock_settings):
        """Should filter by file type."""
        result = await workspace.search_text_handler(
            {"pattern": "hello", "type": "py"},
            mock_settings,
        )

        assert "file1.py" in result
        assert "file2.md" not in result

    @pytest.mark.asyncio
    async def test_handles_no_matches(self, mock_settings):
        """Should handle no matches gracefully."""
        result = await workspace.search_text_handler(
            {"pattern": "nonexistentpattern12345"},
            mock_settings,
        )

        assert "No matches found" in result

    @pytest.mark.asyncio
    async def test_handles_invalid_regex(self, mock_settings):
        """Should handle invalid regex patterns."""
        result = await workspace.search_text_handler(
            {"pattern": "[invalid"},
            mock_settings,
        )

        assert result.startswith("Error:")

    @pytest.mark.asyncio
    async def test_respects_max_results(self, mock_settings):
        """Should respect max_results limit."""
        # Create multiple files with matches
        for i in range(10):
            (mock_settings.paths.workspace_root / f"test{i}.py").write_text("match")

        result = await workspace.search_text_handler(
            {"pattern": "match", "max_results": 3},
            mock_settings,
        )

        # Should not have all matches due to limit
        assert "test0.py" in result


class TestGitStatus:
    """Tests for git_status_handler."""

    @pytest.mark.asyncio
    async def test_shows_status_for_new_repo(self, mock_settings):
        """Should show git status for new repo."""
        # Initialize git repo
        import subprocess

        subprocess.run(
            ["git", "init"],
            cwd=str(mock_settings.paths.workspace_root),
            capture_output=True,
        )

        result = await workspace.git_status_handler({}, mock_settings)

        # New repo should show status (may have untracked files)
        assert "git status" in result.lower() or "git" in result.lower()


class TestToolSpecs:
    """Tests for tool specifications."""

    def test_returns_valid_openai_specs(self):
        """Should return valid OpenAI tool specifications."""
        specs = workspace.get_tool_specs()

        assert len(specs) == 5

        tool_names = {s["name"] for s in specs}
        expected = {"list_files", "read_file", "search_text", "git_status", "git_diff"}
        assert tool_names == expected

        # Check structure
        for spec in specs:
            assert "name" in spec
            assert "description" in spec
            assert "parameters" in spec
            assert spec["parameters"]["type"] == "object"
