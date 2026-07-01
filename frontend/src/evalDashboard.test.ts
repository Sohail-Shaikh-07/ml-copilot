import { describe, expect, it } from 'vitest';

import { buildEvalDashboardSummary } from './evalDashboard';
import type { ToolCallPayload } from './types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'manage_eval_suite',
    arguments: {},
    status: 'success',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T06:00:00Z',
    finished_at: '2026-07-01T06:01:00Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

const suiteReport = {
  status: 'failed',
  summary: {
    fixtures_total: 2,
    fixtures_passed: 1,
    fixtures_failed: 1,
    fixtures_error: 0,
    average_score: 0.5,
    runtime_seconds: 12.4,
    total_tokens: 321,
  },
  fixtures: [
    {
      fixture_id: 'fixture-pass',
      status: 'passed',
      score: 1,
      report_path: '.ml-copilot/evals/artifacts/pass/report.json',
      markdown_path: '.ml-copilot/evals/artifacts/pass/report.md',
      workspace_path: '.ml-copilot/evals/workspaces/pass',
    },
    {
      fixture_id: 'fixture-fail',
      status: 'failed',
      score: 0,
      report_path: '.ml-copilot/evals/artifacts/fail/report.json',
      markdown_path: '.ml-copilot/evals/artifacts/fail/report.md',
      workspace_path: '.ml-copilot/evals/workspaces/fail',
      report: {
        fixture: { metadata: { mode: 'scripted' } },
        scoring: {
          file_changes: { files_changed: ['src/train.py'] },
        },
        checks: [
          { type: 'file_contains', passed: false, path: 'src/train.py', message: 'Expected metric is missing.' },
        ],
      },
    },
  ],
};

describe('buildEvalDashboardSummary', () => {
  it('extracts suite reports and derives release gate state with fixture details', () => {
    const summary = buildEvalDashboardSummary([
      toolCall({
        output: ['Eval suite completed.', '```json', JSON.stringify(suiteReport), '```'].join('\n'),
      }),
    ]);

    expect(summary.gateStatus).toBe('blocked');
    expect(summary.totalSuites).toBe(1);
    expect(summary.latestSuite?.status).toBe('failed');
    expect(summary.latestSuite?.averageScore).toBe(0.5);
    expect(summary.suites[0].fixtures).toHaveLength(2);
    expect(summary.suites[0].fixtures[1]).toMatchObject({
      fixtureId: 'fixture-fail',
      status: 'failed',
      mode: 'scripted',
      changedFiles: ['src/train.py'],
    });
    expect(summary.suites[0].fixtures[1].checks[0]).toMatchObject({
      type: 'file_contains',
      passed: false,
      message: 'Expected metric is missing.',
    });
  });
});
