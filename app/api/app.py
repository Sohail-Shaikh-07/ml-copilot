"""FastAPI app and route handlers for ML Copilot sessions and messages."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent.loop import AgentLoop, create_agent_loop
from app.auth import resolve_hf_request_token
from app.config import AppSettings
from app.storage.models import (
    MessageRecord,
    PendingApprovalRecord,
    SessionRecord,
    ToolCallRecord,
)
from app.storage.models import (
    SessionMetricsSummary as SessionMetricsRecord,
)
from app.storage.repository import SQLiteRepository
from app.tools.datasets import inspect_dataset_handler, validate_dataset_filename

from .runtime import ActiveTurnManager, SessionAuthManager
from .schemas import (
    ApprovalDecisionRequest,
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    DatasetUploadResponse,
    InterruptResponse,
    MessagePayload,
    PendingApprovalPayload,
    SessionDetail,
    SessionMetricsSummary,
    SessionSummary,
    ToolCallPayload,
    TurnResultPayload,
)
from .streaming import SessionEventStreamManager, create_event_stream_response

RepositoryFactory = Callable[[AppSettings], SQLiteRepository]
LoopFactory = Callable[[AppSettings, SQLiteRepository], AgentLoop]
MAX_DATASET_UPLOAD_BYTES = 25 * 1024 * 1024


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
    app.state.event_stream_manager = SessionEventStreamManager()
    app.state.active_turn_manager = ActiveTurnManager()
    app.state.session_auth_manager = SessionAuthManager()

    router = APIRouter(prefix="/api", tags=["sessions"])

    @router.post("/session", response_model=SessionSummary, status_code=status.HTTP_201_CREATED)
    async def create_session(
        payload: CreateSessionRequest,
        request: Request,
        repo: RepositoryDep,
        current_settings: SettingsDep,
    ) -> SessionSummary:
        session_token = _resolve_session_token(request)
        metadata = _sanitize_metadata(payload.metadata)
        record = repo.create_session(
            model=payload.model or current_settings.llm.model,
            title=payload.title,
            metadata=metadata,
        )
        if session_token:
            get_session_auth_manager(request).set_token(record.id, session_token)
        return _serialize_session_summary(repo, record)

    @router.get("/sessions", response_model=list[SessionSummary])
    async def list_sessions(
        repo: RepositoryDep,
    ) -> list[SessionSummary]:
        return [_serialize_session_summary(repo, session) for session in repo.list_sessions()]

    @router.post(
        "/datasets/upload",
        response_model=DatasetUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_dataset(
        request: Request,
        current_settings: SettingsDep,
    ) -> DatasetUploadResponse:
        filename = request.headers.get("X-Filename", "").strip()
        filename_error = validate_dataset_filename(filename)
        if filename_error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=filename_error)

        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Content-Length must be an integer.",
                ) from exc
            if declared_size > MAX_DATASET_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"Dataset upload exceeds {MAX_DATASET_UPLOAD_BYTES} bytes.",
                )

        payload = await request.body()
        if not payload:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset upload is empty.")
        if len(payload) > MAX_DATASET_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Dataset upload exceeds {MAX_DATASET_UPLOAD_BYTES} bytes.",
            )

        upload_dir = current_settings.paths.workspace_root / ".ml-copilot" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        destination = _available_upload_path(upload_dir, filename)
        destination.write_bytes(payload)
        relative_path = destination.relative_to(current_settings.paths.workspace_root).as_posix()
        preview = await inspect_dataset_handler(
            {"source": relative_path, "source_kind": "local", "sample_rows": 3},
            current_settings,
        )
        if preview.startswith("Error:"):
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=preview)

        return DatasetUploadResponse(
            filename=destination.name,
            path=relative_path,
            size_bytes=len(payload),
            preview=preview,
        )

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

    @router.get("/events/{session_id}")
    async def stream_session_events(
        session_id: str,
        request: Request,
        repo: RepositoryDep,
    ) -> StreamingResponse:
        _get_session_or_404(repo, session_id)
        return create_event_stream_response(
            request=request,
            session_id=session_id,
            repository=repo,
            stream_manager=get_event_stream_manager(request),
        )

    @router.post("/chat/{session_id}", response_model=ChatResponse)
    async def chat_session(
        session_id: str,
        payload: ChatRequest,
        request: Request,
        repo: RepositoryDep,
        loop: LoopDep,
    ) -> ChatResponse:
        session = _get_session_or_404(repo, session_id)
        active_turn_manager = get_active_turn_manager(request)
        session_token = _resolve_session_token(request)
        if session_token:
            get_session_auth_manager(request).set_token(session_id, session_token)
        hf_token = _token_for_session(request, session_id)
        if not active_turn_manager.register(session_id, loop):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session already has an active turn",
            )

        repo.update_session(session_id, status="processing")
        session = _get_session_or_404(repo, session_id)
        event_stream_manager = get_event_stream_manager(request)
        loop.add_event_handler(event_stream_manager.publish)
        current_task = asyncio.current_task()

        try:
            result = await loop.run_turn(
                session=session,
                user_message=payload.message,
                system_prompt=payload.system_prompt,
                hf_token=hf_token,
            )
        except asyncio.CancelledError:
            result = {"status": "interrupted"}
        except Exception:
            repo.update_session(session_id, status="error")
            raise
        finally:
            active_turn_manager.unregister(session_id, current_task)
            loop.remove_event_handler(event_stream_manager.publish)

        updated_session = repo.update_session(session_id, status=_status_for_turn_result(result["status"]))
        return ChatResponse(
            session=_serialize_session_detail(repo, updated_session),
            result=_serialize_turn_result(result),
            messages=[_serialize_message(message) for message in repo.list_messages(session_id)],
        )

    @router.post("/approval/{session_id}/{approval_id}", response_model=ChatResponse)
    async def resolve_approval(
        session_id: str,
        approval_id: str,
        payload: ApprovalDecisionRequest,
        request: Request,
        repo: RepositoryDep,
        loop: LoopDep,
    ) -> ChatResponse:
        session = _get_session_or_404(repo, session_id)
        active_turn_manager = get_active_turn_manager(request)
        session_token = _resolve_session_token(request)
        if session_token:
            get_session_auth_manager(request).set_token(session_id, session_token)
        hf_token = _token_for_session(request, session_id)
        if not active_turn_manager.register(session_id, loop):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session already has an active turn",
            )

        repo.update_session(session_id, status="processing")
        event_stream_manager = get_event_stream_manager(request)
        loop.add_event_handler(event_stream_manager.publish)
        current_task = asyncio.current_task()

        try:
            result = await loop.resume_pending_approval(
                session=session,
                approval_id=approval_id,
                approved=payload.approved,
                user_feedback=payload.user_feedback,
                edited_arguments=payload.edited_arguments,
                system_prompt=payload.system_prompt,
                hf_token=hf_token,
            )
        except KeyError as exc:
            fallback_status = "waiting_approval" if repo.list_pending_approvals(session_id) else "idle"
            repo.update_session(session_id, status=fallback_status)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending approval not found",
            ) from exc
        except asyncio.CancelledError:
            result = {"status": "interrupted"}
        except Exception:
            repo.update_session(session_id, status="error")
            raise
        finally:
            active_turn_manager.unregister(session_id, current_task)
            loop.remove_event_handler(event_stream_manager.publish)

        updated_session = repo.update_session(session_id, status=_status_for_turn_result(result["status"]))
        return ChatResponse(
            session=_serialize_session_detail(repo, updated_session),
            result=_serialize_turn_result(result),
            messages=[_serialize_message(message) for message in repo.list_messages(session_id)],
        )

    @router.post("/interrupt/{session_id}", response_model=InterruptResponse)
    async def interrupt_session(
        session_id: str,
        request: Request,
        repo: RepositoryDep,
    ) -> InterruptResponse:
        session = _get_session_or_404(repo, session_id)
        active_turn_manager = get_active_turn_manager(request)

        if not active_turn_manager.interrupt(session_id):
            return InterruptResponse(
                session_id=session_id,
                status=session.status,
                interrupted=False,
                message="No active turn to interrupt.",
            )

        repo.update_session(session_id, status="interrupted")
        return InterruptResponse(
            session_id=session_id,
            status="interrupt_requested",
            interrupted=True,
            message="Active turn interruption requested.",
        )

    app.include_router(router)
    _mount_frontend_if_available(app, resolved_settings)
    return app


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_event_stream_manager(request: Request) -> SessionEventStreamManager:
    return request.app.state.event_stream_manager


def get_active_turn_manager(request: Request) -> ActiveTurnManager:
    return request.app.state.active_turn_manager


def get_session_auth_manager(request: Request) -> SessionAuthManager:
    return request.app.state.session_auth_manager


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


def _resolve_session_token(request: Request) -> str | None:
    """Resolve an explicit HF token from the incoming request."""
    return resolve_hf_request_token(request, include_env_fallback=False)


def _token_for_session(request: Request, session_id: str) -> str | None:
    """Resolve the token to use for a session, falling back to env/cache."""
    auth_manager = get_session_auth_manager(request)
    return auth_manager.get_token(session_id) or resolve_hf_request_token(request)


def _sanitize_metadata(value: dict[str, Any]) -> dict[str, Any]:
    def _sanitize(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: _sanitize(child) for key, child in item.items() if not _is_sensitive_metadata_key(str(key))}
        if isinstance(item, list):
            return [_sanitize(child) for child in item]
        return item

    return _sanitize(value)


def _available_upload_path(directory: Path, filename: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    index = 2
    while True:
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _is_sensitive_metadata_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return (
        "token" in normalized
        or "authorization" in normalized
        or "bearer" in normalized
        or normalized in {"secret", "apikey", "api_key"}
    )


def _mount_frontend_if_available(app: FastAPI, settings: AppSettings) -> None:
    frontend_dist = settings.paths.workspace_root / "frontend" / "dist"
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


RepositoryDep = Annotated[SQLiteRepository, Depends(get_repository)]
SettingsDep = Annotated[AppSettings, Depends(get_settings)]
LoopDep = Annotated[AgentLoop, Depends(get_agent_loop)]


def _get_session_or_404(repo: SQLiteRepository, session_id: str) -> SessionRecord:
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _serialize_session_summary(repo: SQLiteRepository, session: SessionRecord) -> SessionSummary:
    metrics = _serialize_session_metrics(repo.get_session_metrics_summary(session.id))
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
        metrics=metrics,
    )


def _serialize_session_detail(repo: SQLiteRepository, session: SessionRecord) -> SessionDetail:
    summary = _serialize_session_summary(repo, session)
    return SessionDetail(
        **summary.model_dump(),
        pending_approvals=[_serialize_pending_approval(item) for item in repo.list_pending_approvals(session.id)],
        tool_calls=[_serialize_tool_call(tool_call) for tool_call in repo.list_tool_calls(session.id)],
    )


def _serialize_session_metrics(record: SessionMetricsRecord) -> SessionMetricsSummary:
    return SessionMetricsSummary(
        session_id=record.session_id,
        turn_count=record.turn_count,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        total_tokens=record.total_tokens,
        estimated_cost_usd=record.estimated_cost_usd,
        tool_calls=record.tool_calls,
        tool_errors=record.tool_errors,
        tool_retries=record.tool_retries,
        tool_latency_ms=record.tool_latency_ms,
        average_tool_latency_ms=record.average_tool_latency_ms,
        error_count=record.error_count,
        last_updated_at=record.last_updated_at,
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
