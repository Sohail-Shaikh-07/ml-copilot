import { useMemo, useState } from 'react';

import { buildResearchTrailSummary } from '../researchTrail';
import type { ResearchStep, ResearchStepKind } from '../researchTrail';
import type { ToolCallPayload } from '../types';

interface ResearchTrailPanelProps {
  toolCalls: ToolCallPayload[];
}

function kindLabel(kind: ResearchStepKind) {
  if (kind === 'paper') return 'Paper';
  if (kind === 'citation') return 'Citation graph';
  if (kind === 'reading') return 'Paper reading';
  if (kind === 'recipe') return 'Recipe';
  if (kind === 'model') return 'Model';
  if (kind === 'dataset') return 'Dataset';
  if (kind === 'docs') return 'Docs';
  if (kind === 'repository') return 'Repository';
  return 'Decision';
}

function kindTone(kind: ResearchStepKind) {
  if (kind === 'recipe' || kind === 'decision') return 'warning';
  if (kind === 'paper' || kind === 'model' || kind === 'dataset') return 'success';
  return 'neutral';
}

function ResearchStepCard({ step, index }: { step: ResearchStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const showDetails = expanded && (step.evidence.length || step.confidence || step.limitations || step.decision);

  return (
    <article className="research-step-card" data-testid={`research-step-${step.kind}`}>
      <div className="research-step-marker">{index + 1}</div>
      <div className="research-step-body">
        <div className="research-step-head">
          <div>
            <span className={`status-chip ${kindTone(step.kind)}`}>{kindLabel(step.kind)}</span>
            <h4>{step.title}</h4>
            {step.sourceId ? <code>{step.sourceId}</code> : null}
          </div>
          {step.links.length ? (
            <div className="research-step-links">
              {step.links.slice(0, 3).map((link, linkIndex) => (
                <a href={link} key={link} rel="noopener noreferrer" target="_blank">
                  Open source {linkIndex + 1}
                </a>
              ))}
            </div>
          ) : null}
        </div>

        <p>{step.summary}</p>

        <button
          className="ghost-button research-step-toggle"
          type="button"
          aria-label={`${expanded ? 'Hide' : 'Show'} details for ${step.title}`}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? 'Hide details' : 'Show details'}
        </button>

        {showDetails ? (
          <div className="research-step-details">
            {step.confidence ? (
              <div>
                <span>Confidence</span>
                <p>{step.confidence}</p>
              </div>
            ) : null}
            {step.limitations ? (
              <div>
                <span>Limitations</span>
                <p>{step.limitations}</p>
              </div>
            ) : null}
            {step.decision ? (
              <div>
                <span>Decision</span>
                <p>{step.decision}</p>
              </div>
            ) : null}
            {step.evidence.map((item, evidenceIndex) => (
              <blockquote key={`${item.label}-${evidenceIndex}`}>
                <span>{item.label}</span>
                {item.snippet}
              </blockquote>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

export default function ResearchTrailPanel({ toolCalls }: ResearchTrailPanelProps) {
  const summary = useMemo(() => buildResearchTrailSummary(toolCalls), [toolCalls]);

  return (
    <section className="research-trail-panel" id="research-trail" aria-label="Research evidence trail">
      <div className="runtime-detail-header">
        <div>
          <p className="panel-label">Research</p>
          <h3>Research evidence trail</h3>
          <p className="muted">Paper, dataset, model, documentation, and repository evidence recovered from persisted tool calls.</p>
        </div>
        <div className="research-trail-counts">
          <span className="status-chip neutral">{summary.steps.length} step{summary.steps.length === 1 ? '' : 's'}</span>
          <span className="status-chip neutral">{summary.evidenceCount} evidence</span>
          <span className="status-chip neutral">{summary.decisionCount} decisions</span>
        </div>
      </div>

      {!summary.steps.length ? (
        <p className="muted">Research steps will appear here after paper, docs, Hub, dataset, or repository tools run.</p>
      ) : (
        <div className="research-timeline">
          {summary.steps.map((step, index) => <ResearchStepCard index={index} key={step.id} step={step} />)}
        </div>
      )}
    </section>
  );
}
