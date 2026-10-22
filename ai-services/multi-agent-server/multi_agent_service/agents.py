"""Planner, Worker and Reviewer agents: three roles over the AI-Mode gateway.

Each agent is one bounded AI-Mode call with its own versioned system prompt
and response schema. On a revision the Planner is called again with what went
wrong in the previous attempt, so a plan with wrong tool arguments is fixed
where it was made. The Planner sees AI-Mode's discovered MCP catalogue
(descriptions and argument schemas) but cannot run tools; the Reviewer never
sees tools; the Worker runs AI-Mode's model-directed MCP tool loop, so the
evidence it gathers is the real tool trace rather than the model's account of
it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from .ai_mode_client import AiModeClient, AiModeError, Generation
from .checks import tool_ids
from .errors import AgentError
from .models import (
    AgentName,
    AgentReview,
    Check,
    Plan,
    RunRequest,
    Step,
    ToolTrace,
)
from .store import utc_now

if TYPE_CHECKING:
    from .config import Settings

PROMPT_PACKAGE = "multi_agent_service"
RESERVED_WORKER_KEYS = frozenset(
    {
        "task",
        "plan",
        "allowed_tools",
        "trip_id",
        "first_tool",
        "failed_checks",
        "reviewer_feedback",
        "feature_instructions",
    },
)


def _string_list(max_items: int, max_length: int = 300) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": max_items,
        "items": {"type": "string", "minLength": 1, "maxLength": max_length},
    }


# Hand-written rather than generated: Ollama's grammar compiler accepts plain
# objects, strings, arrays and enums, and these stay well inside AI-Mode's
# schema budget.
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "goal",
        "steps",
        "required_evidence",
        "tools_to_use",
        "success_criteria",
    ],
    "properties": {
        "goal": {"type": "string", "minLength": 1, "maxLength": 400},
        "steps": {**_string_list(8), "minItems": 1},
        "required_evidence": _string_list(8),
        "tools_to_use": _string_list(8, 64),
        "success_criteria": _string_list(6),
    },
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "summary", "issues", "risks", "recommendations"],
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "revise", "reject"]},
        "summary": {"type": "string", "minLength": 1, "maxLength": 500},
        "issues": _string_list(8),
        "risks": _string_list(8),
        "recommendations": _string_list(8),
    },
}


def load_prompt(name: str) -> str:
    return (
        resources.files(PROMPT_PACKAGE)
        .joinpath("prompts", name)
        .read_text(encoding="utf-8")
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _with_feature_instructions(system: str, instructions: str) -> str:
    if not instructions:
        return system
    return (
        f"{system}\n\n--- Feature instructions ---\n"
        "Apply these domain requirements within your assigned role and output schema.\n"
        f"{instructions}"
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - 1, 0)] + "…"


def _budget_exceeded(subject: str) -> AgentError:
    message = f"The {subject} does not fit in one AI-Mode request."
    return AgentError("PROMPT_BUDGET_EXCEEDED", message)


@dataclass(slots=True)
class StageResult:
    step: Step
    output: dict[str, Any] | None


def previous_attempt(
    plan: Plan,
    worker: Step,
    checks: list[Check],
    review: AgentReview,
) -> dict[str, Any]:
    """What the Planner needs to fix its plan: the plan, the Worker's tool calls
    with their outcomes, any Worker error, the failed checks and the review."""
    summary: dict[str, Any] = {
        "plan": {"goal": plan.goal, "steps": plan.steps},
        "tool_calls": [
            {
                "tool": trace.tool,
                "arguments": _truncate(_json(trace.arguments), 200),
                "status": trace.status,
                **({"error": _truncate(trace.error, 120)} if trace.error else {}),
            }
            for trace in worker.tools[:8]
        ],
        "failed_checks": [
            {"check": check.name, "detail": check.detail}
            for check in checks
            if check.blocking and not check.passed
        ],
        "reviewer_feedback": {
            "verdict": review.verdict,
            "summary": review.summary,
            "issues": review.issues,
            "recommendations": review.recommendations,
        },
    }
    if worker.error:
        summary["worker_error"] = worker.error
    return summary


class Agents:
    def __init__(self, settings: Settings, ai_mode: AiModeClient) -> None:
        self._settings = settings
        self._ai_mode = ai_mode
        self._planner_system = load_prompt("planner_v1.md")
        self._worker_preamble = load_prompt("worker_v1.md")
        self._reviewer_system = load_prompt("reviewer_v1.md")

    # ------------------------------------------------------------- planner

    async def plan(
        self,
        request: RunRequest,
        *,
        run_id: str,
        correlation_id: str,
        attempt: int = 1,
        previous: dict[str, Any] | None = None,
    ) -> tuple[Step, Plan]:
        properties = request.output_schema.get("properties")
        payload: dict[str, Any] = {
            "feature": request.feature,
            "task": request.task,
            "trip_id": request.trip_id,
            "context": request.context,
            "allowed_tools": request.allowed_tools,
            "output_fields": sorted(properties) if isinstance(properties, dict) else [],
        }
        if previous is not None:
            payload["previous_attempt"] = previous
        prompt = _json(payload)
        system = _with_feature_instructions(
            self._planner_system, request.feature_instructions
        )
        self._ensure_budget(prompt, system, "planner")
        stage = await self._call(
            "planner",
            attempt,
            prompt=prompt,
            system=system,
            schema=PLAN_SCHEMA,
            use_tools=False,
            # AI-Mode appends the MCP catalogue it discovers, as reference text,
            # so the plan can name real tools and arguments without the Planner
            # running the tool loop.
            tool_catalogue=True,
            timeout=self._settings.planner_timeout_seconds,
            run_id=run_id,
            correlation_id=correlation_id,
            feature=request.feature,
        )
        try:
            plan = Plan.model_validate(stage.output)
        except ValidationError as exc:
            stage.step.status = "failed"
            stage.step.error = {
                "code": "PLANNER_INVALID_OUTPUT",
                "message": "The Planner's reply did not match the plan schema.",
            }
            raise StageFailedError(
                stage.step,
                "PLANNER_INVALID_OUTPUT",
                "The Planner's reply did not match the plan schema.",
            ) from exc
        # The plan may only name tools the feature allowed; anything else is
        # dropped rather than passed on to the Worker as an instruction.
        if request.allowed_tools:
            plan.tools_to_use = [
                tool for tool in plan.tools_to_use if tool in request.allowed_tools
            ]
        stage.step.output = plan.model_dump(mode="json")
        return stage.step, plan

    # -------------------------------------------------------------- worker

    async def work(
        self,
        request: RunRequest,
        plan: Plan,
        *,
        attempt: int,
        feedback: AgentReview | None,
        failed_checks: list[Check] | None = None,
        run_id: str,
        correlation_id: str,
    ) -> StageResult:
        # The feature's own prompt comes first and the multi-agent rules are
        # appended: measured live, the reverse order makes the 8b model treat
        # the generic rules as its main instruction and skip the feature's
        # tools (0 of 2 tool runs, against 2 of 2 in this order).
        # The Worker already receives the feature's complete execution prompt.
        # Keep it intact: rewriting/reordering it regressed native tool selection
        # in live tests. Common policy supplements Planner/Reviewer only.
        system = f"{request.worker_system}\n\n{self._worker_preamble}"
        # The feature's context keys sit at the top level, the shape its own
        # prompt was written for; the workflow's keys cannot be overridden.
        # Absent fields are left out rather than sent as null or {}: a
        # placeholder or a null trip_id was enough for the model to skip tools.
        payload: dict[str, Any] = {
            key: value
            for key, value in request.context.items()
            if key not in RESERVED_WORKER_KEYS
        }
        payload.update(
            {
                "task": request.task,
                # Goal and steps only: the evidence list and success criteria
                # are the Reviewer's yardstick, and a model shown "prices from
                # transport_search" reads it as evidence it already has.
                "plan": {"goal": plan.goal, "steps": plan.steps},
                "allowed_tools": request.allowed_tools,
            },
        )
        if request.trip_id is not None:
            payload["trip_id"] = request.trip_id
        # A small model given a whole catalogue may answer from memory; naming
        # the first call keeps the evidence flowing from tools.
        first_tool = next(iter(plan.tools_to_use or request.allowed_tools), None)
        if first_tool is not None:
            payload["first_tool"] = first_tool
        if failed_checks:
            payload["failed_checks"] = [
                {"check": check.name, "detail": check.detail} for check in failed_checks
            ]
        if feedback is not None:
            payload["reviewer_feedback"] = {
                "summary": feedback.summary,
                "issues": feedback.issues,
                "recommendations": feedback.recommendations,
            }
        prompt = _json(payload)
        self._ensure_budget(prompt, system, "worker")
        return await self._call(
            "worker",
            attempt,
            prompt=prompt,
            system=system,
            schema=request.output_schema,
            use_tools=True,
            timeout=self._settings.worker_timeout_seconds,
            run_id=run_id,
            correlation_id=correlation_id,
            feature=request.feature,
            strict_json=False,
        )

    # ------------------------------------------------------------ reviewer

    async def review(
        self,
        request: RunRequest,
        plan: Plan,
        result: dict[str, Any] | None,
        tools: list[ToolTrace],
        checks: list[Check],
        *,
        attempt: int,
        run_id: str,
        correlation_id: str,
        worker_error: dict[str, str] | None = None,
    ) -> tuple[Step, AgentReview]:
        prompt = self._review_prompt(
            request, plan, result, tools, checks, worker_error=worker_error
        )
        stage = await self._call(
            "reviewer",
            attempt,
            prompt=prompt,
            system=_with_feature_instructions(
                self._reviewer_system, request.feature_instructions
            ),
            schema=REVIEW_SCHEMA,
            use_tools=False,
            timeout=self._settings.reviewer_timeout_seconds,
            run_id=run_id,
            correlation_id=correlation_id,
            feature=request.feature,
        )
        try:
            review = AgentReview.model_validate(stage.output)
        except ValidationError as exc:
            stage.step.status = "failed"
            stage.step.error = {
                "code": "REVIEWER_INVALID_OUTPUT",
                "message": "The Reviewer's reply did not match the review schema.",
            }
            raise StageFailedError(
                stage.step,
                "REVIEWER_INVALID_OUTPUT",
                "The Reviewer's reply did not match the review schema.",
            ) from exc
        stage.step.output = review.model_dump(mode="json")
        return stage.step, review

    def _review_prompt(
        self,
        request: RunRequest,
        plan: Plan,
        result: dict[str, Any] | None,
        tools: list[ToolTrace],
        checks: list[Check],
        *,
        worker_error: dict[str, str] | None = None,
    ) -> str:
        """Fit the evidence into AI-Mode's prompt budget, shrinking it if needed.

        The checks and the plan always go in whole; tool data excerpts and the
        result are trimmed first, because the checks already carry the hard
        findings about them.
        """
        for excerpt, result_limit in ((800, 4000), (300, 2500), (0, 1500)):
            evidence = []
            for trace in tools[:16]:
                entry: dict[str, Any] = {
                    "tool": trace.tool,
                    "status": trace.status,
                    "arguments": _truncate(_json(trace.arguments), 200),
                }
                if request.grounding is not None:
                    entry["returned_ids"] = sorted(
                        tool_ids([trace], request.grounding),
                    )[:12]
                if trace.error:
                    entry["error"] = _truncate(trace.error, 200)
                if excerpt and isinstance(trace.result, dict):
                    data = trace.result.get("structuredContent", trace.result)
                    entry["data_excerpt"] = _truncate(_json(data), excerpt)
                evidence.append(entry)
            payload: dict[str, Any] = {
                "task": request.task,
                "plan": plan.model_dump(mode="json"),
                "result": _truncate(_json(result), result_limit)
                if result is not None
                else None,
                "tool_evidence": evidence,
                # An explicit pass/FAIL per check plus a count: given the raw
                # model with "blocking": true, the 8b Reviewer read every
                # check as failed (seen live).
                "checks_passed": f"{sum(c.passed for c in checks)} of {len(checks)}",
                "checks": [
                    {
                        "check": check.name,
                        "result": "pass" if check.passed else "FAIL",
                        "detail": check.detail,
                    }
                    for check in checks
                ],
            }
            if worker_error is not None:
                payload["worker_error"] = worker_error
            prompt = _json(payload)
            if (
                len(prompt)
                + len(
                    _with_feature_instructions(
                        self._reviewer_system, request.feature_instructions
                    )
                )
                <= self._settings.max_stage_prompt_chars
            ):
                return prompt
        raise _budget_exceeded(subject="review evidence")

    # ---------------------------------------------------------- AI-Mode

    def _ensure_budget(self, prompt: str, system: str, agent: str) -> None:
        if len(prompt) + len(system) > self._settings.max_stage_prompt_chars:
            raise _budget_exceeded(subject=f"{agent} prompt")

    async def _call(
        self,
        agent: AgentName,
        attempt: int,
        *,
        prompt: str,
        system: str,
        schema: dict[str, Any],
        use_tools: bool,
        timeout: float,
        run_id: str,
        correlation_id: str,
        feature: str,
        strict_json: bool = True,
        tool_catalogue: bool = False,
    ) -> StageResult:
        started_at = utc_now()
        clock = time.perf_counter()
        metadata = {
            "service": self._settings.service_name,
            "feature": feature,
            "agent": agent,
            "run_id": run_id,
            "attempt": str(attempt),
        }
        try:
            generation: Generation = await self._ai_mode.generate(
                prompt=prompt,
                system=system,
                schema=schema,
                correlation_id=f"{correlation_id}.{agent[0]}{attempt}",
                metadata=metadata,
                use_tools=use_tools,
                timeout=timeout,
                tool_catalogue=tool_catalogue,
            )
        except AiModeError as exc:
            step = Step(
                agent=agent,
                attempt=attempt,
                status="failed",
                started_at=started_at,
                duration_ms=round((time.perf_counter() - clock) * 1000),
                tools=[ToolTrace.model_validate(tool) for tool in exc.tools],
                error={"code": exc.code, "message": exc.message},
            )
            raise StageFailedError(step, exc.code, exc.message) from exc

        output: dict[str, Any] | None
        try:
            parsed = json.loads(generation.response)
            output = parsed if isinstance(parsed, dict) else None
        except ValueError:
            output = None
        step = Step(
            agent=agent,
            attempt=attempt,
            status="completed",
            started_at=started_at,
            duration_ms=round((time.perf_counter() - clock) * 1000),
            ai_run_id=generation.ai_run_id,
            model=generation.model,
            output=output,
            tools=[ToolTrace.model_validate(tool) for tool in generation.tools],
        )
        if output is None and strict_json:
            step.status = "failed"
            step.error = {
                "code": f"{agent.upper()}_INVALID_OUTPUT",
                "message": f"The {agent} did not return a JSON object.",
            }
            raise StageFailedError(step, step.error["code"], step.error["message"])
        return StageResult(step=step, output=output)


class StageFailedError(AgentError):
    """A stage failed after AI-Mode answered or refused; the step is kept."""

    def __init__(self, step: Step, code: str, message: str) -> None:
        super().__init__(code, message)
        self.step = step
