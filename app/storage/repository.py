"""SQLite repository layer for sessions, messages, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from app.db import connect_sqlite
from app.storage.models import EventRecord, MessageRecord, SessionHistory, SessionRecord, utc_now


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        title TEXT,
        status TEXT NOT NULL,
        model TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tool_call_id TEXT,
        name TEXT,
        raw_json TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        data_json TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        arguments_json TEXT NOT NULL,
        status TEXT NOT NULL,
        requires_approval INTEGER NOT NULL,
        approval_id TEXT,
        started_at TEXT,
        finished_at TEXT,
        output TEXT,
        success INTEGER,
        error TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        tool_call_id TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_at TEXT NOT NULL,
        responded_at TEXT,
        user_feedback TEXT,
        edited_payload_json TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_runs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        status TEXT NOT NULL,
        score REAL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        report_json TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )
    """,
)


class SQLiteRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        with connect_sqlite(self.database_path) as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.commit()

    def create_session(
        self,
        *,
        model: str,
        title: str | None = None,
        status: str = "active",
        metadata: dict | None = None,
        session_id: str | None = None,
    ) -> SessionRecord:
        now = utc_now()
        record = SessionRecord(
            id=session_id or str(uuid.uuid4()),
            title=title,
            status=status,
            model=model,
            metadata_json=json.dumps(metadata or {}, sort_keys=True),
            created_at=now,
            updated_at=now,
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, title, status, model, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.title,
                    record.status,
                    record.model,
                    record.metadata_json,
                    record.created_at,
                    record.updated_at,
                ),
            )
            connection.commit()
        return record

    def get_session(self, session_id: str) -> SessionRecord | None:
        with connect_sqlite(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT id, title, status, model, metadata_json, created_at, updated_at
                FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        model: str | None = None,
        metadata: dict | None = None,
    ) -> SessionRecord:
        current = self.get_session(session_id)
        if current is None:
            raise KeyError(f"Unknown session: {session_id}")

        record = SessionRecord(
            id=current.id,
            title=title if title is not None else current.title,
            status=status if status is not None else current.status,
            model=model if model is not None else current.model,
            metadata_json=json.dumps(
                metadata if metadata is not None else json.loads(current.metadata_json),
                sort_keys=True,
            ),
            created_at=current.created_at,
            updated_at=utc_now(),
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                UPDATE sessions
                SET title = ?, status = ?, model = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    record.title,
                    record.status,
                    record.model,
                    record.metadata_json,
                    record.updated_at,
                    record.id,
                ),
            )
            connection.commit()
        return record

    def list_sessions(self) -> list[SessionRecord]:
        with connect_sqlite(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, title, status, model, metadata_json, created_at, updated_at
                FROM sessions
                ORDER BY created_at ASC
                """
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def add_message(
        self,
        *,
        session_id: str,
        turn_id: str,
        role: str,
        content: str,
        sequence: int,
        tool_call_id: str | None = None,
        name: str | None = None,
        raw: dict | None = None,
        message_id: str | None = None,
    ) -> MessageRecord:
        record = MessageRecord(
            id=message_id or str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            name=name,
            raw_json=json.dumps(raw or {}, sort_keys=True),
            sequence=sequence,
            created_at=utc_now(),
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO messages (
                    id, session_id, turn_id, role, content, tool_call_id, name, raw_json, sequence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.turn_id,
                    record.role,
                    record.content,
                    record.tool_call_id,
                    record.name,
                    record.raw_json,
                    record.sequence,
                    record.created_at,
                ),
            )
            self._touch_session(connection, session_id)
            connection.commit()
        return record

    def list_messages(self, session_id: str) -> list[MessageRecord]:
        with connect_sqlite(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, turn_id, role, content, tool_call_id, name, raw_json, sequence, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY sequence ASC, created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def add_event(
        self,
        *,
        session_id: str,
        turn_id: str,
        event_type: str,
        data: dict | None,
        sequence: int,
        event_id: str | None = None,
    ) -> EventRecord:
        record = EventRecord(
            id=event_id or str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            data_json=json.dumps(data or {}, sort_keys=True),
            sequence=sequence,
            created_at=utc_now(),
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO events (id, session_id, turn_id, event_type, data_json, sequence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.turn_id,
                    record.event_type,
                    record.data_json,
                    record.sequence,
                    record.created_at,
                ),
            )
            self._touch_session(connection, session_id)
            connection.commit()
        return record

    def list_events(self, session_id: str) -> list[EventRecord]:
        with connect_sqlite(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, turn_id, event_type, data_json, sequence, created_at
                FROM events
                WHERE session_id = ?
                ORDER BY sequence ASC, created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def list_events_after(self, session_id: str, sequence: int) -> list[EventRecord]:
        with connect_sqlite(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT id, session_id, turn_id, event_type, data_json, sequence, created_at
                FROM events
                WHERE session_id = ? AND sequence > ?
                ORDER BY sequence ASC, created_at ASC
                """,
                (session_id, sequence),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def get_session_history(self, session_id: str) -> SessionHistory:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Unknown session: {session_id}")
        return SessionHistory(
            session=session,
            messages=self.list_messages(session_id),
            events=self.list_events(session_id),
        )

    def delete_session(self, session_id: str) -> None:
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                DELETE FROM sessions
                WHERE id = ?
                """,
                (session_id,),
            )
            connection.commit()

    def _touch_session(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            """
            UPDATE sessions
            SET updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), session_id),
        )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        model=row["model"],
        metadata_json=row["metadata_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(
        id=row["id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        role=row["role"],
        content=row["content"],
        tool_call_id=row["tool_call_id"],
        name=row["name"],
        raw_json=row["raw_json"],
        sequence=row["sequence"],
        created_at=row["created_at"],
    )


def _event_from_row(row: sqlite3.Row) -> EventRecord:
    return EventRecord(
        id=row["id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        event_type=row["event_type"],
        data_json=row["data_json"],
        sequence=row["sequence"],
        created_at=row["created_at"],
    )
