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
        ["docker", "compose", "config", "--services"],  # noqa: S607 - local Docker CLI; literal arguments
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
        "services",
        "review_task_prompt.txt",
        SERVICE_SCOPE="scope",
        IMPLEMENTATION_RECOMMENDATION="rec",
        VALIDATION_EVIDENCE="ev",
    )
    assert "{{" not in text
    assert "scope" in text and "rec" in text and "ev" in text


def test_every_mode_has_its_own_complete_prompts():
    fields = {
        "SERVICE_SCOPE": "scope",
        "IMPLEMENTATION_RECOMMENDATION": "rec",
        "VALIDATION_EVIDENCE": "ev",
        "TOOL_CATALOGUE": "- budgets_list: List budgets.",
        "TOOL_REQUESTS": "1. What budgets exist?",
    }
    names = [
        "implementation_system_prompt.txt",
        "implementation_task_prompt.txt",
        "review_system_prompt.txt",
        "review_task_prompt.txt",
    ]
    texts = {}
    for mode in loop.MODES:
        for name in names:
            text = loop.load_prompt(mode, name, **fields)
            assert "{{" not in text, f"{mode}/{name} has an unfilled placeholder"
            texts[mode, name] = text
    # Different evidence needs different instructions, not one shared prompt.
    for name in names:
        assert len({texts[mode, name] for mode in loop.MODES}) == len(loop.MODES)
    assert "Selected Tool:" in texts["mcp", "implementation_task_prompt.txt"]
    assert "citation" in texts["rag", "review_system_prompt.txt"]


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


def test_tool_selection_is_scored_but_never_fails():
    plan = {
        "catalogue": {"budgets_list": "", "transport_search": ""},
        "tool_selection": [
            {"request": "budgets?", "expected": "budgets_list"},
            {"request": "trains?", "expected": "transport_search"},
            {"request": "hotels?", "expected": "accommodations_search"},
        ],
    }
    picks = (
        "1. Selected Tool: budgets_list | Reason: r | Expected Evidence: e\n"
        "2. Selected Tool: `budgets_list` | Reason: r | Expected Evidence: e\n"
    )
    outcomes = dict(loop.score_tool_selection(plan, picks))
    assert outcomes["budgets?"] == "OK: picked budgets_list"
    assert outcomes["trains?"] == "NOTE: picked budgets_list, expected transport_search"
    assert outcomes["hotels?"] == "SKIP: agent gave no selection"
    assert not any(o.startswith("FAIL") for o in outcomes.values())

    del plan["catalogue"]
    assert loop.score_tool_selection(plan, picks)[0][1] == "SKIP: no tool catalogue"


def test_mcp_prompt_fields_carry_the_live_catalogue_and_requests(monkeypatch):
    def fake_observe(plan):
        plan["catalogue"] = {"budgets_list": "List budgets."}
        return []

    monkeypatch.setattr(loop, "observe_mcp", fake_observe)
    plan, _ = loop.run_mcp()
    fields = plan["prompt_fields"]
    assert fields["TOOL_CATALOGUE"] == "- budgets_list: List budgets."
    assert fields["TOOL_REQUESTS"].startswith("1. ")
    assert len(fields["TOOL_REQUESTS"].splitlines()) == len(plan["tool_selection"])


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


def test_rag_query_unwraps_the_servers_data_envelope(monkeypatch):
    class Reply:
        status_code = 200

        @staticmethod
        def json():
            return {"data": rag_body("high", ["doc-a"])}

    monkeypatch.setattr(loop.requests, "post", lambda *_a, **_k: Reply())
    body, _elapsed = loop.rag_query(RAG_CASES[0])
    assert body["confidence_category"] == "high"
    assert loop.grounding(RAG_CASES[0], body).startswith("OK")


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
             "headSha": "abcdef123"}  # pragma: allowlist secret - synthetic commit ID
        ],
        "student-2-ci.yml": [
            {"databaseId": 2, "status": "completed", "conclusion": "failure",
             "headSha": "abcdef123"}  # pragma: allowlist secret - synthetic commit ID
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


def multi_agent_document(**changes):
    """An export document for a finished, human-approved run."""
    run = {
        "run_id": "magent_0123456789ab",
        "feature": "student-3",
        "status": "completed",
        "attempts": 1,
        "checks": [
            {"name": "output_schema", "passed": True, "blocking": True, "detail": "ok"},
            {"name": "grounding", "passed": True, "blocking": True, "detail": "1 id"},
        ],
        "review": {"verdict": "approve"},
        "human": {"decision": "approve", "reviewer": "mark"},
    }
    stages = [
        {"agent": "planner", "status": "completed", "tool_calls": 0},
        {"agent": "worker", "status": "completed", "tool_calls": 2},
        {"agent": "reviewer", "status": "completed", "tool_calls": 0},
    ]
    names = [
        ("api", "run_created"),
        ("system", "awaiting_human"),
        ("human:mark", "human_decision"),
        ("system", "run_completed"),
    ]
    history = [
        {"sequence": n, "actor": actor, "event": event}
        for n, (actor, event) in enumerate(names, start=1)
    ]
    document = {"run": run, "history": history, "summary": {"stages": stages}}
    return {**document, **changes}


def outcomes(results):
    return dict(results)


def test_multi_agent_review_passes_a_complete_run():
    results = outcomes(loop.audit_checks(multi_agent_document()))

    assert not [o for o in results.values() if o.startswith("FAIL")]
    assert results["human decision"] == "OK: approve by mark"
    assert results["audit trail ends with the final event"] == "OK: run_completed"


def test_multi_agent_review_flags_failed_checks_and_missing_human_decision():
    document = multi_agent_document()
    document["run"]["checks"][1]["passed"] = False
    document["run"]["human"] = None
    document["run"]["status"] = "awaiting_human"
    document["summary"]["stages"] = document["summary"]["stages"][:2]

    results = outcomes(loop.audit_checks(document))

    assert results["check grounding"].startswith("FAIL")
    assert results["reviewer stage completed"] == "FAIL: no completed stage"
    assert results["human decision"].startswith("FAIL: none recorded")


def test_multi_agent_review_checks_decision_matches_final_status_and_audit_order():
    document = multi_agent_document()
    document["run"]["human"]["decision"] = "reject"  # but the run says completed
    document["history"][2], document["history"][1] = (
        document["history"][1],
        document["history"][2],
    )

    results = outcomes(loop.audit_checks(document))

    assert (
        results["final status matches decision"] == "FAIL: completed, expected rejected"
    )
    assert results["audit sequence increasing"].startswith("FAIL")

    document = multi_agent_document()
    document["history"][1]["sequence"], document["history"][2]["sequence"] = 3, 2
    results = outcomes(loop.audit_checks(document))
    assert results["human decision follows awaiting_human"].startswith("FAIL")


def test_multi_agent_review_notes_are_advisory():
    document = multi_agent_document()
    document["run"]["review"] = {"verdict": "revise"}
    document["run"]["attempts"] = 2
    document["summary"]["stages"][1]["tool_calls"] = 0

    results = outcomes(loop.audit_checks(document))

    assert results["reviewer verdict"].startswith("NOTE")
    assert results["revision"].startswith("NOTE")
    assert results["worker tool calls"].startswith("NOTE")


def test_multi_agent_mode_reads_the_newest_decided_run(monkeypatch):
    runs = [
        {"run_id": "magent_aaaaaaaaaaaa", "status": "awaiting_human"},
        {"run_id": "magent_bbbbbbbbbbbb", "status": "completed"},
    ]
    seen = []

    def fake_get(path, **_params):
        seen.append(path)
        if path == "/runs":
            return 200, {"data": runs}
        if path.endswith("/export"):
            return 200, {"data": multi_agent_document()}
        return 200, {"data": {}}

    monkeypatch.setattr(loop, "multi_agent_get", fake_get)
    monkeypatch.delenv("RUN_ID", raising=False)
    plan = {
        "required_files": ["ai-services/agentic-loop/agentic_loop.py", "missing.py"]
    }

    results = outcomes(loop.observe_multi_agent(plan))

    assert "/runs/magent_bbbbbbbbbbbb/export" in seen
    assert results["GET /ready"] == "OK: HTTP 200"
    assert results["file missing.py"] == "FAIL: missing"
    assert results["file ai-services/agentic-loop/agentic_loop.py"] == "OK: present"


def test_multi_agent_mode_uses_run_id_when_given(monkeypatch):
    seen = []
    monkeypatch.setenv("RUN_ID", "magent_cccccccccccc")
    monkeypatch.setattr(
        loop,
        "multi_agent_get",
        lambda path, **_: (seen.append(path), (200, {"data": multi_agent_document()}))[
            1
        ],
    )

    loop.observe_multi_agent({})

    assert "/runs" not in seen
    assert "/runs/magent_cccccccccccc/export" in seen


def test_multi_agent_mode_reports_an_unreachable_server_without_crashing(monkeypatch):
    def down(*_args, **_kwargs):
        message = "connection refused"
        raise OSError(message)

    monkeypatch.setattr(loop, "multi_agent_get", down)

    results = loop.observe_multi_agent({"required_files": []})

    assert results == [("Multi-Agent Server", "FAIL: connection refused")]


def test_multi_agent_mode_fails_when_the_server_has_no_runs(monkeypatch):
    monkeypatch.delenv("RUN_ID", raising=False)
    monkeypatch.setattr(loop, "multi_agent_get", lambda _path, **_: (200, {"data": []}))

    results = outcomes(loop.observe_multi_agent({}))

    assert results["select run"].startswith("FAIL: no runs")


def test_multi_agent_checks_file_lists_real_files():
    plan = loop.load_plan("checks/multi-agent.json")

    assert plan["required_files"]
    assert not [f for f in plan["required_files"] if not (loop.ROOT / f).is_file()]


def test_multi_agent_is_selectable_from_the_menu(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "5")

    assert loop.choose_mode() == "multi-agent"
    assert "multi-agent" in loop.RUNNERS


def test_multi_agent_review_log_is_committed_with_the_human_decision(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(loop, "REVIEW_LOGS", tmp_path / "agentic-loop")
    sections = [
        (None, [("human decision", "OK: approve by mark"), ("check x", "FAIL: bad")])
    ]
    plan = {"goal": "goal"}

    report = loop.render_report(
        "multi-agent", plan, sections, "rec", "rev", ["x"], "Accept"
    )
    path = loop.write_review_log("multi-agent", report, sections, "Accept")

    assert path.name == "multi-agent-review.md"
    assert "### Human decision" in path.read_text()
    data = json.loads((path.parent / "multi-agent-review.json").read_text())
    assert data["human_decision"] == "Accept"
    assert data["failed"] == ["check x"]
    assert "multi-agent" in loop.COMMITTED_LOG_MODES


# ---------------------------------------------------------------- testing mode


def scan_json(**overrides):
    data = {
        "status": "passed",
        "checks": [{"tool": t, "status": "passed"} for t in loop.PRE_COMMIT_TOOLS],
    }
    return json.dumps({**data, **overrides})


def release_reports(monkeypatch, tmp_path):
    folder = tmp_path / "release-2"
    folder.mkdir()
    monkeypatch.setattr(loop, "RELEASE_REPORTS", folder)
    return folder


def test_pre_commit_report_reads_the_scan_json(monkeypatch, tmp_path):
    folder = release_reports(monkeypatch, tmp_path)
    (folder / "student-5-pre-commit-security-scan.json").write_text(scan_json())
    failing = {"status": "failed", "checks": [{"tool": "ruff", "status": "failed"}]}
    (folder / "student-3-pre-commit-security-scan.json").write_text(json.dumps(failing))

    assert loop.pre_commit_report("student-5")[1].startswith("OK: student-5-pre")
    outcome = loop.pre_commit_report("student-3")[1]
    assert outcome.startswith("FAIL") and "detect-secrets" in outcome


def test_pre_commit_report_accepts_a_written_report_that_covers_all_tools(
    monkeypatch, tmp_path
):
    folder = release_reports(monkeypatch, tmp_path)
    (folder / "student-1-pre-commit-security-report.md").write_text(
        "Ruff, detect-secrets and pip-audit ran."
    )
    (folder / "student-4-pre-commit-security-report.md").write_text("Ruff only.")

    assert loop.pre_commit_report("student-1")[1].startswith("OK")
    assert "pip-audit" in loop.pre_commit_report("student-4")[1]
    missing = loop.pre_commit_report("student-2")[1]
    assert missing.startswith("FAIL: no student-2-pre-commit-security-report.md")


def test_pre_commit_setup_needs_the_hook_and_the_scan_script(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    assert all(o.startswith("FAIL") for _, o in loop.pre_commit_setup())

    (tmp_path / ".pre-commit-config.yaml").write_text(
        "- id: security\n  entry: python scripts/security/scan.py\n"
    )
    (tmp_path / "scripts" / "security").mkdir(parents=True)
    (tmp_path / "scripts" / "security" / "scan.py").write_text("")
    assert all(o.startswith("OK") for _, o in loop.pre_commit_setup())


def test_junit_totals_reads_a_testsuite_or_testsuites():
    suite = '<testsuite tests="7" failures="1" errors="0" skipped="2"></testsuite>'
    wrapped = f"<testsuites>{suite}{suite}</testsuites>"

    assert loop.junit_totals(suite) == (7, 1, 0, 2)
    assert loop.junit_totals(wrapped) == (14, 2, 0, 4)


def test_post_commit_checks_turn_artifacts_into_per_student_results(
    monkeypatch, tmp_path
):
    folder = release_reports(monkeypatch, tmp_path)
    (folder / "student-1-post-commit-testing-report.md").write_text("report")
    monkeypatch.setattr(loop, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(loop.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setenv("CI_BRANCH", "feature")
    monkeypatch.setattr(
        loop,
        "REGISTRY",
        [
            {"service": f"student-{n}", "ci": f"student-{n}-ci.yml"}
            for n in (1, 2, 3, 4)
        ],
    )
    sha = "abcdef123"  # pragma: allowlist secret - synthetic commit ID
    runs = {
        "student-1-ci.yml": [
            {"databaseId": 1, "status": "completed", "conclusion": "success",
             "headSha": sha}
        ],
        "student-2-ci.yml": [
            {"databaseId": 2, "status": "completed", "conclusion": "success",
             "headSha": sha}
        ],
        "student-3-ci.yml": [
            {"databaseId": 3, "status": "in_progress", "conclusion": "", "headSha": sha}
        ],
        "student-4-ci.yml": [],
    }  # fmt: skip

    def fake_gh(*args):
        if args[:2] == ("run", "list"):
            return FakeRun(json.dumps(runs[args[3]]))
        if "student-1-endpoint-test-evidence" in args:
            target = Path(args[args.index("--dir") + 1])
            target.mkdir(parents=True)
            (target / "student-1-endpoint-tests.xml").write_text(
                '<testsuite tests="7" failures="0" errors="0" skipped="0"/>'
            )
        return FakeRun()

    monkeypatch.setattr(loop, "gh", fake_gh)
    students = ["student-1", "student-2", "student-3", "student-4"]
    results = dict(loop.post_commit_checks(students))

    assert results["student-1 post-commit testing report"].startswith("OK")
    assert results["student-2 post-commit testing report"].startswith("FAIL")
    assert results["student-1 post-commit endpoint tests"].startswith("OK: 7 test(s)")
    assert (
        "no endpoint-test evidence" in results["student-2 post-commit endpoint tests"]
    )
    assert results["student-3 post-commit endpoint tests"].startswith("SKIP")
    assert results["student-4 post-commit endpoint tests"].startswith("FAIL: no run")


def test_post_commit_checks_fail_a_failing_endpoint_test(monkeypatch, tmp_path):
    release_reports(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(loop.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(loop, "REGISTRY", [{"service": "student-1", "ci": "s1.yml"}])
    run = {
        "databaseId": 9, "status": "completed", "conclusion": "failure",
        "headSha": "abcdef123",  # pragma: allowlist secret - synthetic commit ID
    }  # fmt: skip

    def fake_gh(*args):
        if args[:2] == ("run", "list"):
            return FakeRun(json.dumps([run]))
        target = Path(args[args.index("--dir") + 1])
        target.mkdir(parents=True)
        (target / "student-1-endpoint-tests.xml").write_text(
            '<testsuite tests="7" failures="2" errors="0" skipped="0"/>'
        )
        return FakeRun()

    monkeypatch.setattr(loop, "gh", fake_gh)
    results = dict(loop.post_commit_checks(["student-1"]))

    assert results["student-1 post-commit endpoint tests"].startswith(
        "FAIL: 7 test(s), 2"
    )


def test_latest_run_falls_back_to_main_when_the_branch_has_no_runs(monkeypatch):
    sha = "abcdef123"  # pragma: allowlist secret - synthetic commit ID
    run = {
        "databaseId": 7,
        "status": "completed",
        "conclusion": "success",
        "headSha": sha,
    }
    asked = []

    def fake_gh(*args):
        branch = args[args.index("--branch") + 1]
        asked.append(branch)
        return FakeRun(json.dumps([run] if branch == "main" else []))

    monkeypatch.setattr(loop, "gh", fake_gh)

    found, problem = loop.latest_run("student-1-ci.yml", "feature")
    assert (
        problem is None and found["branch"] == "main" and asked == ["feature", "main"]
    )

    monkeypatch.setattr(loop, "gh", lambda *_a: FakeRun("[]"))
    assert loop.latest_run("x.yml", "feature") == (
        None,
        "no run of x.yml on feature or main",
    )


def test_testing_mode_builds_two_titled_sections(monkeypatch, tmp_path):
    release_reports(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(loop.shutil, "which", lambda _name: None)
    monkeypatch.setattr(loop, "REGISTRY", [{"service": "student-2", "ci": "s2.yml"}])

    plan, sections = loop.run_testing()

    assert [title for title, _ in sections] == [
        "Pre-commit security",
        "Post-commit CI/CD endpoints",
    ]
    assert plan["checks"] and "student-2 pre-commit security report" in {
        c["label"] for c in plan["checks"]
    }


# ----------------------------------------------------------------- cloud mode

CLOUD_REPORT = """# TripGenie Cloud Deployment Report

Deployment Status: Success

Frontend URLs:

- https://shared-ui.example.io
- https://student-1-frontend.example.io

Validation Results:

| Check | Result | HTTP |
| --- | --- | --- |
| shared-ui loads | pass | 200 |
| Student 1 trip round trip | pass | 200 |

Security Configuration:

| Check | Result | Detail |
| --- | --- | --- |
| Only shared-ui and the frontends are public | pass | 5 public |
| Images pulled with a managed identity | pass |  |

AI-Mode, MCP, RAG and the Multi-Agent Server are not deployed; the cloud
profile turns every AI feature off.
"""


def test_cloud_report_checks_pass_a_clean_report():
    results = dict(loop.cloud_report_checks(CLOUD_REPORT))

    assert not [o for o in results.values() if o.startswith("FAIL")]
    assert results["frontend URLs reported"] == "OK: 2 URL(s)"
    assert results["smoke tests"] == "OK: 2 of 2 passed"


def test_cloud_report_checks_name_the_failed_rows():
    bad = (
        CLOUD_REPORT.replace("Success", "Failed")
        .replace("round trip | pass |", "round trip | FAIL |")
        .replace("managed identity | pass |", "managed identity | FAIL |")
        .replace("are not deployed", "run in the cloud")
    )  # fmt: skip
    results = dict(loop.cloud_report_checks(bad))

    assert results["deployment status"] == "FAIL: Failed"
    assert "Student 1 trip round trip" in results["smoke tests"]
    assert "managed identity" in results["security configuration"]
    assert results["AI services not deployed"].startswith("FAIL")


def test_cloud_report_checks_flag_an_empty_report():
    results = dict(loop.cloud_report_checks("# nothing here"))

    assert results["deployment status"] == "FAIL: not stated"
    assert results["smoke tests"].startswith("FAIL")
    assert results["frontend URLs reported"].startswith("FAIL")


def test_cloud_profile_must_turn_every_ai_switch_off(monkeypatch, tmp_path):
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    assert loop.cloud_profile_check()[1].startswith("FAIL: .env.cloud missing")

    profile = tmp_path / "shared" / "configuration"
    profile.mkdir(parents=True)
    env = profile / ".env.cloud"
    env.write_text(
        "# note\nSTUDENT1_BACKEND_RAG_ENABLED=false\nSTUDENT2_BACKEND_RAG_URL=\n"
    )
    assert loop.cloud_profile_check()[1].startswith("OK")

    env.write_text(
        "STUDENT3_BACKEND_MCP_ENABLED=true\nSTUDENT2_BACKEND_AI_MODE_URL=http://x\n"
    )
    outcome = loop.cloud_profile_check()[1]
    assert "STUDENT3_BACKEND_MCP_ENABLED" in outcome
    assert "STUDENT2_BACKEND_AI_MODE_URL" in outcome


def test_cloud_static_checks_need_identity_and_the_production_gate(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    (tmp_path / "scripts" / "deploy" / "azure").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    plan = {"required_files": ["scripts/deploy/azure/deploy-azure.sh"]}

    missing = dict(loop.cloud_static_checks(plan))
    assert missing["file scripts/deploy/azure/deploy-azure.sh"] == "FAIL: missing"
    assert missing["images pulled with a managed identity"].startswith("FAIL")
    assert missing["human release gate (production environment)"].startswith("FAIL")

    (tmp_path / "scripts/deploy/azure/deploy-azure.sh").write_text(
        "az containerapp create --registry-identity $ID"
    )
    (tmp_path / ".github/workflows/cloud-deployment.yml").write_text(
        "    environment: production\n"
    )
    ok = dict(loop.cloud_static_checks(plan))
    assert ok["images pulled with a managed identity"].startswith("OK")
    assert ok["human release gate (production environment)"].startswith("OK")


def test_cloud_report_falls_back_to_the_committed_copy(monkeypatch, tmp_path):
    folder = release_reports(monkeypatch, tmp_path)
    monkeypatch.setattr(loop.shutil, "which", lambda _name: None)
    assert loop.cloud_report_text() == (None, None)

    (folder / "cloud-deployment-results.md").write_text(CLOUD_REPORT)
    text, source = loop.cloud_report_text()
    assert text == CLOUD_REPORT and "committed" in source


def test_cloud_report_prefers_the_latest_workflow_artifact(monkeypatch, tmp_path):
    release_reports(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(loop.shutil, "which", lambda _name: "/usr/bin/gh")
    run = {
        "databaseId": 5, "status": "completed", "conclusion": "success",
        "headSha": "abcdef123",  # pragma: allowlist secret - synthetic commit ID
    }  # fmt: skip

    def fake_gh(*args):
        if args[:2] == ("run", "list"):
            return FakeRun(json.dumps([run]))
        target = Path(args[args.index("--dir") + 1])
        target.mkdir(parents=True)
        (target / "cloud-deployment-results.md").write_text("from the artifact")
        return FakeRun()

    monkeypatch.setattr(loop, "gh", fake_gh)

    assert loop.cloud_report_text() == ("from the artifact", "run 5 artifact")
    assert loop.cloud_workflow_check()[1].startswith("OK: success, run 5")


def test_cloud_run_id_pins_the_run_to_review(monkeypatch, tmp_path):
    release_reports(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(loop.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setenv("CLOUD_RUN_ID", "111")
    sha = "abcdef123"  # pragma: allowlist secret - synthetic commit ID
    run = {"databaseId": 111, "status": "completed", "conclusion": "success",
           "headSha": sha, "headBranch": "main"}  # fmt: skip
    calls = []

    def fake_gh(*args):
        calls.append(args)
        if args[:2] == ("run", "view"):
            return FakeRun(json.dumps(run))
        target = Path(args[args.index("--dir") + 1])
        target.mkdir(parents=True)
        (target / "cloud-deployment-results.md").write_text("old good report")
        return FakeRun()

    monkeypatch.setattr(loop, "gh", fake_gh)

    assert loop.cloud_report_text() == ("old good report", "run 111 artifact")
    assert loop.cloud_workflow_check()[1] == "OK: success, run 111 at abcdef1 on main"
    assert not [c for c in calls if c[:2] == ("run", "list")]

    monkeypatch.setattr(loop, "gh", lambda *_a: FakeRun("", returncode=1))
    assert loop.cloud_run()[1].startswith("gh run view 111")


def test_cloud_mode_reports_a_missing_report_without_crashing(monkeypatch, tmp_path):
    release_reports(monkeypatch, tmp_path)
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(loop.shutil, "which", lambda _name: None)
    monkeypatch.delenv("CLOUD_URL", raising=False)

    plan, sections = loop.run_cloud()
    results = dict(loop.flatten(sections))

    assert results["Deployment report / cloud deployment report"].startswith("FAIL")
    assert results[
        "Configuration and release gate / cloud-deployment.yml latest run"
    ] == ("SKIP: gh CLI unavailable")
    assert plan["checks"]


def test_cloud_probe_checks_the_deployed_frontend(monkeypatch):
    monkeypatch.setattr(loop.requests, "get", lambda *_a, **_k: FakeResponse(200))
    assert loop.cloud_probe("https://app.example.io")[1] == "OK: HTTP 200"

    monkeypatch.setattr(loop.requests, "get", lambda *_a, **_k: FakeResponse(503))
    assert loop.cloud_probe("https://app.example.io")[1] == "FAIL: HTTP 503"


def test_release_decision_is_ready_only_when_accepted_with_clean_checks():
    assert loop.release_decision("Accept", []) == "READY"
    assert (
        loop.release_decision("Accept", ["x: FAIL"]) == "NOT READY (1 failed check(s))"
    )
    assert loop.release_decision("Reject", []) == "NOT READY (Reject)"
    assert loop.release_decision("Partially Accept", []).startswith("NOT READY")
    assert loop.release_decision("Deferred (non-interactive run)", []).startswith(
        "PENDING"
    )


def test_testing_and_cloud_are_selectable_and_write_committed_logs(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "6")
    assert loop.choose_mode() == "testing"
    monkeypatch.setattr("builtins.input", lambda _prompt="": "7")
    assert loop.choose_mode() == "cloud"
    for mode in ("testing", "cloud"):
        assert mode in loop.RUNNERS and mode in loop.COMMITTED_LOG_MODES
