"""Tool specification and registry primitives."""

from __future__ import annotations

import builtins
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

JsonDict = dict[str, Any]
ToolHandler = Callable[[JsonDict], Awaitable[str]]


class ToolRegistryError(RuntimeError):
    """Base error for tool registry failures."""


class DuplicateToolError(ToolRegistryError):
    """Raised when a tool name is registered more than once."""


class UnknownToolError(ToolRegistryError):
    """Raised when the requested tool does not exist."""


@dataclass(frozen=True)
class ToolSpec:
    """Description and callable for a single tool."""

    name: str
    description: str
    input_schema: JsonDict
    handler: ToolHandler = field(repr=False)

    def to_openai_tool(self) -> JsonDict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry:
    """In-memory registry for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> ToolSpec:
        if tool.name in self._tools:
            raise DuplicateToolError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> ToolSpec:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(f"Tool {name!r} is not registered.")
        return tool

    def list_tools(self) -> builtins.list[ToolSpec]:
        return builtins.list(self._tools.values())

    def list(self):
        return self.list_tools()

    def openai_tools(self) -> builtins.list[JsonDict]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    async def call(self, name: str, arguments: JsonDict | None = None) -> str:
        tool = self.get(name)
        return await tool.handler(arguments or {})
