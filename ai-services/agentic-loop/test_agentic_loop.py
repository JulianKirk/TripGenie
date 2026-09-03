import agentic_loop as loop


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
