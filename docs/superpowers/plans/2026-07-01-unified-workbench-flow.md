# Unified Workbench Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guided workbench overview that turns separate Phase 5 panels into one coherent autonomous ML workflow narrative.

**Architecture:** Add pure `workbenchFlow` helpers that derive stage progress from existing session, message, tool-call, metrics, and recovery data. Add a `WorkbenchFlowPanel` that renders setup, data, research, runtime, monitoring, artifacts, evals, report, and publishing stages with jump links into existing panels plus an end-to-end walkthrough. Wire it into App without backend changes.

**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library.

---

### Task 1: Flow summary helper

**Files:**
- Create: `frontend/src/workbenchFlow.ts`
- Test: `frontend/src/workbenchFlow.test.ts`

- [ ] **Step 1: Write failing tests**

Create tests for stage derivation from existing session/tool-call/recovery state: setup, data, research, runtime, monitor, artifacts, evals, and publishing.

- [ ] **Step 2: Run focused helper test and verify RED**

Run: `npm test -- workbenchFlow.test.ts`

Expected: fail because `./workbenchFlow` does not exist.

- [ ] **Step 3: Implement minimal helper**

Create `buildWorkbenchFlowSummary` and exported stage types.

- [ ] **Step 4: Run focused helper test and verify GREEN**

Run: `npm test -- workbenchFlow.test.ts`

Expected: pass.

### Task 2: Guided workbench component

**Files:**
- Create: `frontend/src/components/WorkbenchFlowPanel.tsx`
- Test: `frontend/src/components/WorkbenchFlowPanel.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing component test**

Render the panel with Phase 5 fixture data and assert the workflow guide, resume state, stage links, and end-to-end walkthrough appear.

- [ ] **Step 2: Run focused component test and verify RED**

Run: `npm test -- WorkbenchFlowPanel.test.tsx`

Expected: fail because `./WorkbenchFlowPanel` does not exist.

- [ ] **Step 3: Implement component and styles**

Render user-visible progress cards and walkthrough copy.

- [ ] **Step 4: Run focused component test and verify GREEN**

Run: `npm test -- WorkbenchFlowPanel.test.tsx`

Expected: pass.

### Task 3: App wiring and anchors

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: existing panel components only if a stable anchor id is missing.

- [ ] **Step 1: Wire WorkbenchFlowPanel into inspector**

Pass active session, messages, tool calls, and recovery snapshot into the panel.

- [ ] **Step 2: Add missing stable anchor ids**

Ensure the workflow guide can link to model controls, jobs, usage, runtime, artifacts, research, evals, publishing, and tool trace panels.

- [ ] **Step 3: Run focused tests**

Run: `npm test -- workbenchFlow.test.ts WorkbenchFlowPanel.test.tsx`

Expected: pass.

### Task 4: Full validation and publish

**Files:**
- Create: `docs/superpowers/plans/2026-07-01-unified-workbench-flow.md`

- [ ] **Step 1: Run validation**

Run frontend tests/build, backend pytest/type/lint checks, pre-commit, audit, and whitespace check.

- [ ] **Step 2: Commit and push scoped files**

Stage only ML-412 files. Do not stage `.kiro/`, `ml_copilot.egg-info/`, or local workflow changes.

- [ ] **Step 3: Open PR with public template**

Use sections: `Summary`, `Testing`, `Notes`, `Referrence`, `Close #126`. Do not mention Notion or internal tracker URLs.
