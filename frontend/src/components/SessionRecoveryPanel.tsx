import type { ConnectionHealth, RecoverySnapshot } from '../workbenchState';

interface SessionRecoveryPanelProps {
  health: ConnectionHealth;
  snapshot: RecoverySnapshot | null;
  onReconnect: () => void;
}

function ageLabel(ms: number | null) {
  if (ms === null) return 'no live event yet';
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) return `last event ${minutes}m ${seconds}s ago`;
  return `last event ${seconds}s ago`;
}

export default function SessionRecoveryPanel({ health, snapshot, onReconnect }: SessionRecoveryPanelProps) {
  return (
    <section className="session-recovery-panel" aria-label="Session recovery">
      <div className="runtime-detail-header">
        <div>
          <p className="panel-label">Recovery</p>
          <h3>Session recovery</h3>
          <p className="muted">Typed replay state for refreshes, reconnects, and restored workbench panels.</p>
        </div>
        <span className={`status-chip ${health.tone}`}>{health.label}</span>
      </div>

      {snapshot ? (
        <>
          <div className="recovery-summary">
            <div>
              <span>Session</span>
              <strong>{snapshot.sessionTitle}</strong>
            </div>
            <div>
              <span>Transcript</span>
              <strong>{snapshot.messageCount} messages</strong>
            </div>
            <div>
              <span>Tools</span>
              <strong>{snapshot.toolCallCount} tool calls</strong>
            </div>
            <div>
              <span>Live buffer</span>
              <strong>{snapshot.liveEventCount} live events</strong>
            </div>
          </div>

          <div className="recovery-meta">
            <span>sequence {snapshot.lastEventSequence}</span>
            <span>{snapshot.replayedEventCount} replayed</span>
            <span>{snapshot.duplicateEventCount} duplicate skipped</span>
            <span>{ageLabel(health.lastEventAgeMs)}</span>
          </div>

          {health.canReconnect ? (
            <button className="ghost-button" type="button" onClick={onReconnect}>
              Reconnect with replay
            </button>
          ) : null}
        </>
      ) : (
        <p className="muted">No session recovery snapshot yet.</p>
      )}
    </section>
  );
}
