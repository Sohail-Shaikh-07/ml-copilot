import { describe, expect, it } from 'vitest';

import { buildPublishingDashboardSummary } from './publishingDashboard';
import type { ToolCallPayload } from './types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-publish-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'publish_model_report',
    arguments: {
      repo_id: 'sohail/demo-model',
      model_name: 'Demo Model',
      task: 'text-classification',
      datasets: ['imdb'],
      jobs: ['train-job-1'],
      recommendation: 'Ship this model after one more eval pass.',
      publish: false,
    },
    status: 'completed',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T04:00:00Z',
    finished_at: '2026-07-01T04:00:03Z',
    output: [
      'Prepared model publishing assets.',
      '- README: reports/model-publishing/demo-model/README.md',
      '- Final report: reports/model-publishing/demo-model/FINAL_REPORT.md',
      '- Manifest: reports/model-publishing/demo-model/publish_manifest.json',
      'Set publish=true to upload these assets to the Hugging Face Hub.',
      '',
      '### README.md',
      '```markdown',
      '# Demo Model',
      'Generated model card content.',
      '```',
      '',
      '### FINAL_REPORT.md',
      '```markdown',
      '# Final Report: Demo Model',
      'Recommendation: Ship this model after one more eval pass.',
      '```',
      '',
      '### publish_manifest.json',
      '```json',
      '{',
      '  "repo_id": "sohail/demo-model",',
      '  "model_name": "Demo Model",',
      '  "task": "text-classification",',
      '  "datasets": ["imdb"],',
      '  "jobs": ["train-job-1"],',
      '  "papers": ["paper-123"],',
      '  "metrics": {"accuracy": 0.93},',
      '  "recommendation": "Ship this model after one more eval pass."',
      '}',
      '```',
    ].join('\n'),
    success: true,
    error: null,
    ...overrides,
  };
}

describe('buildPublishingDashboardSummary', () => {
  it('summarizes local publishing artifacts, previews, and provenance', () => {
    const summary = buildPublishingDashboardSummary([toolCall({})]);

    expect(summary.reports).toHaveLength(1);
    expect(summary.latestReport?.repoId).toBe('sohail/demo-model');
    expect(summary.latestReport?.modelName).toBe('Demo Model');
    expect(summary.latestReport?.task).toBe('text-classification');
    expect(summary.latestReport?.publishState).toBe('local-only');
    expect(summary.latestReport?.artifacts.map((artifact) => artifact.fileName)).toEqual([
      'README.md',
      'FINAL_REPORT.md',
      'publish_manifest.json',
    ]);
    expect(summary.latestReport?.previewBlocks.map((block) => block.title)).toEqual([
      'README.md',
      'FINAL_REPORT.md',
      'publish_manifest.json',
    ]);
    expect(summary.latestReport?.provenance.datasets).toContain('imdb');
    expect(summary.latestReport?.provenance.jobs).toContain('train-job-1');
    expect(summary.latestReport?.provenance.papers).toContain('paper-123');
    expect(summary.latestReport?.recommendation).toBe('Ship this model after one more eval pass.');
    expect(summary.needsTokenWarning).toBe(false);
  });

  it('warns when a publish request needs a Hugging Face token', () => {
    const summary = buildPublishingDashboardSummary([
      toolCall({
        arguments: { repo_id: 'sohail/demo-model', publish: true },
        output: 'Error: A Hugging Face token is required when publish=true.',
        success: false,
        error: 'Error: A Hugging Face token is required when publish=true.',
      }),
    ]);

    expect(summary.latestReport?.publishState).toBe('token-required');
    expect(summary.latestReport?.warning).toContain('token');
    expect(summary.needsTokenWarning).toBe(true);
  });
});
