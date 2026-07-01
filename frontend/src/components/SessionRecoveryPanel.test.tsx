import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import SessionRecoveryPanel from './SessionRecoveryPanel';
import type { ConnectionHealth, RecoverySnapshot } from '../workbenchState';

const snapshot: RecoverySnapshot = {
  sessionId: 'session-1',
  sessionTitle: 'Train model',
  messageCount: 4,
  toolCallCount: 3,
  liveEventCount: 5,
  persistedEventCount: 12,
  lastEventSequence: 11,
  replayedEventCount: 2,
  duplicateEventCount: 1,
  recoveredAt: '2026-07-01T06:05:00Z',
  status: 'recovered',
};

const health: ConnectionHealth = {
  phase: 'stale',
  label: 'stream heartbeat stale',
  tone: 'warning',
  lastEventAgeMs: 125_000,
  canReconnect: true,
};

describe('SessionRecoveryPanel', () => {
  it('shows recovery snapshot, stream health, replay details, and reconnect action', async () => {
    const user = userEvent.setup();
    const onReconnect = vi.fn();

    const { unmount } = render(
      <SessionRecoveryPanel
        health={health}
        onReconnect={onReconnect}
        snapshot={snapshot}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Session recovery' });

    expect(within(panel).getByText('stream heartbeat stale')).toBeInTheDocument();
    expect(within(panel).getByText('Train model')).toBeInTheDocument();
    expect(within(panel).getByText('4 messages')).toBeInTheDocument();
    expect(within(panel).getByText('3 tool calls')).toBeInTheDocument();
    expect(within(panel).getByText('5 live events')).toBeInTheDocument();
    expect(within(panel).getByText('sequence 11')).toBeInTheDocument();
    expect(within(panel).getByText('2 replayed')).toBeInTheDocument();
    expect(within(panel).getByText('1 duplicate skipped')).toBeInTheDocument();
    expect(within(panel).getByText('last event 2m 5s ago')).toBeInTheDocument();

    await user.click(within(panel).getByRole('button', { name: 'Reconnect with replay' }));

    expect(onReconnect).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('renders an empty recovery state without reconnect when no session is selected', () => {
    render(
      <SessionRecoveryPanel
        health={{
          phase: 'idle',
          label: 'stream idle',
          tone: 'neutral',
          lastEventAgeMs: null,
          canReconnect: false,
        }}
        onReconnect={vi.fn()}
        snapshot={null}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Session recovery' });
    expect(within(panel).getByText('No session recovery snapshot yet.')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Reconnect with replay' })).not.toBeInTheDocument();
  });
});
