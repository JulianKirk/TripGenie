"""Workflow history and audit log, in one local SQLite file.

The first read/write store in a host service, so concurrency is explicit:
WAL journaling lets reads proceed during a write, and every write goes
through one lock. Runs are small (bounded by the request limits), so a single
writer is never the bottleneck. The audit log is append-only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .models import ACTIVE_STATUSES, HistoryEvent, RunSummary, StoredRun

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    feature TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_feature_created ON runs (feature, created_at);
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs (run_id),
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events (run_id, sequence);
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


class StoreError(Exception):
    pass


class RunStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            # Retire the old caller catalogue from persisted requests as well
            # as the public schema. Keep all other history and audit data.
            rows = connection.execute(
                "SELECT run_id, record FROM runs WHERE instr(record, ?) > 0",
                ('"allowed_tools"',),
            ).fetchall()
            for row in rows:
                record = json.loads(row["record"])
                request = record.get("request")
                if isinstance(request, dict) and "allowed_tools" in request:
                    del request["allowed_tools"]
                    connection.execute(
                        "UPDATE runs SET record = ? WHERE run_id = ?",
                        (json.dumps(record), row["run_id"]),
                    )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @property
    def path(self) -> Path:
        return self._path

    def ping(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("SELECT 1 FROM runs LIMIT 1").fetchall()
        except sqlite3.Error as exc:
            raise StoreError(str(exc)) from exc

    # --------------------------------------------------------------- writes

    def save(self, run: StoredRun, *, insert: bool = False) -> None:
        values = (
            run.feature,
            run.status,
            run.created_at.isoformat(),
            run.updated_at.isoformat(),
            run.model_dump_json(),
            run.run_id,
        )
        with self._lock, closing(self._connect()) as connection:
            if insert:
                connection.execute(
                    "INSERT INTO runs (feature, status, created_at, updated_at, "
                    "record, run_id) VALUES (?, ?, ?, ?, ?, ?)",
                    values,
                )
            else:
                connection.execute(
                    "UPDATE runs SET feature = ?, status = ?, created_at = ?, "
                    "updated_at = ?, record = ? WHERE run_id = ?",
                    values,
                )
            connection.commit()

    def add_event(
        self,
        run_id: str,
        actor: str,
        event: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO events (run_id, at, actor, event, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    utc_now().isoformat(),
                    actor,
                    event,
                    json.dumps(detail or {}, sort_keys=True),
                ),
            )
            connection.commit()

    def fail_interrupted(self) -> list[str]:
        """Runs left mid-flight by a previous process can never finish.

        Marking them failed at start-up keeps the history honest instead of
        showing a run as 'working' forever.
        """
        interrupted: list[str] = []
        for run in self._load_where("status IN (?, ?, ?)", tuple(ACTIVE_STATUSES)):
            run.status = "failed"
            run.updated_at = utc_now()
            run.error = {
                "code": "RUN_INTERRUPTED",
                "message": "The server restarted before this run finished.",
            }
            self.save(run)
            self.add_event(run.run_id, "system", "run_failed", run.error)
            interrupted.append(run.run_id)
        return interrupted

    # ---------------------------------------------------------------- reads

    def get(self, run_id: str) -> StoredRun | None:
        runs = self._load_where("run_id = ?", (run_id,))
        return runs[0] if runs else None

    def list_runs(
        self,
        *,
        feature: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[RunSummary]:
        clauses: list[str] = []
        params: list[object] = []
        if feature is not None:
            clauses.append("feature = ?")
            params.append(feature)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = " AND ".join(clauses) or "1 = 1"
        runs = self._load_where(
            where + " ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [
            RunSummary(
                run_id=run.run_id,
                feature=run.feature,
                task=run.task,
                status=run.status,
                created_at=run.created_at,
                updated_at=run.updated_at,
                verdict=run.review.verdict if run.review else None,
                decision=run.human.decision if run.human else None,
            )
            for run in runs
        ]

    def count_active(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE status IN (?, ?, ?)",
                tuple(ACTIVE_STATUSES),
            ).fetchone()
        return int(row[0])

    def events(self, run_id: str) -> list[HistoryEvent]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT sequence, run_id, at, actor, event, detail FROM events "
                "WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [
            HistoryEvent(
                sequence=row["sequence"],
                run_id=row["run_id"],
                at=datetime.fromisoformat(row["at"]),
                actor=row["actor"],
                event=row["event"],
                detail=json.loads(row["detail"]),
            )
            for row in rows
        ]

    def _load_where(self, where: str, params: tuple[object, ...]) -> list[StoredRun]:
        # `where` is always one of this module's own constant clauses; every
        # caller-supplied value is a bound parameter.
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT record FROM runs WHERE " + where,  # noqa: S608
                params,
            ).fetchall()
        return [StoredRun.model_validate_json(row["record"]) for row in rows]
