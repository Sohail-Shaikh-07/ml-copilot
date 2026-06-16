"""Optional MCP-style tool discovery support.

This module intentionally avoids opening live MCP transports. It loads a
reviewable manifest of discovered tools, registers them behind approval, and
keeps execution stubbed until a future transport layer is added.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.tools.registry import ToolRegistry, ToolSpec

JsonDict = dict[str, Any]

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BLOCKED_MCP_TOOL_NAMES = {
    "apply_patch",
    "run_command",
    "write_file",
    "hf_jobs",
    "hf_doc_search",
    "hf_doc_fetch",
    "hf_whoami",
}


@dataclass(frozen=True)
class MCPToolDescriptor:
    server_name: str
    tool_name: str
    registered_name: str
    description: str
    input_schema: JsonDict


class MCPManifestError(ValueError):
    """Raised when an MCP discovery manifest has an invalid shape."""


def load_mcp_manifest_tools(path: Path) -> list[MCPToolDescriptor]:
    """Load namespaced MCP tool descriptors from a JSON manifest."""
    if not path.exists():
        raise MCPManifestError(f"MCP manifest does not exist: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPManifestError(f"MCP manifest is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise MCPManifestError("MCP manifest must be a JSON object.")

    descriptors: list[MCPToolDescriptor] = []
    for server_name, tools in _iter_manifest_servers(payload):
        if not _is_safe_name(server_name):
            continue
        for tool_payload in tools:
            descriptor = _parse_tool_descriptor(server_name, tool_payload)
            if descriptor is not None:
                descriptors.append(descriptor)
    return descriptors


def register_mcp_manifest_tools(registry: ToolRegistry, manifest_path: Path | None) -> list[ToolSpec]:
    """Register discovered MCP tools as approval-gated placeholders."""
    if manifest_path is None:
        return []

    registered: list[ToolSpec] = []
    for descriptor in load_mcp_manifest_tools(manifest_path):
        if registry.has(descriptor.registered_name):
            continue

        async def _handler(_: JsonDict, item: MCPToolDescriptor = descriptor) -> str:
            return (
                f"MCP tool {item.server_name}/{item.tool_name} is discovered but not executable yet. "
                "A live MCP transport must be configured in a future release before this tool can run."
            )

        registered.append(
            registry.register(
                ToolSpec(
                    name=descriptor.registered_name,
                    description=descriptor.description,
                    input_schema=descriptor.input_schema,
                    handler=_handler,
                    source="mcp",
                    requires_approval=True,
                )
            )
        )
    return registered


def _iter_manifest_servers(payload: JsonDict) -> list[tuple[str, list[JsonDict]]]:
    servers = payload.get("servers")
    if isinstance(servers, list):
        return [
            (str(server.get("name", "")), server["tools"])
            for server in servers
            if isinstance(server, dict) and isinstance(server.get("tools"), list)
        ]

    mcp_servers = payload.get("mcpServers")
    if isinstance(mcp_servers, dict):
        discovered: list[tuple[str, list[JsonDict]]] = []
        for server_name, server_payload in mcp_servers.items():
            if isinstance(server_payload, dict) and isinstance(server_payload.get("tools"), list):
                discovered.append((str(server_name), server_payload["tools"]))
        return discovered

    return []


def _parse_tool_descriptor(server_name: str, payload: Any) -> MCPToolDescriptor | None:
    if not isinstance(payload, dict):
        return None

    tool_name = str(payload.get("name", "")).strip()
    if not _is_safe_name(tool_name) or tool_name in BLOCKED_MCP_TOOL_NAMES:
        return None

    registered_name = f"mcp__{server_name}__{tool_name}"
    if not _is_safe_name(registered_name):
        return None

    description = str(payload.get("description") or f"MCP tool {server_name}/{tool_name}.").strip()
    input_schema = payload.get("input_schema", payload.get("inputSchema", {"type": "object", "properties": {}}))
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}

    return MCPToolDescriptor(
        server_name=server_name,
        tool_name=tool_name,
        registered_name=registered_name,
        description=description,
        input_schema=input_schema,
    )


def _is_safe_name(name: str) -> bool:
    return bool(SAFE_NAME_RE.fullmatch(name))
