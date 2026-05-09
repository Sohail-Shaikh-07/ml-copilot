"""OpenAI-compatible LLM client and wire-format parsers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import AppSettings

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    type: str = "function"

    def arguments_as_json(self) -> JsonDict:
        try:
            return json.loads(self.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise LLMProtocolError(
                f"Tool call {self.id or self.name or '<unknown>'} returned malformed JSON arguments."
            ) from exc


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class StreamEvent:
    type: str
    data: JsonDict


@dataclass(frozen=True)
class LLMResponse:
    model: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
    response_id: str | None = None
    events: list[StreamEvent] = field(default_factory=list)
    raw: JsonDict | None = None


class LLMError(RuntimeError):
    """Base error for LLM client failures."""


class LLMProtocolError(LLMError):
    """Raised when the remote response does not match the expected schema."""


class LLMClient:
    """Small provider-neutral client for OpenAI-compatible chat completions."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        default_model: str,
        timeout_seconds: int = 600,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> "LLMClient":
        return cls(
            base_url=settings.llm.base_url,
            api_key=settings.llm.api_key,
            default_model=settings.llm.model,
            timeout_seconds=settings.llm.timeout_seconds,
            http_client=http_client,
        )

    async def chat(
        self,
        messages: list[JsonDict],
        tools: list[JsonDict] | None = None,
        tool_choice: str | JsonDict | None = "auto",
        stream: bool = True,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload = self._build_payload(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if stream:
            return await self._chat_stream(payload)
        return await self._chat_once(payload)

    def _build_payload(
        self,
        *,
        messages: list[JsonDict],
        tools: list[JsonDict] | None,
        tool_choice: str | JsonDict | None,
        stream: bool,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> JsonDict:
        payload: JsonDict = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _chat_once(self, payload: JsonDict) -> LLMResponse:
        async with self._client() as client:
            response = await client.post(
                "/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
        return parse_chat_completion(data)

    async def _chat_stream(self, payload: JsonDict) -> LLMResponse:
        state = _StreamState()
        async with self._client() as client:
            async with client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    chunk = json.loads(body)
                    apply_stream_chunk(state, chunk)
        return state.to_response()

    def _client(self) -> "_ClientContextManager":
        if self._http_client is not None:
            return _ClientContextManager(self._http_client, close_on_exit=False)
        client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )
        return _ClientContextManager(client, close_on_exit=True)


class _ClientContextManager:
    def __init__(self, client: httpx.AsyncClient, *, close_on_exit: bool) -> None:
        self._client = client
        self._close_on_exit = close_on_exit

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._close_on_exit:
            await self._client.aclose()


def parse_chat_completion(payload: JsonDict) -> LLMResponse:
    choices = payload.get("choices")
    if not choices:
        raise LLMProtocolError("Chat completion response did not include choices.")

    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    tool_calls = [
        ToolCall(
            id=item.get("id", ""),
            type=item.get("type", "function"),
            name=((item.get("function") or {}).get("name") or ""),
            arguments=((item.get("function") or {}).get("arguments") or ""),
        )
        for item in message.get("tool_calls") or []
    ]
    usage_data = payload.get("usage")
    usage = parse_usage(usage_data) if usage_data else None

    for tool_call in tool_calls:
        tool_call.arguments_as_json()

    return LLMResponse(
        model=payload.get("model", ""),
        content=content,
        tool_calls=tool_calls,
        finish_reason=choice.get("finish_reason"),
        usage=usage,
        response_id=payload.get("id"),
        raw=payload,
    )


def parse_usage(payload: JsonDict) -> Usage:
    return Usage(
        prompt_tokens=int(payload.get("prompt_tokens", 0) or 0),
        completion_tokens=int(payload.get("completion_tokens", 0) or 0),
        total_tokens=int(payload.get("total_tokens", 0) or 0),
    )


@dataclass
class _ToolCallBuilder:
    id: str = ""
    type: str = "function"
    name: str = ""
    arguments: str = ""

    def to_tool_call(self) -> ToolCall:
        return ToolCall(
            id=self.id,
            type=self.type,
            name=self.name,
            arguments=self.arguments,
        )


@dataclass
class _StreamState:
    model: str = ""
    content_parts: list[str] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None
    response_id: str | None = None
    events: list[StreamEvent] = field(default_factory=list)
    tool_calls: dict[int, _ToolCallBuilder] = field(default_factory=dict)

    def to_response(self) -> LLMResponse:
        ordered_tool_calls = [
            builder.to_tool_call() for _, builder in sorted(self.tool_calls.items(), key=lambda item: item[0])
        ]
        return LLMResponse(
            model=self.model,
            content="".join(self.content_parts),
            tool_calls=ordered_tool_calls,
            finish_reason=self.finish_reason,
            usage=self.usage,
            response_id=self.response_id,
            events=self.events,
        )


def apply_stream_chunk(state: _StreamState, payload: JsonDict) -> None:
    if not state.model:
        state.model = payload.get("model", "")
    if state.response_id is None:
        state.response_id = payload.get("id")
    if payload.get("usage"):
        state.usage = parse_usage(payload["usage"])

    choices = payload.get("choices") or []
    if not choices:
        return

    choice = choices[0]
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")
    if finish_reason:
        state.finish_reason = finish_reason

    content_piece = delta.get("content")
    if content_piece:
        state.content_parts.append(content_piece)
        state.events.append(StreamEvent(type="content_delta", data={"content": content_piece}))

    for item in delta.get("tool_calls") or []:
        index = int(item.get("index", 0))
        builder = state.tool_calls.setdefault(index, _ToolCallBuilder())
        builder.id = item.get("id", builder.id)
        builder.type = item.get("type", builder.type)
        function = item.get("function") or {}
        builder.name = function.get("name", builder.name)
        builder.arguments += function.get("arguments", "")
        state.events.append(
            StreamEvent(
                type="tool_call_delta",
                data={
                    "index": index,
                    "id": builder.id,
                    "name": builder.name,
                    "arguments": function.get("arguments", ""),
                },
            )
        )
