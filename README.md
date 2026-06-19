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

The current release candidate is intentionally narrow:

- Python backend and agent runtime
- SQLite persistence
- CLI for chat and repo workflows
- FastAPI API with streaming events
- React + Vite frontend shell for sessions, approvals, and tool traces
- fixture-based eval runner with persisted scoring reports
- Docker image for local deployment review
- a small set of trustworthy tools
- ML-specific helpers for repository, dataset, docs, paper, and reporting workflows
- optional MCP-style tool discovery from a local manifest, disabled by default

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
- release packaging and documentation hardening

## Repo Boundaries

This repository is only for the actual `ML Copilot` product.

Planning notes, local reference material, and personal workflow documents should stay outside this repository. That keeps the public Git history focused on product code, tests, docs, and release artifacts.

## Workflow Notes

- [Issue and PR workflow guidance](docs/phase-2-issue-pr-workflow.md)
- [Release readiness guide](docs/release-readiness.md)
- [Eval runner guide](docs/phase-3-eval-runner.md)
- [MCP support guide](docs/phase-3-mcp-support.md)
- Keep GitHub issue and PR titles aligned with the task ID and task name.
- Keep issue labels, PR labels, and assignees in sync for each certified task.

## Setup

ML Copilot targets Python 3.12 and Node.js 22 for the bundled frontend.

Install the backend in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Install frontend dependencies:

```bash
cd frontend
npm ci
```

Create a runtime environment file from the example:

```bash
cp .env.example .env
```

Set at least `LLM_API_KEY` and, when needed, adjust `LLM_BASE_URL`, `LLM_MODEL`, `ML_COPILOT_DB_PATH`, and the safety flags. If you will use Hugging Face-backed tools without a per-session token, set `HF_TOKEN` as a local fallback.

## Run Locally

Print the resolved backend configuration with secrets redacted:

```bash
python -m app.main --print-config
```

Run a CLI task:

```bash
python -m app.main run "Analyze this repository and summarize the ML components."
```

Start the API:

```bash
python -m uvicorn app.api:create_app --factory --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
npm run dev
```

The development frontend proxies `/api` to `http://127.0.0.1:8000`.

## Validate

Run the main local checks before opening a PR:

```bash
python -m pytest -q
python -m ruff check app/ tests/
python -m ruff format --check app/ tests/
python -m mypy app/ --ignore-missing-imports --follow-imports=skip
cd frontend && npm run build
```

Run a bundled eval fixture:

```bash
python -m app.main eval tests/fixtures/evals/ml-201-repo-analysis.json
```

## Deployment Image

The repository includes a production-oriented Dockerfile that builds the React frontend, installs the Python backend package, and serves both from the FastAPI runtime.

Build the image:

```bash
docker build -t ml-copilot .
```

Run the API and bundled frontend:

```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v ml-copilot-data:/data \
  ml-copilot
```

The image listens on port `8000`, stores the default SQLite database at `/data/ml-copilot.db`, and expects secrets such as `LLM_API_KEY` to be provided at runtime through environment variables or `--env-file`. The Docker build intentionally ignores local `.env` files, virtual environments, frontend build output, and `.ml-copilot` runtime data.

## Safety Model

ML Copilot is designed for inspectable local automation, not silent autonomous control:

- tool calls are validated before execution
- risky workspace actions can require explicit approval
- destructive commands are disabled by default
- secrets are redacted in user-facing configuration output
- MCP-style tools are disabled by default and approval-gated when explicitly loaded
- session history, tool calls, approvals, events, and usage metrics are persisted for review

See [release readiness](docs/release-readiness.md) for the current limitations and release checklist.

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

Phase 3 has backend, CLI, API, frontend, eval, observability, and Docker foundations in place for release review. Full autonomous research-and-training behavior remains future work.
