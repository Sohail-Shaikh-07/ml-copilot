import { useMemo, useState } from 'react';
import type {
  PendingApprovalPayload,
  SessionEventPayload,
  SessionMetricsSummary,
  ToolCallPayload,
} from '../types';

interface ToolTracePanelProps {
  liveEvents: SessionEventPayload[];
  pendingApprovals: PendingApprovalPayload[];
  metrics: SessionMetricsSummary | null;
  toolCalls: ToolCallPayload[];
}

interface ToolMetadataItem {
  label: string;
  value: string;
  href?: string;
  linkLabel?: string;
}

interface ToolProfile {
  category: string;
  title: string;
  description: string;
  icon: string;
  metadata: ToolMetadataItem[];
}

const PREVIEW_LIMIT = 520;

function shortId(value: string) {
  return value.slice(0, 8);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `[${value.map(formatValue).join(', ')}]`;
  if (typeof value === 'object') return '{...}';
  return String(value);
}

function formatArgs(args: Record<string, unknown>) {
  const entries = Object.entries(args);
  if (entries.length === 0) return 'No arguments';
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${formatValue(value)}`)
    .join(' | ');
}

function safeStringify(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function sentenceCase(value: string) {
  return value
    .replace(/^mcp__[^_]+__/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDuration(startedAt: string | null, finishedAt: string | null) {
  if (!startedAt || !finishedAt) return null;
  const start = new Date(startedAt);
  const finish = new Date(finishedAt);
  if (Number.isNaN(start.getTime()) || Number.isNaN(finish.getTime())) return null;
  const seconds = Math.max(0, Math.round((finish.getTime() - start.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function formatEventLabel(eventType: string) {
  return eventType
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function eventSummary(event: SessionEventPayload) {
  const content = event.data.content;
  if (typeof content === 'string' && content.trim()) return content;

  const output = event.data.output;
  if (typeof output === 'string' && output.trim()) return output;

  const error = event.data.error;
  if (typeof error === 'string' && error.trim()) return error;

  const tool = event.data.tool ?? event.data.tool_name;
  if (typeof tool === 'string' && tool.trim()) return tool;

  return JSON.stringify(event.data);
}

function firstNonEmptyText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }
  return null;
}

function toneForStatus(status: string) {
  if (status === 'success' || status === 'completed' || status === 'output-available') return 'success';
  if (status === 'error' || status === 'failed' || status === 'output-error') return 'danger';
  if (status === 'approval-required' || status === 'approval-requested') return 'warning';
  return 'neutral';
}

function formatCompact(value: number) {
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(value);
}

function groupToolCalls(toolCalls: ToolCallPayload[]) {
  const sorted = [...toolCalls].sort((a, b) => {
    const aTime = a.started_at ?? a.finished_at ?? '';
    const bTime = b.started_at ?? b.finished_at ?? '';
    return aTime.localeCompare(bTime) || a.id.localeCompare(b.id);
  });

  const groups: Array<{ turnId: string; calls: ToolCallPayload[] }> = [];
  const lookup = new Map<string, ToolCallPayload[]>();

  for (const call of sorted) {
    const current = lookup.get(call.turn_id);
    if (current) {
      current.push(call);
      continue;
    }

    const next = [call];
    lookup.set(call.turn_id, next);
    groups.push({ turnId: call.turn_id, calls: next });
  }

  return groups;
}

function textOutput(call: ToolCallPayload) {
  return firstNonEmptyText(call.error, call.output);
}

function previewText(value: string) {
  if (value.length <= PREVIEW_LIMIT) {
    return { text: value, truncated: false };
  }
  return { text: `${value.slice(0, PREVIEW_LIMIT).trimEnd()}\n...`, truncated: true };
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

function addMetadata(items: ToolMetadataItem[], item: ToolMetadataItem | null) {
  if (!item) return;
  if (!item.value.trim()) return;
  if (items.some((existing) => existing.label === item.label && existing.value === item.value)) return;
  items.push(item);
}

function addRuntimePanelLink(items: ToolMetadataItem[]) {
  addMetadata(items, {
    label: 'Runtime',
    value: 'Runtime panel',
    href: '#runtime-details',
    linkLabel: 'Open runtime panel',
  });
}

function addArtifactBrowserLink(items: ToolMetadataItem[]) {
  addMetadata(items, {
    label: 'Artifacts',
    value: 'Artifact browser',
    href: '#artifact-browser',
    linkLabel: 'Open artifact browser',
  });
}

function addPublishingPanelLink(items: ToolMetadataItem[]) {
  addMetadata(items, {
    label: 'Publishing',
    value: 'Final report panel',
    href: '#publishing-panel',
    linkLabel: 'Open publishing panel',
  });
}

function buildToolProfile(call: ToolCallPayload): ToolProfile {
  const args = call.arguments;
  const output = textOutput(call);
  const metadata: ToolMetadataItem[] = [];
  const operation = getArgText(args, 'operation');

  if (operation) {
    addMetadata(metadata, { label: 'Operation', value: operation });
  }

  switch (call.tool_name) {
    case 'manage_job': {
      const status = matchLine(output, /^Status:\s*(.+)$/i);
      const hardware = getArgText(args, 'hardware') ?? matchLine(output, /^Hardware:\s*(.+)$/i);
      const jobId = getArgText(args, 'job_id') ?? matchLine(output, /^Job(?: ID)?:\s*(.+)$/i);
      const url = firstUrl(output);

      if (status) addMetadata(metadata, { label: 'Status', value: status });
      if (hardware) addMetadata(metadata, { label: 'Hardware', value: hardware });
      if (jobId) addMetadata(metadata, { label: 'Job', value: jobId });
      if (url) addMetadata(metadata, { label: 'Link', value: url, href: url, linkLabel: 'Open job' });
      addRuntimePanelLink(metadata);

      return {
        category: 'Job orchestration',
        title: 'Hugging Face job',
        description: 'Run, inspect, stream logs, or cancel long-running Hugging Face Jobs.',
        icon: '⚙️',
        metadata,
      };
    }
    case 'experiment_workspace': {
      const path = getArgText(args, 'path') ?? getArgText(args, 'workspace_path');
      const command = getArgText(args, 'command');
      const sandboxId = getArgText(args, 'sandbox_id');

      if (command) addMetadata(metadata, { label: 'Command', value: command });
      if (path) addMetadata(metadata, { label: 'Path', value: path });
      if (sandboxId) addMetadata(metadata, { label: 'Sandbox', value: sandboxId });
      addRuntimePanelLink(metadata);
      addArtifactBrowserLink(metadata);

      return {
        category: 'Sandbox runtime',
        title: 'Experiment workspace',
        description: 'Create, inspect, run, and tear down sandboxed experiment workspaces.',
        icon: '🧪',
        metadata,
      };
    }
    case 'manage_experiment_loop': {
      const targetMetric = getArgText(args, 'target_metric');
      const maxAttempts = getArgText(args, 'max_attempts');

      if (targetMetric) addMetadata(metadata, { label: 'Target', value: targetMetric });
      if (maxAttempts) addMetadata(metadata, { label: 'Max attempts', value: maxAttempts });

      return {
        category: 'Experiment loop',
        title: 'Autonomous experiment loop',
        description: 'Track attempts, diagnose failures, and decide the next ML experiment action.',
        icon: '🔁',
        metadata,
      };
    }
    case 'publish_model_report': {
      const outputDir = getArgText(args, 'output_dir');
      const repoId = getArgText(args, 'repo_id');

      if (outputDir) addMetadata(metadata, { label: 'Output', value: outputDir });
      if (repoId) addMetadata(metadata, { label: 'Repository', value: repoId });
      addRuntimePanelLink(metadata);
      addPublishingPanelLink(metadata);
      addArtifactBrowserLink(metadata);

      return {
        category: 'Publishing',
        title: 'Model report',
        description: 'Prepare model cards, final reports, manifests, and optional Hub publishing.',
        icon: '🚀',
        metadata,
      };
    }
    case 'hf_papers':
      addMetadata(metadata, { label: 'Query', value: getArgText(args, 'query') ?? getArgText(args, 'arxiv_id') ?? '' });
      return {
        category: 'Research',
        title: 'Paper search',
        description: 'Search, inspect, and connect papers, citations, datasets, and models.',
        icon: '📄',
        metadata,
      };
    case 'fetch_hf_docs':
    case 'explore_hf_docs':
    case 'find_hf_api':
      addMetadata(metadata, { label: 'Topic', value: getArgText(args, 'query') ?? getArgText(args, 'url') ?? '' });
      return {
        category: 'Documentation',
        title: sentenceCase(call.tool_name),
        description: 'Read Hugging Face documentation and API guidance.',
        icon: '📚',
        metadata,
      };
    case 'hf_inspect_dataset':
    case 'hf_repo_files':
    case 'hf_search_hub':
      addMetadata(metadata, {
        label: 'Resource',
        value: getArgText(args, 'dataset') ?? getArgText(args, 'repo_id') ?? getArgText(args, 'query') ?? '',
      });
      addArtifactBrowserLink(metadata);
      return {
        category: 'Hub operation',
        title: sentenceCase(call.tool_name),
        description: 'Inspect Hugging Face Hub resources and repository metadata.',
        icon: '🤗',
        metadata,
      };
    case 'analyze_repository':
      addMetadata(metadata, { label: 'Path', value: getArgText(args, 'path') ?? '' });
      addArtifactBrowserLink(metadata);
      return {
        category: 'Repository analysis',
        title: 'Repository analyzer',
        description: 'Review project files, ML structure, dependency gaps, and reproducibility signals.',
        icon: '🧭',
        metadata,
      };
    default:
      return {
        category: call.tool_name.startsWith('mcp__') ? 'External integration' : 'Workspace tool',
        title: sentenceCase(call.tool_name),
        description: 'Tool call captured from the persisted session trace.',
        icon: '🛠️',
        metadata,
      };
  }
}

function ToolCallCard({ call }: { call: ToolCallPayload }) {
  const [expanded, setExpanded] = useState(false);
  const profile = useMemo(() => buildToolProfile(call), [call]);
  const duration = formatDuration(call.started_at, call.finished_at);
  const resultText = textOutput(call) ?? 'Waiting for output';
  const resultPreview = previewText(resultText);
  const resultLabel = call.success === false || call.error ? 'Error' : 'Output';
  const statusTone = toneForStatus(call.status);
  const showDetails = expanded || resultPreview.truncated || Object.keys(call.arguments).length > 0;

  return (
    <article className={`tool-card ${statusTone}`} data-testid={`tool-card-${call.id}`}>
      <div className="tool-card-head">
        <div className="tool-card-title-row">
          <span className="tool-card-icon" aria-hidden="true">
            {profile.icon}
          </span>
          <div>
            <span className="tool-card-category">{profile.category}</span>
            <h5>{profile.title}</h5>
            <p>{profile.description}</p>
          </div>
        </div>
        <span className={`status-chip ${statusTone}`}>{call.status}</span>
      </div>

      {profile.metadata.length ? (
        <dl className="tool-card-metadata">
          {profile.metadata.map((item) => (
            <div key={`${item.label}-${item.value}`}>
              <dt>{item.label}</dt>
              <dd>
                {item.href ? (
                  <a href={item.href} rel="noopener noreferrer" target="_blank">
                    {item.linkLabel ?? item.value}
                  </a>
                ) : (
                  item.value
                )}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="tool-card-args">{formatArgs(call.arguments)}</p>
      )}

      <div className={`tool-card-output ${call.success === false || call.error ? 'danger' : ''}`}>
        <span>{resultLabel}</span>
        <p>{resultPreview.text}</p>
      </div>

      <div className="tool-card-meta-row">
        <span>{call.requires_approval ? 'approval required' : 'no approval required'}</span>
        {duration ? <span>{duration}</span> : null}
        {call.approval_id ? <span>approval {shortId(call.approval_id)}</span> : null}
      </div>

      {showDetails ? (
        <button
          className="ghost-button tool-card-details-toggle"
          type="button"
          aria-label={`${expanded ? 'Hide' : 'Show'} details for ${profile.title}`}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Hide details' : 'Show details'}
        </button>
      ) : null}

      {expanded ? (
        <div className="tool-card-details">
          <div>
            <span>Arguments</span>
            <pre>{safeStringify(call.arguments)}</pre>
          </div>
          <div>
            <span>{resultLabel}</span>
            <pre>{resultText}</pre>
          </div>
        </div>
      ) : null}
    </article>
  );
}

export default function ToolTracePanel({ liveEvents, pendingApprovals, metrics, toolCalls }: ToolTracePanelProps) {
  const grouped = groupToolCalls(toolCalls);
  const recentEvents = liveEvents.slice(-6);

  return (
    <div className="tool-trace-panel">
      <section className="tool-trace-card">
        <div className="tool-trace-header">
          <div>
            <p className="panel-label">Tool trace</p>
            <h3>
              {toolCalls.length} calls across {grouped.length} turns
            </h3>
            <p className="muted">
              {metrics
                ? `${formatCompact(metrics.total_tokens)} tokens · ${formatCurrency(metrics.estimated_cost_usd)} est. spend`
                : 'Usage metrics will appear after the first completed turn.'}
            </p>
          </div>
          <span className="status-chip neutral">{recentEvents.length} live events</span>
        </div>

        <div className="tool-trace-live">
          <div className="tool-trace-subheader">
            <strong>Recent events</strong>
            <span>{recentEvents.length ? 'Latest SSE activity' : 'Waiting for events'}</span>
          </div>

          {recentEvents.length === 0 ? (
            <p className="muted">SSE events will appear here while the active session runs.</p>
          ) : (
            <div className="tool-trace-events">
              {recentEvents.map((event) => (
                <article key={event.id} className="tool-trace-event">
                  <div className="tool-trace-event-meta">
                    <span>{formatEventLabel(event.event_type)}</span>
                    <span>#{event.sequence}</span>
                  </div>
                  <p>{eventSummary(event)}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="tool-trace-card">
        <div className="tool-trace-subheader">
          <strong>Grouped calls</strong>
          <span>{pendingApprovals.length} approvals pending</span>
        </div>

        {grouped.length === 0 ? (
          <p className="muted">Tool calls will appear here when the agent starts using tools.</p>
        ) : (
          <div className="tool-trace-groups">
            {grouped.map((group) => (
              <article key={group.turnId} className="tool-trace-group">
                <div className="tool-trace-group-head">
                  <div>
                    <span className="tool-trace-kicker">Turn</span>
                    <h4>{shortId(group.turnId)}</h4>
                  </div>
                  <span className="status-chip neutral">
                    {group.calls.length} call{group.calls.length === 1 ? '' : 's'}
                  </span>
                </div>

                <div className="tool-trace-call-list">
                  {group.calls.map((call) => (
                    <ToolCallCard key={call.id} call={call} />
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
