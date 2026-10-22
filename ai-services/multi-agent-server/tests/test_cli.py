"""The terminal interface drives the same HTTP workflow as a feature backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from conftest import TRANSPORT_B, FakeAiMode, generation, tool_trace
from fastapi.testclient import TestClient
from multi_agent_service import cli
from multi_agent_service.app import create_app
from multi_agent_service.client import MultiAgentClient

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from multi_agent_service.config import Settings


@pytest.fixture
def server(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Point the CLI's client at an in-process server, polling quickly."""
    # The CLI's own terminal schema: an answer plus grounded items.
    terminal_result = {
        "answer": "Take the Spirit of Tasmania ferry from Geelong.",
        "items": [{"id": TRANSPORT_B, "reason": "Only route to Tasmania."}],
    }
    fake = FakeAiMode(
        worker=[lambda _: generation(terminal_result, [tool_trace()])],
    )
    app = create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    with TestClient(app) as test_client:

        class InProcessClient(MultiAgentClient):
            def __init__(self, base_url: str, **_: object) -> None:
                super().__init__("http://testserver")
                self._client.close()
                # TestClient is an httpx.Client bound to the in-process app.
                self._client = test_client

            def close(self) -> None:
                """The fixture owns the TestClient's lifetime."""

            def wait(self, run_id: str, **kwargs: object) -> dict:
                return super().wait(run_id, poll_seconds=0.02, **kwargs)

        monkeypatch.setattr(cli, "MultiAgentClient", InProcessClient)
        yield test_client


def _run_cli(*args: str) -> int:
    return cli.main(list(args))


def test_run_streams_every_stage_and_records_the_decision(
    server: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli(
        "run",
        "--feature",
        "student-3",
        "--task",
        "Cheapest way to Tasmania for four?",
        "--decision",
        "approve",
        "--reviewer",
        "ronit",
        "--notes",
        "ok",
    )

    out = capsys.readouterr().out
    assert code == 0
    for marker in (
        "[PLANNER · attempt 1] completed",
        "[WORKER · attempt 1] completed",
        "tool transport_search success",
        "check PASS grounding",
        "[REVIEWER · attempt 1] completed",
        "verdict: approve",
        "HUMAN REVIEW",
        "HUMAN DECISION: approve by ronit",
        "status: completed",
    ):
        assert marker in out, marker


def test_run_can_stop_at_human_review_and_review_later(
    server: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run_cli("run", "--feature", "student-3", "--task", "t", "--no-review") == 0
    run_id = server.get("/runs").json()["data"][0]["run_id"]
    assert "status: awaiting_human" in capsys.readouterr().out

    code = _run_cli("review", run_id, "--decision", "reject", "--reviewer", "ronit")

    assert code == 0
    assert "status: rejected" in capsys.readouterr().out


def test_without_a_terminal_or_decision_the_run_is_left_for_review(
    server: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli("run", "--feature", "student-3", "--task", "t")

    assert code == 0
    assert "run stays awaiting_human" in capsys.readouterr().out


def test_list_show_and_export(
    server: TestClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_cli("run", "--feature", "student-3", "--task", "t", "--no-review")
    run_id = server.get("/runs").json()["data"][0]["run_id"]
    capsys.readouterr()

    assert _run_cli("list", "--feature", "student-3") == 0
    assert run_id in capsys.readouterr().out
    assert _run_cli("show", run_id) == 0
    assert '"status": "awaiting_human"' in capsys.readouterr().out

    output = tmp_path / "audit.md"
    assert _run_cli("export", run_id, "--output", str(output)) == 0
    assert "## Coordination and audit log" in output.read_text(encoding="utf-8")


def test_server_errors_are_reported_with_their_code(
    server: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli("show", "magent_000000000000")

    assert code == 1
    assert "RUN_NOT_FOUND" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("feature", "id_keys"),
    [
        ("student-3", ["id"]),
        ("student-5", ["budget_id", "expense_id", "trip_id", "item_id"]),
    ],
)
def test_terminal_grounding_uses_each_feature_id_keys(
    monkeypatch: pytest.MonkeyPatch, feature: str, id_keys: list[str]
) -> None:
    sent: list[dict] = []

    class RecordingClient:
        def start_run(self, body: dict) -> dict:
            sent.append(body)
            return {"run_id": "magent_000000000001", "correlation_id": "c"}

        def wait(self, run_id: str, **_: object) -> dict:
            return {"status": "failed"}

    monkeypatch.setattr(cli, "_StepPrinter", lambda: None)
    arguments = cli._parser().parse_args(
        ["run", "--feature", feature, "--task", "t", "--no-review"]
    )

    cli._run(RecordingClient(), arguments)  # type: ignore[arg-type]

    assert sent[0]["grounding"]["id_keys"] == id_keys


def test_failed_checks_are_shown_before_the_human_decides(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ungrounded = {"answer": "A train.", "items": [{"id": "TRN12345", "reason": "x"}]}
    fake = FakeAiMode(worker=[lambda _: generation(ungrounded, [])])
    app = create_app(settings, ai_mode_transport=httpx.MockTransport(fake.handle))
    with TestClient(app) as test_client:

        class InProcessClient(MultiAgentClient):
            def __init__(self, base_url: str, **_: object) -> None:
                super().__init__("http://testserver")
                self._client.close()
                self._client = test_client

            def close(self) -> None:
                """The test owns the TestClient's lifetime."""

            def wait(self, run_id: str, **kwargs: object) -> dict:
                return super().wait(run_id, poll_seconds=0.02, **kwargs)

        monkeypatch.setattr(cli, "MultiAgentClient", InProcessClient)
        code = _run_cli(
            "run",
            "--feature",
            "student-3",
            "--task",
            "t",
            "--decision",
            "reject",
            "--reviewer",
            "ronit",
        )

    out = capsys.readouterr().out
    assert code == 0
    assert "warning: check tool_evidence failed" in out
    assert "warning: check grounding failed: ids no successful student-3" in out
    assert "TRN12345" in out
    assert "status: rejected" in out


def test_a_terminal_with_nothing_to_read_does_not_crash_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_input(_: str) -> str:
        raise EOFError

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", no_input)

    assert cli._ask("Notes: ") is None
