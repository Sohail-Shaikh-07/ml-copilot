"""Tests for app.tools.papers module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import AppPaths, AppSettings
from app.tools.papers import (
    _format_paper_details,
    _normalize_arxiv_id,
    get_tool_specs,
    paper_details_handler,
)


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


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


def test_get_tool_specs() -> None:
    specs = get_tool_specs()

    assert len(specs) == 1
    assert specs[0]["name"] == "paper_details"
    assert "arxiv_id" in specs[0]["parameters"]["properties"]
