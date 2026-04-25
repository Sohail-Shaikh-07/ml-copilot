# Phase 1 Bootstrap

This document captures the first implementation slice for `ML Copilot`.

## Task

`ML-2 / Bootstrap Python project structure`

## What This Slice Establishes

- baseline Python package layout under `app/`
- dedicated `tests/` tree for unit and integration work
- `docs/` for phase-aware project documentation
- `scripts/` as a home for helper utilities
- `pyproject.toml` with `pytest` and `ruff` configuration
- a runnable `python -m app.main` bootstrap entrypoint

## Why This Structure

The repository starts small, but the layout already matches the planned shape of
the agent runtime:

- `app.agent` for loop, prompts, context, and approvals
- `app.tools` for safe tool handlers
- `app.storage` for durable persistence
- `app.api` for backend routes
- `app.evals` for ML-specific evaluation tasks

That gives us stable ownership boundaries before the codebase grows.

## Deferred To Later Tasks

This bootstrap intentionally avoids pulling too much future work forward.

The following stay in later tasks:

- environment-based configuration
- OpenAI-compatible LLM client
- SQLite schema and repository layer
- tool registry and read-only tools
- agent loop and orchestration
- persistent memory and approval workflows

## Notes On Product Direction

The long-term product direction includes:

- persistent sessions and memory
- orchestration through cooperating agents
- safe edit and command execution
- ML-aware repo and dataset workflows

Those remain part of the roadmap, but the base repo should be solid before we
layer that behavior in.
