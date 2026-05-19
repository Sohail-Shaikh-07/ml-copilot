from __future__ import annotations

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
