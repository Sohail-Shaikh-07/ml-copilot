import { useEffect, useState } from 'react';
import type { ApprovalDecisionRequest, PendingApprovalPayload } from '../types';

interface ApprovalDialogProps {
  pendingApprovals: PendingApprovalPayload[];
  resolving: boolean;
  onResolve: (approvalId: string, payload: ApprovalDecisionRequest) => Promise<void>;
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

export default function ApprovalDialog({ pendingApprovals, resolving, onResolve }: ApprovalDialogProps) {
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(null);
  const [argumentText, setArgumentText] = useState('');
  const [feedback, setFeedback] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);

  const selectedApproval =
    pendingApprovals.find((approval) => approval.approval_id === selectedApprovalId) ?? pendingApprovals[0] ?? null;
  const originalArgumentText = selectedApproval ? formatJson(selectedApproval.arguments) : '';
  const hasArgumentEdits = argumentText.trim() !== originalArgumentText.trim();

  useEffect(() => {
    const next = pendingApprovals[0] ?? null;
    setSelectedApprovalId((current) =>
      current && pendingApprovals.some((approval) => approval.approval_id === current)
        ? current
        : next?.approval_id ?? null,
    );
  }, [pendingApprovals]);

  useEffect(() => {
    if (!selectedApproval) {
      setArgumentText('');
      setFeedback('');
      setLocalError(null);
      return;
    }

    setArgumentText(formatJson(selectedApproval.arguments));
    setFeedback('');
    setLocalError(null);
  }, [selectedApproval?.approval_id]);

  async function submitDecision(approved: boolean, includeEditedArguments: boolean) {
    if (!selectedApproval) return;

    setLocalError(null);
    let editedArguments: Record<string, unknown> | null = null;

    if (includeEditedArguments) {
      try {
        const parsed = JSON.parse(argumentText) as unknown;
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          setLocalError('Edited arguments must be a JSON object.');
          return;
        }
        editedArguments = parsed as Record<string, unknown>;
      } catch {
        setLocalError('Edited arguments are not valid JSON.');
        return;
      }
    }

    await onResolve(selectedApproval.approval_id, {
      approved,
      user_feedback: feedback.trim() || null,
      edited_arguments: editedArguments,
    });
  }

  if (!selectedApproval) {
    return (
      <section className="approval-dialog approval-empty">
        <div>
          <p className="panel-label">Approval dialog</p>
          <h3>No pending approvals</h3>
        </div>
        <p className="muted">When the agent needs permission to run a command or patch, the review dialog appears here.</p>
      </section>
    );
  }

  return (
    <section className="approval-dialog">
      <div className="approval-dialog-header">
        <div>
          <p className="panel-label">Approval dialog</p>
          <h3>{selectedApproval.tool_name}</h3>
        </div>
        <span className="status-chip warning">{shortId(selectedApproval.approval_id)}</span>
      </div>

      {pendingApprovals.length > 1 ? (
        <div className="approval-tabs" aria-label="Pending approvals">
          {pendingApprovals.map((approval) => (
            <button
              key={approval.approval_id}
              type="button"
              className={approval.approval_id === selectedApproval.approval_id ? 'active' : ''}
              onClick={() => setSelectedApprovalId(approval.approval_id)}
            >
              {approval.tool_name} / {shortId(approval.approval_id)}
            </button>
          ))}
        </div>
      ) : null}

      <div className="approval-payload">
        <div className="approval-section-label">
          <strong>Exact payload</strong>
          <span>{selectedApproval.tool_call_id}</span>
        </div>
        <pre>{originalArgumentText}</pre>
      </div>

      <label className="approval-edit-field">
        Edited arguments
        <textarea
          rows={8}
          value={argumentText}
          onChange={(event) => setArgumentText(event.target.value)}
          spellCheck={false}
          disabled={resolving}
        />
      </label>

      <label className="approval-feedback-field">
        Feedback
        <textarea
          rows={3}
          placeholder="Explain the approval, rejection, or requested change."
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          disabled={resolving}
        />
      </label>

      {localError ? <p className="approval-error">{localError}</p> : null}

      <div className="approval-actions">
        <button className="ghost-button danger-action" type="button" disabled={resolving} onClick={() => void submitDecision(false, false)}>
          Reject
        </button>
        <button className="ghost-button" type="button" disabled={resolving || !feedback.trim()} onClick={() => void submitDecision(false, false)}>
          Send feedback
        </button>
        <button className="ghost-button" type="button" disabled={resolving || !hasArgumentEdits} onClick={() => void submitDecision(true, true)}>
          Approve edited
        </button>
        <button className="primary-button" type="button" disabled={resolving} onClick={() => void submitDecision(true, false)}>
          Approve
        </button>
      </div>
    </section>
  );
}
