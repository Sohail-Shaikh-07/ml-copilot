"""Fixture-based evaluation runner for ML Copilot."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.agent.loop import create_agent_loop
from app.config import AppPaths, AppSettings
from app.storage.models import EvalRunRecord, SessionRecord, utc_now
from app.storage.repository import SQLiteRepository

AgentRunCallable = Callable[["EvalFixture", Path, AppSettings, SessionRecord], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class EvalFile:
    path: str
    content: str


@dataclass(frozen=True)
class EvalCheck:
    kind: str
    value: str | None = None
    path: str | None = None
    weight: float = 1.0


@dataclass(frozen=True)
class EvalFixture:
    id: str
    prompt: str
    name: str | None = None
    workspace_files: list[EvalFile] = field(default_factory=list)
    checks: list[EvalCheck] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalCheckResult:
    kind: str
    passed: bool
    weight: float
    value: str | None = None
    path: str | None = None
    message: str = ""


@dataclass(frozen=True)
class EvalRunResult:
    record: EvalRunRecord
    workspace_path: Path
    artifact_dir: Path
    report_path: Path
    markdown_path: Path


class EvalRunner:
    """Run task fixtures in clean workspaces and persist eval reports."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        repository: SQLiteRepository | None = None,
        agent_runner: AgentRunCallable | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository or SQLiteRepository(settings.db_path)
        self.repository.initialize()
        self.agent_runner = agent_runner or run_agent_fixture

    async def run_fixture(
        self,
        fixture: EvalFixture,
        *,
        output_dir: Path | None = None,
    ) -> EvalRunResult:
        eval_output_dir = (output_dir or self.settings.paths.workspace_root / ".ml-copilot" / "evals").resolve()
        eval_output_dir.mkdir(parents=True, exist_ok=True)

        session = self.repository.create_session(
            model=self.settings.llm.model,
            title=f"Eval: {fixture.id}",
            metadata={"eval_fixture_id": fixture.id},
        )
        record = self.repository.create_eval_run(
            task_id=fixture.id,
            session_id=session.id,
            report={"status": "running", "fixture_id": fixture.id},
        )
        workspace_path = eval_output_dir / "workspaces" / _safe_slug(fixture.id) / record.id
        artifact_dir = eval_output_dir / "artifacts" / record.id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        status = "error"
        score = 0.0
        error: str | None = None
        agent_output: dict[str, Any] = {}
        check_results: list[EvalCheckResult] = []
        workspace_before: dict[str, str] = {}
        runtime_start = time.perf_counter()

        try:
            workspace_path = self._prepare_workspace(fixture, eval_output_dir, record.id)
            workspace_before = snapshot_workspace(workspace_path)
            eval_settings = replace(
                self.settings,
                paths=AppPaths.from_workspace_root(workspace_path),
                db_path=self.settings.db_path,
            )
            agent_output = await self.agent_runner(fixture, workspace_path, eval_settings, session)
            final_content = str(agent_output.get("content") or "")
            check_results = evaluate_checks(fixture.checks, final_content, workspace_path)
            score = calculate_score(check_results)
            status = "passed" if all(result.passed for result in check_results) else "failed"
        except Exception as exc:
            error = str(exc)

        finished_at = utc_now()
        runtime_seconds = round(time.perf_counter() - runtime_start, 4)
        workspace_after = snapshot_workspace(workspace_path) if workspace_path.exists() else {}
        report = build_report(
            fixture=fixture,
            eval_run_id=record.id,
            session_id=session.id,
            status=status,
            score=score,
            started_at=record.started_at,
            finished_at=finished_at,
            workspace_path=workspace_path,
            artifact_dir=artifact_dir,
            agent_output=agent_output,
            check_results=check_results,
            file_changes=diff_workspace_snapshots(workspace_before, workspace_after),
            safety_events=summarize_safety_events(self.repository, session.id),
            runtime_seconds=runtime_seconds,
            error=error,
        )
        report_path = artifact_dir / "report.json"
        markdown_path = artifact_dir / "report.md"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text(format_markdown_report(report), encoding="utf-8")

        updated_record = self.repository.update_eval_run(
            record.id,
            status=status,
            score=score,
            finished_at=finished_at,
            report=report,
        )
        self.repository.update_session(session.id, status="idle")

        return EvalRunResult(
            record=updated_record,
            workspace_path=workspace_path,
            artifact_dir=artifact_dir,
            report_path=report_path,
            markdown_path=markdown_path,
        )

    def _prepare_workspace(self, fixture: EvalFixture, output_dir: Path, eval_run_id: str) -> Path:
        workspace_path = output_dir / "workspaces" / _safe_slug(fixture.id) / eval_run_id
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
        workspace_path.mkdir(parents=True)

        for file in fixture.workspace_files:
            target = _resolve_workspace_file(workspace_path, file.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file.content, encoding="utf-8")

        return workspace_path


async def run_agent_fixture(
    fixture: EvalFixture,
    workspace_path: Path,
    settings: AppSettings,
    session: SessionRecord,
) -> dict[str, Any]:
    """Default fixture executor that runs one agent turn inside the fixture workspace."""
    loop = create_agent_loop(settings)
    result = await loop.run_turn(session=session, user_message=fixture.prompt)
    return {
        "content": result.get("content", ""),
        "result": result,
        "workspace_path": str(workspace_path),
    }


def load_fixture(path: Path) -> EvalFixture:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Eval fixture must be a JSON object.")
    return fixture_from_dict(raw)


def fixture_from_dict(raw: dict[str, Any]) -> EvalFixture:
    fixture_id = _required_str(raw, "id")
    prompt = _required_str(raw, "prompt")
    return EvalFixture(
        id=fixture_id,
        name=_optional_str(raw.get("name")),
        prompt=prompt,
        workspace_files=_parse_files(raw.get("workspace_files", raw.get("files", []))),
        checks=_parse_checks(raw.get("checks", [])),
        metadata=raw.get("metadata", {}) if isinstance(raw.get("metadata", {}), dict) else {},
    )


def evaluate_checks(checks: list[EvalCheck], final_content: str, workspace_path: Path) -> list[EvalCheckResult]:
    if not checks:
        return [EvalCheckResult(kind="no_checks", passed=True, weight=1.0, message="No checks configured.")]

    results: list[EvalCheckResult] = []
    for check in checks:
        if check.kind == "contains":
            passed = bool(check.value and check.value in final_content)
            message = "Final response contains expected text." if passed else "Final response is missing expected text."
        elif check.kind == "not_contains":
            passed = bool(check.value is not None and check.value not in final_content)
            message = "Final response omits forbidden text." if passed else "Final response contains forbidden text."
        elif check.kind == "file_exists":
            target = _resolve_workspace_file(workspace_path, _required_check_path(check))
            passed = target.exists()
            message = "Expected file exists." if passed else "Expected file is missing."
        elif check.kind == "file_contains":
            target = _resolve_workspace_file(workspace_path, _required_check_path(check))
            content = target.read_text(encoding="utf-8") if target.exists() else ""
            passed = bool(check.value and check.value in content)
            message = "Expected file contains text." if passed else "Expected file is missing text."
        else:
            passed = False
            message = f"Unsupported check type: {check.kind}"

        results.append(
            EvalCheckResult(
                kind=check.kind,
                passed=passed,
                weight=check.weight,
                value=check.value,
                path=check.path,
                message=message,
            )
        )
    return results


def calculate_score(results: list[EvalCheckResult]) -> float:
    total_weight = sum(max(result.weight, 0.0) for result in results)
    if total_weight == 0:
        return 0.0
    passed_weight = sum(max(result.weight, 0.0) for result in results if result.passed)
    return round(passed_weight / total_weight, 4)


def build_report(
    *,
    fixture: EvalFixture,
    eval_run_id: str,
    session_id: str,
    status: str,
    score: float,
    started_at: str,
    finished_at: str,
    workspace_path: Path,
    artifact_dir: Path,
    agent_output: dict[str, Any],
    check_results: list[EvalCheckResult],
    file_changes: dict[str, Any],
    safety_events: dict[str, Any],
    runtime_seconds: float,
    error: str | None,
) -> dict[str, Any]:
    checks_total = len(check_results)
    checks_passed = sum(1 for result in check_results if result.passed)
    token_usage = extract_token_usage(agent_output)
    scoring = {
        "task_success": status == "passed",
        "tests_passed": checks_passed,
        "tests_total": checks_total,
        "files_changed": file_changes["files_changed"],
        "file_changes": file_changes,
        "safety_events": safety_events,
        "token_usage": token_usage,
        "runtime": {
            "started_at": started_at,
            "finished_at": finished_at,
            "seconds": runtime_seconds,
        },
    }
    return {
        "id": eval_run_id,
        "fixture": {
            "id": fixture.id,
            "name": fixture.name,
            "metadata": fixture.metadata,
        },
        "session_id": session_id,
        "status": status,
        "score": score,
        "started_at": started_at,
        "finished_at": finished_at,
        "workspace_path": str(workspace_path),
        "artifact_dir": str(artifact_dir),
        "agent_output": _json_safe(agent_output),
        "scoring": scoring,
        "checks": [
            {
                "type": result.kind,
                "passed": result.passed,
                "weight": result.weight,
                "value": result.value,
                "path": result.path,
                "message": result.message,
            }
            for result in check_results
        ],
        "error": error,
    }


def format_markdown_report(report: dict[str, Any]) -> str:
    fixture = report["fixture"]
    scoring = report.get("scoring") or {}
    runtime = scoring.get("runtime") or {}
    token_usage = scoring.get("token_usage") or {}
    safety_events = scoring.get("safety_events") or {}
    lines = [
        f"# Eval Report: {fixture['id']}",
        "",
        f"- Status: `{report['status']}`",
        f"- Score: `{report['score']}`",
        f"- Task success: `{scoring.get('task_success', report['status'] == 'passed')}`",
        f"- Tests passed: `{scoring.get('tests_passed', 0)}/{scoring.get('tests_total', 0)}`",
        f"- Runtime: `{runtime.get('seconds', 0)}` seconds",
        f"- Tokens: `{token_usage.get('total_tokens', 0)}` total",
        f"- Session: `{report['session_id']}`",
        f"- Workspace: `{report['workspace_path']}`",
        f"- Artifacts: `{report['artifact_dir']}`",
        "",
        "## Changed Files",
    ]
    for file_path in scoring.get("files_changed") or []:
        lines.append(f"- `{file_path}`")
    if not scoring.get("files_changed"):
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Safety Events",
            f"- Approval required: `{safety_events.get('approval_required_count', 0)}`",
            f"- Approval resolved: `{safety_events.get('approval_resolved_count', 0)}`",
            f"- Errors: `{safety_events.get('error_count', 0)}`",
            f"- Interruptions: `{safety_events.get('interrupted_count', 0)}`",
            "",
            "## Checks",
        ]
    )
    for check in report["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        label = check["path"] or check["value"] or check["type"]
        lines.append(f"- {mark} `{check['type']}` {label}: {check['message']}")
    if report.get("error"):
        lines.extend(["", "## Error", str(report["error"])])
    lines.append("")
    return "\n".join(lines)


def snapshot_workspace(workspace_path: Path) -> dict[str, str]:
    if not workspace_path.exists():
        return {}

    snapshot: dict[str, str] = {}
    for path in sorted(item for item in workspace_path.rglob("*") if item.is_file()):
        relative_path = path.relative_to(workspace_path).as_posix()
        snapshot[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def diff_workspace_snapshots(before: dict[str, str], after: dict[str, str]) -> dict[str, Any]:
    created = sorted(path for path in after if path not in before)
    modified = sorted(path for path in after if path in before and after[path] != before[path])
    deleted = sorted(path for path in before if path not in after)
    return {
        "created": created,
        "modified": modified,
        "deleted": deleted,
        "files_changed": sorted({*created, *modified, *deleted}),
    }


def summarize_safety_events(repository: SQLiteRepository, session_id: str) -> dict[str, Any]:
    events = repository.list_events(session_id)
    tool_calls = repository.list_tool_calls(session_id)
    safety_event_types = {"approval_required", "approval_resolved", "error", "interrupted"}
    safety_events = [
        {
            "type": event.event_type,
            "sequence": event.sequence,
            "data": _json_safe(json.loads(event.data_json)),
        }
        for event in events
        if event.event_type in safety_event_types
    ]
    approval_tool_calls = [
        {
            "id": tool_call.id,
            "tool_name": tool_call.tool_name,
            "status": tool_call.status,
            "requires_approval": tool_call.requires_approval,
        }
        for tool_call in tool_calls
        if tool_call.requires_approval
    ]
    return {
        "approval_required_count": sum(1 for event in safety_events if event["type"] == "approval_required"),
        "approval_resolved_count": sum(1 for event in safety_events if event["type"] == "approval_resolved"),
        "error_count": sum(1 for event in safety_events if event["type"] == "error"),
        "interrupted_count": sum(1 for event in safety_events if event["type"] == "interrupted"),
        "events": safety_events,
        "approval_tool_calls": approval_tool_calls,
    }


def extract_token_usage(agent_output: dict[str, Any]) -> dict[str, int]:
    usage = agent_output.get("usage")
    if not isinstance(usage, dict):
        result = agent_output.get("result")
        usage = result.get("usage") if isinstance(result, dict) else None

    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt_tokens = _int_or_zero(usage.get("prompt_tokens"))
    completion_tokens = _int_or_zero(usage.get("completion_tokens"))
    total_tokens = _int_or_zero(usage.get("total_tokens")) or prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_files(raw_files: Any) -> list[EvalFile]:
    if isinstance(raw_files, dict):
        return [EvalFile(path=str(path), content=str(content)) for path, content in raw_files.items()]
    if not isinstance(raw_files, list):
        raise ValueError("workspace_files must be a list or object.")

    files: list[EvalFile] = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError("Each workspace file must be an object.")
        files.append(EvalFile(path=_required_str(item, "path"), content=str(item.get("content", ""))))
    return files


def _parse_checks(raw_checks: Any) -> list[EvalCheck]:
    if not isinstance(raw_checks, list):
        raise ValueError("checks must be a list.")

    checks: list[EvalCheck] = []
    for item in raw_checks:
        if not isinstance(item, dict):
            raise ValueError("Each eval check must be an object.")
        weight = float(item.get("weight", 1.0))
        checks.append(
            EvalCheck(
                kind=_required_str(item, "type"),
                value=_optional_str(item.get("value")),
                path=_optional_str(item.get("path")),
                weight=weight,
            )
        )
    return checks


def _resolve_workspace_file(workspace_path: Path, relative_path: str) -> Path:
    candidate = workspace_path / relative_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace_path.resolve())
    except ValueError as exc:
        raise ValueError(f"Fixture path escapes workspace: {relative_path!r}") from exc
    return resolved


def _required_check_path(check: EvalCheck) -> str:
    if not check.path:
        raise ValueError(f"Check {check.kind!r} requires a path.")
    return check.path


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Fixture field {key!r} must be a non-empty string.")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _safe_slug(value: str) -> str:
    slug = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return slug.strip("-") or "fixture"


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(item) for item in value]
        return str(value)
    return value
