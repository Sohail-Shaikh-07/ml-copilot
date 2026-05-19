from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.llm import LLMResponse
from app.api import create_app
from app.config import AppSettings
from app.storage.repository import SQLiteRepository


class FakeLLMClient:
    def __init__(self, content: str = "Working on it.") -> None:
        self._content = content

    async def chat(self, **kwargs) -> LLMResponse:
        return LLMResponse(model="gpt-test", content=self._content)


class BlockingLLMClient:
    def __init__(self) -> None:
        self.started = threading.Event()

    async def chat(self, **kwargs) -> LLMResponse:
        self.started.set()
        await asyncio.sleep(30)
        return LLMResponse(model="gpt-test", content="Too late.")


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.load(
        environ={
            "ML_COPILOT_WORKSPACE_ROOT": str(tmp_path),
            "ML_COPILOT_DB_PATH": str(tmp_path / "api.db"),
            "LLM_MODEL": "gpt-test",
        }
    )


def test_create_and_list_sessions_via_api(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    created = client.post(
        "/api/session",
        json={"title": "API Session", "metadata": {"source": "test"}},
    )
    listed = client.get("/api/sessions")

    assert created.status_code == 201
    created_body = created.json()
    assert created_body["title"] == "API Session"
    assert created_body["metadata"] == {"source": "test"}

    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body) == 1
    assert listed_body[0]["id"] == created_body["id"]
    assert listed_body[0]["message_count"] == 0


def test_chat_route_persists_messages_and_session_state(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    def loop_factory(app_settings: AppSettings, repository: SQLiteRepository):
        from app.agent.loop import create_agent_loop

        return create_agent_loop(
            app_settings,
            repository=repository,
            llm_client=FakeLLMClient(content="Repository summary ready."),
        )

    app = create_app(settings, loop_factory=loop_factory)
    client = TestClient(app)

    created = client.post("/api/session", json={"title": "Chat Session"})
    session_id = created.json()["id"]

    response = client.post(
        f"/api/chat/{session_id}",
        json={"message": "Analyze the repository layout"},
    )
    messages = client.get(f"/api/session/{session_id}/messages")
    session = client.get(f"/api/session/{session_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "complete"
    assert body["result"]["content"] == "Repository summary ready."
    assert body["session"]["status"] == "idle"
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]

    assert messages.status_code == 200
    assert [message["content"] for message in messages.json()] == [
        "Analyze the repository layout",
        "Repository summary ready.",
    ]

    assert session.status_code == 200
    assert session.json()["message_count"] == 2
    assert session.json()["event_count"] >= 3


def test_missing_session_returns_404(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    response = client.get("/api/session/missing-session")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_event_stream_receives_live_events_for_chat_turn(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    def loop_factory(app_settings: AppSettings, repository: SQLiteRepository):
        from app.agent.loop import create_agent_loop

        return create_agent_loop(
            app_settings,
            repository=repository,
            llm_client=FakeLLMClient(content="Repository summary ready."),
        )

    app = create_app(settings, loop_factory=loop_factory)
    stream_client = TestClient(app)
    chat_client = TestClient(app)

    created = chat_client.post("/api/session", json={"title": "Streaming Session"})
    session_id = created.json()["id"]

    captured: dict[str, object] = {}

    def consume_events() -> None:
        with stream_client.stream("GET", f"/api/events/{session_id}") as response:
            captured["status_code"] = response.status_code
            captured["events"] = _parse_sse_events(response.iter_text())

    consumer = threading.Thread(target=consume_events)
    consumer.start()
    time.sleep(0.1)

    chat_response = chat_client.post(
        f"/api/chat/{session_id}",
        json={"message": "Analyze the repository layout"},
    )

    consumer.join(timeout=5)
    assert not consumer.is_alive()
    assert chat_response.status_code == 200
    assert captured["status_code"] == 200

    events = captured["events"]
    assert isinstance(events, list)
    assert [event["event_type"] for event in events] == [
        "ready",
        "processing",
        "assistant_chunk",
        "assistant_message",
        "turn_complete",
    ]
    assert [event["sequence"] for event in events] == [0, 1, 2, 3, 4]
    assert {event["session_id"] for event in events} == {session_id}
    assert events[-1]["data"] == {"iterations": 1}


def test_event_stream_replays_events_after_last_event_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    def loop_factory(app_settings: AppSettings, repository: SQLiteRepository):
        from app.agent.loop import create_agent_loop

        return create_agent_loop(
            app_settings,
            repository=repository,
            llm_client=FakeLLMClient(content="Repository summary ready."),
        )

    app = create_app(settings, loop_factory=loop_factory)
    client = TestClient(app)

    created = client.post("/api/session", json={"title": "Replay Session"})
    session_id = created.json()["id"]
    client.post(
        f"/api/chat/{session_id}",
        json={"message": "Analyze the repository layout"},
    )

    with client.stream(
        "GET",
        f"/api/events/{session_id}",
        headers={"Last-Event-ID": "1"},
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events(response.iter_text())

    assert [event["event_type"] for event in events] == [
        "assistant_chunk",
        "assistant_message",
        "turn_complete",
    ]
    assert [event["sequence"] for event in events] == [2, 3, 4]
    assert events[0]["data"]["content"] == "Repository summary ready."


def test_interrupt_route_reports_idle_session(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    client = TestClient(app)

    created = client.post("/api/session", json={"title": "Idle Session"})
    session_id = created.json()["id"]

    response = client.post(f"/api/interrupt/{session_id}")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "status": created.json()["status"],
        "interrupted": False,
        "message": "No active turn to interrupt.",
    }


def test_interrupt_route_cancels_active_chat_turn_and_preserves_event(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    llm = BlockingLLMClient()

    def loop_factory(app_settings: AppSettings, repository: SQLiteRepository):
        from app.agent.loop import create_agent_loop

        return create_agent_loop(
            app_settings,
            repository=repository,
            llm_client=llm,
        )

    app = create_app(settings, loop_factory=loop_factory)
    chat_client = TestClient(app)
    interrupt_client = TestClient(app)

    created = interrupt_client.post("/api/session", json={"title": "Interrupt Session"})
    session_id = created.json()["id"]
    captured: dict[str, object] = {}

    def run_chat() -> None:
        captured["response"] = chat_client.post(
            f"/api/chat/{session_id}",
            json={"message": "Start a long turn"},
        )

    worker = threading.Thread(target=run_chat)
    worker.start()

    assert llm.started.wait(timeout=5)
    interrupt_response = interrupt_client.post(f"/api/interrupt/{session_id}")

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert interrupt_response.status_code == 200
    assert interrupt_response.json()["interrupted"] is True

    chat_response = captured["response"]
    assert chat_response.status_code == 200
    body = chat_response.json()
    assert body["result"]["status"] == "interrupted"
    assert body["session"]["status"] == "interrupted"

    with interrupt_client.stream("GET", f"/api/events/{session_id}") as response:
        events = _parse_sse_events(response.iter_text())

    assert response.status_code == 200
    assert events[-1]["event_type"] == "interrupted"


def _parse_sse_events(chunks) -> list[dict[str, object]]:
    buffer = "".join(chunks)
    events: list[dict[str, object]] = []

    for block in buffer.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue

        payload_lines = [line[5:].strip() for line in lines if line.startswith("data:")]
        if not payload_lines:
            continue

        events.append(json.loads("\n".join(payload_lines)))

    return events
