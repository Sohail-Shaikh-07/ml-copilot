# File and Artifact Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ML-406, a safe frontend file/artifact browser that surfaces generated files, provenance, and bounded previews from persisted session tool calls.

**Architecture:** Keep this slice frontend-first. Add a pure artifact extraction module that derives safe file-like records from existing `ToolCallPayload` data, a focused `ArtifactBrowserPanel` component for browsing and previews, and tool-card links that deep-link into the browser. Do not add broad filesystem read APIs in this slice.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing session/tool-call API payloads.

---

### Task 1: Artifact extraction helper

**Files:**
- Create: `frontend/src/artifactBrowser.ts`
- Test: `frontend/src/artifactBrowser.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/artifactBrowser.test.ts` with a test that calls `buildArtifactBrowserItems(toolCalls)` and expects:

```ts
expect(items.map((item) => item.path)).toContain('src/train.py');
expect(items.map((item) => item.path)).toContain('.ml-copilot/reports/model-a/README.md');
expect(items.find((item) => item.path.includes('secret'))?.safe).toBe(false);
expect(items.find((item) => item.path.endsWith('README.md'))?.preview).toContain('# Model Card');
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- artifactBrowser.test.ts` from `frontend/`.
Expected: FAIL because `./artifactBrowser` does not exist.

- [ ] **Step 3: Implement minimal helper**

Create `artifactBrowser.ts` with:

- `buildArtifactBrowserItems(toolCalls: ToolCallPayload[]): ArtifactBrowserItem[]`
- safe path filtering for absolute paths, traversal, home paths, and environment-ish secret paths
- bounded preview extraction from tool output/error
- classification for Markdown, JSON, Python, text, directory, and artifact records
- deterministic de-duplication by normalized path

- [ ] **Step 4: Run focused helper test**

Run: `npm test -- artifactBrowser.test.ts`.
Expected: PASS.

### Task 2: Browser panel UI

**Files:**
- Create: `frontend/src/components/ArtifactBrowserPanel.tsx`
- Test: `frontend/src/components/ArtifactBrowserPanel.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create a test that renders `ArtifactBrowserPanel` with sandbox and publishing tool calls and expects:

- region name `File and artifact browser`
- counts for safe artifacts and blocked paths
- type/provenance labels
- bounded preview text
- a blocked unsafe path warning

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ArtifactBrowserPanel.test.tsx`.
Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement panel**

Build a panel with:

- a summary header
- artifact list with type, source tool, provenance, size when known, safe/blocked status
- selected artifact preview
- empty state when no artifacts exist
- safe-path copy/open command affordances only for safe items

- [ ] **Step 4: Run focused component test**

Run: `npm test -- ArtifactBrowserPanel.test.tsx`.
Expected: PASS.

### Task 3: Wire into workbench and trace cards

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ToolTracePanel.tsx`
- Modify: `frontend/src/components/ToolTracePanel.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing trace-card expectation**

Extend the tool trace test to expect relevant sandbox/publishing cards include an `Open artifact browser` link with `href="#artifact-browser"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- ToolTracePanel.test.tsx`.
Expected: FAIL because the link is not present yet.

- [ ] **Step 3: Implement wiring**

- Import and render `ArtifactBrowserPanel` in the inspector stack after runtime details.
- Add `Artifact browser` metadata link to sandbox, publishing, repository, and dataset-like tool cards.
- Add styles for `.artifact-browser-*`.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm test -- artifactBrowser.test.ts ArtifactBrowserPanel.test.tsx ToolTracePanel.test.tsx`.
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

Stage only ML-406 files plus this plan. Commit with `ML-406: Build file and artifact browser`, push `feature/ML-406-file-artifact-browser`, and open a PR whose body contains `Closes #114`.

- [ ] **Step 4: Verify PR metadata**

Run:

```bash
gh pr view <pr> --json assignees,labels,closingIssuesReferences
```

Expected: assignee `Sohail-Shaikh-07`, labels `feature` and `phase5`, closing issue `#114`.
