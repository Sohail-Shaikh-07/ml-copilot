"""Provider-aware LLM client and wire-format parsers."""

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


@dataclass(frozen=True)
class ProviderRequest:
    path: str
    body: JsonDict
    headers: dict[str, str]
    params: dict[str, str] | None = None


class LLMError(RuntimeError):
    """Base error for LLM client failures."""


class LLMProtocolError(LLMError):
    """Raised when the remote response does not match the expected schema."""


def normalize_provider_name(value: str | None) -> str:
    normalized = (value or "openai_compatible").strip().lower().replace("-", "_")
    if normalized in {"openai", "openai_compatible", "compatible"}:
        return "openai_compatible"
    if normalized in {"anthropic", "claude"}:
        return "anthropic"
    if normalized in {"gemini", "google_gemini", "google"}:
        return "gemini"
    if normalized in {"xai", "grok"}:
        return "xai"
    if normalized == "minimax":
        return "minimax"
    if normalized == "kimi":
        return "kimi"
    if normalized in {"zai", "z_ai", "z"}:
        return "zai"
    raise ValueError(f"Unsupported LLM provider: {value!r}")


class _ProviderAdapter:
    supports_streaming = False

    def build_request(
        self,
        *,
        messages: list[JsonDict],
        tools: list[JsonDict] | None,
        tool_choice: str | JsonDict | None,
        stream: bool,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> ProviderRequest:
        raise NotImplementedError

    def parse_response(self, payload: JsonDict) -> LLMResponse:
        raise NotImplementedError


class _OpenAICompatibleAdapter(_ProviderAdapter):
    supports_streaming = True

    def __init__(self, *, base_url: str, api_key: str | None, default_model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def build_request(
        self,
        *,
        messages: list[JsonDict],
        tools: list[JsonDict] | None,
        tool_choice: str | JsonDict | None,
        stream: bool,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> ProviderRequest:
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
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return ProviderRequest(path="/chat/completions", body=payload, headers=headers)

    def parse_response(self, payload: JsonDict) -> LLMResponse:
        return parse_chat_completion(payload)


class _AnthropicAdapter(_ProviderAdapter):
    def __init__(self, *, base_url: str, api_key: str | None, default_model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def build_request(
        self,
        *,
        messages: list[JsonDict],
        tools: list[JsonDict] | None,
        tool_choice: str | JsonDict | None,
        stream: bool,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> ProviderRequest:
        system_parts, anthropic_messages = _anthropic_messages(messages)
        payload: JsonDict = {
            "model": model or self.default_model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens or 2048,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [_anthropic_tool_spec(tool) for tool in tools]
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return ProviderRequest(path="/messages", body=payload, headers=headers)

    def parse_response(self, payload: JsonDict) -> LLMResponse:
        content_parts = payload.get("content") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for item in content_parts:
            part_type = item.get("type")
            if part_type == "text":
                text_parts.append(item.get("text") or "")
            elif part_type == "tool_use":
                arguments = item.get("input") or {}
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, separators=(",", ":"))
                tool_calls.append(
                    ToolCall(
                        id=item.get("id", ""),
                        type="function",
                        name=item.get("name", ""),
                        arguments=arguments,
                    )
                )

        usage_data = payload.get("usage") or {}
        usage = None
        if usage_data:
            usage = Usage(
                prompt_tokens=int(usage_data.get("input_tokens", 0) or 0),
                completion_tokens=int(usage_data.get("output_tokens", 0) or 0),
                total_tokens=int(usage_data.get("input_tokens", 0) or 0) + int(usage_data.get("output_tokens", 0) or 0),
            )

        for tool_call in tool_calls:
            tool_call.arguments_as_json()

        return LLMResponse(
            model=payload.get("model", ""),
            content="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=payload.get("stop_reason"),
            usage=usage,
            response_id=payload.get("id"),
            raw=payload,
        )


class _GeminiAdapter(_ProviderAdapter):
    def __init__(self, *, base_url: str, api_key: str | None, default_model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def build_request(
        self,
        *,
        messages: list[JsonDict],
        tools: list[JsonDict] | None,
        tool_choice: str | JsonDict | None,
        stream: bool,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
    ) -> ProviderRequest:
        system_parts, contents = _gemini_contents(messages)
        payload: JsonDict = {
            "contents": contents,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [_gemini_function(tool) for tool in tools]}]
        generation_config: JsonDict = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        elif stream:
            generation_config["maxOutputTokens"] = 2048
        if generation_config:
            payload["generationConfig"] = generation_config
        if tool_choice is not None:
            payload["toolConfig"] = _gemini_tool_config(tool_choice)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        params = {"key": self.api_key} if self.api_key else None
        model_path = model or self.default_model
        if not model_path.startswith("models/"):
            model_path = f"models/{model_path}"
        return ProviderRequest(
            path=f"/{model_path}:generateContent",
            body=payload,
            headers=headers,
            params=params,
        )

    def parse_response(self, payload: JsonDict) -> LLMResponse:
        candidates = payload.get("candidates") or []
        if not candidates:
            raise LLMProtocolError("Gemini response did not include candidates.")

        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for index, part in enumerate(parts):
            if "text" in part:
                text_parts.append(part.get("text") or "")
                continue
            function_call = part.get("functionCall") or part.get("function_call") or {}
            if function_call:
                arguments = (
                    function_call.get("args") or function_call.get("arguments") or function_call.get("input") or {}
                )
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, separators=(",", ":"))
                tool_calls.append(
                    ToolCall(
                        id=function_call.get("id") or f"gemini-tool-{index}",
                        type="function",
                        name=function_call.get("name", ""),
                        arguments=arguments,
                    )
                )

        usage_data = payload.get("usageMetadata") or {}
        usage = None
        if usage_data:
            prompt_tokens = int(usage_data.get("promptTokenCount", 0) or 0)
            completion_tokens = int(usage_data.get("candidatesTokenCount", 0) or 0)
            total_tokens = int(usage_data.get("totalTokenCount", 0) or 0)
            if not total_tokens:
                total_tokens = prompt_tokens + completion_tokens
            usage = Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )

        for tool_call in tool_calls:
            tool_call.arguments_as_json()

        return LLMResponse(
            model=payload.get("model", ""),
            content="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=candidate.get("finishReason") or candidate.get("finish_reason"),
            usage=usage,
            response_id=payload.get("responseId") or payload.get("id"),
            raw=payload,
        )


def build_provider_adapter(
    *,
    provider: str,
    base_url: str,
    api_key: str | None,
    default_model: str,
) -> _ProviderAdapter:
    normalized = normalize_provider_name(provider)
    if normalized == "anthropic":
        return _AnthropicAdapter(base_url=base_url, api_key=api_key, default_model=default_model)
    if normalized == "gemini":
        return _GeminiAdapter(base_url=base_url, api_key=api_key, default_model=default_model)
    return _OpenAICompatibleAdapter(base_url=base_url, api_key=api_key, default_model=default_model)


def _anthropic_tool_spec(tool: JsonDict) -> JsonDict:
    function = tool.get("function") or {}
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "input_schema": function.get("parameters")
        or function.get("input_schema")
        or {"type": "object", "properties": {}},
    }


def _anthropic_messages(messages: list[JsonDict]) -> tuple[list[str], list[JsonDict]]:
    system_parts: list[str] = []
    converted: list[JsonDict] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(str(content))
            continue

        if role == "assistant" and message.get("tool_calls"):
            blocks: list[JsonDict] = []
            if content:
                blocks.append({"type": "text", "text": str(content)})
            for tool_call in message.get("tool_calls") or []:
                arguments = ((tool_call.get("function") or {}).get("arguments")) or "{}"
                try:
                    parsed_arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed_arguments = {"__raw_arguments__": arguments}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.get("id", ""),
                        "name": ((tool_call.get("function") or {}).get("name") or ""),
                        "input": parsed_arguments,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue

        if role == "tool":
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id", ""),
                            "content": [{"type": "text", "text": str(content)}],
                        }
                    ],
                }
            )
            continue

        converted.append({"role": role, "content": str(content)})

    return system_parts, converted


def _gemini_tool_config(tool_choice: str | JsonDict) -> JsonDict:
    if isinstance(tool_choice, str):
        mode = "AUTO" if tool_choice == "auto" else tool_choice.upper()
        return {"functionCallingConfig": {"mode": mode}}
    return {"functionCallingConfig": tool_choice}


def _gemini_function(tool: JsonDict) -> JsonDict:
    function = tool.get("function") or {}
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "parameters": function.get("parameters") or {"type": "object", "properties": {}},
    }


def _gemini_contents(messages: list[JsonDict]) -> tuple[list[str], list[JsonDict]]:
    system_parts: list[str] = []
    contents: list[JsonDict] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role == "system":
            if content:
                system_parts.append(str(content))
            continue

        if role == "assistant" and message.get("tool_calls"):
            parts: list[JsonDict] = []
            if content:
                parts.append({"text": str(content)})
            for tool_call in message.get("tool_calls") or []:
                arguments = ((tool_call.get("function") or {}).get("arguments")) or "{}"
                try:
                    parsed_arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed_arguments = {"__raw_arguments__": arguments}
                parts.append(
                    {
                        "functionCall": {
                            "id": tool_call.get("id", ""),
                            "name": ((tool_call.get("function") or {}).get("name") or ""),
                            "args": parsed_arguments,
                        }
                    }
                )
            contents.append({"role": "model", "parts": parts})
            continue

        if role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": message.get("name", ""),
                                "id": message.get("tool_call_id", ""),
                                "response": {"output": str(content)},
                            }
                        }
                    ],
                }
            )
            continue

        contents.append({"role": "user" if role == "user" else "model", "parts": [{"text": str(content)}]})

    return system_parts, contents


class LLMClient:
    """Provider-aware client that keeps one stable internal interface."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        default_model: str,
        provider: str = "openai_compatible",
        timeout_seconds: int = 600,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.provider = normalize_provider_name(provider)
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._adapter = build_provider_adapter(
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            default_model=self.default_model,
        )

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
            provider=settings.llm.provider,
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
        request = self._adapter.build_request(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            model=model or self.default_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if stream and self._adapter.supports_streaming:
            return await self._chat_stream(request)
        return await self._chat_once(request)

    async def _chat_once(self, request: ProviderRequest) -> LLMResponse:
        async with self._client() as client:
            response = await client.post(
                request.path,
                json=request.body,
                params=request.params,
                headers=request.headers,
            )
            response.raise_for_status()
            data = response.json()
        return self._adapter.parse_response(data)

    async def _chat_stream(self, request: ProviderRequest) -> LLMResponse:
        state = _StreamState()
        async with self._client() as client:
            async with client.stream(
                "POST",
                request.path,
                json=request.body,
                params=request.params,
                headers=request.headers,
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
