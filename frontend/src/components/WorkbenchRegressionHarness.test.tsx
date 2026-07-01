import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { renderPhase5WorkbenchHarness } from '../test/workbenchFixtures';

function expectLink(name: string, href: string) {
  expect(screen.getAllByRole('link', { name }).some((link) => link.getAttribute('href') === href)).toBe(true);
}

describe('Phase 5 workbench regression harness', () => {
  it('composes the workbench panels around one shared session fixture', async () => {
    const user = userEvent.setup();
    const onReconnect = vi.fn();
    renderPhase5WorkbenchHarness({ onReconnect });

    expect(screen.getByRole('region', { name: 'Model and provider controls' })).toBeInTheDocument();
    expect(screen.getByText('Provider: Z.ai')).toBeInTheDocument();
    expect(screen.getAllByText('Regression fixture assistant response').length).toBeGreaterThanOrEqual(1);

    const recovery = screen.getByRole('region', { name: 'Session recovery' });
    expect(within(recovery).getByText('stream heartbeat stale')).toBeInTheDocument();
    await user.click(within(recovery).getByRole('button', { name: 'Reconnect with replay' }));
    expect(onReconnect).toHaveBeenCalledTimes(1);

    expect(screen.getByRole('region', { name: 'Hugging Face job progress' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Usage and cost estimate' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Runtime detail panels' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Final report and publishing UI' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Research evidence trail' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Eval suite dashboard' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'File and artifact browser' })).toBeInTheDocument();
    expect(screen.getByText('Tool trace')).toBeInTheDocument();

    expectLink('Open artifact browser', '#artifact-browser');
    expectLink('Open publishing panel', '#publishing-panel');
    expectLink('Open research trail', '#research-trail');
    expectLink('Open eval artifacts', '#artifact-browser');
    expectLink('Open runtime panel', '#runtime-details');
  });
});
