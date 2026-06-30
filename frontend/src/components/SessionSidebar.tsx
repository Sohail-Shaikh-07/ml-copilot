import { useState, type FormEvent } from 'react';
import { uploadDataset } from '../api';
import {
  EFFORT_OPTIONS,
  OPERATING_MODE_OPTIONS,
  PROVIDER_OPTIONS,
  providerLabel,
  readStoredAgentControls,
  suggestedModelForProvider,
  suggestedModelLabelForProvider,
  type OperatingMode,
  type ProviderId,
  type ReasoningEffort,
  type SessionControlState,
} from '../sessionControls';
import type { MessagePayload, SessionDetail, SessionSummary } from '../types';

interface SessionSidebarProps {
  activeSession: SessionDetail | null;
  creating: boolean;
  draftControls: SessionControlState;
  draftHfToken: string;
  draftModel: string;
  draftTitle: string;
  messages: MessagePayload[];
  onCreateSession: (event: FormEvent<HTMLFormElement>) => void;
  onRefreshSessions: () => void;
  onSelectSession: (sessionId: string) => void;
  selectedSessionId: string | null;
  sessions: SessionSummary[];
  setDraftControls: (value: SessionControlState) => void;
  setDraftHfToken: (value: string) => void;
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
  draftControls,
  draftHfToken,
  draftModel,
  draftTitle,
  messages,
  onCreateSession,
  onRefreshSessions,
  onSelectSession,
  selectedSessionId,
  sessions,
  setDraftControls,
  setDraftHfToken,
  setDraftModel,
  setDraftTitle,
}: SessionSidebarProps) {
  const [datasetFile, setDatasetFile] = useState<File | null>(null);
  const [datasetStatus, setDatasetStatus] = useState('');
  const [uploadingDataset, setUploadingDataset] = useState(false);
  const isCurrentSession = Boolean(activeSession && activeSession.id === selectedSessionId);
  const currentSession = isCurrentSession ? activeSession : null;
  const recentMessages = isCurrentSession ? [...messages].slice(-3) : [];
  const selectedControls = currentSession ? readStoredAgentControls(currentSession.metadata) : null;

  function updateDraftControls(patch: Partial<SessionControlState>) {
    setDraftControls({ ...draftControls, ...patch });
  }

  async function handleDatasetUpload() {
    if (!datasetFile) return;
    setUploadingDataset(true);
    setDatasetStatus('');
    try {
      const uploaded = await uploadDataset(datasetFile);
      setDatasetStatus(`Ready at ${uploaded.path}`);
      setDatasetFile(null);
    } catch (error) {
      setDatasetStatus(error instanceof Error ? error.message : 'Dataset upload failed.');
    } finally {
      setUploadingDataset(false);
    }
  }

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
        <section className="model-control-card" aria-label="Model and provider controls">
          <div>
            <p className="panel-label">Agent controls</p>
            <strong>Model and provider</strong>
            <p className="hint">
              Saved with the session so runs reopen with predictable provider, effort, and budget preferences.
            </p>
          </div>
          <div className="model-control-grid">
            <label>
              Provider
              <select
                value={draftControls.provider}
                onChange={(event) => updateDraftControls({ provider: event.target.value as ProviderId })}
              >
                {PROVIDER_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <input
                value={draftModel}
                onChange={(event) => setDraftModel(event.target.value)}
                placeholder={suggestedModelForProvider(draftControls.provider)}
              />
            </label>
          </div>
          <div className="model-preset-row">
            <button
              className="ghost-button"
              type="button"
              onClick={() => setDraftModel(suggestedModelForProvider(draftControls.provider))}
            >
              Use {suggestedModelLabelForProvider(draftControls.provider)}
            </button>
            <span className="hint">Custom model IDs stay editable for OpenAI-compatible and routed providers.</span>
          </div>
          <div className="model-control-grid">
            <label>
              Reasoning effort
              <select
                value={draftControls.reasoningEffort}
                onChange={(event) => updateDraftControls({ reasoningEffort: event.target.value as ReasoningEffort })}
              >
                {EFFORT_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Operating mode
              <select
                value={draftControls.operatingMode}
                onChange={(event) => updateDraftControls({ operatingMode: event.target.value as OperatingMode })}
              >
                {OPERATING_MODE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Temperature
              <input
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={draftControls.temperature}
                onChange={(event) => updateDraftControls({ temperature: event.target.value })}
                placeholder="0.2"
              />
            </label>
            <label>
              Max turns
              <input
                type="number"
                min="1"
                step="1"
                value={draftControls.maxTurns}
                onChange={(event) => updateDraftControls({ maxTurns: event.target.value })}
                placeholder="120"
              />
            </label>
            <label>
              Spend cap
              <input
                type="number"
                min="0"
                step="0.01"
                value={draftControls.spendCapUsd}
                onChange={(event) => updateDraftControls({ spendCapUsd: event.target.value })}
                placeholder="3.50"
              />
            </label>
          </div>
          <p className="hint">
            Unsupported backend controls are treated as transparent preferences in this slice, not hidden enforcement.
          </p>
        </section>
        <label>
          Hugging Face token
          <input
            type="password"
            value={draftHfToken}
            onChange={(event) => setDraftHfToken(event.target.value)}
            placeholder="hf_xxx"
          />
          <span className="hint">Kept in memory only and sent with requests for this browser session.</span>
        </label>
        <button className="primary-button" type="submit" disabled={creating}>
          {creating ? 'Creating...' : 'Create session'}
        </button>
      </form>

      <section className="dataset-upload-card">
        <div>
          <p className="panel-label">Bring your own data</p>
          <strong>Upload a dataset</strong>
        </div>
        <input
          type="file"
          accept=".csv,.tsv,.json,.jsonl,.parquet"
          onChange={(event) => setDatasetFile(event.target.files?.[0] ?? null)}
        />
        <button
          className="ghost-button"
          type="button"
          disabled={!datasetFile || uploadingDataset}
          onClick={handleDatasetUpload}
        >
          {uploadingDataset ? 'Uploading...' : 'Upload and preview'}
        </button>
        {datasetStatus ? <p className="hint">{datasetStatus}</p> : null}
      </section>

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
              {selectedControls ? (
                <div className="session-control-summary" data-testid="selected-session-controls">
                  <span>Provider: {providerLabel(selectedControls.provider)}</span>
                  <span>Effort: {selectedControls.reasoning_effort}</span>
                  <span>Mode: {selectedControls.operating_mode}</span>
                  {selectedControls.spend_cap_usd !== null ? (
                    <span>Spend cap: {formatCurrency(selectedControls.spend_cap_usd)}</span>
                  ) : null}
                </div>
              ) : null}
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
