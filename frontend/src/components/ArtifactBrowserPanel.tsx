import { useMemo, useState } from 'react';

import { artifactReadAction, buildArtifactBrowserItems } from '../artifactBrowser';
import type { ArtifactBrowserItem } from '../artifactBrowser';
import type { ToolCallPayload } from '../types';

interface ArtifactBrowserPanelProps {
  toolCalls: ToolCallPayload[];
}

function formatCount(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function statusClass(item: ArtifactBrowserItem) {
  return item.safe ? 'success' : 'warning';
}

export default function ArtifactBrowserPanel({ toolCalls }: ArtifactBrowserPanelProps) {
  const items = useMemo(() => buildArtifactBrowserItems(toolCalls), [toolCalls]);
  const safeItems = items.filter((item) => item.safe);
  const blockedItems = items.filter((item) => !item.safe);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = items.find((item) => item.id === selectedId) ?? safeItems[0] ?? items[0] ?? null;

  return (
    <section className="artifact-browser-panel" id="artifact-browser" aria-label="File and artifact browser">
      <div className="artifact-browser-header">
        <div>
          <p className="panel-label">Artifacts</p>
          <h3>File and artifact browser</h3>
          <p className="muted">Safe, bounded previews recovered from persisted session tool output.</p>
        </div>
        <div className="runtime-detail-counts">
          <span className="status-chip success">{formatCount(safeItems.length, 'safe file')}</span>
          <span className="status-chip warning">{formatCount(blockedItems.length, 'blocked path')}</span>
        </div>
      </div>

      {items.length === 0 ? (
        <p className="muted">Generated artifacts, reports, manifests, and sandbox files will appear here after tools produce them.</p>
      ) : (
        <div className="artifact-browser-layout">
          <div className="artifact-browser-list">
            {items.map((item) => (
              <article className={`artifact-browser-item ${item.safe ? '' : 'blocked'}`} key={item.id}>
                <div>
                  <span className={`status-chip ${statusClass(item)}`}>{item.safe ? item.kind : 'Blocked'}</span>
                  <strong>{item.fileName}</strong>
                  <code>{item.path}</code>
                </div>
                <dl>
                  <div>
                    <dt>Source</dt>
                    <dd>{item.provenance}</dd>
                  </div>
                  {item.sizeLabel ? (
                    <div>
                      <dt>Size</dt>
                      <dd>{item.sizeLabel}</dd>
                    </div>
                  ) : null}
                </dl>
                {item.blockedReason ? <p className="artifact-browser-warning">{item.blockedReason}</p> : null}
                <button
                  className="ghost-button"
                  type="button"
                  disabled={!item.safe}
                  onClick={() => setSelectedId(item.id)}
                  aria-label={`Preview ${item.fileName}`}
                >
                  {item.safe ? 'Preview' : 'Blocked'}
                </button>
              </article>
            ))}
          </div>

          {selected ? (
            <article className="artifact-browser-preview" data-testid="artifact-preview">
              <div className="runtime-detail-card-head">
                <div>
                  <span>{selected.kind}</span>
                  <h4>{selected.fileName}</h4>
                </div>
                <span className={`status-chip ${statusClass(selected)}`}>{selected.safe ? 'safe' : 'blocked'}</span>
              </div>
              <code>{selected.path}</code>
              <p className="muted">Provenance: {selected.provenance}</p>
              {selected.safe ? (
                <>
                  <pre>{selected.preview ?? 'No text preview was captured for this artifact yet.'}</pre>
                  <div className="runtime-detail-actions">
                    <code>{artifactReadAction(selected.path)}</code>
                  </div>
                </>
              ) : (
                <p className="artifact-browser-warning">{selected.blockedReason}</p>
              )}
            </article>
          ) : null}
        </div>
      )}
    </section>
  );
}
