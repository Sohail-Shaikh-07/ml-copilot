import { describe, expect, it } from 'vitest';

import { buildArtifactBrowserItems } from './artifactBrowser';
import type { ToolCallPayload } from './types';

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

describe('buildArtifactBrowserItems', () => {
  it('extracts safe artifacts with provenance, bounded previews, and blocked unsafe paths', () => {
    const items = buildArtifactBrowserItems([
      toolCall({
        id: 'sandbox-write',
        arguments: { operation: 'write', path: 'src/train.py' },
        output: 'Wrote src/train.py (128 bytes).\n```python\nprint("train")\n```',
      }),
      toolCall({
        id: 'sandbox-read',
        arguments: { operation: 'read', path: '../secrets.env' },
        output: '### ../secrets.env\n```text\nHF_TOKEN=should-not-open\n```',
      }),
      toolCall({
        id: 'publish-report',
        tool_name: 'publish_model_report',
        arguments: { output_dir: '.ml-copilot/reports/model-a' },
        output: [
          'Prepared model publishing assets.',
          '- README: .ml-copilot/reports/model-a/README.md',
          '- Final report: .ml-copilot/reports/model-a/FINAL_REPORT.md',
          '- Manifest: .ml-copilot/reports/model-a/publish_manifest.json',
          '',
          '### .ml-copilot/reports/model-a/README.md',
          '```markdown',
          '# Model Card',
          'This model was evaluated on a fixture dataset.',
          '```',
        ].join('\n'),
      }),
    ]);

    expect(items.map((item) => item.path)).toContain('src/train.py');
    expect(items.map((item) => item.path)).toContain('.ml-copilot/reports/model-a/README.md');
    expect(items.map((item) => item.path)).toContain('../secrets.env');

    const readme = items.find((item) => item.path.endsWith('README.md'));
    expect(readme).toMatchObject({
      fileName: 'README.md',
      kind: 'Markdown',
      provenance: 'publish_model_report',
      safe: true,
      sizeLabel: null,
    });
    expect(readme?.preview).toContain('# Model Card');

    const trainFile = items.find((item) => item.path === 'src/train.py');
    expect(trainFile).toMatchObject({
      fileName: 'train.py',
      kind: 'Python',
      sizeLabel: '128 B',
      safe: true,
    });

    const unsafe = items.find((item) => item.path === '../secrets.env');
    expect(unsafe).toMatchObject({
      safe: false,
      blockedReason: 'Path traversal is blocked',
      preview: null,
    });
  });
});
