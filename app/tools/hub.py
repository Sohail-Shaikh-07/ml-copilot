"""Hugging Face Hub discovery and repo inspection tools."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import AppSettings
from app.tools.context import current_hf_token

HF_API = "https://huggingface.co/api"
HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"
MAX_SEARCH_RESULTS = 10


async def search_hub_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Search Hub models or datasets and rank lightweight fit signals."""
    del settings

    repo_type = _repo_type(args.get("repo_type", "model"))
    query = str(args.get("query", "")).strip()
    task = str(args.get("task", "")).strip()
    license_name = str(args.get("license", "")).strip()
    tags = _normalize_tags(args.get("tags"))
    limit = _bounded_limit(args.get("limit", 5))

    if not query and not task and not tags:
        return "Error: Provide at least one of query, task, or tags."

    endpoint = "models" if repo_type == "model" else "datasets"
    params: dict[str, Any] = {
        "limit": limit,
        "sort": str(args.get("sort") or "downloads"),
        "direction": -1,
        "full": "true",
    }
    if query:
        params["search"] = query
    if repo_type == "model" and task:
        params["pipeline_tag"] = task
    filters = [*tags]
    if repo_type == "dataset" and task:
        filters.insert(0, task)
    if filters:
        params["filter"] = ",".join(filters)

    headers = _auth_headers()
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            response = await client.get(f"{HF_API}/{endpoint}", params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return f"Error searching Hugging Face Hub: {exc}"

    if not isinstance(payload, list) or not payload:
        return "No matching Hub repositories found."

    scored = []
    for item in payload[:limit]:
        if not isinstance(item, dict) or not _repo_id(item):
            continue
        scored.append(
            _scored_candidate(
                item,
                repo_type=repo_type,
                query=query,
                task=task,
                tags=tags,
                license_name=license_name,
            )
        )
    if not scored:
        return "No valid Hub repository metadata was returned."
    scored.sort(key=lambda item: item["score"], reverse=True)
    return _format_search_results(
        scored,
        repo_type=repo_type,
        query=query,
        task=task,
        tags=tags,
        license_name=license_name,
    )


async def inspect_hub_repo_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Inspect a specific Hub model or dataset for fit and schema signals."""
    del settings

    repo_id = str(args.get("repo_id", "")).strip()
    if not repo_id:
        return "Error: repo_id is required."

    repo_type = _repo_type(args.get("repo_type", "model"))
    task = str(args.get("task", "")).strip()
    required_columns = _normalize_tags(args.get("required_columns"))

    endpoint = "models" if repo_type == "model" else "datasets"
    headers = _auth_headers()
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            response = await client.get(f"{HF_API}/{endpoint}/{repo_id}")
            response.raise_for_status()
            repo = response.json()

            dataset_schema = None
            if repo_type == "dataset":
                dataset_schema = await _fetch_dataset_schema(client, repo_id)
    except Exception as exc:
        return f"Error inspecting Hub repository: {exc}"

    if not isinstance(repo, dict):
        return "Error: Hub repository response was not an object."

    return _format_repo_details(
        repo,
        repo_type=repo_type,
        task=task,
        required_columns=required_columns,
        dataset_schema=dataset_schema,
    )


def _auth_headers() -> dict[str, str]:
    token = current_hf_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _repo_type(value: Any) -> str:
    repo_type = str(value or "model").strip().lower()
    return "dataset" if repo_type == "dataset" else "model"


def _bounded_limit(value: Any) -> int:
    try:
        return max(1, min(int(value), MAX_SEARCH_RESULTS))
    except (TypeError, ValueError):
        return 5


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = [str(value)]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = item.strip()
        if tag and tag.lower() not in seen:
            result.append(tag)
            seen.add(tag.lower())
    return result


def _repo_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("modelId") or item.get("datasetId") or "").strip()


def _repo_tags(item: dict[str, Any]) -> list[str]:
    tags = item.get("tags")
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags if str(tag).strip()]


def _license(item: dict[str, Any]) -> str:
    card_data_value = item.get("cardData")
    card_data: dict[str, Any] = card_data_value if isinstance(card_data_value, dict) else {}
    for value in (item.get("license"), card_data.get("license")):
        if isinstance(value, str) and value:
            return value
    for tag in _repo_tags(item):
        if tag.startswith("license:"):
            return tag.split(":", 1)[1]
    return "unknown"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _scored_candidate(
    item: dict[str, Any],
    *,
    repo_type: str,
    query: str,
    task: str,
    tags: list[str],
    license_name: str,
) -> dict[str, Any]:
    repo_id = _repo_id(item)
    repo_tags = _repo_tags(item)
    repo_task = str(item.get("pipeline_tag") or item.get("task") or "")
    repo_license = _license(item)
    downloads = _safe_int(item.get("downloads"))
    likes = _safe_int(item.get("likes"))

    score = min(downloads, 100_000) // 2_000 + min(likes, 10_000) // 200
    reasons: list[str] = []

    haystack = " ".join([repo_id, repo_task, repo_license, *repo_tags]).lower()
    if query and query.lower() in haystack:
        score += 20
        reasons.append("query match")
    if task and (task.lower() == repo_task.lower() or task.lower() in haystack):
        score += 25
        reasons.append("task match")
    for tag in tags:
        if tag.lower() in haystack:
            score += 8
            reasons.append(f"tag:{tag}")
    if license_name and license_name.lower() in repo_license.lower():
        score += 10
        reasons.append("license match")
    if item.get("gated") or item.get("private"):
        score -= 5
        reasons.append("requires access")
    if repo_type == "dataset" and any(tag in {"parquet", "viewer", "croissant"} for tag in repo_tags):
        score += 5
        reasons.append("preview-friendly")

    return {
        "id": repo_id,
        "score": score,
        "task": repo_task or "-",
        "license": repo_license,
        "downloads": downloads,
        "likes": likes,
        "tags": repo_tags,
        "gated": bool(item.get("gated") or item.get("private")),
        "reasons": reasons or ["metadata-ranked"],
    }


def _format_search_results(
    scored: list[dict[str, Any]],
    *,
    repo_type: str,
    query: str,
    task: str,
    tags: list[str],
    license_name: str,
) -> str:
    label = "models" if repo_type == "model" else "datasets"
    sections = [f"## Hub {label} discovery", ""]
    filters = []
    if query:
        filters.append(f"query={query}")
    if task:
        filters.append(f"task={task}")
    if tags:
        filters.append("tags=" + ", ".join(tags))
    if license_name:
        filters.append(f"license={license_name}")
    if filters:
        sections.append("**Filters:** " + " | ".join(filters))
        sections.append("")

    sections.append("| Score | Repository | Task | License | Downloads | Likes | Fit signals |")
    sections.append("|---:|---|---|---|---:|---:|---|")
    for item in scored:
        repo_url = _hub_url(item["id"], repo_type)
        signals = ", ".join(item["reasons"])
        if item["gated"]:
            signals = f"{signals}, gated/private"
        sections.append(
            f"| {item['score']} | [{item['id']}]({repo_url}) | {item['task']} | "
            f"{item['license']} | {item['downloads']} | {item['likes']} | {signals} |"
        )

    sections.append("")
    sections.append("Next step: call `inspect_hub_repo` on the strongest candidates before training.")
    return "\n".join(sections)


async def _fetch_dataset_schema(client: httpx.AsyncClient, repo_id: str) -> dict[str, Any] | None:
    try:
        splits_response = await client.get(f"{HF_DATASETS_SERVER}/splits", params={"dataset": repo_id})
        if splits_response.status_code != 200:
            return None
        splits_payload = splits_response.json()
        splits = splits_payload.get("splits", []) if isinstance(splits_payload, dict) else []
        config = splits[0].get("config", "default") if splits else "default"
        split = splits[0].get("split", "train") if splits else "train"
        info_response = await client.get(f"{HF_DATASETS_SERVER}/info", params={"dataset": repo_id, "config": config})
        if info_response.status_code != 200:
            return {"config": config, "split": split, "features": {}}
        info_payload = info_response.json()
        features = info_payload.get("dataset_info", {}).get("features", {})
        return {"config": config, "split": split, "features": features if isinstance(features, dict) else {}}
    except Exception:  # nosec B110
        return None


def _format_repo_details(
    repo: dict[str, Any],
    *,
    repo_type: str,
    task: str,
    required_columns: list[str],
    dataset_schema: dict[str, Any] | None,
) -> str:
    repo_id = _repo_id(repo)
    repo_tags = _repo_tags(repo)
    repo_task = str(repo.get("pipeline_tag") or repo.get("task") or "unknown")
    repo_license = _license(repo)
    downloads = _safe_int(repo.get("downloads"))
    likes = _safe_int(repo.get("likes"))

    sections = [f"## {repo_id} ({repo_type})", ""]
    sections.append(f"**URL:** {_hub_url(repo_id, repo_type)}")
    sections.append(f"**Task:** {repo_task}")
    sections.append(f"**License:** {repo_license}")
    sections.append(f"**Downloads:** {downloads:,} | **Likes:** {likes:,}")
    if repo.get("gated") or repo.get("private"):
        sections.append("**Access:** gated/private; requires the active Hugging Face token.")
    if repo_tags:
        sections.append(f"**Tags:** {', '.join(repo_tags[:20])}")
    sections.append("")

    fit = _fit_summary(repo_task=repo_task, task=task, license_name=repo_license)
    sections.append("### Fit")
    sections.extend(f"- {line}" for line in fit)

    if dataset_schema is not None:
        features = dataset_schema.get("features") or {}
        columns = list(features)
        sections.append("")
        sections.append(f"### Dataset Schema ({dataset_schema.get('config')}/{dataset_schema.get('split')})")
        if columns:
            sections.append("| Column | Type |")
            sections.append("|---|---|")
            for name, info in list(features.items())[:20]:
                if isinstance(info, dict):
                    dtype = info.get("dtype") or info.get("_type") or "unknown"
                else:
                    dtype = type(info).__name__
                sections.append(f"| {name} | {dtype} |")
        else:
            sections.append("No schema preview was available from datasets-server.")
        if required_columns:
            missing = [column for column in required_columns if column not in columns]
            status = "pass" if not missing else "missing " + ", ".join(missing)
            sections.append("")
            sections.append(f"**Required columns check:** {status}")

    return "\n".join(sections)


def _fit_summary(*, repo_task: str, task: str, license_name: str) -> list[str]:
    summary: list[str] = []
    if task:
        if task.lower() == repo_task.lower() or task.lower() in repo_task.lower():
            summary.append(f"Task fit: matches requested task `{task}`.")
        else:
            summary.append(f"Task fit: requested `{task}`, repo reports `{repo_task}`.")
    else:
        summary.append("Task fit: no requested task supplied; verify against the training recipe.")
    if license_name == "unknown":
        summary.append("License fit: unknown; inspect the model/dataset card before commercial use.")
    else:
        summary.append(f"License fit: `{license_name}` reported by Hub metadata.")
    return summary


def _hub_url(repo_id: str, repo_type: str) -> str:
    if repo_type == "dataset":
        return f"https://huggingface.co/datasets/{repo_id}"
    return f"https://huggingface.co/{repo_id}"


def get_tool_specs() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool specifications."""
    return [
        {
            "name": "search_hub",
            "description": (
                "Search Hugging Face Hub models or datasets and rank candidates by task, license, "
                "tags, popularity, and access signals. Use before selecting a base model or dataset."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_type": {"type": "string", "enum": ["model", "dataset"], "description": "Hub repo type."},
                    "query": {"type": "string", "description": "Search query such as 'sentiment' or 'qwen instruct'."},
                    "task": {
                        "type": "string",
                        "description": "Desired task/pipeline tag, such as text-classification.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Preferred Hub tags, libraries, modalities, or dataset traits.",
                    },
                    "license": {"type": "string", "description": "Preferred license keyword."},
                    "sort": {"type": "string", "description": "Hub sort field, default downloads."},
                    "limit": {"type": "integer", "description": "Number of candidates to return, max 10."},
                },
            },
        },
        {
            "name": "inspect_hub_repo",
            "description": (
                "Inspect a Hugging Face model or dataset for license, task compatibility, access "
                "requirements, and dataset schema. Use after search_hub before training."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_id": {"type": "string", "description": "Hub repository ID, e.g. Qwen/Qwen2.5-0.5B."},
                    "repo_type": {"type": "string", "enum": ["model", "dataset"], "description": "Hub repo type."},
                    "task": {"type": "string", "description": "Requested task to compare against repo metadata."},
                    "required_columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dataset columns required by the planned training recipe.",
                    },
                },
                "required": ["repo_id"],
            },
        },
    ]
