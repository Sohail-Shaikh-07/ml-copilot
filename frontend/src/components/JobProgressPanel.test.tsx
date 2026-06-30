import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import JobProgressPanel from './JobProgressPanel';
import type { ToolCallPayload } from '../types';

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
    started_at: '2026-06-30T06:00:00Z',
    finished_at: '2026-06-30T06:01:00Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

describe('JobProgressPanel', () => {
  it('renders persisted Hugging Face job status, logs, actions, and billing hints', () => {
    render(
      <JobProgressPanel
        toolCalls={[
          toolCall({
            id: 'run-call',
            arguments: { operation: 'run', hardware_flavor: 'cpu-basic', timeout: '30m' },
            output: [
              '# Job launched',
              '',
              '### Job job-123',
              '- **Status:** RUNNING',
              '- **Message:** pulling image',
              '- **Hardware:** cpu-basic',
              '- **Created:** 2026-06-30T06:00:00Z',
              '- **Command:** `python train.py`',
              '- **URL:** https://huggingface.co/jobs/job-123',
              '',
              "**Next:** Use manage_job with operation 'inspect', 'logs', or 'cancel'.",
            ].join('\n'),
          }),
          toolCall({
            id: 'logs-call',
            arguments: { operation: 'logs', job_id: 'job-123' },
            output: ['# Logs for job-123', '', '```', 'epoch=1 loss=0.42', 'eval accuracy=0.91', '```'].join('\n'),
          }),
          toolCall({
            id: 'billing-call',
            arguments: { operation: 'run', hardware_flavor: 'a10g-small', namespace: 'team-space' },
            status: 'failed',
            success: false,
            error:
              'Error: Hugging Face rejected this run because the namespace has no available credits. Add credits at https://huggingface.co/settings/billing and re-run the job.',
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Hugging Face job progress' });
    expect(within(panel).getByText('1 active job')).toBeInTheDocument();

    const jobCard = screen.getByTestId('job-progress-job-123');
    expect(within(jobCard).getByText('RUNNING')).toBeInTheDocument();
    expect(within(jobCard).getByText('cpu-basic')).toBeInTheDocument();
    expect(within(jobCard).getByText('2026-06-30T06:00:00Z')).toBeInTheDocument();
    expect(within(jobCard).getByRole('link', { name: 'Open on Hugging Face' })).toHaveAttribute(
      'href',
      'https://huggingface.co/jobs/job-123',
    );

    expect(within(jobCard).getByText('Launched')).toBeInTheDocument();
    expect(within(jobCard).getByText('Logs fetched')).toBeInTheDocument();
    expect(within(jobCard).getByText(/epoch=1 loss=0\.42/)).toBeInTheDocument();
    expect(within(jobCard).getByText(/eval accuracy=0\.91/)).toBeInTheDocument();

    expect(within(jobCard).getByText("manage_job operation='inspect' job_id='job-123'")).toBeInTheDocument();
    expect(within(jobCard).getByText("manage_job operation='logs' job_id='job-123'")).toBeInTheDocument();
    expect(within(jobCard).getByText("manage_job operation='cancel' job_id='job-123'")).toBeInTheDocument();

    expect(within(panel).getByText('Namespace credits needed')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: 'Open HF billing' })).toHaveAttribute(
      'href',
      'https://huggingface.co/settings/billing',
    );
  });
});
