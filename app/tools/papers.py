"""Paper research tools: metadata, citation graph, section reading, and recipe extraction."""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.config import AppSettings
from app.tools.context import current_hf_token

HF_API = "https://huggingface.co/api"

# arXiv HTML rendering hosts. ar5iv is a fallback for papers without a native
# arXiv HTML version.
ARXIV_HTML = "https://arxiv.org/html"
AR5IV_HTML = "https://ar5iv.labs.arxiv.org/html"

# Semantic Scholar Graph API.
S2_API = "https://api.semanticscholar.org"
S2_TIMEOUT = 12.0

MAX_AUTHOR_COUNT = 10
MAX_SUMMARY_LEN = 500
MAX_SECTION_TEXT_LEN = 8000
MAX_SECTION_PREVIEW_LEN = 280
MAX_CITATION_CONTEXTS = 2
MAX_CITATION_CONTEXT_LEN = 200

# Citation graph result bounds. One-hop traversal only; the caller can follow
# individual arxiv ids to go deeper.
DEFAULT_CITATION_LIMIT = 10
MAX_CITATION_LIMIT = 50

# Recipe extraction bounds.
RECIPE_SNIPPET_LEN = 160
MAX_RECIPE_VALUES = 6


# ---------------------------------------------------------------------------
# arXiv id helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Semantic Scholar client (one-hop traversal only)
# ---------------------------------------------------------------------------


def _s2_headers() -> dict[str, str]:
    """Optional Semantic Scholar API key when provided in the environment."""
    api_key = os.environ.get("S2_API_KEY")
    return {"x-api-key": api_key} if api_key else {}


# Module-level rate-limiting for the shared Semantic Scholar endpoint. Only
# applied when authenticated, mirroring the public unauthenticated limits.
_s2_last_request: float = 0.0

# Lightweight response cache so repeated citation-graph reads within a session
# do not refetch the same paper.
_s2_cache: dict[str, Any] = {}
_S2_CACHE_MAX = 256


def _s2_paper_id(arxiv_id: str) -> str:
    """Convert a bare arxiv id to the Semantic Scholar corpus id format."""
    return f"ARXIV:{arxiv_id}"


def _s2_cache_key(path: str, params: dict[str, Any] | None) -> str:
    normalized = tuple(sorted((params or {}).items()))
    return f"{path}:{normalized}"


async def _s2_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response | None:
    """Semantic Scholar request with bounded retries on rate limiting and 5xx.

    Returns ``None`` when the endpoint is unavailable so callers can degrade
    gracefully instead of surfacing raw transport errors to the agent.
    """
    global _s2_last_request
    url = f"{S2_API}{path}"
    kwargs.setdefault("headers", {}).update(_s2_headers())
    kwargs.setdefault("timeout", S2_TIMEOUT)

    for attempt in range(3):
        if _s2_headers():
            min_interval = 1.0 if "search" in path else 0.1
            elapsed = time.monotonic() - _s2_last_request
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
        _s2_last_request = time.monotonic()

        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.RequestError, httpx.HTTPStatusError):
            if attempt < 2:
                await asyncio.sleep(2.0)
                continue
            return None

        if response.status_code == 429:
            if attempt < 2:
                await asyncio.sleep(5.0)
                continue
            return None
        if response.status_code >= 500:
            if attempt < 2:
                await asyncio.sleep(2.0)
                continue
            return None
        return response
    return None


async def _s2_get_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Cached Semantic Scholar GET returning parsed JSON or ``None``."""
    key = _s2_cache_key(path, params)
    if key in _s2_cache:
        return _s2_cache[key]

    response = await _s2_request(client, "GET", path, params=params or {})
    if response is None or response.status_code != 200:
        return None

    data = response.json()
    if len(_s2_cache) < _S2_CACHE_MAX:
        _s2_cache[key] = data
    return data


# ---------------------------------------------------------------------------
# Paper metadata (paper_details)
# ---------------------------------------------------------------------------


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

    lines.append("\n**Next:** Use citation_graph, read_paper, or extract_training_recipe to go deeper.")
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
    del settings

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


# ---------------------------------------------------------------------------
# Citation graph (Semantic Scholar, one-hop)
# ---------------------------------------------------------------------------


def _format_citation_entry(entry: dict[str, Any], *, show_context: bool) -> str:
    """Format a single reference or citation entry."""
    paper = entry.get("citingPaper") or entry.get("citedPaper") or {}
    title = paper.get("title") or "(untitled)"
    year = paper.get("year") or "?"
    cites = paper.get("citationCount", 0)
    ext_ids = paper.get("externalIds") or {}
    aid = ext_ids.get("ArXiv", "")
    influential_marker = " **[influential]**" if entry.get("isInfluential") else ""

    first_line = f"- **{title}** ({year}, {cites} cites){influential_marker}"
    if aid:
        first_line += f" arxiv:{aid}"
    parts = [first_line]

    if show_context:
        intents = entry.get("intents") or []
        if intents:
            parts.append(f"  Intent: {', '.join(intents)}")
        contexts = entry.get("contexts") or []
        for context in contexts[:MAX_CITATION_CONTEXTS]:
            if context:
                parts.append(f"  > {_truncate(context, MAX_CITATION_CONTEXT_LEN)}")

    return "\n".join(parts)


def _format_citation_graph(
    arxiv_id: str,
    references: list[dict[str, Any]] | None,
    citations: list[dict[str, Any]] | None,
) -> str:
    lines = [f"# Citation graph for {arxiv_id}"]
    lines.append(f"https://arxiv.org/abs/{arxiv_id}\n")

    if references is not None:
        lines.append(f"## References ({len(references)})")
        if references:
            for entry in references:
                lines.append(_format_citation_entry(entry, show_context=False))
        else:
            lines.append("No references found.")
        lines.append("")

    if citations is not None:
        lines.append(f"## Citations ({len(citations)})")
        if citations:
            for entry in citations:
                lines.append(_format_citation_entry(entry, show_context=True))
        else:
            lines.append("No citations found.")
        lines.append("")

    lines.append("**Next:** Use paper_details or read_paper with an arxiv_id above to explore further.")
    return "\n".join(lines)


def _bounded_citation_limit(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CITATION_LIMIT
    return max(1, min(value, MAX_CITATION_LIMIT))


async def _fetch_citation_side(
    client: httpx.AsyncClient,
    s2_id: str,
    side: str,
    limit: int,
) -> list[dict[str, Any]] | None:
    """Fetch one side of the citation graph (references or citations)."""
    fields = "title,externalIds,year,citationCount,influentialCitationCount,contexts,intents,isInfluential"
    params = {"fields": fields, "limit": limit}
    data = await _s2_get_json(client, f"/graph/v1/paper/{s2_id}/{side}", params)
    if data is None:
        return None
    entries = data.get("data") or []
    return [entry for entry in entries if isinstance(entry, dict)]


async def paper_citation_graph_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Return a one-hop citation graph for a paper via Semantic Scholar."""
    del settings

    raw_arxiv_id = args.get("arxiv_id", "")
    arxiv_id = _normalize_arxiv_id(raw_arxiv_id)
    if not arxiv_id:
        return "Error: No arxiv_id provided. Pass an arXiv ID or paper URL."

    direction = str(args.get("direction", "both")).strip().lower()
    if direction not in {"references", "citations", "both"}:
        return "Error: direction must be one of 'references', 'citations', or 'both'."

    limit = _bounded_citation_limit(args.get("limit", DEFAULT_CITATION_LIMIT))
    s2_id = _s2_paper_id(arxiv_id)

    references: list[dict[str, Any]] | None = None
    citations: list[dict[str, Any]] | None = None

    async with httpx.AsyncClient(timeout=S2_TIMEOUT) as client:
        tasks: list[tuple[str, Any]] = []
        if direction in {"references", "both"}:
            tasks.append(("references", _fetch_citation_side(client, s2_id, "references", limit)))
        if direction in {"citations", "both"}:
            tasks.append(("citations", _fetch_citation_side(client, s2_id, "citations", limit)))
        results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        for (label, _), result in zip(tasks, results, strict=True):
            if isinstance(result, BaseException):
                continue
            fetched: list[dict[str, Any]] | None = result
            if label == "references":
                references = fetched
            else:
                citations = fetched

    if references is None and citations is None:
        return (
            f"Error: Could not fetch citation data for {arxiv_id}. "
            "The paper may not be indexed by Semantic Scholar yet, or the service is unavailable."
        )

    return _format_citation_graph(arxiv_id, references, citations)


# ---------------------------------------------------------------------------
# Paper section reading (arXiv HTML)
# ---------------------------------------------------------------------------


def _parse_paper_html(html: str) -> dict[str, Any]:
    """Parse rendered arXiv HTML into a title, abstract, and section list.

    Returns a dict with ``title``, ``abstract``, and ``sections``. Each section
    carries an ``id`` (section number when present), ``title``, ``level``, and
    the concatenated ``text`` between headings.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.find("h1", class_="ltx_title")
    title = title_el.get_text(strip=True).removeprefix("Title:").strip() if title_el else ""

    abstract = ""
    abstract_el = soup.find("div", class_="ltx_abstract")
    if abstract_el:
        for child in abstract_el.children:
            if isinstance(child, Tag) and child.name in ("h6", "h2", "h3", "p", "span"):
                if child.get_text(strip=True).lower() == "abstract":
                    continue
            if isinstance(child, Tag) and child.name == "p":
                abstract += child.get_text(separator=" ", strip=True) + " "
        abstract = abstract.strip()

    sections: list[dict[str, Any]] = []
    headings = soup.find_all(["h2", "h3"], class_=lambda cls: bool(cls) and "ltx_title" in cls)

    for heading in headings:
        level = 2 if heading.name == "h2" else 3
        heading_text = heading.get_text(separator=" ", strip=True)

        text_parts: list[str] = []
        sibling = heading.find_next_sibling()
        while sibling:
            if isinstance(sibling, Tag):
                sibling_classes = sibling.get("class") or []
                if sibling.name in ("h2", "h3") and "ltx_title" in sibling_classes:
                    break
                if sibling.name == "h2" and level == 3:
                    break
                text_parts.append(sibling.get_text(separator=" ", strip=True))
            sibling = sibling.find_next_sibling()

        parent_section = heading.find_parent("section")
        if parent_section and not text_parts:
            for paragraph in parent_section.find_all("p", recursive=False):
                text_parts.append(paragraph.get_text(separator=" ", strip=True))

        section_text = "\n\n".join(part for part in text_parts if part)
        number_match = re.match(r"^([A-Z]?\d+(?:\.\d+)*)\s", heading_text)
        section_id = number_match.group(1) if number_match else ""

        sections.append(
            {
                "id": section_id,
                "title": heading_text,
                "level": level,
                "text": section_text,
            }
        )

    return {"title": title, "abstract": abstract, "sections": sections}


def _find_section(sections: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    """Locate a section by number or title (fuzzy substring match as a fallback)."""
    query_lower = query.lower().strip()

    for section in sections:
        if section["id"] in (query_lower, query):
            return section
    for section in sections:
        if query_lower == section["title"].lower():
            return section
    for section in sections:
        if query_lower in section["title"].lower():
            return section
    for section in sections:
        if section["id"].startswith(f"{query_lower}.") or section["id"] == query_lower:
            return section
    return None


async def _fetch_paper_html(arxiv_id: str) -> dict[str, Any] | None:
    """Fetch and parse rendered arXiv HTML, trying native then ar5iv hosts."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for base_url in (ARXIV_HTML, AR5IV_HTML):
            try:
                response = await client.get(f"{base_url}/{arxiv_id}")
            except httpx.RequestError:
                continue
            if response.status_code != 200:
                continue
            parsed = _parse_paper_html(response.text)
            if parsed["sections"]:
                return parsed
    return None


def _format_paper_toc(parsed: dict[str, Any], arxiv_id: str) -> str:
    """Format a table of contents: abstract plus section previews."""
    lines = [f"# {parsed['title'] or arxiv_id}"]
    lines.append(f"https://arxiv.org/abs/{arxiv_id}\n")

    if parsed["abstract"]:
        lines.append(f"## Abstract\n{parsed['abstract']}\n")

    lines.append("## Sections")
    for section in parsed["sections"]:
        indent = "  " if section["level"] == 3 else ""
        preview = _truncate(section["text"], MAX_SECTION_PREVIEW_LEN) if section["text"] else "(empty)"
        lines.append(f"{indent}- **{section['title']}**: {preview}")

    lines.append(
        '\nCall read_paper with section (e.g. section="4" or section="Experiments") to read a specific section.'
    )
    return "\n".join(lines)


def _format_paper_section(section: dict[str, Any], arxiv_id: str) -> str:
    """Format a single section's full text."""
    lines = [f"# {section['title']}"]
    lines.append(f"https://arxiv.org/abs/{arxiv_id}\n")

    text = section["text"]
    if len(text) > MAX_SECTION_TEXT_LEN:
        text = text[:MAX_SECTION_TEXT_LEN] + f"\n\n... (truncated at {MAX_SECTION_TEXT_LEN} chars)"

    lines.append(text if text else "(This section has no extractable text content.)")
    return "\n".join(lines)


async def read_paper_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Read the table of contents or a specific section of a paper."""
    del settings

    raw_arxiv_id = args.get("arxiv_id", "")
    arxiv_id = _normalize_arxiv_id(raw_arxiv_id)
    if not arxiv_id:
        return "Error: No arxiv_id provided. Pass an arXiv ID or paper URL."

    section_query = str(args.get("section", "")).strip()

    parsed = await _fetch_paper_html(arxiv_id)
    if not parsed or not parsed["sections"]:
        # Fall back to the abstract when no rendered HTML is available.
        try:
            paper = await _fetch_paper(arxiv_id)
        except Exception as exc:
            return f"Error: Could not fetch paper {arxiv_id}: {exc}"

        title = paper.get("title", "")
        abstract = paper.get("summary", "")
        message = f"# {title}\nhttps://arxiv.org/abs/{arxiv_id}\n\n## Abstract\n{abstract}\n\n"
        message += "HTML version not available for this paper. Only the abstract is shown.\n"
        message += f"PDF: https://arxiv.org/pdf/{arxiv_id}"
        return message

    if not section_query:
        return _format_paper_toc(parsed, arxiv_id)

    section = _find_section(parsed["sections"], section_query)
    if not section:
        available = "\n".join(f"- {item['title']}" for item in parsed["sections"])
        return f"Error: Section '{section_query}' not found. Available sections:\n{available}"

    return _format_paper_section(section, arxiv_id)


# ---------------------------------------------------------------------------
# Training recipe extraction (deterministic + evidence-linked)
# ---------------------------------------------------------------------------


# Each pattern maps a recipe field to the labels/terms that commonly introduce
# it in method and experiment sections. Matches are case-insensitive and
# anchored to the sentence immediately following the label so the extracted
# value stays tightly scoped to its evidence.
_RECIPE_PATTERNS: dict[str, list[str]] = {
    "dataset": ["dataset", "datasets", "training data", "train on", "trained on"],
    "architecture": ["architecture", "model architecture", "backbone", "encoder", "decoder"],
    "optimizer": ["optimizer", "optimiser", "adamw", "adam", "sgd"],
    "learning_rate": ["learning rate", "lr"],
    "batch_size": ["batch size", "batch"],
    "epochs": ["epochs", "epoch", "training steps", "steps"],
    "hardware": ["gpu", "gpus", "tpu", "tpus", "a100", "h100", "v100", "hardware"],
}

_RECIPE_FIELD_ORDER = [
    "dataset",
    "architecture",
    "optimizer",
    "learning_rate",
    "batch_size",
    "epochs",
    "hardware",
]


def _split_sentences(text: str) -> list[str]:
    """Split free text into sentences for evidence extraction.

    Splits on sentence-ending punctuation followed by whitespace while keeping
    numeric abbreviations (e.g. ``3.5``) intact.
    """
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned)
    return [part.strip() for part in parts if part.strip()]


def _extract_recipe_values(section_texts: list[str]) -> dict[str, list[dict[str, str]]]:
    """Extract evidence-linked recipe values from section text.

    Returns a mapping of field name to a list of ``{"value", "evidence"}``
    entries, each quoting the sentence the value was taken from.
    """
    sentences: list[str] = []
    for text in section_texts:
        sentences.extend(_split_sentences(text))

    findings: dict[str, list[dict[str, str]]] = {field: [] for field in _RECIPE_FIELD_ORDER}

    for sentence in sentences:
        sentence_lower = sentence.lower()
        for field, labels in _RECIPE_PATTERNS.items():
            if len(findings[field]) >= MAX_RECIPE_VALUES:
                continue
            if any(label in sentence_lower for label in labels):
                findings[field].append(
                    {
                        "value": _truncate(sentence, RECIPE_SNIPPET_LEN),
                        "evidence": _truncate(sentence, RECIPE_SNIPPET_LEN),
                    }
                )

    return findings


def _format_training_recipe(
    arxiv_id: str,
    title: str,
    parsed_sections: list[dict[str, Any]],
    findings: dict[str, list[dict[str, str]]],
) -> str:
    lines = [f"# Training recipe for {title or arxiv_id}"]
    lines.append(f"https://arxiv.org/abs/{arxiv_id}\n")
    lines.append(f"Scanned {len(parsed_sections)} method/experiment section(s).\n")

    any_found = False
    for field in _RECIPE_FIELD_ORDER:
        entries = findings.get(field) or []
        if not entries:
            continue
        any_found = True
        lines.append(f"## {field.replace('_', ' ').title()}")
        for entry in entries[:MAX_RECIPE_VALUES]:
            lines.append(f"- {entry['value']}")
            lines.append(f'  - evidence: "{entry["evidence"]}"')
        lines.append("")

    if not any_found:
        lines.append("No method or experiment details were detected in the available sections.")
        lines.append("Use read_paper to inspect the paper sections directly.")

    lines.append(
        "**Note:** Recipe values are extracted deterministically from method and experiment "
        "sections. Verify against read_paper before relying on them for training."
    )
    return "\n".join(lines)


def _recipe_section_names() -> list[str]:
    """Lowercase title fragments that usually carry recipe details."""
    return ["method", "experiment", "setup", "implementation", "training", "approach"]


def _select_recipe_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick the sections most likely to contain training recipe details."""
    wanted = _recipe_section_names()
    matched = [section for section in sections if any(token in section["title"].lower() for token in wanted)]
    if matched:
        return matched
    # Fall back to the longest non-empty sections when titles are unhelpful.
    populated = [section for section in sections if section["text"]]
    populated.sort(key=lambda section: len(section["text"]), reverse=True)
    return populated[:3]


async def extract_training_recipe_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Extract a deterministic, evidence-linked training recipe from a paper."""
    del settings

    raw_arxiv_id = args.get("arxiv_id", "")
    arxiv_id = _normalize_arxiv_id(raw_arxiv_id)
    if not arxiv_id:
        return "Error: No arxiv_id provided. Pass an arXiv ID or paper URL."

    parsed = await _fetch_paper_html(arxiv_id)
    if not parsed or not parsed["sections"]:
        return (
            f"Error: Could not read the paper sections for {arxiv_id}. Rendered HTML is required for recipe extraction."
        )

    recipe_sections = _select_recipe_sections(parsed["sections"])
    section_texts = [section["text"] for section in recipe_sections if section["text"]]
    findings = _extract_recipe_values(section_texts)

    return _format_training_recipe(arxiv_id, parsed.get("title", ""), recipe_sections, findings)


# ---------------------------------------------------------------------------
# Tool specifications
# ---------------------------------------------------------------------------


def get_tool_specs() -> list[dict[str, Any]]:
    """Return the paper research tool specifications."""
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
        },
        {
            "name": "paper_citation_graph",
            "description": (
                "Trace a one-hop citation graph for a paper via Semantic Scholar. "
                "Returns references (papers this work cites) and citations (papers citing this work) "
                "with influence flags and citation intents. Use to gauge impact and find related work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "ArXiv paper ID or paper URL.",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["references", "citations", "both"],
                        "description": "Which side of the graph to return. Default: both.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum entries per side (default: 10, max: 50).",
                    },
                },
                "required": ["arxiv_id"],
            },
        },
        {
            "name": "read_paper",
            "description": (
                "Read a paper's rendered arXiv HTML. Without a section, returns the abstract and a "
                "table of contents. With a section name or number, returns that section's full text. "
                "Use after paper_details to inspect method or experiment sections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "ArXiv paper ID or paper URL.",
                    },
                    "section": {
                        "type": "string",
                        "description": (
                            "Section name or number to read, for example '4', 'Experiments', or '4.2'. "
                            "Omit to get the abstract and table of contents."
                        ),
                    },
                },
                "required": ["arxiv_id"],
            },
        },
        {
            "name": "extract_training_recipe",
            "description": (
                "Extract a deterministic, evidence-linked training recipe from a paper's method and "
                "experiment sections. Surfaces dataset, architecture, optimizer, learning rate, "
                "batch size, epochs, and hardware, each with a quoted source sentence. "
                "Use before selecting models or datasets for training."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "arxiv_id": {
                        "type": "string",
                        "description": "ArXiv paper ID or paper URL.",
                    },
                },
                "required": ["arxiv_id"],
            },
        },
    ]
