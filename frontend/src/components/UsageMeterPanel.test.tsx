import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import UsageMeterPanel from './UsageMeterPanel';
import type { SessionDetail, ToolCallPayload } from '../types';

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

function session(): SessionDetail {
  return {
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
  };
}

describe('UsageMeterPanel', () => {
  it('renders session usage estimates, budget guardrails, runtime usage, and HF quota warnings', () => {
    render(
      <UsageMeterPanel
        session={session()}
        toolCalls={[
          toolCall({ id: 'job-run', tool_name: 'manage_job', arguments: { operation: 'run' } }),
          toolCall({ id: 'sandbox-run', tool_name: 'experiment_workspace', arguments: { operation: 'run' } }),
          toolCall({
            id: 'quota-error',
            tool_name: 'manage_job',
            status: 'failed',
            success: false,
            error: 'namespace has no available credits. Add credits at https://huggingface.co/settings/billing',
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Usage and cost estimate' });
    expect(within(panel).getByText('2K tokens')).toBeInTheDocument();
    expect(within(panel).getByText('$0.0450 est.')).toBeInTheDocument();
    expect(within(panel).getByText('90% of $0.05 cap')).toBeInTheDocument();
    expect(within(panel).getByText('3 / 4 turns')).toBeInTheDocument();
    expect(within(panel).getByText('HF Jobs')).toBeInTheDocument();
    expect(within(panel).getByText('Hugging Face credits or quota needed')).toBeInTheDocument();
    expect(within(panel).getByText(/Estimates only/)).toBeInTheDocument();
  });
});
