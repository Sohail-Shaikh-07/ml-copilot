from pathlib import Path

from app.storage.repository import SQLiteRepository


def test_initialize_creates_expected_tables(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")

    repository.initialize()

    table_names = {row[0] for row in repository_path_tables(repository.database_path)}

    assert {
        "sessions",
        "messages",
        "events",
        "tool_calls",
        "approvals",
        "eval_runs",
    }.issubset(table_names)


def test_create_and_list_sessions(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()

    created = repository.create_session(
        session_id="session-1",
        title="Repo analysis",
        model="gpt-5.4",
        metadata={"source": "test"},
    )
    fetched = repository.get_session("session-1")
    listed = repository.list_sessions()

    assert fetched == created
    assert listed == [created]


def test_add_message_and_event_updates_session_history(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()
    session = repository.create_session(
        session_id="session-1",
        title="Chat",
        model="gpt-5.4",
    )

    message = repository.add_message(
        session_id=session.id,
        turn_id="turn-1",
        role="user",
        content="Analyze this repo",
        sequence=1,
        raw={"role": "user"},
    )
    event = repository.add_event(
        session_id=session.id,
        turn_id="turn-1",
        event_type="processing",
        data={"status": "started"},
        sequence=1,
    )

    messages = repository.list_messages(session.id)
    events = repository.list_events(session.id)
    refreshed = repository.get_session(session.id)

    assert messages == [message]
    assert events == [event]
    assert refreshed is not None
    assert refreshed.updated_at >= session.updated_at


def test_update_session_and_load_full_history(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()
    repository.create_session(
        session_id="session-1",
        title="Initial",
        model="gpt-5.4",
        metadata={"source": "test"},
    )
    repository.add_message(
        session_id="session-1",
        turn_id="turn-1",
        role="user",
        content="Hello",
        sequence=1,
    )
    repository.add_event(
        session_id="session-1",
        turn_id="turn-1",
        event_type="processing",
        data={"status": "started"},
        sequence=1,
    )

    updated = repository.update_session(
        "session-1",
        title="Updated",
        status="idle",
        metadata={"source": "updated"},
    )
    history = repository.get_session_history("session-1")

    assert updated.title == "Updated"
    assert updated.status == "idle"
    assert updated.metadata_json == '{"source": "updated"}'
    assert history.session == updated
    assert len(history.messages) == 1
    assert len(history.events) == 1


def test_list_events_after_and_delete_session(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()
    repository.create_session(
        session_id="session-1",
        title="Replay",
        model="gpt-5.4",
    )
    repository.add_event(
        session_id="session-1",
        turn_id="turn-1",
        event_type="processing",
        data={"status": "started"},
        sequence=1,
    )
    second = repository.add_event(
        session_id="session-1",
        turn_id="turn-1",
        event_type="assistant_message",
        data={"content": "done"},
        sequence=2,
    )

    replay_events = repository.list_events_after("session-1", 1)
    repository.delete_session("session-1")

    assert replay_events == [second]
    assert repository.get_session("session-1") is None
    assert repository.list_messages("session-1") == []
    assert repository.list_events("session-1") == []


def test_tool_call_and_approval_lifecycle(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()
    repository.create_session(
        session_id="session-1",
        title="Approvals",
        model="gpt-5.4",
    )

    tool_call = repository.add_tool_call(
        session_id="session-1",
        turn_id="turn-1",
        tool_name="run_command",
        arguments={"command": "pytest"},
        status="pending_approval",
        requires_approval=True,
        tool_call_id="call-1",
    )
    approval = repository.create_approval(
        session_id="session-1",
        turn_id="turn-1",
        tool_call_id=tool_call.id,
        approval_id="approval-1",
    )
    repository.update_tool_call(tool_call.id, approval_id=approval.id)

    pending = repository.list_pending_approvals("session-1")
    resolved_approval = repository.update_approval(
        approval.id,
        status="approved",
        responded_at="2026-05-09T00:00:00+00:00",
        user_feedback="looks good",
        edited_payload={"command": "pytest -q"},
    )
    resolved_tool_call = repository.update_tool_call(
        tool_call.id,
        status="completed",
        arguments={"command": "pytest -q"},
        finished_at="2026-05-09T00:00:01+00:00",
        output="ok",
        success=True,
    )

    assert len(pending) == 1
    assert pending[0].approval.id == "approval-1"
    assert pending[0].tool_call.id == "call-1"
    assert resolved_approval.status == "approved"
    assert resolved_approval.edited_payload_json == '{"command": "pytest -q"}'
    assert resolved_tool_call.status == "completed"
    assert resolved_tool_call.output == "ok"
    assert repository.list_pending_approvals("session-1") == []


def test_next_sequences_advance_with_history(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()
    repository.create_session(
        session_id="session-1",
        title="Sequence",
        model="gpt-5.4",
    )

    assert repository.next_message_sequence("session-1") == 0
    assert repository.next_event_sequence("session-1") == 0

    repository.add_message(
        session_id="session-1",
        turn_id="turn-1",
        role="user",
        content="hello",
        sequence=0,
    )
    repository.add_event(
        session_id="session-1",
        turn_id="turn-1",
        event_type="processing",
        data={},
        sequence=0,
    )

    assert repository.next_message_sequence("session-1") == 1
    assert repository.next_event_sequence("session-1") == 1


def repository_path_tables(database_path: Path) -> list[tuple[str]]:
    import sqlite3

    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
    finally:
        connection.close()
