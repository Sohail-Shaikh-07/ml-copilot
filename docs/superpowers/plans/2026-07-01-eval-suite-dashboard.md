# Eval Suite Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ML-407, a frontend eval suite dashboard and release-gating view from existing eval suite reports and persisted tool output.

**Architecture:** Keep this slice frontend-first. Add a pure parser that extracts eval suite report JSON from tool output/artifact previews, then render a focused dashboard panel in the inspector. Link report artifacts into the artifact browser rather than adding new backend file APIs.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing `ToolCallPayload` and artifact-browser infrastructure.

---

### Task 1: Eval dashboard extraction helper

**Files:**
- Create: `frontend/src/evalDashboard.ts`
- Test: `frontend/src/evalDashboard.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/evalDashboard.test.ts` with a test that calls `buildEvalDashboardSummary(toolCalls)` using a tool output containing fenced eval suite JSON:

```ts
expect(summary.gateStatus).toBe('blocked');
expect(summary.suites[0].status).toBe('failed');
expect(summary.suites[0].fixtures).toHaveLength(2);
expect(summary.suites[0].fixtures[1].changedFiles).toContain('src/train.py');
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- evalDashboard.test.ts` from `frontend/`.
Expected: FAIL because `./evalDashboard` does not exist.

- [ ] **Step 3: Implement minimal parser**

Create `evalDashboard.ts` with:

- `buildEvalDashboardSummary(toolCalls: ToolCallPayload[]): EvalDashboardSummary`
- suite JSON parsing from fenced code blocks and raw JSON-like output
- gate status values `healthy`, `blocked`, `unknown`
- fixture summaries with report/workspace/artifact paths, status, score, checks, and changed files where report data includes them
- scripted/live mode inference from fixture metadata or agent output mode

- [ ] **Step 4: Run focused helper test**

Run: `npm test -- evalDashboard.test.ts`.
Expected: PASS.

### Task 2: Dashboard panel UI

**Files:**
- Create: `frontend/src/components/EvalDashboardPanel.tsx`
- Test: `frontend/src/components/EvalDashboardPanel.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create a test that renders `EvalDashboardPanel` with failed and passing fixture data and expects:

- region name `Eval suite dashboard`
- release gate text `Release gate blocked`
- average score, runtime, token usage, pass/fail counts
- fixture rows with check-level failure and changed file details
- artifact-browser link

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- EvalDashboardPanel.test.tsx`.
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement panel**

Build a panel with:

- gate summary header
- suite cards
- fixture table/list
- check-level and changed-file details
- report artifact links to `#artifact-browser`
- empty state when no eval reports are present

- [ ] **Step 4: Run focused component test**

Run: `npm test -- EvalDashboardPanel.test.tsx`.
Expected: PASS.

### Task 3: Wire into workbench and artifact extraction

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/artifactBrowser.ts`
- Modify: `frontend/src/artifactBrowser.test.ts`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing artifact assertion**

Extend the artifact-browser test to expect `suite-report.json` and `suite-report.md` paths from eval suite output are listed.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- artifactBrowser.test.ts`.
Expected: FAIL if suite report labels are not extracted yet.

- [ ] **Step 3: Implement wiring**

- Import and render `EvalDashboardPanel` in the inspector stack near the artifact browser.
- Extend artifact extraction labels to include suite/eval report paths.
- Add `.eval-dashboard-*` styles.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm test -- evalDashboard.test.ts EvalDashboardPanel.test.tsx artifactBrowser.test.ts`.
Expected: PASS.

### Task 4: Full verification and publish

**Files:**
- All changed files.

- [ ] **Step 1: Run frontend validation**

Run from `frontend/`:

```bash
npm test
npm run build
```

- [ ] **Step 2: Run backend/regression validation**

Run from repo root:

```bash
python -m pytest tests/ -q
ruff check app/ tests/
ruff format --check app/ tests/
mypy app/ --ignore-missing-imports --follow-imports=skip
git diff --check
pre-commit run --all-files
```

- [ ] **Step 3: Commit and open PR**

Stage only ML-407 files plus this plan. Commit with `ML-407: Create eval suite dashboard`, push `feature/ML-407-eval-dashboard`, and open a PR whose body contains `Closes #116`.

- [ ] **Step 4: Verify PR metadata**

Run:

```bash
gh pr view <pr> --json assignees,labels,closingIssuesReferences
```

Expected: assignee `Sohail-Shaikh-07`, labels `feature` and `phase5`, closing issue `#116`.
