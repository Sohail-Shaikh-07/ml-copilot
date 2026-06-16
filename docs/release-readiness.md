# Release Readiness

This guide captures the current release-hardening posture for `ML Copilot`.

## Current Release Shape

The release candidate includes:

- Python 3.12 backend and CLI
- FastAPI session API with SSE event streaming
- SQLite persistence for sessions, messages, events, approvals, tool calls, eval runs, and usage metrics
- approval-aware agent loop with OpenAI-compatible model calls
- repository, workspace, dataset, docs, papers, and reporting tools
- React + Vite frontend shell for chat, sessions, approvals, tool traces, and metrics
- fixture-based eval runner with JSON and Markdown reports
- Dockerfile that builds the frontend and serves it from the backend runtime

## Runtime Configuration

Use `.env.example` as the source of truth for supported environment variables.

Required for real model calls:

- `LLM_PROVIDER`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

Important runtime paths and safety flags:

- `ML_COPILOT_WORKSPACE_ROOT`
- `ML_COPILOT_DB_PATH`
- `ML_COPILOT_REQUIRE_TOOL_APPROVAL`
- `ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS`
- `ML_COPILOT_REDACT_SECRETS`
- `ML_COPILOT_ENABLE_MCP`
- `ML_COPILOT_MCP_MANIFEST_PATH`

Confirm the resolved configuration without printing secrets:

```bash
python -m app.main --print-config
```

## Local Release Checks

Run these before tagging or merging release-facing changes:

```bash
python -m pytest -q
python -m ruff check app/ tests/
python -m ruff format --check app/ tests/
python -m mypy app/ --ignore-missing-imports --follow-imports=skip
python -m pre_commit run --all-files
```

Build the frontend:

```bash
cd frontend
npm ci
npm run build
```

Run at least one bundled eval fixture:

```bash
python -m app.main eval tests/fixtures/evals/ml-201-repo-analysis.json
```

If Docker is available, verify the deployment image:

```bash
docker build -t ml-copilot .
docker run --rm -p 8000:8000 --env-file .env -v ml-copilot-data:/data ml-copilot
```

## Safety Expectations

The current safety model is intentionally conservative:

- destructive command execution is disabled by default
- risky tool calls can pause for approval
- approval decisions and edited arguments are persisted
- tool call arguments and outputs are recorded for review
- configuration output redacts secrets
- MCP-style tools are disabled by default and are approval-gated when loaded from a manifest
- local `.env`, `.ml-copilot`, virtualenvs, and frontend build artifacts are excluded from Docker build context

Keep `ML_COPILOT_REQUIRE_TOOL_APPROVAL=true` for normal use. Only set `ML_COPILOT_ALLOW_DESTRUCTIVE_COMMANDS=true` in a disposable workspace where destructive file or shell operations are expected.

## Optional MCP Discovery

MCP support is currently a discovery contract, not live remote execution. Set `ML_COPILOT_ENABLE_MCP=true` and point `ML_COPILOT_MCP_MANIFEST_PATH` at a local JSON manifest to expose MCP-style tool descriptors to the agent. Discovered tools are namespaced as `mcp__<server>__<tool>`, marked with source `mcp`, and require approval before execution.

Supported manifest shape:

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

In this release, MCP tool execution returns a safe placeholder message. A future transport layer can replace that handler without changing the registry shape.

## Eval Guidance

Eval fixtures live in `tests/fixtures/evals/` and are designed to exercise practical ML-engineering tasks such as repository analysis, training-script repair, dataset validation, eval-script updates, and model-card inference.

Each eval run writes:

- a reproducible workspace under `.ml-copilot/evals/workspaces/`
- a JSON report under `.ml-copilot/evals/artifacts/`
- a Markdown reviewer report under `.ml-copilot/evals/artifacts/`
- a persisted `eval_runs` record in SQLite

Use `docs/phase-3-eval-runner.md` for the fixture schema and scoring fields.

## Known Limitations

This release does not yet provide fully autonomous ML research, training, and deployment. In particular:

- paper discovery and citation-graph planning are helper-level capabilities, not an end-to-end autonomous research planner
- dataset selection is assisted by tools and prompts, not a guaranteed automatic benchmark chooser
- training-loop diagnosis is not yet a closed-loop experiment optimizer
- Docker packaging is local-deployment oriented and does not include hosted infrastructure manifests
- the frontend is a focused operator shell, not a full product onboarding flow
- SQLite persistence is appropriate for local and MVP use, not multi-tenant production service operation

These limits should be treated as explicit product boundaries for Phase 3 and inputs into future Phase 4 work.

## Release Handoff Checklist

- Issue and PR titles match the task ID and task name
- Issue labels and PR labels match exactly
- PR is assigned to the active owner
- CI checks pass
- A code-review comment is posted on the PR
- Actionable review findings are fixed on the same branch
- Notion notes include the merged PR and closed issue after user certification
