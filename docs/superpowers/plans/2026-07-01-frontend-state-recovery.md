# Frontend State Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen the frontend session state and recovery path so Phase 5 workbench panels can replay persisted session state and surface stream health without fragile ad hoc updates.

**Architecture:** Add a pure `workbenchState` helper module for session list merges, live event replay/deduplication, recovery snapshots, and connection-health derivation. Add a small `SessionRecoveryPanel` that consumes those typed helpers, then wire App to use the helpers while keeping existing panel props stable.

**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library.

---

### Task 1: Typed workbench state helpers

**Files:**
- Create: `frontend/src/workbenchState.ts`
- Test: `frontend/src/workbenchState.test.ts`

- [ ] **Step 1: Write failing tests**

Create tests for:
- merging session summaries by id without duplicating sessions;
- replaying live events with id/sequence dedupe, bounded history, assistant chunk delta extraction, and terminal event detection;
- building a recovery snapshot from active session, transcript, tool calls, and live events;
- deriving stale/reconnecting/live/offline stream health.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `npm test -- workbenchState.test.ts`

Expected: fail because `./workbenchState` does not exist yet.

- [ ] **Step 3: Implement minimal helpers**

Create the module with exported pure functions:
- `mergeSessionSummaries`
- `replaySessionEvents`
- `buildRecoverySnapshot`
- `deriveConnectionHealth`

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `npm test -- workbenchState.test.ts`

Expected: pass.

### Task 2: User-visible recovery panel

**Files:**
- Create: `frontend/src/components/SessionRecoveryPanel.tsx`
- Test: `frontend/src/components/SessionRecoveryPanel.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing component test**

Test that the panel renders stream status, recovery snapshot counts, last event sequence, replay details, and a reconnect button when recovery is available.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `npm test -- SessionRecoveryPanel.test.tsx`

Expected: fail because `./SessionRecoveryPanel` does not exist yet.

- [ ] **Step 3: Implement minimal component and styles**

Render compact, product-grade session recovery visibility without changing backend contracts.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `npm test -- SessionRecoveryPanel.test.tsx`

Expected: pass.

### Task 3: Wire App to typed state helpers

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/types.ts` if shared string unions are needed

- [ ] **Step 1: Replace ad hoc event append logic**

Use `replaySessionEvents` inside the EventSource handler to cap and dedupe live event history, update the last event sequence, and append assistant chunks from the replay result.

- [ ] **Step 2: Replace ad hoc session list updates**

Use `mergeSessionSummaries` after session create, chat response, and approval response.

- [ ] **Step 3: Add recovery panel and reconnect affordance**

Use `buildRecoverySnapshot` and `deriveConnectionHealth` from App state, render `SessionRecoveryPanel`, and expose a safe reconnect button that calls the existing EventSource flow with replay enabled.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm test -- workbenchState.test.ts SessionRecoveryPanel.test.tsx`

Expected: pass.

### Task 4: Full validation and publish

**Files:**
- Modify: `ML-COPILOT-WORKFLOW.md` outside the repo only after PR is ready.

- [ ] **Step 1: Run validation**

Run frontend tests/build, backend tests/type/lint checks, pre-commit, audit, and `git diff --check`.

- [ ] **Step 2: Commit and push only scoped files**

Stage only ML-410 files and open PR with the requested PR template:
`Summary`, `Testing`, `Notes`, `Referrence`, `Close #122`.

- [ ] **Step 3: Verify GitHub metadata**

Confirm labels `feature`/`phase5`, assignee `Sohail-Shaikh-07`, and issue closing reference.

- [ ] **Step 4: Update Notion and local workflow**

Update ML-410 to review state and keep `ML-COPILOT-WORKFLOW.md` local-only.
