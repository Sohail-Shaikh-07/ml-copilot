"""Tests for autonomous workflow template and preflight planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.loop import _create_tool_registry
from app.config import AppPaths, AppSettings
from app.tools.workflow_templates import get_tool_specs, plan_autonomous_workflow_handler


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def test_get_tool_specs_exposes_planner_schema() -> None:
    specs = get_tool_specs()

    assert len(specs) == 1
    spec = specs[0]
    assert spec["name"] == "plan_autonomous_workflow"
    props = spec["parameters"]["properties"]
    assert "objective" in props
    assert "template" in props
    assert "available_inputs" in props
    assert "constraints" in props


@pytest.mark.asyncio
async def test_planner_returns_deterministic_text_classification_plan(tmp_path: Path) -> None:
    result = await plan_autonomous_workflow_handler(
        {
            "objective": "Fine tune a sentiment classifier for support tickets.",
            "template": "text_classification",
            "available_inputs": {
                "dataset": "data/support_tickets.csv",
                "text_column": "ticket_text",
                "label_column": "sentiment",
                "target_metric": "f1 >= 0.85",
                "provider_api_key": True,
                "hf_token": False,
            },
            "constraints": {
                "allow_remote_jobs": False,
                "max_cost_usd": 5,
            },
        },
        _settings(tmp_path),
    )

    assert "Autonomous workflow plan: text_classification" in result
    assert "Fine tune a sentiment classifier for support tickets." in result
    assert "inspect_dataset" in result
    assert "paper_details" in result
    assert "experiment_workspace" in result
    assert "manage_experiment_loop" in result
    assert "publish_model_report" in result
    assert "Blocker: Hugging Face token is not available for remote jobs or publishing." in result
    assert "Remote jobs disabled by constraints; prefer sandbox/local smoke runs first." in result
    assert "Expected artifacts" in result


@pytest.mark.asyncio
async def test_planner_auto_selects_template_and_marks_missing_dataset(tmp_path: Path) -> None:
    result = await plan_autonomous_workflow_handler(
        {
            "objective": "Train a churn prediction model from customer account rows.",
            "available_inputs": {
                "target_column": "churned",
                "provider_api_key": False,
                "hf_token": True,
            },
        },
        _settings(tmp_path),
    )

    assert "Autonomous workflow plan: tabular_classification" in result
    assert "Blocker: Dataset path, upload, or Hub dataset id is required." in result
    assert (
        "Warning: Provider API key is missing; planning is still available but LLM-assisted research may be limited."
        in result
    )


@pytest.mark.asyncio
async def test_planner_rejects_unknown_template(tmp_path: Path) -> None:
    result = await plan_autonomous_workflow_handler(
        {"objective": "Train something useful.", "template": "magic"},
        _settings(tmp_path),
    )

    assert result.startswith("Error:")
    assert "Unknown workflow template 'magic'" in result


def test_tool_registry_includes_autonomous_workflow_planner(tmp_path: Path) -> None:
    registry = _create_tool_registry(_settings(tmp_path))

    assert registry.get("plan_autonomous_workflow").name == "plan_autonomous_workflow"
