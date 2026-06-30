import { describe, expect, it } from 'vitest';

import {
  DEFAULT_SESSION_CONTROLS,
  buildSessionMetadata,
  suggestedModelForProvider,
} from './sessionControls';

describe('sessionControls', () => {
  it('builds sanitized session metadata for provider, model, effort, mode, and budget controls', () => {
    const metadata = buildSessionMetadata('frontend-shell', {
      ...DEFAULT_SESSION_CONTROLS,
      provider: 'zai',
      reasoningEffort: 'high',
      temperature: '0.2',
      operatingMode: 'careful',
      maxTurns: '120',
      spendCapUsd: '3.50',
    });

    expect(metadata).toEqual({
      source: 'frontend-shell',
      agent_controls: {
        provider: 'zai',
        reasoning_effort: 'high',
        temperature: 0.2,
        operating_mode: 'careful',
        yolo_mode: false,
        max_turns: 120,
        spend_cap_usd: 3.5,
      },
    });
  });

  it('keeps custom model ids while offering provider-specific suggested defaults', () => {
    expect(suggestedModelForProvider('anthropic')).toBe('claude-opus-4-8');
    expect(suggestedModelForProvider('zai')).toBe('zai-org/GLM-5.2:novita');
    expect(suggestedModelForProvider('openai_compatible')).toBe('gpt-5.4');
  });
});
