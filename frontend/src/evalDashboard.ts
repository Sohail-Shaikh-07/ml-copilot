import type { ToolCallPayload } from './types';

export type EvalGateStatus = 'healthy' | 'blocked' | 'unknown';

export interface EvalCheckSummary {
  type: string;
  passed: boolean;
  message: string;
  path: string | null;
}

export interface EvalFixtureSummary {
  fixtureId: string;
  status: string;
  score: number | null;
  mode: string;
  reportPath: string | null;
  markdownPath: string | null;
  workspacePath: string | null;
  changedFiles: string[];
  checks: EvalCheckSummary[];
}

export interface EvalSuiteSummary {
  id: string;
  status: string;
  averageScore: number | null;
  runtimeSeconds: number | null;
  totalTokens: number;
  fixturesTotal: number;
  fixturesPassed: number;
  fixturesFailed: number;
  fixturesError: number;
  fixtures: EvalFixtureSummary[];
}

export interface EvalDashboardSummary {
  gateStatus: EvalGateStatus;
  totalSuites: number;
  latestSuite: EvalSuiteSummary | null;
  suites: EvalSuiteSummary[];
}

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
  return typeof value === 'string' && value.trim() ? value : null;
}

function asNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function parseJsonCandidates(text: string): Record<string, unknown>[] {
  const candidates: Record<string, unknown>[] = [];

  for (const match of text.matchAll(/```(?:json)?\s*([\s\S]*?)```/gi)) {
    const parsed = parseJsonObject(match[1]);
    if (parsed) candidates.push(parsed);
  }

  const trimmed = text.trim();
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    const parsed = parseJsonObject(trimmed);
    if (parsed) candidates.push(parsed);
  }

  return candidates;
}

function parseJsonObject(value: string | undefined) {
  if (!value) return null;
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return null;
  }
}

function looksLikeSuiteReport(report: Record<string, unknown>) {
  return Boolean(asRecord(report.summary) && Array.isArray(report.fixtures));
}

function inferMode(fixture: Record<string, unknown>, nestedReport: Record<string, unknown> | null) {
  const metadata = asRecord(asRecord(nestedReport?.fixture)?.metadata);
  const agentOutput = asRecord(nestedReport?.agent_output);
  return asString(metadata?.mode) ?? asString(agentOutput?.mode) ?? 'live';
}

function changedFilesFromReport(report: Record<string, unknown> | null) {
  const scoring = asRecord(report?.scoring);
  const fileChanges = asRecord(scoring?.file_changes);
  return asArray(fileChanges?.files_changed).map(String);
}

function checksFromReport(report: Record<string, unknown> | null): EvalCheckSummary[] {
  return asArray(report?.checks).flatMap((raw) => {
    const check = asRecord(raw);
    if (!check) return [];
    return [{
      type: asString(check.type) ?? 'check',
      passed: Boolean(check.passed),
      message: asString(check.message) ?? '',
      path: asString(check.path),
    }];
  });
}

function fixtureSummary(raw: unknown): EvalFixtureSummary | null {
  const fixture = asRecord(raw);
  if (!fixture) return null;
  const nestedReport = asRecord(fixture.report);
  const fixtureId = asString(fixture.fixture_id) ?? asString(asRecord(nestedReport?.fixture)?.id);
  if (!fixtureId) return null;

  return {
    fixtureId,
    status: asString(fixture.status) ?? asString(nestedReport?.status) ?? 'unknown',
    score: asNumber(fixture.score ?? nestedReport?.score),
    mode: inferMode(fixture, nestedReport),
    reportPath: asString(fixture.report_path),
    markdownPath: asString(fixture.markdown_path),
    workspacePath: asString(fixture.workspace_path),
    changedFiles: changedFilesFromReport(nestedReport),
    checks: checksFromReport(nestedReport),
  };
}

function suiteSummary(report: Record<string, unknown>, index: number): EvalSuiteSummary | null {
  if (!looksLikeSuiteReport(report)) return null;
  const summary = asRecord(report.summary) ?? {};
  const fixtures = asArray(report.fixtures).flatMap((fixture) => {
    const parsed = fixtureSummary(fixture);
    return parsed ? [parsed] : [];
  });

  return {
    id: `suite-${index + 1}`,
    status: asString(report.status) ?? 'unknown',
    averageScore: asNumber(summary.average_score),
    runtimeSeconds: asNumber(summary.runtime_seconds),
    totalTokens: asNumber(summary.total_tokens) ?? 0,
    fixturesTotal: asNumber(summary.fixtures_total) ?? fixtures.length,
    fixturesPassed: asNumber(summary.fixtures_passed) ?? fixtures.filter((fixture) => fixture.status === 'passed').length,
    fixturesFailed: asNumber(summary.fixtures_failed) ?? fixtures.filter((fixture) => fixture.status === 'failed').length,
    fixturesError: asNumber(summary.fixtures_error) ?? fixtures.filter((fixture) => fixture.status === 'error').length,
    fixtures,
  };
}

function gateStatusForSuite(suite: EvalSuiteSummary | null): EvalGateStatus {
  if (!suite) return 'unknown';
  if (suite.status === 'passed' && suite.fixturesFailed === 0 && suite.fixturesError === 0) return 'healthy';
  return 'blocked';
}

export function buildEvalDashboardSummary(toolCalls: ToolCallPayload[]): EvalDashboardSummary {
  const suites: EvalSuiteSummary[] = [];

  for (const call of toolCalls) {
    const text = firstNonEmptyText(call.output, call.error);
    if (!text) continue;
    for (const candidate of parseJsonCandidates(text)) {
      const suite = suiteSummary(candidate, suites.length);
      if (suite) suites.push(suite);
    }
  }

  const latestSuite = suites.at(-1) ?? null;
  return {
    gateStatus: gateStatusForSuite(latestSuite),
    totalSuites: suites.length,
    latestSuite,
    suites,
  };
}
