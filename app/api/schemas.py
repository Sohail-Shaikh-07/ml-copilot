"""Pydantic schemas for the ML Copilot HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    system_prompt: str | None = None


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    user_feedback: str | None = None
    edited_arguments: dict[str, Any] | None = None
    system_prompt: str | None = None


class PendingApprovalPayload(BaseModel):
    approval_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ToolCallPayload(BaseModel):
    id: str
    session_id: str
    turn_id: str
    tool_name: str
    arguments: dict[str, Any]
    status: str
    requires_approval: bool
    approval_id: str | None
    started_at: str | None
    finished_at: str | None
    output: str | None
    success: bool | None
    error: str | None


class MessagePayload(BaseModel):
    id: str
    session_id: str
    turn_id: str
    role: str
    content: str
    tool_call_id: str | None
    name: str | None
    raw: dict[str, Any]
    sequence: int
    created_at: str


class SessionSummary(BaseModel):
    id: str
    title: str | None
    status: str
    model: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    message_count: int
    event_count: int
    pending_approval_count: int


class SessionDetail(SessionSummary):
    pending_approvals: list[PendingApprovalPayload] = Field(default_factory=list)
    tool_calls: list[ToolCallPayload] = Field(default_factory=list)


class TurnResultPayload(BaseModel):
    status: str
    content: str | None = None
    iterations: int | None = None
    approval_ids: list[str] = Field(default_factory=list)
    pending_approvals: list[PendingApprovalPayload] = Field(default_factory=list)
    resolved_approval_id: str | None = None


class ChatResponse(BaseModel):
    session: SessionDetail
    result: TurnResultPayload
    messages: list[MessagePayload]


class InterruptResponse(BaseModel):
    session_id: str
    status: str
    interrupted: bool
    message: str
