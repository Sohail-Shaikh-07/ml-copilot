import type {
  ApprovalDecisionRequest,
  ChatRequest,
  ChatResponse,
  CreateSessionRequest,
  MessagePayload,
  SessionEventPayload,
  SessionDetail,
  SessionSummary,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed with ${response.status} ${response.statusText}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function getApiBaseLabel() {
  return API_BASE_URL || 'same-origin /api';
}

export function fetchSessions() {
  return request<SessionSummary[]>('/api/sessions');
}

export function fetchSession(sessionId: string) {
  return request<SessionDetail>(`/api/session/${sessionId}`);
}

export function fetchMessages(sessionId: string) {
  return request<MessagePayload[]>(`/api/session/${sessionId}/messages`);
}

export function createSession(payload: CreateSessionRequest) {
  return request<SessionSummary>('/api/session', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function sendChatMessage(sessionId: string, payload: ChatRequest) {
  return request<ChatResponse>(`/api/chat/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function resolveApproval(sessionId: string, approvalId: string, payload: ApprovalDecisionRequest) {
  return request<ChatResponse>(`/api/approval/${sessionId}/${approvalId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createSessionEventSource(
  sessionId: string,
  options: {
    after?: number;
    onEvent: (event: SessionEventPayload) => void;
    onError: () => void;
  },
) {
  const query = options.after !== undefined ? `?after=${options.after}` : '';
  const source = new EventSource(`${API_BASE_URL}/api/events/${sessionId}${query}`);

  source.onmessage = (message) => {
    options.onEvent(JSON.parse(message.data) as SessionEventPayload);
  };
  source.onerror = () => {
    source.close();
    options.onError();
  };

  return source;
}
