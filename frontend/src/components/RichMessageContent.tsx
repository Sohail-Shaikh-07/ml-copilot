import { isValidElement, useMemo, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface RichMessageContentProps {
  content: string;
  isStreaming?: boolean;
}

function safeHref(value: string | undefined) {
  if (!value) return undefined;
  if (value.startsWith('#') || value.startsWith('/')) return value;

  try {
    const parsed = new URL(value);
    return ['http:', 'https:', 'mailto:'].includes(parsed.protocol) ? value : undefined;
  } catch {
    return undefined;
  }
}

function textFromChildren(children: ReactNode): string {
  if (Array.isArray(children)) {
    return children.map(textFromChildren).join('');
  }
  return typeof children === 'string' || typeof children === 'number' ? String(children) : '';
}

function CodeBlock({ children, className }: { children: ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false);
  const code = textFromChildren(children).replace(/\n$/, '');
  const language = /language-(\w+)/.exec(className ?? '')?.[1];

  async function handleCopy() {
    await navigator.clipboard?.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="rich-code-block" data-testid="code-block">
      <div className="rich-code-header">
        <span>{language ?? 'code'}</span>
        <button
          className="ghost-button rich-copy-button"
          type="button"
          aria-label={copied ? 'Copied code block' : 'Copy code block'}
          onClick={() => void handleCopy()}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>
        <code className={className}>{code}</code>
      </pre>
    </div>
  );
}

export default function RichMessageContent({ content, isStreaming = false }: RichMessageContentProps) {
  const [expanded, setExpanded] = useState(false);
  const shouldCollapse = content.length > 3600 && !expanded;
  const displayContent = shouldCollapse ? `${content.slice(0, 3600)}\n\n...` : content;

  const components = useMemo(
    () => ({
      a: ({ href, children }: { href?: string; children?: ReactNode }) => {
        const resolvedHref = safeHref(href);
        return resolvedHref ? (
          <a href={resolvedHref} rel="noopener noreferrer" target="_blank">
            {children}
          </a>
        ) : (
          <span>{children}</span>
        );
      },
      code: ({ children, className }: { children?: ReactNode; className?: string }) => (
        <code className={className}>{children}</code>
      ),
      pre: ({ children }: { children?: ReactNode }) => {
        if (isValidElement<{ children?: ReactNode; className?: string }>(children)) {
          return <CodeBlock className={children.props.className}>{children.props.children}</CodeBlock>;
        }
        return <CodeBlock>{children}</CodeBlock>;
      },
    }),
    [],
  );

  return (
    <div className={`rich-message-content${isStreaming ? ' streaming' : ''}`}>
      <ReactMarkdown components={components} remarkPlugins={[remarkGfm]} skipHtml>
        {displayContent}
      </ReactMarkdown>
      {content.length > 3600 ? (
        <button className="ghost-button rich-expand-button" type="button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Show less' : 'Show full message'}
        </button>
      ) : null}
    </div>
  );
}
