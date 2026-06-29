"""Tool execution context for request-scoped Hugging Face state."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from app.auth import resolve_hf_token


@dataclass(frozen=True)
class ToolExecutionContext:
    """Request-scoped execution metadata for tools."""

    session_id: str | None = None
    hf_token: str | None = None


_CURRENT_TOOL_CONTEXT: ContextVar[ToolExecutionContext | None] = ContextVar(
    "current_tool_execution_context",
    default=None,
)


def get_current_tool_context() -> ToolExecutionContext | None:
    return _CURRENT_TOOL_CONTEXT.get()


@contextmanager
def use_tool_execution_context(context: ToolExecutionContext) -> Iterator[None]:
    token = _CURRENT_TOOL_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_TOOL_CONTEXT.reset(token)


def current_hf_token() -> str | None:
    context = get_current_tool_context()
    return resolve_hf_token(
        context.hf_token if context else None,
        os.environ.get("HF_TOKEN"),
        os.environ.get("HUGGING_FACE_HUB_TOKEN"),
    )


def current_session_id() -> str | None:
    context = get_current_tool_context()
    return context.session_id if context else None
