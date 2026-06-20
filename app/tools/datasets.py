"""Dataset inspection tool for local files and Hugging Face datasets."""

from __future__ import annotations

import asyncio
import csv
import json
import shutil
from pathlib import Path
from typing import Any

import httpx

from app.config import AppSettings
from app.tools.context import current_hf_token
from app.tools.workspace import _safe_path

HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"
MAX_SAMPLE_ROWS = 5
MAX_VALUE_LEN = 120
MAX_LOCAL_ROWS_SCAN = 10_000
SUPPORTED_DATASET_EXTENSIONS = {".csv", ".tsv", ".jsonl", ".json", ".parquet"}


async def inspect_dataset_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Tool handler: inspect a local file or HF dataset."""
    source = str(args.get("source", "")).strip()
    if not source:
        return "Error: No source provided. Pass a local file path or HF dataset name (e.g. 'imdb')."

    source_kind = str(args.get("source_kind", "auto")).strip().lower()
    if source_kind == "local":
        return await _inspect_local(source, args, settings)
    if source_kind == "hub":
        return await _inspect_hf(source, args)
    if source.startswith(("./", "../", ".\\", "..\\", "/")):
        return await _inspect_local(source, args, settings)
    # Has a slash — could be HF namespace (user/dataset) or a local subpath
    if _looks_like_local_path(source, settings.paths.workspace_root):
        return await _inspect_local(source, args, settings)
    if "/" not in source and "\\" not in source and Path(source).suffix.lower() in SUPPORTED_DATASET_EXTENSIONS:
        return await _inspect_local(source, args, settings)
    return await _inspect_hf(source, args)


async def ingest_dataset_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Validate and copy a workspace-local dataset into managed BYOD storage."""
    source = str(args.get("source", "")).strip()
    if not source:
        return "Error: source is required."

    workspace_root = settings.paths.workspace_root
    source_path = Path(source) if Path(source).is_absolute() else workspace_root / source
    safe_source = _safe_path(source_path, workspace_root)
    if safe_source is None:
        return f"Error: Path {source!r} is outside workspace root."
    if not safe_source.exists() or not safe_source.is_file():
        return f"Error: Dataset file not found: {source}"

    filename_error = validate_dataset_filename(safe_source.name)
    if filename_error:
        return f"Error: {filename_error}"

    destination_dir = workspace_root / ".ml-copilot" / "datasets"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(destination_dir, safe_source.name)
    if safe_source.resolve() != destination.resolve():
        shutil.copy2(safe_source, destination)

    managed_path = destination.relative_to(workspace_root).as_posix()
    original_path = safe_source.relative_to(workspace_root).as_posix()
    preview = await _inspect_local(managed_path, args, settings)
    return (
        "## BYOD dataset ingested\n\n"
        f"**Managed path:** `{managed_path}`\n"
        f"**Original path:** `{original_path}`\n\n"
        f"{preview}"
    )


def validate_dataset_filename(filename: str) -> str | None:
    """Validate a user-provided dataset filename."""
    safe_name = Path(filename).name
    if safe_name != filename or safe_name in {"", ".", ".."}:
        return "Filename must not contain directory components."
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_DATASET_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DATASET_EXTENSIONS))
        return f"Unsupported file type '{extension}'. Supported: {supported}"
    return None


def _unique_destination(directory: Path, filename: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _looks_like_local_path(source: str, workspace_root: Path) -> bool:
    """Return True only if source resolves to an existing workspace file."""
    candidate = workspace_root / source
    return candidate.exists()


# --- Local file inspection ---


async def _inspect_local(source: str, args: dict[str, Any], settings: AppSettings) -> str:
    """Inspect a local CSV, JSONL, or Parquet file."""
    workspace_root = settings.paths.workspace_root
    path = Path(source) if Path(source).is_absolute() else workspace_root / source
    safe = _safe_path(path, workspace_root)
    if safe is None:
        return f"Error: Path {source!r} is outside workspace root."
    if not safe.exists():
        return f"Error: File not found: {source}"
    if safe.is_dir():
        return "Error: Path is a directory. Provide a file path."

    ext = safe.suffix.lower()
    sample_rows = min(args.get("sample_rows", MAX_SAMPLE_ROWS), MAX_SAMPLE_ROWS)

    if ext in (".csv", ".tsv"):
        return _inspect_csv(safe, sample_rows, delimiter="\t" if ext == ".tsv" else ",")
    elif ext == ".jsonl":
        return _inspect_jsonl(safe, sample_rows)
    elif ext == ".json":
        return _inspect_json(safe, sample_rows)
    elif ext == ".parquet":
        return _inspect_parquet(safe, sample_rows)
    else:
        return f"Error: Unsupported file type '{ext}'. Supported: .csv, .tsv, .jsonl, .json, .parquet"


def _inspect_csv(path: Path, sample_rows: int, delimiter: str = ",") -> str:
    """Inspect a CSV/TSV file by streaming line-by-line."""
    try:
        f = path.open(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error reading file: {e}"

    rows: list[list[str]] = []
    hit_limit = False
    with f:
        reader = csv.reader(f, delimiter=delimiter)
        for i, row in enumerate(reader):
            if i >= MAX_LOCAL_ROWS_SCAN:
                hit_limit = True
                break
            rows.append(row)

    if not rows:
        return "Error: File is empty."

    headers = rows[0]
    data_rows = rows[1:]
    total_rows = len(data_rows)

    # Compute missing values per column
    missing: dict[str, int] = {h: 0 for h in headers}
    for row in data_rows:
        for i, h in enumerate(headers):
            val = row[i] if i < len(row) else ""
            if val.strip() == "":
                missing[h] += 1

    fmt_name = "TSV" if delimiter == "\t" else "CSV"
    row_label = f"{total_rows:,}+" if hit_limit else f"{total_rows:,}"
    sections = [f"## {path.name}", ""]
    sections.append(f"**Format:** {fmt_name} | **Rows:** {row_label} | **Columns:** {len(headers)}")
    sections.append("")

    # Schema table
    sections.append("### Columns")
    sections.append("| # | Column | Missing |")
    sections.append("|---|--------|---------|")
    for i, h in enumerate(headers, 1):
        m = missing[h]
        pct = f"{m}/{total_rows} ({100 * m // max(total_rows, 1)}%)" if m > 0 else "0"
        sections.append(f"| {i} | {h} | {pct} |")

    # Sample rows
    sections.append("")
    sections.append("### Sample Rows")
    for idx, row in enumerate(data_rows[:sample_rows], 1):
        sections.append(f"**Row {idx}:**")
        for i, h in enumerate(headers):
            val = row[i] if i < len(row) else ""
            if len(val) > MAX_VALUE_LEN:
                val = val[:MAX_VALUE_LEN] + "..."
            sections.append(f"- {h}: {val}")

    return "\n".join(sections)


def _inspect_jsonl(path: Path, sample_rows: int) -> str:
    """Inspect a JSONL file by streaming line-by-line."""
    records: list[dict[str, Any]] = []
    parse_errors = 0
    hit_limit = False

    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= MAX_LOCAL_ROWS_SCAN:
                    hit_limit = True
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    parse_errors += 1
    except OSError as e:
        return f"Error reading file: {e}"

    if not records:
        return "Error: No valid JSON records found."

    return _format_json_records(path.name, "JSONL", records, parse_errors, hit_limit, sample_rows)


def _inspect_json(path: Path, sample_rows: int) -> str:
    """Inspect a .json file — handles both JSON arrays and JSONL."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            first_char = ""
            for ch in f.read(64):
                if ch.strip():
                    first_char = ch
                    break
    except OSError as e:
        return f"Error reading file: {e}"

    # JSON array
    if first_char == "[":
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return "Error: Expected a JSON array of records."
            records = [r for r in data[:MAX_LOCAL_ROWS_SCAN] if isinstance(r, dict)]
            hit_limit = len(data) > MAX_LOCAL_ROWS_SCAN
            if not records:
                return "Error: No valid JSON records found."
            return _format_json_records(path.name, "JSON array", records, 0, hit_limit, sample_rows)
        except json.JSONDecodeError as e:
            return f"Error parsing JSON: {e}"

    # Fall back to JSONL
    return _inspect_jsonl(path, sample_rows)


def _format_json_records(
    filename: str,
    fmt: str,
    records: list[dict[str, Any]],
    parse_errors: int,
    hit_limit: bool,
    sample_rows: int,
) -> str:
    """Format inspection output for JSON-based records."""
    all_keys: dict[str, set[str]] = {}
    for rec in records:
        for k, v in rec.items():
            all_keys.setdefault(k, set()).add(type(v).__name__)

    missing: dict[str, int] = {k: 0 for k in all_keys}
    for rec in records:
        for k in all_keys:
            if k not in rec or rec[k] is None:
                missing[k] += 1

    total = len(records)
    row_label = f"{total:,}+" if hit_limit else f"{total:,}"
    sections = [f"## {filename}", ""]
    sections.append(f"**Format:** {fmt} | **Records:** {row_label} | **Fields:** {len(all_keys)}")
    if parse_errors:
        sections.append(f"**Parse errors:** {parse_errors}")
    sections.append("")

    sections.append("### Fields")
    sections.append("| # | Field | Types | Missing |")
    sections.append("|---|-------|-------|---------|")
    for i, (k, types) in enumerate(all_keys.items(), 1):
        m = missing[k]
        pct = f"{m}/{total} ({100 * m // max(total, 1)}%)" if m > 0 else "0"
        sections.append(f"| {i} | {k} | {', '.join(sorted(types))} | {pct} |")

    sections.append("")
    sections.append("### Sample Records")
    for idx, rec in enumerate(records[:sample_rows], 1):
        sections.append(f"**Record {idx}:**")
        for k, v in rec.items():
            val = str(v)
            if len(val) > MAX_VALUE_LEN:
                val = val[:MAX_VALUE_LEN] + "..."
            sections.append(f"- {k}: {val}")

    return "\n".join(sections)


def _inspect_parquet(path: Path, sample_rows: int) -> str:
    """Inspect a Parquet file (requires pyarrow)."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return "Error: `pyarrow` is not installed. Install it with `pip install pyarrow` to inspect Parquet files."

    try:
        pf = pq.ParquetFile(str(path))
    except Exception as e:
        return f"Error reading Parquet file: {e}"

    metadata = pf.metadata
    schema = pf.schema_arrow
    total_rows = metadata.num_rows

    sections = [f"## {path.name}", ""]
    sections.append(
        f"**Format:** Parquet | **Rows:** {total_rows:,} | "
        f"**Columns:** {schema.num_fields} | "
        f"**Row groups:** {metadata.num_row_groups}"
    )
    sections.append("")

    sections.append("### Columns")
    sections.append("| # | Column | Type |")
    sections.append("|---|--------|------|")
    for i, field in enumerate(schema, 1):
        sections.append(f"| {i} | {field.name} | {field.type} |")

    # Sample rows
    try:
        table = pf.read_row_group(0)
        sample = table.slice(0, sample_rows).to_pydict()
        sections.append("")
        sections.append("### Sample Rows")
        keys = list(sample.keys())
        for idx in range(min(sample_rows, len(sample[keys[0]]))):
            sections.append(f"**Row {idx + 1}:**")
            for k in keys:
                val = str(sample[k][idx])
                if len(val) > MAX_VALUE_LEN:
                    val = val[:MAX_VALUE_LEN] + "..."
                sections.append(f"- {k}: {val}")
    except Exception as e:  # nosec B110
        sections.append(f"\n(Could not read sample rows: {e})")

    return "\n".join(sections)


# --- HF dataset inspection ---


async def _inspect_hf(source: str, args: dict[str, Any]) -> str:
    """Inspect a Hugging Face dataset via datasets-server API."""
    dataset = source
    config = args.get("config")
    split = args.get("split")
    sample_rows = min(args.get("sample_rows", 3), MAX_SAMPLE_ROWS)
    token = current_hf_token()

    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    sections = [f"## {dataset} (Hugging Face)", ""]

    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        # Check validity and get splits
        try:
            valid_resp, splits_resp = await _hf_parallel(
                client,
                [
                    (f"{HF_DATASETS_SERVER}/is-valid", {"dataset": dataset}),
                    (f"{HF_DATASETS_SERVER}/splits", {"dataset": dataset}),
                ],
            )
        except Exception as e:
            return f"Error querying HF datasets-server: {e}"

        # Status
        if valid_resp and valid_resp.get("preview"):
            sections.append("**Status:** ✓ Valid (preview available)")
        else:
            sections.append("**Status:** Dataset may have limited availability")
        sections.append("")

        # Splits
        configs = _extract_configs(splits_resp) if splits_resp else []
        if configs:
            if not config:
                config = configs[0]["name"]
            if not split:
                split = configs[0]["splits"][0] if configs[0]["splits"] else "train"

            sections.append("### Structure")
            sections.append("| Config | Splits |")
            sections.append("|--------|--------|")
            for cfg in configs[:10]:
                sections.append(f"| {cfg['name']} | {', '.join(cfg['splits'][:5])} |")
            sections.append("")

        if not config:
            config = "default"
        if not split:
            split = "train"

        # Schema and sample rows
        try:
            info_resp, rows_resp = await _hf_parallel(
                client,
                [
                    (f"{HF_DATASETS_SERVER}/info", {"dataset": dataset, "config": config}),
                    (
                        f"{HF_DATASETS_SERVER}/first-rows",
                        {"dataset": dataset, "config": config, "split": split},
                    ),
                ],
            )
        except Exception:
            info_resp, rows_resp = None, None

        if info_resp:
            features = info_resp.get("dataset_info", {}).get("features", {})
            if features:
                sections.append("### Schema")
                sections.append("| Column | Type |")
                sections.append("|--------|------|")
                for col, info in features.items():
                    dtype = info.get("dtype") or info.get("_type", "unknown")
                    sections.append(f"| {col} | {dtype} |")
                sections.append("")

        if rows_resp:
            rows = rows_resp.get("rows", [])[:sample_rows]
            if rows:
                sections.append(f"### Sample Rows ({config}/{split})")
                for idx, row_wrapper in enumerate(rows, 1):
                    row = row_wrapper.get("row", {})
                    sections.append(f"**Row {idx}:**")
                    for k, v in row.items():
                        val = str(v)
                        if len(val) > MAX_VALUE_LEN:
                            val = val[:MAX_VALUE_LEN] + "..."
                        sections.append(f"- {k}: {val}")

    return "\n".join(sections)


async def _hf_parallel(
    client: httpx.AsyncClient,
    requests: list[tuple[str, dict[str, str]]],
) -> list[dict[str, Any] | None]:
    """Make parallel GET requests, return parsed JSON or None."""

    async def _get(url: str, params: dict[str, str]) -> dict[str, Any] | None:
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                return resp.json()
        except Exception:  # nosec B110
            pass  # Individual API failures are non-fatal
        return None

    results = await asyncio.gather(*[_get(url, params) for url, params in requests])
    return list(results)


def _extract_configs(splits_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Group splits by config from HF splits response."""
    configs: dict[str, dict[str, Any]] = {}
    for s in splits_data.get("splits", []):
        cfg = s.get("config", "default")
        if cfg not in configs:
            configs[cfg] = {"name": cfg, "splits": []}
        configs[cfg]["splits"].append(s.get("split", ""))
    return list(configs.values())


def get_tool_specs() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool specifications."""
    return [
        {
            "name": "inspect_dataset",
            "description": (
                "Inspect a dataset's metadata, schema, and sample rows. "
                "Supports local CSV/TSV/JSONL/Parquet files and Hugging Face datasets. "
                "For local files, pass the file path. For HF datasets, pass the dataset name (e.g. 'imdb')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": (
                            "Local file path or HF dataset name "
                            "(e.g. 'data/train.csv' or 'imdb' or 'username/dataset')."
                        ),
                    },
                    "source_kind": {
                        "type": "string",
                        "enum": ["auto", "local", "hub"],
                        "description": "Force local or Hub routing when auto-detection is ambiguous.",
                    },
                    "config": {
                        "type": "string",
                        "description": "HF dataset config name (optional, auto-detected).",
                    },
                    "split": {
                        "type": "string",
                        "description": "HF dataset split (optional, defaults to first available).",
                    },
                    "sample_rows": {
                        "type": "integer",
                        "description": "Number of sample rows to show (default: 3, max: 5).",
                    },
                },
                "required": ["source"],
            },
        },
        {
            "name": "ingest_dataset",
            "description": (
                "Ingest a user-provided dataset from a workspace-local path into managed BYOD "
                "storage, validate its format, and return a lightweight schema/sample preview."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Workspace-local CSV, TSV, JSON, JSONL, or Parquet file path.",
                    },
                    "sample_rows": {
                        "type": "integer",
                        "description": "Number of preview rows to show (default: 5, max: 5).",
                    },
                },
                "required": ["source"],
            },
        },
    ]
