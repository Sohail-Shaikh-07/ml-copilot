import type { FormEvent } from 'react';
import type { MessagePayload, SessionDetail, SessionSummary } from '../types';

interface SessionSidebarProps {
  activeSession: SessionDetail | null;
  creating: boolean;
  draftModel: string;
  draftTitle: string;
  messages: MessagePayload[];
  onCreateSession: (event: FormEvent<HTMLFormElement>) => void;
  onRefreshSessions: () => void;
  onSelectSession: (sessionId: string) => void;
  selectedSessionId: string | null;
  sessions: SessionSummary[];
  setDraftModel: (value: string) => void;
  setDraftTitle: (value: string) => void;
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);
}

function formatPreview(message: MessagePayload) {
  const trimmed = message.content.trim().replace(/\s+/g, ' ');
  if (trimmed.length <= 96) {
    return trimmed;
  }
  return `${trimmed.slice(0, 93)}...`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value);
}

function roleLabel(role: string) {
  if (role === 'assistant') return 'Assistant';
  if (role === 'user') return 'User';
  if (role === 'system') return 'System';
  return role.replace(/_/g, ' ');
}

export default function SessionSidebar({
  activeSession,
  creating,
  draftModel,
  draftTitle,
  messages,
  onCreateSession,
  onRefreshSessions,
  onSelectSession,
  selectedSessionId,
  sessions,
  setDraftModel,
  setDraftTitle,
}: SessionSidebarProps) {
  const isCurrentSession = Boolean(activeSession && activeSession.id === selectedSessionId);
  const currentSession = isCurrentSession ? activeSession : null;
  const recentMessages = isCurrentSession ? [...messages].slice(-3) : [];

  return (
    <div className="session-sidebar">
      <div className="panel-header">
        <div>
          <p className="panel-label">Sessions</p>
          <h2>{sessions.length} in play</h2>
        </div>
        <button className="ghost-button" type="button" onClick={onRefreshSessions}>
          Refresh
        </button>
      </div>

      <form className="composer-card" onSubmit={onCreateSession}>
        <label>
          Session title
          <input
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            placeholder="Plan a dataset audit"
          />
        </label>
        <label>
          Model
          <input
            value={draftModel}
            onChange={(event) => setDraftModel(event.target.value)}
            placeholder="gpt-5.4"
          />
        </label>
        <button className="primary-button" type="submit" disabled={creating}>
          {creating ? 'Creating...' : 'Create session'}
        </button>
      </form>

      <div className="session-list">
        {sessions.length === 0 ? (
          <div className="empty-state compact">
            <strong>No sessions yet.</strong>
            <p>Once the backend is running, this rail will show live session history.</p>
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.id === selectedSessionId;
            return (
              <button
                key={session.id}
                type="button"
                className={`session-card ${isActive ? 'active' : ''}`}
                onClick={() => onSelectSession(session.id)}
              >
                <div className="session-card-top">
                  <strong>{session.title?.trim() || 'Untitled session'}</strong>
                  <span className={`status-pill ${session.status === 'error' ? 'danger' : session.status === 'waiting_approval' || session.status === 'interrupted' ? 'warning' : 'neutral'}`}>
                    {session.status}
                  </span>
                </div>
                <p>{session.model}</p>
                <div className="session-card-meta">
                  <span>{session.message_count} messages</span>
                  <span>{session.pending_approval_count} approvals</span>
                  <span>{shortId(session.id)}</span>
                </div>
              </button>
            );
          })
        )}
      </div>

      <section className="session-history-card">
        <div className="panel-header compact">
          <div>
            <p className="panel-label">History</p>
            <h2>{activeSession ? 'Selected session' : 'No session selected'}</h2>
          </div>
        </div>

        {currentSession ? (
          <div className="session-history-stack">
            <div className="session-history-summary">
              <div className="mini-row">
                <strong>{currentSession.title?.trim() || 'Untitled session'}</strong>
                <span>{shortId(currentSession.id)}</span>
              </div>
              <p>{currentSession.model}</p>
              <div className="session-card-meta">
                <span>{currentSession.message_count} messages</span>
                <span>{currentSession.event_count} events</span>
                <span>{currentSession.metrics.turn_count} turns</span>
                <span>{formatCompact(currentSession.metrics.total_tokens)} tokens</span>
                <span>{formatCurrency(currentSession.metrics.estimated_cost_usd)}</span>
                <span>Updated {formatTimestamp(currentSession.updated_at)}</span>
              </div>
            </div>

            <div className="history-items">
              {recentMessages.length === 0 ? (
                <p className="muted">This session has no persisted transcript yet.</p>
              ) : (
                recentMessages.map((message) => (
                  <article key={message.id} className="history-item">
                    <div className="mini-row">
                      <strong>{roleLabel(message.role)}</strong>
                      <span>{formatTimestamp(message.created_at)}</span>
                    </div>
                    <p>{formatPreview(message)}</p>
                  </article>
                ))
              )}
            </div>
          </div>
        ) : (
          <p className="muted">Select a prior session to reopen its persisted conversation and event history.</p>
        )}
      </section>
    </div>
  );
}
