"""Tests for Hugging Face Hub discovery tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.hub import inspect_hub_repo_handler, search_hub_handler


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    responses: dict[str, FakeResponse] = {}
    instances: list["FakeAsyncClient"] = []

    def __init__(self, *args, **kwargs):
        self.headers = kwargs.get("headers", {})
        self.requests: list[tuple[str, dict | None]] = []
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url: str, params=None):
        self.requests.append((url, params))
        return self.responses[url]


@pytest.mark.asyncio
async def test_search_hub_ranks_task_and_license_matches(tmp_path: Path, monkeypatch) -> None:
    FakeAsyncClient.responses = {
        "https://huggingface.co/api/models": FakeResponse(
            [
                {
                    "id": "org/general-model",
                    "downloads": 1000,
                    "likes": 10,
                    "pipeline_tag": "text-generation",
                    "tags": ["license:apache-2.0"],
                },
                {
                    "id": "org/sentiment-model",
                    "downloads": 500,
                    "likes": 5,
                    "pipeline_tag": "text-classification",
                    "tags": ["license:mit", "transformers"],
                },
            ]
        )
    }
    FakeAsyncClient.instances = []
    monkeypatch.setattr("app.tools.hub.httpx.AsyncClient", FakeAsyncClient)

    with use_tool_execution_context(ToolExecutionContext(session_id="session-1", hf_token="hf-token")):
        result = await search_hub_handler(
            {
                "repo_type": "model",
                "query": "sentiment",
                "task": "text-classification",
                "license": "mit",
            },
            _settings(tmp_path),
        )

    assert result.index("org/sentiment-model") < result.index("org/general-model")
    assert "task match" in result
    assert "license match" in result
    assert FakeAsyncClient.instances[0].headers["Authorization"] == "Bearer hf-token"
    assert FakeAsyncClient.instances[0].requests[0][1]["pipeline_tag"] == "text-classification"


@pytest.mark.asyncio
async def test_inspect_dataset_repo_reports_required_column_fit(tmp_path: Path, monkeypatch) -> None:
    repo_id = "org/chat-data"
    FakeAsyncClient.responses = {
        f"https://huggingface.co/api/datasets/{repo_id}": FakeResponse(
            {
                "id": repo_id,
                "downloads": 2000,
                "likes": 20,
                "tags": ["license:apache-2.0", "parquet"],
            }
        ),
        "https://datasets-server.huggingface.co/splits": FakeResponse(
            {"splits": [{"config": "default", "split": "train"}]}
        ),
        "https://datasets-server.huggingface.co/info": FakeResponse(
            {
                "dataset_info": {
                    "features": {
                        "messages": {"_type": "Sequence"},
                        "source": {"dtype": "string"},
                    }
                }
            }
        ),
    }
    FakeAsyncClient.instances = []
    monkeypatch.setattr("app.tools.hub.httpx.AsyncClient", FakeAsyncClient)

    result = await inspect_hub_repo_handler(
        {
            "repo_id": repo_id,
            "repo_type": "dataset",
            "required_columns": ["messages", "source"],
        },
        _settings(tmp_path),
    )

    assert "Dataset Schema (default/train)" in result
    assert "| messages | Sequence |" in result
    assert "**Required columns check:** pass" in result
