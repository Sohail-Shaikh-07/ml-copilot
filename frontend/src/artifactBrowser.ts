import type { ToolCallPayload } from './types';

export interface ArtifactBrowserItem {
  id: string;
  path: string;
  fileName: string;
  kind: string;
  provenance: string;
  sourceCallId: string;
  safe: boolean;
  blockedReason: string | null;
  sizeLabel: string | null;
  preview: string | null;
}

const PREVIEW_LIMIT = 1200;
const PATH_KEYS = ['path', 'file_path', 'workspace_path', 'output_path', 'report_path', 'manifest_path'];
const FILE_EXTENSIONS = ['md', 'markdown', 'json', 'py', 'txt', 'csv', 'yaml', 'yml', 'log', 'html', 'env'];
const PATH_RE = /(?:[A-Za-z]:[\\/]|\.{1,2}[\\/]|~[\\/])?(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\.(?:md|markdown|json|py|txt|csv|ya?ml|log|html|env)\b/g;

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

function normalizePath(path: string) {
  return path.trim().replace(/^['"`]|['"`]$/g, '').replace(/\\/g, '/');
}

function displayPath(path: string) {
  return path.trim().replace(/^['"`]|['"`]$/g, '');
}

function fileName(path: string) {
  return normalizePath(path).split('/').filter(Boolean).pop() ?? path;
}

function extension(path: string) {
  const name = fileName(path).toLowerCase();
  return name.includes('.') ? name.split('.').pop() ?? '' : '';
}

function classify(path: string) {
  const ext = extension(path);
  if (ext === 'md' || ext === 'markdown') return 'Markdown';
  if (ext === 'json') return 'JSON';
  if (ext === 'py') return 'Python';
  if (ext === 'csv') return 'CSV';
  if (ext === 'yaml' || ext === 'yml') return 'YAML';
  if (ext === 'log') return 'Log';
  if (ext === 'html') return 'HTML';
  return 'Text';
}

function formatSize(bytes: number | null) {
  if (bytes === null) return null;
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb >= 10 ? 0 : 1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}

function safetyForPath(path: string): { safe: boolean; blockedReason: string | null } {
  const normalized = normalizePath(path);
  if (/^[A-Za-z]:\//.test(normalized) || normalized.startsWith('/') || normalized.startsWith('~/')) {
    return { safe: false, blockedReason: 'Unsafe absolute path is blocked' };
  }
  if (normalized.split('/').includes('..')) {
    return { safe: false, blockedReason: 'Path traversal is blocked' };
  }
  if (/(^|\/)(\.env|.*secret.*|.*token.*)$/i.test(normalized)) {
    return { safe: false, blockedReason: 'Sensitive-looking path is blocked' };
  }
  return { safe: true, blockedReason: null };
}

function boundedPreview(value: string | null) {
  if (!value) return null;
  const trimmed = value.trim();
  if (trimmed.length <= PREVIEW_LIMIT) return trimmed;
  return `${trimmed.slice(0, PREVIEW_LIMIT).trimEnd()}\n...`;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function previewForPath(path: string, output: string | null | undefined) {
  if (!output) return null;
  const normalized = normalizePath(path);
  const display = displayPath(path);
  const headingPatterns = [normalized, display, fileName(path)].map(escapeRegExp);

  for (const pattern of headingPatterns) {
    const heading = new RegExp(`^#{1,4}\\s+${pattern}\\s*\\r?\\n\`\`\`\\w*\\s*\\r?\\n([\\s\\S]*?)\\r?\\n\`\`\``, 'im');
    const match = output.match(heading);
    if (match?.[1]) return boundedPreview(match[1]);
  }

  const fenced = output.match(/```\w*\s*\r?\n([\s\S]*?)\r?\n```/);
  if (fenced?.[1]) return boundedPreview(fenced[1]);

  return null;
}

function collectCandidatePaths(call: ToolCallPayload) {
  const output = firstNonEmptyText(call.output, call.error);
  const candidates: Array<{ path: string; sizeBytes: number | null }> = [];

  for (const key of PATH_KEYS) {
    const value = getArgText(call.arguments, key);
    if (value) candidates.push({ path: value, sizeBytes: null });
  }

  if (output) {
    for (const match of output.matchAll(/^Wrote\s+(.+?)\s+\((\d+)\s+bytes\)\.?$/gim)) {
      candidates.push({ path: match[1], sizeBytes: Number(match[2]) });
    }

    for (const match of output.matchAll(/^- (?:README|Final report|Manifest|Report|Markdown report|Suite report|Model card|Dataset|Artifact):\s*(.+)$/gim)) {
      candidates.push({ path: match[1], sizeBytes: null });
    }

    for (const match of output.matchAll(PATH_RE)) {
      candidates.push({ path: match[0], sizeBytes: null });
    }
  }

  return candidates;
}

export function buildArtifactBrowserItems(toolCalls: ToolCallPayload[]): ArtifactBrowserItem[] {
  const items = new Map<string, ArtifactBrowserItem>();

  for (const call of toolCalls) {
    const output = firstNonEmptyText(call.output, call.error);
    for (const candidate of collectCandidatePaths(call)) {
      const path = displayPath(candidate.path);
      const normalized = normalizePath(path);
      if (!path || !FILE_EXTENSIONS.includes(extension(path))) continue;
      const safety = safetyForPath(path);
      const id = normalized.toLowerCase();
      const existing = items.get(id);
      const preview = safety.safe ? previewForPath(path, output) : null;

      items.set(id, {
        id,
        path,
        fileName: fileName(path),
        kind: classify(path),
        provenance: existing?.provenance ?? call.tool_name,
        sourceCallId: existing?.sourceCallId ?? call.id,
        safe: safety.safe,
        blockedReason: safety.blockedReason,
        sizeLabel: existing?.sizeLabel ?? formatSize(candidate.sizeBytes),
        preview: existing?.preview ?? preview,
      });
    }
  }

  return [...items.values()].sort((a, b) => {
    if (a.safe !== b.safe) return a.safe ? -1 : 1;
    return a.path.localeCompare(b.path);
  });
}

export function artifactReadAction(path: string) {
  return `experiment_workspace operation='read' path='${path}'`;
}
