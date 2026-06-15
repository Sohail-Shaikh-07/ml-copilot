import asyncio
import json

import httpx

from app.agent.llm import (
    LLMClient,
    LLMProtocolError,
    ToolCall,
    apply_stream_chunk,
    parse_chat_completion,
)
from app.config import AppSettings


def run(coro):
    return asyncio.run(coro)


class MockAsyncStream(httpx.AsyncByteStream):
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aiter__(self):
        for line in self._lines:
            yield f"{line}\n\n".encode("utf-8")


def test_parse_chat_completion_reads_content_tool_calls_and_usage() -> None:
    response = parse_chat_completion(
        {
            "id": "resp_123",
            "model": "gpt-5.4",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "I can help with that.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"README.md"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 7,
                "total_tokens": 17,
            },
        }
    )

    assert response.response_id == "resp_123"
    assert response.model == "gpt-5.4"
    assert response.content == "I can help with that."
    assert response.finish_reason == "tool_calls"
    assert response.usage is not None
    assert response.usage.total_tokens == 17
    assert response.tool_calls == [
        ToolCall(
            id="call_1",
            type="function",
            name="read_file",
            arguments='{"path":"README.md"}',
        )
    ]


def test_parse_chat_completion_requires_choices() -> None:
    try:
        parse_chat_completion({"id": "missing_choices"})
    except LLMProtocolError:
        pass
    else:
        raise AssertionError("Expected LLMProtocolError when choices are missing.")


def test_parse_chat_completion_rejects_malformed_tool_call_json() -> None:
    try:
        parse_chat_completion(
            {
                "id": "resp_bad_json",
                "model": "gpt-5.4",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_bad",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":',
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        )
    except LLMProtocolError as exc:
        assert "malformed JSON arguments" in str(exc)
    else:
        raise AssertionError("Expected malformed tool call JSON to raise LLMProtocolError.")


def test_apply_stream_chunk_accumulates_content_tool_calls_and_usage() -> None:
    from app.agent.llm import _StreamState

    state = _StreamState()

    apply_stream_chunk(
        state,
        {
            "id": "resp_stream",
            "model": "gpt-5.4",
            "choices": [
                {
                    "delta": {
                        "content": "Hello ",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "list_files",
                                    "arguments": '{"path":',
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
    )
    apply_stream_chunk(
        state,
        {
            "id": "resp_stream",
            "model": "gpt-5.4",
            "choices": [
                {
                    "delta": {
                        "content": "world",
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "arguments": '"."}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 8,
                "total_tokens": 28,
            },
        },
    )

    response = state.to_response()
    assert response.response_id == "resp_stream"
    assert response.content == "Hello world"
    assert response.finish_reason == "tool_calls"
    assert response.usage is not None
    assert response.usage.total_tokens == 28
    assert response.tool_calls[0].name == "list_files"
    assert response.tool_calls[0].arguments == '{"path":"."}'


def test_streamed_tool_call_arguments_raise_on_malformed_json() -> None:
    from app.agent.llm import _StreamState

    state = _StreamState()
    apply_stream_chunk(
        state,
        {
            "id": "resp_stream_bad",
            "model": "gpt-5.4",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_bad",
                                "type": "function",
                                "function": {
                                    "name": "search_text",
                                    "arguments": '{"query":',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    )

    response = state.to_response()
    try:
        response.tool_calls[0].arguments_as_json()
    except LLMProtocolError as exc:
        assert "malformed JSON arguments" in str(exc)
    else:
        raise AssertionError("Expected malformed streamed tool call JSON to raise LLMProtocolError.")


def test_client_non_streaming_chat_uses_openai_shape() -> None:
    recorded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["path"] = request.url.path
        recorded["authorization"] = request.headers.get("Authorization")
        recorded["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "resp_non_stream",
                "model": "demo-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "done",
                            "tool_calls": [],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    client = LLMClient(
        base_url="https://example.invalid/v1",
        api_key="secret",
        default_model="demo-model",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.invalid/v1",
        ),
    )

    response = run(
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"type": "function", "function": {"name": "list_files"}}],
            stream=False,
            temperature=0.2,
        )
    )

    assert recorded["path"] == "/v1/chat/completions"
    assert recorded["authorization"] == "Bearer secret"
    assert recorded["payload"]["model"] == "demo-model"
    assert recorded["payload"]["stream"] is False
    assert recorded["payload"]["messages"][0]["content"] == "hello"
    assert "tools" in recorded["payload"]
    assert response.content == "done"


def test_client_streaming_chat_aggregates_sse_chunks() -> None:
    first_chunk = {
        "id": "resp_stream",
        "model": "demo-model",
        "choices": [
            {
                "delta": {"content": "Hello "},
                "finish_reason": None,
            }
        ],
    }
    second_chunk = {
        "id": "resp_stream",
        "model": "demo-model",
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "search_text",
                                "arguments": '{"query":',
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    }
    third_chunk = {
        "id": "resp_stream",
        "model": "demo-model",
        "choices": [
            {
                "delta": {
                    "content": "there",
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {"arguments": '"ml"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 4,
            "total_tokens": 15,
        },
    }
    lines = [
        f"data: {json.dumps(first_chunk, separators=(',', ':'))}",
        f"data: {json.dumps(second_chunk, separators=(',', ':'))}",
        f"data: {json.dumps(third_chunk, separators=(',', ':'))}",
        "data: [DONE]",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=MockAsyncStream(lines),
        )

    client = LLMClient.from_settings(
        AppSettings.load(
            environ={
                "LLM_BASE_URL": "https://example.invalid/v1",
                "LLM_MODEL": "demo-model",
            }
        ),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.invalid/v1",
        ),
    )

    response = run(
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert response.model == "demo-model"
    assert response.content == "Hello there"
    assert response.finish_reason == "tool_calls"
    assert response.usage is not None
    assert response.usage.total_tokens == 15
    assert response.tool_calls[0].name == "search_text"
    assert response.tool_calls[0].arguments == '{"query":"ml"}'
    assert [event.type for event in response.events] == [
        "content_delta",
        "tool_call_delta",
        "content_delta",
        "tool_call_delta",
    ]


def test_client_anthropic_adapter_uses_native_messages_shape() -> None:
    recorded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["path"] = request.url.path
        recorded["headers"] = {
            "x-api-key": request.headers.get("x-api-key"),
            "anthropic-version": request.headers.get("anthropic-version"),
        }
        recorded["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 4, "output_tokens": 6},
            },
        )

    client = LLMClient(
        base_url="https://example.invalid/v1",
        api_key="anthropic-key",
        default_model="claude-test",
        provider="anthropic",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.invalid/v1",
        ),
    )

    response = run(
        client.chat(
            messages=[{"role": "system", "content": "Be concise."}, {"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert recorded["path"] == "/v1/messages"
    assert recorded["headers"]["x-api-key"] == "anthropic-key"
    assert recorded["headers"]["anthropic-version"] == "2023-06-01"
    assert recorded["payload"]["system"] == "Be concise."
    assert recorded["payload"]["messages"] == [{"role": "user", "content": "hello"}]
    assert response.content == "done"
    assert response.finish_reason == "end_turn"
    assert response.usage is not None
    assert response.usage.total_tokens == 10


def test_client_gemini_adapter_parses_function_calls() -> None:
    recorded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["path"] = request.url.path
        recorded["params"] = dict(request.url.params)
        recorded["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "gemini_resp_123",
                "model": "gemini-test",
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {"text": "working"},
                                {
                                    "functionCall": {
                                        "id": "call_1",
                                        "name": "read_file",
                                        "args": {"path": "README.md"},
                                    }
                                },
                            ]
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 8,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 13,
                },
            },
        )

    client = LLMClient(
        base_url="https://example.invalid/v1beta",
        api_key="gemini-key",
        default_model="gemini-test",
        provider="gemini",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://example.invalid/v1beta",
        ),
    )

    response = run(
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
        )
    )

    assert recorded["path"] == "/v1beta/models/gemini-test:generateContent"
    assert recorded["params"]["key"] == "gemini-key"
    assert recorded["payload"]["contents"] == [{"role": "user", "parts": [{"text": "hello"}]}]
    assert response.content == "working"
    assert response.tool_calls[0].name == "read_file"
    assert response.tool_calls[0].arguments == '{"path":"README.md"}'
    assert response.usage is not None
    assert response.usage.total_tokens == 13
