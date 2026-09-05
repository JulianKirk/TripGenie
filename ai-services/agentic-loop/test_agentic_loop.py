import json
import subprocess
from pathlib import Path

import agentic_loop as loop

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_registered_compose_services_exist():
    registered_services = json.loads(
        (Path(__file__).parent / "services.json").read_text()
    )
    result = subprocess.run(
        ["docker", "compose", "config", "--services"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    compose_services = set(result.stdout.splitlines())

    missing_services = {
        compose_service
        for service in registered_services
        for compose_service in service["compose"].split()
        if compose_service not in compose_services
    }

    assert not missing_services, (
        "Agentic Loop registry references unknown Compose services: "
        f"{sorted(missing_services)}"
    )


def test_prompt_substitution():
    text = loop.load_prompt(
        "review_task_prompt.txt",
        SERVICE_SCOPE="scope",
        IMPLEMENTATION_RECOMMENDATION="rec",
        VALIDATION_EVIDENCE="ev",
    )
    assert "{{" not in text
    assert "scope" in text and "rec" in text and "ev" in text


class FakeResponse:
    def __init__(self, status_code=200, text="body"):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def test_observe_flags_status_and_content(monkeypatch):
    responses = {
        "/a": FakeResponse(500),
        "/b": FakeResponse(200, "nothing useful"),
        "/c": FakeResponse(200, "has sydney in it"),
    }
    monkeypatch.setattr(loop, "measure", lambda c: (responses[c["path"]], 5.0))
    monkeypatch.setattr(
        loop,
        "PLAN",
        {
            "checks": [
                {"label": "a", "path": "/a"},
                {"label": "b", "path": "/b", "contains": ["sydney"]},
                {"label": "c", "path": "/c", "contains": ["sydney"]},
            ]
        },
    )
    outcomes = dict(loop.observe())
    assert outcomes["a"].startswith("FAIL: HTTP 500")
    assert outcomes["b"].startswith("FAIL: body missing")
    assert outcomes["c"].startswith("OK")


def test_observe_accepts_documented_status_and_content_alternatives(monkeypatch):
    monkeypatch.setattr(
        loop,
        "measure",
        lambda _check: (FakeResponse(503, '{"code":"MODEL_UNAVAILABLE"}'), 5.0),
    )
    monkeypatch.setattr(
        loop,
        "PLAN",
        {
            "checks": [
                {
                    "label": "ai",
                    "path": "/ai",
                    "status": [200, 503, 504],
                    "contains_any": ["analysis", "MODEL_UNAVAILABLE"],
                }
            ]
        },
    )

    assert dict(loop.observe())["ai"].startswith("OK: HTTP 503")


def test_nfr_ratio(monkeypatch):
    timings = iter([900] + [10] * 19)
    monkeypatch.setattr(loop, "NFR_SAMPLES", 20)
    monkeypatch.setattr(loop, "measure", lambda _c: (None, next(timings)))
    assert loop.observe_nfr({"label": "x", "nfr_ms": 500})[1].startswith("OK: 19/20")


def test_flow_chains_saved_values_and_checks_invariants(monkeypatch):
    seen = []

    def fake_measure(check):
        seen.append(check["path"])
        bodies = {
            "/budgets": '{"data":[{"budget_id":"b1","total_budget":"100.00"}]}',
            "/budgets/b1/summary": (
                '{"data":{"budget_id":"b1","total_budget":"100.00",'
                '"actual_spending":"30.00",'
                '"committed_costs":"20.00","remaining_budget":"50.00"}}'
            ),
        }
        return FakeResponse(200, bodies[check["path"]]), 5.0

    monkeypatch.setattr(loop, "measure", fake_measure)
    monkeypatch.setattr(
        loop,
        "PLAN",
        {
            "checks": [],
            "flows": [
                {
                    "name": "budget",
                    "steps": [
                        {
                            "label": "list",
                            "path": "/budgets",
                            "save": {"ID": "data.0.budget_id"},
                        },
                        {
                            "label": "summary",
                            "path": "/budgets/${ID}/summary",
                            "contains": ["${ID}"],
                            "save": {
                                "TOTAL": "data.total_budget",
                                "SPENT": "data.actual_spending",
                                "COMMITTED": "data.committed_costs",
                                "REMAINING": "data.remaining_budget",
                            },
                        },
                    ],
                    "invariants": [
                        {
                            "label": "remaining = total - spent - committed",
                            "expr": (
                                "float(REMAINING) == float(TOTAL) - float(SPENT)"
                                " - float(COMMITTED)"
                            ),
                        }
                    ],
                }
            ],
        },
    )

    outcomes = dict(loop.observe())
    assert seen == ["/budgets", "/budgets/b1/summary"]
    assert outcomes["budget / remaining = total - spent - committed"] == "OK: holds"


def test_flow_skips_later_steps_and_invariants_after_a_failure(monkeypatch):
    monkeypatch.setattr(loop, "measure", lambda _c: (FakeResponse(500, "{}"), 5.0))
    monkeypatch.setattr(
        loop,
        "PLAN",
        {
            "checks": [],
            "flows": [
                {
                    "name": "f",
                    "steps": [
                        {"label": "one", "path": "/a"},
                        {"label": "two", "path": "/b"},
                    ],
                    "invariants": [{"label": "rule", "expr": "True"}],
                }
            ],
        },
    )

    outcomes = dict(loop.observe())
    assert outcomes["f / one"].startswith("FAIL: HTTP 500")
    assert outcomes["f / two"] == "SKIP: after one"
    assert outcomes["f / rule"] == "SKIP: after one"


def test_failed_extraction_fails_the_step(monkeypatch):
    monkeypatch.setattr(loop, "measure", lambda _c: (FakeResponse(200, "{}"), 5.0))
    monkeypatch.setattr(
        loop,
        "PLAN",
        {
            "checks": [],
            "flows": [
                {
                    "name": "f",
                    "steps": [
                        {"label": "one", "path": "/a", "save": {"ID": "data.0.id"}}
                    ],
                }
            ],
        },
    )

    assert dict(loop.observe())["f / one"].startswith("FAIL: cannot save ['ID']")


def test_every_checks_file_puts_its_flows_and_rules_in_the_agent_scope(monkeypatch):
    for path in sorted((Path(__file__).parent / "checks").glob("*.json")):
        plan = json.loads(path.read_text())
        monkeypatch.setattr(loop, "PLAN", plan)
        scope = loop.scope()
        for flow in plan["flows"]:
            assert flow["steps"], f"{path.name}: {flow['name']} has no steps"
            assert flow["name"] in scope
        for rule in plan["rules"]:
            assert rule in scope
