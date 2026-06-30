import { useMemo } from 'react';
import { buildUsageMeterSummary } from '../usageMeter';
import type { SessionDetail, ToolCallPayload } from '../types';

interface UsageMeterPanelProps {
  session: SessionDetail | null;
  toolCalls: ToolCallPayload[];
}

function formatCompact(value: number) {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function formatCurrency(value: number, maximumFractionDigits = 4, minimumFractionDigits = maximumFractionDigits) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits,
    minimumFractionDigits,
  }).format(value);
}

function formatLatency(value: number) {
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

function progressLabel(percent: number | null, fallback: string) {
  return percent === null ? fallback : `${percent}%`;
}

export default function UsageMeterPanel({ session, toolCalls }: UsageMeterPanelProps) {
  const summary = useMemo(
    () => (session ? buildUsageMeterSummary(session, toolCalls) : null),
    [session, toolCalls],
  );

  return (
    <section className="usage-meter-panel" aria-label="Usage and cost estimate">
      <div className="usage-meter-header">
        <div>
          <p className="panel-label">Usage</p>
          <h3>Cost estimate</h3>
          <p className="muted">Tracks tokens, estimated provider spend, runtime tools, and budget hints.</p>
        </div>
        <span className={`status-chip ${summary?.warningLevel ?? 'neutral'}`}>
          {summary?.warningLevel === 'danger'
            ? 'cap reached'
            : summary?.warningLevel === 'warning'
              ? 'near cap'
              : 'estimate'}
        </span>
      </div>

      {!session || !summary ? (
        <p className="muted">Usage estimates will appear after you select or create a session.</p>
      ) : (
        <>
          <div className="usage-meter-grid">
            <article className="usage-meter-card">
              <span>Tokens</span>
              <strong>{formatCompact(session.metrics.total_tokens)} tokens</strong>
              <p>
                {formatCompact(session.metrics.prompt_tokens)} prompt ·{' '}
                {formatCompact(session.metrics.completion_tokens)} completion
              </p>
            </article>

            <article className="usage-meter-card">
              <span>Estimated provider cost</span>
              <strong>{formatCurrency(session.metrics.estimated_cost_usd)} est.</strong>
              <p>
                {summary.costProgressPercent === null || summary.costCapUsd === null
                  ? 'No spend cap set for this session'
                  : `${progressLabel(summary.costProgressPercent, '0%')} of ${formatCurrency(summary.costCapUsd, 2, 2)} cap`}
              </p>
              <div className="usage-meter-progress" aria-label="Spend cap progress">
                <span style={{ width: `${Math.min(summary.costProgressPercent ?? 0, 100)}%` }} />
              </div>
            </article>

            <article className="usage-meter-card">
              <span>Turns</span>
              <strong>
                {summary.turnCap === null
                  ? `${session.metrics.turn_count} turns`
                  : `${session.metrics.turn_count} / ${summary.turnCap} turns`}
              </strong>
              <p>
                {summary.turnProgressPercent === null
                  ? 'No max-turn guardrail set'
                  : `${summary.turnProgressPercent}% of session turn budget`}
              </p>
              <div className="usage-meter-progress" aria-label="Turn cap progress">
                <span style={{ width: `${Math.min(summary.turnProgressPercent ?? 0, 100)}%` }} />
              </div>
            </article>

            <article className="usage-meter-card">
              <span>Tool health</span>
              <strong>{session.metrics.tool_calls} calls</strong>
              <p>
                {session.metrics.tool_errors} errors · {session.metrics.tool_retries} retries · avg{' '}
                {formatLatency(session.metrics.average_tool_latency_ms)}
              </p>
            </article>
          </div>

          {summary.runtimeBreakdown.length ? (
            <div className="usage-meter-breakdown" aria-label="Runtime usage breakdown">
              {summary.runtimeBreakdown.map((item) => (
                <div className="usage-meter-breakdown-item" key={item.label}>
                  <strong>{item.label}</strong>
                  <span>{item.count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">Runtime usage appears after jobs, sandboxes, publishing, or experiment-loop tools run.</p>
          )}

          {summary.hfQuotaWarning ? (
            <div className="usage-meter-warning">
              <strong>{summary.hfQuotaWarning.title}</strong>
              <p>{summary.hfQuotaWarning.body}</p>
              <a href={summary.hfQuotaWarning.href} rel="noopener noreferrer" target="_blank">
                Open Hugging Face billing
              </a>
            </div>
          ) : null}

          <p className="hint">{summary.copyNote}</p>
        </>
      )}
    </section>
  );
}
