import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import RuntimeDetailPanel from './RuntimeDetailPanel';
import type { ToolCallPayload } from '../types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'experiment_workspace',
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

describe('RuntimeDetailPanel', () => {
  it('groups persisted sandbox, job, and artifact details with safe action affordances', () => {
    render(
      <RuntimeDetailPanel
        toolCalls={[
          toolCall({
            id: 'sandbox-create',
            arguments: { operation: 'create', hardware: 'cpu-basic' },
            output: [
              'Experiment workspace created.',
              '- Space: owner/ml-copilot-sandbox-session-1',
              '- URL: https://owner-ml-copilot-sandbox-session-1.hf.space',
              '- Hardware: cpu-basic',
              '- Created: 2026-06-30T06:00:00Z',
            ].join('\n'),
          }),
          toolCall({
            id: 'sandbox-write',
            arguments: { operation: 'write', path: 'src/train.py' },
            output: 'Wrote src/train.py (128 bytes).',
          }),
          toolCall({
            id: 'sandbox-run',
            arguments: { operation: 'run', command: 'python src/train.py', timeout_seconds: 120 },
            status: 'failed',
            success: false,
            error: ['Command: python src/train.py', 'Exit code: 1', '', 'Stderr:', 'CUDA out of memory'].join('\n'),
          }),
          toolCall({
            id: 'job-call',
            tool_name: 'manage_job',
            arguments: { operation: 'logs', job_id: 'job-123' },
            output: ['# Logs for job-123', '', '```', 'epoch=1 loss=0.42', '```'].join('\n'),
          }),
          toolCall({
            id: 'publish-call',
            tool_name: 'publish_model_report',
            arguments: { repo_id: 'owner/model-a', output_dir: '.ml-copilot/reports/model-a' },
            output: [
              'Prepared model publishing assets.',
              '- README: D:\\work\\.ml-copilot\\reports\\model-a\\README.md',
              '- Final report: D:\\work\\.ml-copilot\\reports\\model-a\\FINAL_REPORT.md',
              '- Manifest: D:\\work\\.ml-copilot\\reports\\model-a\\publish_manifest.json',
            ].join('\n'),
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Runtime detail panels' });
    expect(within(panel).getByText('1 sandbox')).toBeInTheDocument();
    expect(within(panel).getByText('1 job reference')).toBeInTheDocument();
    expect(within(panel).getAllByText('5 artifacts')).toHaveLength(2);

    const sandbox = screen.getByTestId('runtime-sandbox-owner-ml-copilot-sandbox-session-1');
    expect(within(sandbox).getByText('owner/ml-copilot-sandbox-session-1')).toBeInTheDocument();
    expect(within(sandbox).getByText('cpu-basic')).toBeInTheDocument();
    expect(within(sandbox).getByRole('link', { name: 'Open sandbox' })).toHaveAttribute(
      'href',
      'https://owner-ml-copilot-sandbox-session-1.hf.space',
    );
    expect(within(sandbox).getByText('src/train.py')).toBeInTheDocument();
    expect(within(sandbox).getByText('python src/train.py')).toBeInTheDocument();
    expect(within(sandbox).getByText(/CUDA out of memory/)).toBeInTheDocument();
    expect(within(sandbox).getByText("experiment_workspace operation='status'")).toBeInTheDocument();
    expect(within(sandbox).getByText("experiment_workspace operation='read' path='src/train.py'")).toBeInTheDocument();

    const job = screen.getByTestId('runtime-job-job-123');
    expect(within(job).getByText('job-123')).toBeInTheDocument();
    expect(within(job).getByText(/epoch=1 loss=0\.42/)).toBeInTheDocument();
    expect(within(job).getByText("manage_job operation='inspect' job_id='job-123'")).toBeInTheDocument();
    expect(within(job).getByText("manage_job operation='logs' job_id='job-123'")).toBeInTheDocument();

    const artifacts = screen.getByTestId('runtime-artifacts');
    expect(within(artifacts).getByText('.ml-copilot/reports/model-a')).toBeInTheDocument();
    expect(within(artifacts).getByText('README.md')).toBeInTheDocument();
    expect(within(artifacts).getByText('FINAL_REPORT.md')).toBeInTheDocument();
    expect(within(artifacts).getByText('publish_manifest.json')).toBeInTheDocument();
    expect(within(artifacts).getByText('src/train.py')).toBeInTheDocument();
  });
});
