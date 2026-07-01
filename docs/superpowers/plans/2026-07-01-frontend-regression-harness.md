# Frontend Regression Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add frontend regression coverage that composes Phase 5 workbench panels around a shared realistic session fixture.

**Architecture:** Create test-only fixture helpers that generate a complete session, message transcript, live events, recovery state, and tool-call outputs covering jobs, runtime, publishing, research, evals, artifacts, usage, provider controls, and trace-card anchors. Add one integration-style regression test that renders the panels together and asserts user-visible surfaces and cross-panel links.

**Tech Stack:** React, TypeScript, Vitest, Testing Library.

---

### Task 1: Shared frontend workbench fixture helpers

**Files:**
- Create: `frontend/src/testUtils/workbenchFixtures.tsx`
- Test: `frontend/src/components/WorkbenchRegressionHarness.test.tsx`

- [ ] **Step 1: Write failing harness test**

Create a component test that imports `renderPhase5WorkbenchHarness` from `../testUtils/workbenchFixtures`, renders the harness, and asserts visible sections for provider controls, rich messages, job progress, recovery, usage, runtime, publishing, research, eval, artifact browser, and trace cards.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `npm test -- WorkbenchRegressionHarness.test.tsx`

Expected: fail because `../testUtils/workbenchFixtures` does not exist.

- [ ] **Step 3: Implement fixture helper**

Create shared `phase5WorkbenchFixture()` and `renderPhase5WorkbenchHarness()` helpers. The harness should compose existing production components without modifying production code.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `npm test -- WorkbenchRegressionHarness.test.tsx`

Expected: pass.

### Task 2: Full validation and publish

**Files:**
- Create: `frontend/src/testUtils/workbenchFixtures.tsx`
- Create: `frontend/src/components/WorkbenchRegressionHarness.test.tsx`
- Create: `docs/superpowers/plans/2026-07-01-frontend-regression-harness.md`

- [ ] **Step 1: Run validation**

Run frontend test/build, backend pytest/type/lint checks, pre-commit, audit, and whitespace check.

- [ ] **Step 2: Commit and push only scoped files**

Stage only ML-411 files. Do not stage `.kiro/`, `ml_copilot.egg-info/`, or the local workflow file.

- [ ] **Step 3: Open PR with public template**

Use sections: `Summary`, `Testing`, `Notes`, `Referrence`, `Close #124`. Do not mention Notion or internal tracker URLs.

- [ ] **Step 4: Verify GitHub metadata**

Confirm labels `feature`/`phase5`, assignee `Sohail-Shaikh-07`, and GitHub closing issue reference.
