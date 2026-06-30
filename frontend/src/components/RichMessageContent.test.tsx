import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import RichMessageContent from './RichMessageContent';

describe('RichMessageContent', () => {
  it('renders markdown blocks, tables, links, and copyable code safely', async () => {
    const user = userEvent.setup();
    const content = [
      '## Experiment result',
      '',
      'The run improved **accuracy** and kept `loss` stable.',
      '',
      '- inspect `metrics.json`',
      '- publish the report',
      '',
      '| metric | value |',
      '| --- | ---: |',
      '| accuracy | 0.91 |',
      '',
      '[Open report](https://example.com/report)',
      '',
      '<script>window.__bad = true</script>',
      '',
      '```python',
      'print("hello")',
      '```',
    ].join('\n');

    render(<RichMessageContent content={content} />);

    expect(screen.getByRole('heading', { name: 'Experiment result' })).toBeInTheDocument();
    expect(screen.getAllByText('accuracy')).toHaveLength(2);
    expect(screen.getByRole('list')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open report' })).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.queryByText(/window\.__bad/)).not.toBeInTheDocument();

    const codeBlock = screen.getByTestId('code-block');
    expect(within(codeBlock).getByText('python')).toBeInTheDocument();
    expect(within(codeBlock).getByText('print("hello")')).toBeInTheDocument();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText,
      },
    });

    await user.click(within(codeBlock).getByRole('button', { name: 'Copy code block' }));

    expect(writeText).toHaveBeenCalledWith('print("hello")');
    expect(await within(codeBlock).findByRole('button', { name: 'Copied code block' })).toBeInTheDocument();
  });
});
