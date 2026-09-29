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
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import requests

HERE = Path(__file__).parent
REPORTS = HERE / "reports"
REGISTRY = json.loads((HERE / "services.json").read_text())
MODES = ("services", "mcp", "rag", "ci")
IMPLEMENTATION_MODEL = os.getenv("IMPLEMENTATION_MODEL", "claude-sonnet-5")
REVIEW_MODEL = os.getenv("REVIEW_MODEL", "claude-opus-5")
NFR_SAMPLES = int(os.getenv("NFR_SAMPLES", "20"))
NFR_PASS_RATIO = 0.95
OUTCOME_ICONS = {"OK": "✅", "FAIL": "❌", "SKIP": "⏭️"}
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


def load_plan(name):
    return json.loads((HERE / name).read_text())


def load_prompt(name, **fields):
    text = (HERE / "prompts" / name).read_text(encoding="utf-8").strip()
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
        held = eval(
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
        names = {tool["name"] for tool in listed["result"]["tools"]}
    except Exception as exc:  # noqa: BLE001
        return [("tools/list", f"FAIL: MCP server unreachable at {MCP_URL} ({exc})")]
    expected = set(plan["tools"])
    if names == expected:
        results = [("tools/list", f"OK: all {len(expected)} tools registered")]
    else:
        missing, extra = sorted(expected - names), sorted(names - expected)
        results = [("tools/list", f"FAIL: missing {missing}, unexpected {extra}")]

    # In CI only the services that passed their own build are started, so a read
    # from any other student would fail for a reason that is not the MCP server.
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
    return plan, [(None, observe_mcp(plan))]


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
    return response.json(), elapsed


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
    for case in plan["cases"]:
        label = case["case_id"]
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
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def observe_ci():
    """The latest run of each service's own workflow on this branch, and what
    it uploaded. Conclusions are the evidence; artifacts land in reports/ci/."""
    if not shutil.which("gh"):
        return [("gh", "SKIP: gh CLI unavailable; install it and run gh auth login")]
    branch = (
        os.getenv("CI_BRANCH")
        or subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
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


RUNNERS = {"services": run_services, "mcp": run_mcp, "rag": run_rag, "ci": run_ci}


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
        # No credentials in CI by default. The loop still reports the
        # deterministic evidence, which is the half that gates the build.
        return f"{model} unavailable ({exc})"


def implementation_advice(plan, evidence):
    return call_model(
        IMPLEMENTATION_MODEL,
        load_prompt("implementation_system_prompt.txt", SERVICE_SCOPE=scope(plan)),
        load_prompt(
            "implementation_task_prompt.txt",
            SERVICE_SCOPE=scope(plan),
            VALIDATION_EVIDENCE=evidence,
        ),
        2000,
    )


def review_advice(plan, recommendation, evidence):
    return call_model(
        REVIEW_MODEL,
        load_prompt("review_system_prompt.txt"),
        load_prompt(
            "review_task_prompt.txt",
            SERVICE_SCOPE=scope(plan),
            IMPLEMENTATION_RECOMMENDATION=recommendation,
            VALIDATION_EVIDENCE=evidence,
        ),
        2000,
    )


def flatten(sections):
    """(label, outcome) pairs, each label prefixed with its section if any."""
    return [
        (f"{title} / {label}" if title else label, outcome)
        for title, results in sections
        for label, outcome in results
    ]


def render_report(mode, plan, sections, recommendation, review, failures):
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
        "Agent findings are advisory -- only the checks above decide the exit code.",
        "",
    ]
    return "\n".join(lines)


def write_report(mode, report):
    """Keep every run for the release write-up, and put it on the GitHub Actions
    summary page too -- nobody reads a job log, they do read the summary tab."""
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORTS / f"{mode}-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(report)
    return path


def human_review():
    print("\nHUMAN REVIEW\n1 - Accept\n2 - Partially Accept\n3 - Reject")
    return {"1": "Accept", "2": "Partially Accept"}.get(
        input("Decision: ").strip(), "Reject"
    )


def choose_mode():
    print("AGENTIC LOOP")
    print("  1 - Services\n  2 - MCP\n  3 - RAG\n  4 - CI\n  0 - Exit")
    choice = input("Choose a validation mode: ").strip()
    return {"1": "services", "2": "mcp", "3": "rag", "4": "ci"}.get(choice)


def pick_mode(argv, interactive):
    """--mode wins; a terminal with no flag gets the menu; anything else runs
    services, so the existing `--ci` workflow is unchanged."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ci", action="store_true", help="non-interactive run")
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
    recommendation = implementation_advice(plan, evidence)
    print(recommendation)

    print(f"\nREVIEW AGENT ({REVIEW_MODEL})")
    review = review_advice(plan, recommendation, evidence)
    print(review)

    decision = human_review() if interactive else "Deferred (non-interactive run)"
    print(f"\nHUMAN DECISION\n  {decision}")

    print("\nADAPT")
    if failures:
        print(f"  {len(failures)} deterministic check(s) failed:")
        for failure in failures:
            print(f"    - {failure}")
    else:
        print("  All deterministic checks passed; agent advice is advisory only.")

    report = render_report(mode, plan, sections, recommendation, review, failures)
    print(f"\nREPORT\n  {write_report(mode, report)}")

    print("\nLOOP COMPLETE")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
