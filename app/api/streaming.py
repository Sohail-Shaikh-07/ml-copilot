"""Helpers for replayable SSE session event streaming."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.agent.loop import AgentEvent
from app.storage.models import EventRecord
from app.storage.repository import SQLiteRepository

TERMINAL_EVENT_TYPES = {
    "turn_complete",
    "approval_required",
    "error",
    "interrupted",
}
KEEPALIVE_INTERVAL_SECONDS = 15


class SessionEventStreamManager:
    """Fan out live agent events to per-session SSE subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_subscription_id = 0
        self._subscribers: dict[str, dict[int, queue.Queue[AgentEvent]]] = {}

    def subscribe(self, session_id: str) -> tuple[int, queue.Queue[AgentEvent]]:
        subscription_queue: queue.Queue[AgentEvent] = queue.Queue()
        with self._lock:
            self._next_subscription_id += 1
            subscription_id = self._next_subscription_id
            session_subscribers = self._subscribers.setdefault(session_id, {})
            session_subscribers[subscription_id] = subscription_queue
        return subscription_id, subscription_queue

    def unsubscribe(self, session_id: str, subscription_id: int) -> None:
        with self._lock:
            session_subscribers = self._subscribers.get(session_id)
            if not session_subscribers:
                return
            session_subscribers.pop(subscription_id, None)
            if not session_subscribers:
                self._subscribers.pop(session_id, None)

    def publish(self, event: AgentEvent) -> None:
        with self._lock:
            queues = list(self._subscribers.get(event.session_id, {}).values())
        for subscriber_queue in queues:
            subscriber_queue.put_nowait(event)


def create_event_stream_response(
    *,
    request: Request,
    session_id: str,
    repository: SQLiteRepository,
    stream_manager: SessionEventStreamManager,
) -> StreamingResponse:
    """Create an SSE response that replays persisted events then follows live ones."""
    after_sequence = _last_event_sequence(request)
    subscription_id, live_queue = stream_manager.subscribe(session_id)
    replay_events = repository.list_events_after(session_id, after_sequence)

    async def event_generator():
        last_sequence = after_sequence
        try:
            for record in replay_events:
                payload = _event_payload_from_record(record)
                if payload["sequence"] <= last_sequence:
                    continue
                last_sequence = payload["sequence"]
                yield _format_sse(payload)
                if payload["event_type"] in TERMINAL_EVENT_TYPES:
                    return

            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.to_thread(
                        live_queue.get,
                        True,
                        KEEPALIVE_INTERVAL_SECONDS,
                    )
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue

                payload = _event_payload_from_agent_event(event)
                if payload["sequence"] <= last_sequence:
                    continue
                last_sequence = payload["sequence"]
                yield _format_sse(payload)
                if payload["event_type"] in TERMINAL_EVENT_TYPES:
                    return
        finally:
            stream_manager.unsubscribe(session_id, subscription_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _last_event_sequence(request: Request) -> int:
    raw_value = request.headers.get("last-event-id") or request.query_params.get("after")
    if raw_value is None:
        return -1
    try:
        return max(-1, int(raw_value))
    except (TypeError, ValueError):
        return -1


def _format_sse(payload: dict[str, Any]) -> str:
    sequence = payload["sequence"]
    return f"id: {sequence}\ndata: {json.dumps(payload)}\n\n"


def _event_payload_from_record(record: EventRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.session_id,
        "turn_id": record.turn_id,
        "event_type": record.event_type,
        "data": json.loads(record.data_json),
        "sequence": record.sequence,
        "created_at": record.created_at,
    }


def _event_payload_from_agent_event(event: AgentEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "session_id": event.session_id,
        "turn_id": event.turn_id,
        "event_type": event.event_type,
        "data": event.data,
        "sequence": event.sequence,
        "created_at": event.created_at,
    }
