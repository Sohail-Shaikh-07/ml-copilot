import type { ToolCallPayload } from './types';

export type PublishState = 'local-only' | 'dry-run' | 'uploaded' | 'token-required' | 'error';

export interface PublishingArtifact {
  path: string;
  fileName: string;
  kind: string;
}

export interface PublishingPreviewBlock {
  title: string;
  content: string;
}

export interface PublishingProvenance {
  datasets: string[];
  papers: string[];
  jobs: string[];
  evals: string[];
}

export interface PublishingReportSummary {
  id: string;
  repoId: string | null;
  modelName: string | null;
  task: string | null;
  publishState: PublishState;
  outputDir: string | null;
  artifacts: PublishingArtifact[];
  previewBlocks: PublishingPreviewBlock[];
  provenance: PublishingProvenance;
  recommendation: string | null;
  warning: string | null;
}

export interface PublishingDashboardSummary {
  reports: PublishingReportSummary[];
  latestReport: PublishingReportSummary | null;
  needsTokenWarning: boolean;
}

const PREVIEW_LIMIT = 1400;
const PUBLISH_ARTIFACT_RE = /^- (README|Final report|Manifest|Model card):\s*(.+)$/gim;

function firstNonEmptyText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asString(value: unknown) {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => asString(item)).filter((item): item is string => Boolean(item));
  }
  const text = asString(value);
  if (!text) return [];
  return text.split(/[;,]/).map((item) => item.trim()).filter(Boolean);
}

function unique(values: string[]) {
  return [...new Set(values.filter((value) => value.trim()))];
}

function basename(path: string) {
  return path.trim().replace(/^['"`]|['"`]$/g, '').split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function artifactKind(label: string, fileName: string) {
  if (/manifest/i.test(label) || fileName.endsWith('.json')) return 'Manifest';
  if (/final report/i.test(label)) return 'Final report';
  if (/readme|model card/i.test(label) || fileName.toLowerCase() === 'readme.md') return 'Model card';
  return 'Artifact';
}

function extractArtifacts(output: string | null): PublishingArtifact[] {
  if (!output) return [];
  const artifacts = new Map<string, PublishingArtifact>();
  for (const match of output.matchAll(PUBLISH_ARTIFACT_RE)) {
    const label = match[1];
    const path = match[2]?.trim();
    if (!path) continue;
    const fileName = basename(path);
    artifacts.set(path, {
      path,
      fileName,
      kind: artifactKind(label, fileName),
    });
  }
  return [...artifacts.values()];
}

function boundedPreview(value: string) {
  const trimmed = value.trim();
  if (trimmed.length <= PREVIEW_LIMIT) return trimmed;
  return `${trimmed.slice(0, PREVIEW_LIMIT).trimEnd()}\n...`;
}

function extractPreviewBlocks(output: string | null): PublishingPreviewBlock[] {
  if (!output) return [];
  const blocks: PublishingPreviewBlock[] = [];
  for (const match of output.matchAll(/^#{2,4}\s+(README\.md|FINAL_REPORT\.md|publish_manifest\.json)\s*\r?\n```(?:\w+)?\s*\r?\n([\s\S]*?)\r?\n```/gim)) {
    const title = match[1];
    const content = match[2];
    if (title && content) {
      blocks.push({ title, content: boundedPreview(content) });
    }
  }
  return blocks;
}

function parseJsonObject(value: string | undefined) {
  if (!value) return null;
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return null;
  }
}

function manifestFromPreviews(previews: PublishingPreviewBlock[]) {
  const manifest = previews.find((preview) => preview.title === 'publish_manifest.json');
  return parseJsonObject(manifest?.content);
}

function outputDirFromArtifacts(artifacts: PublishingArtifact[]) {
  const first = artifacts[0]?.path;
  if (!first || !first.includes('/')) return null;
  return first.split(/[\\/]/).slice(0, -1).join('/');
}

function publishState(call: ToolCallPayload, text: string | null): PublishState {
  const lowered = text?.toLowerCase() ?? '';
  if (lowered.includes('hugging face token is required')) return 'token-required';
  if (call.success === false || lowered.startsWith('error:')) return 'error';
  if (lowered.includes('published model assets to https://huggingface.co/')) return 'uploaded';
  if (call.arguments.publish === true) return 'dry-run';
  return 'local-only';
}

function warningForState(state: PublishState) {
  if (state === 'token-required') return 'A Hugging Face token is required before publishing to the Hub.';
  if (state === 'dry-run') return 'Publishing was requested; confirm token and approval state before retrying.';
  if (state === 'uploaded') return 'Assets were uploaded to Hugging Face Hub.';
  if (state === 'error') return 'Publishing did not complete successfully.';
  return null;
}

function argOrManifest(args: Record<string, unknown>, manifest: Record<string, unknown> | null, key: string) {
  return args[key] ?? manifest?.[key];
}

function reportFromCall(call: ToolCallPayload, index: number): PublishingReportSummary | null {
  if (call.tool_name !== 'publish_model_report') return null;
  const text = firstNonEmptyText(call.output, call.error);
  const artifacts = extractArtifacts(text);
  const previewBlocks = extractPreviewBlocks(text);
  const manifest = manifestFromPreviews(previewBlocks);
  const state = publishState(call, text);

  return {
    id: call.id || `publish-${index + 1}`,
    repoId: asString(argOrManifest(call.arguments, manifest, 'repo_id')),
    modelName: asString(argOrManifest(call.arguments, manifest, 'model_name')),
    task: asString(argOrManifest(call.arguments, manifest, 'task')),
    publishState: state,
    outputDir: asString(call.arguments.output_dir) ?? outputDirFromArtifacts(artifacts),
    artifacts,
    previewBlocks,
    provenance: {
      datasets: unique([...asStringList(argOrManifest(call.arguments, manifest, 'datasets'))]),
      papers: unique([...asStringList(argOrManifest(call.arguments, manifest, 'papers'))]),
      jobs: unique([...asStringList(argOrManifest(call.arguments, manifest, 'jobs'))]),
      evals: unique([...asStringList(argOrManifest(call.arguments, manifest, 'evals'))]),
    },
    recommendation: asString(argOrManifest(call.arguments, manifest, 'recommendation')),
    warning: warningForState(state),
  };
}

export function buildPublishingDashboardSummary(toolCalls: ToolCallPayload[]): PublishingDashboardSummary {
  const reports = toolCalls.flatMap((call, index) => {
    const report = reportFromCall(call, index);
    return report ? [report] : [];
  });
  const latestReport = reports.at(-1) ?? null;

  return {
    reports,
    latestReport,
    needsTokenWarning: reports.some((report) => report.publishState === 'token-required'),
  };
}
