"""SQLite repository layer for sessions, messages, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from app.db import connect_sqlite
from app.storage.models import (
    ApprovalRecord,
    EventRecord,
    MessageRecord,
    PendingApprovalRecord,
    SessionHistory,
    SessionRecord,
    ToolCallRecord,
    utc_now,
)

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
                INSERT INTO sessions (
                    id,
                    title,
                    status,
                    model,
                    metadata_json,
                    created_at,
                    updated_at
                )
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
                    id,
                    session_id,
                    turn_id,
                    role,
                    content,
                    tool_call_id,
                    name,
                    raw_json,
                    sequence,
                    created_at
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
                SELECT
                    id,
                    session_id,
                    turn_id,
                    role,
                    content,
                    tool_call_id,
                    name,
                    raw_json,
                    sequence,
                    created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY sequence ASC, created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def next_message_sequence(self, session_id: str) -> int:
        with connect_sqlite(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) AS max_sequence
                FROM messages
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return int(row["max_sequence"]) + 1

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
                INSERT INTO events (
                    id,
                    session_id,
                    turn_id,
                    event_type,
                    data_json,
                    sequence,
                    created_at
                )
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

    def next_event_sequence(self, session_id: str) -> int:
        with connect_sqlite(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) AS max_sequence
                FROM events
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return int(row["max_sequence"]) + 1

    def add_tool_call(
        self,
        *,
        session_id: str,
        turn_id: str,
        tool_name: str,
        arguments: dict | None,
        status: str,
        requires_approval: bool,
        approval_id: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        output: str | None = None,
        success: bool | None = None,
        error: str | None = None,
        tool_call_id: str | None = None,
    ) -> ToolCallRecord:
        record = ToolCallRecord(
            id=tool_call_id or str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            tool_name=tool_name,
            arguments_json=json.dumps(arguments or {}, sort_keys=True),
            status=status,
            requires_approval=requires_approval,
            approval_id=approval_id,
            started_at=started_at,
            finished_at=finished_at,
            output=output,
            success=success,
            error=error,
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO tool_calls (
                    id,
                    session_id,
                    turn_id,
                    tool_name,
                    arguments_json,
                    status,
                    requires_approval,
                    approval_id,
                    started_at,
                    finished_at,
                    output,
                    success,
                    error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.turn_id,
                    record.tool_name,
                    record.arguments_json,
                    record.status,
                    1 if record.requires_approval else 0,
                    record.approval_id,
                    record.started_at,
                    record.finished_at,
                    record.output,
                    None if record.success is None else int(record.success),
                    record.error,
                ),
            )
            self._touch_session(connection, session_id)
            connection.commit()
        return record

    def get_tool_call(self, tool_call_id: str) -> ToolCallRecord | None:
        with connect_sqlite(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    session_id,
                    turn_id,
                    tool_name,
                    arguments_json,
                    status,
                    requires_approval,
                    approval_id,
                    started_at,
                    finished_at,
                    output,
                    success,
                    error
                FROM tool_calls
                WHERE id = ?
                """,
                (tool_call_id,),
            ).fetchone()
        return _tool_call_from_row(row) if row else None

    def update_tool_call(
        self,
        tool_call_id: str,
        *,
        status: str | None = None,
        approval_id: str | None = None,
        arguments: dict | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        output: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> ToolCallRecord:
        current = self.get_tool_call(tool_call_id)
        if current is None:
            raise KeyError(f"Unknown tool call: {tool_call_id}")

        record = ToolCallRecord(
            id=current.id,
            session_id=current.session_id,
            turn_id=current.turn_id,
            tool_name=current.tool_name,
            arguments_json=(
                json.dumps(arguments, sort_keys=True)
                if arguments is not None
                else current.arguments_json
            ),
            status=status if status is not None else current.status,
            requires_approval=current.requires_approval,
            approval_id=approval_id if approval_id is not None else current.approval_id,
            started_at=started_at if started_at is not None else current.started_at,
            finished_at=finished_at if finished_at is not None else current.finished_at,
            output=output if output is not None else current.output,
            success=success if success is not None else current.success,
            error=error if error is not None else current.error,
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                UPDATE tool_calls
                SET
                    arguments_json = ?,
                    status = ?,
                    approval_id = ?,
                    started_at = ?,
                    finished_at = ?,
                    output = ?,
                    success = ?,
                    error = ?
                WHERE id = ?
                """,
                (
                    record.arguments_json,
                    record.status,
                    record.approval_id,
                    record.started_at,
                    record.finished_at,
                    record.output,
                    None if record.success is None else int(record.success),
                    record.error,
                    record.id,
                ),
            )
            self._touch_session(connection, record.session_id)
            connection.commit()
        return record

    def list_tool_calls(self, session_id: str) -> list[ToolCallRecord]:
        with connect_sqlite(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    session_id,
                    turn_id,
                    tool_name,
                    arguments_json,
                    status,
                    requires_approval,
                    approval_id,
                    started_at,
                    finished_at,
                    output,
                    success,
                    error
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY started_at ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
        return [_tool_call_from_row(row) for row in rows]

    def create_approval(
        self,
        *,
        session_id: str,
        turn_id: str,
        tool_call_id: str,
        status: str = "pending",
        requested_at: str | None = None,
        responded_at: str | None = None,
        user_feedback: str | None = None,
        edited_payload: dict | None = None,
        approval_id: str | None = None,
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            id=approval_id or str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            status=status,
            requested_at=requested_at or utc_now(),
            responded_at=responded_at,
            user_feedback=user_feedback,
            edited_payload_json=(
                json.dumps(edited_payload, sort_keys=True)
                if edited_payload is not None
                else None
            ),
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    id,
                    session_id,
                    turn_id,
                    tool_call_id,
                    status,
                    requested_at,
                    responded_at,
                    user_feedback,
                    edited_payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.turn_id,
                    record.tool_call_id,
                    record.status,
                    record.requested_at,
                    record.responded_at,
                    record.user_feedback,
                    record.edited_payload_json,
                ),
            )
            self._touch_session(connection, session_id)
            connection.commit()
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with connect_sqlite(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    session_id,
                    turn_id,
                    tool_call_id,
                    status,
                    requested_at,
                    responded_at,
                    user_feedback,
                    edited_payload_json
                FROM approvals
                WHERE id = ?
                """,
                (approval_id,),
            ).fetchone()
        return _approval_from_row(row) if row else None

    def update_approval(
        self,
        approval_id: str,
        *,
        status: str | None = None,
        responded_at: str | None = None,
        user_feedback: str | None = None,
        edited_payload: dict | None = None,
    ) -> ApprovalRecord:
        current = self.get_approval(approval_id)
        if current is None:
            raise KeyError(f"Unknown approval: {approval_id}")

        record = ApprovalRecord(
            id=current.id,
            session_id=current.session_id,
            turn_id=current.turn_id,
            tool_call_id=current.tool_call_id,
            status=status if status is not None else current.status,
            requested_at=current.requested_at,
            responded_at=responded_at if responded_at is not None else current.responded_at,
            user_feedback=user_feedback if user_feedback is not None else current.user_feedback,
            edited_payload_json=(
                json.dumps(edited_payload, sort_keys=True)
                if edited_payload is not None
                else current.edited_payload_json
            ),
        )
        with connect_sqlite(self.database_path) as connection:
            connection.execute(
                """
                UPDATE approvals
                SET
                    status = ?,
                    responded_at = ?,
                    user_feedback = ?,
                    edited_payload_json = ?
                WHERE id = ?
                """,
                (
                    record.status,
                    record.responded_at,
                    record.user_feedback,
                    record.edited_payload_json,
                    record.id,
                ),
            )
            self._touch_session(connection, record.session_id)
            connection.commit()
        return record

    def list_pending_approvals(self, session_id: str | None = None) -> list[PendingApprovalRecord]:
        query = """
            SELECT
                a.id AS approval_id,
                a.session_id AS approval_session_id,
                a.turn_id AS approval_turn_id,
                a.tool_call_id AS approval_tool_call_id,
                a.status AS approval_status,
                a.requested_at AS approval_requested_at,
                a.responded_at AS approval_responded_at,
                a.user_feedback AS approval_user_feedback,
                a.edited_payload_json AS approval_edited_payload_json,
                tc.id AS tool_call_id,
                tc.session_id AS tool_call_session_id,
                tc.turn_id AS tool_call_turn_id,
                tc.tool_name AS tool_call_tool_name,
                tc.arguments_json AS tool_call_arguments_json,
                tc.status AS tool_call_status,
                tc.requires_approval AS tool_call_requires_approval,
                tc.approval_id AS tool_call_approval_id,
                tc.started_at AS tool_call_started_at,
                tc.finished_at AS tool_call_finished_at,
                tc.output AS tool_call_output,
                tc.success AS tool_call_success,
                tc.error AS tool_call_error
            FROM approvals a
            INNER JOIN tool_calls tc ON tc.id = a.tool_call_id
            WHERE a.status = 'pending'
        """
        params: tuple[str, ...] = ()
        if session_id is not None:
            query += " AND a.session_id = ?"
            params = (session_id,)
        query += " ORDER BY a.requested_at ASC, a.id ASC"

        with connect_sqlite(self.database_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_pending_approval_from_row(row) for row in rows]

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


def _tool_call_from_row(row: sqlite3.Row) -> ToolCallRecord:
    return ToolCallRecord(
        id=row["id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        tool_name=row["tool_name"],
        arguments_json=row["arguments_json"],
        status=row["status"],
        requires_approval=bool(row["requires_approval"]),
        approval_id=row["approval_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        output=row["output"],
        success=None if row["success"] is None else bool(row["success"]),
        error=row["error"],
    )


def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
    return ApprovalRecord(
        id=row["id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        tool_call_id=row["tool_call_id"],
        status=row["status"],
        requested_at=row["requested_at"],
        responded_at=row["responded_at"],
        user_feedback=row["user_feedback"],
        edited_payload_json=row["edited_payload_json"],
    )


def _pending_approval_from_row(row: sqlite3.Row) -> PendingApprovalRecord:
    return PendingApprovalRecord(
        approval=ApprovalRecord(
            id=row["approval_id"],
            session_id=row["approval_session_id"],
            turn_id=row["approval_turn_id"],
            tool_call_id=row["approval_tool_call_id"],
            status=row["approval_status"],
            requested_at=row["approval_requested_at"],
            responded_at=row["approval_responded_at"],
            user_feedback=row["approval_user_feedback"],
            edited_payload_json=row["approval_edited_payload_json"],
        ),
        tool_call=ToolCallRecord(
            id=row["tool_call_id"],
            session_id=row["tool_call_session_id"],
            turn_id=row["tool_call_turn_id"],
            tool_name=row["tool_call_tool_name"],
            arguments_json=row["tool_call_arguments_json"],
            status=row["tool_call_status"],
            requires_approval=bool(row["tool_call_requires_approval"]),
            approval_id=row["tool_call_approval_id"],
            started_at=row["tool_call_started_at"],
            finished_at=row["tool_call_finished_at"],
            output=row["tool_call_output"],
            success=None if row["tool_call_success"] is None else bool(row["tool_call_success"]),
            error=row["tool_call_error"],
        ),
    )
