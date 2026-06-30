import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import SessionSidebar from './SessionSidebar';
import { DEFAULT_SESSION_CONTROLS, type SessionControlState } from '../sessionControls';
import type { MessagePayload, SessionDetail, SessionSummary } from '../types';

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 'session-1',
    title: 'Train classifier',
    status: 'idle',
    model: 'zai-org/GLM-5.2:novita',
    metadata: {},
    created_at: '2026-06-30T06:00:00Z',
    updated_at: '2026-06-30T06:30:00Z',
    message_count: 3,
    event_count: 9,
    pending_approval_count: 0,
    metrics: {
      session_id: 'session-1',
      turn_count: 2,
      prompt_tokens: 1000,
      completion_tokens: 500,
      total_tokens: 1500,
      estimated_cost_usd: 0.012,
      tool_calls: 4,
      tool_errors: 0,
      tool_retries: 0,
      tool_latency_ms: 1200,
      average_tool_latency_ms: 300,
      error_count: 0,
      last_updated_at: '2026-06-30T06:30:00Z',
    },
    ...overrides,
  };
}

function message(overrides: Partial<MessagePayload> = {}): MessagePayload {
  return {
    id: 'message-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    role: 'assistant',
    content: 'Ready.',
    tool_call_id: null,
    name: null,
    raw: {},
    sequence: 1,
    created_at: '2026-06-30T06:01:00Z',
    ...overrides,
  };
}

describe('SessionSidebar model/provider controls', () => {
  it('renders provider controls and saved session preferences', async () => {
    const user = userEvent.setup();
    const setDraftControls = vi.fn();
    const draftControls: SessionControlState = {
      ...DEFAULT_SESSION_CONTROLS,
      provider: 'zai',
      reasoningEffort: 'high',
      temperature: '0.2',
      operatingMode: 'careful',
      maxTurns: '120',
      spendCapUsd: '3.50',
    };
    const activeSession = session({
      metadata: {
        agent_controls: {
          provider: 'zai',
          reasoning_effort: 'high',
          temperature: 0.2,
          operating_mode: 'careful',
          yolo_mode: false,
          max_turns: 120,
          spend_cap_usd: 3.5,
        },
      },
    }) as SessionDetail;

    render(
      <SessionSidebar
        activeSession={{ ...activeSession, pending_approvals: [], tool_calls: [] }}
        creating={false}
        draftControls={draftControls}
        draftHfToken=""
        draftModel="zai-org/GLM-5.2:novita"
        draftTitle=""
        messages={[message()]}
        onCreateSession={vi.fn()}
        onRefreshSessions={vi.fn()}
        onSelectSession={vi.fn()}
        selectedSessionId="session-1"
        sessions={[activeSession]}
        setDraftControls={setDraftControls}
        setDraftHfToken={vi.fn()}
        setDraftModel={vi.fn()}
        setDraftTitle={vi.fn()}
      />,
    );

    const controls = screen.getByRole('region', { name: 'Model and provider controls' });
    expect(within(controls).getByLabelText('Provider')).toHaveValue('zai');
    expect(within(controls).getByLabelText('Reasoning effort')).toHaveValue('high');
    expect(within(controls).getByLabelText('Operating mode')).toHaveValue('careful');
    expect(within(controls).getByLabelText('Temperature')).toHaveValue(0.2);
    expect(within(controls).getByLabelText('Max turns')).toHaveValue(120);
    expect(within(controls).getByLabelText('Spend cap')).toHaveValue(3.5);
    expect(within(controls).getByRole('button', { name: 'Use GLM 5.2' })).toBeInTheDocument();

    await user.selectOptions(within(controls).getByLabelText('Provider'), 'anthropic');

    expect(setDraftControls).toHaveBeenCalledWith(expect.objectContaining({ provider: 'anthropic' }));

    const summary = screen.getByTestId('selected-session-controls');
    expect(within(summary).getByText('Provider: Z.ai')).toBeInTheDocument();
    expect(within(summary).getByText('Effort: high')).toBeInTheDocument();
    expect(within(summary).getByText('Mode: careful')).toBeInTheDocument();
    expect(within(summary).getByText('Spend cap: $3.50')).toBeInTheDocument();
  });
});
