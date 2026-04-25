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
