# Phase 6 Autonomous Workflow Planner

ML-500 adds `plan_autonomous_workflow`, a deterministic planning tool that helps the agent turn a user objective into a safe, inspectable ML workflow before long-running jobs begin.

The planner currently supports these templates:

- `tabular_classification`
- `text_classification`
- `image_classification`
- `custom_experiment`
- `auto`, which selects one of the templates from the objective text

Each plan includes:

- readiness checks for required inputs and credentials
- recommended ML Copilot tools for each stage
- expected artifacts
- key risks to resolve before release or publishing
- run constraints such as remote-job availability, maximum spend, or maximum runtime

The planner is intentionally dry-run friendly. It does not call external services, upload files, launch jobs, or persist secrets.

Example:

```json
{
  "objective": "Fine tune a sentiment classifier for support tickets.",
  "template": "text_classification",
  "available_inputs": {
    "dataset": "data/support_tickets.csv",
    "text_column": "ticket_text",
    "label_column": "sentiment",
    "target_metric": "f1 >= 0.85",
    "provider_api_key": true,
    "hf_token": false
  },
  "constraints": {
    "allow_remote_jobs": false,
    "max_cost_usd": 5
  }
}
```
