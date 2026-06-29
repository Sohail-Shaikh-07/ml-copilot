"""Tests for autonomous experiment loop planning and diagnosis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.loop import _create_tool_registry
from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.experiments import get_tool_specs, manage_experiment_loop_handler


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def _token_context(session_id: str = "session-1"):
    return use_tool_execution_context(ToolExecutionContext(session_id=session_id, hf_token="hf-session-token"))


def _state_file(tmp_path: Path, session_id: str = "session-1") -> Path:
    return tmp_path / ".ml-copilot" / "experiments" / f"{session_id}.json"


def test_get_tool_specs() -> None:
    specs = get_tool_specs()
    assert len(specs) == 1
    assert specs[0]["name"] == "manage_experiment_loop"
    props = specs[0]["parameters"]["properties"]
    assert props["operation"]["enum"] == ["record", "status", "diagnose", "next", "reset"]
    assert "experiment_id" in props
    assert "stop_conditions" in props


@pytest.mark.asyncio
async def test_record_failed_attempt_persists_diagnosis_and_next_action(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_experiment_loop_handler(
            {
                "operation": "record",
                "experiment_id": "exp-1",
                "command": "python train.py --batch-size 64",
                "exit_code": 1,
                "logs": "RuntimeError: CUDA out of memory while allocating tensor",
                "metrics": {"eval_loss": 2.1},
                "stop_conditions": {"max_attempts": 3, "target_metric": {"name": "accuracy", "min": 0.9}},
            },
            _settings(tmp_path),
        )

    assert "Attempt 1 recorded" in result
    assert "failed" in result.lower()
    assert "out of memory" in result.lower()
    assert "reduce batch size" in result.lower()
    assert "Next action: retry" in result

    state = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
    attempt = state["experiments"]["exp-1"]["attempts"][0]
    assert attempt["status"] == "failed"
    assert attempt["diagnosis"]["category"] == "resource_exhausted"
    assert attempt["recommendation"]["action"] == "retry"
    assert "hf-session-token" not in json.dumps(state)


@pytest.mark.asyncio
async def test_record_metric_success_stops_loop(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_experiment_loop_handler(
            {
                "operation": "record",
                "experiment_id": "exp-1",
                "command": "python train.py",
                "exit_code": 0,
                "logs": "eval accuracy: 0.93",
                "metrics": {"accuracy": 0.93},
                "stop_conditions": {"max_attempts": 3, "target_metric": {"name": "accuracy", "min": 0.9}},
            },
            _settings(tmp_path),
        )

    assert "Attempt 1 recorded" in result
    assert "target metric reached" in result.lower()
    assert "Next action: stop" in result


@pytest.mark.asyncio
async def test_next_stops_when_max_attempts_reached(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    for idx in range(2):
        with _token_context():
            await manage_experiment_loop_handler(
                {
                    "operation": "record",
                    "experiment_id": "exp-1",
                    "command": f"python train.py --try {idx}",
                    "exit_code": 1,
                    "logs": "ValueError: bad label shape",
                    "stop_conditions": {"max_attempts": 2},
                },
                settings,
            )

    with _token_context():
        result = await manage_experiment_loop_handler(
            {"operation": "next", "experiment_id": "exp-1", "stop_conditions": {"max_attempts": 2}},
            settings,
        )

    assert "Next action: stop" in result
    assert "max attempts reached" in result.lower()


@pytest.mark.asyncio
async def test_status_lists_attempt_history(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with _token_context():
        await manage_experiment_loop_handler(
            {
                "operation": "record",
                "experiment_id": "exp-1",
                "command": "python train.py",
                "exit_code": 0,
                "logs": "loss=1.2",
                "metrics": {"loss": 1.2},
            },
            settings,
        )
        result = await manage_experiment_loop_handler({"operation": "status", "experiment_id": "exp-1"}, settings)

    assert "# Experiment exp-1" in result
    assert "Attempt 1" in result
    assert "python train.py" in result
    assert "loss=1.2" in result


@pytest.mark.asyncio
async def test_reset_removes_experiment_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with _token_context():
        await manage_experiment_loop_handler(
            {"operation": "record", "experiment_id": "exp-1", "command": "python train.py", "exit_code": 0},
            settings,
        )
        result = await manage_experiment_loop_handler({"operation": "reset", "experiment_id": "exp-1"}, settings)

    assert "reset" in result.lower()
    state = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
    assert "exp-1" not in state["experiments"]


def test_tool_registry_includes_experiment_loop(tmp_path: Path) -> None:
    registry = _create_tool_registry(_settings(tmp_path))
    assert registry.get("manage_experiment_loop").name == "manage_experiment_loop"
