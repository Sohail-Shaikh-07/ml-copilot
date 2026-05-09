import asyncio

from app.tools import DuplicateToolError, ToolRegistry, ToolSpec, UnknownToolError


def run(coro):
    return asyncio.run(coro)


async def list_files_handler(arguments: dict[str, object]) -> str:
    return f"listing:{arguments['path']}"


def test_toolspec_exports_openai_function_shape() -> None:
    spec = ToolSpec(
        name="list_files",
        description="List files in a workspace path.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=list_files_handler,
    )

    assert spec.to_openai_tool() == {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a workspace path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }


def test_registry_registers_lists_and_calls_tools() -> None:
    registry = ToolRegistry()
    spec = ToolSpec(
        name="list_files",
        description="List files in a workspace path.",
        input_schema={"type": "object"},
        handler=list_files_handler,
    )

    registry.register(spec)

    assert registry.get("list_files") == spec
    assert registry.list_tools() == [spec]
    assert registry.list() == [spec]
    assert registry.openai_tools() == [spec.to_openai_tool()]
    assert run(registry.call("list_files", {"path": "."})) == "listing:."


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="list_files",
            description="List files.",
            input_schema={"type": "object"},
            handler=list_files_handler,
        )
    )

    try:
        registry.register(
            ToolSpec(
                name="list_files",
                description="Duplicate list files.",
                input_schema={"type": "object"},
                handler=list_files_handler,
            )
        )
    except DuplicateToolError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("Expected duplicate registration to raise DuplicateToolError.")


def test_registry_raises_for_unknown_tool_lookup_and_call() -> None:
    registry = ToolRegistry()

    try:
        registry.get("missing_tool")
    except UnknownToolError as exc:
        assert "missing_tool" in str(exc)
    else:
        raise AssertionError("Expected get() to raise UnknownToolError.")

    try:
        run(registry.call("missing_tool"))
    except UnknownToolError as exc:
        assert "missing_tool" in str(exc)
    else:
        raise AssertionError("Expected call() to raise UnknownToolError.")
