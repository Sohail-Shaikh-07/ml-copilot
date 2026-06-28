"""Tests for app.tools.papers module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import AppPaths, AppSettings
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.papers import (
    _extract_recipe_values,
    _find_section,
    _format_paper_details,
    _format_training_recipe,
    _normalize_arxiv_id,
    _parse_paper_html,
    _select_recipe_sections,
    extract_training_recipe_handler,
    get_tool_specs,
    paper_citation_graph_handler,
    paper_details_handler,
    read_paper_handler,
)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


# ---------------------------------------------------------------------------
# paper_details (existing behavior preserved)
# ---------------------------------------------------------------------------


def test_normalize_arxiv_id_from_urls() -> None:
    assert _normalize_arxiv_id("https://huggingface.co/papers/2305.18290") == "2305.18290"
    assert _normalize_arxiv_id("https://arxiv.org/abs/2305.18290") == "2305.18290"
    assert _normalize_arxiv_id(None) == ""


def test_format_paper_details() -> None:
    paper = {
        "id": "2305.18290",
        "title": "A Sample Paper",
        "upvotes": 42,
        "summary": "Abstract text that explains the paper.",
        "ai_summary": "Shorter AI summary.",
        "ai_keywords": ["ml", "agents"],
        "githubRepo": "org/repo",
        "githubStars": 99,
        "authors": [{"name": "Ada"}, {"name": "Bob"}],
    }

    result = _format_paper_details(paper)

    assert "A Sample Paper" in result
    assert "2305.18290" in result
    assert "Ada, Bob" in result
    assert "ml, agents" in result
    assert "org/repo" in result
    assert "AI Summary" in result
    assert "Abstract" in result


@pytest.mark.asyncio
async def test_paper_details_handler_uses_session_token(tmp_path: Path) -> None:
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
            return FakeResponse(
                {
                    "id": "2305.18290",
                    "title": "A Sample Paper",
                    "upvotes": 10,
                    "summary": "Paper abstract.",
                    "authors": [{"name": "Ada"}],
                }
            )

    with patch("app.tools.papers.httpx.AsyncClient", new=FakeAsyncClient):
        with use_tool_execution_context(ToolExecutionContext(session_id="session-1", hf_token="hf-session-token")):
            result = await paper_details_handler(
                {"arxiv_id": "https://huggingface.co/papers/2305.18290"},
                _settings(tmp_path),
            )

    assert "A Sample Paper" in result
    assert FakeAsyncClient.instances[0].headers["Authorization"] == "Bearer hf-session-token"


@pytest.mark.asyncio
async def test_paper_details_handler_success(tmp_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "id": "2305.18290",
        "title": "A Sample Paper",
        "upvotes": 10,
        "summary": "Paper abstract.",
        "authors": [{"name": "Ada"}],
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await paper_details_handler(
            {"arxiv_id": "https://huggingface.co/papers/2305.18290"},
            _settings(tmp_path),
        )

    assert "A Sample Paper" in result
    assert "Ada" in result
    assert "huggingface.co/papers/2305.18290" in result


@pytest.mark.asyncio
async def test_paper_details_handler_missing_id(tmp_path: Path) -> None:
    result = await paper_details_handler({}, _settings(tmp_path))

    assert "Error" in result


@pytest.mark.asyncio
async def test_paper_details_handler_not_found(tmp_path: Path) -> None:
    request = httpx.Request("GET", "https://huggingface.co/api/papers/2305.18290")
    response = httpx.Response(404, request=request)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await paper_details_handler({"arxiv_id": "2305.18290"}, _settings(tmp_path))

    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# Tool specs
# ---------------------------------------------------------------------------


def test_get_tool_specs() -> None:
    specs = get_tool_specs()
    names = [spec["name"] for spec in specs]

    assert "paper_details" in names
    assert "paper_citation_graph" in names
    assert "read_paper" in names
    assert "extract_training_recipe" in names
    for spec in specs:
        assert "arxiv_id" in spec["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Citation graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_citation_graph_missing_id(tmp_path: Path) -> None:
    result = await paper_citation_graph_handler({}, _settings(tmp_path))
    assert "Error" in result


@pytest.mark.asyncio
async def test_citation_graph_invalid_direction(tmp_path: Path) -> None:
    result = await paper_citation_graph_handler(
        {"arxiv_id": "2305.18290", "direction": "sideways"},
        _settings(tmp_path),
    )
    assert "Error" in result
    assert "direction" in result.lower()


@pytest.mark.asyncio
async def test_citation_graph_success(tmp_path: Path) -> None:
    async def fake_fetch(client, s2_id, side, limit):
        if side == "references":
            return [
                {
                    "citedPaper": {
                        "title": "Referenced Work",
                        "year": 2021,
                        "citationCount": 30,
                        "externalIds": {"ArXiv": "2101.00001"},
                    },
                    "isInfluential": False,
                }
            ]
        return [
            {
                "citingPaper": {
                    "title": "Citing Work",
                    "year": 2024,
                    "citationCount": 5,
                    "externalIds": {"ArXiv": "2401.00002"},
                },
                "isInfluential": True,
                "intents": ["methodology"],
                "contexts": ["We build on the method from 2305.18290."],
            }
        ]

    with patch("app.tools.papers._fetch_citation_side", new=fake_fetch):
        result = await paper_citation_graph_handler(
            {"arxiv_id": "2305.18290", "direction": "both"},
            _settings(tmp_path),
        )

    assert "Citation graph for 2305.18290" in result
    assert "References (1)" in result
    assert "Referenced Work" in result
    assert "Citations (1)" in result
    assert "Citing Work" in result
    assert "[influential]" in result
    assert "Intent: methodology" in result


@pytest.mark.asyncio
async def test_citation_graph_unavailable(tmp_path: Path) -> None:
    async def fake_fetch(client, s2_id, side, limit):
        return None

    with patch("app.tools.papers._fetch_citation_side", new=fake_fetch):
        result = await paper_citation_graph_handler(
            {"arxiv_id": "2305.18290"},
            _settings(tmp_path),
        )

    assert "Error" in result
    assert "Semantic Scholar" in result


@pytest.mark.asyncio
async def test_citation_graph_respects_limit(tmp_path: Path) -> None:
    captured: dict[str, int] = {}

    async def fake_fetch(client, s2_id, side, limit):
        captured[side] = limit
        return []

    with patch("app.tools.papers._fetch_citation_side", new=fake_fetch):
        await paper_citation_graph_handler(
            {"arxiv_id": "2305.18290", "limit": 3},
            _settings(tmp_path),
        )

    assert captured["references"] == 3
    assert captured["citations"] == 3


# ---------------------------------------------------------------------------
# Paper section reading
# ---------------------------------------------------------------------------


SAMPLE_ARXIV_HTML = """
<html><body>
<h1 class="ltx_title">Title: Attention Is All You Need</h1>
<div class="ltx_abstract"><h6>Abstract</h6><p>The dominant sequence transduction models are based on
complex recurrent or convolutional neural networks.</p></div>
<h2 class="ltx_title">1 Introduction</h2>
<p>We propose a new simple network architecture.</p>
<h2 class="ltx_title">3 Model Architecture</h2>
<p>The encoder maps an input sequence to a representation. Most competitive
neural sequence transduction models have an encoder and a decoder.</p>
<h3 class="ltx_title">3.1 Scaled Dot-Product Attention</h3>
<p>We compute the dot products of the query with all keys.</p>
<h2 class="ltx_title">5 Results</h2>
<p>On the WMT 2014 English-to-German task we trained for 100000 steps with
batch size 2048 using Adam with learning rate 0.5 on 8 GPUs.</p>
</body></html>
"""


def test_parse_paper_html_extracts_sections() -> None:
    parsed = _parse_paper_html(SAMPLE_ARXIV_HTML)

    assert parsed["title"] == "Attention Is All You Need"
    assert "dominant sequence transduction" in parsed["abstract"]
    titles = [section["title"] for section in parsed["sections"]]
    assert "1 Introduction" in titles
    assert "3 Model Architecture" in titles
    assert "3.1 Scaled Dot-Product Attention" in titles


def test_find_section_by_number_and_name() -> None:
    sections = _parse_paper_html(SAMPLE_ARXIV_HTML)["sections"]

    assert _find_section(sections, "3")["title"] == "3 Model Architecture"
    assert _find_section(sections, "Model Architecture") is not None
    assert _find_section(sections, "nonexistent") is None


@pytest.mark.asyncio
async def test_read_paper_toc(tmp_path: Path) -> None:
    async def fake_fetch(arxiv_id):
        return _parse_paper_html(SAMPLE_ARXIV_HTML)

    with patch("app.tools.papers._fetch_paper_html", new=fake_fetch):
        result = await read_paper_handler({"arxiv_id": "1706.03762"}, _settings(tmp_path))

    assert "Attention Is All You Need" in result
    assert "## Sections" in result
    assert "1 Introduction" in result
    assert "table of contents" in result.lower() or "section" in result.lower()


@pytest.mark.asyncio
async def test_read_paper_specific_section(tmp_path: Path) -> None:
    async def fake_fetch(arxiv_id):
        return _parse_paper_html(SAMPLE_ARXIV_HTML)

    with patch("app.tools.papers._fetch_paper_html", new=fake_fetch):
        result = await read_paper_handler(
            {"arxiv_id": "1706.03762", "section": "3"},
            _settings(tmp_path),
        )

    assert "3 Model Architecture" in result
    assert "encoder" in result.lower()


@pytest.mark.asyncio
async def test_read_paper_missing_section_falls_back_to_abstract(tmp_path: Path) -> None:
    async def fake_fetch_paper_html(arxiv_id):
        return None

    async def fake_fetch_paper(arxiv_id):
        return {"title": "Fallback Title", "summary": "Fallback abstract text."}

    with (
        patch("app.tools.papers._fetch_paper_html", new=fake_fetch_paper_html),
        patch("app.tools.papers._fetch_paper", new=fake_fetch_paper),
    ):
        result = await read_paper_handler({"arxiv_id": "1706.03762"}, _settings(tmp_path))

    assert "Fallback Title" in result
    assert "Fallback abstract text." in result
    assert "HTML version not available" in result


@pytest.mark.asyncio
async def test_read_paper_missing_id(tmp_path: Path) -> None:
    result = await read_paper_handler({}, _settings(tmp_path))
    assert "Error" in result


# ---------------------------------------------------------------------------
# Training recipe extraction
# ---------------------------------------------------------------------------


def test_extract_recipe_values_finds_fields_with_evidence() -> None:
    text = (
        "We train on the WMT 2014 English-to-German dataset. "
        "Our architecture is a transformer encoder-decoder. "
        "We use the Adam optimizer with a learning rate of 0.5. "
        "Training used a batch size of 2048 for 100000 steps on 8 GPUs."
    )

    findings = _extract_recipe_values([text])

    assert findings["dataset"]
    assert findings["architecture"]
    assert findings["optimizer"]
    assert findings["learning_rate"]
    assert findings["batch_size"]
    assert findings["epochs"]
    assert findings["hardware"]
    for field in ("dataset", "optimizer", "hardware"):
        entry = findings[field][0]
        assert entry["value"]
        assert entry["evidence"]


def test_extract_recipe_values_handles_empty_text() -> None:
    findings = _extract_recipe_values([""])
    for field in findings:
        assert findings[field] == []


def test_select_recipe_sections_prefers_method_sections() -> None:
    sections = [
        {"id": "1", "title": "1 Introduction", "level": 2, "text": "short"},
        {"id": "4", "title": "4 Experiments", "level": 2, "text": "long experiment text"},
        {"id": "3", "title": "3 Method", "level": 2, "text": "method details"},
    ]

    selected = _select_recipe_sections(sections)
    selected_titles = [section["title"] for section in selected]

    assert "4 Experiments" in selected_titles
    assert "3 Method" in selected_titles
    assert "1 Introduction" not in selected_titles


def test_format_training_recipe_lists_findings_with_evidence() -> None:
    findings = {
        "dataset": [{"value": "WMT 2014 dataset.", "evidence": "WMT 2014 dataset."}],
        "architecture": [{"value": "Transformer encoder-decoder.", "evidence": "Transformer encoder-decoder."}],
        "optimizer": [],
        "learning_rate": [],
        "batch_size": [],
        "epochs": [],
        "hardware": [],
    }
    sections = [{"id": "4", "title": "4 Experiments", "level": 2, "text": "..."}]

    result = _format_training_recipe("1706.03762", "Attention Is All You Need", sections, findings)

    assert "Training recipe for Attention Is All You Need" in result
    assert "## Dataset" in result
    assert "## Architecture" in result
    assert "evidence:" in result
    assert "Optimizer" not in result  # empty fields are omitted


def test_format_training_recipe_handles_no_findings() -> None:
    findings = {
        field: []
        for field in ("dataset", "architecture", "optimizer", "learning_rate", "batch_size", "epochs", "hardware")
    }

    result = _format_training_recipe("1706.03762", "Title", [], findings)

    assert "No method or experiment details" in result


@pytest.mark.asyncio
async def test_extract_training_recipe_handler_success(tmp_path: Path) -> None:
    async def fake_fetch(arxiv_id):
        return _parse_paper_html(SAMPLE_ARXIV_HTML)

    with patch("app.tools.papers._fetch_paper_html", new=fake_fetch):
        result = await extract_training_recipe_handler(
            {"arxiv_id": "1706.03762"},
            _settings(tmp_path),
        )

    assert "Training recipe" in result
    assert "batch size" in result.lower() or "Batch Size" in result
    assert "evidence:" in result


@pytest.mark.asyncio
async def test_extract_training_recipe_handler_no_html(tmp_path: Path) -> None:
    async def fake_fetch(arxiv_id):
        return None

    with patch("app.tools.papers._fetch_paper_html", new=fake_fetch):
        result = await extract_training_recipe_handler(
            {"arxiv_id": "1706.03762"},
            _settings(tmp_path),
        )

    assert "Error" in result
    assert "HTML" in result


@pytest.mark.asyncio
async def test_extract_training_recipe_handler_missing_id(tmp_path: Path) -> None:
    result = await extract_training_recipe_handler({}, _settings(tmp_path))
    assert "Error" in result
