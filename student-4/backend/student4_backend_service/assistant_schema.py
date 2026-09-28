"""Constrain model tool arguments with the schemas actually registered in MCP."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .assistant_models import ACTION

if TYPE_CHECKING:
    from mcp.types import Tool


def compact_schema(value: Any, prefix: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: (
                item.replace("#/$defs/", f"#/$defs/{prefix}")
                if key == "$ref" and isinstance(item, str)
                else compact_schema(item, prefix)
            )
            for key, item in value.items()
            if key not in {"title", "description", "default"}
        }
    if isinstance(value, list):
        return [compact_schema(item, prefix) for item in value]
    return value


def action_schema(
    tools: list[Tool], *, activity_ids: list[str] | None = None
) -> dict[str, Any]:
    definitions = compact_schema(ACTION.json_schema())["$defs"]
    definitions.pop("ToolAction", None)
    if activity_ids is not None:
        if activity_ids:
            definitions["ActivityPart"]["properties"]["activity_id"]["enum"] = (
                activity_ids
            )
        else:
            definitions["FinalAction"]["properties"]["parts"]["items"] = {
                "$ref": "#/$defs/TextPart"
            }
            definitions.pop("ActivityPart")
    variants: list[dict[str, Any]] = [{"$ref": "#/$defs/FinalAction"}]
    for tool in tools:
        prefix = tool.name + "__"
        arguments = compact_schema(tool.inputSchema, prefix)
        for name, definition in arguments.pop("$defs", {}).items():
            definitions[prefix + name] = definition
        variants.append(
            {
                "type": "object",
                "properties": {
                    "type": {"const": "tool", "type": "string"},
                    "name": {"const": tool.name, "type": "string"},
                    "arguments": arguments,
                },
                "required": ["type", "name", "arguments"],
                "additionalProperties": False,
            }
        )
    return {"anyOf": variants, "$defs": definitions}
