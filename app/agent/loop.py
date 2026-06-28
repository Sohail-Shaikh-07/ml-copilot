"""ML Copilot agent loop implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from app.agent.llm import LLMClient, Usage
from app.config import AppSettings
from app.storage.models import MessageRecord, PendingApprovalRecord, SessionRecord
from app.storage.repository import SQLiteRepository
from app.tools.context import ToolExecutionContext, use_tool_execution_context
from app.tools.registry import ToolHandler, ToolRegistry, ToolSpec, UnknownToolError

logger = logging.getLogger(__name__)


class EventType:
    READY = "ready"
    PROCESSING = "processing"
    ASSISTANT_CHUNK = "assistant_chunk"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"
    INTERRUPTED = "interrupted"


MAX_ITERATIONS = 50
APPROVAL_REQUIRED_TOOLS = {"apply_patch", "run_command", "write_file"}


@dataclass
class AgentEvent:
    """Event emitted during agent execution."""

    id: str
    session_id: str
    turn_id: str
    event_type: str
    data: dict[str, Any]
    sequence: int
    created_at: str

    @classmethod
    def create(
        cls,
        session_id: str,
        turn_id: str,
        event_type: str,
        data: dict[str, Any],
        sequence: int,
    ) -> "AgentEvent":
        return cls(
            id=str(uuid.uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            data=data,
            sequence=sequence,
            created_at=_utc_now(),
        )


@dataclass
class TurnContext:
    """Context for a single agent turn."""

    session_id: str
    turn_id: str
    messages: list[dict[str, Any]]
    event_sequence: int
    message_sequence: int
    hf_token: str | None = None


@dataclass
class TurnMetricsAccumulator:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    tool_retries: int = 0
    tool_latency_ms: float = 0.0
    error_count: int = 0
    seen_fingerprints: set[str] = field(default_factory=set)

    def record_usage(self, usage: Usage) -> None:
        self.prompt_tokens += max(0, usage.prompt_tokens)
        self.completion_tokens += max(0, usage.completion_tokens)
        self.total_tokens += max(0, usage.total_tokens or usage.prompt_tokens + usage.completion_tokens)

    def record_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> None:
        self.tool_calls += 1
        fingerprint = f"{tool_name}:{json.dumps(arguments, sort_keys=True, separators=(',', ':'))}"
        if fingerprint in self.seen_fingerprints:
            self.tool_retries += 1
        else:
            self.seen_fingerprints.add(fingerprint)

    def record_tool_error(self) -> None:
        self.tool_errors += 1
        self.error_count += 1

    def record_failure(self) -> None:
        self.error_count += 1

    def record_tool_latency(self, elapsed_ms: float) -> None:
        self.tool_latency_ms += max(0.0, elapsed_ms)


def _estimate_turn_cost_usd(settings: AppSettings, metrics: TurnMetricsAccumulator) -> float:
    prompt_cost = metrics.prompt_tokens * settings.usage.prompt_cost_per_1k_tokens_usd / 1000.0
    completion_cost = metrics.completion_tokens * settings.usage.completion_cost_per_1k_tokens_usd / 1000.0
    return round(prompt_cost + completion_cost, 6)


class AgentLoop:
    """Main agent loop that orchestrates LLM calls and tool execution."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        repository: SQLiteRepository,
        settings: AppSettings,
    ) -> None:
        self.llm = llm_client
        self.tools = tool_registry
        self.repo = repository
        self.settings = settings
        self._event_handlers: list[Callable[[AgentEvent], None]] = []
        self._interrupted = False

    def add_event_handler(self, handler: Callable[[AgentEvent], None]) -> None:
        """Add a handler for agent events (e.g. SSE streaming)."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[AgentEvent], None]) -> None:
        """Remove an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    async def emit_event(
        self,
        turn_context: TurnContext,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Emit an event and persist it."""
        event = AgentEvent.create(
            session_id=turn_context.session_id,
            turn_id=turn_context.turn_id,
            event_type=event_type,
            data=data,
            sequence=turn_context.event_sequence,
        )
        turn_context.event_sequence += 1

        self.repo.add_event(
            session_id=event.session_id,
            turn_id=event.turn_id,
            event_type=event.event_type,
            data=event.data,
            sequence=event.sequence,
            event_id=event.id,
        )

        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Event handler error: %s", exc)

    async def run_turn(
        self,
        session: SessionRecord,
        user_message: str,
        system_prompt: str | None = None,
        hf_token: str | None = None,
    ) -> dict[str, Any]:
        """Run a complete turn for a new user message."""
        ctx = self._build_turn_context(session, system_prompt, hf_token=hf_token)
        await self.emit_event(ctx, EventType.READY, {"message": "Agent ready"})

        pending_approvals = self.repo.list_pending_approvals(session.id)
        if pending_approvals:
            await self._abandon_pending_approvals(ctx, pending_approvals)

        self._append_message(
            ctx,
            role="user",
            content=user_message,
        )
        try:
            await self.emit_event(ctx, EventType.PROCESSING, {})
            return await self._run_loop(session, ctx)
        except asyncio.CancelledError:
            await self.emit_event(ctx, EventType.INTERRUPTED, {"message": "Turn interrupted."})
            raise

    async def resume_pending_approval(
        self,
        session: SessionRecord,
        approval_id: str,
        *,
        approved: bool,
        user_feedback: str | None = None,
        edited_arguments: dict[str, Any] | None = None,
        system_prompt: str | None = None,
        hf_token: str | None = None,
    ) -> dict[str, Any]:
        """Apply an approval decision and continue the agent loop."""
        ctx = self._build_turn_context(session, system_prompt, hf_token=hf_token)
        await self.emit_event(ctx, EventType.READY, {"message": "Approval decision received"})
        await self.emit_event(ctx, EventType.PROCESSING, {})

        pending_approval = self._get_pending_approval(session.id, approval_id)
        if approved:
            await self._approve_pending_tool(
                ctx,
                pending_approval,
                user_feedback=user_feedback,
                edited_arguments=edited_arguments,
            )
        else:
            await self._reject_pending_tool(
                ctx,
                pending_approval,
                status="rejected",
                message=_approval_rejection_message(user_feedback),
                user_feedback=user_feedback,
                edited_arguments=edited_arguments,
            )

        remaining_approvals = self.repo.list_pending_approvals(session.id)
        if remaining_approvals:
            pending_payloads = _serialize_pending_approvals(remaining_approvals)
            await self.emit_event(
                ctx,
                EventType.APPROVAL_REQUIRED,
                {"tools": pending_payloads, "count": len(pending_payloads)},
            )
            return {
                "status": "approval_required",
                "pending_approvals": pending_payloads,
                "approval_ids": [item["approval_id"] for item in pending_payloads],
                "resolved_approval_id": approval_id,
            }

        try:
            return await self._run_loop(session, ctx)
        except asyncio.CancelledError:
            await self.emit_event(ctx, EventType.INTERRUPTED, {"message": "Turn interrupted."})
            raise

    def interrupt(self) -> None:
        """Signal the agent to stop after the current operation."""
        self._interrupted = True

    def _build_turn_context(
        self,
        session: SessionRecord,
        system_prompt: str | None,
        *,
        hf_token: str | None = None,
    ) -> TurnContext:
        prompt = system_prompt or _default_system_prompt()
        history = [_message_to_llm_dict(record) for record in self.repo.list_messages(session.id)]
        return TurnContext(
            session_id=session.id,
            turn_id=str(uuid.uuid4()),
            messages=[{"role": "system", "content": prompt}, *history],
            event_sequence=self.repo.next_event_sequence(session.id),
            message_sequence=self.repo.next_message_sequence(session.id),
            hf_token=hf_token,
        )

    async def _run_loop(
        self,
        session: SessionRecord,
        ctx: TurnContext,
    ) -> dict[str, Any]:
        tool_specs = self.tools.openai_tools()
        iterations = 0
        turn_started_at = _utc_now()
        metrics = TurnMetricsAccumulator()

        while iterations < MAX_ITERATIONS:
            if self._interrupted:
                await self.emit_event(ctx, EventType.INTERRUPTED, {})
                await self._record_turn_metrics(
                    session=session,
                    turn_id=ctx.turn_id,
                    metrics=metrics,
                    status="interrupted",
                    iterations=iterations,
                    started_at=turn_started_at,
                )
                return {"status": "interrupted", "iterations": iterations}

            iterations += 1

            try:
                response = await self.llm.chat(
                    messages=ctx.messages,
                    tools=tool_specs if tool_specs else None,
                    tool_choice="auto" if tool_specs else None,
                    stream=True,
                )
            except asyncio.CancelledError:
                await self.emit_event(ctx, EventType.INTERRUPTED, {"message": "Turn interrupted."})
                await self._record_turn_metrics(
                    session=session,
                    turn_id=ctx.turn_id,
                    metrics=metrics,
                    status="interrupted",
                    iterations=iterations,
                    started_at=turn_started_at,
                )
                raise
            except Exception as exc:
                metrics.record_failure()
                await self.emit_event(ctx, EventType.ERROR, {"error": str(exc)})
                await self._record_turn_metrics(
                    session=session,
                    turn_id=ctx.turn_id,
                    metrics=metrics,
                    status="error",
                    iterations=iterations,
                    started_at=turn_started_at,
                )
                raise

            full_content = response.content
            tool_calls = response.tool_calls
            if response.usage is not None:
                metrics.record_usage(response.usage)

            if full_content:
                await self.emit_event(
                    ctx,
                    EventType.ASSISTANT_CHUNK,
                    {"content": full_content, "finish_reason": response.finish_reason},
                )

            assistant_content = "" if tool_calls else (full_content or "")
            assistant_raw = (
                {"tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in tool_calls]}
                if tool_calls
                else None
            )
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_content,
            }
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in tool_calls
                ]
            self._append_message(
                ctx,
                role="assistant",
                content=assistant_content,
                raw=assistant_raw,
                llm_message=assistant_message,
            )

            if not tool_calls:
                await self.emit_event(ctx, EventType.ASSISTANT_MESSAGE, {"content": full_content or ""})
                await self.emit_event(ctx, EventType.TURN_COMPLETE, {"iterations": iterations})
                await self._record_turn_metrics(
                    session=session,
                    turn_id=ctx.turn_id,
                    metrics=metrics,
                    status="complete",
                    iterations=iterations,
                    started_at=turn_started_at,
                )
                return {"status": "complete", "content": full_content, "iterations": iterations}

            pending_payloads: list[dict[str, Any]] = []
            approval_ids: list[str] = []

            for tool_call in tool_calls:
                await self.emit_event(
                    ctx,
                    EventType.TOOL_CALL,
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                )

                try:
                    arguments = tool_call.arguments_as_json()
                except Exception as exc:
                    error_message = f"Tool execution error: {exc}"
                    metrics.record_tool_call(tool_call.name, {"__raw_arguments__": tool_call.arguments})
                    metrics.record_tool_error()
                    self.repo.add_tool_call(
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tool_name=tool_call.name,
                        arguments={},
                        status="failed",
                        requires_approval=False,
                        started_at=_utc_now(),
                        finished_at=_utc_now(),
                        output=error_message,
                        success=False,
                        error=error_message,
                        tool_call_id=tool_call.id,
                    )
                    await self._record_tool_output(
                        ctx,
                        tool_call_id=tool_call.id,
                        tool_name=tool_call.name,
                        output=error_message,
                        success=False,
                    )
                    continue

                requires_approval = self._tool_requires_approval(tool_call.name)
                metrics.record_tool_call(tool_call.name, arguments)
                if requires_approval:
                    self.repo.add_tool_call(
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tool_name=tool_call.name,
                        arguments=arguments,
                        status="pending_approval",
                        requires_approval=True,
                        started_at=_utc_now(),
                        tool_call_id=tool_call.id,
                    )
                    approval = self.repo.create_approval(
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tool_call_id=tool_call.id,
                    )
                    self.repo.update_tool_call(tool_call.id, approval_id=approval.id)
                    approval_ids.append(approval.id)
                    pending_payloads.append(
                        {
                            "approval_id": approval.id,
                            "tool_call_id": tool_call.id,
                            "tool_name": tool_call.name,
                            "arguments": arguments,
                        }
                    )
                    continue

                await self._execute_tool_call(
                    ctx,
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    arguments=arguments,
                    metrics=metrics,
                )

            if pending_payloads:
                await self.emit_event(
                    ctx,
                    EventType.APPROVAL_REQUIRED,
                    {"tools": pending_payloads, "count": len(pending_payloads)},
                )
                await self._record_turn_metrics(
                    session=session,
                    turn_id=ctx.turn_id,
                    metrics=metrics,
                    status="approval_required",
                    iterations=iterations,
                    started_at=turn_started_at,
                )
                return {
                    "status": "approval_required",
                    "iterations": iterations,
                    "pending_approvals": pending_payloads,
                    "approval_ids": approval_ids,
                }

        await self.emit_event(ctx, EventType.TURN_COMPLETE, {"iterations": iterations, "max_reached": True})
        await self._record_turn_metrics(
            session=session,
            turn_id=ctx.turn_id,
            metrics=metrics,
            status="max_iterations",
            iterations=iterations,
            started_at=turn_started_at,
        )
        return {"status": "max_iterations", "iterations": iterations}

    async def _execute_tool_call(
        self,
        ctx: TurnContext,
        *,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        metrics: TurnMetricsAccumulator | None = None,
    ) -> None:
        now = _utc_now()
        existing = self.repo.get_tool_call(tool_call_id)
        if existing is None:
            self.repo.add_tool_call(
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
                tool_name=tool_name,
                arguments=arguments,
                status="running",
                requires_approval=False,
                started_at=now,
                tool_call_id=tool_call_id,
            )
        else:
            self.repo.update_tool_call(
                tool_call_id,
                status="running",
                arguments=arguments,
                started_at=existing.started_at or now,
                error=None,
            )

        start = perf_counter()
        try:
            with use_tool_execution_context(
                ToolExecutionContext(
                    session_id=ctx.session_id,
                    hf_token=ctx.hf_token,
                )
            ):
                tool_output = await self.tools.call(tool_name, arguments)
            success = True
            error = None
        except asyncio.CancelledError:
            if metrics is not None:
                metrics.record_tool_error()
                metrics.record_tool_latency((perf_counter() - start) * 1000.0)
            tool_output = "Tool execution interrupted."
            self.repo.update_tool_call(
                tool_call_id,
                status="interrupted",
                arguments=arguments,
                finished_at=_utc_now(),
                output=tool_output,
                success=False,
                error=tool_output,
            )
            await self._record_tool_output(
                ctx,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                output=tool_output,
                success=False,
            )
            raise
        except Exception as exc:
            if metrics is not None:
                metrics.record_tool_error()
            tool_output = f"Tool execution error: {exc}"
            success = False
            error = str(exc)

        if metrics is not None:
            metrics.record_tool_latency((perf_counter() - start) * 1000.0)
        self.repo.update_tool_call(
            tool_call_id,
            status="completed" if success else "failed",
            arguments=arguments,
            finished_at=_utc_now(),
            output=tool_output,
            success=success,
            error=error,
        )
        await self._record_tool_output(
            ctx,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            output=tool_output,
            success=success,
        )

    async def _record_turn_metrics(
        self,
        *,
        session: SessionRecord,
        turn_id: str,
        metrics: TurnMetricsAccumulator,
        status: str,
        iterations: int,
        started_at: str,
    ) -> None:
        finished_at = _utc_now()
        self.repo.add_turn_metrics(
            session_id=session.id,
            turn_id=turn_id,
            status=status,
            iterations=iterations,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            total_tokens=metrics.total_tokens,
            estimated_cost_usd=_estimate_turn_cost_usd(self.settings, metrics),
            tool_calls=metrics.tool_calls,
            tool_errors=metrics.tool_errors,
            tool_retries=metrics.tool_retries,
            tool_latency_ms=round(metrics.tool_latency_ms, 2),
            error_count=metrics.error_count,
            started_at=started_at,
            finished_at=finished_at,
        )

    async def _record_tool_output(
        self,
        ctx: TurnContext,
        *,
        tool_call_id: str,
        tool_name: str,
        output: str,
        success: bool,
    ) -> None:
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": output,
            "name": tool_name,
        }
        self._append_message(
            ctx,
            role="tool",
            content=output,
            tool_call_id=tool_call_id,
            name=tool_name,
            llm_message=tool_message,
        )
        await self.emit_event(
            ctx,
            EventType.TOOL_OUTPUT,
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "output": output,
                "success": success,
            },
        )

    async def _abandon_pending_approvals(
        self,
        ctx: TurnContext,
        pending_approvals: list[PendingApprovalRecord],
    ) -> None:
        for pending_approval in pending_approvals:
            await self._reject_pending_tool(
                ctx,
                pending_approval,
                status="abandoned",
                message="Tool execution abandoned because the user continued the conversation.",
                user_feedback=None,
                edited_arguments=None,
            )

    async def _approve_pending_tool(
        self,
        ctx: TurnContext,
        pending_approval: PendingApprovalRecord,
        *,
        user_feedback: str | None,
        edited_arguments: dict[str, Any] | None,
    ) -> None:
        original_arguments = json.loads(pending_approval.tool_call.arguments_json)
        arguments = edited_arguments if edited_arguments is not None else original_arguments
        self.repo.update_approval(
            pending_approval.approval.id,
            status="approved",
            responded_at=_utc_now(),
            user_feedback=user_feedback,
            edited_payload=edited_arguments,
        )
        self.repo.update_tool_call(
            pending_approval.tool_call.id,
            status="approved",
            arguments=arguments,
        )
        await self.emit_event(
            ctx,
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": pending_approval.approval.id,
                "tool_call_id": pending_approval.tool_call.id,
                "tool_name": pending_approval.tool_call.tool_name,
                "decision": "approved",
            },
        )
        await self._execute_tool_call(
            ctx,
            tool_call_id=pending_approval.tool_call.id,
            tool_name=pending_approval.tool_call.tool_name,
            arguments=arguments,
        )

    async def _reject_pending_tool(
        self,
        ctx: TurnContext,
        pending_approval: PendingApprovalRecord,
        *,
        status: str,
        message: str,
        user_feedback: str | None,
        edited_arguments: dict[str, Any] | None,
    ) -> None:
        self.repo.update_approval(
            pending_approval.approval.id,
            status=status,
            responded_at=_utc_now(),
            user_feedback=user_feedback,
            edited_payload=edited_arguments,
        )
        self.repo.update_tool_call(
            pending_approval.tool_call.id,
            status=status,
            finished_at=_utc_now(),
            output=message,
            success=False,
            error=message,
        )
        await self.emit_event(
            ctx,
            EventType.APPROVAL_RESOLVED,
            {
                "approval_id": pending_approval.approval.id,
                "tool_call_id": pending_approval.tool_call.id,
                "tool_name": pending_approval.tool_call.tool_name,
                "decision": status,
            },
        )
        await self._record_tool_output(
            ctx,
            tool_call_id=pending_approval.tool_call.id,
            tool_name=pending_approval.tool_call.tool_name,
            output=message,
            success=False,
        )

    def _append_message(
        self,
        ctx: TurnContext,
        *,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        name: str | None = None,
        raw: dict[str, Any] | None = None,
        llm_message: dict[str, Any] | None = None,
    ) -> None:
        self.repo.add_message(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            role=role,
            content=content,
            sequence=ctx.message_sequence,
            tool_call_id=tool_call_id,
            name=name,
            raw=raw,
        )
        ctx.message_sequence += 1
        ctx.messages.append(
            llm_message
            if llm_message is not None
            else _message_payload(
                role=role,
                content=content,
                tool_call_id=tool_call_id,
                name=name,
            )
        )

    def _get_pending_approval(self, session_id: str, approval_id: str) -> PendingApprovalRecord:
        for pending_approval in self.repo.list_pending_approvals(session_id):
            if pending_approval.approval.id == approval_id:
                return pending_approval
        raise KeyError(f"Unknown pending approval: {approval_id}")

    def _tool_requires_approval(self, tool_name: str) -> bool:
        if tool_name in APPROVAL_REQUIRED_TOOLS:
            return self.settings.safety.require_tool_approval
        try:
            return self.tools.get(tool_name).requires_approval
        except UnknownToolError:
            return False


def _utc_now() -> str:
    """Return current UTC time as an ISO string."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _default_system_prompt() -> str:
    """Return the default system prompt for the ML Copilot agent."""
    return """You are an expert ML engineering assistant specialized in analyzing
and improving machine learning codebases.

Your capabilities:
- Analyze ML repositories and understand their structure
- Read and understand code, documentation, and research papers
- Search for patterns, bugs, and improvement opportunities
- Propose and implement fixes with approval
- Run tests and experiments when approved
- Debug failures and provide solutions

Guidelines:
- Always read code before editing it
- Prefer small, focused changes over large refactors
- Ask for approval before running commands or editing files
- Use existing patterns in the codebase when implementing new features
- For complex tasks, break them into smaller steps
- Provide clear explanations of your reasoning and changes

When using tools:
- Use list_files to explore repository structure
- Use read_file to understand code before making changes
- Use search_text to find relevant code patterns
- Use git_status and git_diff to track changes
- Always confirm with the user before executing sensitive operations

Safety:
- Never execute destructive commands without explicit approval
- Always validate changes work correctly
- Keep modifications scoped and reversible
"""


def _message_to_llm_dict(record: MessageRecord) -> dict[str, Any]:
    raw = json.loads(record.raw_json) if record.raw_json else {}
    message = _message_payload(
        role=record.role,
        content=record.content,
        tool_call_id=record.tool_call_id,
        name=record.name,
    )
    if record.role == "assistant" and raw.get("tool_calls"):
        message["tool_calls"] = [
            {
                "id": item["id"],
                "type": "function",
                "function": {
                    "name": item["name"],
                    "arguments": item["arguments"],
                },
            }
            for item in raw["tool_calls"]
        ]
    return message


def _message_payload(
    *,
    role: str,
    content: str,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": role, "content": content}
    if tool_call_id:
        payload["tool_call_id"] = tool_call_id
    if name:
        payload["name"] = name
    return payload


def _approval_rejection_message(user_feedback: str | None) -> str:
    if user_feedback:
        return f"Tool execution rejected by user. Feedback: {user_feedback}"
    return "Tool execution rejected by user."


def _serialize_pending_approvals(
    pending_approvals: list[PendingApprovalRecord],
) -> list[dict[str, Any]]:
    return [
        {
            "approval_id": pending_approval.approval.id,
            "tool_call_id": pending_approval.tool_call.id,
            "tool_name": pending_approval.tool_call.tool_name,
            "arguments": json.loads(pending_approval.tool_call.arguments_json),
        }
        for pending_approval in pending_approvals
    ]


def create_agent_loop(
    settings: AppSettings,
    repository: SQLiteRepository | None = None,
    llm_client: LLMClient | None = None,
) -> AgentLoop:
    """Create a configured agent loop with all dependencies."""
    if repository is None:
        repository = SQLiteRepository(settings.db_path)
        repository.initialize()

    if llm_client is None:
        llm_client = LLMClient.from_settings(settings)

    tool_registry = _create_tool_registry(settings)

    return AgentLoop(
        llm_client=llm_client,
        tool_registry=tool_registry,
        repository=repository,
        settings=settings,
    )


def _create_tool_registry(settings: AppSettings) -> ToolRegistry:
    """Create and populate the built-in and configured tool registry."""
    from app.tools import datasets, docs, hub, mcp, papers, repo_analyzer, reporting, workspace

    registry = ToolRegistry()
    workspace_specs = workspace.get_tool_specs()

    for spec in workspace_specs:
        name = spec["name"]
        handler = _get_workspace_handler(name, settings)
        tool_spec = ToolSpec(
            name=name,
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=handler,
        )
        registry.register(tool_spec)

    for spec in reporting.get_tool_specs():
        tool_spec = ToolSpec(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=_make_report_handler(settings),
        )
        registry.register(tool_spec)

    for spec in datasets.get_tool_specs():
        tool_spec = ToolSpec(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=_make_dataset_handler(spec["name"], settings),
        )
        registry.register(tool_spec)

    for spec in hub.get_tool_specs():
        tool_spec = ToolSpec(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=_make_hub_handler(spec["name"], settings),
        )
        registry.register(tool_spec)

    for spec in docs.get_tool_specs():
        tool_spec = ToolSpec(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=_make_docs_handler(spec["name"], settings),
        )
        registry.register(tool_spec)

    for spec in papers.get_tool_specs():
        tool_spec = ToolSpec(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=_make_papers_handler(spec["name"], settings),
        )
        registry.register(tool_spec)

    for spec in repo_analyzer.get_tool_specs():
        tool_spec = ToolSpec(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec.get("parameters", {"type": "object", "properties": {}}),
            handler=_make_repo_analyzer_handler(settings),
        )
        registry.register(tool_spec)

    if settings.mcp.enabled:
        try:
            mcp.register_mcp_manifest_tools(registry, settings.mcp.manifest_path)
        except mcp.MCPManifestError as exc:
            logger.warning("MCP manifest discovery failed, continuing with local tools: %s", exc)

    return registry


def _get_workspace_handler(name: str, settings: AppSettings) -> ToolHandler:
    """Get the handler function for a workspace tool."""
    from app.tools import workspace as ws

    handlers: dict[str, ToolHandler] = {
        "list_files": lambda args: ws.list_files_handler(args, settings),
        "read_file": lambda args: ws.read_file_handler(args, settings),
        "search_text": lambda args: ws.search_text_handler(args, settings),
        "git_status": lambda args: ws.git_status_handler(args, settings),
        "git_diff": lambda args: ws.git_diff_handler(args, settings),
        "run_command": lambda args: ws.run_command_handler(args, settings),
        "apply_patch": lambda args: ws.apply_patch_handler(args, settings),
    }

    try:
        return handlers[name]
    except KeyError as exc:
        raise UnknownToolError(f"Workspace tool handler is not registered for {name!r}.") from exc


def _make_report_handler(settings: AppSettings) -> ToolHandler:
    """Create a handler for the git_report tool."""
    from app.tools import reporting

    async def _handler(args: dict[str, Any]) -> str:
        return await reporting.git_report_handler(args, settings)

    return _handler


def _make_dataset_handler(name: str, settings: AppSettings) -> ToolHandler:
    """Create a handler for dataset inspection and BYOD ingestion tools."""
    from app.tools import datasets

    handlers = {
        "inspect_dataset": datasets.inspect_dataset_handler,
        "ingest_dataset": datasets.ingest_dataset_handler,
    }

    async def _handler(args: dict[str, Any]) -> str:
        return await handlers[name](args, settings)

    return _handler


def _make_hub_handler(name: str, settings: AppSettings) -> ToolHandler:
    """Create a handler for Hub discovery and repository inspection."""
    from app.tools import hub

    handlers = {
        "search_hub": hub.search_hub_handler,
        "inspect_hub_repo": hub.inspect_hub_repo_handler,
    }

    async def _handler(args: dict[str, Any]) -> str:
        return await handlers[name](args, settings)

    return _handler


def _make_papers_handler(name: str, settings: AppSettings) -> ToolHandler:
    """Create a handler for a paper research tool (metadata, citations, reading, recipes)."""
    from app.tools import papers

    handlers = {
        "paper_details": papers.paper_details_handler,
        "paper_citation_graph": papers.paper_citation_graph_handler,
        "read_paper": papers.read_paper_handler,
        "extract_training_recipe": papers.extract_training_recipe_handler,
    }

    async def _handler(args: dict[str, Any]) -> str:
        return await handlers[name](args, settings)

    return _handler


def _make_repo_analyzer_handler(settings: AppSettings) -> ToolHandler:
    """Create a handler for the analyze_ml_repo tool."""
    from app.tools import repo_analyzer

    async def _handler(args: dict[str, Any]) -> str:
        return await repo_analyzer.analyze_ml_repo_handler(args, settings)

    return _handler


def _make_docs_handler(name: str, settings: AppSettings) -> ToolHandler:
    """Create a handler for docs tools (search_docs or fetch_doc_page)."""
    from app.tools import docs

    handlers = {
        "search_docs": docs.search_docs_handler,
        "fetch_doc_page": docs.fetch_doc_page_handler,
    }

    async def _handler(args: dict[str, Any]) -> str:
        return await handlers[name](args, settings)

    return _handler
