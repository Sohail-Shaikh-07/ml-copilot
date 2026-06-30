import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import ArtifactBrowserPanel from './ArtifactBrowserPanel';
import type { ToolCallPayload } from '../types';

function toolCall(overrides: Partial<ToolCallPayload>): ToolCallPayload {
  return {
    id: 'call-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'experiment_workspace',
    arguments: {},
    status: 'success',
    requires_approval: false,
    approval_id: null,
    started_at: '2026-07-01T06:00:00Z',
    finished_at: '2026-07-01T06:01:00Z',
    output: null,
    success: true,
    error: null,
    ...overrides,
  };
}

describe('ArtifactBrowserPanel', () => {
  it('lists artifacts, blocks unsafe paths, and shows bounded previews for selected files', async () => {
    const user = userEvent.setup();

    render(
      <ArtifactBrowserPanel
        toolCalls={[
          toolCall({
            id: 'sandbox-write',
            arguments: { operation: 'write', path: 'src/train.py' },
            output: 'Wrote src/train.py (128 bytes).\n```python\nprint("train")\n```',
          }),
          toolCall({
            id: 'unsafe-read',
            arguments: { operation: 'read', path: 'C:\\Users\\sohai\\.env' },
            output: '### C:\\Users\\sohai\\.env\n```text\nTOKEN=hidden\n```',
          }),
          toolCall({
            id: 'publish-report',
            tool_name: 'publish_model_report',
            arguments: { output_dir: '.ml-copilot/reports/model-a' },
            output: [
              '- README: .ml-copilot/reports/model-a/README.md',
              '- Manifest: .ml-copilot/reports/model-a/publish_manifest.json',
              '',
              '### .ml-copilot/reports/model-a/README.md',
              '```markdown',
              '# Model Card',
              'Evaluation summary and card metadata.',
              '```',
            ].join('\n'),
          }),
        ]}
      />,
    );

    const panel = screen.getByRole('region', { name: 'File and artifact browser' });
    expect(within(panel).getByText('3 safe files')).toBeInTheDocument();
    expect(within(panel).getByText('1 blocked path')).toBeInTheDocument();
    expect(within(panel).getByText('README.md')).toBeInTheDocument();
    expect(within(panel).getAllByText('publish_model_report').length).toBeGreaterThan(0);
    expect(within(panel).getByText('C:\\Users\\sohai\\.env')).toBeInTheDocument();
    expect(within(panel).getByText('Unsafe absolute path is blocked')).toBeInTheDocument();

    await user.click(within(panel).getByRole('button', { name: 'Preview README.md' }));

    const preview = within(panel).getByTestId('artifact-preview');
    expect(within(preview).getByText('.ml-copilot/reports/model-a/README.md')).toBeInTheDocument();
    expect(within(preview).getByText('Markdown')).toBeInTheDocument();
    expect(within(preview).getByText(/# Model Card/)).toBeInTheDocument();
    expect(within(preview).getByText("experiment_workspace operation='read' path='.ml-copilot/reports/model-a/README.md'")).toBeInTheDocument();
  });
});
