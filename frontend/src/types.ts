export interface CreateSessionRequest {
  title?: string | null;
  model?: string | null;
  metadata?: Record<string, unknown>;
}

export interface SessionSummary {
  id: string;
  title: string | null;
  status: string;
  model: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  message_count: number;
  event_count: number;
  pending_approval_count: number;
}

export interface PendingApprovalPayload {
  approval_id: string;
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ToolCallPayload {
  id: string;
  session_id: string;
  turn_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: string;
  requires_approval: boolean;
  approval_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  output: string | null;
  success: boolean | null;
  error: string | null;
}

export interface SessionDetail extends SessionSummary {
  pending_approvals: PendingApprovalPayload[];
  tool_calls: ToolCallPayload[];
}

export interface MessagePayload {
  id: string;
  session_id: string;
  turn_id: string;
  role: string;
  content: string;
  tool_call_id: string | null;
  name: string | null;
  raw: Record<string, unknown>;
  sequence: number;
  created_at: string;
}
