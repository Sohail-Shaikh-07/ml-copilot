"""Suite-level orchestration for fixture-based evals."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.evals.runner import AgentRunCallable, EvalRunner, EvalRunResult, load_fixture
from app.storage.repository import SQLiteRepository


@dataclass(frozen=True)
class EvalSuiteRunResult:
    """Aggregate result for a run of multiple eval fixtures."""

    status: str
    score: float
    fixture_results: list[EvalRunResult]
    report: dict[str, Any]
    report_path: Path
    markdown_path: Path

    @property
    def report_json(self) -> str:
        return json.dumps(self.report, sort_keys=True)


class EvalSuiteRunner:
    """Run a directory or list of eval fixtures and write aggregate reports."""

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
        self.agent_runner = agent_runner

    async def run_path(self, path: Path, *, output_dir: Path | None = None) -> EvalSuiteRunResult:
        """Discover and run fixtures from a JSON fixture path or directory."""
        return await self.run_fixture_paths(discover_fixture_paths(path), output_dir=output_dir)

    async def run_fixture_paths(
        self,
        fixture_paths: list[Path],
        *,
        output_dir: Path | None = None,
    ) -> EvalSuiteRunResult:
        """Run the provided fixture files in deterministic order."""
        if not fixture_paths:
            raise ValueError("At least one eval fixture is required.")

        eval_output_dir = (output_dir or self.settings.paths.workspace_root / ".ml-copilot" / "evals").resolve()
        eval_output_dir.mkdir(parents=True, exist_ok=True)
        suite_dir = eval_output_dir / "suites" / _suite_id(fixture_paths)
        suite_dir.mkdir(parents=True, exist_ok=True)

        runner = EvalRunner(self.settings, repository=self.repository, agent_runner=self.agent_runner)
        runtime_start = time.perf_counter()
        results: list[EvalRunResult] = []
        for fixture_path in fixture_paths:
            results.append(await runner.run_fixture(load_fixture(fixture_path), output_dir=eval_output_dir))

        runtime_seconds = round(time.perf_counter() - runtime_start, 4)
        report = build_suite_report(results, runtime_seconds=runtime_seconds)
        report_path = suite_dir / "suite-report.json"
        markdown_path = suite_dir / "suite-report.md"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown_path.write_text(format_suite_markdown_report(report), encoding="utf-8")
        return EvalSuiteRunResult(
            status=report["status"],
            score=report["summary"]["average_score"],
            fixture_results=results,
            report=report,
            report_path=report_path,
            markdown_path=markdown_path,
        )


def discover_fixture_paths(path: Path) -> list[Path]:
    """Return sorted fixture JSON files from a fixture path or directory."""
    resolved = path.resolve()
    if resolved.is_file():
        if resolved.suffix.lower() != ".json":
            raise ValueError(f"Eval fixture must be a JSON file: {path}")
        return [resolved]
    if not resolved.exists():
        raise ValueError(f"Eval fixture path does not exist: {path}")
    if not resolved.is_dir():
        raise ValueError(f"Eval fixture path must be a file or directory: {path}")

    fixture_paths = sorted(item for item in resolved.glob("*.json") if item.is_file())
    if not fixture_paths:
        raise ValueError(f"No eval fixture JSON files found in {path}")
    return fixture_paths


def build_suite_report(results: list[EvalRunResult], *, runtime_seconds: float) -> dict[str, Any]:
    """Build a JSON-serializable aggregate report for fixture results."""
    fixture_reports = [_decode_report(result) for result in results]
    statuses = [result.record.status for result in results]
    fixtures_total = len(results)
    fixtures_passed = sum(1 for status in statuses if status == "passed")
    fixtures_failed = sum(1 for status in statuses if status == "failed")
    fixtures_error = sum(1 for status in statuses if status == "error")
    average_score = round(sum(float(result.record.score or 0.0) for result in results) / fixtures_total, 4)
    status = "passed" if fixtures_passed == fixtures_total else "error" if fixtures_error else "failed"
    total_tokens = sum(
        int(((report.get("scoring") or {}).get("token_usage") or {}).get("total_tokens") or 0)
        for report in fixture_reports
    )
    return {
        "status": status,
        "summary": {
            "fixtures_total": fixtures_total,
            "fixtures_passed": fixtures_passed,
            "fixtures_failed": fixtures_failed,
            "fixtures_error": fixtures_error,
            "average_score": average_score,
            "runtime_seconds": runtime_seconds,
            "total_tokens": total_tokens,
        },
        "fixtures": [
            {
                "fixture_id": result.record.task_id,
                "eval_run_id": result.record.id,
                "status": result.record.status,
                "score": result.record.score,
                "report_path": str(result.report_path),
                "markdown_path": str(result.markdown_path),
                "workspace_path": str(result.workspace_path),
            }
            for result in results
        ],
    }


def format_suite_markdown_report(report: dict[str, Any]) -> str:
    """Render a compact Markdown summary for a suite run."""
    summary = report["summary"]
    lines = [
        "# Eval Suite Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Fixtures: `{summary['fixtures_passed']}/{summary['fixtures_total']}` passed",
        f"- Failed: `{summary['fixtures_failed']}`",
        f"- Errors: `{summary['fixtures_error']}`",
        f"- Average score: `{summary['average_score']}`",
        f"- Runtime: `{summary['runtime_seconds']}` seconds",
        f"- Tokens: `{summary['total_tokens']}` total",
        "",
        "## Fixtures",
    ]
    for fixture in report["fixtures"]:
        lines.append(
            f"- `{fixture['status']}` `{fixture['fixture_id']}` "
            f"score=`{fixture['score']}` report=`{fixture['markdown_path']}`"
        )
    lines.append("")
    return "\n".join(lines)


def _decode_report(result: EvalRunResult) -> dict[str, Any]:
    try:
        loaded = json.loads(result.record.report_json)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _suite_id(fixture_paths: list[Path]) -> str:
    stem = fixture_paths[0].parent.name if len(fixture_paths) > 1 else fixture_paths[0].stem
    return _safe_slug(f"{stem}-{int(time.time() * 1000)}")


def _safe_slug(value: str) -> str:
    slug = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    return slug.strip("-") or "suite"
