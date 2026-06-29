"""Tests for model publishing, model card, and final report tooling."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agent.loop import _create_tool_registry
from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.publishing import get_tool_specs, publish_model_report_handler


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def _token_context(session_id: str = "session-1"):
    return use_tool_execution_context(ToolExecutionContext(session_id=session_id, hf_token="hf-session-token"))


class _FakeHfApi:
    instances: list["_FakeHfApi"] = []

    def __init__(self, token=None):
        self.token = token
        self.create_repo_calls: list[dict] = []
        self.upload_folder_calls: list[dict] = []
        _FakeHfApi.instances.append(self)

    def create_repo(self, **kwargs):
        self.create_repo_calls.append(kwargs)
        return types.SimpleNamespace(url=f"https://huggingface.co/{kwargs['repo_id']}")

    def upload_folder(self, **kwargs):
        self.upload_folder_calls.append(kwargs)
        return "commit-123"


@pytest.fixture(autouse=True)
def _stub_huggingface_hub():
    fake_module = types.ModuleType("huggingface_hub")
    fake_module.HfApi = _FakeHfApi
    original = sys.modules.get("huggingface_hub")
    _FakeHfApi.instances.clear()
    sys.modules["huggingface_hub"] = fake_module
    try:
        yield
    finally:
        _FakeHfApi.instances.clear()
        if original is not None:
            sys.modules["huggingface_hub"] = original
        else:
            sys.modules.pop("huggingface_hub", None)


def _payload(**overrides):
    payload = {
        "repo_id": "owner/tiny-classifier",
        "model_name": "Tiny Classifier",
        "task": "text-classification",
        "license": "apache-2.0",
        "datasets": ["owner/sentiment-data"],
        "base_models": ["distilbert-base-uncased"],
        "papers": ["Attention Is All You Need"],
        "jobs": ["job-123"],
        "sandbox_commands": ["python smoke.py"],
        "metrics": {"accuracy": 0.91, "f1": 0.88},
        "recommendation": "Publish this model; it met the target accuracy with acceptable validation loss.",
        "limitations": ["Evaluated on a small validation split."],
        "output_dir": "reports/tiny-classifier",
    }
    payload.update(overrides)
    return payload


def test_get_tool_specs() -> None:
    specs = get_tool_specs()
    assert len(specs) == 1
    assert specs[0]["name"] == "publish_model_report"
    props = specs[0]["parameters"]["properties"]
    assert "repo_id" in props
    assert "publish" in props
    assert "metrics" in props


@pytest.mark.asyncio
async def test_prepare_writes_model_card_report_and_manifest(tmp_path: Path) -> None:
    with _token_context():
        result = await publish_model_report_handler(_payload(), _settings(tmp_path))

    output_dir = tmp_path / "reports" / "tiny-classifier"
    readme = output_dir / "README.md"
    report = output_dir / "FINAL_REPORT.md"
    manifest = output_dir / "publish_manifest.json"

    assert "Prepared model publishing assets" in result
    assert readme.exists()
    assert report.exists()
    assert manifest.exists()

    readme_text = readme.read_text(encoding="utf-8")
    assert "license: apache-2.0" in readme_text
    assert "- text-classification" in readme_text
    assert "# Tiny Classifier" in readme_text
    assert "owner/sentiment-data" in readme_text
    assert "accuracy: 0.91" in readme_text
    assert "AutoModel" in readme_text

    report_text = report.read_text(encoding="utf-8")
    assert "## Reproducibility" in report_text
    assert "job-123" in report_text
    assert "python smoke.py" in report_text
    assert "Publish this model" in report_text

    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["repo_id"] == "owner/tiny-classifier"
    assert manifest_data["files"] == ["README.md", "FINAL_REPORT.md", "publish_manifest.json"]
    assert "hf-session-token" not in readme_text + report_text + json.dumps(manifest_data)


@pytest.mark.asyncio
async def test_rejects_output_dir_outside_workspace(tmp_path: Path) -> None:
    with _token_context():
        result = await publish_model_report_handler(_payload(output_dir="../outside"), _settings(tmp_path))

    assert "Error" in result
    assert "outside workspace" in result.lower()


@pytest.mark.asyncio
async def test_publish_requires_hf_token(tmp_path: Path) -> None:
    with patch("app.tools.publishing.current_hf_token", return_value=None):
        result = await publish_model_report_handler(_payload(publish=True), _settings(tmp_path))

    assert "Error" in result
    assert "token" in result.lower()


@pytest.mark.asyncio
async def test_publish_uploads_prepared_folder_to_hub(tmp_path: Path) -> None:
    with _token_context():
        result = await publish_model_report_handler(_payload(publish=True, private=True), _settings(tmp_path))

    assert "Published model assets" in result
    api = _FakeHfApi.instances[-1]
    assert api.token == "hf-session-token"
    assert api.create_repo_calls[-1] == {
        "repo_id": "owner/tiny-classifier",
        "repo_type": "model",
        "private": True,
        "exist_ok": True,
    }
    upload_call = api.upload_folder_calls[-1]
    assert upload_call["repo_id"] == "owner/tiny-classifier"
    assert upload_call["repo_type"] == "model"
    assert Path(upload_call["folder_path"]).name == "tiny-classifier"
    assert "ML Copilot" in upload_call["commit_message"]


def test_tool_registry_includes_publish_model_report(tmp_path: Path) -> None:
    registry = _create_tool_registry(_settings(tmp_path))
    assert registry.get("publish_model_report").name == "publish_model_report"
