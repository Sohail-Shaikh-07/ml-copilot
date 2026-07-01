import { describe, expect, it } from 'vitest';

import { buildResearchTrailSummary } from './researchTrail';
import type { ToolCallPayload } from './types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'paper_details',
    arguments: {},
    status: 'completed',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T06:00:00Z',
    finished_at: '2026-07-01T06:00:02Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

describe('buildResearchTrailSummary', () => {
  it('builds an evidence-backed timeline from research tool calls', () => {
    const summary = buildResearchTrailSummary([
      toolCall({
        id: 'paper',
        tool_name: 'paper_details',
        arguments: { arxiv_id: '2401.12345' },
        output: [
          '# Efficient Fine-Tuning for Small Models',
          '**arxiv_id:** 2401.12345 | **upvotes:** 42',
          'https://huggingface.co/papers/2401.12345',
          'https://arxiv.org/abs/2401.12345',
          '## AI Summary',
          'Adapters improve accuracy while keeping training cost low.',
        ].join('\n'),
      }),
      toolCall({
        id: 'recipe',
        tool_name: 'extract_training_recipe',
        arguments: { arxiv_id: '2401.12345' },
        output: [
          '# Training recipe for Efficient Fine-Tuning for Small Models',
          'Scanned 2 method/experiment section(s).',
          '## Dataset',
          '- We train on IMDb and SST-2 sentiment datasets.',
          '  - evidence: "We train on IMDb and SST-2 sentiment datasets."',
          '**Note:** Recipe values are extracted deterministically from method and experiment sections. Verify against read_paper before relying on them for training.',
        ].join('\n'),
      }),
      toolCall({
        id: 'hub',
        tool_name: 'search_hub',
        arguments: { repo_type: 'model', query: 'distilbert sentiment', task: 'text-classification' },
        output: [
          '## Hub models discovery',
          '| Score | Repository | Task | License | Downloads | Likes | Fit signals |',
          '|---:|---|---|---|---:|---:|---|',
          '| 91 | [distilbert/distilbert-base-uncased](https://huggingface.co/distilbert/distilbert-base-uncased) | text-classification | apache-2.0 | 1000 | 50 | task match |',
        ].join('\n'),
      }),
      toolCall({
        id: 'dataset',
        tool_name: 'inspect_dataset',
        arguments: { source: 'imdb' },
        output: '## imdb (Hugging Face)\n**Status:** Dataset preview available\n| text | string |\n| label | class_label |',
      }),
      toolCall({
        id: 'repo',
        tool_name: 'analyze_repository',
        arguments: { path: '.' },
        output: '## Repository analysis\nDecision: use adapter fine-tuning and gate with eval fixtures.\nEvidence: tests and configs are present.',
      }),
    ]);

    expect(summary.steps).toHaveLength(5);
    expect(summary.steps.map((step) => step.kind)).toEqual(['paper', 'recipe', 'model', 'dataset', 'repository']);
    expect(summary.steps[0].title).toBe('Efficient Fine-Tuning for Small Models');
    expect(summary.steps[0].sourceId).toBe('2401.12345');
    expect(summary.steps[0].links).toContain('https://arxiv.org/abs/2401.12345');
    expect(summary.steps[1].evidence[0].snippet).toContain('IMDb and SST-2');
    expect(summary.steps[1].confidence).toBe('deterministic extraction');
    expect(summary.steps[1].limitations).toContain('Verify against read_paper');
    expect(summary.steps[2].title).toContain('distilbert/distilbert-base-uncased');
    expect(summary.steps[3].title).toBe('imdb');
    expect(summary.decisionCount).toBe(1);
    expect(summary.evidenceCount).toBeGreaterThanOrEqual(4);
  });
});
