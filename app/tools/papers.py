"""Paper metadata reader for Hugging Face papers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import AppSettings
from app.tools.context import current_hf_token

HF_API = "https://huggingface.co/api"

MAX_AUTHOR_COUNT = 10
MAX_SUMMARY_LEN = 500


def _normalize_arxiv_id(value: Any) -> str:
    """Normalize raw IDs and paper URLs to an arXiv identifier."""
    if value is None:
        return ""

    candidate = str(value).strip()
    if not candidate:
        return ""

    if "://" in candidate:
        parsed = urlparse(candidate)
        candidate = parsed.path.rstrip("/").split("/")[-1]

    for prefix in ("arxiv:", "ArXiv:"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]

    return candidate.strip().rstrip("/")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _format_paper_details(paper: dict[str, Any]) -> str:
    """Format Hugging Face paper metadata as readable Markdown."""
    arxiv_id = paper.get("id", "")
    title = paper.get("title", "Unknown")
    upvotes = paper.get("upvotes", 0)
    summary = paper.get("summary") or ""
    ai_summary = paper.get("ai_summary") or ""
    keywords = paper.get("ai_keywords") or []
    github = paper.get("githubRepo") or ""
    stars = paper.get("githubStars") or 0
    authors = paper.get("authors") or []

    lines = [f"# {title}"]
    lines.append(f"**arxiv_id:** {arxiv_id} | **upvotes:** {upvotes}")
    lines.append(f"https://huggingface.co/papers/{arxiv_id}")
    lines.append(f"https://arxiv.org/abs/{arxiv_id}")

    if authors:
        names = [author.get("name", "") for author in authors[:MAX_AUTHOR_COUNT]]
        author_str = ", ".join(name for name in names if name)
        if len(authors) > MAX_AUTHOR_COUNT:
            author_str += f" (+{len(authors) - MAX_AUTHOR_COUNT} more)"
        if author_str:
            lines.append(f"**Authors:** {author_str}")

    if keywords:
        lines.append(f"**Keywords:** {', '.join(keywords)}")
    if github:
        lines.append(f"**GitHub:** {github} ({stars} stars)")
    if ai_summary:
        lines.append(f"\n## AI Summary\n{ai_summary}")
    if summary:
        lines.append(f"\n## Abstract\n{_truncate(summary, MAX_SUMMARY_LEN)}")

    lines.append("\n**Next:** Use this metadata before citation graph or paper reading tasks.")
    return "\n".join(lines)


async def _fetch_paper(arxiv_id: str) -> dict[str, Any]:
    headers: dict[str, str] = {}
    token = current_hf_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        resp = await client.get(f"{HF_API}/papers/{arxiv_id}")
        resp.raise_for_status()
        return resp.json()


async def paper_details_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Fetch and format Hugging Face paper metadata."""
    raw_arxiv_id = args.get("arxiv_id", "")
    arxiv_id = _normalize_arxiv_id(raw_arxiv_id)
    if not arxiv_id:
        return "Error: No arxiv_id provided. Pass an arXiv ID or paper URL."

    try:
        paper = await _fetch_paper(arxiv_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return f"Error: Paper {arxiv_id} was not found on Hugging Face."
        return f"Error fetching paper {arxiv_id}: HTTP {exc.response.status_code}"
    except httpx.RequestError as exc:
        return f"Error fetching paper {arxiv_id}: {exc}"
    except Exception as exc:
        return f"Error fetching paper {arxiv_id}: {exc}"

    return _format_paper_details(paper)


def get_tool_specs() -> list[dict[str, Any]]:
    """Return the paper metadata tool specification."""
    return [
        {
            "name": "paper_details",
            "description": (
                "Fetch Hugging Face paper metadata for an arXiv ID. "
                "Returns title, authors, keywords, abstract or summary, and useful links."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": (
                            "ArXiv paper ID or paper URL, for example '2305.18290' or "
                            "'https://huggingface.co/papers/2305.18290'."
                        ),
                    },
                },
                "required": ["arxiv_id"],
            },
        }
    ]
