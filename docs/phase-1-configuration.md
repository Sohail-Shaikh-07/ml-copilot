# Phase 1 Configuration

This document captures the configuration slice for `ML Copilot`.

## Task

`ML-3 / Add configuration and environment loading`

## Supported Settings

The current configuration layer supports:

- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `LLM_TIMEOUT_SECONDS`
- `ML_COPILOT_WORKSPACE_ROOT`
- `ML_COPILOT_DB_PATH`
- `ML_COPILOT_REQUIRE_TOOL_APPROVAL`
- `ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS`
- `ML_COPILOT_REDACT_SECRETS`
- `ML_COPILOT_ENV_FILE`

An example configuration file is included at `.env.example`.

## Precedence

Configuration is resolved in this order:

1. process environment variables
2. values loaded from a `.env` file
3. built-in defaults

Process environment wins over `.env` so local overrides remain predictable in
development, tests, and CI.

## Defaults

- `LLM_BASE_URL=https://api.openai.com/v1`
- `LLM_MODEL=gpt-5.4`
- `LLM_TIMEOUT_SECONDS=600`
- `ML_COPILOT_REQUIRE_TOOL_APPROVAL=true`
- `ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS=false`
- `ML_COPILOT_REDACT_SECRETS=true`
- default database path is `.ml-copilot/ml-copilot.db` under the workspace root

## Provider Strategy

For the MVP, `ML Copilot` should stay provider-agnostic through an
OpenAI-compatible interface:

- one internal request shape
- one `base_url`
- one `api_key`
- one `model`

That already covers a lot of real providers and gateways when they expose an
OpenAI-style API, including:

- OpenAI
- OpenRouter
- Groq
- DeepInfra
- local vLLM and similar gateways

Some providers may also offer OpenAI-compatible adapters depending on the
gateway or routing layer in front of them.

For providers with native APIs that are not cleanly OpenAI-compatible, the next
step should be an adapter layer rather than hardwiring provider logic all over
the app. A later design can introduce a dedicated provider field such as:

```text
LLM_PROVIDER=openai_compatible | anthropic | gemini
```

Then the runtime can route through small provider clients behind one internal
`LLMClient` interface.

That gives us a good path to support:

- Anthropic
- Google Gemini
- xAI Grok
- Minimax
- Kimi
- Z.ai

without breaking the simpler MVP contract.

## Notes

This slice keeps the configuration layer stdlib-only on purpose. We can add a
heavier settings framework later if the runtime grows enough to justify it, but
the current approach is easy to test and has no extra bootstrap dependency.
