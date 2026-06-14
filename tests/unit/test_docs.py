"""Tests for app.tools.docs module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import AppPaths, AppSettings
from app.tools.docs import (
    DOC_ENDPOINTS,
    _format_results,
    _search_docs,
    fetch_doc_page_handler,
    get_tool_specs,
    search_docs_handler,
)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


class TestFormatResults:
    def test_no_query(self) -> None:
        items = [{"title": "Overview", "url": "https://hf.co/docs/trl", "glimpse": "TRL intro..."}]
        result = _format_results("trl", items, total=10)
        assert "Documentation" in result
        assert "Overview" in result
        assert "1 shown" in result

    def test_with_query(self) -> None:
        items = [{"title": "DPO Trainer", "url": "https://hf.co/docs/trl/dpo", "glimpse": "DPO...", "score": 3.5}]
        result = _format_results("trl", items, total=50, query="dpo")
        assert "dpo" in result
        assert "3.50" in result
        assert "1 result" in result


class TestSearchDocs:
    @pytest.mark.asyncio
    async def test_search_indexed_docs(self) -> None:
        docs = [
            {
                "title": "LoRA Training",
                "url": "https://hf.co/docs/peft/lora",
                "md_url": "",
                "glimpse": "LoRA guide",
                "content": "Low-rank adaptation training tutorial for PEFT",
                "section": "peft",
            },
            {
                "title": "Installation",
                "url": "https://hf.co/docs/peft/install",
                "md_url": "",
                "glimpse": "Install peft",
                "content": "pip install peft",
                "section": "peft",
            },
        ]
        results, msg = await _search_docs("peft", docs, "lora training", limit=5)
        assert len(results) >= 1
        assert results[0]["title"] == "LoRA Training"
        assert msg is None

    @pytest.mark.asyncio
    async def test_no_matches(self) -> None:
        docs = [
            {"title": "Install", "url": "u", "md_url": "", "glimpse": "g", "content": "pip install", "section": "x"},
        ]
        results, msg = await _search_docs("x", docs, "xyznonexistent", limit=5)
        assert results == []
        assert msg is not None


class TestSearchDocsHandler:
    @pytest.mark.asyncio
    async def test_missing_endpoint(self, tmp_path: Path) -> None:
        result = await search_docs_handler({}, _settings(tmp_path))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_invalid_endpoint(self, tmp_path: Path) -> None:
        result = await search_docs_handler({"endpoint": "nonexistent"}, _settings(tmp_path))
        assert "Unknown endpoint" in result

    @pytest.mark.asyncio
    async def test_valid_endpoint_mocked(self, tmp_path: Path) -> None:
        mock_docs = [
            {
                "title": "Quickstart",
                "url": "https://hf.co/docs/trl/quickstart",
                "md_url": "",
                "glimpse": "Get started with TRL",
                "content": "TRL quickstart guide",
                "section": "trl",
            },
        ]
        with patch("app.tools.docs._get_docs", new_callable=AsyncMock) as mock:
            mock.return_value = mock_docs
            result = await search_docs_handler({"endpoint": "trl"}, _settings(tmp_path))
        assert "Quickstart" in result
        assert "Documentation" in result

    @pytest.mark.asyncio
    async def test_with_query_mocked(self, tmp_path: Path) -> None:
        mock_docs = [
            {
                "title": "DPO",
                "url": "u1",
                "md_url": "",
                "glimpse": "DPO trainer",
                "content": "Direct preference optimization trainer",
                "section": "trl",
            },
            {
                "title": "SFT",
                "url": "u2",
                "md_url": "",
                "glimpse": "SFT trainer",
                "content": "Supervised fine-tuning",
                "section": "trl",
            },
        ]
        with patch("app.tools.docs._get_docs", new_callable=AsyncMock) as mock:
            mock.return_value = mock_docs
            result = await search_docs_handler({"endpoint": "trl", "query": "dpo"}, _settings(tmp_path))
        assert "DPO" in result

    @pytest.mark.asyncio
    async def test_invalid_max_results(self, tmp_path: Path) -> None:
        result = await search_docs_handler({"endpoint": "trl", "max_results": -1}, _settings(tmp_path))
        assert "Error" in result


class TestFetchDocPageHandler:
    @pytest.mark.asyncio
    async def test_missing_url(self, tmp_path: Path) -> None:
        result = await fetch_doc_page_handler({}, _settings(tmp_path))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_successful_fetch(self, tmp_path: Path) -> None:
        mock_resp = MagicMock()
        mock_resp.text = "# DPO Trainer\n\nContent here."
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await fetch_doc_page_handler(
                {"url": "https://huggingface.co/docs/trl/dpo_trainer"}, _settings(tmp_path)
            )
        assert "DPO Trainer" in result

    @pytest.mark.asyncio
    async def test_appends_md_extension(self, tmp_path: Path) -> None:
        mock_resp = MagicMock()
        mock_resp.text = "content"
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await fetch_doc_page_handler({"url": "https://huggingface.co/docs/trl/sft"}, _settings(tmp_path))
            call_url = mock_client.get.call_args[0][0]
        assert call_url.endswith(".md")

    @pytest.mark.asyncio
    async def test_rejects_non_hf_docs_urls(self, tmp_path: Path) -> None:
        result = await fetch_doc_page_handler({"url": "https://example.com/docs/trl/sft"}, _settings(tmp_path))
        assert "HuggingFace docs URLs" in result


class TestGetToolSpecs:
    def test_returns_two_tools(self) -> None:
        specs = get_tool_specs()
        assert len(specs) == 2
        names = {s["name"] for s in specs}
        assert "search_docs" in names
        assert "fetch_doc_page" in names

    def test_endpoints_enum(self) -> None:
        specs = get_tool_specs()
        search_spec = next(s for s in specs if s["name"] == "search_docs")
        assert "enum" in search_spec["parameters"]["properties"]["endpoint"]
        assert "transformers" in search_spec["parameters"]["properties"]["endpoint"]["enum"]


class TestDocEndpoints:
    def test_key_endpoints_present(self) -> None:
        assert "transformers" in DOC_ENDPOINTS
        assert "datasets" in DOC_ENDPOINTS
        assert "peft" in DOC_ENDPOINTS
        assert "trl" in DOC_ENDPOINTS
