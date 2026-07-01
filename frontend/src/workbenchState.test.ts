import { describe, expect, it } from 'vitest';

import {
  buildRecoverySnapshot,
  deriveConnectionHealth,
  mergeSessionSummaries,
  replaySessionEvents,
} from './workbenchState';
import type { MessagePayload, SessionDetail, SessionEventPayload, SessionSummary, ToolCallPayload } from './types';

function metrics() {
  return {
    session_id: 'session-1',
    turn_count: 1,
    prompt_tokens: 10,
    completion_tokens: 20,
    total_tokens: 30,
    estimated_cost_usd: 0.001,
    tool_calls: 2,
    tool_errors: 0,
    tool_retries: 0,
    tool_latency_ms: 500,
    average_tool_latency_ms: 250,
    error_count: 0,
    last_updated_at: '2026-07-01T06:00:00Z',
  };
}

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 'session-1',
    title: 'Train model',
    status: 'running',
    model: 'zai-org/GLM-5.2:novita',
    metadata: {},
    created_at: '2026-07-01T05:00:00Z',
    updated_at: '2026-07-01T06:00:00Z',
    message_count: 2,
    event_count: 8,
    pending_approval_count: 0,
    metrics: metrics(),
    ...overrides,
  };
}

function detail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    ...session(),
    pending_approvals: [],
    tool_calls: [],
    ...overrides,
  };
}

function message(overrides: Partial<MessagePayload> = {}): MessagePayload {
  return {
    id: 'message-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    role: 'assistant',
    content: 'Recovered answer',
    tool_call_id: null,
    name: null,
    raw: {},
    sequence: 4,
    created_at: '2026-07-01T05:01:00Z',
    ...overrides,
  };
}

function event(overrides: Partial<SessionEventPayload> = {}): SessionEventPayload {
  return {
    id: 'event-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    event_type: 'assistant_chunk',
    data: { content: 'hello' },
    sequence: 7,
    created_at: '2026-07-01T05:02:00Z',
    ...overrides,
  };
}

function toolCall(overrides: Partial<ToolCallPayload> = {}): ToolCallPayload {
  return {
    id: 'tool-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'manage_job',
    arguments: {},
    status: 'success',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T05:02:00Z',
    finished_at: '2026-07-01T05:03:00Z',
    output: 'done',
    success: true,
    error: null,
    ...overrides,
  };
}

describe('workbench state helpers', () => {
  it('merges session summaries by id and keeps the newest updated session first', () => {
    const merged = mergeSessionSummaries(
      [session({ id: 'session-1', title: 'Old', updated_at: '2026-07-01T05:00:00Z' })],
      [
        session({ id: 'session-2', title: 'Another', updated_at: '2026-07-01T05:30:00Z' }),
        session({ id: 'session-1', title: 'New', updated_at: '2026-07-01T06:00:00Z' }),
      ],
    );

    expect(merged.map((item) => item.id)).toEqual(['session-1', 'session-2']);
    expect(merged[0].title).toBe('New');
  });

  it('replays session events with dedupe, bounded history, assistant deltas, and terminal detection', () => {
    const replay = replaySessionEvents({
      current: [
        event({ id: 'event-1', sequence: 7, data: { content: 'hello ' } }),
        event({ id: 'event-older', sequence: 6, event_type: 'tool_call_started', data: {} }),
      ],
      incoming: [
        event({ id: 'event-1', sequence: 7, data: { content: 'duplicate' } }),
        event({ id: 'event-2', sequence: 8, data: { content: 'world' } }),
        event({ id: 'event-3', sequence: 9, event_type: 'turn_complete', data: {} }),
      ],
      limit: 3,
    });

    expect(replay.events.map((item) => item.id)).toEqual(['event-1', 'event-2', 'event-3']);
    expect(replay.lastSequence).toBe(9);
    expect(replay.duplicateCount).toBe(1);
    expect(replay.replayedCount).toBe(2);
    expect(replay.assistantDelta).toBe('world');
    expect(replay.terminalEventType).toBe('turn_complete');
  });

  it('builds a recovery snapshot from persisted session detail and replayed events', () => {
    const snapshot = buildRecoverySnapshot({
      session: detail({ event_count: 12, tool_calls: [toolCall(), toolCall({ id: 'tool-2' })] }),
      messages: [message(), message({ id: 'message-2', sequence: 5 })],
      liveEvents: [event({ sequence: 7 }), event({ id: 'event-2', sequence: 9 })],
      lastEventSequence: 9,
      replayedEventCount: 3,
      duplicateEventCount: 1,
      recoveredAt: '2026-07-01T06:05:00Z',
    });

    expect(snapshot?.sessionTitle).toBe('Train model');
    expect(snapshot?.messageCount).toBe(2);
    expect(snapshot?.toolCallCount).toBe(2);
    expect(snapshot?.lastEventSequence).toBe(9);
    expect(snapshot?.replayedEventCount).toBe(3);
    expect(snapshot?.duplicateEventCount).toBe(1);
    expect(snapshot?.status).toBe('recovered');
  });

  it('derives live, stale, reconnecting, and offline connection health', () => {
    expect(deriveConnectionHealth({
      loadState: 'ready',
      sessionState: 'ready',
      streamState: 'streaming',
      lastEventAt: '2026-07-01T06:00:00Z',
      now: '2026-07-01T06:00:20Z',
      staleAfterMs: 60_000,
    }).phase).toBe('live');

    expect(deriveConnectionHealth({
      loadState: 'ready',
      sessionState: 'ready',
      streamState: 'streaming',
      lastEventAt: '2026-07-01T06:00:00Z',
      now: '2026-07-01T06:02:00Z',
      staleAfterMs: 60_000,
    }).phase).toBe('stale');

    expect(deriveConnectionHealth({
      loadState: 'ready',
      sessionState: 'ready',
      streamState: 'connecting',
      lastEventAt: '2026-07-01T06:00:00Z',
      now: '2026-07-01T06:00:10Z',
      staleAfterMs: 60_000,
      hasReplayCursor: true,
    }).phase).toBe('reconnecting');

    expect(deriveConnectionHealth({
      loadState: 'error',
      sessionState: 'idle',
      streamState: 'idle',
      lastEventAt: null,
      now: '2026-07-01T06:00:10Z',
      staleAfterMs: 60_000,
    }).phase).toBe('offline');
  });
});
