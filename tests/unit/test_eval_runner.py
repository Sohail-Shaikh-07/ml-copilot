"""Tests for fixture-based eval runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppPaths, AppSettings
from app.evals.runner import EvalFixture, EvalRunner, fixture_from_dict, load_fixture
from app.storage.models import SessionRecord
from app.storage.repository import SQLiteRepository


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


@pytest.mark.asyncio
async def test_eval_runner_writes_workspace_scores_and_artifacts(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = SQLiteRepository(settings.db_path)
    fixture = fixture_from_dict(
        {
            "id": "fixture-pass",
            "name": "Passing fixture",
            "prompt": "Create a summary",
            "workspace_files": [{"path": "input.txt", "content": "seed data"}],
            "checks": [
                {"type": "contains", "value": "done"},
                {"type": "file_exists", "path": "summary.md"},
                {"type": "file_contains", "path": "summary.md", "value": "artifact"},
            ],
        }
    )

    async def fake_agent(
        _fixture: EvalFixture,
        workspace_path: Path,
        _settings: AppSettings,
        session: SessionRecord,
    ) -> dict[str, object]:
        (workspace_path / "summary.md").write_text("artifact created\n", encoding="utf-8")
        (workspace_path / "input.txt").write_text("seed data updated\n", encoding="utf-8")
        repository.add_event(
            session_id=session.id,
            turn_id="turn-1",
            event_type="approval_required",
            data={"tool_name": "run_command"},
            sequence=0,
        )
        repository.add_tool_call(
            session_id=session.id,
            turn_id="turn-1",
            tool_name="run_command",
            arguments={"command": "pytest"},
            status="pending_approval",
            requires_approval=True,
            tool_call_id="tool-1",
        )
        return {
            "content": "done",
            "session_id": session.id,
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        }

    result = await EvalRunner(settings, repository=repository, agent_runner=fake_agent).run_fixture(
        fixture,
        output_dir=tmp_path / "eval-output",
    )

    assert result.record.status == "passed"
    assert result.record.score == 1.0
    assert (result.workspace_path / "input.txt").read_text(encoding="utf-8") == "seed data updated\n"
    assert result.report_path.exists()
    assert result.markdown_path.exists()

    report = json.loads(result.record.report_json)
    assert report["fixture"]["id"] == "fixture-pass"
    assert report["status"] == "passed"
    assert all(check["passed"] for check in report["checks"])
    assert report["scoring"]["task_success"] is True
    assert report["scoring"]["tests_passed"] == 3
    assert report["scoring"]["tests_total"] == 3
    assert report["scoring"]["file_changes"]["created"] == ["summary.md"]
    assert report["scoring"]["file_changes"]["modified"] == ["input.txt"]
    assert report["scoring"]["files_changed"] == ["input.txt", "summary.md"]
    assert report["scoring"]["safety_events"]["approval_required_count"] == 1
    assert report["scoring"]["safety_events"]["approval_tool_calls"][0]["tool_name"] == "run_command"
    assert report["scoring"]["token_usage"]["total_tokens"] == 18
    assert report["scoring"]["runtime"]["seconds"] >= 0
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert "## Changed Files" in markdown
    assert "## Safety Events" in markdown
    assert repository.list_eval_runs("fixture-pass") == [result.record]


@pytest.mark.asyncio
async def test_eval_runner_records_failed_checks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    fixture = fixture_from_dict(
        {
            "id": "fixture-fail",
            "prompt": "Create a summary",
            "checks": [
                {"type": "contains", "value": "expected", "weight": 2},
                {"type": "not_contains", "value": "forbidden", "weight": 1},
            ],
        }
    )

    async def fake_agent(
        _fixture: EvalFixture,
        _workspace_path: Path,
        _settings: AppSettings,
        _session: SessionRecord,
    ) -> dict[str, object]:
        return {"content": "missing expected and forbidden"}

    result = await EvalRunner(settings, agent_runner=fake_agent).run_fixture(
        fixture,
        output_dir=tmp_path / "eval-output",
    )

    report = json.loads(result.record.report_json)

    assert result.record.status == "failed"
    assert result.record.score == pytest.approx(2 / 3, abs=0.0001)
    assert [check["passed"] for check in report["checks"]] == [True, False]
    assert report["scoring"]["task_success"] is False
    assert report["scoring"]["tests_passed"] == 1
    assert report["scoring"]["tests_total"] == 2


@pytest.mark.asyncio
async def test_eval_runner_records_agent_errors(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    fixture = fixture_from_dict({"id": "fixture-error", "prompt": "fail", "checks": []})

    async def failing_agent(
        _fixture: EvalFixture,
        _workspace_path: Path,
        _settings: AppSettings,
        _session: SessionRecord,
    ) -> dict[str, object]:
        raise RuntimeError("boom")

    result = await EvalRunner(settings, agent_runner=failing_agent).run_fixture(
        fixture,
        output_dir=tmp_path / "eval-output",
    )
    report = json.loads(result.record.report_json)

    assert result.record.status == "error"
    assert result.record.score == 0.0
    assert report["error"] == "boom"


@pytest.mark.asyncio
async def test_eval_runner_sanitizes_agent_output_for_reports(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    fixture = fixture_from_dict({"id": "fixture-json-safe", "prompt": "ok", "checks": []})

    async def fake_agent(
        _fixture: EvalFixture,
        workspace_path: Path,
        _settings: AppSettings,
        _session: SessionRecord,
    ) -> dict[str, object]:
        return {"content": "ok", "path": workspace_path}

    result = await EvalRunner(settings, agent_runner=fake_agent).run_fixture(
        fixture,
        output_dir=tmp_path / "eval-output",
    )
    report = json.loads(result.record.report_json)

    assert result.record.status == "passed"
    assert report["agent_output"]["path"] == str(result.workspace_path)


@pytest.mark.asyncio
async def test_runner_records_workspace_escape_as_error(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "id": "fixture-escape",
                "prompt": "unsafe",
                "workspace_files": [{"path": "../outside.txt", "content": "bad"}],
            }
        ),
        encoding="utf-8",
    )
    settings = _settings(tmp_path)
    fixture = load_fixture(fixture_path)

    async def fake_agent(
        _fixture: EvalFixture,
        _workspace_path: Path,
        _settings: AppSettings,
        _session: SessionRecord,
    ) -> dict[str, object]:
        return {"content": "should not run"}

    result = await EvalRunner(settings, agent_runner=fake_agent).run_fixture(
        fixture,
        output_dir=tmp_path / "eval-output",
    )
    report = json.loads(result.record.report_json)

    assert result.record.status == "error"
    assert "escapes workspace" in report["error"]
