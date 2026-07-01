import { useMemo } from 'react';

import { buildPublishingDashboardSummary } from '../publishingDashboard';
import type { PublishingReportSummary, PublishState } from '../publishingDashboard';
import type { ToolCallPayload } from '../types';

interface PublishingPanelProps {
  toolCalls: ToolCallPayload[];
}

function stateLabel(state: PublishState) {
  if (state === 'local-only') return 'Local assets prepared';
  if (state === 'dry-run') return 'Publish requested';
  if (state === 'uploaded') return 'Uploaded to Hub';
  if (state === 'token-required') return 'Token required';
  return 'Publish failed';
}

function stateTone(state: PublishState) {
  if (state === 'local-only' || state === 'uploaded') return 'success';
  if (state === 'dry-run' || state === 'token-required') return 'warning';
  return 'danger';
}

function ProvenanceGroup({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div>
      <span>{label}</span>
      <div className="publishing-chip-row">
        {values.map((value) => <code key={value}>{value}</code>)}
      </div>
    </div>
  );
}

function ReportCard({ report }: { report: PublishingReportSummary }) {
  const hasProvenance = Boolean(
    report.provenance.datasets.length ||
    report.provenance.papers.length ||
    report.provenance.jobs.length ||
    report.provenance.evals.length,
  );

  return (
    <article className="publishing-report-card">
      <div className="runtime-detail-card-head">
        <div>
          <span>Publishing report</span>
          <h4>{report.repoId ?? 'Repository pending'}</h4>
        </div>
        <a href="#artifact-browser">Open publishing artifacts</a>
      </div>

      <div className="publishing-status-row">
        <span className={`status-chip ${stateTone(report.publishState)}`}>{stateLabel(report.publishState)}</span>
        {report.modelName ? <strong>{report.modelName}</strong> : null}
        {report.task ? <span>{report.task}</span> : null}
      </div>

      {report.warning ? <p className="artifact-browser-warning">{report.warning}</p> : null}
      {report.outputDir ? <p className="muted">Output directory: {report.outputDir}</p> : null}
      {report.recommendation ? <p>{report.recommendation}</p> : null}

      {report.artifacts.length ? (
        <div className="publishing-artifact-grid">
          {report.artifacts.map((artifact) => (
            <div className="runtime-artifact" key={artifact.path}>
              <span>{artifact.kind}</span>
              <strong>{artifact.fileName}</strong>
              <small>{artifact.path}</small>
            </div>
          ))}
        </div>
      ) : null}

      {hasProvenance ? (
        <div className="publishing-provenance">
          <strong>Provenance</strong>
          <ProvenanceGroup label="Datasets" values={report.provenance.datasets} />
          <ProvenanceGroup label="Papers" values={report.provenance.papers} />
          <ProvenanceGroup label="Jobs" values={report.provenance.jobs} />
          <ProvenanceGroup label="Evals" values={report.provenance.evals} />
        </div>
      ) : null}

      {report.previewBlocks.length ? (
        <div className="publishing-preview-stack">
          {report.previewBlocks.map((block) => (
            <div className="publishing-preview" key={block.title}>
              <span>{block.title}</span>
              <pre>{block.content}</pre>
            </div>
          ))}
        </div>
      ) : null}
    </article>
  );
}

export default function PublishingPanel({ toolCalls }: PublishingPanelProps) {
  const summary = useMemo(() => buildPublishingDashboardSummary(toolCalls), [toolCalls]);

  return (
    <section className="publishing-panel" id="publishing-panel" aria-label="Final report and publishing UI">
      <div className="runtime-detail-header">
        <div>
          <p className="panel-label">Publishing</p>
          <h3>Final report and publishing</h3>
          <p className="muted">Preview generated model cards, final reports, manifests, and Hub publishing state.</p>
        </div>
        <span className={`status-chip ${summary.needsTokenWarning ? 'warning' : 'neutral'}`}>
          {summary.reports.length} report{summary.reports.length === 1 ? '' : 's'}
        </span>
      </div>

      {!summary.latestReport ? (
        <p className="muted">Publishing artifacts will appear here after `publish_model_report` prepares local report assets.</p>
      ) : (
        <div className="publishing-report-stack">
          {summary.reports.map((report) => <ReportCard key={report.id} report={report} />)}
        </div>
      )}
    </section>
  );
}
