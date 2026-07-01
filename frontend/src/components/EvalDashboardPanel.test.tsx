import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import EvalDashboardPanel from './EvalDashboardPanel';
import type { ToolCallPayload } from '../types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'eval-suite-call',
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

describe('EvalDashboardPanel', () => {
  it('shows release gate health, suite metrics, fixtures, failures, and artifact links', () => {
    const report = {
      status: 'failed',
      summary: {
        fixtures_total: 2,
        fixtures_passed: 1,
        fixtures_failed: 1,
        fixtures_error: 0,
        average_score: 0.5,
        runtime_seconds: 9.25,
        total_tokens: 42,
      },
      fixtures: [
        {
          fixture_id: 'fixture-pass',
          status: 'passed',
          score: 1,
          markdown_path: '.ml-copilot/evals/artifacts/pass/report.md',
          report_path: '.ml-copilot/evals/artifacts/pass/report.json',
          report: {
            agent_output: { mode: 'live' },
            checks: [{ type: 'contains', passed: true, message: 'Final response contains expected text.' }],
          },
        },
        {
          fixture_id: 'fixture-fail',
          status: 'failed',
          score: 0,
          markdown_path: '.ml-copilot/evals/artifacts/fail/report.md',
          report_path: '.ml-copilot/evals/artifacts/fail/report.json',
          workspace_path: '.ml-copilot/evals/workspaces/fail',
          report: {
            fixture: { metadata: { mode: 'scripted' } },
            scoring: { file_changes: { files_changed: ['src/train.py'] } },
            checks: [
              {
                type: 'file_contains',
                passed: false,
                path: 'src/train.py',
                message: 'Expected metric is missing.',
              },
            ],
          },
        },
      ],
    };

    render(
      <EvalDashboardPanel
        toolCalls={[
          toolCall({
            output: ['Suite report:', '```json', JSON.stringify(report), '```'].join('\n'),
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Eval suite dashboard' });
    expect(within(panel).getByText('Release gate blocked')).toBeInTheDocument();
    expect(within(panel).getByText('50% score')).toBeInTheDocument();
    expect(within(panel).getByText('1 / 2 passed')).toBeInTheDocument();
    expect(within(panel).getByText('9.25s runtime')).toBeInTheDocument();
    expect(within(panel).getByText('42 tokens')).toBeInTheDocument();
    expect(within(panel).getByText('fixture-fail')).toBeInTheDocument();
    expect(within(panel).getByText('scripted')).toBeInTheDocument();
    expect(within(panel).getByText('src/train.py')).toBeInTheDocument();
    expect(within(panel).getByText('Expected metric is missing.')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: 'Open eval artifacts' })).toHaveAttribute(
      'href',
      '#artifact-browser',
    );
  });
});
