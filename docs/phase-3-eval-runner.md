# Phase 3 Eval Runner

This document captures the first evaluation-runner slice for `ML Copilot`.

## Task

`ML-200 / Build eval runner`

## Scope

The runner executes JSON task fixtures with:

- a clean workspace rendered from fixture files
- one agent turn against the fixture prompt
- deterministic scoring checks
- persisted `eval_runs` records
- JSON and Markdown artifacts for each run

## Fixture Shape

```json
{
  "id": "repo-summary-basic",
  "name": "Repo summary basic",
  "prompt": "Summarize the repository and write summary.md.",
  "workspace_files": [
    {
      "path": "README.md",
      "content": "# Sample project\n"
    }
  ],
  "checks": [
    {
      "type": "contains",
      "value": "summary"
    },
    {
      "type": "file_exists",
      "path": "summary.md"
    },
    {
      "type": "file_contains",
      "path": "summary.md",
      "value": "Sample project"
    }
  ]
}
```

Supported check types:

- `contains`: final agent response includes `value`
- `not_contains`: final agent response omits `value`
- `file_exists`: a workspace file exists at `path`
- `file_contains`: a workspace file at `path` includes `value`

## CLI

Run an eval fixture:

```bash
python -m app.main eval path/to/fixture.json
```

Use a custom artifact directory:

```bash
python -m app.main eval path/to/fixture.json --output-dir .ml-copilot/evals
```

Print the persisted report JSON:

```bash
python -m app.main eval path/to/fixture.json --json
```

The command exits with `0` when all checks pass and `1` when the eval fails or errors.

## Artifacts

Each run writes:

- `workspaces/<fixture-id>/<eval-run-id>/` for the reproducible fixture workspace
- `artifacts/<eval-run-id>/report.json` for machine-readable results
- `artifacts/<eval-run-id>/report.md` for reviewer-friendly results

The same report payload is persisted in SQLite under `eval_runs.report_json`.
