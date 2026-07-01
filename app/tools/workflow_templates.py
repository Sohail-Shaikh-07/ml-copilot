"""Autonomous workflow template and preflight planning tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import AppSettings


@dataclass(frozen=True)
class WorkflowTemplate:
    key: str
    title: str
    required_inputs: tuple[str, ...]
    stages: tuple[tuple[str, tuple[str, ...], str], ...]
    expected_artifacts: tuple[str, ...]
    risks: tuple[str, ...]


TEMPLATES: dict[str, WorkflowTemplate] = {
    "tabular_classification": WorkflowTemplate(
        key="tabular_classification",
        title="Tabular classification",
        required_inputs=("dataset", "target_column"),
        stages=(
            (
                "Scope and data readiness",
                ("inspect_dataset", "ingest_dataset"),
                "Validate the tabular source, target column, schema, label balance, and leakage risks.",
            ),
            (
                "Research and baseline selection",
                ("search_hub", "search_docs", "paper_details"),
                "Find comparable datasets/models and choose a simple baseline before heavier training.",
            ),
            (
                "Sandbox training loop",
                ("experiment_workspace", "manage_experiment_loop"),
                "Run local or sandbox smoke experiments, diagnose failures, and iterate toward the target metric.",
            ),
            (
                "Evaluation gate",
                ("manage_experiment_loop", "git_report"),
                "Compare validation metrics against the requested target and capture reproducibility evidence.",
            ),
            (
                "Report and publish-ready assets",
                ("publish_model_report",),
                "Prepare a model card, final report, manifest, limitations, and follow-up recommendations.",
            ),
        ),
        expected_artifacts=(
            "dataset profile",
            "baseline metrics",
            "training command history",
            "evaluation summary",
            "model card and final report",
        ),
        risks=(
            "target leakage or unstable validation split",
            "class imbalance",
            "metric target not aligned with business objective",
        ),
    ),
    "text_classification": WorkflowTemplate(
        key="text_classification",
        title="Text classification",
        required_inputs=("dataset", "text_column", "label_column"),
        stages=(
            (
                "Scope and data readiness",
                ("inspect_dataset", "ingest_dataset"),
                "Validate text and label columns, empty text rates, label balance, and train/validation split.",
            ),
            (
                "Research and recipe extraction",
                ("search_hub", "paper_details", "paper_citation_graph", "extract_training_recipe"),
                "Identify candidate base models, papers, and training recipes for the task size.",
            ),
            (
                "Sandbox fine-tuning loop",
                ("experiment_workspace", "manage_experiment_loop"),
                "Run a bounded smoke fine-tune, classify failures, and choose the next safest iteration.",
            ),
            (
                "Evaluation gate",
                ("manage_experiment_loop", "read_file"),
                "Check target metrics, inspect errors, and capture validation evidence before publishing.",
            ),
            (
                "Report and publish-ready assets",
                ("publish_model_report",),
                "Prepare a model card, final report, manifest, limitations, and recommended next steps.",
            ),
        ),
        expected_artifacts=(
            "dataset profile",
            "candidate model shortlist",
            "training recipe notes",
            "fine-tune/eval logs",
            "model card and final report",
        ),
        risks=(
            "private or sensitive text in examples",
            "label noise",
            "base-model/license mismatch",
        ),
    ),
    "image_classification": WorkflowTemplate(
        key="image_classification",
        title="Image classification",
        required_inputs=("dataset", "label_column"),
        stages=(
            (
                "Scope and data readiness",
                ("inspect_dataset", "ingest_dataset"),
                "Validate image paths, labels, split structure, corrupt files, and class balance.",
            ),
            (
                "Research and baseline selection",
                ("search_hub", "paper_details", "search_docs"),
                "Choose a lightweight vision baseline and training recipe before remote acceleration.",
            ),
            (
                "Sandbox training loop",
                ("experiment_workspace", "manage_experiment_loop"),
                "Run preprocessing and a small training/eval smoke loop before scaling.",
            ),
            (
                "Remote job escalation",
                ("manage_job", "manage_experiment_loop"),
                "Escalate only when local smoke checks pass and credentials/quota are available.",
            ),
            (
                "Report and publish-ready assets",
                ("publish_model_report",),
                "Prepare model documentation, sample predictions, limitations, and release notes.",
            ),
        ),
        expected_artifacts=(
            "dataset integrity report",
            "baseline metrics",
            "training logs",
            "sample predictions",
            "model card and final report",
        ),
        risks=(
            "large files or corrupt images",
            "GPU memory pressure",
            "train/validation data leakage through near-duplicates",
        ),
    ),
    "custom_experiment": WorkflowTemplate(
        key="custom_experiment",
        title="Custom ML experiment",
        required_inputs=("objective",),
        stages=(
            (
                "Clarify objective and assets",
                ("git_report", "list_files", "search_text"),
                "Inventory existing code/data and convert the objective into measurable acceptance criteria.",
            ),
            (
                "Research and environment setup",
                ("search_docs", "paper_details", "experiment_workspace"),
                "Identify reference implementation details and prepare a safe sandbox workspace.",
            ),
            (
                "Experiment loop",
                ("manage_experiment_loop", "run_command"),
                "Run bounded experiments, classify failures, and stop on target, budget, or max attempts.",
            ),
            (
                "Evaluation and reporting",
                ("git_report", "publish_model_report"),
                "Capture changed files, metrics, limitations, and publish-ready documentation.",
            ),
        ),
        expected_artifacts=(
            "objective checklist",
            "workspace inventory",
            "experiment history",
            "evaluation notes",
            "final report",
        ),
        risks=(
            "unclear metric target",
            "missing dataset or baseline",
            "unbounded runtime without explicit constraints",
        ),
    ),
}


def get_tool_specs() -> list[dict[str, Any]]:
    """Return tool specs for autonomous workflow planning."""
    return [
        {
            "name": "plan_autonomous_workflow",
            "description": (
                "Choose an ML workflow template and return a deterministic preflight plan with stages, "
                "required inputs, recommended tools, risks, and expected artifacts before long autonomous runs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "User-facing ML objective or project goal.",
                    },
                    "template": {
                        "type": "string",
                        "enum": [
                            "auto",
                            "tabular_classification",
                            "text_classification",
                            "image_classification",
                            "custom_experiment",
                        ],
                        "description": "Workflow template to use; auto selects from the objective.",
                    },
                    "available_inputs": {
                        "type": "object",
                        "description": (
                            "Known inputs and capabilities such as dataset, target_column, text_column, "
                            "label_column, target_metric, provider_api_key, hf_token, repo_id, or eval_fixture."
                        ),
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Run constraints such as allow_remote_jobs, max_cost_usd, max_runtime_minutes.",
                    },
                },
                "required": ["objective"],
            },
        }
    ]


async def plan_autonomous_workflow_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Return a deterministic workflow plan and readiness checklist."""
    del settings
    objective = str(args.get("objective") or "").strip()
    if not objective:
        return "Error: objective is required."

    available_inputs = _dict_arg(args.get("available_inputs"))
    constraints = _dict_arg(args.get("constraints"))
    template_key = _resolve_template(str(args.get("template") or "auto"), objective)
    template = TEMPLATES.get(template_key)
    if template is None:
        known = ", ".join(["auto", *TEMPLATES])
        return f"Error: Unknown workflow template {template_key!r}. Known templates: {known}."

    readiness = _readiness_lines(template, available_inputs, constraints)

    lines = [
        f"# Autonomous workflow plan: {template.key}",
        "",
        f"Objective: {objective}",
        f"Template: {template.title}",
        "",
        "## Readiness",
        *readiness,
        "",
        "## Stages",
    ]

    for index, (stage_name, tools, description) in enumerate(template.stages, start=1):
        lines.append(f"{index}. {stage_name}")
        lines.append(f"   - Recommended tools: {', '.join(tools)}")
        lines.append(f"   - Plan: {description}")

    lines.extend(["", "## Expected artifacts"])
    lines.extend(f"- {artifact}" for artifact in template.expected_artifacts)
    lines.extend(["", "## Key risks"])
    lines.extend(f"- {risk}" for risk in template.risks)

    return "\n".join(lines)


def _dict_arg(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve_template(requested: str, objective: str) -> str:
    requested = requested.strip() or "auto"
    if requested != "auto":
        return requested

    lowered = objective.lower()
    if any(token in lowered for token in ("text", "sentiment", "ticket", "review", "classification")):
        return "text_classification"
    if any(token in lowered for token in ("image", "vision", "photo", "picture")):
        return "image_classification"
    if any(token in lowered for token in ("tabular", "csv", "churn", "account", "row", "rows", "customer")):
        return "tabular_classification"
    return "custom_experiment"


def _has_input(available_inputs: dict[str, Any], key: str) -> bool:
    value = available_inputs.get(key)
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _readiness_lines(
    template: WorkflowTemplate,
    available_inputs: dict[str, Any],
    constraints: dict[str, Any],
) -> list[str]:
    lines: list[str] = []

    for required in template.required_inputs:
        if required == "objective":
            continue
        if _has_input(available_inputs, required):
            lines.append(f"- Ready: {required.replace('_', ' ').title()} is available.")
        elif required == "dataset":
            lines.append("- Blocker: Dataset path, upload, or Hub dataset id is required.")
        else:
            lines.append(f"- Blocker: {required.replace('_', ' ').title()} is required.")

    if _has_input(available_inputs, "target_metric"):
        lines.append(f"- Ready: Target metric is defined as {available_inputs['target_metric']}.")
    else:
        lines.append("- Warning: Target metric is not defined; add one before evaluating release readiness.")

    if not _has_input(available_inputs, "provider_api_key"):
        lines.append(
            "- Warning: Provider API key is missing; planning is still available but LLM-assisted research may be "
            "limited."
        )

    if not _has_input(available_inputs, "hf_token"):
        lines.append("- Blocker: Hugging Face token is not available for remote jobs or publishing.")

    if constraints.get("allow_remote_jobs") is False:
        lines.append("- Remote jobs disabled by constraints; prefer sandbox/local smoke runs first.")

    if "max_cost_usd" in constraints:
        lines.append(f"- Constraint: Maximum expected spend is ${float(constraints['max_cost_usd']):g}.")
    if "max_runtime_minutes" in constraints:
        lines.append(f"- Constraint: Maximum runtime is {float(constraints['max_runtime_minutes']):g} minutes.")

    return lines or ["- Ready: No blocking preflight requirements were detected."]
