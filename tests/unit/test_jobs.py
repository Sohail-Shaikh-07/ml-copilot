"""Tests for app.tools.jobs module."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.jobs import (
    _build_python_command,
    _is_billing_error,
    _normalize_command,
    _normalize_env,
    _normalize_secrets,
    get_tool_specs,
    manage_job_handler,
)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


class _FakeStatus:
    def __init__(self, stage: str = "RUNNING", message: str = ""):
        self.stage = stage
        self.message = message


class _FakeJob:
    def __init__(self, job_id: str = "job-1", stage: str = "RUNNING"):
        self.id = job_id
        self.status = _FakeStatus(stage=stage)
        self.flavor = "cpu-basic"
        self.docker_image = "ghcr.io/astral-sh/uv:python3.12-bookworm"
        self.created_at = "2026-06-28T12:00:00Z"
        self.command = ["uv", "run", "-"]
        self.url = f"https://huggingface.co/jobs/{job_id}"


class _FakeHfApi:
    """Minimal stand-in for huggingface_hub.HfApi exercising job methods."""

    instances: list["_FakeHfApi"] = []

    def __init__(self, token=None):
        self.token = token
        self.run_job_calls: list[dict] = []
        _FakeHfApi.instances.append(self)

    def run_job(self, **kwargs):
        self.run_job_calls.append(kwargs)
        return _FakeJob(job_id="job-123", stage="QUEUED")

    def list_jobs(self, namespace=None):
        return [_FakeJob("job-1", "RUNNING"), _FakeJob("job-2", "COMPLETED")]

    def inspect_job(self, job_id, namespace=None):
        return _FakeJob(job_id=job_id, stage="RUNNING")

    def fetch_job_logs(self, job_id, namespace=None):
        return iter([f"[{job_id}] step 1 ok", f"[{job_id}] step 2 ok", ""])

    def cancel_job(self, job_id, namespace=None):
        self.cancelled = job_id


@pytest.fixture(autouse=True)
def _reset_fake_api():
    _FakeHfApi.instances.clear()
    yield
    _FakeHfApi.instances.clear()


@pytest.fixture(autouse=True)
def _stub_huggingface_hub():
    """Inject a fake huggingface_hub module for the duration of each test."""
    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _FakeHfApi
    original = sys.modules.get("huggingface_hub")
    sys.modules["huggingface_hub"] = fake_module
    try:
        yield
    finally:
        if original is not None:
            sys.modules["huggingface_hub"] = original
        else:
            sys.modules.pop("huggingface_hub", None)


def _token_context():
    return use_tool_execution_context(ToolExecutionContext(session_id="session-1", hf_token="hf-session-token"))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalize_command_accepts_string_and_list() -> None:
    assert _normalize_command("uv run train.py") == ["uv", "run", "train.py"]
    assert _normalize_command(["uv", "run", " train.py "]) == ["uv", "run", "train.py"]
    assert _normalize_command(None) is None
    assert _normalize_command("   ") is None
    assert _normalize_command([]) is None


def test_normalize_env_layers_over_defaults() -> None:
    env = _normalize_env({"CUDA_VISIBLE_DEVICES": "0", "TQDM_DISABLE": "0"})
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["TQDM_DISABLE"] == "0"  # user override wins
    assert env["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"  # default retained


def test_normalize_secrets_injects_token_and_drops_placeholders() -> None:
    with _token_context():
        secrets = _normalize_secrets({"WANDB_API_KEY": "abc", "SKIP": "$SKIP_ME"})
    assert secrets["HF_TOKEN"] == "hf-session-token"
    assert secrets["HUGGING_FACE_HUB_TOKEN"] == "hf-session-token"
    assert secrets["WANDB_API_KEY"] == "abc"
    assert "SKIP" not in secrets


def test_is_billing_error_detects_credit_messages() -> None:
    assert _is_billing_error("namespace has no available credits")
    assert _is_billing_error("HTTP 402 payment required")
    assert not _is_billing_error("invalid flavor")


def test_build_python_command_for_url_and_inline() -> None:
    assert _build_python_command("https://example.com/train.py") == ["uv", "run", "https://example.com/train.py"]
    assert _build_python_command("import torch") == ["uv", "run", "-"]


def test_get_tool_specs() -> None:
    specs = get_tool_specs()
    assert len(specs) == 1
    assert specs[0]["name"] == "manage_job"
    props = specs[0]["parameters"]["properties"]
    assert "operation" in props
    assert "script" in props
    assert "command" in props
    assert "job_id" in props


# ---------------------------------------------------------------------------
# Dispatch validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_operation(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({}, _settings(tmp_path))
    assert "Error" in result
    assert "operation" in result.lower()


@pytest.mark.asyncio
async def test_unknown_operation(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({"operation": "fly"}, _settings(tmp_path))
    assert "Error" in result
    assert "fly" in result


@pytest.mark.asyncio
async def test_missing_token(tmp_path: Path) -> None:
    # No token in context or environment.
    with patch("app.tools.jobs.current_hf_token", return_value=None):
        result = await manage_job_handler({"operation": "list"}, _settings(tmp_path))
    assert "Error" in result
    assert "token" in result.lower()


# ---------------------------------------------------------------------------
# run operation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_python_job(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {
                "operation": "run",
                "script": "import torch\nprint('hello')",
                "hardware_flavor": "cpu-basic",
                "timeout": "1h",
            },
            _settings(tmp_path),
        )

    assert "Job launched" in result
    assert "job-123" in result
    call = _FakeHfApi.instances[-1].run_job_calls[-1]
    assert call["flavor"] == "cpu-basic"
    assert call["timeout"] == "1h"
    assert call["command"] == ["uv", "run", "-"]
    assert call["secrets"]["HF_TOKEN"] == "hf-session-token"


@pytest.mark.asyncio
async def test_run_docker_job(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {
                "operation": "run",
                "command": ["duckdb", "-c", "select 1"],
                "image": "duckdb/duckdb",
                "hardware_flavor": "cpu-upgrade",
            },
            _settings(tmp_path),
        )

    assert "Job launched" in result
    call = _FakeHfApi.instances[-1].run_job_calls[-1]
    assert call["command"] == ["duckdb", "-c", "select 1"]
    assert call["image"] == "duckdb/duckdb"


@pytest.mark.asyncio
async def test_run_rejects_both_script_and_command(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {"operation": "run", "script": "print(1)", "command": ["echo", "hi"]},
            _settings(tmp_path),
        )
    assert "Error" in result
    assert "both" in result.lower()


@pytest.mark.asyncio
async def test_run_requires_script_or_command(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({"operation": "run"}, _settings(tmp_path))
    assert "Error" in result


@pytest.mark.asyncio
async def test_run_rejects_unsupported_flavor(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {"operation": "run", "script": "print(1)", "hardware_flavor": "rtx-4090"},
            _settings(tmp_path),
        )
    assert "Error" in result
    assert "rtx-4090" in result


@pytest.mark.asyncio
async def test_run_surfaces_billing_error(tmp_path: Path) -> None:
    class _BillingApi(_FakeHfApi):
        def run_job(self, **kwargs):
            raise RuntimeError("namespace has no available credits for jobs")

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _BillingApi
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        with _token_context():
            result = await manage_job_handler(
                {"operation": "run", "script": "print(1)"},
                _settings(tmp_path),
            )

    assert "Error" in result
    assert "credits" in result.lower()


# ---------------------------------------------------------------------------
# list / inspect / logs / cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_defaults_to_running(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({"operation": "list"}, _settings(tmp_path))
    assert "Jobs (1)" in result
    assert "job-1" in result
    assert "job-2" not in result  # completed filtered out


@pytest.mark.asyncio
async def test_list_all_includes_every_status(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {"operation": "list", "all": True},
            _settings(tmp_path),
        )
    assert "Jobs (2)" in result


@pytest.mark.asyncio
async def test_list_empty(tmp_path: Path) -> None:
    class _EmptyApi(_FakeHfApi):
        def list_jobs(self, namespace=None):
            return []

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _EmptyApi
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        with _token_context():
            result = await manage_job_handler({"operation": "list"}, _settings(tmp_path))
    assert "No jobs found" in result


@pytest.mark.asyncio
async def test_inspect_requires_job_id(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({"operation": "inspect"}, _settings(tmp_path))
    assert "Error" in result
    assert "job_id" in result


@pytest.mark.asyncio
async def test_inspect_success(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {"operation": "inspect", "job_id": "job-1"},
            _settings(tmp_path),
        )
    assert "Job details" in result
    assert "job-1" in result


@pytest.mark.asyncio
async def test_logs_success(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {"operation": "logs", "job_id": "job-1"},
            _settings(tmp_path),
        )
    assert "Logs for job-1" in result
    assert "step 1 ok" in result


@pytest.mark.asyncio
async def test_logs_requires_job_id(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({"operation": "logs"}, _settings(tmp_path))
    assert "Error" in result


@pytest.mark.asyncio
async def test_logs_empty(tmp_path: Path) -> None:
    class _NoLogsApi(_FakeHfApi):
        def fetch_job_logs(self, job_id, namespace=None):
            return iter([])

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _NoLogsApi
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        with _token_context():
            result = await manage_job_handler(
                {"operation": "logs", "job_id": "job-1"},
                _settings(tmp_path),
            )
    assert "No logs available" in result


@pytest.mark.asyncio
async def test_logs_truncates_long_output(tmp_path: Path) -> None:
    class _VerboseApi(_FakeHfApi):
        def fetch_job_logs(self, job_id, namespace=None):
            return iter([f"line {i}" for i in range(1000)])

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _VerboseApi
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        with _token_context():
            result = await manage_job_handler(
                {"operation": "logs", "job_id": "job-1"},
                _settings(tmp_path),
            )
    assert "first 500 of 1000" in result


@pytest.mark.asyncio
async def test_cancel_success(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler(
            {"operation": "cancel", "job_id": "job-1"},
            _settings(tmp_path),
        )
    assert "cancelled" in result.lower()
    assert "job-1" in result


@pytest.mark.asyncio
async def test_cancel_requires_job_id(tmp_path: Path) -> None:
    with _token_context():
        result = await manage_job_handler({"operation": "cancel"}, _settings(tmp_path))
    assert "Error" in result


@pytest.mark.asyncio
async def test_cancel_surfaces_api_error(tmp_path: Path) -> None:
    class _FailApi(_FakeHfApi):
        def cancel_job(self, job_id, namespace=None):
            raise RuntimeError("not authorized to cancel")

    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _FailApi
    with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
        with _token_context():
            result = await manage_job_handler(
                {"operation": "cancel", "job_id": "job-1"},
                _settings(tmp_path),
            )
    assert "Error" in result
    assert "not authorized" in result
