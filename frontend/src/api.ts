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

export interface DatasetUploadResponse {
  filename: string;
  path: string;
  size_bytes: number;
  preview: string;
}

async function request<T>(path: string, init?: RequestInit, hfToken?: string | null): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers ? (init.headers as Record<string, string>) : {}),
  };
  if (hfToken) {
    headers.Authorization = `Bearer ${hfToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers,
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

export function createSession(payload: CreateSessionRequest, hfToken?: string | null) {
  return request<SessionSummary>('/api/session', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, hfToken);
}

export function sendChatMessage(sessionId: string, payload: ChatRequest, hfToken?: string | null) {
  return request<ChatResponse>(`/api/chat/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }, hfToken);
}

export function resolveApproval(
  sessionId: string,
  approvalId: string,
  payload: ApprovalDecisionRequest,
  hfToken?: string | null,
) {
  return request<ChatResponse>(`/api/approval/${sessionId}/${approvalId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }, hfToken);
}

export function uploadDataset(file: File) {
  return request<DatasetUploadResponse>('/api/datasets/upload', {
    method: 'POST',
    body: file,
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
      'X-Filename': file.name,
    },
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
  const source = new EventSource(`${API_BASE_URL}/api/events/${sessionId}${query}`, {
    withCredentials: true,
  });

  source.onmessage = (message) => {
    options.onEvent(JSON.parse(message.data) as SessionEventPayload);
  };
  source.onerror = () => {
    source.close();
    options.onError();
  };

  return source;
}
