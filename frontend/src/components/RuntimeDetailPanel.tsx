import { useMemo } from 'react';
import type { ToolCallPayload } from '../types';

interface RuntimeDetailPanelProps {
  toolCalls: ToolCallPayload[];
}

interface SandboxDetail {
  id: string;
  url: string | null;
  hardware: string | null;
  createdAt: string | null;
  files: string[];
  commands: Array<{ command: string; status: string; output: string | null }>;
}

interface JobDetail {
  id: string;
  logs: string[];
  url: string | null;
}

interface ArtifactDetail {
  id: string;
  label: string;
  kind: string;
  source: string;
}

interface RuntimeDetails {
  sandboxes: SandboxDetail[];
  jobs: JobDetail[];
  artifacts: ArtifactDetail[];
}

const ARTIFACT_FILE_RE = /\b(?:README\.md|FINAL_REPORT\.md|publish_manifest\.json|report\.json|report\.md)\b/gi;

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

function slug(value: string) {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'runtime';
}

function formatCount(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function addUnique(values: string[], value: string | null | undefined) {
  const normalized = value?.trim();
  if (!normalized) return;
  if (!values.includes(normalized)) values.push(normalized);
}

function addArtifact(artifacts: Map<string, ArtifactDetail>, label: string | null | undefined, kind: string, source: string) {
  const normalized = label?.trim();
  if (!normalized) return;
  const id = `${kind}:${normalized}`;
  if (!artifacts.has(id)) {
    artifacts.set(id, { id, label: normalized, kind, source });
  }
}

function parseLogs(output: string | null | undefined) {
  if (!output) return [];
  const fenced = output.match(/```\s*([\s\S]*?)\s*```/);
  const body = fenced?.[1] ?? output;
  return body
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .filter((line) => line.trim() && !line.startsWith('# Logs for'))
    .slice(-12);
}

function parseJobId(call: ToolCallPayload) {
  const output = firstNonEmptyText(call.output, call.error);
  return (
    getArgText(call.arguments, 'job_id') ??
    matchLine(output, /^### Job\s+(.+)$/i) ??
    matchLine(output, /^# Logs for\s+([^\s(]+)/i) ??
    matchLine(output, /^Job\s+([^\s]+)\s+has been cancelled/i)
  );
}

function sandboxFromCall(call: ToolCallPayload, fallbackId: string): SandboxDetail {
  const output = firstNonEmptyText(call.output, call.error);
  const id = matchLine(output, /^- Space:\s*(.+)$/i) ?? fallbackId;
  return {
    id,
    url: firstUrl(output) ?? null,
    hardware: getArgText(call.arguments, 'hardware') ?? matchLine(output, /^- Hardware:\s*(.+)$/i),
    createdAt: matchLine(output, /^- Created:\s*(.+)$/i),
    files: [],
    commands: [],
  };
}

function collectArtifactsFromText(artifacts: Map<string, ArtifactDetail>, text: string | null | undefined, source: string) {
  if (!text) return;
  const pathBullets = text.matchAll(/^- (?:README|Final report|Manifest):\s*(.+)$/gim);
  for (const match of pathBullets) {
    const path = match[1]?.trim();
    if (path) addArtifact(artifacts, basename(path), 'artifact', source);
  }

  for (const match of text.matchAll(ARTIFACT_FILE_RE)) {
    addArtifact(artifacts, match[0], 'artifact', source);
  }
}

function deriveRuntimeDetails(toolCalls: ToolCallPayload[]): RuntimeDetails {
  const sandboxes = new Map<string, SandboxDetail>();
  const jobs = new Map<string, JobDetail>();
  const artifacts = new Map<string, ArtifactDetail>();
  let activeSandboxId = 'active-sandbox';

  for (const call of toolCalls) {
    const output = firstNonEmptyText(call.output, call.error);
    const operation = getArgText(call.arguments, 'operation');

    if (call.tool_name === 'experiment_workspace') {
      const createDetail = sandboxFromCall(call, activeSandboxId);
      if (operation === 'create' || !sandboxes.size) {
        activeSandboxId = createDetail.id;
        if (!sandboxes.has(createDetail.id)) sandboxes.set(createDetail.id, createDetail);
      }

      const sandbox = sandboxes.get(activeSandboxId) ?? createDetail;
      sandboxes.set(sandbox.id, sandbox);

      const path = getArgText(call.arguments, 'path') ?? matchLine(output, /^Wrote\s+(.+?)\s+\(/i) ?? matchLine(output, /^###\s+(.+)$/i);
      addUnique(sandbox.files, path);
      if (path) addArtifact(artifacts, path, 'sandbox file', 'sandbox');

      const command = getArgText(call.arguments, 'command') ?? matchLine(output, /^Command:\s*(.+)$/i);
      if (command) {
        sandbox.commands.push({
          command,
          status: call.success === false || call.error ? 'failed' : 'completed',
          output: output ? output.slice(0, 700) : null,
        });
      }
    }

    if (call.tool_name === 'manage_job') {
      const jobId = parseJobId(call);
      if (jobId) {
        const current = jobs.get(jobId) ?? { id: jobId, logs: [], url: null };
        current.url = current.url ?? firstUrl(output);
        const logs = parseLogs(output);
        for (const line of logs) addUnique(current.logs, line);
        jobs.set(jobId, current);
      }
    }

    if (call.tool_name === 'publish_model_report') {
      addArtifact(artifacts, getArgText(call.arguments, 'output_dir'), 'artifact directory', 'publishing');
      collectArtifactsFromText(artifacts, output, 'publishing');
    }

    collectArtifactsFromText(artifacts, output, call.tool_name);
  }

  return {
    sandboxes: [...sandboxes.values()],
    jobs: [...jobs.values()],
    artifacts: [...artifacts.values()],
  };
}

function sandboxStatusAction() {
  return "experiment_workspace operation='status'";
}

function sandboxReadAction(path: string) {
  return `experiment_workspace operation='read' path='${path}'`;
}

function jobAction(operation: 'inspect' | 'logs', jobId: string) {
  return `manage_job operation='${operation}' job_id='${jobId}'`;
}

export default function RuntimeDetailPanel({ toolCalls }: RuntimeDetailPanelProps) {
  const details = useMemo(() => deriveRuntimeDetails(toolCalls), [toolCalls]);
  const hasRuntimeDetails = details.sandboxes.length || details.jobs.length || details.artifacts.length;

  return (
    <section className="runtime-detail-panel" id="runtime-details" aria-label="Runtime detail panels">
      <div className="runtime-detail-header">
        <div>
          <p className="panel-label">Runtime details</p>
          <h3>Sandboxes, jobs, and artifacts</h3>
          <p className="muted">Recovered from persisted session tool calls for current and historical sessions.</p>
        </div>
        <div className="runtime-detail-counts">
          <span className="status-chip neutral">{formatCount(details.sandboxes.length, 'sandbox', 'sandboxes')}</span>
          <span className="status-chip neutral">{formatCount(details.jobs.length, 'job reference')}</span>
          <span className="status-chip neutral">{formatCount(details.artifacts.length, 'artifact')}</span>
        </div>
      </div>

      {!hasRuntimeDetails ? (
        <p className="muted">Sandbox sessions, job references, and generated artifacts will appear here after runtime tools run.</p>
      ) : (
        <div className="runtime-detail-stack">
          {details.sandboxes.map((sandbox) => (
            <article className="runtime-detail-card" data-testid={`runtime-sandbox-${slug(sandbox.id)}`} key={sandbox.id}>
              <div className="runtime-detail-card-head">
                <div>
                  <span>Sandbox runtime</span>
                  <h4>{sandbox.id}</h4>
                </div>
                {sandbox.url ? (
                  <a href={sandbox.url} rel="noopener noreferrer" target="_blank">
                    Open sandbox
                  </a>
                ) : null}
              </div>

              <dl className="runtime-detail-metadata">
                {sandbox.hardware ? (
                  <div>
                    <dt>Hardware</dt>
                    <dd>{sandbox.hardware}</dd>
                  </div>
                ) : null}
                {sandbox.createdAt ? (
                  <div>
                    <dt>Created</dt>
                    <dd>{sandbox.createdAt}</dd>
                  </div>
                ) : null}
              </dl>

              {sandbox.files.length ? (
                <div className="runtime-detail-list">
                  <strong>Files</strong>
                  {sandbox.files.map((file) => (
                    <span key={file}>{file}</span>
                  ))}
                </div>
              ) : null}

              {sandbox.commands.length ? (
                <div className="runtime-command-list">
                  <strong>Commands</strong>
                  {sandbox.commands.map((command, index) => (
                    <div className={`runtime-command ${command.status}`} key={`${command.command}-${index}`}>
                      <span>{command.command}</span>
                      {command.output ? <pre>{command.output}</pre> : null}
                    </div>
                  ))}
                </div>
              ) : null}

              <div className="runtime-detail-actions">
                <code>{sandboxStatusAction()}</code>
                {sandbox.files.slice(0, 3).map((file) => (
                  <code key={file}>{sandboxReadAction(file)}</code>
                ))}
              </div>
            </article>
          ))}

          {details.jobs.map((job) => (
            <article className="runtime-detail-card" data-testid={`runtime-job-${slug(job.id)}`} key={job.id}>
              <div className="runtime-detail-card-head">
                <div>
                  <span>Job reference</span>
                  <h4>{job.id}</h4>
                </div>
                {job.url ? (
                  <a href={job.url} rel="noopener noreferrer" target="_blank">
                    Open job
                  </a>
                ) : null}
              </div>

              {job.logs.length ? (
                <div className="runtime-command-list">
                  <strong>Latest logs</strong>
                  <pre>{job.logs.join('\n')}</pre>
                </div>
              ) : null}

              <div className="runtime-detail-actions">
                <code>{jobAction('inspect', job.id)}</code>
                <code>{jobAction('logs', job.id)}</code>
              </div>
            </article>
          ))}

          {details.artifacts.length ? (
            <article className="runtime-detail-card" data-testid="runtime-artifacts">
              <div className="runtime-detail-card-head">
                <div>
                  <span>Generated artifacts</span>
                  <h4>{formatCount(details.artifacts.length, 'artifact')}</h4>
                </div>
              </div>

              <div className="runtime-artifact-grid">
                {details.artifacts.map((artifact) => (
                  <div className="runtime-artifact" key={artifact.id}>
                    <span>{artifact.kind}</span>
                    <strong>{artifact.label}</strong>
                    <small>{artifact.source}</small>
                  </div>
                ))}
              </div>
            </article>
          ) : null}
        </div>
      )}
    </section>
  );
}
