import { useMemo } from 'react';

import { buildEvalDashboardSummary } from '../evalDashboard';
import type { EvalGateStatus, EvalSuiteSummary } from '../evalDashboard';
import type { ToolCallPayload } from '../types';

interface EvalDashboardPanelProps {
  toolCalls: ToolCallPayload[];
}

function formatScore(score: number | null) {
  if (score === null) return 'No score';
  return `${Math.round(score * 100)}% score`;
}

function formatRuntime(seconds: number | null) {
  if (seconds === null) return 'runtime unknown';
  return `${seconds}s runtime`;
}

function gateLabel(status: EvalGateStatus) {
  if (status === 'healthy') return 'Release gate healthy';
  if (status === 'blocked') return 'Release gate blocked';
  return 'Release gate unknown';
}

function gateTone(status: EvalGateStatus) {
  if (status === 'healthy') return 'success';
  if (status === 'blocked') return 'danger';
  return 'neutral';
}

function fixtureTone(status: string) {
  if (status === 'passed') return 'success';
  if (status === 'failed' || status === 'error') return 'danger';
  return 'neutral';
}

function SuiteCard({ suite }: { suite: EvalSuiteSummary }) {
  return (
    <article className="eval-dashboard-suite">
      <div className="runtime-detail-card-head">
        <div>
          <span>Eval suite</span>
          <h4>{suite.status}</h4>
        </div>
        <a href="#artifact-browser">Open eval artifacts</a>
      </div>

      <div className="eval-dashboard-metrics">
        <span>{formatScore(suite.averageScore)}</span>
        <span>{suite.fixturesPassed} / {suite.fixturesTotal} passed</span>
        <span>{formatRuntime(suite.runtimeSeconds)}</span>
        <span>{suite.totalTokens} tokens</span>
      </div>

      <div className="eval-dashboard-fixtures">
        {suite.fixtures.map((fixture) => (
          <article className="eval-dashboard-fixture" key={fixture.fixtureId}>
            <div className="eval-dashboard-fixture-head">
              <div>
                <strong>{fixture.fixtureId}</strong>
                <span>{fixture.mode}</span>
              </div>
              <span className={`status-chip ${fixtureTone(fixture.status)}`}>{fixture.status}</span>
            </div>
            <p className="muted">{formatScore(fixture.score)}</p>
            {fixture.changedFiles.length ? (
              <div className="eval-dashboard-detail-list">
                <span>Changed files</span>
                {fixture.changedFiles.map((file) => <code key={file}>{file}</code>)}
              </div>
            ) : null}
            {fixture.checks.length ? (
              <div className="eval-dashboard-detail-list">
                <span>Checks</span>
                {fixture.checks.map((check, index) => (
                  <p key={`${check.type}-${index}`} className={check.passed ? 'muted' : 'artifact-browser-warning'}>
                    <span>{check.type}{check.path ? ` ${check.path}` : ''}</span>
                    {check.message}
                  </p>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </article>
  );
}

export default function EvalDashboardPanel({ toolCalls }: EvalDashboardPanelProps) {
  const summary = useMemo(() => buildEvalDashboardSummary(toolCalls), [toolCalls]);

  return (
    <section className="eval-dashboard-panel" id="eval-dashboard" aria-label="Eval suite dashboard">
      <div className="eval-dashboard-header">
        <div>
          <p className="panel-label">Evals</p>
          <h3>Eval suite dashboard</h3>
          <p className="muted">Release gating view derived from generated eval suite reports.</p>
        </div>
        <span className={`status-chip ${gateTone(summary.gateStatus)}`}>{gateLabel(summary.gateStatus)}</span>
      </div>

      {!summary.latestSuite ? (
        <p className="muted">Eval suite reports will appear here after deterministic or live eval runs generate report JSON.</p>
      ) : (
        <div className="eval-dashboard-stack">
          {summary.suites.map((suite) => <SuiteCard key={suite.id} suite={suite} />)}
        </div>
      )}
    </section>
  );
}
