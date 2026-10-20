"""The workflow history survives restarts, and is honest about lost runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from conftest import FakeAiMode, start_and_settle
from fastapi.testclient import TestClient
from multi_agent_service.app import create_app
from multi_agent_service.models import RunRequest, StoredRun
from multi_agent_service.store import RunStore, utc_now

if TYPE_CHECKING:
    from pathlib import Path

    from multi_agent_service.config import Settings


def _stored(run_id: str, status: str) -> StoredRun:
    now = utc_now()
    return StoredRun(
        run_id=run_id,
        feature="student-3",
        task="t",
        correlation_id="c",
        status=status,
        created_at=now,
        updated_at=now,
        request=RunRequest(
            feature="student-3",
            task="t",
            worker_system="w",
            output_schema={"type": "object"},
        ),
    )


def test_runs_and_history_survive_a_restart(settings: Settings) -> None:
    fake = FakeAiMode()
    transport = httpx.MockTransport(fake.handle)
    with TestClient(create_app(settings, ai_mode_transport=transport)) as client:
        run = start_and_settle(client)

    with TestClient(create_app(settings, ai_mode_transport=transport)) as client:
        reloaded = client.get(f"/runs/{run['run_id']}").json()["data"]
        events = client.get(f"/runs/{run['run_id']}/history").json()["data"]
        approved = client.post(
            f"/runs/{run['run_id']}/review",
            json={"decision": "approve", "reviewer": "ronit"},
        )

    assert reloaded["status"] == "awaiting_human"
    assert reloaded["steps"] == run["steps"]
    assert events[-1]["event"] == "awaiting_human"
    assert approved.status_code == 200


def test_runs_cut_off_by_a_restart_are_marked_failed(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    for run_id, status in [
        ("magent_000000000001", "working"),
        ("magent_000000000002", "awaiting_human"),
        ("magent_000000000003", "completed"),
    ]:
        store.save(_stored(run_id, status), insert=True)

    interrupted = RunStore(tmp_path / "runs.sqlite3").fail_interrupted()

    assert interrupted == ["magent_000000000001"]
    run = store.get("magent_000000000001")
    assert run is not None
    assert run.status == "failed"
    assert run.error == {
        "code": "RUN_INTERRUPTED",
        "message": "The server restarted before this run finished.",
    }
    assert store.get("magent_000000000002").status == "awaiting_human"
    assert store.events("magent_000000000001")[-1].event == "run_failed"


def test_the_store_uses_write_ahead_logging(tmp_path: Path) -> None:
    import sqlite3
    from contextlib import closing

    path = tmp_path / "runs.sqlite3"
    RunStore(path)

    with closing(sqlite3.connect(path)) as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode == "wal"
