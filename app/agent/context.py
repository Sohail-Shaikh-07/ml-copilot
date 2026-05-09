"""Context builder for agent messages with token budgeting and summarization support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.storage.models import MessageRecord

# Rough character-to-token ratio (for simple budgeting without tiktoken)
CHARS_PER_TOKEN = 4

# Default budget limits
DEFAULT_MESSAGE_BUDGET = 100_000  # characters
DEFAULT_SYSTEM_BUDGET = 8_000  # characters


@dataclass
class ContextBudget:
    """Budget constraints for context building."""

    max_chars: int = DEFAULT_MESSAGE_BUDGET
    max_system_chars: int = DEFAULT_SYSTEM_BUDGET
    include_system: bool = True


@dataclass
class MessageForContext:
    """A message prepared for context inclusion."""

    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    is_summary: bool = False


@dataclass
class BuiltContext:
    """Built context with messages and metadata."""

    messages: list[dict[str, Any]]
    total_chars: int
    truncated: bool
    summary: str | None = None


class ContextBuilder:
    """Builds context messages for LLM completion with budget management."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def build(
        self,
        recent_messages: list[MessageRecord],
        system_prompt: str | None = None,
        summary: str | None = None,
    ) -> BuiltContext:
        """Build context messages within budget constraints.

        Args:
            recent_messages: Messages from the session (newest last)
            system_prompt: System prompt to prepend
            summary: Optional summary of older conversation

        Returns:
            BuiltContext with messages ready for LLM and metadata
        """
        output_messages: list[dict[str, Any]] = []
        total_chars = 0
        truncated = False

        # Add system prompt (with optional summary)
        if self.budget.include_system and system_prompt:
            system_content = system_prompt
            if summary:
                system_content = (
                    f"[Prior conversation summary]:\n{summary}\n\n"
                    f"[Current session]:\n{system_prompt}"
                )

            if len(system_content) > self.budget.max_system_chars:
                system_content = (
                    f"{system_content[: self.budget.max_system_chars - 50]}"
                    "\n... [truncated]"
                )
                truncated = True

            output_messages.append({"role": "system", "content": system_content})
            total_chars += len(system_content)

        # Convert MessageRecords to MessageForContext
        msg_for_context: list[MessageForContext] = []
        for msg in recent_messages:
            mc = MessageForContext(
                role=msg.role,
                content=msg.content,
                tool_call_id=msg.tool_call_id,
                name=msg.name,
            )
            msg_for_context.append(mc)

        # Build message list, newest first for context
        # Start from most recent and work backwards
        available_budget = self.budget.max_chars - total_chars
        selected_messages: list[MessageForContext] = []

        # Take newest messages first until budget is exhausted
        for msg in reversed(msg_for_context):
            msg_chars = len(msg.content) + 50  # +50 for role/name overhead

            if available_budget - msg_chars < 0:
                truncated = True
                break

            selected_messages.insert(0, msg)
            available_budget -= msg_chars
            total_chars += msg_chars

        # Convert to message dicts
        for msg in selected_messages:
            msg_dict: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                msg_dict["name"] = msg.name
            output_messages.append(msg_dict)

        return BuiltContext(
            messages=output_messages,
            total_chars=total_chars,
            truncated=truncated,
            summary=summary,
        )

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count from text."""
        return len(text) // CHARS_PER_TOKEN

    def should_summarize(self, messages: list[MessageRecord], threshold: float = 0.8) -> bool:
        """Check if messages should be summarized based on total length.

        Args:
            messages: All messages to check
            threshold: Ratio of budget at which summarization is suggested (default 0.8)

        Returns:
            True if summarization is recommended
        """
        total_chars = sum(len(m.content) for m in messages)
        return total_chars > (self.budget.max_chars * threshold)


class Summarizer:
    """Placeholder for future context summarization using LLM."""

    def summarize(self, messages: list[MessageForContext]) -> str:
        """Summarize a list of messages.

        This is a placeholder. In full implementation, this would call
        an LLM to generate a summary of the conversation history.
        """
        if not messages:
            return ""

        # Simple placeholder: just count messages
        role_counts: dict[str, int] = {}
        for msg in messages:
            role_counts[msg.role] = role_counts.get(msg.role, 0) + 1

        parts = [f"Conversation summary ({len(messages)} messages):"]
        for role, count in role_counts.items():
            parts.append(f"- {count} {role} message(s)")

        return "; ".join(parts)


def create_context_builder(
    max_chars: int | None = None,
    max_system_chars: int | None = None,
) -> ContextBuilder:
    """Create a configured context builder."""
    budget = ContextBudget(
        max_chars=max_chars or DEFAULT_MESSAGE_BUDGET,
        max_system_chars=max_system_chars or DEFAULT_SYSTEM_BUDGET,
    )
    return ContextBuilder(budget)


def messages_to_context_dict(
    messages: list[MessageRecord],
    system_prompt: str | None = None,
    summary: str | None = None,
    max_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Convenience function to convert messages to context dict for LLM.

    Args:
        messages: Session messages
        system_prompt: System prompt
        summary: Optional conversation summary
        max_chars: Optional max characters budget

    Returns:
        List of message dicts ready for LLM
    """
    builder = create_context_builder(max_chars=max_chars)
    ctx = builder.build(messages, system_prompt=system_prompt, summary=summary)
    return ctx.messages