"""Workflow history and coordination/audit export for one run.

The same document backs `GET /runs/{id}/export` and the CLI `export` command:
the evidence the Release 2 report and the agentic loop's Multi-Agent Review
mode read. It is built from the stored run and its append-only event log.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import HistoryEvent, RunRecord


def audit_document(run: RunRecord, events: list[HistoryEvent]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "run": run.model_dump(mode="json"),
        "history": [event.model_dump(mode="json") for event in events],
        "summary": {
            "stages": [
                {
                    "agent": step.agent,
                    "attempt": step.attempt,
                    "status": step.status,
                    "duration_ms": step.duration_ms,
                    "tool_calls": len(step.tools),
                }
                for step in run.steps
            ],
            "checks_failed": [check.name for check in run.checks if not check.passed],
            "verdict": run.review.verdict if run.review else None,
            "human_decision": run.human.decision if run.human else None,
            "final_status": run.status,
        },
    }


def audit_markdown(run: RunRecord, events: list[HistoryEvent]) -> str:
    sections = [
        _overview(run),
        _plan(run),
        _stages(run),
        _checks(run),
        _review(run),
        _human(run),
        _outcome(run),
        _audit_log(events),
    ]
    return "\n".join(line for section in sections for line in section) + "\n"


def _overview(run: RunRecord) -> list[str]:
    return [
        f"# Multi-agent run {run.run_id}",
        "",
        f"- Feature: `{run.feature}`",
        f"- Task: {run.task}",
        f"- Trip: `{run.trip_id}`" if run.trip_id else "- Trip: none",
        f"- Correlation ID: `{run.correlation_id}`",
        f"- Status: **{run.status}**",
        f"- Created: {run.created_at.isoformat()}",
        f"- Updated: {run.updated_at.isoformat()}",
    ]


def _plan(run: RunRecord) -> list[str]:
    lines = ["", "## Plan (Planner)", ""]
    if run.plan is None:
        return [*lines, "_No plan was produced._"]
    lines.append(f"**Goal:** {run.plan.goal}")
    lines.extend(f"{index}. {step}" for index, step in enumerate(run.plan.steps, 1))
    if run.plan.required_evidence:
        lines += ["", "Required evidence: " + "; ".join(run.plan.required_evidence)]
    return lines


def _stages(run: RunRecord) -> list[str]:
    lines = [
        "",
        "## Stages",
        "",
        "| Agent | Attempt | Status | Duration | Tool calls |",
        "| --- | --- | --- | --- | --- |",
    ]
    for step in run.steps:
        calls = ", ".join(f"`{tool.tool}` {tool.status}" for tool in step.tools)
        lines.append(
            f"| {step.agent} | {step.attempt} | {step.status} "
            f"| {step.duration_ms} ms | {calls or 'none'} |",
        )
    return lines


def _checks(run: RunRecord) -> list[str]:
    lines = ["", "## Deterministic checks", ""]
    if not run.checks:
        return [*lines, "_None ran._"]
    return lines + [
        f"- {'PASS' if check.passed else 'FAIL'} `{check.name}`: {check.detail}"
        for check in run.checks
    ]


def _review(run: RunRecord) -> list[str]:
    lines = ["", "## Review (Reviewer)", ""]
    if run.review is None:
        return [*lines, "_No review was produced._"]
    lines.append(f"**Verdict:** {run.review.verdict} · {run.review.summary}")
    for label, items in (
        ("Issues", run.review.issues),
        ("Risks", run.review.risks),
        ("Recommendations", run.review.recommendations),
    ):
        if items:
            lines.append(f"- {label}: " + "; ".join(items))
    return lines


def _human(run: RunRecord) -> list[str]:
    lines = ["", "## Human review", ""]
    if run.human is None:
        waiting = run.status == "awaiting_human"
        return [*lines, "_Awaiting a decision._" if waiting else "_None._"]
    lines.append(
        f"**Decision:** {run.human.decision} by {run.human.reviewer} "
        f"at {run.human.decided_at.isoformat()}",
    )
    if run.human.notes:
        lines.append(f"Notes: {run.human.notes}")
    lines.append(f"Approved actions: {len(run.approved_actions)}")
    return lines


def _outcome(run: RunRecord) -> list[str]:
    lines: list[str] = []
    if run.final_result is not None:
        body = json.dumps(run.final_result, indent=2)
        lines += ["", "## Final result", "", "```json", body, "```"]
    if run.error:
        code, message = run.error.get("code"), run.error.get("message")
        lines += ["", f"**Error:** `{code}` {message}"]
    return lines


def _audit_log(events: list[HistoryEvent]) -> list[str]:
    lines = [
        "",
        "## Coordination and audit log",
        "",
        "| # | Time (UTC) | Actor | Event | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for event in events:
        detail = json.dumps(event.detail, sort_keys=True)
        lines.append(
            f"| {event.sequence} | {event.at.isoformat()} | {event.actor} "
            f"| {event.event} | `{detail}` |",
        )
    return lines
