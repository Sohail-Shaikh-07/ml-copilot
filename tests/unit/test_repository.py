from pathlib import Path

from app.storage.repository import SQLiteRepository


def test_initialize_creates_expected_tables(tmp_path: Path) -> None:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")

    repository.initialize()

    table_names = {
        row[0]
        for row in repository_path_tables(repository.database_path)
    }

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
