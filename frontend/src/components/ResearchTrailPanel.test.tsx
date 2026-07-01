import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import ResearchTrailPanel from './ResearchTrailPanel';
import type { ToolCallPayload } from '../types';

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

describe('ResearchTrailPanel', () => {
  it('renders an expandable evidence-backed research timeline', async () => {
    const user = userEvent.setup();
    render(
      <ResearchTrailPanel
        toolCalls={[
          toolCall({
            id: 'paper',
            tool_name: 'paper_details',
            arguments: { arxiv_id: '2401.12345' },
            output: [
              '# Efficient Fine-Tuning for Small Models',
              '**arxiv_id:** 2401.12345 | **upvotes:** 42',
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
              '## Dataset',
              '- We train on IMDb and SST-2 sentiment datasets.',
              '  - evidence: "We train on IMDb and SST-2 sentiment datasets."',
              '**Note:** Recipe values are extracted deterministically from method and experiment sections. Verify against read_paper before relying on them for training.',
            ].join('\n'),
          }),
          toolCall({
            id: 'hub',
            tool_name: 'search_hub',
            arguments: { repo_type: 'model', query: 'distilbert sentiment' },
            output: '| 91 | [distilbert/distilbert-base-uncased](https://huggingface.co/distilbert/distilbert-base-uncased) | text-classification | apache-2.0 | 1000 | 50 | task match |',
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Research evidence trail' });
    expect(within(panel).getByText('Research evidence trail')).toBeInTheDocument();
    expect(within(panel).getByText('3 steps')).toBeInTheDocument();
    expect(within(panel).getByText('Efficient Fine-Tuning for Small Models')).toBeInTheDocument();
    expect(within(panel).getAllByText('2401.12345').length).toBeGreaterThan(0);
    expect(within(within(panel).getByTestId('research-step-paper')).getByRole('link', { name: 'Open source 1' })).toHaveAttribute('href', 'https://arxiv.org/abs/2401.12345');
    expect(within(panel).getByText('distilbert/distilbert-base-uncased')).toBeInTheDocument();

    const recipeCard = within(panel).getByTestId('research-step-recipe');
    expect(within(recipeCard).queryByText(/IMDb and SST-2/)).not.toBeInTheDocument();

    await user.click(within(recipeCard).getByRole('button', { name: 'Show details for Training recipe for Efficient Fine-Tuning for Small Models' }));

    expect(within(recipeCard).getByText(/IMDb and SST-2/)).toBeInTheDocument();
    expect(within(recipeCard).getByText('deterministic extraction')).toBeInTheDocument();
    expect(within(recipeCard).getByText(/Verify against read_paper/)).toBeInTheDocument();
  });
});
