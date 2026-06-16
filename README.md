# ML Copilot

`ML Copilot` is a focused ML engineering agent for real repository work.

It is designed to inspect codebases, read docs and papers, propose safe changes, run approved commands, analyze datasets, debug failures, and leave behind a clear final report with artifacts and next steps.

The goal is not to be the biggest agent platform. The goal is to be reliable, inspectable, and useful for day-to-day ML engineering.

## Why This Exists

Most agent demos can talk about ML code. Fewer can work through an actual ML engineering loop with persistence, safety, approvals, reproducibility, and evals.

`ML Copilot` is built to close that gap with a smaller, sharper MVP:

- OpenAI-compatible model interface
- durable sessions and event history
- safe file and command tools
- approval flow for risky actions
- ML-aware repo and dataset analysis
- evals that measure whether the agent is actually useful

## Product Shape

The first version is intentionally narrow:

- Python backend and agent runtime
- SQLite persistence
- CLI for chat and repo workflows
- FastAPI API with streaming events
- a small set of trustworthy tools
- ML-specific helpers added only after the core loop is stable

## Architecture

```text
+-------------------+        +--------------------+
| User              |        | Local Workspace    |
| CLI / API Client  |        | code, tests, data  |
+---------+---------+        +----------+---------+
          |                             ^
          v                             |
+---------+---------------------------------------+
|                 ML Copilot Backend              |
|                                                 |
|  +----------------+    +--------------------+   |
|  | Session API    |    | SSE Event Stream   |   |
|  +--------+-------+    +----------+---------+   |
|           |                         ^            |
|           v                         |            |
|  +--------+----------------------------------+  |
|  | Agent Loop                               |  |
|  | - builds context                         |  |
|  | - calls model                            |  |
|  | - validates tool calls                   |  |
|  | - pauses on approvals                    |  |
|  | - records messages and events            |  |
|  +--------+----------------+----------------+  |
|           |                |                   |
|           v                v                   |
|  +--------+-----+   +------+---------------+   |
|  | LLM Client   |   | Tool Registry        |   |
|  | OpenAI-style |   | fs | git | shell     |   |
|  +--------+-----+   | datasets | docs      |   |
|           |         +------+---------------+   |
|           v                |                   |
|  +--------+----------------+---------------+   |
|  | Persistence                             |   |
|  | sessions | messages | events | approvals|   |
|  +-----------------------------------------+   |
+------------------------------------------------+
```

## High-Level Flow

```text
User request
   ||
   vv
Create or resume session
   ||
   vv
Build context + tool schema
   ||
   vv
Call OpenAI-compatible model
   ||
   vv
Assistant responds
   ||
   +--> text only ----------------------------+
   ||                                         |
   +--> tool calls --> validate --> safe? ----+
                         ||           ||
                         ||           ++ yes -> run tool -> store result
                         ||
                         ++ no  -> ask for approval -> run or reject
                                                   ||
                                                   vv
                                           continue loop
                                                   ||
                                                   vv
                                     final answer + event history
```

## Core Principles

- Read before editing
- keep changes scoped
- require approval for risky actions
- persist useful history
- design for evals, not demos
- stay provider-agnostic through an OpenAI-compatible interface

## Initial Roadmap

### Phase 1

- project bootstrap
- LLM client
- SQLite persistence
- read-only repo tools
- basic agent loop
- CLI repo analysis

### Phase 2

- approval flow
- safe patch tool
- safe command tool
- FastAPI backend
- SSE replay
- interrupt handling

### Phase 3

- ML dataset inspection
- docs and paper helpers
- eval runner
- React + Vite frontend shell for chat, approvals, and tool traces

## Repo Boundaries

This repository is only for the actual `ML Copilot` product.

Planning notes and local reference material live outside this repo in the parent workspace, including:

- project planning documents
- Notion and issue workflow notes
- `.codex-reference/ml-intern`

That keeps the Git repository clean while still letting AI tooling use the surrounding workspace for context.

## Workflow Notes

- [Issue and PR workflow guidance](docs/phase-2-issue-pr-workflow.md)
- Keep GitHub issue and PR titles aligned with the task ID and task name.
- Keep issue labels, PR labels, and assignees in sync for each certified task.

## Planned Stack

- Python 3.12
- FastAPI
- Pydantic
- SQLite
- `httpx`
- `uv`
- `pytest`
- `ruff`
- React + TypeScript later, after backend contracts stabilize

## Success Criteria For MVP

The MVP is successful when a user can:

1. start a session
2. ask for ML repo analysis
3. let the agent inspect files and context
4. approve code edits or commands when needed
5. rerun checks
6. receive a trustworthy final report
7. reopen the session and inspect the history

## Status

Scaffolding the public repository and defining the architecture baseline.
