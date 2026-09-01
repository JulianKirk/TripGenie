"""PLAN -> ACT -> OBSERVE -> AGENTS -> HUMAN -> ADAPT, for any TripGenie service.

The deterministic half is a JSON checks file (see `checks/`): a goal and a list
of HTTP checks. The agent half is two Claude calls that read the evidence and
comment on it -- advisory only, they never decide the exit code.

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


def load_prompt(name, **fields):
    text = (HERE / "prompts" / name).read_text(encoding="utf-8").strip()
    for key, value in fields.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def scope():
    """What the agents are allowed to talk about: this service, nothing else."""
    lines = [PLAN["goal"], "", "Endpoints under test:"]
    lines += [f"- {c.get('method', 'GET')} {c['path']}" for c in PLAN["checks"]]
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


def observe():
    results = []
    for check in PLAN["checks"]:
        expected = check.get("status", 200)
        try:
            response, elapsed = measure(check)
            missing = [t for t in check.get("contains", []) if t not in response.text]
            if response.status_code != expected:
                outcome = f"FAIL: HTTP {response.status_code}, expected {expected}"
            elif not response.text.strip():
                outcome = "FAIL: empty body"
            elif missing:
                outcome = f"FAIL: body missing {missing}"
            else:
                outcome = f"OK: HTTP {response.status_code} in {elapsed:.0f}ms"
        except Exception as exc:  # noqa: BLE001 - a broken check is evidence, not a crash
            outcome = f"FAIL: {exc}"
        results.append((check["label"], outcome))

        if check.get("nfr_ms") and outcome.startswith("OK"):
            results.append(observe_nfr(check))
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
    print(review_advice(recommendation, evidence))

    decision = human_review() if interactive else "Deferred (non-interactive run)"
    print(f"\nHUMAN DECISION\n  {decision}")

    print("\nADAPT")
    if failures:
        print(f"  {len(failures)} deterministic check(s) failed:")
        for failure in failures:
            print(f"    - {failure}")
    else:
        print("  All deterministic checks passed; agent advice is advisory only.")

    print("\nLOOP COMPLETE")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
