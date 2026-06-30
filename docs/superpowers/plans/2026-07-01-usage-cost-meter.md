# Usage and Cost Meter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a product-grade usage meter that shows session tokens, estimated cost, runtime/tool usage, HF quota/credits warnings, and user budget guardrails without implying ML Copilot has its own billing system.

**Architecture:** Keep ML-405 frontend-first. Derive all values from existing `SessionMetricsSummary`, persisted `ToolCallPayload` records, and ML-404 `agent_controls` metadata. Add one pure helper module for usage summarization and one React panel in the inspector so the logic is typed and testable.

**Tech Stack:** React, TypeScript, Vitest, Testing Library, existing FastAPI/SQLite session metrics.

---

### Task 1: Pure usage summary helpers

**Files:**
- Create: `frontend/src/usageMeter.ts`
- Test: `frontend/src/usageMeter.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/usageMeter.test.ts` with assertions for:

```ts
import { describe, expect, it } from 'vitest';
import { buildUsageMeterSummary } from './usageMeter';
import type { SessionDetail, ToolCallPayload } from './types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'manage_job',
    arguments: {},
    status: 'success',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T00:00:00Z',
    finished_at: '2026-07-01T00:01:30Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

const session = {
  id: 'session-1',
  title: 'Usage check',
  status: 'idle',
  model: 'zai-org/GLM-5.2:novita',
  metadata: {
    agent_controls: {
      provider: 'zai',
      reasoning_effort: 'high',
      temperature: 0.2,
      operating_mode: 'fast',
      yolo_mode: true,
      max_turns: 4,
      spend_cap_usd: 0.05,
    },
  },
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:10:00Z',
  message_count: 4,
  event_count: 12,
  pending_approval_count: 0,
  pending_approvals: [],
  tool_calls: [],
  metrics: {
    session_id: 'session-1',
    turn_count: 3,
    prompt_tokens: 1200,
    completion_tokens: 800,
    total_tokens: 2000,
    estimated_cost_usd: 0.045,
    tool_calls: 3,
    tool_errors: 1,
    tool_retries: 1,
    tool_latency_ms: 90000,
    average_tool_latency_ms: 30000,
    error_count: 1,
    last_updated_at: '2026-07-01T00:10:00Z',
  },
} satisfies SessionDetail;

describe('usageMeter', () => {
  it('summarizes usage, budget progress, runtime mix, and HF quota warnings', () => {
    const summary = buildUsageMeterSummary(session, [
      toolCall({ id: 'job-run', tool_name: 'manage_job', arguments: { operation: 'run' } }),
      toolCall({ id: 'sandbox-run', tool_name: 'experiment_workspace', arguments: { operation: 'run' } }),
      toolCall({
        id: 'quota-error',
        tool_name: 'manage_job',
        status: 'failed',
        success: false,
        error: 'namespace has no available credits. Add credits at https://huggingface.co/settings/billing',
      }),
    ]);

    expect(summary.costProgressPercent).toBe(90);
    expect(summary.turnProgressPercent).toBe(75);
    expect(summary.warningLevel).toBe('warning');
    expect(summary.runtimeBreakdown).toEqual([
      { label: 'HF Jobs', count: 2 },
      { label: 'Sandbox', count: 1 },
    ]);
    expect(summary.hfQuotaWarning?.title).toBe('Hugging Face credits or quota needed');
    expect(summary.copyNote).toContain('Estimates only');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- usageMeter.test.ts`

Expected: FAIL because `frontend/src/usageMeter.ts` does not exist.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/usageMeter.ts` with:

```ts
import { readStoredAgentControls } from './sessionControls';
import type { SessionDetail, ToolCallPayload } from './types';

export type UsageWarningLevel = 'neutral' | 'warning' | 'danger';

export interface UsageMeterSummary {
  costCapUsd: number | null;
  costProgressPercent: number | null;
  turnCap: number | null;
  turnProgressPercent: number | null;
  warningLevel: UsageWarningLevel;
  runtimeBreakdown: Array<{ label: string; count: number }>;
  hfQuotaWarning: { title: string; body: string; href: string } | null;
  copyNote: string;
}

export function buildUsageMeterSummary(session: SessionDetail, toolCalls: ToolCallPayload[]): UsageMeterSummary {
  const controls = readStoredAgentControls(session.metadata);
  const costCapUsd = controls?.spend_cap_usd ?? null;
  const turnCap = controls?.max_turns ?? null;
  const costProgressPercent = progress(session.metrics.estimated_cost_usd, costCapUsd);
  const turnProgressPercent = progress(session.metrics.turn_count, turnCap);
  const warningLevel = highestWarning(costProgressPercent, turnProgressPercent);
  return {
    costCapUsd,
    costProgressPercent,
    turnCap,
    turnProgressPercent,
    warningLevel,
    runtimeBreakdown: buildRuntimeBreakdown(toolCalls),
    hfQuotaWarning: findHfQuotaWarning(toolCalls),
    copyNote: 'Estimates only. Actual charges happen with your configured model provider or Hugging Face account.',
  };
}
```

Add the `progress`, `highestWarning`, `buildRuntimeBreakdown`, and `findHfQuotaWarning` helpers in the same file. Count `manage_job` as “HF Jobs”, `experiment_workspace` as “Sandbox”, `publish_model_report` as “Publishing”, and `manage_experiment_loop` as “Experiment loop”. Detect quota warnings when output/error includes `credits`, `quota`, `billing`, `payment required`, or `402`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- usageMeter.test.ts`

Expected: PASS.

### Task 2: Usage meter panel

**Files:**
- Create: `frontend/src/components/UsageMeterPanel.tsx`
- Test: `frontend/src/components/UsageMeterPanel.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/components/UsageMeterPanel.test.tsx` that renders a `UsageMeterPanel` with a session containing `estimated_cost_usd`, token counts, a spend cap, max turns, and an HF quota error tool call. Assert visible labels:

```ts
expect(screen.getByRole('region', { name: 'Usage and cost estimate' })).toBeInTheDocument();
expect(screen.getByText('2K tokens')).toBeInTheDocument();
expect(screen.getByText('$0.0450 est.')).toBeInTheDocument();
expect(screen.getByText('90% of $0.05 cap')).toBeInTheDocument();
expect(screen.getByText('3 / 4 turns')).toBeInTheDocument();
expect(screen.getByText('HF Jobs')).toBeInTheDocument();
expect(screen.getByText('Hugging Face credits or quota needed')).toBeInTheDocument();
expect(screen.getByText(/Estimates only/)).toBeInTheDocument();
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- UsageMeterPanel.test.tsx`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement and wire the panel**

Implement `UsageMeterPanel` to accept:

```ts
interface UsageMeterPanelProps {
  session: SessionDetail | null;
  toolCalls: ToolCallPayload[];
}
```

Render an empty state when no session is selected. For a selected session, render:

- token split: prompt, completion, total
- estimated cost and spend-cap progress
- turn progress against `max_turns`
- tool/runtime breakdown
- tool health: errors, retries, average latency
- HF quota warning with link only when detected
- estimate disclaimer copy

In `App.tsx`, import and place `<UsageMeterPanel session={activeSession} toolCalls={toolCalls} />` in the inspector stack near the job/runtime panels.

- [ ] **Step 4: Style the panel**

Add CSS classes with the project’s current glass-card style:

```css
.usage-meter-panel
.usage-meter-grid
.usage-meter-card
.usage-meter-progress
.usage-meter-progress span
.usage-meter-warning
.usage-meter-breakdown
```

- [ ] **Step 5: Run focused tests**

Run: `npm test -- usageMeter.test.ts UsageMeterPanel.test.tsx`

Expected: PASS.

### Task 3: Verification and publish

**Files:**
- Commit only ML-405 files and no local workflow/untracked artifacts.

- [ ] **Step 1: Run full validation**

Run:

```bash
npm test
npm run build
python -m pytest tests/ -q
ruff check app/ tests/
ruff format --check app/ tests/
mypy app/ --ignore-missing-imports --follow-imports=skip
git diff --check
```

- [ ] **Step 2: Commit and push**

Stage only:

```text
docs/superpowers/plans/2026-07-01-usage-cost-meter.md
frontend/src/usageMeter.ts
frontend/src/usageMeter.test.ts
frontend/src/components/UsageMeterPanel.tsx
frontend/src/components/UsageMeterPanel.test.tsx
frontend/src/App.tsx
frontend/src/styles.css
```

Commit: `ML-405: Add usage and billing meter`

- [ ] **Step 3: Open PR**

Create PR title `ML-405 / Add usage and billing meter`; body must include:

```markdown
## Reference
Closes #112
```

Verify assignee, labels, and closing issue reference with:

```bash
gh pr view <pr> --json assignees,labels,closingIssuesReferences
```

Then watch CI and post the required `Code review` comment.

