import type { ToolCallPayload } from './types';

export type ResearchStepKind = 'paper' | 'citation' | 'reading' | 'recipe' | 'model' | 'dataset' | 'docs' | 'repository' | 'decision';

export interface ResearchEvidence {
  label: string;
  snippet: string;
}

export interface ResearchStep {
  id: string;
  kind: ResearchStepKind;
  title: string;
  sourceId: string | null;
  summary: string;
  links: string[];
  evidence: ResearchEvidence[];
  confidence: string | null;
  limitations: string | null;
  decision: string | null;
}

export interface ResearchTrailSummary {
  steps: ResearchStep[];
  evidenceCount: number;
  decisionCount: number;
}

const RESEARCH_TOOLS = new Set([
  'paper_details',
  'paper_citation_graph',
  'read_paper',
  'extract_training_recipe',
  'search_hub',
  'inspect_hub_repo',
  'inspect_dataset',
  'hf_papers',
  'hf_search_hub',
  'hf_inspect_dataset',
  'hf_repo_files',
  'fetch_hf_docs',
  'explore_hf_docs',
  'find_hf_api',
  'analyze_repository',
]);

function firstNonEmptyText(...values: Array<string | null | undefined>) {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return null;
}

function asString(value: unknown) {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function bounded(value: string, limit = 260) {
  const trimmed = value.replace(/\s+/g, ' ').trim();
  if (trimmed.length <= limit) return trimmed;
  return `${trimmed.slice(0, limit).trimEnd()}...`;
}

function heading(text: string | null, fallback: string) {
  const match = text?.match(/^#\s+(.+)$/m) ?? text?.match(/^##\s+(.+)$/m);
  return match?.[1]?.trim() ?? fallback;
}

function links(text: string | null) {
  return [...new Set(text?.match(/https?:\/\/[^\s)]+/g) ?? [])];
}

function matchLine(text: string | null, pattern: RegExp) {
  if (!text) return null;
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(pattern);
    if (match?.[1]?.trim()) return match[1].trim();
  }
  return null;
}

function arxivId(call: ToolCallPayload, text: string | null) {
  return asString(call.arguments.arxiv_id) ?? matchLine(text, /\*\*arxiv_id:\*\*\s*([^|\n]+)/i);
}

function evidenceFromLines(text: string | null): ResearchEvidence[] {
  if (!text) return [];
  const evidence: ResearchEvidence[] = [];

  for (const match of text.matchAll(/evidence:\s*"([^"]+)"/gi)) {
    evidence.push({ label: 'Evidence', snippet: bounded(match[1]) });
  }
  for (const match of text.matchAll(/^Evidence:\s*(.+)$/gim)) {
    evidence.push({ label: 'Evidence', snippet: bounded(match[1]) });
  }

  const aiSummary = text.match(/## AI Summary\s+([\s\S]*?)(?:\n## |\n\*\*Next:|$)/i);
  if (aiSummary?.[1]) {
    evidence.push({ label: 'AI summary', snippet: bounded(aiSummary[1]) });
  }

  const abstract = text.match(/## Abstract\s+([\s\S]*?)(?:\n## |\n\*\*Next:|$)/i);
  if (abstract?.[1]) {
    evidence.push({ label: 'Abstract', snippet: bounded(abstract[1]) });
  }

  return evidence;
}

function firstHubCandidate(text: string | null) {
  const match = text?.match(/\|\s*\d+\s*\|\s*\[([^\]]+)\]\(([^)]+)\)/);
  return match ? { repo: match[1], link: match[2] } : null;
}

function decisionFromText(text: string | null) {
  return matchLine(text, /^Decision:\s*(.+)$/i);
}

function kindForCall(call: ToolCallPayload, text: string | null): ResearchStepKind | null {
  if (call.tool_name === 'paper_details' || call.tool_name === 'hf_papers') return 'paper';
  if (call.tool_name === 'paper_citation_graph') return 'citation';
  if (call.tool_name === 'read_paper') return 'reading';
  if (call.tool_name === 'extract_training_recipe') return 'recipe';
  if (call.tool_name === 'search_hub' || call.tool_name === 'inspect_hub_repo' || call.tool_name === 'hf_search_hub' || call.tool_name === 'hf_repo_files') {
    return (asString(call.arguments.repo_type) ?? text ?? '').toLowerCase().includes('dataset') ? 'dataset' : 'model';
  }
  if (call.tool_name === 'inspect_dataset' || call.tool_name === 'hf_inspect_dataset') return 'dataset';
  if (call.tool_name === 'fetch_hf_docs' || call.tool_name === 'explore_hf_docs' || call.tool_name === 'find_hf_api') return 'docs';
  if (call.tool_name === 'analyze_repository') return 'repository';
  return RESEARCH_TOOLS.has(call.tool_name) ? 'decision' : null;
}

function titleForStep(call: ToolCallPayload, kind: ResearchStepKind, text: string | null) {
  if (kind === 'model' || kind === 'dataset') {
    const candidate = firstHubCandidate(text);
    if (candidate) return candidate.repo;
    return asString(call.arguments.repo_id) ?? asString(call.arguments.source) ?? asString(call.arguments.dataset) ?? heading(text, call.tool_name);
  }
  if (kind === 'docs') return asString(call.arguments.query) ?? asString(call.arguments.url) ?? heading(text, 'Documentation research');
  if (kind === 'repository') return asString(call.arguments.path) ?? heading(text, 'Repository analysis');
  return heading(text, asString(call.arguments.arxiv_id) ?? call.tool_name);
}

function summaryForStep(kind: ResearchStepKind, text: string | null, evidence: ResearchEvidence[]) {
  if (kind === 'recipe') return 'Extracted training recipe with source-linked evidence.';
  if (kind === 'citation') return 'Citation context and related work traversal.';
  if (kind === 'model') return 'Model candidate or Hub repository considered.';
  if (kind === 'dataset') return 'Dataset candidate, schema, or preview considered.';
  if (kind === 'repository') return 'Repository evidence and implementation readiness considered.';
  return evidence[0]?.snippet ?? bounded(text ?? 'Research step captured from tool output.');
}

function reportFromCall(call: ToolCallPayload, index: number): ResearchStep | null {
  const text = firstNonEmptyText(call.output, call.error);
  const kind = kindForCall(call, text);
  if (!kind) return null;

  const evidence = evidenceFromLines(text);
  const candidate = firstHubCandidate(text);
  const sourceLinks = links(text);
  if (candidate?.link && !sourceLinks.includes(candidate.link)) sourceLinks.push(candidate.link);
  if (!evidence.length && text) {
    evidence.push({ label: 'Output', snippet: bounded(text) });
  }

  const decision = decisionFromText(text);
  const limitation = text?.match(/Verify against read_paper[^.\n]*[.\n]?/i)?.[0]?.trim() ?? null;

  return {
    id: call.id || `research-${index + 1}`,
    kind,
    title: titleForStep(call, kind, text),
    sourceId: arxivId(call, text) ?? asString(call.arguments.repo_id) ?? asString(call.arguments.source) ?? null,
    summary: summaryForStep(kind, text, evidence),
    links: sourceLinks,
    evidence,
    confidence: kind === 'recipe' && text?.toLowerCase().includes('deterministically') ? 'deterministic extraction' : null,
    limitations: limitation,
    decision,
  };
}

export function buildResearchTrailSummary(toolCalls: ToolCallPayload[]): ResearchTrailSummary {
  const steps = toolCalls.flatMap((call, index) => {
    const step = reportFromCall(call, index);
    return step ? [step] : [];
  });

  return {
    steps,
    evidenceCount: steps.reduce((total, step) => total + step.evidence.length, 0),
    decisionCount: steps.filter((step) => step.decision).length,
  };
}
