"""Documentation search and fetch tools for HuggingFace and ML libraries."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from whoosh.analysis import StemmingAnalyzer
from whoosh.fields import ID, TEXT, Schema
from whoosh.filedb.filestore import RamStorage
from whoosh.qparser import MultifieldParser, OrGroup

from app.config import AppSettings

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_RESULTS = 20
MAX_RESULTS_CAP = 50

DOC_ENDPOINTS = [
    "hub",
    "transformers",
    "diffusers",
    "datasets",
    "smolagents",
    "huggingface_hub",
    "peft",
    "accelerate",
    "trl",
    "tokenizers",
    "evaluate",
    "sentence_transformers",
    "bitsandbytes",
    "tgi",
    "safetensors",
    "optimum",
    "autotrain",
    "timm",
]

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_docs_cache: dict[str, list[dict[str, str]]] = {}
_index_cache: dict[str, tuple[Any, MultifieldParser]] = {}
_cache_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# HF Documentation — Fetching
# ---------------------------------------------------------------------------


async def _fetch_endpoint_docs(endpoint: str) -> list[dict[str, str]]:
    """Fetch all doc pages for an endpoint by parsing sidebar and fetching each page."""
    url = f"https://huggingface.co/docs/{endpoint}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        sidebar = soup.find("nav", class_=lambda x: x and "flex-auto" in x)
        if not sidebar:
            raise ValueError(f"Could not find navigation sidebar for '{endpoint}'")

        nav_items = []
        for link in sidebar.find_all("a", href=True):
            href = link["href"]
            page_url = f"https://huggingface.co{href}" if href.startswith("/") else href
            nav_items.append({"title": link.get_text(strip=True), "url": page_url})

        if not nav_items:
            raise ValueError(f"No navigation links found for '{endpoint}'")

        async def fetch_page(item: dict[str, str]) -> dict[str, str]:
            md_url = f"{item['url']}.md"
            try:
                r = await client.get(md_url)
                r.raise_for_status()
                content = r.text.strip()
                glimpse = content[:200] + "..." if len(content) > 200 else content
            except Exception as e:
                content, glimpse = "", f"[Could not fetch: {str(e)[:50]}]"
            return {
                "title": item["title"],
                "url": item["url"],
                "md_url": md_url,
                "glimpse": glimpse,
                "content": content,
                "section": endpoint,
            }

        return list(await asyncio.gather(*[fetch_page(item) for item in nav_items]))


async def _get_docs(endpoint: str) -> list[dict[str, str]]:
    """Get docs for endpoint with caching."""
    async with _cache_lock:
        if endpoint in _docs_cache:
            return _docs_cache[endpoint]

    docs = await _fetch_endpoint_docs(endpoint)
    async with _cache_lock:
        _docs_cache[endpoint] = docs
    return docs


# ---------------------------------------------------------------------------
# HF Documentation — Search
# ---------------------------------------------------------------------------


async def _build_search_index(endpoint: str, docs: list[dict[str, str]]) -> tuple[Any, MultifieldParser]:
    """Build or retrieve cached Whoosh search index."""
    async with _cache_lock:
        if endpoint in _index_cache:
            return _index_cache[endpoint]

    analyzer = StemmingAnalyzer()
    schema = Schema(
        title=TEXT(stored=True, analyzer=analyzer),
        url=ID(stored=True, unique=True),
        md_url=ID(stored=True),
        section=ID(stored=True),
        glimpse=TEXT(stored=True, analyzer=analyzer),
        content=TEXT(stored=False, analyzer=analyzer),
    )
    storage = RamStorage()
    index = storage.create_index(schema)
    writer = index.writer()
    for doc in docs:
        writer.add_document(
            title=doc.get("title", ""),
            url=doc.get("url", ""),
            md_url=doc.get("md_url", ""),
            section=doc.get("section", endpoint),
            glimpse=doc.get("glimpse", ""),
            content=doc.get("content", ""),
        )
    writer.commit()

    parser = MultifieldParser(
        ["title", "content"],
        schema=schema,
        fieldboosts={"title": 2.0, "content": 1.0},
        group=OrGroup,
    )

    async with _cache_lock:
        _index_cache[endpoint] = (index, parser)
    return index, parser


async def _search_docs(
    endpoint: str, docs: list[dict[str, str]], query: str, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """Search docs using Whoosh full-text search."""
    index, parser = await _build_search_index(endpoint, docs)

    try:
        query_obj = parser.parse(query)
    except Exception:
        return [], "Query contained unsupported syntax; showing default ordering."

    with index.searcher() as searcher:
        results = searcher.search(query_obj, limit=limit)
        matches = [
            {
                "title": hit["title"],
                "url": hit["url"],
                "md_url": hit.get("md_url", ""),
                "section": hit.get("section", endpoint),
                "glimpse": hit["glimpse"],
                "score": round(hit.score, 2),
            }
            for hit in results
        ]

    if not matches:
        return [], "No matches found; showing default ordering."
    return matches, None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_results(
    endpoint: str,
    items: list[dict[str, Any]],
    total: int,
    query: str | None = None,
    note: str | None = None,
) -> str:
    """Format search results as readable Markdown."""
    base_url = f"https://huggingface.co/docs/{endpoint}"
    out = f"## Documentation: {base_url}\n\n"

    if query:
        out += f"**Query:** '{query}' → {len(items)} result(s) out of {total} pages"
        if note:
            out += f" ({note})"
        out += "\n\n"
    else:
        out += f"**Pages:** {len(items)} shown (total: {total})"
        if note:
            out += f" ({note})"
        out += "\n\n"

    for i, item in enumerate(items, 1):
        out += f"### {i}. {item['title']}\n"
        out += f"- **URL:** {item['url']}\n"
        if query and "score" in item:
            out += f"- **Relevance:** {item['score']:.2f}\n"
        out += f"- **Preview:** {item['glimpse']}\n\n"

    return out


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------


async def search_docs_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Explore HF documentation structure with optional search query."""
    endpoint = args.get("endpoint", "").strip().lstrip("/")
    query = args.get("query", "").strip() or None
    max_results = args.get("max_results")

    if not endpoint:
        return "Error: No endpoint provided. Use one of: " + ", ".join(DOC_ENDPOINTS)

    if endpoint not in DOC_ENDPOINTS:
        return f"Error: Unknown endpoint '{endpoint}'. Available: {', '.join(DOC_ENDPOINTS)}"

    try:
        if max_results is not None:
            max_results = int(max_results)
            if max_results <= 0:
                return "Error: max_results must be greater than zero."
    except (TypeError, ValueError):
        return "Error: max_results must be an integer."

    try:
        docs = await _get_docs(endpoint)
        total = len(docs)

        limit = min(max_results or DEFAULT_MAX_RESULTS, MAX_RESULTS_CAP)
        limit_note = None
        if max_results and max_results > MAX_RESULTS_CAP:
            limit_note = f"Capped at {MAX_RESULTS_CAP}."

        if query:
            results, fallback_msg = await _search_docs(endpoint, docs, query, limit)
            if not results:
                results = [
                    {
                        "title": d["title"],
                        "url": d["url"],
                        "glimpse": d["glimpse"],
                        "section": d.get("section", endpoint),
                    }
                    for d in docs[:limit]
                ]
        else:
            results = [
                {
                    "title": d["title"],
                    "url": d["url"],
                    "glimpse": d["glimpse"],
                    "section": d.get("section", endpoint),
                }
                for d in docs[:limit]
            ]
            fallback_msg = None

        notes = []
        if query and fallback_msg:
            notes.append(fallback_msg)
        if limit_note:
            notes.append(limit_note)
        note = "; ".join(notes) if notes else None

        return _format_results(endpoint, results, total, query, note)

    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} fetching docs for '{endpoint}'."
    except httpx.RequestError as e:
        return f"Error: Network request failed — {e}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching docs: {e}"


async def fetch_doc_page_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Fetch full Markdown content of a documentation page."""
    url = args.get("url", "").strip()
    if not url:
        return "Error: No URL provided."

    normalized_url = _normalize_hf_docs_url(url)
    if normalized_url is None:
        return "Error: fetch_doc_page only accepts HuggingFace docs URLs under https://huggingface.co/docs/."

    url = normalized_url

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return f"## Documentation: {url}\n\n{resp.text}"
    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} fetching {url}"
    except httpx.RequestError as e:
        return f"Error: Network request failed — {e}"
    except Exception as e:
        return f"Error fetching page: {e}"


def _normalize_hf_docs_url(url: str) -> str | None:
    """Return a normalized HuggingFace docs .md URL, or None if the URL is not allowed."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "huggingface.co":
        return None
    if not parsed.path.startswith("/docs/"):
        return None

    normalized = parsed._replace(query="", fragment="").geturl()
    if not normalized.endswith(".md"):
        normalized = f"{normalized}.md"
    return normalized


# ---------------------------------------------------------------------------
# Tool Specifications
# ---------------------------------------------------------------------------


def get_tool_specs() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool specifications for docs tools."""
    return [
        {
            "name": "search_docs",
            "description": (
                "Browse and search HuggingFace documentation. Discovers available pages "
                "with 200-char previews. Use with a query to find relevant docs, "
                "or without to browse the full structure. "
                "Pattern: search_docs (find pages) → fetch_doc_page (get full content)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "enum": DOC_ENDPOINTS,
                        "description": (
                            "Documentation section to search. Key endpoints: "
                            "transformers, diffusers, datasets, peft, trl, accelerate, "
                            "huggingface_hub, smolagents, tokenizers, evaluate, optimum."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Keyword search to rank and filter pages. "
                            "Supports stemming (e.g. 'training' matches 'train')."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (default: 20, max: 50).",
                    },
                },
                "required": ["endpoint"],
            },
        },
        {
            "name": "fetch_doc_page",
            "description": (
                "Fetch full Markdown content of an HF documentation page. "
                "Use after search_docs to get complete content of a relevant page. "
                "The .md extension is added automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Full URL to the documentation page from search_docs results. "
                            "Example: 'https://huggingface.co/docs/trl/dpo_trainer'"
                        ),
                    },
                },
                "required": ["url"],
            },
        },
    ]
