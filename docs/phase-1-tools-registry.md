# Phase 1: Tool Registry

`ML-8` adds the minimal tool abstraction that later agent work will build on.

## Scope

- define a shared `ToolSpec` model for tool metadata and handlers
- export tool metadata in OpenAI-compatible function format
- register tools by name in a central in-memory registry
- dispatch tool handlers asynchronously with clear duplicate and unknown-tool errors

## Why this shape

The registry stays intentionally small in Phase 1.

We only need enough structure to:

- expose tool definitions to the LLM client
- route tool calls by name
- keep later tool tasks consistent

This avoids pulling orchestration, approvals, or provider-specific behavior into the base tool layer too early.
