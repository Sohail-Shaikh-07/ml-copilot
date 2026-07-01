import { describe, expect, it } from 'vitest';

import { buildWorkbenchFlowSummary } from './workbenchFlow';
import type { RecoverySnapshot } from './workbenchState';
import type { MessagePayload, SessionDetail, ToolCallPayload } from './types';

function metrics() {
  return {
    session_id: 'session-1',
    turn_count: 3,
    prompt_tokens: 1000,
    completion_tokens: 700,
    total_tokens: 1700,
    estimated_cost_usd: 0.034,
    tool_calls: 7,
    tool_errors: 0,
    tool_retries: 1,
    tool_latency_ms: 45000,
    average_tool_latency_ms: 6428,
    error_count: 0,
    last_updated_at: '2026-07-01T06:10:00Z',
  };
}

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
    started_at: '2026-07-01T06:00:00Z',
    finished_at: '2026-07-01T06:01:00Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

function session(toolCalls: ToolCallPayload[]): SessionDetail {
  return {
    id: 'session-1',
    title: 'Autonomous workflow',
    status: 'running',
    model: 'zai-org/GLM-5.2:novita',
    metadata: { agent_controls: { provider: 'zai', reasoning_effort: 'high' } },
    created_at: '2026-07-01T06:00:00Z',
    updated_at: '2026-07-01T06:10:00Z',
    message_count: 2,
    event_count: 12,
    pending_approval_count: 0,
    metrics: metrics(),
    pending_approvals: [],
    tool_calls: toolCalls,
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
    created_at: '2026-07-01T06:00:00Z',
    ...overrides,
  };
}

const recovery: RecoverySnapshot = {
  sessionId: 'session-1',
  sessionTitle: 'Autonomous workflow',
  messageCount: 2,
  toolCallCount: 7,
  liveEventCount: 2,
  persistedEventCount: 12,
  lastEventSequence: 11,
  replayedEventCount: 2,
  duplicateEventCount: 1,
  recoveredAt: '2026-07-01T06:10:00Z',
  status: 'recovered',
};

describe('buildWorkbenchFlowSummary', () => {
  it('derives an end-to-end autonomous workflow from existing session state', () => {
    const toolCalls = [
      toolCall({ id: 'dataset', tool_name: 'inspect_dataset', arguments: { dataset: 'imdb' }, output: 'Dataset imdb has train/test splits.' }),
      toolCall({ id: 'paper', tool_name: 'paper_details', arguments: { arxiv_id: '2401.12345' }, output: '# Efficient Fine-Tuning' }),
      toolCall({ id: 'sandbox', tool_name: 'experiment_workspace', arguments: { operation: 'run', command: 'python train.py' }, output: 'Wrote src/train.py' }),
      toolCall({ id: 'job', tool_name: 'manage_job', arguments: { operation: 'run', hardware_flavor: 'cpu-basic' }, output: 'Status: RUNNING' }),
      toolCall({ id: 'eval', tool_name: 'manage_eval_suite', arguments: { operation: 'run' }, output: 'Suite report: {"status":"passed"}' }),
      toolCall({ id: 'publish', tool_name: 'publish_model_report', arguments: { repo_id: 'owner/model-a' }, output: 'Prepared README.md and FINAL_REPORT.md' }),
    ];

    const summary = buildWorkbenchFlowSummary({
      session: session(toolCalls),
      messages: [message({ role: 'user', content: 'Train a model.' }), message()],
      toolCalls,
      recovery,
    });

    expect(summary.completedCount).toBe(8);
    expect(summary.resumeLabel).toBe('Recovered through event #11');
    expect(summary.stages.map((stage) => stage.id)).toEqual([
      'setup',
      'data',
      'research',
      'runtime',
      'monitor',
      'artifacts',
      'evals',
      'publish',
    ]);
    expect(summary.stages.every((stage) => stage.status === 'complete')).toBe(true);
    expect(summary.stages.find((stage) => stage.id === 'setup')?.href).toBe('#model-provider-controls');
    expect(summary.stages.find((stage) => stage.id === 'runtime')?.href).toBe('#runtime-details');
    expect(summary.stages.find((stage) => stage.id === 'evals')?.href).toBe('#eval-dashboard');
    expect(summary.walkthrough).toHaveLength(8);
    expect(summary.walkthrough[0]).toContain('Choose provider');
  });

  it('marks the first missing stage as active so users know where to continue', () => {
    const summary = buildWorkbenchFlowSummary({
      session: session([]),
      messages: [message()],
      toolCalls: [],
      recovery: null,
    });

    expect(summary.completedCount).toBe(1);
    expect(summary.stages.find((stage) => stage.id === 'setup')?.status).toBe('complete');
    expect(summary.stages.find((stage) => stage.id === 'data')?.status).toBe('active');
    expect(summary.stages.find((stage) => stage.id === 'research')?.status).toBe('waiting');
    expect(summary.resumeLabel).toBe('No recovery snapshot yet');
  });
});
