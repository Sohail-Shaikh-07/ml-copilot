"""Tests for sandbox-first experiment workspace tooling."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.sandbox import experiment_workspace_handler, get_tool_specs


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def _token_context(session_id: str = "session-1"):
    return use_tool_execution_context(ToolExecutionContext(session_id=session_id, hf_token="hf-session-token"))


class _FakeHfApi:
    instances: list["_FakeHfApi"] = []

    def __init__(self, token=None):
        self.token = token
        self.create_repo_calls: list[dict] = []
        self.upload_file_calls: list[dict] = []
        self.secret_calls: list[dict] = []
        self.hardware_calls: list[dict] = []
        self.delete_repo_calls: list[dict] = []
        _FakeHfApi.instances.append(self)

    def create_repo(self, **kwargs):
        self.create_repo_calls.append(kwargs)
        return types.SimpleNamespace(url=f"https://huggingface.co/spaces/{kwargs['repo_id']}")

    def upload_file(self, **kwargs):
        self.upload_file_calls.append(kwargs)

    def add_space_secret(self, **kwargs):
        self.secret_calls.append(kwargs)

    def request_space_hardware(self, **kwargs):
        self.hardware_calls.append(kwargs)

    def delete_repo(self, **kwargs):
        self.delete_repo_calls.append(kwargs)


@pytest.fixture(autouse=True)
def _reset_fake_api():
    _FakeHfApi.instances.clear()
    yield
    _FakeHfApi.instances.clear()


@pytest.fixture(autouse=True)
def _stub_huggingface_hub():
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


def _metadata_file(tmp_path: Path, session_id: str = "session-1") -> Path:
    return tmp_path / ".ml-copilot" / "sandboxes" / f"{session_id}.json"


def _write_record(tmp_path: Path, *, session_id: str = "session-1") -> dict[str, str]:
    record = {
        "session_id": session_id,
        "space_id": "owner/ml-copilot-sandbox-session-1",
        "hardware": "cpu-basic",
        "url": "https://owner-ml-copilot-sandbox-session-1.hf.space",
        "api_token": "sandbox-secret-token",
        "created_at": "2026-06-29T00:00:00Z",
    }
    path = _metadata_file(tmp_path, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return record


def test_get_tool_specs() -> None:
    specs = get_tool_specs()
    assert len(specs) == 1
    assert specs[0]["name"] == "experiment_workspace"
    props = specs[0]["parameters"]["properties"]
    assert props["operation"]["enum"] == ["create", "status", "write", "read", "run", "teardown"]
    assert "path" in props
    assert "command" in props
    assert "timeout_seconds" in props


@pytest.mark.asyncio
async def test_create_requires_hf_token(tmp_path: Path) -> None:
    with patch("app.tools.sandbox.current_hf_token", return_value=None):
        result = await experiment_workspace_handler({"operation": "create"}, _settings(tmp_path))
    assert "Error" in result
    assert "token" in result.lower()


@pytest.mark.asyncio
async def test_create_workspace_persists_metadata_without_leaking_control_token(tmp_path: Path) -> None:
    with _token_context():
        result = await experiment_workspace_handler(
            {"operation": "create", "namespace": "owner", "hardware": "cpu-basic"},
            _settings(tmp_path),
        )

    assert "Experiment workspace created" in result
    assert "owner/ml-copilot-sandbox-session-1" in result
    assert "sandbox_api_token" not in result.lower()
    assert "api_token" not in result.lower()

    api = _FakeHfApi.instances[-1]
    assert api.token == "hf-session-token"
    assert api.create_repo_calls[-1]["repo_id"] == "owner/ml-copilot-sandbox-session-1"
    assert api.create_repo_calls[-1]["repo_type"] == "space"
    assert api.secret_calls[-1]["key"] == "SANDBOX_API_TOKEN"
    assert api.hardware_calls[-1]["hardware"] == "cpu-basic"
    assert {call["path_in_repo"] for call in api.upload_file_calls} == {"Dockerfile", "app.py"}

    metadata = json.loads(_metadata_file(tmp_path).read_text(encoding="utf-8"))
    assert metadata["session_id"] == "session-1"
    assert metadata["space_id"] == "owner/ml-copilot-sandbox-session-1"
    assert metadata["api_token"]


@pytest.mark.asyncio
async def test_write_rejects_path_escape(tmp_path: Path) -> None:
    _write_record(tmp_path)
    with _token_context():
        result = await experiment_workspace_handler(
            {"operation": "write", "path": "../secret.py", "content": "print(1)"},
            _settings(tmp_path),
        )
    assert "Error" in result
    assert "path" in result.lower()


@pytest.mark.asyncio
async def test_remote_operations_require_hf_token(tmp_path: Path) -> None:
    _write_record(tmp_path)
    with patch("app.tools.sandbox.current_hf_token", return_value=None):
        with use_tool_execution_context(ToolExecutionContext(session_id="session-1", hf_token=None)):
            result = await experiment_workspace_handler(
                {"operation": "run", "command": "python scripts/smoke.py"},
                _settings(tmp_path),
            )
    assert "Error" in result
    assert "token" in result.lower()


@pytest.mark.asyncio
async def test_write_calls_remote_workspace_with_control_plane_auth(tmp_path: Path) -> None:
    _write_record(tmp_path)
    captured: dict[str, object] = {}

    async def fake_post(record, endpoint, payload, *, timeout_seconds):
        captured.update(
            {
                "headers": {
                    "Authorization": "Bearer hf-session-token",
                    "X-Sandbox-Authorization": f"Bearer {record.api_token}",
                },
                "endpoint": endpoint,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"path": payload["path"], "bytes_written": len(payload["content"])}

    with patch("app.tools.sandbox._post_sandbox", side_effect=fake_post):
        with _token_context():
            result = await experiment_workspace_handler(
                {"operation": "write", "path": "scripts/smoke.py", "content": "print('ok')"},
                _settings(tmp_path),
            )

    assert "Wrote scripts/smoke.py" in result
    assert captured["endpoint"] == "/api/write"
    assert captured["payload"] == {"path": "scripts/smoke.py", "content": "print('ok')"}
    assert captured["headers"]["X-Sandbox-Authorization"] == "Bearer sandbox-secret-token"


@pytest.mark.asyncio
async def test_read_returns_bounded_remote_file_content(tmp_path: Path) -> None:
    _write_record(tmp_path)

    async def fake_post(record, endpoint, payload, *, timeout_seconds):
        assert endpoint == "/api/read"
        assert payload == {"path": "logs/out.txt", "max_bytes": 1200}
        return {"path": "logs/out.txt", "content": "hello\nworld", "truncated": False}

    with patch("app.tools.sandbox._post_sandbox", side_effect=fake_post):
        with _token_context():
            result = await experiment_workspace_handler(
                {"operation": "read", "path": "logs/out.txt", "max_bytes": 1200},
                _settings(tmp_path),
            )

    assert "logs/out.txt" in result
    assert "hello\nworld" in result


@pytest.mark.asyncio
async def test_run_calls_remote_workspace_and_formats_output(tmp_path: Path) -> None:
    _write_record(tmp_path)

    async def fake_post(record, endpoint, payload, *, timeout_seconds):
        assert endpoint == "/api/run"
        assert payload == {"command": "python scripts/smoke.py", "timeout_seconds": 30}
        assert timeout_seconds == 35
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "timed_out": False}

    with patch("app.tools.sandbox._post_sandbox", side_effect=fake_post):
        with _token_context():
            result = await experiment_workspace_handler(
                {"operation": "run", "command": "python scripts/smoke.py", "timeout_seconds": 30},
                _settings(tmp_path),
            )

    assert "Exit code: 0" in result
    assert "ok" in result


@pytest.mark.asyncio
async def test_teardown_deletes_space_and_metadata(tmp_path: Path) -> None:
    _write_record(tmp_path)
    with _token_context():
        result = await experiment_workspace_handler({"operation": "teardown"}, _settings(tmp_path))

    assert "torn down" in result.lower()
    assert not _metadata_file(tmp_path).exists()
    assert _FakeHfApi.instances[-1].delete_repo_calls[-1] == {
        "repo_id": "owner/ml-copilot-sandbox-session-1",
        "repo_type": "space",
    }
