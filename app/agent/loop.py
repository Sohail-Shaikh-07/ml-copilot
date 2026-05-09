"""ML Copilot agent loop implementation."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent.llm import LLMClient, ToolCall
from app.config import AppSettings
from app.storage.models import SessionRecord
from app.storage.repository import SQLiteRepository
from app.tools.registry import ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)


# Event types for SSE streaming
class EventType:
    READY = "ready"
    PROCESSING = "processing"
    ASSISTANT_CHUNK = "assistant_chunk"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"
    APPROVAL_REQUIRED = "approval_required"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"
    INTERRUPTED = "interrupted"


# Maximum iterations per turn to prevent infinite loops
MAX_ITERATIONS = 50

# Tools that require approval before execution
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
    user_message: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    event_sequence: int = 0


@dataclass
class ToolExecutionResult:
    """Result of a tool execution."""

    tool_name: str
    tool_call_id: str
    success: bool
    output: str
    requires_approval: bool = False
    error: str | None = None


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

        # Event handlers (for SSE streaming)
        self._event_handlers: list[Callable[[AgentEvent], None]] = []

        # Interrupt flag
        self._interrupted = False

    def add_event_handler(self, handler: Callable[[AgentEvent], None]) -> None:
        """Add a handler for agent events (e.g., SSE streaming)."""
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

        # Persist event
        self.repo.add_event(
            session_id=event.session_id,
            turn_id=event.turn_id,
            event_type=event.event_type,
            data=event.data,
            sequence=event.sequence,
            event_id=event.id,
        )

        # Notify handlers
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.warning(f"Event handler error: {e}")

    async def run_turn(
        self,
        session: SessionRecord,
        user_message: str,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Run a complete agent turn with user message and tool execution."""
        turn_id = str(uuid.uuid4())

        # Create turn context
        ctx = TurnContext(
            session_id=session.id,
            turn_id=turn_id,
            user_message=user_message,
            messages=_build_messages(
                user_message=user_message,
                system_prompt=system_prompt or _default_system_prompt(),
            ),
        )

        # Emit ready event
        await self.emit_event(ctx, EventType.READY, {"message": "Agent ready"})

        # Store user message
        self.repo.add_message(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
            role="user",
            content=user_message,
            sequence=0,
        )
        ctx.messages.append({"role": "user", "content": user_message})

        # Emit processing event
        await self.emit_event(ctx, EventType.PROCESSING, {})

        # Get tool specs for LLM
        tool_specs = self.tools.openai_tools()

        # Track iterations
        iterations = 0
        tool_results: list[dict[str, Any]] = []

        while iterations < MAX_ITERATIONS:
            if self._interrupted:
                await self.emit_event(ctx, EventType.INTERRUPTED, {})
                break

            iterations += 1

            # Call LLM
            try:
                response = await self.llm.chat(
                    messages=ctx.messages,
                    tools=tool_specs if tool_specs else None,
                    tool_choice="auto" if tool_specs else None,
                    stream=True,
                )
            except Exception as e:
                await self.emit_event(ctx, EventType.ERROR, {"error": str(e)})
                raise

            # Process response
            full_content = response.content
            tool_calls = response.tool_calls

            # Emit assistant chunk (for streaming display)
            if full_content:
                await self.emit_event(
                    ctx,
                    EventType.ASSISTANT_CHUNK,
                    {"content": full_content, "finish_reason": response.finish_reason},
                )

            # Store assistant message
            assistant_content = full_content or ""
            if tool_calls:
                assistant_content = ""  # Tool calls are in raw_json

            self.repo.add_message(
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
                role="assistant",
                content=assistant_content,
                sequence=len(ctx.messages),
                raw=(
                    {"tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in tool_calls
                    ]}
                    if tool_calls else None
                ),
            )
            ctx.messages.append({
                "role": "assistant",
                "content": assistant_content,
                **({
                    "tool_calls": [
                        {"id": tc.id, "type": tc.type, "function": {
                            "name": tc.name,
                            "arguments": tc.arguments
                        }}
                        for tc in tool_calls
                    ]
                } if tool_calls else {}),
            })

            # If no tool calls, we're done
            if not tool_calls:
                await self.emit_event(
                    ctx, EventType.ASSISTANT_MESSAGE, {"content": full_content or ""}
                )
                await self.emit_event(
                    ctx, EventType.TURN_COMPLETE, {"iterations": iterations}
                )
                return {"status": "complete", "content": full_content, "iterations": iterations}

            # Process tool calls
            for tc in tool_calls:
                await self.emit_event(
                    ctx,
                    EventType.TOOL_CALL,
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                )

                # Check if approval is required
                requires_approval = tc.name in APPROVAL_REQUIRED_TOOLS

                if requires_approval and self.settings.safety.require_tool_approval:
                    # Emit approval required event and wait
                    await self.emit_event(
                        ctx,
                        EventType.APPROVAL_REQUIRED,
                        {
                            "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "arguments": tc.arguments,
                        },
                    )
                    # For now, auto-reject if approval not granted
                    # In full implementation, this would wait for user approval
                    tool_result = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            "Approval required. "
                            "Tool execution skipped pending user approval."
                        ),
                    }
                    tool_results.append(tool_result)
                    ctx.messages.append(tool_result)
                    continue

                # Execute tool
                try:
                    args = tc.arguments_as_json()
                    tool_output = await self.tools.call(tc.name, args)
                except Exception as e:
                    tool_output = f"Tool execution error: {e}"

                # Store tool result
                tool_result = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_output,
                }
                tool_results.append(tool_result)
                ctx.messages.append(tool_result)

                await self.emit_event(
                    ctx,
                    EventType.TOOL_OUTPUT,
                    {
                        "tool_call_id": tc.id,
                        "tool_name": tc.name,
                        "output": tool_output,
                        "success": "error" not in tool_output.lower(),
                    },
                )

        # Max iterations reached
        await self.emit_event(
            ctx,
            EventType.TURN_COMPLETE,
            {"iterations": iterations, "max_reached": True}
        )
        return {"status": "max_iterations", "iterations": iterations}

    def interrupt(self) -> None:
        """Signal the agent to stop after current operation."""
        self._interrupted = True


# ── Helper Functions ─────────────────────────────────────────────────────────────


def _utc_now() -> str:
    """Return current UTC time as ISO string."""
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


def _default_system_prompt() -> str:
    """Return the default system prompt for the ML Copilot agent."""
    return """You are an expert ML engineering assistant specialized in analyzing and improving machine learning codebases.

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


def _build_messages(user_message: str, system_prompt: str) -> list[dict[str, Any]]:
    """Build the message list for LLM completion."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
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
    """Create and populate the tool registry with workspace tools."""
    from app.tools import workspace

    registry = ToolRegistry()

    # Register workspace tools
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

    return registry


def _get_workspace_handler(name: str, settings: AppSettings):
    """Get the handler function for a workspace tool."""
    from app.tools import workspace as ws

    handlers = {
        "list_files": lambda args: ws.list_files_handler(args, settings),
        "read_file": lambda args: ws.read_file_handler(args, settings),
        "search_text": lambda args: ws.search_text_handler(args, settings),
        "git_status": lambda args: ws.git_status_handler(args, settings),
        "git_diff": lambda args: ws.git_diff_handler(args, settings),
    }

    return handlers.get(name)