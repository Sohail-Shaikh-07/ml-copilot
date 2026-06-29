"""Model publishing, model card, and final report tooling."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.tools.context import current_hf_token, current_session_id
from app.tools.workspace import _safe_path

DEFAULT_OUTPUT_ROOT = "reports/model-publishing"
PUBLISH_MANIFEST = "publish_manifest.json"
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def get_tool_specs() -> list[dict[str, Any]]:
    """Return tool specs for model publishing and report generation."""
    return [
        {
            "name": "publish_model_report",
            "description": (
                "Prepare Hub-ready model publishing assets locally: README model card, final reproducibility "
                "report, manifest, and optional explicit Hugging Face Hub upload."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "Target Hugging Face model repo id."},
                    "model_name": {"type": "string", "description": "Human-readable model name."},
                    "task": {"type": "string", "description": "Primary task or pipeline tag."},
                    "license": {"type": "string", "description": "Model license for card metadata."},
                    "datasets": {"type": "array", "items": {"type": "string"}},
                    "base_models": {"type": "array", "items": {"type": "string"}},
                    "papers": {"type": "array", "items": {"type": "string"}},
                    "jobs": {"type": "array", "items": {"type": "string"}},
                    "sandbox_commands": {"type": "array", "items": {"type": "string"}},
                    "metrics": {"type": "object", "description": "Final model metrics."},
                    "recommendation": {"type": "string", "description": "Final recommendation and rationale."},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                    "output_dir": {"type": "string", "description": "Workspace-relative output directory."},
                    "publish": {
                        "type": "boolean",
                        "description": "When true, upload the prepared folder to the Hugging Face Hub.",
                    },
                    "private": {"type": "boolean", "description": "Create/update the Hub repo as private."},
                },
                "required": ["repo_id"],
            },
        }
    ]


async def _to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(func, *args, **kwargs)


def _hf_api() -> Any:
    from huggingface_hub import HfApi

    return HfApi(token=current_hf_token())


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", value.strip()).strip(".-_")
    return cleaned or "model"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_metrics(value: Any) -> dict[str, float | str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float | str] = {}
    for key, raw in value.items():
        try:
            result[str(key)] = float(raw)
        except (TypeError, ValueError):
            result[str(key)] = str(raw)
    return result


def _format_metrics(metrics: dict[str, float | str]) -> list[str]:
    if not metrics:
        return ["- No final metrics were provided."]
    lines = []
    for key, value in metrics.items():
        if isinstance(value, float):
            lines.append(f"- {key}: {value:g}")
        else:
            lines.append(f"- {key}: {value}")
    return lines


def _bullets_or_empty(values: list[str]) -> list[str]:
    return [f"- {value}" for value in values] if values else ["- Not specified."]


def _resolve_output_dir(args: dict[str, Any], settings: AppSettings, repo_id: str) -> Path | str:
    raw = str(args.get("output_dir") or "").strip()
    if not raw:
        raw = f"{DEFAULT_OUTPUT_ROOT}/{_slug(repo_id.rsplit('/', 1)[-1])}"
    candidate = Path(raw)
    if candidate.is_absolute():
        safe = _safe_path(candidate, settings.paths.workspace_root)
    else:
        safe = _safe_path(settings.paths.workspace_root / candidate, settings.paths.workspace_root)
    if safe is None:
        return f"Error: output_dir {raw!r} is outside workspace root {settings.paths.workspace_root}"
    return safe


def _model_name(args: dict[str, Any], repo_id: str) -> str:
    return str(args.get("model_name") or repo_id.rsplit("/", 1)[-1]).strip()


def _model_card(args: dict[str, Any], repo_id: str) -> str:
    model_name = _model_name(args, repo_id)
    task = str(args.get("task") or "model").strip()
    license_name = str(args.get("license") or "unknown").strip()
    datasets = _as_list(args.get("datasets"))
    base_models = _as_list(args.get("base_models"))
    limitations = _as_list(args.get("limitations"))
    metrics = _normalize_metrics(args.get("metrics"))

    tags = [task, "ml-copilot", "generated-report"]
    metadata = [
        "---",
        f"license: {license_name}",
        "tags:",
        *[f"- {tag}" for tag in tags if tag],
        "---",
        "",
    ]

    lines = [
        *metadata,
        f"# {model_name}",
        "",
        "## Model Details",
        "",
        f"- Repository: `{repo_id}`",
        f"- Task: {task}",
        f"- License: {license_name}",
        f"- Generated: {_now()}",
        "",
        "## Training Inputs",
        "",
        "### Datasets",
        *_bullets_or_empty(datasets),
        "",
        "### Base Models",
        *_bullets_or_empty(base_models),
        "",
        "## Metrics",
        "",
        *_format_metrics(metrics),
        "",
        "## Usage",
        "",
        "```python",
        "from transformers import AutoModel, AutoTokenizer",
        "",
        f'model_id = "{repo_id}"',
        "tokenizer = AutoTokenizer.from_pretrained(model_id)",
        "model = AutoModel.from_pretrained(model_id)",
        "```",
        "",
        "## Limitations",
        "",
        *([f"- {item}" for item in limitations] if limitations else ["- Limitations were not specified."]),
        "",
        "## Provenance",
        "",
        "Generated by ML Copilot from the supplied experiment, job, dataset, and paper context.",
    ]
    return "\n".join(lines).strip() + "\n"


def _final_report(args: dict[str, Any], repo_id: str) -> str:
    model_name = _model_name(args, repo_id)
    metrics = _normalize_metrics(args.get("metrics"))
    sections = [
        f"# Final Report: {model_name}",
        "",
        "## Recommendation",
        "",
        str(args.get("recommendation") or "No final recommendation was provided.").strip(),
        "",
        "## Final Metrics",
        "",
        *_format_metrics(metrics),
        "",
        "## Reproducibility",
        "",
        "### Datasets",
        *_bullets_or_empty(_as_list(args.get("datasets"))),
        "",
        "### Papers",
        *_bullets_or_empty(_as_list(args.get("papers"))),
        "",
        "### Jobs",
        *_bullets_or_empty(_as_list(args.get("jobs"))),
        "",
        "### Sandbox Commands",
        *_bullets_or_empty(_as_list(args.get("sandbox_commands"))),
        "",
        "## What Worked",
        "",
        "Use the metrics and recommendation above to identify the best observed run.",
        "",
        "## What Failed",
        "",
        "Review failed jobs, sandbox commands, and experiment attempts linked above before broadening scope.",
    ]
    return "\n".join(sections).strip() + "\n"


def _manifest(args: dict[str, Any], repo_id: str) -> dict[str, Any]:
    return {
        "repo_id": repo_id,
        "repo_type": "model",
        "model_name": _model_name(args, repo_id),
        "task": str(args.get("task") or "").strip(),
        "license": str(args.get("license") or "").strip(),
        "datasets": _as_list(args.get("datasets")),
        "base_models": _as_list(args.get("base_models")),
        "papers": _as_list(args.get("papers")),
        "jobs": _as_list(args.get("jobs")),
        "sandbox_commands": _as_list(args.get("sandbox_commands")),
        "metrics": _normalize_metrics(args.get("metrics")),
        "recommendation": str(args.get("recommendation") or "").strip(),
        "files": ["README.md", "FINAL_REPORT.md", PUBLISH_MANIFEST],
        "generated_at": _now(),
        "session_id": current_session_id(),
    }


def _write_assets(args: dict[str, Any], settings: AppSettings, repo_id: str) -> Path | str:
    output_dir = _resolve_output_dir(args, settings, repo_id)
    if isinstance(output_dir, str):
        return output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "README.md").write_text(_model_card(args, repo_id), encoding="utf-8")
    (output_dir / "FINAL_REPORT.md").write_text(_final_report(args, repo_id), encoding="utf-8")
    (output_dir / PUBLISH_MANIFEST).write_text(json.dumps(_manifest(args, repo_id), indent=2), encoding="utf-8")
    return output_dir


async def _publish(output_dir: Path, args: dict[str, Any], repo_id: str) -> str:
    token = current_hf_token()
    if not token:
        return "Error: A Hugging Face token is required when publish=true."

    api = _hf_api()
    private = bool(args.get("private", True))
    await _to_thread(api.create_repo, repo_id=repo_id, repo_type="model", private=private, exist_ok=True)
    await _to_thread(
        api.upload_folder,
        repo_id=repo_id,
        repo_type="model",
        folder_path=str(output_dir),
        commit_message="ML Copilot model card and final report",
    )
    return f"Published model assets to https://huggingface.co/{repo_id}"


async def publish_model_report_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Prepare local model publishing assets and optionally upload them to the Hub."""
    repo_id = str(args.get("repo_id") or "").strip()
    if not repo_id:
        return "Error: repo_id is required."
    if "/" not in repo_id:
        return "Error: repo_id must include a namespace, e.g. 'owner/model-name'."

    output_dir = _write_assets(args, settings, repo_id)
    if isinstance(output_dir, str):
        return output_dir

    if bool(args.get("publish", False)):
        publish_result = await _publish(output_dir, args, repo_id)
        if publish_result.startswith("Error:"):
            return publish_result
        return f"{publish_result}\nLocal assets: {output_dir}"

    return (
        "Prepared model publishing assets.\n"
        f"- README: {output_dir / 'README.md'}\n"
        f"- Final report: {output_dir / 'FINAL_REPORT.md'}\n"
        f"- Manifest: {output_dir / PUBLISH_MANIFEST}\n"
        "Set publish=true to upload these assets to the Hugging Face Hub."
    )
