import asyncio
import json
from pathlib import Path

import pytest

from app.agent.loop import _create_tool_registry
from app.config import AppSettings
from app.tools.mcp import MCPManifestError, load_mcp_manifest_tools, register_mcp_manifest_tools
from app.tools.registry import ToolRegistry


def run(coro):
    return asyncio.run(coro)


def write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_mcp_manifest_tools_namespaces_and_filters_tools(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path / "mcp-tools.json",
        {
            "servers": [
                {
                    "name": "research",
                    "tools": [
                        {
                            "name": "search_papers",
                            "description": "Search paper metadata.",
                            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                        },
                        {"name": "run_command", "description": "Blocked builtin name."},
                        {"name": "bad name", "description": "Unsafe name."},
                    ],
                },
                {"name": "bad server", "tools": [{"name": "safe_tool"}]},
            ]
        },
    )

    tools = load_mcp_manifest_tools(manifest)

    assert [tool.registered_name for tool in tools] == ["mcp__research__search_papers"]
    assert tools[0].description == "Search paper metadata."
    assert tools[0].input_schema["properties"]["query"]["type"] == "string"


def test_register_mcp_manifest_tools_adds_approval_gated_placeholders(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path / "mcp-tools.json",
        {
            "mcpServers": {
                "docs": {
                    "tools": [
                        {
                            "name": "lookup",
                            "description": "Lookup docs.",
                            "inputSchema": {"type": "object"},
                        }
                    ]
                }
            }
        },
    )
    registry = ToolRegistry()

    registered = register_mcp_manifest_tools(registry, manifest)

    assert len(registered) == 1
    tool = registry.get("mcp__docs__lookup")
    assert tool.source == "mcp"
    assert tool.requires_approval is True
    assert "not executable yet" in run(registry.call("mcp__docs__lookup", {"query": "x"}))


def test_missing_mcp_manifest_raises_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(MCPManifestError, match="does not exist"):
        load_mcp_manifest_tools(tmp_path / "missing.json")


def test_agent_registry_loads_mcp_tools_only_when_enabled(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path / "mcp-tools.json",
        {"servers": [{"name": "research", "tools": [{"name": "search", "description": "Search."}]}]},
    )

    disabled = AppSettings.load(environ={"ML_COPILOT_WORKSPACE_ROOT": str(tmp_path)})
    enabled = AppSettings.load(
        environ={
            "ML_COPILOT_WORKSPACE_ROOT": str(tmp_path),
            "ML_COPILOT_ENABLE_MCP": "true",
            "ML_COPILOT_MCP_MANIFEST_PATH": str(manifest),
        }
    )

    assert _create_tool_registry(disabled).list_by_source("mcp") == []
    assert [tool.name for tool in _create_tool_registry(enabled).list_by_source("mcp")] == ["mcp__research__search"]


def test_agent_registry_keeps_local_tools_when_mcp_manifest_is_missing(tmp_path: Path) -> None:
    settings = AppSettings.load(
        environ={
            "ML_COPILOT_WORKSPACE_ROOT": str(tmp_path),
            "ML_COPILOT_ENABLE_MCP": "true",
            "ML_COPILOT_MCP_MANIFEST_PATH": str(tmp_path / "missing.json"),
        }
    )

    registry = _create_tool_registry(settings)

    assert registry.has("list_files")
    assert registry.list_by_source("mcp") == []


def test_mcp_tools_require_approval_even_when_global_approval_is_disabled(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path / "mcp-tools.json",
        {"servers": [{"name": "research", "tools": [{"name": "search", "description": "Search."}]}]},
    )
    settings = AppSettings.load(
        environ={
            "ML_COPILOT_WORKSPACE_ROOT": str(tmp_path),
            "ML_COPILOT_REQUIRE_TOOL_APPROVAL": "false",
            "ML_COPILOT_ENABLE_MCP": "true",
            "ML_COPILOT_MCP_MANIFEST_PATH": str(manifest),
        }
    )
    registry = _create_tool_registry(settings)

    assert registry.get("mcp__research__search").requires_approval is True
