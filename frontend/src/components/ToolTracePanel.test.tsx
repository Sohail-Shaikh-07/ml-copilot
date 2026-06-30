import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import ToolTracePanel from './ToolTracePanel';
import type { SessionEventPayload, ToolCallPayload } from '../types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'tool-call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'manage_job',
    arguments: {},
    status: 'success',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-06-30T06:00:00Z',
    finished_at: '2026-06-30T06:02:05Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

function liveEvent(overrides: Partial<SessionEventPayload>): SessionEventPayload {
  return {
    id: 'event-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    event_type: 'tool_call_started',
    data: {},
    sequence: 1,
    created_at: '2026-06-30T06:00:00Z',
    ...overrides,
  };
}

describe('ToolTracePanel', () => {
  it('renders categorized tool cards with summarized output and expandable raw details', async () => {
    const user = userEvent.setup();
    const longLog = `${'training log line\n'.repeat(40)}final validation accuracy: 0.91`;

    render(
      <ToolTracePanel
        metrics={{
          session_id: 'session-1',
          turn_count: 1,
          prompt_tokens: 1200,
          completion_tokens: 700,
          total_tokens: 1900,
          estimated_cost_usd: 0.0432,
          tool_calls: 3,
          tool_errors: 1,
          tool_retries: 0,
          tool_latency_ms: 125000,
          average_tool_latency_ms: 41666,
          error_count: 1,
          last_updated_at: '2026-06-30T06:03:00Z',
        }}
        pendingApprovals={[]}
        liveEvents={[
          liveEvent({
            id: 'event-job',
            event_type: 'tool_call_started',
            data: { tool_name: 'manage_job', operation: 'run' },
            sequence: 7,
          }),
        ]}
        toolCalls={[
          toolCall({
            id: 'job-call',
            tool_name: 'manage_job',
            arguments: { operation: 'run', hardware: 'cpu-basic', timeout_seconds: 600 },
            output: [
              'Job hf-job-123 started.',
              'Status: RUNNING',
              'Hardware: cpu-basic',
              'URL: https://huggingface.co/jobs/hf-job-123',
              longLog,
            ].join('\n'),
          }),
          toolCall({
            id: 'sandbox-call',
            tool_name: 'experiment_workspace',
            arguments: { operation: 'run', command: 'python train.py' },
            status: 'failed',
            success: false,
            error: 'Command failed with CUDA out of memory while training.',
          }),
          toolCall({
            id: 'publish-call',
            tool_name: 'publish_model_report',
            arguments: { output_dir: '.ml-copilot/reports/model-a' },
            output: 'Prepared README.md, FINAL_REPORT.md, and publish_manifest.json.',
          }),
        ]}
      />,
    );

    const jobCard = screen.getByTestId('tool-card-job-call');
    expect(within(jobCard).getByText('Job orchestration')).toBeInTheDocument();
    expect(within(jobCard).getByText('Hugging Face job')).toBeInTheDocument();
    expect(within(jobCard).getByText('RUNNING')).toBeInTheDocument();
    expect(within(jobCard).getByText('cpu-basic')).toBeInTheDocument();
    expect(within(jobCard).getByRole('link', { name: 'Open job' })).toHaveAttribute(
      'href',
      'https://huggingface.co/jobs/hf-job-123',
    );
    expect(within(jobCard).queryByText(/final validation accuracy/)).not.toBeInTheDocument();

    await user.click(within(jobCard).getByRole('button', { name: 'Show details for Hugging Face job' }));

    expect(within(jobCard).getByText(/final validation accuracy: 0\.91/)).toBeInTheDocument();
    expect(within(jobCard).getByText(/"timeout_seconds": 600/)).toBeInTheDocument();

    const sandboxCard = screen.getByTestId('tool-card-sandbox-call');
    expect(within(sandboxCard).getByText('Sandbox runtime')).toBeInTheDocument();
    expect(within(sandboxCard).getByText('Command failed with CUDA out of memory while training.')).toBeInTheDocument();
    expect(within(sandboxCard).getByRole('link', { name: 'Open runtime panel' })).toHaveAttribute(
      'href',
      '#runtime-details',
    );

    const publishCard = screen.getByTestId('tool-card-publish-call');
    expect(within(publishCard).getByText('Publishing')).toBeInTheDocument();
    expect(within(publishCard).getByText('.ml-copilot/reports/model-a')).toBeInTheDocument();
  });
});
