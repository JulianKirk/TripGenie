"""Deterministic checks on the Worker's output, run before the Reviewer.

These carry the hard guarantees, so the review never rests on a model's
opinion alone: the result matches the feature's schema, every record it names
came back from a successful tool call by that feature's MCP tools in this
run, only allowed tools were used, and nothing wrote data.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .models import Check, Grounding, RunRequest, ToolTrace


def walk(value: Any, path: str) -> list[Any]:
    """Values at a dotted path; a `[]` suffix walks every list element."""
    current: list[Any] = [value]
    for segment in path.split("."):
        is_list = segment.endswith("[]")
        key = segment[:-2] if is_list else segment
        found: list[Any] = []
        for item in current:
            if not isinstance(item, dict) or key not in item:
                continue
            child = item[key]
            if is_list:
                if isinstance(child, list):
                    found.extend(child)
            else:
                found.append(child)
        current = found
    return current


def _collect_ids(value: Any, keys: set[str], into: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in keys
                and isinstance(item, (str, int))
                and not isinstance(item, bool)
            ):
                into.add(str(item))
            _collect_ids(item, keys, into)
    elif isinstance(value, list):
        for item in value:
            _collect_ids(item, keys, into)


def tool_ids(tools: list[ToolTrace], grounding: Grounding) -> set[str]:
    """Record ids returned by successful calls to the grounding source's tools."""
    ids: set[str] = set()
    for trace in tools:
        if trace.status != "success" or not isinstance(trace.result, dict):
            continue
        envelope = trace.result.get("structuredContent")
        if (
            not isinstance(envelope, dict)
            or envelope.get("ok") is not True
            or envelope.get("source") != grounding.source
        ):
            continue
        _collect_ids(envelope.get("data"), set(grounding.id_keys), ids)
    return ids


def is_write_tool(name: str, markers: tuple[str, ...]) -> bool:
    return any(part in markers for part in name.lower().split("_"))


def validate_schema(schema: dict[str, Any]) -> str | None:
    """None when the schema is valid JSON Schema with local references only."""

    def remote_ref(value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(item, str) or not item.startswith("#")
                ):
                    return True
                if remote_ref(item):
                    return True
        elif isinstance(value, list):
            return any(remote_ref(item) for item in value)
        return False

    if remote_ref(schema):
        return "only local JSON schema references are supported"
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return f"invalid JSON schema: {exc.message}"
    return None


def schema_errors(result: Any, schema: dict[str, Any], limit: int = 3) -> list[str]:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(result), key=lambda error: list(error.path))
    return [
        f"{'/'.join(str(part) for part in error.path) or '(root)'}: {error.message}"[
            :200
        ]
        for error in errors[:limit]
    ]


def tool_scope_check(tools: list[ToolTrace], available_tools: list[str]) -> Check:
    outside = sorted(
        {trace.tool for trace in tools if trace.tool not in available_tools}
    )
    return Check(
        name="allowed_tools",
        passed=not outside,
        blocking=True,
        detail=(
            "tools outside the feature catalogue: " + ", ".join(outside)
            if outside
            else "every tool call was in the feature catalogue"
        ),
    )


def run_checks(
    request: RunRequest,
    result: dict[str, Any] | None,
    tools: list[ToolTrace],
    markers: tuple[str, ...],
    available_tools: list[str],
) -> list[Check]:
    checks: list[Check] = []

    if result is None:
        checks.append(
            Check(
                name="output_schema",
                passed=False,
                blocking=True,
                detail="the Worker returned no parseable JSON result",
            ),
        )
    else:
        problems = schema_errors(result, request.output_schema)
        checks.append(
            Check(
                name="output_schema",
                passed=not problems,
                blocking=True,
                detail="; ".join(problems) or "result matches the feature's schema",
            ),
        )

    called = [trace.tool for trace in tools]
    checks.append(tool_scope_check(tools, available_tools))
    succeeded = sum(1 for trace in tools if trace.status == "success")
    checks.append(
        Check(
            name="tool_evidence",
            passed=succeeded > 0,
            blocking=True,
            detail=f"{succeeded} of {len(tools)} tool call(s) succeeded",
        ),
    )

    writes = sorted({name for name in called if is_write_tool(name, markers)})
    checks.append(
        Check(
            name="no_writes",
            passed=not writes,
            blocking=True,
            detail=(
                "write tools were called: " + ", ".join(writes)
                if writes
                else "no tool that changes data was called"
            ),
        ),
    )

    if request.grounding is not None and request.grounding.id_paths:
        known = tool_ids(tools, request.grounding)
        named: list[str] = []
        for path in request.grounding.id_paths:
            named.extend(
                str(value)
                for value in walk(result or {}, path)
                if isinstance(value, (str, int)) and not isinstance(value, bool)
            )
        ungrounded = sorted({value for value in named if value not in known})
        checks.append(
            Check(
                name="grounding",
                passed=not ungrounded,
                blocking=True,
                detail=(
                    "ids no successful "
                    f"{request.grounding.source} tool returned: "
                    + ", ".join(ungrounded[:10])
                    if ungrounded
                    else f"all {len(named)} referenced id(s) came from tool results"
                ),
            ),
        )

    return checks
