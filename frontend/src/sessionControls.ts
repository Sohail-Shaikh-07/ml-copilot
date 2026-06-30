export type ProviderId =
  | 'openai_compatible'
  | 'anthropic'
  | 'gemini'
  | 'xai'
  | 'zai'
  | 'kimi'
  | 'minimax';

export type ReasoningEffort = 'off' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
export type OperatingMode = 'normal' | 'careful' | 'fast';

export interface SessionControlState {
  provider: ProviderId;
  reasoningEffort: ReasoningEffort;
  temperature: string;
  operatingMode: OperatingMode;
  maxTurns: string;
  spendCapUsd: string;
}

export interface StoredAgentControls {
  provider: ProviderId;
  reasoning_effort: ReasoningEffort;
  temperature: number | null;
  operating_mode: OperatingMode;
  yolo_mode: boolean;
  max_turns: number | null;
  spend_cap_usd: number | null;
}

export const DEFAULT_SESSION_CONTROLS: SessionControlState = {
  provider: 'openai_compatible',
  reasoningEffort: 'off',
  temperature: '',
  operatingMode: 'normal',
  maxTurns: '',
  spendCapUsd: '',
};

export const PROVIDER_OPTIONS: Array<{ id: ProviderId; label: string; suggestedModel: string; suggestedLabel: string }> = [
  {
    id: 'openai_compatible',
    label: 'OpenAI-compatible',
    suggestedModel: 'gpt-5.4',
    suggestedLabel: 'GPT-5.4',
  },
  {
    id: 'anthropic',
    label: 'Anthropic',
    suggestedModel: 'claude-opus-4-8',
    suggestedLabel: 'Claude Opus 4.8',
  },
  {
    id: 'gemini',
    label: 'Gemini',
    suggestedModel: 'gemini-2.5-pro',
    suggestedLabel: 'Gemini 2.5 Pro',
  },
  {
    id: 'xai',
    label: 'xAI',
    suggestedModel: 'grok-4',
    suggestedLabel: 'Grok 4',
  },
  {
    id: 'zai',
    label: 'Z.ai',
    suggestedModel: 'zai-org/GLM-5.2:novita',
    suggestedLabel: 'GLM 5.2',
  },
  {
    id: 'kimi',
    label: 'Kimi',
    suggestedModel: 'moonshotai/Kimi-K2.7-Code:novita',
    suggestedLabel: 'Kimi K2.7 Code',
  },
  {
    id: 'minimax',
    label: 'MiniMax',
    suggestedModel: 'MiniMaxAI/MiniMax-M3:novita',
    suggestedLabel: 'MiniMax M3',
  },
];

export const EFFORT_OPTIONS: Array<{ id: ReasoningEffort; label: string }> = [
  { id: 'off', label: 'Off' },
  { id: 'minimal', label: 'Minimal' },
  { id: 'low', label: 'Low' },
  { id: 'medium', label: 'Medium' },
  { id: 'high', label: 'High' },
  { id: 'xhigh', label: 'Extra high' },
  { id: 'max', label: 'Max' },
];

export const OPERATING_MODE_OPTIONS: Array<{ id: OperatingMode; label: string; description: string }> = [
  { id: 'normal', label: 'Normal', description: 'Balanced approvals and autonomy.' },
  { id: 'careful', label: 'Careful', description: 'Prefer extra safety and confirmation.' },
  { id: 'fast', label: 'Fast / YOLO-style', description: 'Persisted as a fast-mode preference only.' },
];

const providerLabels = new Map(PROVIDER_OPTIONS.map((option) => [option.id, option.label]));

export function providerLabel(provider: ProviderId | string | null | undefined) {
  return providerLabels.get(provider as ProviderId) ?? 'Unknown provider';
}

export function suggestedModelForProvider(provider: ProviderId) {
  return PROVIDER_OPTIONS.find((option) => option.id === provider)?.suggestedModel ?? 'gpt-5.4';
}

export function suggestedModelLabelForProvider(provider: ProviderId) {
  return PROVIDER_OPTIONS.find((option) => option.id === provider)?.suggestedLabel ?? 'GPT-5.4';
}

function nullableNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function nullablePositiveInt(value: string): number | null {
  const parsed = nullableNumber(value);
  if (parsed === null) return null;
  return Math.max(1, Math.round(parsed));
}

export function buildSessionMetadata(source: string, controls: SessionControlState): Record<string, unknown> {
  return {
    source,
    agent_controls: {
      provider: controls.provider,
      reasoning_effort: controls.reasoningEffort,
      temperature: nullableNumber(controls.temperature),
      operating_mode: controls.operatingMode,
      yolo_mode: controls.operatingMode === 'fast',
      max_turns: nullablePositiveInt(controls.maxTurns),
      spend_cap_usd: nullableNumber(controls.spendCapUsd),
    },
  };
}

export function readStoredAgentControls(metadata: Record<string, unknown>): StoredAgentControls | null {
  const raw = metadata.agent_controls;
  if (!raw || typeof raw !== 'object') return null;
  const controls = raw as Record<string, unknown>;
  return {
    provider: String(controls.provider || 'openai_compatible') as ProviderId,
    reasoning_effort: String(controls.reasoning_effort || 'off') as ReasoningEffort,
    temperature: typeof controls.temperature === 'number' ? controls.temperature : null,
    operating_mode: String(controls.operating_mode || 'normal') as OperatingMode,
    yolo_mode: Boolean(controls.yolo_mode),
    max_turns: typeof controls.max_turns === 'number' ? controls.max_turns : null,
    spend_cap_usd: typeof controls.spend_cap_usd === 'number' ? controls.spend_cap_usd : null,
  };
}
