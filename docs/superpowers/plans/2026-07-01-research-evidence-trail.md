# Research Evidence Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frontend research-step visualization that turns persisted research tool calls into an expandable evidence-backed timeline.

**Architecture:** Keep the slice frontend-first. Add pure parser helpers for paper/docs/Hub/dataset/repository/decision signals from `ToolCallPayload`, then render those steps in an inspector panel and link research tool cards into it.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, existing persisted session tool-call payloads.

---

### Task 1: Research trail parser

**Files:**
- Create: `frontend/src/researchTrail.test.ts`
- Create: `frontend/src/researchTrail.ts`

- [ ] **Step 1: Write the failing parser test**

Create a test that feeds `paper_details`, `extract_training_recipe`, `search_hub`, `inspect_dataset`, and `analyze_repository` calls. Assert that `buildResearchTrailSummary` returns five steps, groups them into paper/recipe/model/dataset/repository kinds, extracts evidence snippets, source links, recipe confidence/limitations, and reports a decision count.

- [ ] **Step 2: Verify RED**

Run `cd frontend && npm test -- researchTrail.test.ts`.

Expected: FAIL because `researchTrail.ts` does not exist.

- [ ] **Step 3: Implement minimal parser**

Create `researchTrail.ts` with typed `ResearchStep`, `ResearchEvidence`, `ResearchTrailSummary`, helpers for coercion/bounded snippets/links, and parsers for known research tools.

- [ ] **Step 4: Verify GREEN**

Run `cd frontend && npm test -- researchTrail.test.ts`.

Expected: PASS.

### Task 2: Research trail panel

**Files:**
- Create: `frontend/src/components/ResearchTrailPanel.test.tsx`
- Create: `frontend/src/components/ResearchTrailPanel.tsx`

- [ ] **Step 1: Write the failing component test**

Render `<ResearchTrailPanel toolCalls={calls} />` and assert the region name, timeline title, paper title/arxiv id, evidence quote, recipe confidence/limitation text, Hub candidate, dataset, repository, and expand/collapse behavior.

- [ ] **Step 2: Verify RED**

Run `cd frontend && npm test -- ResearchTrailPanel.test.tsx`.

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement minimal panel**

Create a panel that shows summary chips, ordered timeline cards, expandable detail sections, evidence snippets, source links, and recipe/decision labels.

- [ ] **Step 4: Verify GREEN**

Run `cd frontend && npm test -- ResearchTrailPanel.test.tsx`.

Expected: PASS.

### Task 3: Wire panel and trace links

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ToolTracePanel.tsx`
- Modify: `frontend/src/components/ToolTracePanel.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing trace-link test**

Update `ToolTracePanel.test.tsx` so a research-related card exposes `Open research trail` with `href="#research-trail"`.

- [ ] **Step 2: Verify RED**

Run `cd frontend && npm test -- ToolTracePanel.test.tsx`.

Expected: FAIL because the link is not wired.

- [ ] **Step 3: Implement wiring and styles**

Render `ResearchTrailPanel` in the inspector, add a research-trail link helper in `ToolTracePanel.tsx`, and add focused timeline/evidence styles.

- [ ] **Step 4: Verify GREEN**

Run `cd frontend && npm test -- researchTrail.test.ts ResearchTrailPanel.test.tsx ToolTracePanel.test.tsx`.

Expected: PASS.

### Task 4: Full validation and PR

Run full frontend/backend validation, commit only scoped files, push `feature/ML-409-research-evidence-trail`, and open PR title `ML-409 / Visualize research steps and evidence trail` with the established `## Summary`, `Closes #120`, and `## Validation` sections.
