"""Persistence models for the SQLite repository layer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class SessionRecord:
    id: str
    title: str | None
    status: str
    model: str
    metadata_json: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MessageRecord:
    id: str
    session_id: str
    turn_id: str
    role: str
    content: str
    tool_call_id: str | None
    name: str | None
    raw_json: str
    sequence: int
    created_at: str


@dataclass(frozen=True)
class EventRecord:
    id: str
    session_id: str
    turn_id: str
    event_type: str
    data_json: str
    sequence: int
    created_at: str


@dataclass(frozen=True)
class ToolCallRecord:
    id: str
    session_id: str
    turn_id: str
    tool_name: str
    arguments_json: str
    status: str
    requires_approval: bool
    approval_id: str | None
    started_at: str | None
    finished_at: str | None
    output: str | None
    success: bool | None
    error: str | None


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    session_id: str
    turn_id: str
    tool_call_id: str
    status: str
    requested_at: str
    responded_at: str | None
    user_feedback: str | None
    edited_payload_json: str | None


@dataclass(frozen=True)
class PendingApprovalRecord:
    approval: ApprovalRecord
    tool_call: ToolCallRecord


@dataclass(frozen=True)
class EvalRunRecord:
    id: str
    task_id: str
    session_id: str
    status: str
    score: float | None
    started_at: str
    finished_at: str | None
    report_json: str


@dataclass(frozen=True)
class SessionHistory:
    session: SessionRecord
    messages: list[MessageRecord]
    events: list[EventRecord]
