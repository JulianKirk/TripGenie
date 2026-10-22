"""Deterministic checks: the guarantees that do not depend on a model."""

from __future__ import annotations

import pytest
from conftest import OUTPUT_SCHEMA, TRANSPORT_A, TRANSPORT_B, WORKER_RESULT, tool_trace
from multi_agent_service.checks import (
    is_write_tool,
    run_checks,
    tool_ids,
    validate_schema,
    walk,
)
from multi_agent_service.config import Settings
from multi_agent_service.models import Grounding, RunRequest, ToolTrace

MARKERS = Settings().write_tool_markers


def _request(**overrides) -> RunRequest:
    body = {
        "feature": "student-3",
        "task": "t",
        "worker_system": "rules",
        "output_schema": OUTPUT_SCHEMA,
        "grounding": {"source": "student-3", "id_paths": ["items[].id"]},
    }
    body.update(overrides)
    return RunRequest.model_validate(body)


def _traces(*traces: dict) -> list[ToolTrace]:
    return [ToolTrace.model_validate(trace) for trace in traces]


def _by_name(checks) -> dict:
    return {check.name: check for check in checks}


def test_walk_follows_dotted_paths_and_lists() -> None:
    value = {"a": {"b": [{"c": 1}, {"c": 2}, {"d": 3}]}, "x": "y"}

    assert walk(value, "a.b[].c") == [1, 2]
    assert walk(value, "x") == ["y"]
    assert walk(value, "missing.path") == []
    assert walk(value, "x[]") == []


@pytest.mark.parametrize(
    ("name", "write"),
    [
        ("activities_create", True),
        ("activities_delete", True),
        ("accommodations_search", False),
        ("budgets_get_summary", False),
        ("transport_trip_costs", False),
        ("trips_list_itinerary_items", False),
    ],
)
def test_write_tools_are_recognised_by_name(name: str, write: bool) -> None:
    assert is_write_tool(name, MARKERS) is write


def test_tool_ids_only_trust_successful_calls_from_the_source() -> None:
    grounding = Grounding(source="student-3")
    traces = _traces(
        tool_trace(ids=(TRANSPORT_A,)),
        tool_trace(ids=("transport_failed_x",), status="error"),
        tool_trace(ids=("activity_other_x",), source="student-4"),
    )

    assert tool_ids(traces, grounding) == {TRANSPORT_A}


def test_a_grounded_answer_passes_every_check() -> None:
    checks = _by_name(
        run_checks(
            _request(),
            WORKER_RESULT,
            _traces(tool_trace()),
            MARKERS,
            ["transport_search"],
        )
    )

    assert all(check.passed for check in checks.values()), checks
    assert checks["grounding"].detail == "all 1 referenced id(s) came from tool results"


def test_each_check_catches_its_own_failure() -> None:
    result = {**WORKER_RESULT, "items": [{"id": TRANSPORT_A, "reason": "r"}]}
    traces = _traces(tool_trace(ids=(TRANSPORT_B,)), tool_trace("activities_delete"))

    checks = _by_name(
        run_checks(_request(), result, traces, MARKERS, ["transport_search"])
    )

    assert not checks["grounding"].passed
    assert TRANSPORT_A in checks["grounding"].detail
    assert not checks["tool_scope"].passed
    assert "activities_delete" in checks["tool_scope"].detail
    assert not checks["no_writes"].passed
    assert all(check.blocking for check in checks.values())


def test_no_result_and_no_evidence_fail() -> None:
    checks = _by_name(run_checks(_request(), None, [], MARKERS, ["transport_search"]))

    assert not checks["output_schema"].passed
    assert not checks["tool_evidence"].passed


def test_schema_violations_are_reported() -> None:
    checks = _by_name(
        run_checks(
            _request(),
            {"answer": ""},
            _traces(tool_trace()),
            MARKERS,
            ["transport_search"],
        )
    )

    assert not checks["output_schema"].passed
    assert "required" in checks["output_schema"].detail


def test_evidence_is_required_without_grounding() -> None:
    checks = _by_name(
        run_checks(
            _request(grounding=None),
            WORKER_RESULT,
            [],
            MARKERS,
            ["transport_search"],
        )
    )

    assert set(checks) == {
        "output_schema",
        "no_writes",
        "tool_scope",
        "tool_evidence",
    }
    assert not checks["tool_evidence"].passed


@pytest.mark.parametrize(
    ("schema", "ok"),
    [
        ({"type": "object"}, True),
        ({"type": "object", "$defs": {"a": {}}, "$ref": "#/$defs/a"}, True),
        ({"type": "object", "$ref": "https://example.com/s.json"}, False),
        ({"type": "object", "required": "answer"}, False),
    ],
)
def test_schema_validation(schema: dict, ok: bool) -> None:
    assert (validate_schema(schema) is None) is ok
