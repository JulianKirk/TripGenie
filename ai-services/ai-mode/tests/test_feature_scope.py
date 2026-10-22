"""Feature selection uses MCP metadata for reference and executable catalogues."""

import copy
import json

import pytest
from test_agent import MCP, message, run
from test_plain_generation import run_with_catalogue


def scoped_mcp():
    mcp = MCP()
    for tool in mcp.tools:
        owner = "student-5" if tool["name"].startswith("budgets") else "student-4"
        tool["_meta"] = {"tripgenie": {"owner": owner, "features": [owner]}}
    shared = copy.deepcopy(mcp.tools[0])
    shared["name"] = "trip_get_context"
    shared["_meta"] = {
        "tripgenie": {"owner": "student-1", "features": ["student-3", "student-4"]}
    }
    mcp.tools.append(shared)
    return mcp


def test_native_and_reference_catalogues_use_identical_feature_definitions():
    mcp = scoped_mcp()
    native, calls, _ = run([message("Answer")], mcp, {"feature": "student-4"})
    plain, references, _ = run_with_catalogue(
        [message("Plan")], {"feature": "student-4"}, mcp
    )
    assert native.status_code == plain.status_code == 200
    selected = {"activities_search", "activities_delete", "trip_get_context"}
    definitions = calls[0]["tools"]
    assert {d["function"]["name"] for d in definitions} == selected
    assert (
        json.loads(references[0]["messages"][0]["content"].split("\n")[-1])
        == definitions
    )
    assert references[0]["tools"] == []
    assert set(native.json()["data"]["available_tools"]) == selected
    assert set(plain.json()["data"]["available_tools"]) == selected
    assert mcp.calls == []


def test_foreign_write_name_is_rejected_before_mcp_execution():
    response, calls, mcp = run(
        [message(name="activities_delete", arguments={"value": "do not execute"})],
        scoped_mcp(),
        {"feature": "student-5"},
    )
    assert response.status_code == 502
    assert mcp.calls == []
    assert response.json()["tools"][0]["status"] == "rejected"
    assert {t["function"]["name"] for t in calls[0]["tools"]} == {"budgets_get_summary"}


@pytest.mark.parametrize("feature", ["student-9", "activity-assistant", "", [], True])
def test_invalid_feature_is_rejected_before_model_or_mcp_calls(feature):
    response, calls, mcp = run([], scoped_mcp(), {"feature": feature})
    assert response.status_code == 422
    assert calls == mcp.calls == []


@pytest.mark.parametrize(
    "metadata", [None, {}, {"tripgenie": []}, {"tripgenie": {"features": "student-4"}}]
)
def test_empty_or_malformed_feature_catalogue_never_falls_back(metadata):
    mcp = MCP()
    for tool in mcp.tools:
        if metadata is not None:
            tool["_meta"] = metadata
    response, calls, _ = run([], mcp, {"feature": "student-4"})
    assert response.status_code == 502
    assert calls == []
    assert mcp.calls == []


def test_omitting_feature_preserves_the_full_catalogue():
    response, calls, _ = run([message("Answer")], scoped_mcp())
    assert response.status_code == 200
    assert len(calls[0]["tools"]) == 4
    assert len(response.json()["data"]["available_tools"]) == 4


def test_feature_does_not_enable_tools_on_plain_generation():
    mcp = scoped_mcp()

    def unexpected_request(_):
        pytest.fail("Plain generation without catalogue must not contact MCP")

    mcp.handle = unexpected_request
    response, calls, mcp = run_with_catalogue(
        [message("Answer")], {"feature": "student-4", "tool_catalogue": False}, mcp
    )
    assert response.status_code == 200
    assert calls[0]["tools"] == []
    assert response.json()["data"]["available_tools"] == []
    assert mcp.calls == []


def test_scope_is_taken_from_the_explicit_field_not_metadata():
    response, calls, _ = run(
        [message("Answer")],
        scoped_mcp(),
        {"feature": "student-5", "metadata": {"feature": "student-4"}},
    )
    assert response.status_code == 200
    assert [t["function"]["name"] for t in calls[0]["tools"]] == ["budgets_get_summary"]


def test_foreign_definitions_do_not_consume_feature_context_budget():
    mcp = scoped_mcp()
    mcp.tools[1]["description"] = "Foreign feature definition " * 1000
    response, calls, _ = run(
        [message("Answer")], mcp, {"feature": "student-4"}, agent_context_chars=5000
    )
    assert response.status_code == 200, response.text
    assert all(
        t["function"]["name"] != "budgets_get_summary" for t in calls[0]["tools"]
    )


def test_foreign_call_keeps_prior_successful_execution_visible():
    response, _, mcp = run(
        [
            message(name="activities_search", arguments={"value": "Sydney"}),
            message(name="budgets_get_summary", arguments={"value": "foreign"}),
        ],
        scoped_mcp(),
        {"feature": "student-4"},
    )
    assert response.status_code == 502
    assert [t["status"] for t in response.json()["tools"]] == ["success", "rejected"]
    assert [call["name"] for call in mcp.calls] == ["activities_search"]
