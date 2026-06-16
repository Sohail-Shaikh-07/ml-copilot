# Phase 3 MCP Support Follow-Up

`ML-211` adds an incremental MCP support contract for `ML Copilot`.

## Scope

This release does not open live MCP transports. Instead, it adds:

- configuration flags for optional MCP-style discovery
- a local JSON manifest format for discovered tool descriptors
- namespaced registration as `mcp__<server>__<tool>`
- approval-gated placeholder execution for discovered tools
- tests around manifest parsing, registration, filtering, and safety behavior

This keeps the core local tool system stable while creating a clear seam for future live MCP clients.

## Manifest

Set these environment variables:

```bash
ML_COPILOT_ENABLE_MCP=true
ML_COPILOT_MCP_MANIFEST_PATH=.ml-copilot/mcp-tools.json
```

Example manifest:

```json
{
  "servers": [
    {
      "name": "research",
      "tools": [
        {
          "name": "search_papers",
          "description": "Search paper metadata.",
          "input_schema": {
            "type": "object",
            "properties": {
              "query": {"type": "string"}
            },
            "required": ["query"]
          }
        }
      ]
    }
  ]
}
```

The loader also accepts an `mcpServers` object with per-server `tools` arrays.

## Safety

MCP-style tools are disabled by default. When loaded, they:

- are skipped if server or tool names are unsafe
- are skipped if they use blocked built-in or high-risk tool names
- are registered under a namespaced name
- are marked with source `mcp`
- require approval before execution
- return a safe placeholder until a live transport is implemented

This mirrors the product safety model: external capabilities should be discoverable and reviewable before they become executable.
