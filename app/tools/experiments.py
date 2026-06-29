"""Autonomous experiment loop planning, persistence, and diagnosis tools."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.tools.context import current_session_id

MAX_STORED_LOG_CHARS = 12_000
MAX_DISPLAY_LOG_CHARS = 1_000
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True)
class Diagnosis:
    category: str
    summary: str


@dataclass(frozen=True)
class Recommendation:
    action: str
    reason: str
    next_step: str


@dataclass(frozen=True)
class Attempt:
    attempt_id: int
    command: str
    status: str
    exit_code: int | None
    timed_out: bool
    runtime_seconds: float | None
    cost_estimate_usd: float | None
    metrics: dict[str, float]
    logs: str
    diagnosis: Diagnosis
    recommendation: Recommendation
    created_at: str


def get_tool_specs() -> list[dict[str, Any]]:
    """Return tool specs for the experiment-loop controller."""
    return [
        {
            "name": "manage_experiment_loop",
            "description": (
                "Persist and inspect experiment attempts, diagnose failures from bounded logs and metrics, "
                "recommend minimal next actions, and enforce max-attempt, metric, runtime, or budget stops."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["record", "status", "diagnose", "next", "reset"],
                        "description": "Experiment-loop operation to perform.",
                    },
                    "experiment_id": {
                        "type": "string",
                        "description": "Stable experiment identifier for this session.",
                    },
                    "command": {
                        "type": "string",
                        "description": "Command, script, or job description used for the attempt.",
                    },
                    "exit_code": {
                        "type": ["integer", "null"],
                        "description": "Process exit code when available.",
                    },
                    "timed_out": {
                        "type": "boolean",
                        "description": "Whether the attempt timed out.",
                    },
                    "runtime_seconds": {
                        "type": "number",
                        "description": "Attempt runtime in seconds.",
                    },
                    "cost_estimate_usd": {
                        "type": "number",
                        "description": "Optional estimated attempt cost for budget stop checks.",
                    },
                    "logs": {
                        "type": "string",
                        "description": "Bounded stdout/stderr or job logs to inspect.",
                    },
                    "metrics": {
                        "type": "object",
                        "description": "Numeric metric values observed for this attempt.",
                    },
                    "stop_conditions": {
                        "type": "object",
                        "description": (
                            "Optional stop conditions: max_attempts, target_metric {name,min|max}, "
                            "max_runtime_seconds, max_cost_usd."
                        ),
                    },
                },
                "required": ["operation", "experiment_id"],
            },
        }
    ]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_id(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("-", value.strip()).strip(".-_")
    return cleaned[:80] or "default"


def _session_key() -> str:
    return _safe_id(current_session_id() or "default")


def _state_path(settings: AppSettings) -> Path:
    return settings.paths.workspace_root / ".ml-copilot" / "experiments" / f"{_session_key()}.json"


def _empty_state() -> dict[str, Any]:
    return {"session_id": current_session_id() or "default", "experiments": {}}


def _load_state(settings: AppSettings) -> dict[str, Any]:
    path = _state_path(settings)
    if not path.exists():
        return _empty_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("session_id", current_session_id() or "default")
    data.setdefault("experiments", {})
    return data


def _save_state(settings: AppSettings, state: dict[str, Any]) -> None:
    path = _state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_experiment_id(args: dict[str, Any]) -> str | None:
    raw = str(args.get("experiment_id") or "").strip()
    return raw or None


def _normalize_metrics(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw in value.items():
        try:
            result[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return result


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _truncate_logs(value: Any, limit: int = MAX_STORED_LOG_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n... [{omitted} chars truncated] ..."


def _display_logs(value: str) -> str:
    if len(value) <= MAX_DISPLAY_LOG_CHARS:
        return value
    omitted = len(value) - MAX_DISPLAY_LOG_CHARS
    return value[:MAX_DISPLAY_LOG_CHARS] + f"\n... [{omitted} chars omitted] ..."


def _target_metric_reached(metrics: dict[str, float], stop_conditions: dict[str, Any]) -> tuple[bool, str | None]:
    target = stop_conditions.get("target_metric")
    if not isinstance(target, dict):
        return False, None
    name = str(target.get("name") or "").strip()
    if not name or name not in metrics:
        return False, None
    value = metrics[name]
    if "min" in target and value >= float(target["min"]):
        return True, f"target metric reached: {name}={value:g} >= {float(target['min']):g}"
    if "max" in target and value <= float(target["max"]):
        return True, f"target metric reached: {name}={value:g} <= {float(target['max']):g}"
    return False, None


def _classify_diagnosis(*, exit_code: int | None, timed_out: bool, logs: str, metrics: dict[str, float]) -> Diagnosis:
    lowered = logs.lower()
    if timed_out:
        return Diagnosis("timeout", "The attempt timed out before producing a final result.")
    if exit_code not in (None, 0):
        if any(token in lowered for token in ("out of memory", "cuda oom", "cuda memory", "oom")):
            return Diagnosis(
                "resource_exhausted",
                "The attempt failed with an out of memory error because available memory was exhausted.",
            )
        if any(token in lowered for token in ("modulenotfounderror", "no module named", "importerror")):
            return Diagnosis("dependency_missing", "The attempt failed because a dependency could not be imported.")
        if any(token in lowered for token in ("valueerror", "shape", "dimension", "label")):
            return Diagnosis("data_or_shape_error", "The attempt failed due to a data, label, or tensor shape issue.")
        return Diagnosis("runtime_error", "The attempt exited with a non-zero status; inspect logs for details.")
    if metrics:
        return Diagnosis("completed_with_metrics", "The attempt completed and reported metrics.")
    return Diagnosis("completed", "The attempt completed without a detected runtime failure.")


def _budget_stop(attempts: list[dict[str, Any]], stop_conditions: dict[str, Any]) -> str | None:
    max_attempts = _int_or_none(stop_conditions.get("max_attempts"))
    if max_attempts is not None and len(attempts) >= max_attempts:
        return f"max attempts reached: {len(attempts)} >= {max_attempts}"

    max_runtime = _float_or_none(stop_conditions.get("max_runtime_seconds"))
    if max_runtime is not None:
        runtime = sum(float(attempt.get("runtime_seconds") or 0.0) for attempt in attempts)
        if runtime >= max_runtime:
            return f"runtime budget exhausted: {runtime:g}s >= {max_runtime:g}s"

    max_cost = _float_or_none(stop_conditions.get("max_cost_usd"))
    if max_cost is not None:
        cost = sum(float(attempt.get("cost_estimate_usd") or 0.0) for attempt in attempts)
        if cost >= max_cost:
            return f"cost budget exhausted: ${cost:g} >= ${max_cost:g}"

    return None


def _recommend(
    *,
    diagnosis: Diagnosis,
    status: str,
    command: str,
    metrics: dict[str, float],
    attempts: list[dict[str, Any]],
    stop_conditions: dict[str, Any],
) -> Recommendation:
    target_reached, target_reason = _target_metric_reached(metrics, stop_conditions)
    if target_reached and target_reason:
        return Recommendation("stop", target_reason, "Stop the loop and summarize the successful run.")

    stop_reason = _budget_stop(attempts, stop_conditions)
    if stop_reason:
        return Recommendation("stop", stop_reason, "Stop the loop and report the best observed attempt.")

    if status == "succeeded":
        return Recommendation("stop", "attempt completed successfully", "Stop unless a higher target is required.")

    if diagnosis.category == "resource_exhausted":
        return Recommendation(
            "retry",
            "resource exhaustion is often fixed by reducing memory pressure",
            f"Retry after you reduce batch size or sequence length for `{command}`.",
        )
    if diagnosis.category == "dependency_missing":
        return Recommendation(
            "retry",
            "missing dependency detected",
            "Install the missing package in the sandbox or job image, then rerun the same command.",
        )
    if diagnosis.category == "data_or_shape_error":
        return Recommendation(
            "revise",
            "data or tensor shape mismatch detected",
            "Inspect dataset columns, labels, collator, and model head dimensions before rerunning.",
        )
    if diagnosis.category == "timeout":
        return Recommendation(
            "retry",
            "attempt exceeded its timeout",
            "Retry with a smaller smoke-test slice or a longer explicit timeout.",
        )
    return Recommendation("retry", "failure has no specific classifier yet", "Inspect the bounded logs and rerun.")


def _attempt_status(exit_code: int | None, timed_out: bool) -> str:
    if timed_out:
        return "timed_out"
    if exit_code not in (None, 0):
        return "failed"
    return "succeeded"


def _attempt_from_args(args: dict[str, Any], existing_attempts: list[dict[str, Any]]) -> Attempt:
    command = str(args.get("command") or "").strip()
    exit_code = _int_or_none(args.get("exit_code"))
    timed_out = bool(args.get("timed_out", False))
    runtime_seconds = _float_or_none(args.get("runtime_seconds"))
    cost_estimate_usd = _float_or_none(args.get("cost_estimate_usd"))
    metrics = _normalize_metrics(args.get("metrics"))
    logs = _truncate_logs(args.get("logs"))
    status = _attempt_status(exit_code, timed_out)
    diagnosis = _classify_diagnosis(exit_code=exit_code, timed_out=timed_out, logs=logs, metrics=metrics)
    provisional = {
        "runtime_seconds": runtime_seconds,
        "cost_estimate_usd": cost_estimate_usd,
    }
    attempts_for_stop = [*existing_attempts, provisional]
    recommendation = _recommend(
        diagnosis=diagnosis,
        status=status,
        command=command,
        metrics=metrics,
        attempts=attempts_for_stop,
        stop_conditions=_stop_conditions(args),
    )
    return Attempt(
        attempt_id=len(existing_attempts) + 1,
        command=command,
        status=status,
        exit_code=exit_code,
        timed_out=timed_out,
        runtime_seconds=provisional["runtime_seconds"],
        cost_estimate_usd=provisional["cost_estimate_usd"],
        metrics=metrics,
        logs=logs,
        diagnosis=diagnosis,
        recommendation=recommendation,
        created_at=_utc_now(),
    )


def _stop_conditions(args: dict[str, Any]) -> dict[str, Any]:
    value = args.get("stop_conditions")
    return value if isinstance(value, dict) else {}


def _experiment(state: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    experiments = state.setdefault("experiments", {})
    return experiments.setdefault(experiment_id, {"attempts": []})


def _format_recommendation(recommendation: dict[str, Any] | Recommendation) -> str:
    if isinstance(recommendation, Recommendation):
        action = recommendation.action
        reason = recommendation.reason
        next_step = recommendation.next_step
    else:
        action = str(recommendation.get("action", ""))
        reason = str(recommendation.get("reason", ""))
        next_step = str(recommendation.get("next_step", ""))
    return f"Next action: {action}\nReason: {reason}\nNext step: {next_step}"


def _format_attempt(attempt: dict[str, Any]) -> str:
    lines = [
        f"## Attempt {attempt['attempt_id']}",
        f"- Status: {attempt['status']}",
        f"- Command: `{attempt.get('command', '')}`",
        f"- Diagnosis: {attempt['diagnosis']['summary']}",
        f"- Recommendation: {attempt['recommendation']['action']}",
    ]
    metrics = attempt.get("metrics") or {}
    if metrics:
        lines.append("- Metrics: " + ", ".join(f"{key}={value:g}" for key, value in metrics.items()))
    logs = _display_logs(str(attempt.get("logs") or "")).strip()
    if logs:
        lines.extend(["", "Logs:", logs])
    return "\n".join(lines)


async def _record(args: dict[str, Any], settings: AppSettings, experiment_id: str) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        return "Error: command is required for record."
    state = _load_state(settings)
    experiment = _experiment(state, experiment_id)
    attempts = experiment.setdefault("attempts", [])
    attempt = _attempt_from_args(args, attempts)
    attempts.append(
        {
            **asdict(attempt),
            "diagnosis": asdict(attempt.diagnosis),
            "recommendation": asdict(attempt.recommendation),
        }
    )
    experiment["updated_at"] = attempt.created_at
    _save_state(settings, state)

    return "\n".join(
        [
            f"Attempt {attempt.attempt_id} recorded for experiment {experiment_id}.",
            f"Status: {attempt.status}",
            f"Diagnosis: {attempt.diagnosis.summary}",
            _format_recommendation(attempt.recommendation),
        ]
    )


async def _status(settings: AppSettings, experiment_id: str) -> str:
    state = _load_state(settings)
    experiment = state.get("experiments", {}).get(experiment_id)
    if not experiment:
        return f"No experiment history found for {experiment_id}."
    attempts = experiment.get("attempts", [])
    lines = [f"# Experiment {experiment_id}", f"Attempts: {len(attempts)}"]
    for attempt in attempts:
        lines.extend(["", _format_attempt(attempt)])
    return "\n".join(lines)


async def _diagnose_latest(settings: AppSettings, experiment_id: str) -> str:
    state = _load_state(settings)
    attempts = state.get("experiments", {}).get(experiment_id, {}).get("attempts", [])
    if not attempts:
        return f"No attempts recorded for {experiment_id}."
    latest = attempts[-1]
    return "\n".join(
        [
            f"Latest diagnosis for {experiment_id}:",
            f"- Category: {latest['diagnosis']['category']}",
            f"- Summary: {latest['diagnosis']['summary']}",
            _format_recommendation(latest["recommendation"]),
        ]
    )


async def _next(args: dict[str, Any], settings: AppSettings, experiment_id: str) -> str:
    state = _load_state(settings)
    attempts = state.get("experiments", {}).get(experiment_id, {}).get("attempts", [])
    if not attempts:
        return f"No attempts recorded for {experiment_id}. Record a first attempt before requesting next action."
    latest = attempts[-1]
    stop_reason = _budget_stop(attempts, _stop_conditions(args))
    if stop_reason:
        return _format_recommendation(
            Recommendation("stop", stop_reason, "Stop the loop and report the best observed attempt.")
        )
    return _format_recommendation(latest["recommendation"])


async def _reset(settings: AppSettings, experiment_id: str) -> str:
    state = _load_state(settings)
    state.setdefault("experiments", {}).pop(experiment_id, None)
    _save_state(settings, state)
    return f"Experiment {experiment_id} reset."


async def manage_experiment_loop_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Handle experiment loop record/status/diagnose/next/reset operations."""
    operation = str(args.get("operation") or "").strip().lower()
    if not operation:
        return "Error: operation is required."
    experiment_id = _normalize_experiment_id(args)
    if experiment_id is None:
        return "Error: experiment_id is required."

    if operation == "record":
        return await _record(args, settings, experiment_id)
    if operation == "status":
        return await _status(settings, experiment_id)
    if operation == "diagnose":
        return await _diagnose_latest(settings, experiment_id)
    if operation == "next":
        return await _next(args, settings, experiment_id)
    if operation == "reset":
        return await _reset(settings, experiment_id)
    return f"Error: Unknown experiment loop operation {operation!r}."
