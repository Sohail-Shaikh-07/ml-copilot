"""Sandbox-first experiment workspace tools backed by Hugging Face Spaces."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.config import AppSettings
from app.tools.context import current_hf_token, current_session_id

DEFAULT_HARDWARE = "cpu-basic"
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_TIMEOUT_SECONDS = 3600
MAX_COMMAND_OUTPUT_CHARS = 20_000
DEFAULT_READ_BYTES = 64_000
MAX_READ_BYTES = 256_000
SUPPORTED_HARDWARE = {
    "cpu-basic",
    "cpu-upgrade",
    "t4-small",
    "t4-medium",
    "a10g-small",
    "a10g-large",
    "a10g-largex2",
    "a10g-largex4",
    "a100-large",
}
_SAFE_SLUG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


SANDBOX_DOCKERFILE = """\
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn
COPY app.py /app/app.py
RUN mkdir -p /app/workspace
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
"""


SANDBOX_APP = r'''"""Runtime API for ML Copilot experiment sandboxes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

WORKSPACE = Path("/app/workspace").resolve()
MAX_READ_BYTES = 256_000
MAX_COMMAND_TIMEOUT_SECONDS = 3600
MAX_COMMAND_OUTPUT_CHARS = 20_000
TOKEN = os.environ.get("SANDBOX_API_TOKEN", "")

app = FastAPI(title="ML Copilot experiment sandbox")


class WriteRequest(BaseModel):
    path: str
    content: str


class ReadRequest(BaseModel):
    path: str
    max_bytes: int = 64_000


class RunRequest(BaseModel):
    command: str
    timeout_seconds: int = 120


def _authorize(value: str | None) -> None:
    expected = f"Bearer {TOKEN}"
    if not TOKEN or value != expected:
        raise HTTPException(status_code=401, detail="invalid sandbox authorization")


def _resolve_path(value: str) -> Path:
    raw = value.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="path is required")
    posix = PurePosixPath(raw)
    if posix.is_absolute() or any(part in {"..", ""} for part in posix.parts):
        raise HTTPException(status_code=400, detail="path escapes sandbox workspace")
    resolved = (WORKSPACE / Path(*posix.parts)).resolve()
    if WORKSPACE not in (resolved, *resolved.parents):
        raise HTTPException(status_code=400, detail="path escapes sandbox workspace")
    return resolved


def _clip(value: str, limit: int = MAX_COMMAND_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    head = limit // 3
    tail = limit - head
    omitted = len(value) - limit
    return value[:head] + f"\n\n... [{omitted} chars omitted] ...\n\n" + value[-tail:]


def _decode_timeout_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/write")
def write_file(payload: WriteRequest, x_sandbox_authorization: str | None = Header(default=None)):
    _authorize(x_sandbox_authorization)
    target = _resolve_path(payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = payload.content.encode("utf-8")
    target.write_bytes(data)
    return {"path": payload.path, "bytes_written": len(data)}


@app.post("/api/read")
def read_file(payload: ReadRequest, x_sandbox_authorization: str | None = Header(default=None)):
    _authorize(x_sandbox_authorization)
    target = _resolve_path(payload.path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    max_bytes = min(max(int(payload.max_bytes), 1), MAX_READ_BYTES)
    data = target.read_bytes()
    clipped = data[:max_bytes]
    return {
        "path": payload.path,
        "content": clipped.decode("utf-8", errors="replace"),
        "truncated": len(data) > len(clipped),
    }


@app.post("/api/run")
def run_command(payload: RunRequest, x_sandbox_authorization: str | None = Header(default=None)):
    _authorize(x_sandbox_authorization)
    command = payload.command.strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    timeout = min(max(int(payload.timeout_seconds), 1), MAX_COMMAND_TIMEOUT_SECONDS)
    try:
        completed = subprocess.run(
            command,
            cwd=WORKSPACE,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "exit_code": completed.returncode,
            "stdout": _clip(completed.stdout or ""),
            "stderr": _clip(completed.stderr or ""),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "stdout": _clip(_decode_timeout_output(exc.stdout)),
            "stderr": _clip(_decode_timeout_output(exc.stderr)),
            "timed_out": True,
        }
'''


@dataclass(frozen=True)
class SandboxRecord:
    session_id: str
    space_id: str
    hardware: str
    url: str
    api_token: str
    created_at: str


def get_tool_specs() -> list[dict[str, Any]]:
    """Return tool specs for the experiment workspace tool."""
    return [
        {
            "name": "experiment_workspace",
            "description": (
                "Create and use a lightweight Hugging Face Space-backed sandbox for experiment preflight "
                "work: status, write files, read files, run package installs or smoke commands, and teardown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["create", "status", "write", "read", "run", "teardown"],
                        "description": "Sandbox operation to perform.",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Hugging Face namespace/user/org for create. Defaults to the token owner.",
                    },
                    "hardware": {
                        "type": "string",
                        "description": "Hugging Face Space hardware for create. Defaults to cpu-basic.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Sandbox-relative file path for write/read operations.",
                    },
                    "content": {
                        "type": "string",
                        "description": "UTF-8 file content to write into the sandbox.",
                    },
                    "command": {
                        "type": "string",
                        "description": "Shell command to run in the sandbox workspace.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Bounded command timeout in seconds.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Maximum bytes to read from a sandbox file.",
                    },
                },
                "required": ["operation"],
            },
        }
    ]


def _hf_api() -> Any:
    from huggingface_hub import HfApi

    return HfApi(token=current_hf_token())


async def _to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(func, *args, **kwargs)


def _session_key() -> str:
    raw = current_session_id() or "default"
    return _safe_slug(raw).strip(".-_") or "default"


def _safe_slug(value: str) -> str:
    slug = _SAFE_SLUG_RE.sub("-", value.strip()).strip("-").lower()
    return slug[:48] or "sandbox"


def _metadata_dir(settings: AppSettings) -> Path:
    return settings.paths.workspace_root / ".ml-copilot" / "sandboxes"


def _metadata_path(settings: AppSettings) -> Path:
    return _metadata_dir(settings) / f"{_session_key()}.json"


def _load_record(settings: AppSettings) -> SandboxRecord | None:
    path = _metadata_path(settings)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return SandboxRecord(
        session_id=str(data["session_id"]),
        space_id=str(data["space_id"]),
        hardware=str(data["hardware"]),
        url=str(data["url"]),
        api_token=str(data["api_token"]),
        created_at=str(data["created_at"]),
    )


def _save_record(settings: AppSettings, record: SandboxRecord) -> None:
    directory = _metadata_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    _metadata_path(settings).write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")


def _delete_record(settings: AppSettings) -> None:
    path = _metadata_path(settings)
    if path.exists():
        path.unlink()


def _validate_hardware(value: Any) -> str:
    hardware = str(value or DEFAULT_HARDWARE).strip() or DEFAULT_HARDWARE
    if hardware not in SUPPORTED_HARDWARE:
        supported = ", ".join(sorted(SUPPORTED_HARDWARE))
        raise ValueError(f"Unsupported hardware '{hardware}'. Supported hardware: {supported}.")
    return hardware


def _validate_remote_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("path is required.")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise ValueError(f"Path {raw!r} escapes the sandbox workspace.")
    return str(path)


def _normalize_timeout(value: Any) -> int:
    if value in (None, ""):
        return DEFAULT_COMMAND_TIMEOUT_SECONDS
    timeout = int(value)
    return min(max(timeout, 1), MAX_COMMAND_TIMEOUT_SECONDS)


def _normalize_max_bytes(value: Any) -> int:
    if value in (None, ""):
        return DEFAULT_READ_BYTES
    max_bytes = int(value)
    return min(max(max_bytes, 1), MAX_READ_BYTES)


def _truncate_output(value: Any) -> str:
    text = "" if value is None else str(value)
    if len(text) <= MAX_COMMAND_OUTPUT_CHARS:
        return text
    head = MAX_COMMAND_OUTPUT_CHARS // 3
    tail = MAX_COMMAND_OUTPUT_CHARS - head
    omitted = len(text) - MAX_COMMAND_OUTPUT_CHARS
    return text[:head] + f"\n\n... [{omitted} chars omitted] ...\n\n" + text[-tail:]


def _space_runtime_url(space_id: str) -> str:
    owner, name = space_id.split("/", 1)
    return f"https://{owner.replace('_', '-')}-{name.replace('_', '-')}.hf.space"


async def _create_space(api: Any, *, space_id: str, hardware: str, api_token: str) -> None:
    await _to_thread(
        api.create_repo,
        repo_id=space_id,
        repo_type="space",
        private=True,
        exist_ok=True,
        space_sdk="docker",
    )
    await _to_thread(
        api.upload_file,
        repo_id=space_id,
        repo_type="space",
        path_in_repo="Dockerfile",
        path_or_fileobj=SANDBOX_DOCKERFILE.encode("utf-8"),
    )
    await _to_thread(
        api.upload_file,
        repo_id=space_id,
        repo_type="space",
        path_in_repo="app.py",
        path_or_fileobj=SANDBOX_APP.encode("utf-8"),
    )
    await _to_thread(
        api.add_space_secret,
        repo_id=space_id,
        key="SANDBOX_API_TOKEN",
        value=api_token,
    )
    await _to_thread(api.request_space_hardware, repo_id=space_id, hardware=hardware)


def _format_record(record: SandboxRecord) -> str:
    return "\n".join(
        [
            f"- Space: {record.space_id}",
            f"- URL: {record.url}",
            f"- Hardware: {record.hardware}",
            f"- Created: {record.created_at}",
        ]
    )


def _require_token() -> str | None:
    token = current_hf_token()
    return token if token else None


def _require_record(settings: AppSettings) -> SandboxRecord | str:
    record = _load_record(settings)
    if record is None:
        return "Error: No active experiment workspace for this session. Run operation='create' first."
    return record


def _require_remote_token() -> str | None:
    return _require_token()


def _sandbox_headers(record: SandboxRecord) -> dict[str, str]:
    headers = {"X-Sandbox-Authorization": f"Bearer {record.api_token}"}
    token = current_hf_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _post_sandbox(
    record: SandboxRecord,
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    import httpx

    url = f"{record.url.rstrip('/')}{endpoint}"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, json=payload, headers=_sandbox_headers(record))
        response.raise_for_status()
        return dict(response.json())


async def _create(args: dict[str, Any], settings: AppSettings) -> str:
    if not _require_token():
        return "Error: A Hugging Face token is required to create an experiment workspace."

    try:
        hardware = _validate_hardware(args.get("hardware"))
    except ValueError as exc:
        return f"Error: {exc}"

    namespace = str(args.get("namespace") or "").strip()
    if not namespace:
        try:
            whoami = await _to_thread(_hf_api().whoami)
            namespace = str(whoami.get("name") or whoami.get("fullname") or "").strip()
        except Exception:
            namespace = ""
    if not namespace:
        return "Error: Provide a Hugging Face namespace for the sandbox Space."

    session = _session_key()
    space_id = f"{_safe_slug(namespace)}/ml-copilot-sandbox-{session}"
    api_token = secrets.token_urlsafe(32)
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record = SandboxRecord(
        session_id=current_session_id() or "default",
        space_id=space_id,
        hardware=hardware,
        url=_space_runtime_url(space_id),
        api_token=api_token,
        created_at=created_at,
    )

    try:
        await _create_space(_hf_api(), space_id=space_id, hardware=hardware, api_token=api_token)
    except Exception as exc:
        return f"Error: Failed to create experiment workspace: {exc}"

    _save_record(settings, record)
    return "Experiment workspace created.\n" + _format_record(record)


async def _status(settings: AppSettings) -> str:
    record = _load_record(settings)
    if record is None:
        return "No active experiment workspace for this session."
    return "Active experiment workspace:\n" + _format_record(record)


async def _write(args: dict[str, Any], settings: AppSettings) -> str:
    record = _require_record(settings)
    if isinstance(record, str):
        return record
    if not _require_remote_token():
        return "Error: A Hugging Face token is required to access the experiment workspace."
    try:
        path = _validate_remote_path(args.get("path"))
    except ValueError as exc:
        return f"Error: {exc}"
    content = args.get("content")
    if content is None:
        return "Error: content is required for write."
    try:
        response = await _post_sandbox(
            record,
            "/api/write",
            {"path": path, "content": str(content)},
            timeout_seconds=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return f"Error: Failed to write sandbox file: {exc}"
    return f"Wrote {response.get('path', path)} ({response.get('bytes_written', 0)} bytes)."


async def _read(args: dict[str, Any], settings: AppSettings) -> str:
    record = _require_record(settings)
    if isinstance(record, str):
        return record
    if not _require_remote_token():
        return "Error: A Hugging Face token is required to access the experiment workspace."
    try:
        path = _validate_remote_path(args.get("path"))
        max_bytes = _normalize_max_bytes(args.get("max_bytes"))
    except (TypeError, ValueError) as exc:
        return f"Error: {exc}"
    try:
        response = await _post_sandbox(
            record,
            "/api/read",
            {"path": path, "max_bytes": max_bytes},
            timeout_seconds=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return f"Error: Failed to read sandbox file: {exc}"

    content = str(response.get("content", ""))
    suffix = "\n[truncated]" if response.get("truncated") else ""
    return f"### {response.get('path', path)}\n\n{content}{suffix}"


async def _run(args: dict[str, Any], settings: AppSettings) -> str:
    record = _require_record(settings)
    if isinstance(record, str):
        return record
    if not _require_remote_token():
        return "Error: A Hugging Face token is required to access the experiment workspace."
    command = str(args.get("command") or "").strip()
    if not command:
        return "Error: command is required for run."
    try:
        timeout = _normalize_timeout(args.get("timeout_seconds"))
    except (TypeError, ValueError) as exc:
        return f"Error: timeout_seconds must be an integer: {exc}"

    try:
        response = await _post_sandbox(
            record,
            "/api/run",
            {"command": command, "timeout_seconds": timeout},
            timeout_seconds=timeout + 5,
        )
    except Exception as exc:
        return f"Error: Failed to run sandbox command: {exc}"

    lines = [f"Command: {command}"]
    if response.get("exit_code") is not None:
        lines.append(f"Exit code: {response.get('exit_code')}")
    if response.get("timed_out"):
        lines.append("Status: timed out")
    stdout = _truncate_output(response.get("stdout", "")).strip()
    stderr = _truncate_output(response.get("stderr", "")).strip()
    if stdout:
        lines.extend(["", "Stdout:", stdout])
    if stderr:
        lines.extend(["", "Stderr:", stderr])
    if not stdout and not stderr:
        lines.extend(["", "(no output)"])
    return "\n".join(lines)


async def _teardown(settings: AppSettings) -> str:
    record = _require_record(settings)
    if isinstance(record, str):
        return record
    if not _require_token():
        return "Error: A Hugging Face token is required to tear down an experiment workspace."
    try:
        await _to_thread(_hf_api().delete_repo, repo_id=record.space_id, repo_type="space")
    except Exception as exc:
        return f"Error: Failed to tear down experiment workspace: {exc}"
    _delete_record(settings)
    return f"Experiment workspace torn down: {record.space_id}"


async def experiment_workspace_handler(args: dict[str, Any], settings: AppSettings) -> str:
    """Handle experiment workspace operations."""
    operation = str(args.get("operation") or "").strip().lower()
    if not operation:
        return "Error: operation is required."
    if operation == "create":
        return await _create(args, settings)
    if operation == "status":
        return await _status(settings)
    if operation == "write":
        return await _write(args, settings)
    if operation == "read":
        return await _read(args, settings)
    if operation == "run":
        return await _run(args, settings)
    if operation == "teardown":
        return await _teardown(settings)
    return f"Error: Unknown experiment workspace operation {operation!r}."
