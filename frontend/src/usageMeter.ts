import { readStoredAgentControls } from './sessionControls';
import type { SessionDetail, ToolCallPayload } from './types';

export type UsageWarningLevel = 'neutral' | 'warning' | 'danger';

export interface UsageMeterSummary {
  costCapUsd: number | null;
  costProgressPercent: number | null;
  turnCap: number | null;
  turnProgressPercent: number | null;
  warningLevel: UsageWarningLevel;
  runtimeBreakdown: Array<{ label: string; count: number }>;
  hfQuotaWarning: { title: string; body: string; href: string } | null;
  copyNote: string;
}

const HF_BILLING_URL = 'https://huggingface.co/settings/billing';
const QUOTA_PATTERNS = ['credits', 'quota', 'billing', 'payment required', '402'];
const RUNTIME_LABELS: Record<string, string> = {
  manage_job: 'HF Jobs',
  experiment_workspace: 'Sandbox',
  publish_model_report: 'Publishing',
  manage_experiment_loop: 'Experiment loop',
};

export function buildUsageMeterSummary(session: SessionDetail, toolCalls: ToolCallPayload[]): UsageMeterSummary {
  const controls = readStoredAgentControls(session.metadata);
  const costCapUsd = controls?.spend_cap_usd ?? null;
  const turnCap = controls?.max_turns ?? null;
  const costProgressPercent = progress(session.metrics.estimated_cost_usd, costCapUsd);
  const turnProgressPercent = progress(session.metrics.turn_count, turnCap);

  return {
    costCapUsd,
    costProgressPercent,
    turnCap,
    turnProgressPercent,
    warningLevel: highestWarning(costProgressPercent, turnProgressPercent),
    runtimeBreakdown: buildRuntimeBreakdown(toolCalls),
    hfQuotaWarning: findHfQuotaWarning(toolCalls),
    copyNote: 'Estimates only. Actual charges happen with your configured model provider or Hugging Face account.',
  };
}

function progress(value: number, cap: number | null): number | null {
  if (cap === null || cap <= 0) return null;
  return Math.round((Math.max(0, value) / cap) * 100);
}

function highestWarning(...progressValues: Array<number | null>): UsageWarningLevel {
  if (progressValues.some((value) => value !== null && value >= 100)) return 'danger';
  if (progressValues.some((value) => value !== null && value >= 80)) return 'warning';
  return 'neutral';
}

function buildRuntimeBreakdown(toolCalls: ToolCallPayload[]) {
  const counts = new Map<string, number>();

  for (const call of toolCalls) {
    const label = RUNTIME_LABELS[call.tool_name];
    if (!label) continue;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }

  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function findHfQuotaWarning(toolCalls: ToolCallPayload[]) {
  const call = toolCalls.find((item) => hasQuotaText(item.output) || hasQuotaText(item.error));
  if (!call) return null;

  return {
    title: 'Hugging Face credits or quota needed',
    body: 'A Hugging Face Jobs or Sandbox action reported a credits, quota, or billing problem. Add credits or adjust the run in your HF account, then retry.',
    href: firstUrl(call.output) ?? firstUrl(call.error) ?? HF_BILLING_URL,
  };
}

function hasQuotaText(value: string | null | undefined) {
  if (!value) return false;
  const lowered = value.toLowerCase();
  return QUOTA_PATTERNS.some((pattern) => lowered.includes(pattern));
}

function firstUrl(text: string | null | undefined) {
  return text?.match(/https?:\/\/[^\s)]+/)?.[0] ?? null;
}
