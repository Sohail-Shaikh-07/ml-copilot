"""Runtime coordination helpers for active API requests."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

from app.agent.loop import AgentLoop


@dataclass(frozen=True)
class ActiveTurn:
    """A currently running agent turn for a session."""

    session_id: str
    loop: AgentLoop
    task: asyncio.Task[Any]
    event_loop: asyncio.AbstractEventLoop


class ActiveTurnManager:
    """Track running turns so another request can interrupt them safely."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: dict[str, ActiveTurn] = {}

    def register(self, session_id: str, loop: AgentLoop) -> bool:
        """Register the current task as the active turn for a session."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Cannot register an active turn outside an asyncio task.")

        active_turn = ActiveTurn(
            session_id=session_id,
            loop=loop,
            task=task,
            event_loop=asyncio.get_running_loop(),
        )
        with self._lock:
            if session_id in self._turns:
                return False
            self._turns[session_id] = active_turn
        return True

    def unregister(self, session_id: str, task: asyncio.Task[Any] | None = None) -> None:
        """Remove an active turn if it still belongs to the given task."""
        with self._lock:
            active_turn = self._turns.get(session_id)
            if active_turn is None:
                return
            if task is not None and active_turn.task is not task:
                return
            self._turns.pop(session_id, None)

    def interrupt(self, session_id: str) -> bool:
        """Request interruption of an active session turn."""
        with self._lock:
            active_turn = self._turns.get(session_id)

        if active_turn is None:
            return False

        active_turn.loop.interrupt()
        active_turn.event_loop.call_soon_threadsafe(active_turn.task.cancel)
        return True
