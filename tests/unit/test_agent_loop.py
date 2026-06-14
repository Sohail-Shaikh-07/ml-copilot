from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agent.llm import LLMResponse, ToolCall
from app.agent.loop import AgentLoop, _create_tool_registry
from app.config import AppPaths, AppSettings
from app.storage.repository import SQLiteRepository
from app.tools.registry import ToolRegistry, ToolSpec


class DummyLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


async def _async_handler(output: str, calls: list[dict[str, object]], args: dict[str, object]) -> str:
    calls.append(args)
    return output


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings.from_paths(AppPaths.from_workspace_root(tmp_path))


def _repository(tmp_path: Path) -> SQLiteRepository:
    repository = SQLiteRepository(tmp_path / "ml-copilot.db")
    repository.initialize()
    return repository


def _registry(tool_output: str, tool_calls: list[dict[str, object]]) -> ToolRegistry:
    registry = ToolRegistry()

    async def run_command_handler(args: dict[str, object]) -> str:
        return await _async_handler(tool_output, tool_calls, args)

    registry.register(
        ToolSpec(
            name="run_command",
            description="Run a command",
            input_schema={"type": "object"},
            handler=run_command_handler,
        )
    )
    return registry


def test_tool_registry_includes_paper_details(tmp_path: Path) -> None:
    registry = _create_tool_registry(_settings(tmp_path))

    assert registry.get("paper_details").name == "paper_details"
    assert registry.get("analyze_ml_repo").name == "analyze_ml_repo"


@pytest.mark.asyncio
async def test_run_turn_persists_pending_approval_and_resumes_after_approval(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session = repository.create_session(session_id="session-1", title="Approval", model="gpt-5.4")
    tool_invocations: list[dict[str, object]] = []
    llm = DummyLLM(
        responses=[
            LLMResponse(
                model="gpt-5.4",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_command",
                        arguments='{"command":"pytest"}',
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                model="gpt-5.4",
                content="Command executed successfully.",
                finish_reason="stop",
            ),
        ]
    )
    loop = AgentLoop(
        llm_client=llm,
        tool_registry=_registry("pytest ok", tool_invocations),
        repository=repository,
        settings=_settings(tmp_path),
    )

    first_result = await loop.run_turn(session, "Run the tests")
    pending = repository.list_pending_approvals(session.id)

    assert first_result["status"] == "approval_required"
    assert len(pending) == 1
    assert repository.list_messages(session.id)[-1].role == "assistant"

    final_result = await loop.resume_pending_approval(
        session,
        pending[0].approval.id,
        approved=True,
        user_feedback="approved",
    )

    updated_approval = repository.get_approval(pending[0].approval.id)
    updated_tool_call = repository.get_tool_call("call-1")
    second_call_messages = llm.calls[1]["messages"]

    assert final_result["status"] == "complete"
    assert updated_approval is not None
    assert updated_approval.status == "approved"
    assert updated_tool_call is not None
    assert updated_tool_call.status == "completed"
    assert tool_invocations == [{"command": "pytest"}]
    assert repository.list_pending_approvals(session.id) == []
    assert any(message["role"] == "tool" and message["content"] == "pytest ok" for message in second_call_messages)
    assert any(message["role"] == "assistant" and message.get("tool_calls") for message in second_call_messages)


@pytest.mark.asyncio
async def test_rejecting_pending_approval_resumes_loop_with_tool_feedback(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session = repository.create_session(session_id="session-1", title="Reject", model="gpt-5.4")
    tool_invocations: list[dict[str, object]] = []
    llm = DummyLLM(
        responses=[
            LLMResponse(
                model="gpt-5.4",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_command",
                        arguments='{"command":"rm -rf ."}',
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                model="gpt-5.4",
                content="Understood. I will not run that command.",
                finish_reason="stop",
            ),
        ]
    )
    loop = AgentLoop(
        llm_client=llm,
        tool_registry=_registry("should not run", tool_invocations),
        repository=repository,
        settings=_settings(tmp_path),
    )

    await loop.run_turn(session, "Clean the repo")
    pending = repository.list_pending_approvals(session.id)
    result = await loop.resume_pending_approval(
        session,
        pending[0].approval.id,
        approved=False,
        user_feedback="skip it",
    )

    updated_approval = repository.get_approval(pending[0].approval.id)
    updated_tool_call = repository.get_tool_call("call-1")
    second_call_messages = llm.calls[1]["messages"]

    assert result["status"] == "complete"
    assert updated_approval is not None
    assert updated_approval.status == "rejected"
    assert updated_tool_call is not None
    assert updated_tool_call.status == "rejected"
    assert tool_invocations == []
    assert any(
        message["role"] == "tool" and "rejected by user" in message["content"] for message in second_call_messages
    )


@pytest.mark.asyncio
async def test_multiple_pending_approvals_wait_until_all_decisions_are_recorded(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session = repository.create_session(session_id="session-1", title="Batch", model="gpt-5.4")
    tool_invocations: list[dict[str, object]] = []
    llm = DummyLLM(
        responses=[
            LLMResponse(
                model="gpt-5.4",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_command",
                        arguments='{"command":"pytest"}',
                    ),
                    ToolCall(
                        id="call-2",
                        name="run_command",
                        arguments='{"command":"ruff check app"}',
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                model="gpt-5.4",
                content="Both approved commands completed.",
                finish_reason="stop",
            ),
        ]
    )
    loop = AgentLoop(
        llm_client=llm,
        tool_registry=_registry("command ok", tool_invocations),
        repository=repository,
        settings=_settings(tmp_path),
    )

    first_result = await loop.run_turn(session, "Run both checks")
    pending = repository.list_pending_approvals(session.id)

    assert first_result["status"] == "approval_required"
    assert len(pending) == 2
    assert len(llm.calls) == 1

    second_result = await loop.resume_pending_approval(
        session,
        pending[0].approval.id,
        approved=True,
        user_feedback="approve first",
    )

    remaining_pending = repository.list_pending_approvals(session.id)
    assert second_result["status"] == "approval_required"
    assert len(second_result["pending_approvals"]) == 1
    assert len(remaining_pending) == 1
    assert remaining_pending[0].tool_call.id == "call-2"
    assert len(llm.calls) == 1
    assert tool_invocations == [{"command": "pytest"}]

    final_result = await loop.resume_pending_approval(
        session,
        remaining_pending[0].approval.id,
        approved=True,
        user_feedback="approve second",
    )

    final_messages = llm.calls[1]["messages"]

    assert final_result["status"] == "complete"
    assert repository.list_pending_approvals(session.id) == []
    assert len(llm.calls) == 2
    assert tool_invocations == [{"command": "pytest"}, {"command": "ruff check app"}]
    assert any(message["role"] == "tool" and message["content"] == "command ok" for message in final_messages)


@pytest.mark.asyncio
async def test_approved_tool_uses_edited_arguments(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session = repository.create_session(session_id="session-1", title="Edited", model="gpt-5.4")
    tool_invocations: list[dict[str, object]] = []
    llm = DummyLLM(
        responses=[
            LLMResponse(
                model="gpt-5.4",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_command",
                        arguments='{"command":"pytest"}',
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                model="gpt-5.4",
                content="Edited command completed.",
                finish_reason="stop",
            ),
        ]
    )
    loop = AgentLoop(
        llm_client=llm,
        tool_registry=_registry("command ok", tool_invocations),
        repository=repository,
        settings=_settings(tmp_path),
    )

    await loop.run_turn(session, "Run the tests")
    pending = repository.list_pending_approvals(session.id)
    result = await loop.resume_pending_approval(
        session,
        pending[0].approval.id,
        approved=True,
        user_feedback="use quieter command",
        edited_arguments={"command": "pytest -q"},
    )

    updated_approval = repository.get_approval(pending[0].approval.id)
    updated_tool_call = repository.get_tool_call("call-1")

    assert result["status"] == "complete"
    assert updated_approval is not None
    assert updated_approval.edited_payload_json == '{"command": "pytest -q"}'
    assert updated_tool_call is not None
    assert updated_tool_call.arguments_json == '{"command": "pytest -q"}'
    assert tool_invocations == [{"command": "pytest -q"}]


@pytest.mark.asyncio
async def test_new_user_message_abandons_pending_approvals_before_continuing(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session = repository.create_session(session_id="session-1", title="Abandon", model="gpt-5.4")
    tool_invocations: list[dict[str, object]] = []
    llm = DummyLLM(
        responses=[
            LLMResponse(
                model="gpt-5.4",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="run_command",
                        arguments='{"command":"pytest"}',
                    )
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                model="gpt-5.4",
                content="Continuing with the new request only.",
                finish_reason="stop",
            ),
        ]
    )
    loop = AgentLoop(
        llm_client=llm,
        tool_registry=_registry("should not run", tool_invocations),
        repository=repository,
        settings=_settings(tmp_path),
    )

    first_result = await loop.run_turn(session, "Run the tests")
    assert first_result["status"] == "approval_required"

    second_result = await loop.run_turn(session, "Ignore that and just summarize")
    updated_tool_call = repository.get_tool_call("call-1")
    updated_approval = repository.list_pending_approvals(session.id)
    latest_messages = llm.calls[1]["messages"]

    assert second_result["status"] == "complete"
    assert updated_tool_call is not None
    assert updated_tool_call.status == "abandoned"
    assert updated_tool_call.output == "Tool execution abandoned because the user continued the conversation."
    assert updated_approval == []
    assert tool_invocations == []
    assert any(
        message["role"] == "tool" and "abandoned because the user continued the conversation" in message["content"]
        for message in latest_messages
    )


@pytest.mark.asyncio
async def test_cancelled_tool_call_is_recorded_as_interrupted(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session = repository.create_session(session_id="session-1", title="Cancel Tool", model="gpt-5.4")
    tool_started = asyncio.Event()

    async def slow_tool_handler(args: dict[str, object]) -> str:
        tool_started.set()
        await asyncio.sleep(30)
        return "should not complete"

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="slow_tool",
            description="Slow test tool",
            input_schema={"type": "object"},
            handler=slow_tool_handler,
        )
    )
    llm = DummyLLM(
        responses=[
            LLMResponse(
                model="gpt-5.4",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="slow_tool",
                        arguments="{}",
                    )
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    loop = AgentLoop(
        llm_client=llm,
        tool_registry=registry,
        repository=repository,
        settings=_settings(tmp_path),
    )

    task = asyncio.create_task(loop.run_turn(session, "Run the slow tool"))
    await asyncio.wait_for(tool_started.wait(), timeout=2)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    tool_call = repository.get_tool_call("call-1")
    event_types = [event.event_type for event in repository.list_events(session.id)]

    assert tool_call is not None
    assert tool_call.status == "interrupted"
    assert tool_call.output == "Tool execution interrupted."
    assert "tool_output" in event_types
    assert event_types[-1] == "interrupted"
