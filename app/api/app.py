"""FastAPI app and route handlers for ML Copilot sessions and messages."""

from __future__ import annotations

import json
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status

from app.agent.loop import AgentLoop, create_agent_loop
from app.config import AppSettings
from app.storage.models import MessageRecord, PendingApprovalRecord, SessionRecord, ToolCallRecord
from app.storage.repository import SQLiteRepository

from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    MessagePayload,
    PendingApprovalPayload,
    SessionDetail,
    SessionSummary,
    ToolCallPayload,
    TurnResultPayload,
)

RepositoryFactory = Callable[[AppSettings], SQLiteRepository]
LoopFactory = Callable[[AppSettings, SQLiteRepository], AgentLoop]


def create_app(
    settings: AppSettings | None = None,
    *,
    repository_factory: RepositoryFactory | None = None,
    loop_factory: LoopFactory | None = None,
) -> FastAPI:
    """Create the FastAPI application for ML Copilot."""
    resolved_settings = settings or AppSettings.load()
    app = FastAPI(title=resolved_settings.app_name, version=resolved_settings.version)
    app.state.settings = resolved_settings
    app.state.repository_factory = repository_factory or _default_repository_factory
    app.state.loop_factory = loop_factory or _default_loop_factory

    router = APIRouter(prefix="/api", tags=["sessions"])

    @router.post("/session", response_model=SessionSummary, status_code=status.HTTP_201_CREATED)
    async def create_session(
        payload: CreateSessionRequest,
        repo: RepositoryDep,
        current_settings: SettingsDep,
    ) -> SessionSummary:
        record = repo.create_session(
            model=payload.model or current_settings.llm.model,
            title=payload.title,
            metadata=payload.metadata,
        )
        return _serialize_session_summary(repo, record)

    @router.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions(
        repo: RepositoryDep,
    ) -> list[SessionSummary]:
        return [_serialize_session_summary(repo, session) for session in repo.list_sessions()]

    @router.get("/session/{session_id}", response_model=SessionDetail)
    async def get_session(
        session_id: str,
        repo: RepositoryDep,
    ) -> SessionDetail:
        session = _get_session_or_404(repo, session_id)
        return _serialize_session_detail(repo, session)

    @router.get("/session/{session_id}/messages", response_model=list[MessagePayload])
    async def get_session_messages(
        session_id: str,
        repo: RepositoryDep,
    ) -> list[MessagePayload]:
        _get_session_or_404(repo, session_id)
        return [_serialize_message(message) for message in repo.list_messages(session_id)]

    @router.post("/chat/{session_id}", response_model=ChatResponse)
    async def chat_session(
        session_id: str,
        payload: ChatRequest,
        repo: RepositoryDep,
        loop: LoopDep,
    ) -> ChatResponse:
        session = _get_session_or_404(repo, session_id)
        repo.update_session(session_id, status="processing")
        session = _get_session_or_404(repo, session_id)

        try:
            result = await loop.run_turn(
                session=session,
                user_message=payload.message,
                system_prompt=payload.system_prompt,
            )
        except Exception:
            repo.update_session(session_id, status="error")
            raise

        updated_session = repo.update_session(session_id, status=_status_for_turn_result(result["status"]))
        return ChatResponse(
            session=_serialize_session_detail(repo, updated_session),
            result=_serialize_turn_result(result),
            messages=[_serialize_message(message) for message in repo.list_messages(session_id)],
        )

    app.include_router(router)
    return app


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_repository(
    request: Request,
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> SQLiteRepository:
    factory: RepositoryFactory = request.app.state.repository_factory
    return factory(settings)


def get_agent_loop(
    request: Request,
    settings: Annotated[AppSettings, Depends(get_settings)],
    repo: Annotated[SQLiteRepository, Depends(get_repository)],
) -> AgentLoop:
    factory: LoopFactory = request.app.state.loop_factory
    return factory(settings, repo)


def _default_repository_factory(settings: AppSettings) -> SQLiteRepository:
    repository = SQLiteRepository(settings.db_path)
    repository.initialize()
    return repository


def _default_loop_factory(settings: AppSettings, repository: SQLiteRepository) -> AgentLoop:
    return create_agent_loop(settings, repository=repository)


RepositoryDep = Annotated[SQLiteRepository, Depends(get_repository)]
SettingsDep = Annotated[AppSettings, Depends(get_settings)]
LoopDep = Annotated[AgentLoop, Depends(get_agent_loop)]


def _get_session_or_404(repo: SQLiteRepository, session_id: str) -> SessionRecord:
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _serialize_session_summary(repo: SQLiteRepository, session: SessionRecord) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        title=session.title,
        status=session.status,
        model=session.model,
        metadata=json.loads(session.metadata_json),
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=len(repo.list_messages(session.id)),
        event_count=len(repo.list_events(session.id)),
        pending_approval_count=len(repo.list_pending_approvals(session.id)),
    )


def _serialize_session_detail(repo: SQLiteRepository, session: SessionRecord) -> SessionDetail:
    summary = _serialize_session_summary(repo, session)
    return SessionDetail(
        **summary.model_dump(),
        pending_approvals=[_serialize_pending_approval(item) for item in repo.list_pending_approvals(session.id)],
        tool_calls=[_serialize_tool_call(tool_call) for tool_call in repo.list_tool_calls(session.id)],
    )


def _serialize_pending_approval(record: PendingApprovalRecord) -> PendingApprovalPayload:
    return PendingApprovalPayload(
        approval_id=record.approval.id,
        tool_call_id=record.tool_call.id,
        tool_name=record.tool_call.tool_name,
        arguments=json.loads(record.tool_call.arguments_json),
    )


def _serialize_tool_call(record: ToolCallRecord) -> ToolCallPayload:
    return ToolCallPayload(
        id=record.id,
        session_id=record.session_id,
        turn_id=record.turn_id,
        tool_name=record.tool_name,
        arguments=json.loads(record.arguments_json),
        status=record.status,
        requires_approval=record.requires_approval,
        approval_id=record.approval_id,
        started_at=record.started_at,
        finished_at=record.finished_at,
        output=record.output,
        success=record.success,
        error=record.error,
    )


def _serialize_message(record: MessageRecord) -> MessagePayload:
    return MessagePayload(
        id=record.id,
        session_id=record.session_id,
        turn_id=record.turn_id,
        role=record.role,
        content=record.content,
        tool_call_id=record.tool_call_id,
        name=record.name,
        raw=json.loads(record.raw_json) if record.raw_json else {},
        sequence=record.sequence,
        created_at=record.created_at,
    )


def _serialize_turn_result(payload: dict[str, Any]) -> TurnResultPayload:
    pending = payload.get("pending_approvals") or []
    return TurnResultPayload(
        status=str(payload.get("status", "")),
        content=payload.get("content"),
        iterations=payload.get("iterations"),
        approval_ids=[str(item) for item in payload.get("approval_ids") or []],
        pending_approvals=[PendingApprovalPayload.model_validate(item) for item in pending],
        resolved_approval_id=payload.get("resolved_approval_id"),
    )


def _status_for_turn_result(result_status: str) -> str:
    if result_status == "approval_required":
        return "waiting_approval"
    if result_status == "interrupted":
        return "interrupted"
    if result_status == "max_iterations":
        return "attention_required"
    return "idle"
