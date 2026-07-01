import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import PublishingPanel from './PublishingPanel';
import type { ToolCallPayload } from '../types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'publish-call',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'publish_model_report',
    arguments: {
      repo_id: 'sohail/demo-model',
      model_name: 'Demo Model',
      task: 'text-classification',
      datasets: ['imdb'],
      jobs: ['train-job-1'],
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
      '  "recommendation": "Ship this model after one more eval pass."',
      '}',
      '```',
    ].join('\n'),
    success: true,
    error: null,
    ...overrides,
  };
}

describe('PublishingPanel', () => {
  afterEach(() => cleanup());

  it('renders publishing status, artifacts, previews, and provenance', () => {
    render(<PublishingPanel toolCalls={[toolCall({})]} />);

    const panel = screen.getByRole('region', { name: 'Final report and publishing UI' });
    expect(within(panel).getByText('sohail/demo-model')).toBeInTheDocument();
    expect(within(panel).getByText('Demo Model')).toBeInTheDocument();
    expect(within(panel).getByText('Local assets prepared')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: 'Open publishing artifacts' })).toHaveAttribute('href', '#artifact-browser');
    expect(within(panel).getAllByText('README.md').length).toBeGreaterThan(0);
    expect(within(panel).getAllByText('FINAL_REPORT.md').length).toBeGreaterThan(0);
    expect(within(panel).getAllByText('publish_manifest.json').length).toBeGreaterThan(0);
    expect(within(panel).getByText('imdb')).toBeInTheDocument();
    expect(within(panel).getByText('train-job-1')).toBeInTheDocument();
    expect(within(panel).getByText('paper-123')).toBeInTheDocument();
    expect(within(panel).getByText(/# Final Report: Demo Model/)).toBeInTheDocument();
  });

  it('shows token-aware warning for failed Hub publish attempts', () => {
    render(
      <PublishingPanel
        toolCalls={[
          toolCall({
            arguments: { repo_id: 'sohail/demo-model', publish: true },
            output: 'Error: A Hugging Face token is required when publish=true.',
            success: false,
            error: 'Error: A Hugging Face token is required when publish=true.',
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Final report and publishing UI' });
    expect(within(panel).getByText('Token required')).toBeInTheDocument();
    expect(within(panel).getByText(/Hugging Face token is required/)).toBeInTheDocument();
  });
});
