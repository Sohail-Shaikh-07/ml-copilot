import type { PendingApprovalPayload, SessionEventPayload, ToolCallPayload } from '../types';

interface ToolTracePanelProps {
  liveEvents: SessionEventPayload[];
  pendingApprovals: PendingApprovalPayload[];
  toolCalls: ToolCallPayload[];
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `[${value.map(formatValue).join(', ')}]`;
  if (typeof value === 'object') return '{...}';
  return String(value);
}

function formatArgs(args: Record<string, unknown>) {
  const entries = Object.entries(args);
  if (entries.length === 0) return 'No arguments';
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(' | ');
}

function formatDuration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt || !finishedAt) return null;
  const start = new Date(startedAt);
  const finish = new Date(finishedAt);
  if (Number.isNaN(start.getTime()) || Number.isNaN(finish.getTime())) return null;
  const seconds = Math.max(0, Math.round((finish.getTime() - start.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function formatEventLabel(eventType: string) {
  return eventType
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function eventSummary(event: SessionEventPayload) {
  const content = event.data.content;
  if (typeof content === 'string' && content.trim()) return content;

  const output = event.data.output;
  if (typeof output === 'string' && output.trim()) return output;

  const error = event.data.error;
  if (typeof error === 'string' && error.trim()) return error;

  const tool = event.data.tool;
  if (typeof tool === 'string' && tool.trim()) return tool;

  return JSON.stringify(event.data);
}

function firstNonEmptyText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }
  return null;
}

function toneForStatus(status: string) {
  if (status === 'success' || status === 'completed' || status === 'output-available') return 'success';
  if (status === 'error' || status === 'failed' || status === 'output-error') return 'danger';
  if (status === 'approval-required' || status === 'approval-requested') return 'warning';
  return 'neutral';
}

function groupToolCalls(toolCalls: ToolCallPayload[]) {
  const sorted = [...toolCalls].sort((a, b) => {
    const aTime = a.started_at ?? a.finished_at ?? '';
    const bTime = b.started_at ?? b.finished_at ?? '';
    return aTime.localeCompare(bTime) || a.id.localeCompare(b.id);
  });

  const groups: Array<{ turnId: string; calls: ToolCallPayload[] }> = [];
  const lookup = new Map<string, ToolCallPayload[]>();

  for (const call of sorted) {
    const current = lookup.get(call.turn_id);
    if (current) {
      current.push(call);
      continue;
    }

    const next = [call];
    lookup.set(call.turn_id, next);
    groups.push({ turnId: call.turn_id, calls: next });
  }

  return groups;
}

export default function ToolTracePanel({ liveEvents, pendingApprovals, toolCalls }: ToolTracePanelProps) {
  const grouped = groupToolCalls(toolCalls);
  const recentEvents = liveEvents.slice(-6);

  return (
    <div className="tool-trace-panel">
      <section className="tool-trace-card">
        <div className="tool-trace-header">
          <div>
            <p className="panel-label">Tool trace</p>
            <h3>
              {toolCalls.length} calls across {grouped.length} turns
            </h3>
          </div>
          <span className="status-chip neutral">{recentEvents.length} live events</span>
        </div>

        <div className="tool-trace-live">
          <div className="tool-trace-subheader">
            <strong>Recent events</strong>
            <span>{recentEvents.length ? 'Latest SSE activity' : 'Waiting for events'}</span>
          </div>

          {recentEvents.length === 0 ? (
            <p className="muted">SSE events will appear here while the active session runs.</p>
          ) : (
            <div className="tool-trace-events">
              {recentEvents.map((event) => (
                <article key={event.id} className="tool-trace-event">
                  <div className="tool-trace-event-meta">
                    <span>{formatEventLabel(event.event_type)}</span>
                    <span>#{event.sequence}</span>
                  </div>
                  <p>{eventSummary(event)}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="tool-trace-card">
        <div className="tool-trace-subheader">
          <strong>Grouped calls</strong>
          <span>{pendingApprovals.length} approvals pending</span>
        </div>

        {grouped.length === 0 ? (
          <p className="muted">Tool calls will appear here when the agent starts using tools.</p>
        ) : (
          <div className="tool-trace-groups">
            {grouped.map((group) => (
              <article key={group.turnId} className="tool-trace-group">
                <div className="tool-trace-group-head">
                  <div>
                    <span className="tool-trace-kicker">Turn</span>
                    <h4>{shortId(group.turnId)}</h4>
                  </div>
                  <span className="status-chip neutral">
                    {group.calls.length} call{group.calls.length === 1 ? '' : 's'}
                  </span>
                </div>

                <div className="tool-trace-call-list">
                  {group.calls.map((call) => {
                    const duration = formatDuration(call.started_at, call.finished_at);
                    const summary = firstNonEmptyText(call.output, call.error) ?? 'Waiting for output';
                    return (
                      <div key={call.id} className="tool-trace-call">
                        <div className="tool-trace-call-head">
                          <div>
                            <strong>{call.tool_name}</strong>
                            <p>{formatArgs(call.arguments)}</p>
                          </div>
                          <span className={`status-chip ${toneForStatus(call.status)}`}>{call.status}</span>
                        </div>

                        <div className="tool-trace-call-meta">
                          <span>{call.requires_approval ? 'approval required' : 'no approval required'}</span>
                          {duration ? <span>{duration}</span> : null}
                          {call.approval_id ? <span>approval {shortId(call.approval_id)}</span> : null}
                        </div>

                        <div className="tool-trace-output">
                          <span>{call.success === false ? 'Error' : 'Output'}</span>
                          <p>{summary}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
