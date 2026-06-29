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

Run every fixture in a directory as a suite:

```bash
python -m app.main eval tests/fixtures/evals
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
For directory suite runs, the command exits with `0` only when every fixture passes.

## Artifacts

Each run writes:

- `workspaces/<fixture-id>/<eval-run-id>/` for the reproducible fixture workspace
- `artifacts/<eval-run-id>/report.json` for machine-readable results
- `artifacts/<eval-run-id>/report.md` for reviewer-friendly results
- `suites/<suite-id>/suite-report.json` for aggregate directory runs
- `suites/<suite-id>/suite-report.md` for reviewer-friendly aggregate directory runs

The same report payload is persisted in SQLite under `eval_runs.report_json`.

## Scoring Report Format

Each report includes a `scoring` object with stable fields for downstream
automation:

- `task_success`: whether all configured checks passed
- `tests_passed` and `tests_total`: check pass count and total check count
- `files_changed`: flattened list of created, modified, or deleted workspace files
- `file_changes`: created, modified, and deleted file lists
- `safety_events`: approval, error, interruption, and approval-tool-call summary
- `token_usage`: prompt, completion, and total token counts when available
- `runtime`: start time, finish time, and elapsed seconds

The Markdown report mirrors the same information with dedicated sections for
changed files, safety events, and check results.

## Suite Report Format

Directory runs reuse the same fixture runner for each task and then write one
aggregate report with:

- overall suite status: `passed`, `failed`, or `error`
- fixture counts for passed, failed, and errored tasks
- average score across fixtures
- total runtime and token count
- per-fixture eval run IDs, status, score, workspaces, and report paths

## Bundled Fixtures

The first seeded eval fixtures live under `tests/fixtures/evals/`:

- `ml-201-training-script-fix.json`
- `ml-201-dataset-validation.json`
- `ml-201-eval-script.json`
- `ml-201-model-card-inference.json`
- `ml-201-repo-analysis.json`
