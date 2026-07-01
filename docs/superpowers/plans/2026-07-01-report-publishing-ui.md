# Report Publishing UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frontend final-report/publishing panel that makes `publish_model_report` outputs inspectable, previewable, provenance-aware, and safe around Hub publishing.

**Architecture:** Keep this slice frontend-first. Add pure parser helpers that derive publishing summaries from persisted `ToolCallPayload` records, then render them in a focused inspector panel wired into `App.tsx`. Reuse existing artifact-browser links instead of adding backend file-read or remote-publish behavior.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, existing persisted session API/tool-call payloads.

---

### Task 1: Publishing summary parser

**Files:**
- Create: `frontend/src/publishingDashboard.test.ts`
- Create: `frontend/src/publishingDashboard.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/publishingDashboard.test.ts` with a test that imports `buildPublishingDashboardSummary` from `./publishingDashboard`, feeds one `publish_model_report` call, and expects:

```ts
expect(summary.reports).toHaveLength(1);
expect(summary.reports[0].repoId).toBe('sohail/demo-model');
expect(summary.reports[0].publishState).toBe('local-only');
expect(summary.reports[0].artifacts.map((artifact) => artifact.fileName)).toEqual([
  'README.md',
  'FINAL_REPORT.md',
  'publish_manifest.json',
]);
expect(summary.reports[0].previewBlocks.map((block) => block.title)).toEqual([
  'README.md',
  'FINAL_REPORT.md',
  'publish_manifest.json',
]);
expect(summary.reports[0].provenance.datasets).toContain('imdb');
expect(summary.reports[0].provenance.jobs).toContain('train-job-1');
expect(summary.needsTokenWarning).toBe(false);
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd frontend
npm test -- publishingDashboard.test.ts
```

Expected: FAIL because `frontend/src/publishingDashboard.ts` does not exist yet.

- [ ] **Step 3: Implement minimal parser**

Create `frontend/src/publishingDashboard.ts` with:

```ts
import type { ToolCallPayload } from './types';

export type PublishState = 'local-only' | 'dry-run' | 'uploaded' | 'token-required' | 'error';

export interface PublishingArtifact {
  path: string;
  fileName: string;
  kind: string;
}

export interface PublishingPreviewBlock {
  title: string;
  content: string;
}

export interface PublishingProvenance {
  datasets: string[];
  papers: string[];
  jobs: string[];
  evals: string[];
}

export interface PublishingReportSummary {
  id: string;
  repoId: string | null;
  modelName: string | null;
  task: string | null;
  publishState: PublishState;
  outputDir: string | null;
  artifacts: PublishingArtifact[];
  previewBlocks: PublishingPreviewBlock[];
  provenance: PublishingProvenance;
  recommendation: string | null;
  warning: string | null;
}

export interface PublishingDashboardSummary {
  reports: PublishingReportSummary[];
  latestReport: PublishingReportSummary | null;
  needsTokenWarning: boolean;
}
```

Then implement helper functions for string/list coercion, artifact extraction from `- README:`, `- Final report:`, `- Manifest:`, fenced preview extraction under `### README.md`, `### FINAL_REPORT.md`, and `### publish_manifest.json`, JSON manifest parsing, and publish-state inference from output text and args.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
cd frontend
npm test -- publishingDashboard.test.ts
```

Expected: PASS.

### Task 2: Publishing panel component

**Files:**
- Create: `frontend/src/components/PublishingPanel.test.tsx`
- Create: `frontend/src/components/PublishingPanel.tsx`

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/components/PublishingPanel.test.tsx` rendering `<PublishingPanel toolCalls={calls} />` with a publishing call that includes README/final-report/manifest previews. Assert the panel exposes:

```ts
expect(screen.getByRole('region', { name: 'Final report and publishing UI' })).toBeInTheDocument();
expect(screen.getByText('sohail/demo-model')).toBeInTheDocument();
expect(screen.getByText('Local assets prepared')).toBeInTheDocument();
expect(screen.getByRole('link', { name: 'Open publishing artifacts' })).toHaveAttribute('href', '#artifact-browser');
expect(screen.getByText('README.md')).toBeInTheDocument();
expect(screen.getByText('FINAL_REPORT.md')).toBeInTheDocument();
expect(screen.getByText('publish_manifest.json')).toBeInTheDocument();
expect(screen.getByText('imdb')).toBeInTheDocument();
expect(screen.getByText('train-job-1')).toBeInTheDocument();
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd frontend
npm test -- PublishingPanel.test.tsx
```

Expected: FAIL because the component does not exist yet.

- [ ] **Step 3: Implement minimal component**

Create `frontend/src/components/PublishingPanel.tsx` that uses `useMemo(buildPublishingDashboardSummary(toolCalls))`, renders an empty state when no reports exist, shows the latest/all reports, status chip, repo/model metadata, warnings, provenance chips, artifact links to `#artifact-browser`, and bounded previews.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
cd frontend
npm test -- PublishingPanel.test.tsx
```

Expected: PASS.

### Task 3: Wire panel into inspector and tool cards

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ToolTracePanel.tsx`
- Modify: `frontend/src/components/ToolTracePanel.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing wiring test**

Update `frontend/src/components/ToolTracePanel.test.tsx` so the `publish_model_report` card is expected to include a link named `Open publishing panel` with `href="#publishing-panel"`.

- [ ] **Step 2: Verify RED**

Run:

```bash
cd frontend
npm test -- ToolTracePanel.test.tsx
```

Expected: FAIL because only runtime/artifact links exist.

- [ ] **Step 3: Implement wiring**

Import `PublishingPanel` in `frontend/src/App.tsx` and render it between `RuntimeDetailPanel` and `EvalDashboardPanel`. Add a publishing-panel metadata link helper in `ToolTracePanel.tsx` and call it for `publish_model_report`.

- [ ] **Step 4: Add styles**

Add focused `.publishing-panel`, `.publishing-report-card`, `.publishing-artifact-grid`, `.publishing-preview`, and `.publishing-provenance` styles in `frontend/src/styles.css`, following existing inspector card patterns.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
cd frontend
npm test -- ToolTracePanel.test.tsx PublishingPanel.test.tsx publishingDashboard.test.ts
```

Expected: PASS.

### Task 4: Full validation and handoff

**Files:**
- Modify: `ML-COPILOT-WORKFLOW.md` outside the repo root only
- Update: Notion ML-408 page

- [ ] **Step 1: Run frontend and backend validation**

Run:

```bash
cd frontend
npm test
npm run build
cd ..
python -m pytest tests/ -q
mypy app/ --ignore-missing-imports --follow-imports=skip
ruff check app/ tests/
ruff format --check app/ tests/
git diff --check
pre-commit run --all-files
cd frontend
npm audit --omit=dev
```

- [ ] **Step 2: Create PR with the established template**

Use title `ML-408 / Add final report and publishing UI`, labels `feature` and `phase5`, assignee `Sohail-Shaikh-07`, and a PR body with exactly `## Summary`, `Closes #118`, and `## Validation`.

- [ ] **Step 3: Verify metadata**

Run:

```bash
gh pr view --json number,title,labels,assignees,body,url
```

Expected: PR has both labels, self-assignee, and `Closes #118`.

- [ ] **Step 4: Update tracking**

Update Notion ML-408 to mention PR URL, validation, and auto-close linkage. Update local-only `D:\My work\Github Repository\ml-engineer\ML-COPILOT-WORKFLOW.md` without committing it.
