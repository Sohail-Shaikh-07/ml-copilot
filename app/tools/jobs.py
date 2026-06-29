"""Hugging Face Jobs orchestration and monitoring tools."""

from __future__ import annotations

import asyncio
from typing import Any

from app.config import AppSettings
from app.tools.context import current_hf_token

# Default Docker image for Python jobs. Uses the uv runner image so inline
# scripts and dependency installation stay fast and predictable.
DEFAULT_PYTHON_IMAGE = "ghcr.io/astral-sh/uv:python3.12-bookworm"
DEFAULT_DOCKER_IMAGE = "python:3.12"

DEFAULT_HARDWARE_FLAVOR = "cpu-basic"
DEFAULT_TIMEOUT = "30m"
MAX_LOG_LINES = 500

# Hardware flavors recognized by the Hugging Face Jobs API. Validation keeps
# the agent from submitting unsupported flavors that the API would reject.
CPU_FLAVORS = {"cpu-basic", "cpu-upgrade"}
GPU_FLAVORS = {
    "t4-small",
    "t4-medium",
    "a10g-small",
    "a10g-large",
    "a10g-largex2",
    "a10g-largex4",
    "a100-large",
    "a100x4",
    "a100x8",
    "l4x1",
    "l4x4",
    "l40sx1",
    "l40sx4",
    "l40sx8",
}
SUPPORTED_FLAVORS = CPU_FLAVORS | GPU_FLAVORS

# Environment variables injected by default to keep job output clean.
DEFAULT_ENV: dict[str, str] = {
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "TQDM_DISABLE": "1",
    "TRANSFORMERS_VERBOSITY": "warning",
}


# ---------------------------------------------------------------------------
# Hugging Face API bridge
# ---------------------------------------------------------------------------


def _hf_api() -> Any:
    """Build a Hugging Face API client using the active per-session token."""
    from huggingface_hub import HfApi

    return HfApi(token=current_hf_token())


async def _to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a blocking Hugging Face API call off the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _auth_headers() -> dict[str, str]:
    token = current_hf_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


# ---------------------------------------------------------------------------
# Argument validation and helpers
# ---------------------------------------------------------------------------


def _validate_hardware_flavor(flavor: str) -> str | None:
    """Return an error message when the hardware flavor is unsupported."""
    if flavor not in SUPPORTED_FLAVORS:
        return (
            f"Error: Unsupported hardware flavor '{flavor}'. Supported flavors: {', '.join(sorted(SUPPORTED_FLAVORS))}."
        )
    return None


def _normalize_command(value: Any) -> list[str] | None:
    """Normalize a raw command argument into a list, or None when missing."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped.split() if stripped else None
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None
    return None


def _normalize_env(value: Any) -> dict[str, str]:
    """Normalize env vars and layer them on top of the defaults."""
    result = dict(DEFAULT_ENV)
    if isinstance(value, dict):
        for key, raw in value.items():
            result[str(key)] = str(raw)
    return result


def _normalize_secrets(value: Any) -> dict[str, str]:
    """Normalize secret values. The HF token is always injected last."""
    result: dict[str, str] = {}
    if isinstance(value, dict):
        for key, raw in value.items():
            if str(raw).strip().startswith("$"):
                continue
            result[str(key)] = str(raw)

    token = current_hf_token()
    if token:
        result["HF_TOKEN"] = token
        result["HUGGING_FACE_HUB_TOKEN"] = token
    return result


def _is_billing_error(message: str) -> bool:
    """Detect namespace credit or billing rejection from an API error."""
    lowered = message.lower()
    return any(token in lowered for token in ("no available credits", "billing", "quota", "payment required", "402"))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_job(job: Any) -> str:
    """Format a single job object as readable Markdown."""
    job_id = getattr(job, "id", "?")
    status = getattr(getattr(job, "status", None), "stage", "UNKNOWN")
    message = getattr(getattr(job, "status", None), "message", "") or ""
    flavor = getattr(job, "flavor", "") or DEFAULT_HARDWARE_FLAVOR
    image = getattr(job, "docker_image", "") or ""
    created_at = getattr(job, "created_at", "")
    command = getattr(job, "command", []) or []
    url = getattr(job, "url", "") or f"https://huggingface.co/jobs/{job_id}"

    lines = [f"### Job {job_id}"]
    lines.append(f"- **Status:** {status}")
    if message:
        lines.append(f"- **Message:** {message}")
    lines.append(f"- **Hardware:** {flavor}")
    if image:
        lines.append(f"- **Image:** {image}")
    if created_at:
        lines.append(f"- **Created:** {created_at}")
    if command:
        lines.append(f"- **Command:** `{' '.join(command)}`")
    lines.append(f"- **URL:** {url}")
    return "\n".join(lines)


def _format_job_list(jobs: list[Any]) -> str:
    if not jobs:
        return "No jobs found."
    lines = [f"# Jobs ({len(jobs)})\n"]
    for job in jobs:
        lines.append(_format_job(job))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------


async def _run_job(args: dict[str, Any]) -> str:
    """Launch a Python or Docker job on Hugging Face compute."""
    script = args.get("script")
    command = _normalize_command(args.get("command"))

    if script and command:
        return "Error: Provide either 'script' or 'command', not both."
    if not script and not command:
        return "Error: Provide either 'script' (Python) or 'command' (Docker) to run a job."

    flavor = str(args.get("hardware_flavor", DEFAULT_HARDWARE_FLAVOR)).strip()
    flavor_error = _validate_hardware_flavor(flavor)
    if flavor_error:
        return flavor_error

    timeout = str(args.get("timeout", DEFAULT_TIMEOUT)).strip() or DEFAULT_TIMEOUT
    namespace = args.get("namespace")
    image = args.get("image")

    if script:
        command = _build_python_command(str(script))
        image = image or DEFAULT_PYTHON_IMAGE

    try:
        api = _hf_api()
        job = await _to_thread(
            api.run_job,
            image=image,
            command=command,
            env=_normalize_env(args.get("env")),
            secrets=_normalize_secrets(args.get("secrets")),
            flavor=flavor,
            timeout=timeout,
            namespace=namespace,
        )
    except Exception as exc:
        message = str(exc)
        if _is_billing_error(message):
            return (
                "Error: Hugging Face rejected this run because the namespace has no available "
                "credits. HF Jobs are billed with namespace credits, which are separate from "
                "HF Pro membership. Add credits at https://huggingface.co/settings/billing and "
                "re-run the job."
            )
        return f"Error launching job: {message}"

    lines = ["# Job launched\n"]
    lines.append(_format_job(job))
    lines.append("")
    lines.append("**Next:** Use manage_job with operation 'inspect', 'logs', or 'cancel'.")
    return "\n".join(lines)


def _build_python_command(script: str) -> list[str]:
    """Build a uv run command for an inline script, URL, or file path."""
    parts = ["uv", "run"]
    if script.startswith(("http://", "https://")):
        parts.append(script)
    else:
        # Inline scripts are passed via stdin so the job never needs a file.
        parts.append("-")
    return parts


async def _list_jobs(args: dict[str, Any]) -> str:
    """List jobs, optionally filtered by status."""
    try:
        api = _hf_api()
        jobs = await _to_thread(api.list_jobs, namespace=args.get("namespace"))
    except Exception as exc:
        return f"Error listing jobs: {exc}"

    jobs = list(jobs or [])
    status_filter = str(args.get("status", "")).strip().upper()
    show_all = bool(args.get("all", False))

    if status_filter:
        jobs = [job for job in jobs if status_filter in str(_job_stage(job)).upper()]
    elif not show_all:
        jobs = [job for job in jobs if str(_job_stage(job)).upper() == "RUNNING"]

    if not jobs:
        hint = " Use all=true to include completed and failed jobs." if not show_all else ""
        return f"No jobs found.{hint}"

    return _format_job_list(jobs)


async def _inspect_job(args: dict[str, Any]) -> str:
    """Inspect one or more jobs by id."""
    job_id = args.get("job_id")
    if not job_id:
        return "Error: job_id is required to inspect a job."

    job_ids = job_id if isinstance(job_id, list) else [job_id]
    jobs: list[Any] = []
    for single_id in job_ids:
        try:
            api = _hf_api()
            job = await _to_thread(api.inspect_job, job_id=str(single_id), namespace=args.get("namespace"))
        except Exception as exc:
            return f"Error inspecting job {single_id}: {exc}"
        jobs.append(job)

    lines = [f"# Job details ({len(jobs)})\n"]
    for job in jobs:
        lines.append(_format_job(job))
        lines.append("")
    return "\n".join(lines)


async def _fetch_logs(args: dict[str, Any]) -> str:
    """Fetch job logs, truncated to a bounded number of lines."""
    job_id = args.get("job_id")
    if not job_id:
        return "Error: job_id is required to fetch logs."

    try:
        api = _hf_api()
        logs_generator = api.fetch_job_logs(job_id=str(job_id), namespace=args.get("namespace"))
        logs = await _to_thread(list, logs_generator)
    except Exception as exc:
        return f"Error fetching logs for job {job_id}: {exc}"

    if not logs:
        return f"No logs available for job {job_id}."

    log_lines = [str(line).rstrip() for line in logs if str(line).strip()]
    if len(log_lines) > MAX_LOG_LINES:
        head = "\n".join(log_lines[:MAX_LOG_LINES])
        return f"# Logs for {job_id} (first {MAX_LOG_LINES} of {len(log_lines)} lines)\n\n```\n{head}\n```"

    body = "\n".join(log_lines)
    return f"# Logs for {job_id}\n\n```\n{body}\n```"


async def _cancel_job(args: dict[str, Any]) -> str:
    """Cancel a running or queued job."""
    job_id = args.get("job_id")
    if not job_id:
        return "Error: job_id is required to cancel a job."

    try:
        api = _hf_api()
        await _to_thread(api.cancel_job, job_id=str(job_id), namespace=args.get("namespace"))
    except Exception as exc:
        return f"Error cancelling job {job_id}: {exc}"

    return f"Job {job_id} has been cancelled.\n\nVerify with manage_job operation 'inspect' and job_id '{job_id}'."


def _job_stage(job: Any) -> str:
    """Safely read a job's stage string."""
    return str(getattr(getattr(job, "status", None), "stage", "UNKNOWN"))


_OPERATIONS = {
    "run": _run_job,
    "list": _list_jobs,
    "inspect": _inspect_job,
    "logs": _fetch_logs,
    "cancel": _cancel_job,
}


async def manage_job_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Dispatch a Hugging Face Jobs operation."""
    del settings

    operation = str(args.get("operation", "")).strip().lower()
    if not operation:
        return f"Error: 'operation' is required. Valid operations: {', '.join(sorted(_OPERATIONS))}."

    handler = _OPERATIONS.get(operation)
    if handler is None:
        return f"Error: Unknown operation '{operation}'. Valid operations: {', '.join(sorted(_OPERATIONS))}."

    if not current_hf_token():
        return "Error: A Hugging Face token is required for Jobs operations. Attach a session token or set HF_TOKEN."

    return await handler(args)


# ---------------------------------------------------------------------------
# Tool specification
# ---------------------------------------------------------------------------


def get_tool_specs() -> list[dict[str, Any]]:
    """Return the Hugging Face Jobs tool specification."""
    return [
        {
            "name": "manage_job",
            "description": (
                "Orchestrate Hugging Face Jobs: launch Python or Docker jobs on HF compute, "
                "list jobs, inspect status, fetch logs, and cancel runs. Requires a per-session "
                "Hugging Face token. Use after selecting a model and dataset to actually run "
                "experiments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["run", "list", "inspect", "logs", "cancel"],
                        "description": "Jobs operation to execute.",
                    },
                    "script": {
                        "type": "string",
                        "description": (
                            "Python script source, file path, or URL. Triggers Python mode via uv. "
                            "Mutually exclusive with 'command'."
                        ),
                    },
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Docker command to run as a list. Triggers Docker mode. Mutually exclusive with 'script'."
                        ),
                    },
                    "image": {
                        "type": "string",
                        "description": "Docker image. Auto-selected when omitted.",
                    },
                    "hardware_flavor": {
                        "type": "string",
                        "description": (
                            "Hardware flavor. CPU: cpu-basic, cpu-upgrade. "
                            "GPU: t4-small, t4-medium, a10g-small, a10g-large, a100-large, "
                            "l4x1, l4x4, l40sx1, l40sx4, l40sx8. Default: cpu-basic."
                        ),
                    },
                    "timeout": {
                        "type": "string",
                        "description": "Maximum job runtime, for example '30m' or '8h'. Default: '30m'.",
                    },
                    "env": {
                        "type": "object",
                        "description": "Environment variables for the job. HF_TOKEN is auto-included.",
                    },
                    "secrets": {
                        "type": "object",
                        "description": "Secret environment variables. The HF token is injected automatically.",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Optional namespace to run the job under (own account or an org).",
                    },
                    "job_id": {
                        "type": "string",
                        "description": (
                            "Job ID. Required for inspect, logs, and cancel. A list is accepted for inspect."
                        ),
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter for list (e.g. 'running', 'completed').",
                    },
                    "all": {
                        "type": "boolean",
                        "description": "For list: include completed and failed jobs instead of running only.",
                    },
                },
                "required": ["operation"],
            },
        }
    ]
