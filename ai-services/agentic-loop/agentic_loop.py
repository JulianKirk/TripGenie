"""PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT, for any TripGenie service.

The deterministic half is a JSON checks file (see `checks/`): a goal, a list of
HTTP checks, the business-process `flows` those endpoints have to add up to, and
the domain `rules` the agents must not contradict. The agent half is two Claude
calls that read the evidence and comment on it -- advisory only, they never
decide the exit code.

Four modes, picked with --mode or from a menu when run in a terminal:

    services  HTTP checks against running backends (checks/<service>.json)
    mcp       tool calls against the host MCP server (checks/mcp.json)
    rag       calibration queries against the host RAG server (checks/rag.json)
    ci        the latest student-x-ci.yml runs and their artifacts, via gh

Run it against your own service by pointing CHECKS_FILE at your own file:

    CHECKS_FILE=checks/student-2.json python agentic_loop.py --ci

or against several, the way the CI job does, with SERVICES:

    SERVICES="student-1 student-3" python agentic_loop.py --ci --mode services

ponytail: HTTP checks only, no direct database reads. Every TripGenie database
lives behind its own service, so its API is already the honest way in.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
REGISTRY = json.loads((HERE / "services.json").read_text())
MODES = ("services", "mcp", "rag", "ci", "multi-agent", "testing", "cloud")
IMPLEMENTATION_MODEL = os.getenv("IMPLEMENTATION_MODEL", "claude-sonnet-5")
REVIEW_MODEL = os.getenv("REVIEW_MODEL", "claude-opus-5")
NFR_SAMPLES = int(os.getenv("NFR_SAMPLES", "20"))
NFR_PASS_RATIO = 0.95
# NOTE is advisory: agent-scored rows such as MCP tool selection. Only FAIL
# counts towards the exit code.
OUTCOME_ICONS = {"OK": "✅", "FAIL": "❌", "SKIP": "⏭️", "NOTE": "⚠️"}
READY_ATTEMPTS = 20
READY_DELAY = 3
MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8012/mcp")
MCP_BUDGET_MS = 3000
# Same names and defaults as ai-services/mcp-server/tripgenie_mcp/config.py, so
# the direct backend reads hit the same backends the tools do.
MCP_BACKENDS = {
    "MCP_STUDENT_1_URL": "http://127.0.0.1:18001",
    "MCP_STUDENT_2_URL": "http://127.0.0.1:9000",
    "MCP_STUDENT_3_URL": "http://127.0.0.1:18003",
    "MCP_STUDENT_4_URL": "http://127.0.0.1:18008",
    "MCP_STUDENT_5_URL": "http://127.0.0.1:18005",
}
RAG_URL = os.getenv("RAG_URL", "http://127.0.0.1:8011")
RAG_INSUFFICIENT_BUDGET_MS = 3000
RAG_ANSWER_BUDGET_MS = 30000
ROOT = HERE.parents[1]
MULTI_AGENT_URL = os.getenv("MULTI_AGENT_URL", "http://127.0.0.1:8013")
MULTI_AGENT_AGENTS = ("planner", "worker", "reviewer")
# The last audit event of a finished run, by its final status.
MULTI_AGENT_TERMINAL_EVENT = {
    "completed": "run_completed",
    "rejected": "run_rejected",
    "failed": "run_failed",
}
# reports/ is git-ignored scratch. These review/validation logs are Release 2
# evidence, so they are written to a committed folder as well.
REVIEW_LOGS = ROOT / "docs" / "reports" / "release-2" / "agentic-loop"
COMMITTED_LOG_MODES = ("multi-agent", "testing", "cloud")
RELEASE_REPORTS = ROOT / "docs" / "reports" / "release-2"
PRE_COMMIT_TOOLS = ("ruff", "detect-secrets", "pip-audit")


def load_plan(name):
    return json.loads((HERE / name).read_text())


def load_prompt(mode, name, **fields):
    """Each mode has its own prompts, like the labs: what counts as evidence,
    and what a useful finding looks like, differ between an HTTP service, an
    MCP tool server, a RAG pipeline and a CI run."""
    text = (HERE / "prompts" / mode / name).read_text(encoding="utf-8").strip()
    for key, value in fields.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def scope(plan):
    """What the agents are allowed to talk about: this service, nothing else."""
    lines = [plan["goal"], "", "Under test:"]
    # The labels, not the paths: a path still holds its ${VAR} and the literal
    # probe values (a bogus uuid, a malformed id), which read as real endpoints.
    lines += [f"- {c['label']}" for c in plan.get("checks", []) + plan.get("steps", [])]
    for flow in plan.get("flows", []):
        lines += ["", f"Business process under test -- {flow['name']}:"]
        lines += [f"- {step['label']}" for step in flow["steps"]]
        lines += [
            f"- invariant: {rule['label']}" for rule in flow.get("invariants", [])
        ]
    if plan.get("rules"):
        lines += ["", "Domain rules (these are correct; never contradict them):"]
        lines += [f"- {rule}" for rule in plan["rules"]]
    return "\n".join(lines)


def measure(check):
    """One request. Returns the response and how long it took, in ms."""
    # ${VARS} in the path so one checks file can span several services and the
    # CI job can point them wherever it published them.
    url = os.path.expandvars(check["path"])
    started = time.perf_counter()
    response = requests.request(
        check.get("method", "GET"),
        url,
        data=check.get("form"),
        json=check.get("json"),
        headers=check.get("headers"),
        timeout=check.get("timeout", 10),
    )
    return response, (time.perf_counter() - started) * 1000


def run_check(check):
    """One check. Returns its outcome line and the response it came from."""
    expected = check.get("status", 200)
    try:
        response, elapsed = measure(check)
    except Exception as exc:  # noqa: BLE001 - a broken check is evidence, not a crash
        return f"FAIL: {exc}", None

    missing = [t for t in check.get("contains", []) if t not in response.text]
    alternatives = check.get("contains_any", [])
    expected_statuses = expected if isinstance(expected, list) else [expected]
    if response.status_code not in expected_statuses:
        outcome = f"FAIL: HTTP {response.status_code}, expected {expected_statuses}"
    elif not response.text.strip():
        outcome = "FAIL: empty body"
    elif missing:
        outcome = f"FAIL: body missing {missing}"
    elif alternatives and not any(t in response.text for t in alternatives):
        outcome = f"FAIL: body missing any of {alternatives}"
    else:
        outcome = f"OK: HTTP {response.status_code} in {elapsed:.0f}ms"
    return outcome, response


def observe(plan):
    results = []
    for check in plan.get("checks", []):
        outcome, _ = run_check(check)
        results.append((check["label"], outcome))

        if check.get("nfr_ms") and outcome.startswith("OK"):
            results.append(observe_nfr(check))
    return results + observe_flows(plan)


def read_path(payload, path):
    """`data.0.budget_id` out of a decoded body. A digit indexes a list."""
    for part in path.split("."):
        payload = payload[int(part)] if part.isdigit() else payload[part]
    return payload


def resolve(step, values):
    """Substitute what earlier steps saved into this one, wherever it appears --
    path, query string, JSON body, expected substrings."""
    text = json.dumps(step)
    for name, value in values.items():
        text = text.replace("${" + name + "}", str(value))
    return json.loads(text)


def check_invariant(rule, values):
    """A business rule the saved values must hold to, e.g. remaining = total - spent."""
    try:
        # ponytail: eval, over an expression from this repo's own checks file and
        # values from the service under test. No caller input reaches it.
        held = eval(  # noqa: S307 - trusted repository checks/*.json expressions only
            rule["expr"],
            {"__builtins__": {"float": float, "abs": abs, "len": len}},
            values,
        )
    except Exception as exc:  # noqa: BLE001 - a broken rule is evidence, not a crash
        return f"FAIL: {exc}"
    return "OK: holds" if held else f"FAIL: {rule['expr']} is false for {values}"


def observe_flows(plan):
    """The business processes: several requests in order, each able to feed the
    next, then the invariants the collected values have to satisfy."""
    results = []
    for flow in plan.get("flows", []):
        values = {}
        stopped = None
        for step in flow["steps"]:
            label = f"{flow['name']} / {step['label']}"
            if stopped:
                results.append((label, f"SKIP: after {stopped}"))
                continue
            outcome, response = run_check(resolve(step, values))
            if outcome.startswith("OK") and step.get("save"):
                try:
                    body = response.json()
                    values.update(
                        {n: read_path(body, p) for n, p in step["save"].items()}
                    )
                except Exception as exc:  # noqa: BLE001 - nothing to save is a failure
                    outcome = f"FAIL: cannot save {list(step['save'])} ({exc})"
            if not outcome.startswith("OK"):
                stopped = step["label"]
            results.append((label, outcome))
        for rule in flow.get("invariants", []):
            label = f"{flow['name']} / {rule['label']}"
            outcome = (
                f"SKIP: after {stopped}" if stopped else check_invariant(rule, values)
            )
            results.append((label, outcome))
    return results


def observe_nfr(check):
    budget = check["nfr_ms"]
    timings = [measure(check)[1] for _ in range(NFR_SAMPLES)]
    within = sum(t <= budget for t in timings)
    label = f"NFR {check['label']} <= {budget}ms"
    if within / NFR_SAMPLES >= NFR_PASS_RATIO:
        return label, f"OK: {within}/{NFR_SAMPLES} within budget"
    return label, f"FAIL: only {within}/{NFR_SAMPLES} within budget"


def wait_ready(entry):
    """Poll a service's health endpoint until it reports ready, like the old
    curl step did, so one slow service fails its own section and nothing else."""
    url = os.environ["SERVICE_URL"] + entry["health"]
    for _ in range(READY_ATTEMPTS):
        try:
            if entry["ready"] in requests.get(url, timeout=5).text:
                return True
        except requests.RequestException:
            pass
        time.sleep(READY_DELAY)
    return False


def run_services():
    """One service from CHECKS_FILE, or every entry of services.json in SERVICES.

    SKIPPED carries the gate's reason for the rest, as `service=reason;...`."""
    selected = os.getenv("SERVICES")
    if selected is None:
        plan = load_plan(os.getenv("CHECKS_FILE", "checks/shared.json"))
        return plan, [(None, observe(plan))]

    selected = selected.split()
    reasons = dict(
        item.split("=", 1)
        for item in os.getenv("SKIPPED", "").split(";")
        if "=" in item
    )
    plans, sections = [], []
    for entry in REGISTRY:
        name = entry["service"]
        if name not in selected:
            reason = reasons.get(name, "not selected")
            sections.append((name, [("loop", f"SKIP: {reason}")]))
            continue
        plan = load_plan(f"checks/{name}.json")
        plans.append(plan)
        os.environ["SERVICE_URL"] = f"http://127.0.0.1:{entry['port']}"
        backend = entry.get("backend_port", entry["port"])
        os.environ["BACKEND_URL"] = f"http://127.0.0.1:{backend}"
        if wait_ready(entry):
            sections.append((name, observe(plan)))
        else:
            outcome = f"FAIL: not ready after {READY_ATTEMPTS} attempts"
            sections.append((name, [(f"GET {entry['health']}", outcome)]))
    unknown = sorted(set(selected) - {e["service"] for e in REGISTRY})
    sections += [(name, [("loop", "FAIL: not in services.json")]) for name in unknown]

    combined = {
        "goal": "Validate the selected services: " + ", ".join(selected),
        "checks": [c for p in plans for c in p.get("checks", [])],
        "flows": [f for p in plans for f in p.get("flows", [])],
        "rules": [r for p in plans for r in p.get("rules", [])],
    }
    return combined, sections


def mcp_call(method, params=None):
    """One JSON-RPC request. The server is stateless with JSON responses, so a
    plain POST is the whole protocol -- no session, no SDK."""
    started = time.perf_counter()
    response = requests.post(
        MCP_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={"Accept": "application/json, text/event-stream"},
        timeout=10,
    )
    elapsed = (time.perf_counter() - started) * 1000
    return response.json(), elapsed


def call_tool(step):
    body, elapsed = mcp_call(
        "tools/call", {"name": step["tool"], "arguments": step.get("arguments", {})}
    )
    result = body.get("result") or {}
    # The envelope, or whatever came back instead, so a failure shows it.
    return body, result.get("structuredContent") or result or body, elapsed


def short(value):
    return json.dumps(value)[:200]


def mcp_step(step, values):
    """One tool step: a probe that must be refused, or a valid read."""
    label = step["label"]
    if "${" in json.dumps(step.get("arguments", {})):
        return [(label, "SKIP: an earlier step did not save its input")]
    try:
        body, envelope, elapsed = call_tool(step)
    except Exception as exc:  # noqa: BLE001 - an unreachable server is evidence
        return [(label, f"FAIL: {exc}")]

    if step.get("rejected"):
        refused = "error" in body or (body.get("result") or {}).get("isError")
        return [(label, "OK: rejected" if refused else f"FAIL: accepted {short(body)}")]
    if step.get("error"):
        code = (envelope.get("error") or {}).get("code")
        if code == step["error"]:
            return [(label, f"OK: {code}")]
        return [(label, f"FAIL: expected {step['error']}, got {short(body)}")]
    return mcp_read(step, envelope, elapsed, values)


def mcp_read(step, envelope, elapsed, values):
    """A valid read: the envelope, then latency, consistency and the direct
    backend comparison."""
    label = step["label"]
    if envelope.get("ok") is not True or "data" not in envelope:
        return [(label, f"FAIL: {short(envelope)}")]
    if envelope.get("source") != step["source"]:
        return [
            (label, f"FAIL: source {envelope.get('source')}, expected {step['source']}")
        ]
    rows = [(label, f"OK: {step['source']} in {elapsed:.0f}ms")]
    try:
        values.update(
            {n: read_path(envelope, p) for n, p in step.get("save", {}).items()}
        )
    except Exception as exc:  # noqa: BLE001 - nothing to save is a failure
        rows[0] = (label, f"FAIL: cannot save {list(step['save'])} ({exc})")

    within = elapsed <= MCP_BUDGET_MS
    rows.append(
        (
            f"{label} latency <= {MCP_BUDGET_MS}ms",
            f"{'OK' if within else 'FAIL'}: {elapsed:.0f}ms",
        )
    )

    try:
        _, again, _ = call_tool(step)
        same = again.get("data") == envelope["data"]
        outcome = "OK: same data" if same else "FAIL: data changed between calls"
    except Exception as exc:  # noqa: BLE001
        outcome = f"FAIL: {exc}"
    rows.append((f"{label} repeated", outcome))

    if step.get("compare"):
        rows.append((f"{label} matches backend", compare_backend(step, envelope)))
    return rows


def compare_backend(step, envelope):
    """The tool's IDs and amounts against the same backend read directly."""
    compare = step["compare"]
    try:
        direct = requests.get(os.path.expandvars(compare["path"]), timeout=10).json()
        wrong = [
            f"{tool_path}={read_path(envelope, tool_path)!r} "
            f"but {direct_path}={read_path(direct, direct_path)!r}"
            for tool_path, direct_path in compare["fields"].items()
            if str(read_path(envelope, tool_path))
            != str(read_path(direct, direct_path))
        ]
    except Exception as exc:  # noqa: BLE001
        return f"FAIL: {exc}"
    return (
        f"FAIL: {'; '.join(wrong)}"
        if wrong
        else f"OK: {len(compare['fields'])} field(s) match"
    )


def observe_mcp(plan):
    for name, url in MCP_BACKENDS.items():
        os.environ.setdefault(name, url)
    try:
        listed, _ = mcp_call("tools/list")
        # The descriptions the server advertises are what the tool-selection
        # agent chooses from, the same way AI-Mode's model does.
        plan["catalogue"] = {
            tool["name"]: tool.get("description", "")
            for tool in listed["result"]["tools"]
        }
        names = set(plan["catalogue"])
    except Exception as exc:  # noqa: BLE001
        return [("tools/list", f"FAIL: MCP server unreachable at {MCP_URL} ({exc})")]
    expected = set(plan["tools"])
    if names == expected:
        results = [("tools/list", f"OK: all {len(expected)} tools registered")]
    else:
        missing, extra = sorted(expected - names), sorted(names - expected)
        results = [("tools/list", f"FAIL: missing {missing}, unexpected {extra}")]

    # With SERVICES set, only those backends were started, so a read from any
    # other student would fail for a reason that is not the MCP server.
    started = os.getenv("SERVICES")
    values = {}
    for step in plan["steps"]:
        source = step.get("source")
        if started is not None and source and source not in started.split():
            results.append((step["label"], f"SKIP: {source} not started in this run"))
            continue
        results += mcp_step(resolve(step, values), values)
    return results


def run_mcp():
    plan = load_plan("checks/mcp.json")
    results = observe_mcp(plan)
    cases = plan.get("tool_selection", [])
    plan["prompt_fields"] = {
        "TOOL_CATALOGUE": "\n".join(
            f"- {name}: {text}" for name, text in plan.get("catalogue", {}).items()
        )
        or "Unavailable: tools/list failed.",
        "TOOL_REQUESTS": "\n".join(
            f"{number}. {item['request']}" for number, item in enumerate(cases, start=1)
        ),
    }
    return plan, [(None, results)]


def score_tool_selection(plan, selections):
    """The implementation agent's picks against the expected tools. Advisory:
    a wrong pick is a NOTE, never a FAIL -- the model decides it, not the server."""
    cases = plan.get("tool_selection", [])
    if not plan.get("catalogue"):
        return [(case["request"], "SKIP: no tool catalogue") for case in cases]
    selected = re.compile(r"^\s*(\d+)\.\s*Selected Tool:\s*`?(\w+)", re.MULTILINE)
    picked = dict(selected.findall(selections))
    rows = []
    for number, case in enumerate(cases, start=1):
        choice = picked.get(str(number))
        if choice is None:
            outcome = "SKIP: agent gave no selection"
        elif choice == case["expected"]:
            outcome = f"OK: picked {choice}"
        else:
            outcome = f"NOTE: picked {choice}, expected {case['expected']}"
        rows.append((case["request"], outcome))
    return rows


def rag_query(case):
    started = time.perf_counter()
    response = requests.post(
        f"{RAG_URL}/query",
        json={"query": case["query"], "feature": case["feature"]},
        timeout=RAG_ANSWER_BUDGET_MS / 1000 * 2,
    )
    elapsed = (time.perf_counter() - started) * 1000
    if response.status_code != 200:
        message = f"HTTP {response.status_code}: {response.text[:200]}"
        raise RuntimeError(message)
    # The RAG server wraps every answer in {"data": ...} (release-1-rag-contract).
    return response.json()["data"], elapsed


def grounding(case, body):
    """Is this answer what the calibration case expects?"""
    if case["expect_insufficient_context"]:
        if body.get("insufficient_context") is True:
            return "OK: insufficient context"
        category = body.get("confidence_category")
        return f"FAIL: expected insufficient context, got {category}"
    if body.get("insufficient_context") or not body.get("answer", "").strip():
        return "FAIL: no grounded answer"
    cited = {c["source_id"] for c in body.get("citations", [])}
    missing = sorted(set(case["expected_source_ids"]) - cited)
    if missing:
        return f"FAIL: citations missing {missing} (cited {sorted(cited)})"
    return f"OK: {body['confidence_category']} confidence, cites {sorted(cited)}"


def observe_rag(plan):
    try:
        ready = requests.get(f"{RAG_URL}/ready", timeout=10)
    except requests.RequestException as exc:
        return [("GET /ready", f"FAIL: RAG server unreachable at {RAG_URL} ({exc})")]
    if ready.status_code != 200:
        return [("GET /ready", f"FAIL: HTTP {ready.status_code} {ready.text[:200]}")]

    results = [("GET /ready", "OK: HTTP 200")]
    cases = plan["cases"]
    for number, case in enumerate(cases, 1):
        label = case["case_id"]
        # Each case is two model answers; say so, or a long run looks hung.
        print(f"  [{number}/{len(cases)}] {label}", flush=True)
        try:
            first, elapsed = rag_query(case)
            second, _ = rag_query(case)
        except Exception as exc:  # noqa: BLE001
            results.append((label, f"FAIL: {exc}"))
            continue
        results.append((label, grounding(case, first)))

        budget = (
            RAG_INSUFFICIENT_BUDGET_MS
            if first.get("insufficient_context")
            else RAG_ANSWER_BUDGET_MS
        )
        within = elapsed <= budget
        results.append(
            (
                f"{label} latency <= {budget}ms",
                f"{'OK' if within else 'FAIL'}: {elapsed:.0f}ms",
            )
        )

        def fingerprint(body):
            cited = sorted(c["source_id"] for c in body.get("citations", []))
            return body.get("confidence_category"), cited

        same = fingerprint(first) == fingerprint(second)
        results.append(
            (
                f"{label} repeated",
                "OK: same citations and confidence"
                if same
                else f"FAIL: {fingerprint(first)} then {fingerprint(second)}",
            )
        )
    return results


def run_rag():
    plan = load_plan("checks/rag.json")
    calibration = json.loads((HERE / plan["calibration"]).read_text())
    plan["cases"] = calibration["cases"]
    plan["checks"] = [{"label": f"{c['case_id']}: {c['query']}"} for c in plan["cases"]]
    return plan, [(None, observe_rag(plan))]


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)  # noqa: S603, S607 - local gh CLI, fixed internal callers, no shell


def observe_ci():
    """The latest run of each service's own workflow on this branch, and what
    it uploaded. Conclusions are the evidence; artifacts land in reports/ci/."""
    if not shutil.which("gh"):
        return [("gh", "SKIP: gh CLI unavailable; install it and run gh auth login")]
    branch = (
        os.getenv("CI_BRANCH")
        or subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607 - local Git CLI with literal arguments
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    )

    results = []
    for entry in REGISTRY:
        label = f"{entry['service']} ({entry['ci']})"
        listed = gh(
            "run", "list", "--workflow", entry["ci"], "--branch", branch,
            "--limit", "1", "--json", "databaseId,status,conclusion,headSha",
        )  # fmt: skip
        if listed.returncode != 0:
            results.append((label, f"FAIL: gh run list: {listed.stderr.strip()[:200]}"))
            continue
        runs = json.loads(listed.stdout or "[]")
        if not runs:
            results.append((label, f"SKIP: no run on {branch}"))
            continue
        run = runs[0]
        where = f"run {run['databaseId']} at {run['headSha'][:7]}"
        if run["status"] != "completed":
            results.append((label, f"SKIP: {where} is {run['status']}"))
            continue

        target = REPORTS / "ci" / entry["service"]
        # ponytail: our own download folder, emptied so gh does not refuse to
        # overwrite the last run's files.
        shutil.rmtree(target, ignore_errors=True)
        # A run with no artifacts exits non-zero; that is not a failed check.
        gh("run", "download", str(run["databaseId"]), "--dir", str(target))
        artifacts = sorted(p.name for p in target.iterdir()) if target.exists() else []
        detail = f"{where}; artifacts: {', '.join(artifacts) or 'none'}"
        verdict = "OK" if run["conclusion"] == "success" else "FAIL"
        results.append((label, f"{verdict}: {run['conclusion']}, {detail}"))
    return results


def run_ci():
    plan = load_plan("checks/ci.json")
    plan["checks"] = [{"label": f"{e['service']} ({e['ci']})"} for e in REGISTRY]
    return plan, [(None, observe_ci())]


def multi_agent_get(path, **params):
    """(status code, JSON body) from the Multi-Agent Server."""
    response = requests.get(
        f"{MULTI_AGENT_URL}{path}", params=params or None, timeout=15
    )
    return response.status_code, response.json()


def pick_multi_agent_run():
    """RUN_ID if set, else the newest run a human has decided, else the newest."""
    if os.getenv("RUN_ID"):
        return os.environ["RUN_ID"], None
    status, body = multi_agent_get("/runs", limit=50)
    runs = body.get("data") or []
    if status != 200 or not runs:
        return (
            None,
            "no runs on the server; start one with `python -m multi_agent_service run`",
        )
    decided = [r for r in runs if r.get("status") in ("completed", "rejected")]
    return (decided or runs)[0]["run_id"], None


def audit_checks(document):
    """Checks over one run's export document: stages, deterministic checks,
    Reviewer verdict, human decision and the order of the audit events."""
    run = document.get("run", {})
    events = sorted(document.get("history", []), key=lambda e: e.get("sequence", 0))
    stages = document.get("summary", {}).get("stages", [])
    human = run.get("human")
    status = run.get("status")
    summary = (
        f"{run.get('run_id')} ({run.get('feature')}), status {status}, "
        f"{run.get('attempts', 0)} attempt(s)"
    )
    results = [("run under review", f"OK: {summary}")]

    completed = {s.get("agent") for s in stages if s.get("status") == "completed"}
    results += [
        (
            f"{agent} stage completed",
            "OK: completed" if agent in completed else "FAIL: no completed stage",
        )
        for agent in MULTI_AGENT_AGENTS
    ]
    calls = sum(s.get("tool_calls", 0) for s in stages if s.get("agent") == "worker")
    results.append(
        (
            "worker tool calls",
            f"OK: {calls} call(s)" if calls else "NOTE: the Worker made no tool calls",
        )
    )

    checks = run.get("checks") or []
    if not checks:
        results.append(("deterministic checks", "FAIL: none recorded"))
    results += [
        (
            f"check {check.get('name')}",
            f"{'OK' if check.get('passed') else 'FAIL'}: {check.get('detail')}",
        )
        for check in checks
    ]

    review = run.get("review")
    if not review:
        results.append(("reviewer verdict", "FAIL: no review recorded"))
    elif review.get("verdict") == "approve":
        results.append(("reviewer verdict", "OK: approve"))
    else:
        results.append(
            (
                "reviewer verdict",
                f"NOTE: {review.get('verdict')}; the human decision is the gate",
            )
        )
    if run.get("attempts", 0) > 1:
        results.append(
            ("revision", f"NOTE: Worker revised ({run['attempts']} attempts)")
        )

    if not human:
        results.append(("human decision", f"FAIL: none recorded (status {status})"))
    else:
        results.append(
            (
                "human decision",
                f"OK: {human.get('decision')} by {human.get('reviewer')}",
            )
        )
        expected = "rejected" if human.get("decision") == "reject" else "completed"
        results.append(
            (
                "final status matches decision",
                "OK: " + status
                if status == expected
                else f"FAIL: {status}, expected {expected}",
            )
        )

    names = [e.get("event") for e in events]
    sequence = [e.get("sequence") for e in document.get("history", [])]
    results.append(
        (
            "audit trail starts with run_created",
            "OK: run_created"
            if names[:1] == ["run_created"]
            else f"FAIL: starts {names[:1]}",
        )
    )
    results.append(
        (
            "audit sequence increasing",
            "OK: ordered"
            if sequence == sorted(set(sequence))
            else "FAIL: out of order or repeated",
        )
    )
    if "human_decision" in names:
        in_order = "awaiting_human" in names and names.index(
            "awaiting_human"
        ) < names.index("human_decision")
        actor = next(
            e.get("actor", "") for e in events if e.get("event") == "human_decision"
        )
        results.append(
            (
                "human decision follows awaiting_human",
                "OK: in order"
                if in_order
                else "FAIL: decision without awaiting_human first",
            )
        )
        results.append(
            (
                "human decision attributed to a person",
                f"OK: {actor}"
                if actor.startswith("human:")
                else f"FAIL: actor {actor!r}",
            )
        )
    terminal = MULTI_AGENT_TERMINAL_EVENT.get(status)
    if terminal:
        results.append(
            (
                "audit trail ends with the final event",
                f"OK: {terminal}"
                if names[-1:] == [terminal]
                else f"FAIL: ends {names[-1:]}, expected {terminal}",
            )
        )
    return results


def observe_multi_agent(plan):
    results = [
        (
            f"file {relative}",
            "OK: present" if (ROOT / relative).is_file() else "FAIL: missing",
        )
        for relative in plan.get("required_files", [])
    ]
    try:
        for label, endpoint in (("GET /health", "/health"), ("GET /ready", "/ready")):
            status, _ = multi_agent_get(endpoint)
            results.append(
                (
                    label,
                    f"OK: HTTP {status}" if status == 200 else f"FAIL: HTTP {status}",
                )
            )
        run_id, problem = pick_multi_agent_run()
        if problem:
            results.append(("select run", f"FAIL: {problem}"))
            return results
        status, body = multi_agent_get(f"/runs/{run_id}/export")
    except Exception as exc:  # noqa: BLE001 - an unreachable server is evidence, not a crash
        results.append(("Multi-Agent Server", f"FAIL: {exc}"))
        return results
    if status != 200:
        results.append((f"GET /runs/{run_id}/export", f"FAIL: HTTP {status}"))
        return results
    return results + audit_checks(body.get("data", {}))


def run_multi_agent():
    plan = load_plan("checks/multi-agent.json")
    results = observe_multi_agent(plan)
    plan["checks"] = [{"label": label} for label, _ in results]
    return plan, [(None, results)]


def ci_branch():
    return (
        os.getenv("CI_BRANCH")
        or subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607 - local Git CLI with literal arguments
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    )


def latest_run(workflow, branch):
    """(run, problem): the newest run of a workflow on a branch, or why not.

    A feature branch that changed nothing a workflow watches has no runs, so
    the newest run on main stands in; the run records which branch it came from."""
    for tried in dict.fromkeys([branch, "main"]):
        listed = gh(
            "run", "list", "--workflow", workflow, "--branch", tried,
            "--limit", "1", "--json", "databaseId,status,conclusion,headSha",
        )  # fmt: skip
        if listed.returncode != 0:
            return None, f"gh run list: {listed.stderr.strip()[:200]}"
        runs = json.loads(listed.stdout or "[]")
        if runs:
            return {**runs[0], "branch": tried}, None
    return None, f"no run of {workflow} on {branch} or main"


def pre_commit_report(student):
    """One student's pre-commit security evidence: the scan's JSON result, else
    a written report that covers all three tools."""
    scan = RELEASE_REPORTS / f"{student}-pre-commit-security-scan.json"
    report = RELEASE_REPORTS / f"{student}-pre-commit-security-report.md"
    label = f"{student} pre-commit security report"
    if scan.is_file():
        try:
            data = json.loads(scan.read_text(encoding="utf-8"))
        except ValueError as exc:
            return label, f"FAIL: {scan.name} is not valid JSON ({exc})"
        tools = {c.get("tool"): c.get("status") for c in data.get("checks", [])}
        gaps = [t for t in PRE_COMMIT_TOOLS if tools.get(t) != "passed"]
        if data.get("status") == "passed" and not gaps:
            return label, f"OK: {scan.name} passed ({', '.join(PRE_COMMIT_TOOLS)})"
        return (
            label,
            "FAIL: {} status {}, not passed: {}".format(
                scan.name, data.get("status"), gaps or "n/a"
            ),
        )
    if report.is_file():
        text = report.read_text(encoding="utf-8").lower()
        missing = [t for t in PRE_COMMIT_TOOLS if t not in text]
        if missing:
            return label, f"FAIL: {report.name} does not cover {missing}"
        return label, f"OK: {report.name} covers {', '.join(PRE_COMMIT_TOOLS)}"
    return label, f"FAIL: no {report.name} or {scan.name} in docs/reports/release-2"


def pre_commit_setup():
    config = ROOT / ".pre-commit-config.yaml"
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    hooked = "id: security" in text and "scripts/security/scan.py" in text
    scan = ROOT / "scripts" / "security" / "scan.py"
    return [
        (
            "pre-commit hook runs the security scan",
            "OK: security hook -> scripts/security/scan.py"
            if hooked
            else "FAIL: .pre-commit-config.yaml has no security hook for scan.py",
        ),
        (
            "scripts/security/scan.py",
            "OK: present" if scan.is_file() else "FAIL: missing",
        ),
    ]


def junit_totals(xml_text):
    """(tests, failures, errors, skipped) from a JUnit XML document."""
    root = ET.fromstring(xml_text)  # noqa: S314 - our own downloaded CI artifact
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return tuple(
        sum(int(s.get(key, 0)) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    )


def post_commit_checks(students):
    results = []
    for student in students:
        post = RELEASE_REPORTS / f"{student}-post-commit-testing-report.md"
        results.append(
            (
                f"{student} post-commit testing report",
                f"OK: {post.name}"
                if post.is_file()
                else f"FAIL: no {post.name} in docs/reports/release-2",
            )
        )
    if not shutil.which("gh"):
        return [
            *results,
            ("gh", "SKIP: gh CLI unavailable; install it and run gh auth login"),
        ]
    branch = ci_branch()
    for entry in (e for e in REGISTRY if e["service"] in students):
        label = f"{entry['service']} post-commit endpoint tests"
        run, problem = latest_run(entry["ci"], branch)
        if problem:
            results.append((label, f"FAIL: {problem}"))
            continue
        where = f"run {run['databaseId']} at {run['headSha'][:7]} on {run['branch']}"
        if run["status"] != "completed":
            results.append((label, f"SKIP: {where} is {run['status']}"))
            continue
        target = REPORTS / "testing" / entry["service"]
        shutil.rmtree(target, ignore_errors=True)
        gh(
            "run", "download", str(run["databaseId"]),
            "--name", f"{entry['service']}-endpoint-test-evidence",
            "--dir", str(target),
        )  # fmt: skip
        found = sorted(target.rglob("*endpoint-tests.xml")) if target.exists() else []
        if not found:
            results.append(
                (
                    label,
                    "FAIL: {} ({}) has no endpoint-test evidence artifact".format(
                        where, run["conclusion"]
                    ),
                )
            )
            continue
        try:
            tests, failures, errors, skipped = junit_totals(
                found[0].read_text(encoding="utf-8")
            )
        except (ET.ParseError, ValueError) as exc:
            results.append((label, f"FAIL: {found[0].name} unreadable ({exc})"))
            continue
        detail = (
            f"{tests} test(s), {failures} failed, {errors} errors, "
            f"{skipped} skipped; {where}"
        )
        passed = run["conclusion"] == "success" and tests > 0 and not failures + errors
        results.append((label, f"{'OK' if passed else 'FAIL'}: {detail}"))
    return results


def run_testing():
    plan = load_plan("checks/testing.json")
    students = [e["service"] for e in REGISTRY if e["service"].startswith("student-")]
    pre = pre_commit_setup() + [pre_commit_report(s) for s in students]
    post = post_commit_checks(students)
    plan["checks"] = [{"label": label} for label, _ in pre + post]
    return plan, [("Pre-commit security", pre), ("Post-commit CI/CD endpoints", post)]


def table_rows(text, start, end):
    """Cells of each Markdown table row between two markers, header skipped."""
    section = text.split(start, 1)[-1].split(end, 1)[0] if start in text else ""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.strip().startswith("|")
    ]
    return [r for r in rows if r and not set(r[0]) <= {"-", " "} and r[0] != "Check"]


def cloud_report_checks(text):
    """Checks over the generated cloud-deployment-results.md."""
    results = []
    status = re.search(r"Deployment Status:\s*(\w+)", text)
    results.append(
        (
            "deployment status",
            f"OK: {status.group(1)}"
            if status and status.group(1) == "Success"
            else f"FAIL: {status.group(1) if status else 'not stated'}",
        )
    )
    urls = re.findall(r"^- (https://\S+)", text, re.MULTILINE)
    results.append(
        (
            "frontend URLs reported",
            f"OK: {len(urls)} URL(s)" if urls else "FAIL: none listed",
        )
    )
    for name, start, end in (
        ("smoke tests", "Validation Results:", "Security Configuration:"),
        ("security configuration", "Security Configuration:", "AI-Mode"),
    ):
        rows = table_rows(text, start, end)
        failed = [r[0] for r in rows if len(r) > 1 and r[1].upper() == "FAIL"]
        if not rows:
            results.append((name, "FAIL: no result rows in the report"))
        elif failed:
            results.append(
                (
                    name,
                    f"FAIL: {len(failed)} of {len(rows)} failed: {', '.join(failed)}",
                )
            )
        else:
            results.append((name, f"OK: {len(rows)} of {len(rows)} passed"))
    results.append(
        (
            "AI services not deployed",
            "OK: report states the AI services are not deployed"
            if "are not deployed" in text
            else "FAIL: report does not state the AI services are off",
        )
    )
    return results


def cloud_profile_check():
    """The cloud env profile turns every AI switch off by default."""
    profile = ROOT / "shared" / "configuration" / ".env.cloud"
    if not profile.is_file():
        return "cloud profile turns AI features off", "FAIL: .env.cloud missing"
    on, urls = [], []
    for line in profile.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if line.startswith("#") or not _:
            continue
        if name.endswith("_ENABLED") and value.strip().lower() != "false":
            on.append(name)
        if name.endswith(("_AI_MODE_URL", "_RAG_URL")) and value.strip():
            urls.append(name)
    if on or urls:
        return "cloud profile turns AI features off", f"FAIL: still on: {on + urls}"
    return (
        "cloud profile turns AI features off",
        "OK: every *_ENABLED is false, AI URLs blank",
    )


def cloud_static_checks(plan):
    results = [
        (
            f"file {relative}",
            "OK: present" if (ROOT / relative).is_file() else "FAIL: missing",
        )
        for relative in plan.get("required_files", [])
    ]
    deploy = ROOT / "scripts" / "deploy" / "azure" / "deploy-azure.sh"
    text = deploy.read_text(encoding="utf-8") if deploy.is_file() else ""
    results.append(
        (
            "images pulled with a managed identity",
            "OK: deploy-azure.sh uses --registry-identity"
            if "--registry-identity" in text
            else "FAIL: no --registry-identity in deploy-azure.sh",
        )
    )
    workflow = ROOT / ".github" / "workflows" / "cloud-deployment.yml"
    text = workflow.read_text(encoding="utf-8") if workflow.is_file() else ""
    results.append(
        (
            "human release gate (production environment)",
            "OK: deploy job runs in `environment: production`"
            if "environment: production" in text
            else "FAIL: no production environment gate in cloud-deployment.yml",
        )
    )
    return [*results, cloud_profile_check()]


def cloud_run():
    """(run, problem): the run named by CLOUD_RUN_ID, else the newest one."""
    run_id = os.getenv("CLOUD_RUN_ID")
    if not run_id:
        return latest_run("cloud-deployment.yml", ci_branch())
    fields = "databaseId,status,conclusion,headSha,headBranch"
    viewed = gh("run", "view", run_id, "--json", fields)
    if viewed.returncode != 0:
        return None, f"gh run view {run_id}: {viewed.stderr.strip()[:200]}"
    run = json.loads(viewed.stdout)
    return {**run, "branch": run.get("headBranch", "?")}, None


def cloud_report_text():
    """(text, source): the newest workflow's evidence artifact, else the
    committed report."""
    if shutil.which("gh"):
        run, _ = cloud_run()
        if run and run["status"] == "completed":
            target = REPORTS / "ci" / "cloud"
            shutil.rmtree(target, ignore_errors=True)
            gh(
                "run", "download", str(run["databaseId"]),
                "--name", "cloud-deployment-evidence", "--dir", str(target),
            )  # fmt: skip
            found = (
                sorted(target.rglob("cloud-deployment-results.md"))
                if target.exists()
                else []
            )
            if found:
                return found[0].read_text(
                    encoding="utf-8"
                ), f"run {run['databaseId']} artifact"
    committed = RELEASE_REPORTS / "cloud-deployment-results.md"
    if committed.is_file():
        return committed.read_text(
            encoding="utf-8"
        ), "committed docs/reports/release-2 copy"
    return None, None


def cloud_workflow_check():
    if not shutil.which("gh"):
        return "cloud-deployment.yml latest run", "SKIP: gh CLI unavailable"
    run, problem = cloud_run()
    if problem:
        return "cloud-deployment.yml latest run", f"SKIP: {problem}"
    where = f"run {run['databaseId']} at {run['headSha'][:7]} on {run['branch']}"
    if run["status"] != "completed":
        return "cloud-deployment.yml latest run", f"SKIP: {where} is {run['status']}"
    verdict = "OK" if run["conclusion"] == "success" else "FAIL"
    return "cloud-deployment.yml latest run", f"{verdict}: {run['conclusion']}, {where}"


def cloud_probe(url):
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        return f"GET {url}", f"FAIL: {exc}"
    ok = response.status_code == 200
    return f"GET {url}", f"{'OK' if ok else 'FAIL'}: HTTP {response.status_code}"


def run_cloud():
    plan = load_plan("checks/cloud.json")
    text, source = cloud_report_text()
    report = (
        cloud_report_checks(text)
        if text
        else [
            (
                "cloud deployment report",
                "FAIL: no workflow artifact or committed report",
            )
        ]
    )
    if source:
        report.insert(0, ("report source", f"OK: {source}"))
    configuration = [*cloud_static_checks(plan), cloud_workflow_check()]
    if os.getenv("CLOUD_URL"):
        configuration.append(cloud_probe(os.environ["CLOUD_URL"]))
    plan["checks"] = [{"label": label} for label, _ in report + configuration]
    return plan, [
        ("Deployment report", report),
        ("Configuration and release gate", configuration),
    ]


def release_decision(decision, failures):
    """The human decision, as a release call: READY only on Accept with every
    deterministic check passing."""
    if decision.startswith("Deferred"):
        return "PENDING (non-interactive run; a human must decide)"
    if decision == "Accept" and not failures:
        return "READY"
    reason = f"{len(failures)} failed check(s)" if failures else decision
    return f"NOT READY ({reason})"


RUNNERS = {
    "services": run_services,
    "mcp": run_mcp,
    "rag": run_rag,
    "ci": run_ci,
    "multi-agent": run_multi_agent,
    "testing": run_testing,
    "cloud": run_cloud,
}


def call_model(model, system_prompt, user_prompt, max_tokens):
    """One Claude call. Credentials come from the environment -- ANTHROPIC_API_KEY,
    or an `ant auth login` profile locally."""
    try:
        client = anthropic.Anthropic(timeout=180.0)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            # These two agents write three lines each. Low effort keeps the
            # thinking budget (and the bill) in proportion to that.
            output_config={"effort": "low"},
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return text or "No response generated."
    except Exception as exc:  # noqa: BLE001 - a missing key is evidence, not a crash
        # No credentials, no agents. The loop still reports the deterministic
        # evidence, which is the half that decides the exit code.
        return f"{model} unavailable ({exc})"


def prompt_fields(plan, **fields):
    """The placeholders every prompt may use, plus any a mode adds itself
    (the MCP tool catalogue and requests)."""
    return {"SERVICE_SCOPE": scope(plan), **plan.get("prompt_fields", {}), **fields}


def implementation_advice(mode, plan, evidence):
    fields = prompt_fields(plan, VALIDATION_EVIDENCE=evidence)
    return call_model(
        IMPLEMENTATION_MODEL,
        load_prompt(mode, "implementation_system_prompt.txt", **fields),
        load_prompt(mode, "implementation_task_prompt.txt", **fields),
        2000,
    )


def review_advice(mode, plan, recommendation, evidence):
    fields = prompt_fields(
        plan,
        IMPLEMENTATION_RECOMMENDATION=recommendation,
        VALIDATION_EVIDENCE=evidence,
    )
    return call_model(
        REVIEW_MODEL,
        load_prompt(mode, "review_system_prompt.txt", **fields),
        load_prompt(mode, "review_task_prompt.txt", **fields),
        2000,
    )


def flatten(sections):
    """(label, outcome) pairs, each label prefixed with its section if any."""
    return [
        (f"{title} / {label}" if title else label, outcome)
        for title, results in sections
        for label, outcome in results
    ]


def render_report(
    mode, plan, sections, recommendation, review, failures, decision=None
):
    verdict = f"{len(failures)} check(s) failed" if failures else "all checks passed"
    lines = [f"## Agentic loop ({mode}) -- {verdict}", "", f"_{plan['goal']}_"]
    for title, results in sections:
        lines += ["", f"### {title}", ""] if title else [""]
        lines += ["| Check | Result |", "| --- | --- |"]
        lines += [
            f"| {label} | {OUTCOME_ICONS.get(outcome.split(':')[0], '✅')} {outcome} |"
            for label, outcome in results
        ]
    lines += [
        "",
        f"### Implementation agent ({IMPLEMENTATION_MODEL})",
        "",
        recommendation,
        "",
        f"### Review agent ({REVIEW_MODEL})",
        "",
        review,
        "",
    ]
    if decision:
        lines += ["### Human decision", "", decision, ""]
    lines += [
        "Agent findings are advisory -- only the checks above decide the exit code.",
        "",
    ]
    return "\n".join(lines)


def write_report(mode, report):
    """Keep every run for the release write-up."""
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORTS / f"{mode}-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    return path


def write_review_log(mode, report, sections, decision):
    """The committed review/validation log: the report plus a JSON copy of the
    checks, overwritten on each run (reports/ keeps every timestamped run)."""
    REVIEW_LOGS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = REVIEW_LOGS / f"{mode}-review.md"
    path.write_text(f"_Generated {stamp}_\n\n{report}", encoding="utf-8")
    results = flatten(sections)
    (REVIEW_LOGS / f"{mode}-review.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "generated_at": stamp,
                "human_decision": decision,
                "failed": [name for name, out in results if out.startswith("FAIL")],
                "checks": [{"check": name, "outcome": out} for name, out in results],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def human_review():
    print("\nHUMAN REVIEW\n1 - Accept\n2 - Partially Accept\n3 - Reject")
    return {"1": "Accept", "2": "Partially Accept"}.get(
        input("Decision: ").strip(), "Reject"
    )


def choose_mode():
    print("AGENTIC LOOP")
    print(
        "  1 - Services\n  2 - MCP\n  3 - RAG\n  4 - CI\n  5 - Multi-Agent\n"
        "  6 - Testing\n  7 - Cloud\n  0 - Exit"
    )
    choice = input("Choose a validation mode: ").strip()
    return {
        "1": "services",
        "2": "mcp",
        "3": "rag",
        "4": "ci",
        "5": "multi-agent",
        "6": "testing",
        "7": "cloud",
    }.get(choice)


def pick_mode(argv, interactive):
    """--mode wins; a terminal with no flag gets the menu; anything else
    (a pipe, or --ci for a non-interactive run) runs services."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ci", action="store_true", help="non-interactive: no menu, no human review"
    )
    parser.add_argument("--mode", choices=MODES)
    args = parser.parse_args(argv)
    if args.mode:
        return args.mode
    if interactive and not args.ci:
        return choose_mode()
    return "services"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    interactive = "--ci" not in argv and sys.stdin.isatty()
    mode = pick_mode(argv, interactive)
    if mode is None:
        return 0

    print("=" * 60)
    print("AGENTIC LOOP: PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT")
    print("=" * 60)

    print(f"\nACT\n  Running {mode} checks")
    plan, sections = RUNNERS[mode]()
    print(f"\nPLAN\n  {plan['goal']}")
    results = flatten(sections)

    print("\nOBSERVE")
    for label, outcome in results:
        print(f"  {label} -> {outcome}")

    failures = [
        f"{label}: {outcome}"
        for label, outcome in results
        if outcome.startswith("FAIL")
    ]
    evidence = "; ".join(f"{label} -> {outcome}" for label, outcome in results)

    print(f"\nIMPLEMENTATION AGENT ({IMPLEMENTATION_MODEL})")
    recommendation = implementation_advice(mode, plan, evidence)
    print(recommendation)

    if mode == "mcp":
        # The reviewer sees how the picks scored, so it can judge them.
        selection = score_tool_selection(plan, recommendation)
        sections.append(("Tool selection (advisory)", selection))
        print("\nTOOL SELECTION (advisory)")
        for label, outcome in selection:
            print(f"  {label} -> {outcome}")
        evidence += "; " + "; ".join(f"{req} -> {out}" for req, out in selection)

    print(f"\nREVIEW AGENT ({REVIEW_MODEL})")
    review = review_advice(mode, plan, recommendation, evidence)
    print(review)

    decision = human_review() if interactive else "Deferred (non-interactive run)"
    print(f"\nHUMAN DECISION\n  {decision}")
    if mode == "cloud":
        release = release_decision(decision, failures)
        print(f"\nRELEASE DECISION\n  {release}")
        decision = f"{decision}. Release decision: {release}"

    print("\nADAPT")
    if failures:
        print(f"  {len(failures)} deterministic check(s) failed:")
        for failure in failures:
            print(f"    - {failure}")
    else:
        print("  All deterministic checks passed; agent advice is advisory only.")

    report = render_report(
        mode, plan, sections, recommendation, review, failures, decision
    )
    print(f"\nREPORT\n  {write_report(mode, report)}")
    if mode in COMMITTED_LOG_MODES:
        print(f"  {write_review_log(mode, report, sections, decision)}")

    print("\nLOOP COMPLETE")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
