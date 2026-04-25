# Phase 1 LLM Client

This document captures the LLM client slice for `ML Copilot`.

## Task

`ML-4 / Implement OpenAI-compatible LLM client`

## Scope

The current client is intentionally narrow and provider-neutral:

- OpenAI-style `/chat/completions`
- non-streaming response parsing
- streaming SSE parsing
- tool-call parsing for full responses and streamed deltas
- timeout handling through the configured HTTP client
- usage parsing when the provider returns token counts

## Why This Shape

The goal here is to stabilize one internal contract before the agent loop lands.
That gives later work a single client surface for:

- the agent runtime
- tests with mocked transports
- OpenAI-compatible providers and gateways
- future native provider adapters

## Deferred To Later Tasks

This task does not yet include:

- provider-specific SDK adapters
- retries and backoff policy
- cost accounting
- event emission into the session model
- context management integration

## Provider Strategy

The default path stays OpenAI-compatible-first. That keeps the initial client
small while covering several practical backends through configuration.

Later native adapters should sit behind the same internal interface rather than
leaking provider-specific conditionals across the codebase.
