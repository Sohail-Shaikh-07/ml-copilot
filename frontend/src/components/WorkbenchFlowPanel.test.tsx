import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import WorkbenchFlowPanel from './WorkbenchFlowPanel';
import { phase5WorkbenchFixture } from '../test/workbenchFixtures';

describe('WorkbenchFlowPanel', () => {
  it('guides users through the full autonomous workflow with panel links and resume state', () => {
    const fixture = phase5WorkbenchFixture();

    render(
      <WorkbenchFlowPanel
        messages={fixture.messages}
        recovery={fixture.recoverySnapshot}
        session={fixture.activeSession}
        toolCalls={fixture.toolCalls}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Autonomous workflow guide' });
    expect(within(panel).getByText('8 / 8 stages complete')).toBeInTheDocument();
    expect(within(panel).getByText('Recovered through event #9')).toBeInTheDocument();
    expect(within(panel).getByText('Choose model and operating mode')).toBeInTheDocument();
    expect(within(panel).getByText('Research papers, recipes, and Hub candidates')).toBeInTheDocument();
    expect(within(panel).getByText('Generate final report and publish intentionally')).toBeInTheDocument();

    expect(within(panel).getByRole('link', { name: 'Open Choose model and operating mode' })).toHaveAttribute('href', '#model-provider-controls');
    expect(within(panel).getByRole('link', { name: 'Open Run sandbox or hosted jobs' })).toHaveAttribute('href', '#runtime-details');
    expect(within(panel).getByRole('link', { name: 'Open Run evals and check release gates' })).toHaveAttribute('href', '#eval-dashboard');
    expect(within(panel).getByRole('link', { name: 'Open Generate final report and publish intentionally' })).toHaveAttribute('href', '#publishing-panel');

    const walkthrough = within(panel).getByRole('list', { name: 'End-to-end walkthrough' });
    expect(within(walkthrough).getAllByRole('listitem')).toHaveLength(8);
    expect(within(walkthrough).getByText(/Choose provider/)).toBeInTheDocument();
    expect(within(walkthrough).getByText(/Generate the final report/)).toBeInTheDocument();
  });
});
