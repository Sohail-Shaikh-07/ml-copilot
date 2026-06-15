# Phase 2: Issue and PR Workflow

`ML-112` captures the handoff pattern for tasks after the user has certified them.

## When To Start

- Start the GitHub handoff only after the task is implemented and validated.
- Use the task ID and task title exactly as they appear in Notion.
- Keep the branch focused on a single task.

## GitHub Issue

- Title: `ML-### / short task title`
- Body sections: `Goal`, `Context`, `Scope`, `Acceptance Criteria`, `Notion`
- Assignee: the active owner doing the work
- Labels: match the task type and keep them consistent with the PR

## Pull Request

- Title: match the issue title
- Body sections: `Summary`, `Testing`, `Notes`, `Reference`
- Assignee: the active owner
- Labels: match the issue labels exactly
- Use a concise human tone, like a teammate handoff instead of a generated log

## Review

- Write review feedback as `Code review`
- If review feedback points to a fix, apply the fix, commit it, and push again on the same PR
- Keep review comments specific to the code change or workflow gap

## Notion Handoff

- Update the task to `Completed` only after implementation, validation, PR creation, and user certification
- Record the merged PR and closed issue in the Notes field
