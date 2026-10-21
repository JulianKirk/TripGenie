"""Terminal interface: serve the server, or run and review workflows through it.

`run` and `review` talk to a running server over HTTP, exactly as a feature
backend does, so a terminal run is the same workflow the UI drives:

    python -m multi_agent_service serve
    python -m multi_agent_service run --feature student-3 --task "..." [--trip-id ...]
    python -m multi_agent_service review <run_id>
    python -m multi_agent_service show <run_id>
    python -m multi_agent_service list [--feature student-3]
    python -m multi_agent_service export <run_id> [--format markdown] [--output file]
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

import uvicorn

from .client import MultiAgentClient, MultiAgentClientError
from .config import Settings

# The read-only tools each feature owns on the shared MCP server, used as the
# default allow-list for terminal runs. Names only: MCP owns the definitions,
# and `--tool` overrides this list.
DEFAULT_TOOLS: dict[str, list[str]] = {
    "student-1": ["trip_get_context", "trips_list_itinerary_items"],
    "student-2": [
        "accommodations_search",
        "accommodations_get",
        "accommodations_committed_costs",
    ],
    "student-3": [
        "transport_search",
        "transport_get",
        "transport_compare",
        "transport_trip_costs",
    ],
    "student-4": [
        "activities_search",
        "activities_get",
        "activities_list_categories",
        "activities_committed_costs",
    ],
    "student-5": ["budgets_list", "budgets_get_summary", "expenses_list"],
}

TERMINAL_WORKER_RULES = """\
You are TripGenie's assistant for one feature's data, answering a question
asked from the terminal. Use the native MCP functions to obtain every fact.
Actually invoke them; never describe a proposed call in prose and never
answer from memory.

After the tools have returned, put your answer in `answer`, quoting exact
figures from the tool results. List each relevant record in `items` with its
`id` copied exactly from a successful tool result and a one-line `reason`. If
no tool returned anything relevant, say so in `answer` and leave `items`
empty.
"""

TERMINAL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "items"],
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": 1200},
        "items": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "reason"],
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 80},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 240},
                },
            },
        },
    },
}

DECISIONS = {"1": "approve", "2": "correct", "3": "partial", "4": "reject"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TripGenie shared Multi-Agent Server")
    parser.add_argument(
        "--url",
        default=os.getenv("MULTI_AGENT_URL", "http://127.0.0.1:8013"),
        help="Server URL for run/review/show/list/export",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Run the local Multi-Agent Server")

    run = commands.add_parser(
        "run", help="Start a Planner → Worker → Reviewer workflow"
    )
    run.add_argument("--feature", required=True, choices=sorted(DEFAULT_TOOLS))
    run.add_argument("--task", required=True)
    run.add_argument("--trip-id")
    run.add_argument(
        "--tool", action="append", dest="tools", help="Allowed tool (repeatable)"
    )
    run.add_argument("--decision", choices=sorted(set(DECISIONS.values())))
    run.add_argument("--reviewer", default=None)
    run.add_argument("--notes")
    run.add_argument("--no-review", action="store_true", help="Stop at awaiting_human")

    review = commands.add_parser("review", help="Record the human decision on a run")
    review.add_argument("run_id")
    review.add_argument("--decision", choices=sorted(set(DECISIONS.values())))
    review.add_argument("--reviewer", default=None)
    review.add_argument("--notes")
    review.add_argument("--accepted", help="Comma-separated action indexes (partial)")
    review.add_argument(
        "--corrected-file", type=Path, help="Corrected result JSON (correct)"
    )

    show = commands.add_parser("show", help="Print a run")
    show.add_argument("run_id")

    listing = commands.add_parser("list", help="List recent runs")
    listing.add_argument("--feature")
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=20)

    export = commands.add_parser("export", help="Write a run's history and audit log")
    export.add_argument("run_id")
    export.add_argument("--format", choices=["json", "markdown"], default="markdown")
    export.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    # A Windows console or pipe may use a legacy code page without "→" or
    # model-written characters; substitute them instead of crashing mid-run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    arguments = _parser().parse_args(argv)
    if arguments.command == "serve":
        settings = Settings.from_env()
        uvicorn.run(
            "multi_agent_service.app:app", host=settings.host, port=settings.port
        )
        return 0

    with MultiAgentClient(arguments.url) as client:
        try:
            return COMMANDS[arguments.command](client, arguments)
        except MultiAgentClientError as exc:
            print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
            return 1


# ---------------------------------------------------------------- commands


def _run(client: MultiAgentClient, arguments: argparse.Namespace) -> int:
    feature = arguments.feature
    request = {
        "feature": feature,
        "task": arguments.task,
        "trip_id": arguments.trip_id,
        "worker_system": TERMINAL_WORKER_RULES,
        "output_schema": TERMINAL_OUTPUT_SCHEMA,
        "allowed_tools": arguments.tools or DEFAULT_TOOLS[feature],
        "grounding": {"source": feature, "id_paths": ["items[].id"]},
        "metadata": {"service": "multi-agent-cli", "feature": "terminal-run"},
    }
    run = client.start_run(
        {key: value for key, value in request.items() if value is not None}
    )
    print(f"run {run['run_id']} started for {feature}")
    print(f"correlation id {run['correlation_id']}")
    printer = _StepPrinter()
    run = client.wait(run["run_id"], on_update=printer)
    if run["status"] != "awaiting_human" or arguments.no_review:
        print(f"status: {run['status']}")
        return 0 if run["status"] != "failed" else 1
    return _decide(client, run, arguments)


def _review(client: MultiAgentClient, arguments: argparse.Namespace) -> int:
    run = client.get_run(arguments.run_id)
    _StepPrinter()(run)
    return _decide(client, run, arguments)


def _show(client: MultiAgentClient, arguments: argparse.Namespace) -> int:
    print(json.dumps(client.get_run(arguments.run_id), indent=2))
    return 0


def _list(client: MultiAgentClient, arguments: argparse.Namespace) -> int:
    runs = client.list_runs(
        feature=arguments.feature, status=arguments.status, limit=arguments.limit
    )
    for run in runs:
        print(
            f"{run['run_id']}  {run['feature']:<10} {run['status']:<15} "
            f"verdict={run.get('verdict') or '-':<8} "
            f"decision={run.get('decision') or '-':<8} {run['task'][:60]}",
        )
    return 0


def _export(client: MultiAgentClient, arguments: argparse.Namespace) -> int:
    markdown = arguments.format == "markdown"
    document = client.export(arguments.run_id, markdown=markdown)
    text = document if markdown else json.dumps(document, indent=2)
    if arguments.output:
        arguments.output.write_text(text, encoding="utf-8")
        print(f"wrote {arguments.output}")
    else:
        print(text)
    return 0


COMMANDS = {
    "run": _run,
    "review": _review,
    "show": _show,
    "list": _list,
    "export": _export,
}


# ----------------------------------------------------------------- helpers


class _StepPrinter:
    """Print each completed stage once, as the run progresses."""

    def __init__(self) -> None:
        self._printed = 0
        self._status = None

    def __call__(self, run: dict[str, Any]) -> None:
        for step in run.get("steps", [])[self._printed :]:
            _print_step(step, run)
        self._printed = len(run.get("steps", []))
        if run.get("status") != self._status:
            self._status = run.get("status")
            print(f"  status → {self._status}")
            if self._status == "failed" and run.get("error"):
                _print_error(run["error"])


def _print_error(error: dict[str, Any]) -> None:
    print(f"  error: {error.get('code')}: {error.get('message')}")


def _print_planner(step: dict[str, Any], _: dict[str, Any]) -> None:
    output = step.get("output") or {}
    print(f"  goal: {output.get('goal')}")
    for index, line in enumerate(output.get("steps", []), 1):
        print(f"  {index}. {line}")


def _print_worker(step: dict[str, Any], run: dict[str, Any]) -> None:
    for tool in step.get("tools", []):
        arguments = json.dumps(tool.get("arguments", {}))
        print(f"  tool {tool['tool']} {tool['status']} {arguments}")
    if step.get("output"):
        print("  result: " + json.dumps(step["output"])[:400])
    for check in run.get("checks", []):
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  check {mark} {check['name']}: {check['detail']}")


def _print_reviewer(step: dict[str, Any], _: dict[str, Any]) -> None:
    output = step.get("output") or {}
    print(f"  verdict: {output.get('verdict')} — {output.get('summary')}")
    for label in ("issues", "risks", "recommendations"):
        for item in output.get(label, []):
            print(f"  {label[:-1]}: {item}")


STEP_PRINTERS = {
    "planner": _print_planner,
    "worker": _print_worker,
    "reviewer": _print_reviewer,
}


def _print_step(step: dict[str, Any], run: dict[str, Any]) -> None:
    agent, attempt = step["agent"], step["attempt"]
    duration = step["duration_ms"]
    print(f"\n[{agent.upper()} · attempt {attempt}] {step['status']} in {duration} ms")
    STEP_PRINTERS[agent](step, run)
    if step.get("error"):
        _print_error(step["error"])


def _ask(prompt: str) -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        return input(prompt).strip()
    except EOFError:  # A pseudo-terminal with nothing to read, e.g. Git Bash.
        return None


def _choose_decision(arguments: argparse.Namespace) -> str | None:
    if arguments.decision is not None:
        return arguments.decision
    if not sys.stdin.isatty():
        return None
    print("  1 - Approve\n  2 - Correct\n  3 - Partially accept\n  4 - Reject")
    decision = None
    while decision is None:
        decision = DECISIONS.get(input("Decision: ").strip())
    return decision


def _decision_body(decision: str, arguments: argparse.Namespace) -> dict[str, Any]:
    body: dict[str, Any] = {
        "decision": decision,
        "reviewer": arguments.reviewer or getpass.getuser() or "terminal",
    }
    notes = arguments.notes if arguments.notes is not None else _ask("Notes: ")
    if notes:
        body["notes"] = notes
    if decision == "partial":
        raw = getattr(arguments, "accepted", None)
        raw = raw if raw is not None else _ask("Accepted action indexes (1,2): ")
        body["accepted_actions"] = [
            int(part) for part in (raw or "").split(",") if part.strip()
        ]
    if decision == "correct":
        path = getattr(arguments, "corrected_file", None)
        raw = path.read_text(encoding="utf-8") if path else _ask("Corrected JSON: ")
        if raw:
            body["corrected_result"] = json.loads(raw)
    return body


def _decide(
    client: MultiAgentClient, run: dict[str, Any], arguments: argparse.Namespace
) -> int:
    if run["status"] != "awaiting_human":
        print(f"run is {run['status']}; nothing to review")
        return 1
    print("\nHUMAN REVIEW")
    for check in run.get("checks", []):
        if not check["passed"]:
            print(f"  warning: check {check['name']} failed: {check['detail']}")
    for index, action in enumerate(run.get("proposed_actions", [])):
        print(f"  action {index}: {json.dumps(action)}")
    decision = _choose_decision(arguments)
    if decision is None:
        print("no --decision and no terminal to ask; run stays awaiting_human")
        return 0
    final = client.review(run["run_id"], _decision_body(decision, arguments))
    human = final["human"]
    print(f"\nHUMAN DECISION: {human['decision']} by {human['reviewer']}")
    print(f"status: {final['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
