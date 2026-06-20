"""Tests for app.tools.datasets module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.datasets import (
    _inspect_csv,
    _inspect_json,
    _inspect_jsonl,
    _looks_like_local_path,
    get_tool_specs,
    ingest_dataset_handler,
    inspect_dataset_handler,
)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


class TestLooksLikeLocalPath:
    def test_existing_file(self, tmp_path: Path) -> None:
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "train.csv").write_text("x")
        assert _looks_like_local_path("data/train.csv", tmp_path) is True

    def test_nonexistent(self, tmp_path: Path) -> None:
        assert _looks_like_local_path("user/dataset", tmp_path) is False


@pytest.mark.asyncio
async def test_inspect_hf_dataset_uses_session_token(tmp_path: Path) -> None:
    class FakeResponse:
        def __init__(self, payload: dict[str, object]):
            self._payload = payload

        def json(self) -> dict[str, object]:
            return self._payload

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        instances: list["FakeAsyncClient"] = []

        def __init__(self, *args, **kwargs):
            self.headers = kwargs.get("headers", {})
            FakeAsyncClient.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            if url.endswith("/is-valid"):
                return FakeResponse({"preview": True})
            if url.endswith("/splits"):
                return FakeResponse({"splits": [{"config": "default", "split": "train"}]})
            if url.endswith("/info"):
                return FakeResponse({"dataset_info": {"features": {"text": {"dtype": "string"}}}})
            if url.endswith("/first-rows"):
                return FakeResponse({"rows": [{"row": {"text": "hello"}}]})
            return FakeResponse({})

    with patch("app.tools.datasets.httpx.AsyncClient", new=FakeAsyncClient):
        with use_tool_execution_context(ToolExecutionContext(session_id="session-1", hf_token="hf-session-token")):
            result = await inspect_dataset_handler({"source": "hf-user/imdb"}, _settings(tmp_path))

    assert "hf-user/imdb (Hugging Face)" in result
    assert FakeAsyncClient.instances[0].headers["Authorization"] == "Bearer hf-session-token"


class TestInspectCsv:
    def test_basic_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,,London\n")
        result = _inspect_csv(csv_file, sample_rows=2)
        assert "data.csv" in result
        assert "Columns:** 3" in result
        assert "name" in result
        assert "Alice" in result

    def test_missing_values(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "gaps.csv"
        csv_file.write_text("a,b\n1,\n2,\n3,x\n")
        result = _inspect_csv(csv_file, sample_rows=1)
        assert "2/3" in result

    def test_empty_file(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        result = _inspect_csv(csv_file, sample_rows=1)
        assert "empty" in result.lower()

    def test_tsv(self, tmp_path: Path) -> None:
        tsv_file = tmp_path / "data.tsv"
        tsv_file.write_text("col1\tcol2\nval1\tval2\n")
        result = _inspect_csv(tsv_file, sample_rows=1, delimiter="\t")
        assert "col1" in result
        assert "TSV" in result


class TestInspectJsonl:
    def test_basic_jsonl(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"text":"hello","label":1}\n{"text":"world","label":0}\n')
        result = _inspect_jsonl(f, sample_rows=2)
        assert "data.jsonl" in result
        assert "text" in result
        assert "hello" in result

    def test_missing_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"a":1,"b":2}\n{"a":3}\n')
        result = _inspect_jsonl(f, sample_rows=1)
        assert "1/2" in result

    def test_parse_errors(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text('{"a":1}\nnot json\n{"a":2}\n')
        result = _inspect_jsonl(f, sample_rows=1)
        assert "Parse errors" in result

    def test_empty_jsonl(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("\n\n")
        result = _inspect_jsonl(f, sample_rows=1)
        assert "Error" in result


class TestInspectJson:
    def test_json_array(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text(json.dumps([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]))
        result = _inspect_json(f, sample_rows=2)
        assert "JSON array" in result
        assert "a" in result

    def test_json_falls_back_to_jsonl(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"x":1}\n{"x":2}\n')
        result = _inspect_json(f, sample_rows=1)
        assert "JSONL" in result


class TestInspectDatasetHandler:
    @pytest.mark.asyncio
    async def test_local_csv(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "train.csv"
        csv_file.write_text("x,y\n1,2\n3,4\n")
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "train.csv"}, settings)
        assert "train.csv" in result

    @pytest.mark.asyncio
    async def test_missing_source(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({}, settings)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_nonexistent_file(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "nope.csv"}, settings)
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_workspace_escape(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "../../etc/passwd"}, settings)
        assert "outside workspace" in result.lower()

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("binary")
        settings = _settings(tmp_path)
        result = await inspect_dataset_handler({"source": "data.xlsx"}, settings)
        assert "Unsupported" in result

    @pytest.mark.asyncio
    async def test_hf_dataset_not_misrouted(self, tmp_path: Path) -> None:
        """HF dataset names with extensions should route to HF, not local."""
        settings = _settings(tmp_path)
        with patch("app.tools.datasets._inspect_hf", new_callable=AsyncMock) as mock_hf:
            mock_hf.return_value = "## user/data.csv (Hugging Face)"
            result = await inspect_dataset_handler({"source": "user/data.csv"}, settings)
        assert "Hugging Face" in result

    @pytest.mark.asyncio
    async def test_hf_dataset(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        mock_responses = [
            {"preview": True},
            {"splits": [{"config": "default", "split": "train"}]},
        ]
        with patch("app.tools.datasets._hf_parallel", new_callable=AsyncMock) as mock_hf:
            mock_hf.side_effect = [
                mock_responses,
                [{"dataset_info": {"features": {"text": {"dtype": "string"}}}}, {"rows": []}],
            ]
            result = await inspect_dataset_handler({"source": "username/dataset"}, settings)
        assert "Hugging Face" in result

    @pytest.mark.asyncio
    async def test_bare_hf_dataset_name_routes_to_hub(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        with patch("app.tools.datasets._inspect_hf", new_callable=AsyncMock) as mock_hf:
            mock_hf.return_value = "## imdb (Hugging Face)"
            result = await inspect_dataset_handler({"source": "imdb"}, settings)
        assert "Hugging Face" in result
        mock_hf.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_source_kind_can_force_local_routing(self, tmp_path: Path) -> None:
        (tmp_path / "dataset").write_text("text,label\nhello,1\n", encoding="utf-8")
        result = await inspect_dataset_handler(
            {"source": "dataset", "source_kind": "local"},
            _settings(tmp_path),
        )
        assert "Unsupported file type" in result


@pytest.mark.asyncio
async def test_ingest_dataset_copies_and_previews_byod_file(tmp_path: Path) -> None:
    source = tmp_path / "uploads" / "train.csv"
    source.parent.mkdir()
    source.write_text("text,label\nhello,1\nworld,0\n", encoding="utf-8")

    result = await ingest_dataset_handler(
        {"source": "uploads/train.csv", "sample_rows": 2},
        _settings(tmp_path),
    )

    managed = tmp_path / ".ml-copilot" / "datasets" / "train.csv"
    assert managed.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert "BYOD dataset ingested" in result
    assert ".ml-copilot/datasets/train.csv" in result
    assert "hello" in result


class TestGetToolSpecs:
    def test_spec(self) -> None:
        specs = get_tool_specs()
        assert [spec["name"] for spec in specs] == ["inspect_dataset", "ingest_dataset"]
        assert "source" in specs[0]["parameters"]["properties"]
