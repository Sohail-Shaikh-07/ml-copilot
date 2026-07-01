import type { MessagePayload, SessionDetail, SessionEventPayload, SessionSummary, ToolCallPayload } from './types';

export type LoadState = 'idle' | 'loading' | 'ready' | 'error';
export type StreamState = 'idle' | 'connecting' | 'streaming' | 'closed' | 'error';
export type ConnectionPhase = 'idle' | 'loading' | 'recovering' | 'reconnecting' | 'live' | 'stale' | 'closed' | 'offline';

const terminalEventTypes = new Set(['turn_complete', 'approval_required', 'error', 'interrupted']);

export interface EventReplayInput {
  current: SessionEventPayload[];
  incoming: SessionEventPayload[];
  limit?: number;
}

export interface EventReplayResult {
  events: SessionEventPayload[];
  lastSequence: number;
  duplicateCount: number;
  replayedCount: number;
  assistantDelta: string;
  terminalEventType: string | null;
}

export interface RecoverySnapshotInput {
  session: SessionDetail | null;
  messages: MessagePayload[];
  liveEvents: SessionEventPayload[];
  lastEventSequence: number;
  replayedEventCount: number;
  duplicateEventCount: number;
  recoveredAt: string | null;
}

export interface RecoverySnapshot {
  sessionId: string;
  sessionTitle: string;
  messageCount: number;
  toolCallCount: number;
  liveEventCount: number;
  persistedEventCount: number;
  lastEventSequence: number;
  replayedEventCount: number;
  duplicateEventCount: number;
  recoveredAt: string | null;
  status: 'recovering' | 'recovered' | 'empty';
}

export interface ConnectionHealthInput {
  loadState: LoadState;
  sessionState: LoadState;
  streamState: StreamState;
  lastEventAt: string | null;
  now?: string;
  staleAfterMs?: number;
  hasReplayCursor?: boolean;
}

export interface ConnectionHealth {
  phase: ConnectionPhase;
  label: string;
  tone: 'neutral' | 'success' | 'warning' | 'danger';
  lastEventAgeMs: number | null;
  canReconnect: boolean;
}

function timestamp(value: string) {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function sessionTitle(session: SessionSummary | SessionDetail) {
  return session.title?.trim() || 'Untitled session';
}

export function mergeSessionSummaries(current: SessionSummary[], incoming: SessionSummary | SessionSummary[]) {
  const nextById = new Map(current.map((session) => [session.id, session]));
  for (const session of Array.isArray(incoming) ? incoming : [incoming]) {
    nextById.set(session.id, session);
  }
  return [...nextById.values()].sort((left, right) => timestamp(right.updated_at) - timestamp(left.updated_at));
}

export function replaySessionEvents({ current, incoming, limit = 40 }: EventReplayInput): EventReplayResult {
  const byId = new Map(current.map((item) => [item.id, item]));
  const seenSequences = new Set(current.map((item) => item.sequence));
  let duplicateCount = 0;
  let replayedCount = 0;
  let assistantDelta = '';
  let terminalEventType: string | null = null;

  for (const item of incoming) {
    if (byId.has(item.id) || seenSequences.has(item.sequence)) {
      duplicateCount += 1;
      continue;
    }
    byId.set(item.id, item);
    seenSequences.add(item.sequence);
    replayedCount += 1;

    if (item.event_type === 'assistant_chunk' && typeof item.data.content === 'string') {
      assistantDelta += item.data.content;
    }
    if (terminalEventTypes.has(item.event_type)) {
      terminalEventType = item.event_type;
    }
  }

  const events = [...byId.values()]
    .sort((left, right) => left.sequence - right.sequence)
    .slice(-limit);
  const lastSequence = events.reduce((last, item) => Math.max(last, item.sequence), -1);

  return {
    events,
    lastSequence,
    duplicateCount,
    replayedCount,
    assistantDelta,
    terminalEventType,
  };
}

export function buildRecoverySnapshot(input: RecoverySnapshotInput): RecoverySnapshot | null {
  if (!input.session) return null;

  const toolCalls: ToolCallPayload[] = input.session.tool_calls ?? [];
  const hasRecoveredState = input.messages.length > 0 || toolCalls.length > 0 || input.liveEvents.length > 0;

  return {
    sessionId: input.session.id,
    sessionTitle: sessionTitle(input.session),
    messageCount: input.messages.length,
    toolCallCount: toolCalls.length,
    liveEventCount: input.liveEvents.length,
    persistedEventCount: input.session.event_count,
    lastEventSequence: input.lastEventSequence,
    replayedEventCount: input.replayedEventCount,
    duplicateEventCount: input.duplicateEventCount,
    recoveredAt: input.recoveredAt,
    status: input.recoveredAt ? 'recovered' : hasRecoveredState ? 'recovering' : 'empty',
  };
}

export function deriveConnectionHealth({
  loadState,
  sessionState,
  streamState,
  lastEventAt,
  now = new Date().toISOString(),
  staleAfterMs = 90_000,
  hasReplayCursor = false,
}: ConnectionHealthInput): ConnectionHealth {
  const nowMs = timestamp(now);
  const lastEventAgeMs = lastEventAt ? Math.max(0, nowMs - timestamp(lastEventAt)) : null;

  if (loadState === 'error') {
    return {
      phase: 'offline',
      label: 'backend offline',
      tone: 'danger',
      lastEventAgeMs,
      canReconnect: false,
    };
  }

  if (loadState === 'loading' || sessionState === 'loading') {
    return {
      phase: streamState === 'connecting' && hasReplayCursor ? 'reconnecting' : 'loading',
      label: streamState === 'connecting' && hasReplayCursor ? 'replaying stream' : 'loading session',
      tone: 'neutral',
      lastEventAgeMs,
      canReconnect: false,
    };
  }

  if (streamState === 'connecting') {
    return {
      phase: hasReplayCursor ? 'reconnecting' : 'recovering',
      label: hasReplayCursor ? 'reconnecting from replay cursor' : 'opening stream',
      tone: 'neutral',
      lastEventAgeMs,
      canReconnect: false,
    };
  }

  if (streamState === 'error') {
    return {
      phase: 'offline',
      label: 'stream disconnected',
      tone: 'danger',
      lastEventAgeMs,
      canReconnect: true,
    };
  }

  if (streamState === 'closed') {
    return {
      phase: 'closed',
      label: 'stream closed after turn',
      tone: 'success',
      lastEventAgeMs,
      canReconnect: hasReplayCursor,
    };
  }

  if (streamState === 'streaming' && lastEventAgeMs !== null && lastEventAgeMs > staleAfterMs) {
    return {
      phase: 'stale',
      label: 'stream heartbeat stale',
      tone: 'warning',
      lastEventAgeMs,
      canReconnect: true,
    };
  }

  if (streamState === 'streaming') {
    return {
      phase: 'live',
      label: 'stream live',
      tone: 'success',
      lastEventAgeMs,
      canReconnect: false,
    };
  }

  return {
    phase: 'idle',
    label: 'stream idle',
    tone: 'neutral',
    lastEventAgeMs,
    canReconnect: hasReplayCursor,
  };
}
