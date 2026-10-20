"""The Planner → Worker → Reviewer → Human Review workflow.

A run is a small state machine persisted after every transition:

    planning → working → reviewing → awaiting_human → completed | rejected
                  ↑          │  (verdict "revise", at most max_revisions)
                  └──────────┘
    any stage → failed (the steps it completed are kept)

Runs execute in the background so no HTTP request has to outlive a three-agent
chain; callers poll the run. Every transition is also written to the
append-only audit log, which is the workflow history the report and the
agentic loop read.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .agents import Agents, StageFailedError
from .checks import run_checks, schema_errors, validate_schema, walk
from .errors import (
    VALIDATION_ERROR_MESSAGE,
    AgentError,
    busy,
    conflict,
    not_found,
    validation_error,
)
from .models import (
    AgentReview,
    Check,
    HumanReview,
    ReviewRequest,
    RunRecord,
    RunRequest,
    StoredRun,
)
from .store import RunStore, utc_now

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)

MAX_PROPOSED_ACTIONS = 10


class WorkflowEngine:
    def __init__(self, settings: Settings, store: RunStore, agents: Agents) -> None:
        self._settings = settings
        self._store = store
        self._agents = agents
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------ starting

    async def start(self, request: RunRequest) -> RunRecord:
        self._validate(request)
        if len(self._tasks) >= self._settings.max_active_runs:
            raise busy(self._settings.max_active_runs)

        now = utc_now()
        run_id = f"magent_{uuid4().hex[:12]}"
        run = StoredRun(
            run_id=run_id,
            feature=request.feature,
            task=request.task,
            trip_id=request.trip_id,
            correlation_id=request.correlation_id or f"{request.feature}-{run_id}",
            status="planning",
            created_at=now,
            updated_at=now,
            request=request,
        )
        self._store.save(run, insert=True)
        self._event(
            run,
            "api",
            "run_created",
            {
                "feature": request.feature,
                "correlation_id": run.correlation_id,
                "allowed_tools": request.allowed_tools,
                "trip_id": request.trip_id,
            },
        )
        task = asyncio.create_task(self._execute(run))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return self.public(run)

    def _validate(self, request: RunRequest) -> None:
        details: list[dict[str, str]] = []
        limits = self._settings
        if request.feature not in limits.features:
            details.append(
                {
                    "field": "feature",
                    "issue": f"must be one of: {', '.join(limits.features)}",
                },
            )
        if len(request.task) > limits.max_task_chars:
            details.append(
                {
                    "field": "task",
                    "issue": f"must be at most {limits.max_task_chars} characters",
                },
            )
        if len(json.dumps(request.context)) > limits.max_context_chars:
            details.append(
                {
                    "field": "context",
                    "issue": (
                        f"must be at most {limits.max_context_chars} characters as JSON"
                    ),
                },
            )
        if len(request.worker_system) > limits.max_system_chars:
            details.append(
                {
                    "field": "worker_system",
                    "issue": f"must be at most {limits.max_system_chars} characters",
                },
            )
        if len(json.dumps(request.output_schema)) > limits.max_schema_chars:
            details.append(
                {
                    "field": "output_schema",
                    "issue": (
                        f"must be at most {limits.max_schema_chars} characters as JSON"
                    ),
                },
            )
        elif (problem := validate_schema(request.output_schema)) is not None:
            details.append({"field": "output_schema", "issue": problem})
        if details:
            raise validation_error(VALIDATION_ERROR_MESSAGE, details)

    # ----------------------------------------------------------- executing

    async def _execute(self, run: StoredRun) -> None:
        try:
            await asyncio.wait_for(
                self._pipeline(run),
                timeout=self._settings.run_timeout_seconds,
            )
        except TimeoutError:
            self._fail(run, "RUN_TIMEOUT", "The workflow did not finish in time.")
        except StageFailedError as exc:
            run.steps.append(exc.step)
            self._fail(run, exc.code, exc.message)
        except AgentError as exc:
            self._fail(run, exc.code, exc.message)
        except Exception:
            logger.exception("multi_agent run_id=%s crashed", run.run_id)
            self._fail(run, "INTERNAL_ERROR", "The workflow stopped unexpectedly.")

    async def _pipeline(self, run: StoredRun) -> None:
        request = run.request
        self._event(run, "planner", "stage_started", {"agent": "planner"})
        step, plan = await self._agents.plan(
            request,
            run_id=run.run_id,
            correlation_id=run.correlation_id,
        )
        run.steps.append(step)
        run.plan = plan
        self._transition(run, "working")
        self._event(
            run,
            "planner",
            "stage_completed",
            {
                "agent": "planner",
                "duration_ms": step.duration_ms,
                "steps": len(plan.steps),
            },
        )

        attempt = 1
        feedback: AgentReview | None = None
        failed: list[Check] = []
        while True:
            self._event(
                run, "worker", "stage_started", {"agent": "worker", "attempt": attempt}
            )
            stage = await self._agents.work(
                request,
                plan,
                attempt=attempt,
                feedback=feedback,
                failed_checks=failed,
                run_id=run.run_id,
                correlation_id=run.correlation_id,
            )
            run.steps.append(stage.step)
            run.attempts = attempt
            run.result = stage.output
            run.checks = run_checks(
                request,
                stage.output,
                stage.step.tools,
                self._settings.write_tool_markers,
            )
            self._transition(run, "reviewing")
            self._event(
                run,
                "worker",
                "stage_completed",
                {
                    "agent": "worker",
                    "attempt": attempt,
                    "duration_ms": stage.step.duration_ms,
                    "tool_calls": [f"{t.tool}:{t.status}" for t in stage.step.tools],
                },
            )
            self._event(
                run,
                "system",
                "checks_completed",
                {
                    "passed": [check.name for check in run.checks if check.passed],
                    "failed": [check.name for check in run.checks if not check.passed],
                },
            )

            self._event(
                run,
                "reviewer",
                "stage_started",
                {"agent": "reviewer", "attempt": attempt},
            )
            review_step, review = await self._agents.review(
                request,
                plan,
                stage.output,
                stage.step.tools,
                run.checks,
                attempt=attempt,
                run_id=run.run_id,
                correlation_id=run.correlation_id,
            )
            review = _apply_check_floor(review, run.checks)
            review_step.output = review.model_dump(mode="json")
            run.steps.append(review_step)
            run.review = review
            self._save(run)
            self._event(
                run,
                "reviewer",
                "review_completed",
                {
                    "attempt": attempt,
                    "verdict": review.verdict,
                    "issues": len(review.issues),
                    "risks": len(review.risks),
                    "duration_ms": review_step.duration_ms,
                },
            )

            failed = [c for c in run.checks if c.blocking and not c.passed]
            # A failed hard check is fixable by another attempt (most often:
            # the Worker answered without calling a tool), whatever verdict
            # the Reviewer reached; the human still has the final say.
            retry = review.verdict == "revise" or bool(failed)
            if retry and attempt <= self._settings.max_revisions:
                attempt += 1
                feedback = review
                self._transition(run, "working")
                self._event(run, "reviewer", "revision_requested", {"attempt": attempt})
                continue
            break

        run.proposed_actions = _actions(run.result, request.actions_path)
        self._transition(run, "awaiting_human")
        self._event(
            run,
            "system",
            "awaiting_human",
            {"verdict": review.verdict, "proposed_actions": len(run.proposed_actions)},
        )

    # -------------------------------------------------------------- human

    def review(self, run_id: str, decision: ReviewRequest) -> RunRecord:
        run = self._load(run_id)
        if run.status != "awaiting_human":
            raise conflict(
                code="RUN_NOT_AWAITING_REVIEW",
                message=(
                    f"Run '{run_id}' is {run.status}, not awaiting a human decision."
                ),
                details=[{"field": "status", "issue": run.status}],
            )

        details: list[dict[str, str]] = []
        final: dict[str, Any] | None = run.result
        approved: list[dict[str, Any]] = []
        accepted: list[int] = []

        if decision.decision == "approve":
            approved = list(run.proposed_actions)
            accepted = list(range(len(run.proposed_actions)))
        elif decision.decision == "correct":
            if decision.corrected_result is None:
                details.append(
                    {"field": "corrected_result", "issue": "required when correcting"},
                )
            else:
                problems = schema_errors(
                    decision.corrected_result,
                    run.request.output_schema,
                )
                details.extend(
                    {"field": "corrected_result", "issue": problem}
                    for problem in problems
                )
                final = decision.corrected_result
                approved = _actions(final, run.request.actions_path)
                accepted = list(range(len(approved)))
        elif decision.decision == "partial":
            indexes = decision.accepted_actions
            if not indexes:
                details.append(
                    {
                        "field": "accepted_actions",
                        "issue": "list the proposed actions accepted",
                    },
                )
            elif any(index >= len(run.proposed_actions) for index in indexes):
                details.append(
                    {
                        "field": "accepted_actions",
                        "issue": (
                            f"must index the {len(run.proposed_actions)} "
                            "proposed action(s)"
                        ),
                    },
                )
            else:
                accepted = sorted(set(indexes))
                approved = [run.proposed_actions[index] for index in accepted]
        else:
            final = None
        if details:
            raise validation_error(VALIDATION_ERROR_MESSAGE, details)

        run.human = HumanReview(
            decision=decision.decision,
            reviewer=decision.reviewer,
            notes=decision.notes,
            decided_at=utc_now(),
            accepted_actions=accepted,
        )
        run.final_result = final
        run.approved_actions = approved
        status = "rejected" if decision.decision == "reject" else "completed"
        self._transition(run, status)
        self._event(
            run,
            f"human:{decision.reviewer}",
            "human_decision",
            {
                "decision": decision.decision,
                "notes": decision.notes,
                "accepted_actions": accepted,
            },
        )
        self._event(run, "system", f"run_{status}", {"approved_actions": len(approved)})
        return self.public(run)

    # --------------------------------------------------------------- reads

    def get(self, run_id: str) -> RunRecord:
        return self.public(self._load(run_id))

    def request_of(self, run_id: str) -> RunRequest:
        return self._load(run_id).request

    async def wait(self, run_id: str) -> None:
        """Await a run still executing in this process (tests and the CLI)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    @property
    def active_runs(self) -> int:
        return len(self._tasks)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    @staticmethod
    def public(run: RunRecord) -> RunRecord:
        return RunRecord.model_validate(run.model_dump(exclude={"request"}))

    # ------------------------------------------------------------- helpers

    def _load(self, run_id: str) -> StoredRun:
        run = self._store.get(run_id)
        if run is None:
            raise not_found(run_id)
        return run

    def _transition(self, run: StoredRun, status: str) -> None:
        run.status = status  # type: ignore[assignment]
        self._save(run)
        logger.info(
            "multi_agent run_id=%s feature=%s status=%s",
            run.run_id,
            run.feature,
            status,
        )

    def _save(self, run: StoredRun) -> None:
        run.updated_at = utc_now()
        self._store.save(run)

    def _fail(self, run: StoredRun, code: str, message: str) -> None:
        run.error = {"code": code, "message": message}
        self._transition(run, "failed")
        self._event(run, "system", "run_failed", {"code": code, "message": message})

    def _event(
        self,
        run: RunRecord,
        actor: str,
        event: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._store.add_event(run.run_id, actor, event, detail)


def _apply_check_floor(review: AgentReview, checks: list[Check]) -> AgentReview:
    """A failed blocking check means the answer cannot be approved as it is."""
    failed = [check for check in checks if check.blocking and not check.passed]
    if not failed or review.verdict != "approve":
        return review
    issues = [f"Check '{check.name}' failed: {check.detail}" for check in failed]
    return review.model_copy(
        update={
            "verdict": "revise",
            "issues": (issues + review.issues)[:8],
            "summary": (
                "Downgraded from approve: "
                + ", ".join(check.name for check in failed)
                + " failed. "
                + review.summary
            )[:500],
        },
    )


def _actions(result: dict[str, Any] | None, path: str | None) -> list[dict[str, Any]]:
    if result is None or path is None:
        return []
    found = walk(result, path)
    items = found[0] if len(found) == 1 and isinstance(found[0], list) else found
    return [item for item in items if isinstance(item, dict)][:MAX_PROPOSED_ACTIONS]
