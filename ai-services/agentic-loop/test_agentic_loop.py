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


def test_student_4_functional_flow_starts_location_dependencies():
    directory = Path(__file__).parent
    registered_services = json.loads((directory / "services.json").read_text())
    student_4 = next(
        service for service in registered_services if service["service"] == "student-4"
    )

    assert student_4["compose"] == "student-4"
    assert not student_4.get("no_deps", False)

    checks = json.loads((directory / "checks/student-4.json").read_text())["checks"]
    outcomes = {check["label"]: check.get("contains", []) for check in checks}
    assert '"status":"ok"' in outcomes["GET frontend /health"]
    assert '"status":"ok"' in outcomes["GET backend /health"]
    assert '"location":"ok"' in outcomes["GET backend /health"]


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
    plan = {
        "checks": [
            {"label": "a", "path": "/a"},
            {"label": "b", "path": "/b", "contains": ["sydney"]},
            {"label": "c", "path": "/c", "contains": ["sydney"]},
        ]
    }
    outcomes = dict(loop.observe(plan))
    assert outcomes["a"].startswith("FAIL: HTTP 500")
    assert outcomes["b"].startswith("FAIL: body missing")
    assert outcomes["c"].startswith("OK")


def test_observe_accepts_documented_status_and_content_alternatives(monkeypatch):
    monkeypatch.setattr(
        loop,
        "measure",
        lambda _check: (FakeResponse(503, '{"code":"MODEL_UNAVAILABLE"}'), 5.0),
    )
    plan = {
        "checks": [
            {
                "label": "ai",
                "path": "/ai",
                "status": [200, 503, 504],
                "contains_any": ["analysis", "MODEL_UNAVAILABLE"],
            }
        ]
    }

    assert dict(loop.observe(plan))["ai"].startswith("OK: HTTP 503")


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
    plan = {
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
    }

    outcomes = dict(loop.observe(plan))
    assert seen == ["/budgets", "/budgets/b1/summary"]
    assert outcomes["budget / remaining = total - spent - committed"] == "OK: holds"


def test_flow_skips_later_steps_and_invariants_after_a_failure(monkeypatch):
    monkeypatch.setattr(loop, "measure", lambda _c: (FakeResponse(500, "{}"), 5.0))
    plan = {
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
    }

    outcomes = dict(loop.observe(plan))
    assert outcomes["f / one"].startswith("FAIL: HTTP 500")
    assert outcomes["f / two"] == "SKIP: after one"
    assert outcomes["f / rule"] == "SKIP: after one"


def test_failed_extraction_fails_the_step(monkeypatch):
    monkeypatch.setattr(loop, "measure", lambda _c: (FakeResponse(200, "{}"), 5.0))
    plan = {
        "checks": [],
        "flows": [
            {
                "name": "f",
                "steps": [{"label": "one", "path": "/a", "save": {"ID": "data.0.id"}}],
            }
        ],
    }

    assert dict(loop.observe(plan))["f / one"].startswith("FAIL: cannot save ['ID']")


def test_every_checks_file_puts_its_flows_and_rules_in_the_agent_scope():
    for path in sorted((Path(__file__).parent / "checks").glob("*.json")):
        plan = json.loads(path.read_text())
        scope = loop.scope(plan)
        for flow in plan.get("flows", []):
            assert flow["steps"], f"{path.name}: {flow['name']} has no steps"
            assert flow["name"] in scope
        for rule in plan.get("rules", []):
            assert rule in scope


def test_mode_selection_keeps_the_ci_default():
    assert loop.pick_mode(["--ci"], interactive=False) == "services"
    assert loop.pick_mode([], interactive=False) == "services"
    assert loop.pick_mode(["--ci", "--mode", "rag"], interactive=False) == "rag"


def test_menu_exit_and_choice(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "0")
    assert loop.pick_mode([], interactive=True) is None
    monkeypatch.setattr("builtins.input", lambda _prompt: "2")
    assert loop.pick_mode([], interactive=True) == "mcp"


def test_services_mode_reports_each_service_and_keeps_going(monkeypatch):
    monkeypatch.setenv("SERVICES", "student-1 student-3")
    monkeypatch.setenv("SKIPPED", "student-2=service unchanged;student-4=build failed")
    monkeypatch.setattr(
        loop, "wait_ready", lambda entry: entry["service"] == "student-3"
    )
    monkeypatch.setattr(
        loop, "observe", lambda _plan: [("GET /health", "OK: HTTP 200 in 5ms")]
    )

    plan, sections = loop.run_services()
    outcomes = dict(sections)

    assert outcomes["student-1"] == [
        ("GET /ready", "FAIL: not ready after 20 attempts")
    ]
    assert outcomes["student-3"] == [("GET /health", "OK: HTTP 200 in 5ms")]
    assert outcomes["student-2"] == [("loop", "SKIP: service unchanged")]
    assert outcomes["student-4"] == [("loop", "SKIP: build failed")]
    assert outcomes["shared"] == [("loop", "SKIP: not selected")]
    assert "student-1, student-3" in plan["goal"]


def test_report_has_a_section_per_service():
    sections = [("student-1", [("a", "FAIL: x")]), ("student-2", [("loop", "SKIP: y")])]
    report = loop.render_report(
        "services", {"goal": "g"}, sections, "rec", "rev", ["a"]
    )
    assert "### student-1" in report and "### student-2" in report
    assert "1 check(s) failed" in report


MCP_STEPS = [
    {
        "label": "read",
        "tool": "budgets_list",
        "arguments": {},
        "source": "student-5",
        "save": {"TRIP_ID": "data.budgets.0.trip_id"},
    },
    {
        "label": "chained",
        "tool": "trip_get_context",
        "arguments": {"trip_id": "${TRIP_ID}"},
        "source": "student-1",
    },
    {
        "label": "bad limit",
        "tool": "budgets_list",
        "arguments": {"limit": 0},
        "error": "VALIDATION_ERROR",
    },
    {"label": "unknown", "tool": "nope", "rejected": True},
]


def fake_mcp(tools, responses, timings=None):
    """responses: tool name -> list of structuredContent, one per call."""
    timings = iter(timings or [])

    def call(method, params=None):
        if method == "tools/list":
            return {"result": {"tools": [{"name": n} for n in tools]}}, 5.0
        queue = responses[params["name"]]
        content = queue.pop(0) if len(queue) > 1 else queue[0]
        if content is None:
            return {"error": {"code": -32602, "message": "Unknown tool"}}, 5.0
        return {"result": {"structuredContent": content}}, next(timings, 5.0)

    return call


def test_mcp_checks_envelopes_boundaries_and_chaining(monkeypatch):
    ok5 = {"ok": True, "data": {"budgets": [{"trip_id": "t1"}]}, "source": "student-5"}
    ok1 = {"ok": True, "data": {"id": "t1"}, "source": "student-1"}
    invalid = {"ok": False, "error": {"code": "VALIDATION_ERROR"}}
    calls = []
    call = fake_mcp(
        ["budgets_list", "trip_get_context"],
        {
            "budgets_list": [ok5, ok5, invalid],
            "trip_get_context": [ok1],
            "nope": [None],
        },
    )

    def recording(method, params=None):
        calls.append(params)
        return call(method, params)

    monkeypatch.setattr(loop, "mcp_call", recording)
    plan = {"tools": ["budgets_list", "trip_get_context"], "steps": MCP_STEPS}
    outcomes = dict(loop.observe_mcp(plan))

    assert outcomes["tools/list"].startswith("OK: all 2")
    assert outcomes["read"].startswith("OK: student-5")
    assert outcomes["read repeated"] == "OK: same data"
    assert {"name": "trip_get_context", "arguments": {"trip_id": "t1"}} in calls
    assert outcomes["chained"].startswith("OK: student-1")
    assert outcomes["bad limit"] == "OK: VALIDATION_ERROR"
    assert outcomes["unknown"] == "OK: rejected"


def test_mcp_flags_missing_tools_wrong_source_slow_and_changing_calls(monkeypatch):
    first = {"ok": True, "data": {"n": 1}, "source": "student-5"}
    second = {"ok": True, "data": {"n": 2}, "source": "student-5"}
    monkeypatch.setattr(
        loop,
        "mcp_call",
        fake_mcp(["budgets_list"], {"budgets_list": [first, second]}, [4000.0]),
    )
    step = {"label": "read", "tool": "budgets_list", "source": "student-5"}
    plan = {"tools": ["budgets_list", "trip_get_context"], "steps": [step]}
    outcomes = dict(loop.observe_mcp(plan))

    assert "missing ['trip_get_context']" in outcomes["tools/list"]
    assert outcomes["read latency <= 3000ms"].startswith("FAIL: 4000ms")
    assert outcomes["read repeated"] == "FAIL: data changed between calls"

    wrong = {"ok": True, "data": {}, "source": "student-4"}
    monkeypatch.setattr(loop, "mcp_call", fake_mcp([], {"budgets_list": [wrong]}))
    assert dict(loop.observe_mcp(plan))["read"].startswith("FAIL: source student-4")


def test_mcp_skips_a_step_whose_input_was_never_saved(monkeypatch):
    broken = {"ok": False, "error": {"code": "PROVIDER_UNAVAILABLE"}}
    monkeypatch.setattr(
        loop, "mcp_call", fake_mcp([], {"budgets_list": [broken], "nope": [None]})
    )
    plan = {"tools": [], "steps": MCP_STEPS[:2]}
    outcomes = dict(loop.observe_mcp(plan))
    assert outcomes["read"].startswith("FAIL")
    assert outcomes["chained"].startswith("SKIP")


def test_mcp_only_reads_from_services_started_in_this_run(monkeypatch):
    monkeypatch.setenv("SERVICES", "student-1")
    invalid = {"ok": False, "error": {"code": "VALIDATION_ERROR"}}
    monkeypatch.setattr(loop, "mcp_call", fake_mcp([], {"budgets_list": [invalid]}))
    plan = {"tools": [], "steps": [MCP_STEPS[0], MCP_STEPS[2]]}
    outcomes = dict(loop.observe_mcp(plan))
    assert outcomes["read"] == "SKIP: student-5 not started in this run"
    assert outcomes["bad limit"] == "OK: VALIDATION_ERROR"


def test_mcp_compares_tool_data_with_the_backend(monkeypatch):
    monkeypatch.setenv("MCP_STUDENT_5_URL", "http://s5")
    envelope = {"ok": True, "data": {"items": [{"id": "a", "price": "1.00"}]}}
    monkeypatch.setattr(
        loop.requests,
        "get",
        lambda url, **_kwargs: FakeResponse(
            200, '{"data":[{"id":"a","price":"2.00"}]}' if url == "http://s5/x" else ""
        ),
    )
    step = {
        "compare": {
            "path": "${MCP_STUDENT_5_URL}/x",
            "fields": {
                "data.items.0.id": "data.0.id",
                "data.items.0.price": "data.0.price",
            },
        }
    }
    outcome = loop.compare_backend(step, envelope)
    assert outcome.startswith("FAIL: data.items.0.price='1.00'")
    assert "data.items.0.id" not in outcome


RAG_CASES = [
    {
        "case_id": "grounded",
        "query": "q1",
        "feature": "shared",
        "expected_source_ids": ["doc-a"],
        "expect_insufficient_context": False,
    },
    {
        "case_id": "unanswerable",
        "query": "q2",
        "feature": "shared",
        "expected_source_ids": [],
        "expect_insufficient_context": True,
    },
]


def rag_body(category, sources, answer="An answer."):
    return {
        "answer": answer,
        "confidence_category": category,
        "insufficient_context": category == "insufficient_context",
        "citations": [{"source_id": s} for s in sources],
    }


def test_rag_checks_grounding_insufficient_context_and_repeats(monkeypatch):
    monkeypatch.setattr(loop.requests, "get", lambda *_a, **_k: FakeResponse(200, "{}"))
    replies = {
        "q1": [
            (rag_body("high", ["doc-a"]), 900.0),
            (rag_body("high", ["doc-a"]), 5.0),
        ],
        "q2": [
            (rag_body("insufficient_context", [], "Not enough."), 4000.0),
            (rag_body("insufficient_context", [], "Not enough."), 5.0),
        ],
    }
    monkeypatch.setattr(loop, "rag_query", lambda case: replies[case["query"]].pop(0))
    outcomes = dict(loop.observe_rag({"cases": RAG_CASES}))

    assert outcomes["grounded"].startswith("OK: high confidence")
    assert outcomes["grounded latency <= 30000ms"].startswith("OK")
    assert outcomes["grounded repeated"].startswith("OK")
    assert outcomes["unanswerable"] == "OK: insufficient context"
    assert outcomes["unanswerable latency <= 3000ms"].startswith("FAIL: 4000ms")


def test_rag_flags_missing_citations_and_unstable_retrieval(monkeypatch):
    monkeypatch.setattr(loop.requests, "get", lambda *_a, **_k: FakeResponse(200, "{}"))
    replies = [(rag_body("low", ["doc-b"]), 5.0), (rag_body("medium", ["doc-b"]), 5.0)]
    monkeypatch.setattr(loop, "rag_query", lambda _case: replies.pop(0))
    outcomes = dict(loop.observe_rag({"cases": RAG_CASES[:1]}))

    assert outcomes["grounded"].startswith("FAIL: citations missing ['doc-a']")
    assert outcomes["grounded repeated"].startswith("FAIL")


def test_rag_mode_reads_the_rag_servers_calibration_cases():
    plan = loop.load_plan("checks/rag.json")
    cases = json.loads((loop.HERE / plan["calibration"]).read_text())["cases"]
    assert any(case["expect_insufficient_context"] for case in cases)


class FakeRun:
    def __init__(self, stdout="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, "", returncode


def test_ci_mode_skips_without_gh(monkeypatch):
    monkeypatch.setattr(loop.shutil, "which", lambda _name: None)
    assert loop.observe_ci()[0][1].startswith("SKIP: gh CLI unavailable")


def test_ci_mode_turns_run_conclusions_into_checks(monkeypatch, tmp_path):
    monkeypatch.setattr(loop.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(loop, "REPORTS", tmp_path)
    monkeypatch.setenv("CI_BRANCH", "feature")
    monkeypatch.setattr(
        loop,
        "REGISTRY",
        [
            {"service": "student-1", "ci": "student-1-ci.yml"},
            {"service": "student-2", "ci": "student-2-ci.yml"},
            {"service": "student-3", "ci": "student-3-ci.yml"},
        ],
    )
    runs = {
        "student-1-ci.yml": [
            {"databaseId": 1, "status": "completed", "conclusion": "success",
             "headSha": "abcdef123"}
        ],
        "student-2-ci.yml": [
            {"databaseId": 2, "status": "completed", "conclusion": "failure",
             "headSha": "abcdef123"}
        ],
        "student-3-ci.yml": [],
    }  # fmt: skip

    def fake_gh(*args):
        if args[:2] == ("run", "list"):
            assert args[args.index("--branch") + 1] == "feature"
            return FakeRun(json.dumps(runs[args[3]]))
        target = Path(args[args.index("--dir") + 1])
        (target / "report").mkdir(parents=True)
        return FakeRun()

    monkeypatch.setattr(loop, "gh", fake_gh)
    outcomes = dict(loop.observe_ci())

    assert outcomes["student-1 (student-1-ci.yml)"].startswith("OK: success, run 1")
    assert "artifacts: report" in outcomes["student-1 (student-1-ci.yml)"]
    assert outcomes["student-2 (student-2-ci.yml)"].startswith("FAIL: failure")
    assert outcomes["student-3 (student-3-ci.yml)"] == "SKIP: no run on feature"
