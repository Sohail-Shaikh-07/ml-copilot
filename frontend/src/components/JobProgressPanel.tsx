import { useMemo } from 'react';
import type { ToolCallPayload } from '../types';

interface JobProgressPanelProps {
  toolCalls: ToolCallPayload[];
}

interface JobProgress {
  id: string;
  status: string;
  message: string | null;
  hardware: string | null;
  createdAt: string | null;
  command: string | null;
  url: string | null;
  logs: string[];
  timeline: Array<{ label: string; detail: string | null }>;
}

const ACTIVE_STATUSES = new Set(['QUEUED', 'RUNNING', 'STARTING', 'PENDING']);
const BILLING_URL = 'https://huggingface.co/settings/billing';

function firstNonEmptyText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return null;
}

function getArgText(args: Record<string, unknown>, key: string) {
  const value = args[key];
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function matchLine(text: string | null | undefined, pattern: RegExp) {
  if (!text) return null;
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(pattern);
    if (match?.[1]?.trim()) return match[1].trim();
  }
  return null;
}

function firstUrl(text: string | null | undefined) {
  return text?.match(/https?:\/\/[^\s)]+/)?.[0] ?? null;
}

function parseJobId(call: ToolCallPayload) {
  const output = firstNonEmptyText(call.output, call.error);
  return (
    getArgText(call.arguments, 'job_id') ??
    matchLine(output, /^### Job\s+(.+)$/i) ??
    matchLine(output, /^Job\s+([^\s]+)\s+has been cancelled/i) ??
    matchLine(output, /^# Logs for\s+([^\s(]+)/i) ??
    matchLine(output, /^Error (?:fetching logs|cancelling job|inspecting job)\s+([^:]+):/i)
  );
}

function parseMarkdownBullet(text: string | null | undefined, label: string) {
  return matchLine(text, new RegExp(`^- \\*\\*${label}:\\*\\*\\s*(.+)$`, 'i'));
}

function parseLogs(output: string | null | undefined) {
  if (!output) return [];
  const fenced = output.match(/```(?:\w+)?\n([\s\S]*?)```/);
  const body = fenced?.[1] ?? output.replace(/^# Logs for[^\n]*\n*/i, '');
  return body
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim())
    .slice(-8);
}

function isBillingProblem(text: string | null | undefined) {
  if (!text) return false;
  const lowered = text.toLowerCase();
  return (
    lowered.includes('no available credits') ||
    lowered.includes('billing') ||
    lowered.includes('quota') ||
    lowered.includes('payment required') ||
    lowered.includes('402')
  );
}

function upsertJob(jobs: Map<string, JobProgress>, jobId: string): JobProgress {
  const current = jobs.get(jobId);
  if (current) return current;

  const next: JobProgress = {
    id: jobId,
    status: 'UNKNOWN',
    message: null,
    hardware: null,
    createdAt: null,
    command: null,
    url: null,
    logs: [],
    timeline: [],
  };
  jobs.set(jobId, next);
  return next;
}

function addTimeline(job: JobProgress, label: string, detail: string | null = null) {
  if (job.timeline.some((item) => item.label === label && item.detail === detail)) return;
  job.timeline.push({ label, detail });
}

function buildJobs(toolCalls: ToolCallPayload[]) {
  const jobs = new Map<string, JobProgress>();
  const billingProblems: string[] = [];

  for (const call of toolCalls) {
    if (call.tool_name !== 'manage_job') continue;

    const output = firstNonEmptyText(call.output, call.error);
    if (isBillingProblem(output)) {
      billingProblems.push(output ?? 'Hugging Face Jobs need namespace credits before this run can continue.');
    }

    const jobId = parseJobId(call);
    if (!jobId) continue;

    const job = upsertJob(jobs, jobId);
    const operation = getArgText(call.arguments, 'operation')?.toLowerCase();
    const status = parseMarkdownBullet(output, 'Status');
    const message = parseMarkdownBullet(output, 'Message');
    const hardware = getArgText(call.arguments, 'hardware_flavor') ?? parseMarkdownBullet(output, 'Hardware');
    const createdAt = parseMarkdownBullet(output, 'Created');
    const command = parseMarkdownBullet(output, 'Command')?.replace(/^`|`$/g, '');
    const url = firstUrl(output);

    if (status) job.status = status.toUpperCase();
    if (message) job.message = message;
    if (hardware) job.hardware = hardware;
    if (createdAt) job.createdAt = createdAt;
    if (command) job.command = command;
    if (url) job.url = url;

    if (operation === 'run') addTimeline(job, 'Launched', call.finished_at);
    if (operation === 'inspect') addTimeline(job, 'Inspected', call.finished_at);
    if (operation === 'logs') {
      addTimeline(job, 'Logs fetched', call.finished_at);
      job.logs = parseLogs(call.output);
    }
    if (operation === 'cancel') {
      job.status = 'CANCELLED';
      addTimeline(job, 'Cancel requested', call.finished_at);
    }
  }

  return {
    jobs: [...jobs.values()].sort((a, b) => a.id.localeCompare(b.id)),
    billingProblem: billingProblems[0] ?? null,
  };
}

function statusTone(status: string) {
  if (status === 'COMPLETED') return 'success';
  if (status === 'FAILED' || status === 'ERROR' || status === 'CANCELLED') return 'danger';
  if (ACTIVE_STATUSES.has(status)) return 'warning';
  return 'neutral';
}

function actionText(operation: 'inspect' | 'logs' | 'cancel', jobId: string) {
  return `manage_job operation='${operation}' job_id='${jobId}'`;
}

export default function JobProgressPanel({ toolCalls }: JobProgressPanelProps) {
  const { jobs, billingProblem } = useMemo(() => buildJobs(toolCalls), [toolCalls]);
  const activeCount = jobs.filter((job) => ACTIVE_STATUSES.has(job.status)).length;

  return (
    <section className="job-progress-panel" aria-label="Hugging Face job progress">
      <div className="job-progress-header">
        <div>
          <p className="panel-label">HF Jobs</p>
          <h3>Job progress</h3>
          <p className="muted">Recovered from persisted manage_job calls, so job state remains visible after refresh.</p>
        </div>
        <span className={`status-chip ${activeCount > 0 ? 'warning' : 'neutral'}`}>
          {activeCount} active job{activeCount === 1 ? '' : 's'}
        </span>
      </div>

      {billingProblem ? (
        <div className="job-billing-alert">
          <strong>Namespace credits needed</strong>
          <p>
            HF Jobs use namespace credits, which are separate from HF Pro membership. Add credits, then re-run the job.
          </p>
          <a href={BILLING_URL} rel="noopener noreferrer" target="_blank">
            Open HF billing
          </a>
        </div>
      ) : null}

      {jobs.length === 0 ? (
        <p className="muted">Hugging Face Jobs will appear here after manage_job launches, inspects, logs, or cancels a run.</p>
      ) : (
        <div className="job-progress-list">
          {jobs.map((job) => (
            <article key={job.id} className="job-progress-card" data-testid={`job-progress-${job.id}`}>
              <div className="job-progress-card-head">
                <div>
                  <span className="tool-card-category">Hugging Face job</span>
                  <h4>{job.id}</h4>
                  {job.message ? <p>{job.message}</p> : null}
                </div>
                <span className={`status-chip ${statusTone(job.status)}`}>{job.status}</span>
              </div>

              <dl className="job-progress-metadata">
                {job.hardware ? (
                  <div>
                    <dt>Hardware</dt>
                    <dd>{job.hardware}</dd>
                  </div>
                ) : null}
                {job.createdAt ? (
                  <div>
                    <dt>Created</dt>
                    <dd>{job.createdAt}</dd>
                  </div>
                ) : null}
                {job.command ? (
                  <div>
                    <dt>Command</dt>
                    <dd>{job.command}</dd>
                  </div>
                ) : null}
                {job.url ? (
                  <div>
                    <dt>Destination</dt>
                    <dd>
                      <a href={job.url} rel="noopener noreferrer" target="_blank">
                        Open on Hugging Face
                      </a>
                    </dd>
                  </div>
                ) : null}
              </dl>

              <div className="job-progress-timeline" aria-label={`Timeline for ${job.id}`}>
                {job.timeline.map((item) => (
                  <div key={`${item.label}-${item.detail ?? ''}`}>
                    <span aria-hidden="true" />
                    <p>{item.label}</p>
                    {item.detail ? <small>{item.detail}</small> : null}
                  </div>
                ))}
              </div>

              {job.logs.length ? (
                <div className="job-progress-logs">
                  <span>Latest logs</span>
                  <pre>{job.logs.join('\n')}</pre>
                </div>
              ) : null}

              <div className="job-progress-actions" aria-label={`Safe actions for ${job.id}`}>
                <code>{actionText('inspect', job.id)}</code>
                <code>{actionText('logs', job.id)}</code>
                {ACTIVE_STATUSES.has(job.status) ? <code>{actionText('cancel', job.id)}</code> : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
