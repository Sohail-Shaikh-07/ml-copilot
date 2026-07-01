# Autonomous Workflow Template Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic autonomous workflow template and preflight planner so the agent can turn a user ML objective into a safe, inspectable run plan before long jobs begin.

**Architecture:** Add a focused backend tool module that owns workflow template definitions and readiness rendering. Wire the tool into the existing `AgentLoop` tool registry using the same pattern as publishing, jobs, experiments, and repository analysis tools. Cover the contract with unit tests before implementation.

**Tech Stack:** Python, pytest, existing `ToolRegistry`, existing `AppSettings` test helpers.

---

### Task 1: Planner contract tests

**Files:**
- Create: `tests/unit/test_workflow_templates.py`

- [x] **Step 1: Write the failing tests**

Define tests that import `app.tools.workflow_templates`, assert the `plan_autonomous_workflow` schema, exercise a deterministic text-classification plan, check auto-selection for a tabular churn objective, reject an unknown template, and verify registry inclusion.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_workflow_templates.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools.workflow_templates'`.

### Task 2: Planner implementation

**Files:**
- Create: `app/tools/workflow_templates.py`
- Modify: `app/agent/loop.py`

- [x] **Step 1: Add template definitions**

Create `WorkflowTemplate` records for `tabular_classification`, `text_classification`, `image_classification`, and `custom_experiment`, each with required inputs, stages, recommended tools, expected artifacts, and risks.

- [x] **Step 2: Add tool spec and handler**

Expose `plan_autonomous_workflow` with `objective`, `template`, `available_inputs`, and `constraints`. Return deterministic Markdown with readiness, stages, expected artifacts, and key risks.

- [x] **Step 3: Wire registry**

Import `workflow_templates` in `_create_tool_registry`, register its spec, and add `_make_workflow_template_handler`.

- [x] **Step 4: Run focused tests**

Run: `python -m pytest tests/unit/test_workflow_templates.py -q`

Expected: PASS with `5 passed`.

### Task 3: Validation and PR

**Files:**
- Modify as needed based on validation.

- [x] **Step 1: Run backend validation**

Run focused tests, full backend tests, Ruff check/format, mypy, pre-commit, and diff whitespace checks.

- [ ] **Step 2: Commit and push**

Stage only ML-500 files, commit with `feat: add autonomous workflow planner`, and push `feature/ML-500-workflow-template-planner`.

- [ ] **Step 3: Open PR**

Use the requested public PR template with `Summary`, `Testing`, `Notes`, `Referrence`, and `Close #128`. Do not mention internal tracker URLs.
