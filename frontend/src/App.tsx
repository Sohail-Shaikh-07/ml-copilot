import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  createSession,
  createSessionEventSource,
  fetchMessages,
  fetchSession,
  fetchSessions,
  getApiBaseLabel,
  sendChatMessage,
} from './api';
import ToolTracePanel from './components/ToolTracePanel';
import type {
  MessagePayload,
  PendingApprovalPayload,
  SessionDetail,
  SessionEventPayload,
  SessionSummary,
  ToolCallPayload,
} from './types';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';
type StreamState = 'idle' | 'connecting' | 'streaming' | 'closed' | 'error';

const seedMetadata = { source: 'frontend-shell' };
const terminalEventTypes = new Set(['turn_complete', 'approval_required', 'error', 'interrupted']);

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

function titleForSession(session: SessionSummary | SessionDetail) {
  return session.title?.trim() || 'Untitled session';
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function roleLabel(role: string) {
  if (role === 'assistant') return 'Assistant';
  if (role === 'user') return 'User';
  if (role === 'system') return 'System';
  return role.replace(/_/g, ' ');
}

function statusTone(status: string) {
  if (status === 'waiting_approval' || status === 'interrupted') return 'warning';
  if (status === 'error' || status === 'failed') return 'danger';
  if (status === 'idle' || status === 'completed' || status === 'passed') return 'success';
  return 'neutral';
}

function App() {
  const apiLabel = useMemo(() => getApiBaseLabel(), []);
  const eventSourceRef = useRef<EventSource | null>(null);
  const lastEventSequenceRef = useRef<number>(-1);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [messages, setMessages] = useState<MessagePayload[]>([]);
  const [liveEvents, setLiveEvents] = useState<SessionEventPayload[]>([]);
  const [liveAssistantText, setLiveAssistantText] = useState('');
  const [state, setState] = useState<LoadState>('idle');
  const [sessionState, setSessionState] = useState<LoadState>('idle');
  const [streamState, setStreamState] = useState<StreamState>('idle');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [sending, setSending] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftModel, setDraftModel] = useState('');
  const [draftPrompt, setDraftPrompt] = useState('');

  useEffect(() => {
    void refreshSessions();
  }, []);

  useEffect(() => {
    if (!selectedSessionId) {
      setActiveSession(null);
      setMessages([]);
      setLiveEvents([]);
      setLiveAssistantText('');
      setStreamState('idle');
      closeEventStream();
      return;
    }

    lastEventSequenceRef.current = -1;
    setLiveEvents([]);
    setLiveAssistantText('');
    void refreshSession(selectedSessionId);
    connectEventStream(selectedSessionId, { replay: true });

    return () => closeEventStream();
  }, [selectedSessionId]);

  function closeEventStream() {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
  }

  function connectEventStream(sessionId: string, options: { replay: boolean }) {
    closeEventStream();
    setStreamState('connecting');

    const after = options.replay ? lastEventSequenceRef.current : undefined;
    eventSourceRef.current = createSessionEventSource(sessionId, {
      after,
      onEvent: (event) => {
        lastEventSequenceRef.current = Math.max(lastEventSequenceRef.current, event.sequence);
        setStreamState('streaming');
        setLiveEvents((current) => [...current.slice(-39), event]);

        if (event.event_type === 'assistant_chunk') {
          const content = event.data.content;
          if (typeof content === 'string') {
            setLiveAssistantText((current) => current + content);
          }
        }

        if (terminalEventTypes.has(event.event_type)) {
          closeEventStream();
          setStreamState('closed');
          void refreshSession(sessionId);
          void refreshSessions();
        }
      },
      onError: () => {
        eventSourceRef.current = null;
        setStreamState('error');
      },
    });
  }

  async function refreshSessions() {
    setState('loading');
    setError(null);

    try {
      const data = await fetchSessions();
      setSessions(data);
      setState('ready');
      setSelectedSessionId((current) => {
        if (current && data.some((session) => session.id === current)) {
          return current;
        }
        return data[0]?.id ?? null;
      });
      if (data.length === 0) {
        setNotice('Create a session to start filling the shell.');
      } else {
        setNotice(null);
      }
    } catch (err) {
      setState('error');
      setSessions([]);
      setSelectedSessionId(null);
      setActiveSession(null);
      setMessages([]);
      setError(err instanceof Error ? err.message : 'Unable to load sessions.');
      setNotice('The backend is offline or the API base URL is not reachable.');
    }
  }

  async function refreshSession(sessionId: string) {
    setSessionState('loading');
    try {
      const [detail, transcript] = await Promise.all([
        fetchSession(sessionId),
        fetchMessages(sessionId),
      ]);
      setActiveSession(detail);
      setMessages(transcript);
      setSessionState('ready');
    } catch (err) {
      setActiveSession(null);
      setMessages([]);
      setSessionState('error');
      setError(err instanceof Error ? err.message : 'Unable to load session details.');
    }
  }

  async function handleCreateSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError(null);

    try {
      const created = await createSession({
        title: draftTitle.trim() || null,
        model: draftModel.trim() || null,
        metadata: seedMetadata,
      });
      setSessions((current) => [created, ...current.filter((session) => session.id !== created.id)]);
      setSelectedSessionId(created.id);
      setDraftTitle('');
      setDraftModel('');
      setNotice('Session created. Send a prompt to start streaming agent activity.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create session.');
    } finally {
      setCreating(false);
    }
  }

  async function handleSendPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSessionId || !draftPrompt.trim() || sending) {
      return;
    }

    const prompt = draftPrompt.trim();
    setSending(true);
    setError(null);
    setNotice(null);
    setDraftPrompt('');
    setLiveAssistantText('');
    setLiveEvents([]);
    connectEventStream(selectedSessionId, { replay: false });

    try {
      const response = await sendChatMessage(selectedSessionId, { message: prompt });
      setActiveSession(response.session);
      setMessages(response.messages);
      setLiveAssistantText('');
      setSessions((current) =>
        current.map((session) => (session.id === response.session.id ? response.session : session)),
      );

      if (response.result.status === 'approval_required') {
        setNotice('The agent is waiting for approval. Approval controls are planned for the next dedicated task.');
      } else if (response.result.status === 'interrupted') {
        setNotice('The turn was interrupted.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send prompt.');
      closeEventStream();
      setStreamState('error');
    } finally {
      setSending(false);
      void refreshSession(selectedSessionId);
      void refreshSessions();
    }
  }

  const sessionStats = activeSession
    ? [
        { label: 'Messages', value: activeSession.message_count },
        { label: 'Events', value: activeSession.event_count },
        { label: 'Approvals', value: activeSession.pending_approval_count },
      ]
    : [];

  const pendingApprovals: PendingApprovalPayload[] = activeSession?.pending_approvals ?? [];
  const toolCalls: ToolCallPayload[] = activeSession?.tool_calls ?? [];

  return (
    <div className="app-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <header className="topbar">
        <div>
          <p className="eyebrow">ML Copilot / Phase 3</p>
          <h1>React Vite frontend shell</h1>
        </div>
        <div className="status-stack">
          <span className={`status-pill ${state === 'ready' ? 'success' : state === 'error' ? 'danger' : 'neutral'}`}>
            {state === 'ready' ? 'backend connected' : state === 'error' ? 'backend offline' : 'loading sessions'}
          </span>
          <span className="status-chip">{apiLabel}</span>
        </div>
      </header>

      {notice ? <div className="banner">{notice}</div> : null}
      {error ? <div className="banner banner-danger">{error}</div> : null}

      <main className="workspace">
        <aside className="panel sidebar">
          <div className="panel-header">
            <div>
              <p className="panel-label">Sessions</p>
              <h2>{sessions.length} in play</h2>
            </div>
            <button className="ghost-button" type="button" onClick={() => void refreshSessions()}>
              Refresh
            </button>
          </div>

          <form className="composer-card" onSubmit={handleCreateSession}>
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
                    onClick={() => setSelectedSessionId(session.id)}
                  >
                    <div className="session-card-top">
                      <strong>{titleForSession(session)}</strong>
                      <span className={`status-pill ${statusTone(session.status)}`}>{session.status}</span>
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
        </aside>

        <section className="panel transcript">
          <div className="panel-header">
            <div>
              <p className="panel-label">Conversation</p>
              <h2>{activeSession ? titleForSession(activeSession) : 'Waiting for a session'}</h2>
            </div>
            {activeSession ? <span className={`status-chip ${statusTone(activeSession.status)}`}>{activeSession.status}</span> : null}
          </div>

          {selectedSessionId && activeSession ? (
            <>
              <div className="stat-row">
                {sessionStats.map((stat) => (
                  <article className="stat-card" key={stat.label}>
                    <span>{stat.label}</span>
                    <strong>{stat.value}</strong>
                  </article>
                ))}
              </div>

              <div className="message-stream">
                {sessionState === 'loading' ? (
                  <div className="empty-state">
                    <strong>Loading transcript...</strong>
                  </div>
                ) : messages.length === 0 ? (
                  <div className="empty-state">
                    <strong>No transcript yet.</strong>
                    <p>The shell is wired to the API, so the first run can fill this panel with messages.</p>
                  </div>
                ) : (
                  messages.map((message) => (
                    <article key={message.id} className={`message ${message.role}`}>
                      <div className="message-meta">
                        <span>{roleLabel(message.role)}</span>
                        <span>{formatTimestamp(message.created_at)}</span>
                      </div>
                      <p>{message.content}</p>
                    </article>
                  ))
                )}
                {liveAssistantText ? (
                  <article className="message assistant live">
                    <div className="message-meta">
                      <span>Assistant streaming</span>
                      <span>live</span>
                    </div>
                    <p>{liveAssistantText}</p>
                  </article>
                ) : null}
              </div>

              <form className="composer-shell" onSubmit={handleSendPrompt}>
                <label>
                  Prompt
                  <textarea
                    placeholder="Ask ML Copilot to inspect a repo, explain a failure, or plan the next experiment."
                    rows={4}
                    value={draftPrompt}
                    onChange={(event) => setDraftPrompt(event.target.value)}
                    disabled={sending}
                  />
                </label>
                <div className="composer-actions">
                  <span className={`status-chip ${streamState === 'error' ? 'danger' : streamState === 'streaming' ? 'success' : 'neutral'}`}>
                    stream: {streamState}
                  </span>
                  <button className="primary-button" type="submit" disabled={sending || !draftPrompt.trim()}>
                    {sending ? 'Sending...' : 'Send prompt'}
                  </button>
                </div>
              </form>
            </>
          ) : (
            <div className="empty-state hero">
              <strong>Pick or create a session to start the shell.</strong>
              <p>
                This view is wired to the live sessions API and is ready to become the full chat surface in the next slice.
              </p>
            </div>
          )}
        </section>

        <aside className="panel inspector">
          <div className="panel-header">
            <div>
              <p className="panel-label">Inspector</p>
              <h2>Session details</h2>
            </div>
          </div>

          <div className="inspector-stack">
            <section className="info-card">
              <h3>Backend state</h3>
              <p>{apiLabel}</p>
              <p className="muted">
                The shell falls back to a clean empty state if the backend is not available.
              </p>
            </section>

            <section className="info-card">
              <h3>Pending approvals</h3>
              {pendingApprovals.length === 0 ? (
                <p className="muted">None right now.</p>
              ) : (
                pendingApprovals.map((approval) => (
                  <div key={approval.approval_id} className="mini-row">
                    <strong>{approval.tool_name}</strong>
                    <span>{shortId(approval.approval_id)}</span>
                  </div>
                ))
              )}
            </section>

            <ToolTracePanel liveEvents={liveEvents} pendingApprovals={pendingApprovals} toolCalls={toolCalls} />
          </div>
        </aside>
      </main>
    </div>
  );
}

export default App;
