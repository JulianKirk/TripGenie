"""PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT, for any TripGenie service.

The deterministic half is a JSON checks file (see `checks/`): a goal, a list of
HTTP checks, the business-process `flows` those endpoints have to add up to, and
the domain `rules` the agents must not contradict. The agent half is two Claude
calls that read the evidence and comment on it -- advisory only, they never
decide the exit code.

Run it against your own service by pointing CHECKS_FILE at your own file:

    CHECKS_FILE=checks/student-2.json python agentic_loop.py --ci

ponytail: HTTP checks only, no direct database reads. Every TripGenie database
lives behind its own service, so its API is already the honest way in.
"""

import json
import os
import sys
import time
from pathlib import Path

import anthropic
import requests

HERE = Path(__file__).parent

PLAN = json.loads((HERE / os.getenv("CHECKS_FILE", "checks/shared.json")).read_text())
IMPLEMENTATION_MODEL = os.getenv("IMPLEMENTATION_MODEL", "claude-sonnet-5")
REVIEW_MODEL = os.getenv("REVIEW_MODEL", "claude-opus-5")
NFR_SAMPLES = int(os.getenv("NFR_SAMPLES", "20"))
NFR_PASS_RATIO = 0.95
OUTCOME_ICONS = {"OK": "✅", "FAIL": "❌", "SKIP": "⏭️"}


def load_prompt(name, **fields):
    text = (HERE / "prompts" / name).read_text(encoding="utf-8").strip()
    for key, value in fields.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def scope():
    """What the agents are allowed to talk about: this service, nothing else."""
    lines = [PLAN["goal"], "", "Endpoints under test:"]
    # The labels, not the paths: a path still holds its ${VAR} and the literal
    # probe values (a bogus uuid, a malformed id), which read as real endpoints.
    lines += [f"- {c['label']}" for c in PLAN["checks"]]
    for flow in PLAN.get("flows", []):
        lines += ["", f"Business process under test -- {flow['name']}:"]
        lines += [f"- {step['label']}" for step in flow["steps"]]
        lines += [
            f"- invariant: {rule['label']}" for rule in flow.get("invariants", [])
        ]
    if PLAN.get("rules"):
        lines += ["", "Domain rules (these are correct; never contradict them):"]
        lines += [f"- {rule}" for rule in PLAN["rules"]]
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


def observe():
    results = []
    for check in PLAN["checks"]:
        outcome, _ = run_check(check)
        results.append((check["label"], outcome))

        if check.get("nfr_ms") and outcome.startswith("OK"):
            results.append(observe_nfr(check))
    return results + observe_flows()


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


def observe_flows():
    """The business processes: several requests in order, each able to feed the
    next, then the invariants the collected values have to satisfy."""
    results = []
    for flow in PLAN.get("flows", []):
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


def implementation_advice(evidence):
    return call_model(
        IMPLEMENTATION_MODEL,
        load_prompt("implementation_system_prompt.txt", SERVICE_SCOPE=scope()),
        load_prompt(
            "implementation_task_prompt.txt",
            SERVICE_SCOPE=scope(),
            VALIDATION_EVIDENCE=evidence,
        ),
        2000,
    )


def review_advice(recommendation, evidence):
    return call_model(
        REVIEW_MODEL,
        load_prompt("review_system_prompt.txt"),
        load_prompt(
            "review_task_prompt.txt",
            SERVICE_SCOPE=scope(),
            IMPLEMENTATION_RECOMMENDATION=recommendation,
            VALIDATION_EVIDENCE=evidence,
        ),
        2000,
    )


def write_summary(results, recommendation, review, failures):
    """Put the run on the GitHub Actions summary page. Nobody reads a job log;
    they do read the summary tab, which is where the agent findings belong."""
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    verdict = f"{len(failures)} check(s) failed" if failures else "all checks passed"
    lines = [
        f"## Agentic loop -- {verdict}",
        "",
        f"_{PLAN['goal']}_",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
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
    with Path(summary).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def human_review():
    print("\nHUMAN REVIEW\n1 - Accept\n2 - Partially Accept\n3 - Reject")
    return {"1": "Accept", "2": "Partially Accept"}.get(
        input("Decision: ").strip(), "Reject"
    )


def main():
    interactive = "--ci" not in sys.argv and sys.stdin.isatty()

    print("=" * 60)
    print("AGENTIC LOOP: PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT")
    print("=" * 60)
    print(f"\nPLAN\n  {PLAN['goal']}")

    print("\nACT\n  Running deterministic checks")
    results = observe()

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
    recommendation = implementation_advice(evidence)
    print(recommendation)

    print(f"\nREVIEW AGENT ({REVIEW_MODEL})")
    review = review_advice(recommendation, evidence)
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

    write_summary(results, recommendation, review, failures)

    print("\nLOOP COMPLETE")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
