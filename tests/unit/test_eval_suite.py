"""Tests for running eval fixtures as a suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppPaths, AppSettings
from app.evals.runner import EvalFixture
from app.evals.suite import EvalSuiteRunner, discover_fixture_paths
from app.storage.models import SessionRecord
from app.storage.repository import SQLiteRepository


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def _write_fixture(path: Path, fixture_id: str, expected: str) -> None:
    path.write_text(
        json.dumps(
            {
                "id": fixture_id,
                "prompt": f"Complete {fixture_id}",
                "checks": [{"type": "contains", "value": expected}],
            }
        ),
        encoding="utf-8",
    )


def test_discover_fixture_paths_returns_sorted_json_files(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    _write_fixture(fixture_dir / "b.json", "b", "ok")
    _write_fixture(fixture_dir / "a.json", "a", "ok")
    (fixture_dir / "notes.md").write_text("ignore me", encoding="utf-8")

    paths = discover_fixture_paths(fixture_dir)

    assert [path.name for path in paths] == ["a.json", "b.json"]


def test_discover_fixture_paths_rejects_empty_directories(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()

    with pytest.raises(ValueError, match="No eval fixture JSON files"):
        discover_fixture_paths(fixture_dir)


@pytest.mark.asyncio
async def test_eval_suite_runner_writes_aggregate_reports(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = SQLiteRepository(settings.db_path)
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    _write_fixture(fixture_dir / "first.json", "fixture-pass", "ok")
    _write_fixture(fixture_dir / "second.json", "fixture-fail", "missing")

    async def fake_agent(
        fixture: EvalFixture,
        _workspace_path: Path,
        _settings: AppSettings,
        _session: SessionRecord,
    ) -> dict[str, object]:
        content = "ok" if fixture.id == "fixture-pass" else "not enough"
        return {"content": content, "usage": {"total_tokens": 3}}

    result = await EvalSuiteRunner(settings, repository=repository, agent_runner=fake_agent).run_path(
        fixture_dir,
        output_dir=tmp_path / "eval-output",
    )

    assert result.status == "failed"
    assert result.score == pytest.approx(0.5)
    assert result.report_path.exists()
    assert result.markdown_path.exists()

    report = json.loads(result.report_json)
    assert report["summary"]["fixtures_total"] == 2
    assert report["summary"]["fixtures_passed"] == 1
    assert report["summary"]["fixtures_failed"] == 1
    assert report["summary"]["fixtures_error"] == 0
    assert report["summary"]["average_score"] == pytest.approx(0.5)
    assert [item["fixture_id"] for item in report["fixtures"]] == ["fixture-pass", "fixture-fail"]
    assert {record.status for record in repository.list_eval_runs()} == {"passed", "failed"}

    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "# Eval Suite Report" in markdown
    assert "fixture-pass" in markdown
    assert "fixture-fail" in markdown
