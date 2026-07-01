import { buildWorkbenchFlowSummary } from '../workbenchFlow';
import type { MessagePayload, SessionDetail, ToolCallPayload } from '../types';
import type { RecoverySnapshot } from '../workbenchState';

interface WorkbenchFlowPanelProps {
  session: SessionDetail | null;
  messages: MessagePayload[];
  toolCalls: ToolCallPayload[];
  recovery: RecoverySnapshot | null;
}

function statusTone(status: string) {
  if (status === 'complete') return 'success';
  if (status === 'active') return 'warning';
  return 'neutral';
}

export default function WorkbenchFlowPanel({ session, messages, toolCalls, recovery }: WorkbenchFlowPanelProps) {
  const summary = buildWorkbenchFlowSummary({ session, messages, toolCalls, recovery });

  return (
    <section className="workbench-flow-panel" aria-label="Autonomous workflow guide">
      <div className="runtime-detail-header">
        <div>
          <p className="panel-label">Workflow</p>
          <h3>Autonomous workflow guide</h3>
          <p className="muted">A single path through setup, data, research, runtime, evals, reports, and publishing.</p>
        </div>
        <div className="workbench-flow-summary">
          <span className="status-chip success">
            {summary.completedCount} / {summary.totalCount} stages complete
          </span>
          <span className="status-chip neutral">{summary.resumeLabel}</span>
        </div>
      </div>

      <div className="workbench-stage-grid">
        {summary.stages.map((stage, index) => (
          <article className={`workbench-stage-card ${stage.status}`} key={stage.id}>
            <div className="workbench-stage-head">
              <span className={`status-chip ${statusTone(stage.status)}`}>{stage.status}</span>
              <span className="workbench-stage-number">{index + 1}</span>
            </div>
            <h4>{stage.title}</h4>
            <p>{stage.summary}</p>
            {stage.evidence.length ? (
              <div className="workbench-stage-evidence">
                {stage.evidence.slice(0, 2).map((item) => <code key={item}>{item}</code>)}
              </div>
            ) : null}
            <a href={stage.href}>Open {stage.title}</a>
          </article>
        ))}
      </div>

      <div className="workbench-walkthrough">
        <h4>End-to-end walkthrough</h4>
        <ol aria-label="End-to-end walkthrough">
          {summary.walkthrough.map((step) => <li key={step}>{step}</li>)}
        </ol>
      </div>
    </section>
  );
}
