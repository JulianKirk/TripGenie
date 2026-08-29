from __future__ import annotations

import sqlite3
import threading
from time import perf_counter

import pytest
from database_service.app import create_app
from database_service.config import Settings
from database_service.errors import ApiError
from database_service.models import (
    ItineraryItemCreate,
    ItineraryItemUpdate,
    TripCreate,
    TripUpdate,
)
from database_service.repository import (
    SEED_MARKER_COMPLETED,
    SEED_MARKER_KEY,
    SEED_MARKER_SKIPPED_EXISTING_DATA,
    DatabaseService,
)
from fastapi.testclient import TestClient

LEGACY_SCHEMA_SQL = """
CREATE TABLE trips (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    destination TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    traveller_count INTEGER NOT NULL CHECK (traveller_count > 0),
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'planned', 'active', 'completed', 'cancelled')
    ),
    notes TEXT,
    CHECK (start_date <= end_date)
);

CREATE TABLE itinerary_items (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    title TEXT NOT NULL,
    location TEXT,
    description TEXT,
    category TEXT NOT NULL CHECK (
        category IN ('accommodation', 'transport', 'activity', 'meal', 'note', 'other')
    ),
    notes TEXT,
    CHECK (start_time IS NULL OR end_time IS NULL OR start_time < end_time)
);
"""


def create_trip_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Canberra Planning Sprint",
        "destination": "Canberra",
        "start_date": "2027-05-01",
        "end_date": "2027-05-04",
        "traveller_count": 2,
        "status": "planned",
        "notes": "Need a mix of museums and cafes.",
    }
    payload.update(overrides)
    return payload


def create_item_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "date": "2027-05-02",
        "start_time": "09:00",
        "end_time": "10:30",
        "title": "Museum Visit",
        "location": "National Museum of Australia",
        "description": "Start with the main collection.",
        "category": "activity",
        "notes": "Book tickets online.",
    }
    payload.update(overrides)
    return payload


def _schema_metadata_value(database_path, key: str) -> str | None:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = ?",
            (key,),
        ).fetchone()

    return None if row is None else str(row[0])


def test_reinitialisation_does_not_restore_deleted_seed_trip(
    service: DatabaseService,
) -> None:
    service.initialize()

    service.delete_trip("trip_2026_melbourne_food_trail")
    service.initialize()

    with pytest.raises(ApiError) as excinfo:
        service.get_trip("trip_2026_melbourne_food_trail")

    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "NOT_FOUND"


def test_reinitialisation_preserves_deleted_seed_item_and_narrowed_trip_window(
    service: DatabaseService,
) -> None:
    service.initialize()

    service.delete_itinerary_item("item_2026_sydney_harbour_walk")
    updated_trip = service.update_trip(
        "trip_2026_sydney_long_weekend",
        TripUpdate.model_validate({"start_date": "2026-10-04"}),
    )
    assert updated_trip["start_date"] == "2026-10-04"

    service.initialize()

    reloaded_trip = service.get_trip("trip_2026_sydney_long_weekend")
    reloaded_items = service.list_itinerary_items("trip_2026_sydney_long_weekend")

    assert reloaded_trip["start_date"] == "2026-10-04"
    assert reloaded_items == []


class FailingSeedDatabaseService(DatabaseService):
    def _seed_itinerary_items(self, connection: sqlite3.Connection) -> None:
        raise RuntimeError("simulated seed failure")


def test_failed_initialisation_does_not_leave_false_seed_marker(
    database_path,
) -> None:
    settings = Settings(sqlite_path=database_path)
    service = FailingSeedDatabaseService(settings)

    with pytest.raises(RuntimeError, match="simulated seed failure"):
        service.initialize()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            ).fetchall()
        }
        marker = (
            connection.execute(
                "SELECT value FROM schema_metadata WHERE key = ?",
                (SEED_MARKER_KEY,),
            ).fetchone()
            if "schema_metadata" in tables
            else None
        )
        trip_count = (
            connection.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
            if "trips" in tables
            else 0
        )
        item_count = (
            connection.execute(
                "SELECT COUNT(*) FROM itinerary_items",
            ).fetchone()[0]
            if "itinerary_items" in tables
            else 0
        )

    assert marker is None
    assert trip_count == 0
    assert item_count == 0

    recovered_service = DatabaseService(settings)
    recovered_service.initialize()

    assert (
        _schema_metadata_value(database_path, SEED_MARKER_KEY)
        == SEED_MARKER_COMPLETED
    )


def test_existing_non_empty_legacy_database_is_marked_without_reseeding(
    database_path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(LEGACY_SCHEMA_SQL)
        connection.execute(
            """
            INSERT INTO trips (
                id,
                name,
                destination,
                start_date,
                end_date,
                traveller_count,
                status,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trip_existing_user_01",
                "Existing User Trip",
                "Perth",
                "2027-04-01",
                "2027-04-03",
                1,
                "draft",
                "Preserve this row.",
            ),
        )
        connection.execute(
            """
            INSERT INTO itinerary_items (
                id,
                trip_id,
                date,
                start_time,
                end_time,
                title,
                location,
                description,
                category,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "item_existing_user_01",
                "trip_existing_user_01",
                "2027-04-02",
                "09:00",
                "10:00",
                "Coffee Catch-up",
                "Perth CBD",
                "Keep this user-created item.",
                "meal",
                None,
            ),
        )
        connection.commit()

    service = DatabaseService(Settings(sqlite_path=database_path))
    service.initialize()

    with sqlite3.connect(database_path) as connection:
        trip_ids = {
            row[0]
            for row in connection.execute(
                "SELECT id FROM trips ORDER BY id",
            ).fetchall()
        }
        item_ids = {
            row[0]
            for row in connection.execute(
                "SELECT id FROM itinerary_items ORDER BY id",
            ).fetchall()
        }

    assert trip_ids == {"trip_existing_user_01"}
    assert item_ids == {"item_existing_user_01"}
    assert (
        _schema_metadata_value(database_path, SEED_MARKER_KEY)
        == SEED_MARKER_SKIPPED_EXISTING_DATA
    )


def _assert_thread_successes(errors: list[BaseException]) -> None:
    if errors:
        raise errors[0]


def test_trip_patch_serialises_concurrent_updates_and_preserves_both_changes(
    service: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.initialize()
    trip = service.create_trip(
        TripCreate.model_validate(create_trip_payload(id="trip_concurrent_trip_01")),
    )
    trip_id = str(trip["id"])

    first_read_ready = threading.Event()
    release_first_read = threading.Event()
    second_started = threading.Event()
    second_read_reached = threading.Event()
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    original_get_trip_row = DatabaseService._get_trip_row

    def controlled_get_trip_row(self, connection, current_trip_id):
        row = original_get_trip_row(self, connection, current_trip_id)
        if current_trip_id != trip_id:
            return row

        thread_name = threading.current_thread().name
        if thread_name == "trip-update-first":
            first_read_ready.set()
            assert release_first_read.wait(timeout=2)
        elif thread_name == "trip-update-second":
            second_read_reached.set()

        return row

    monkeypatch.setattr(DatabaseService, "_get_trip_row", controlled_get_trip_row)

    def run_update(
        payload: dict[str, object],
        *,
        started: threading.Event | None = None,
    ) -> None:
        try:
            if started is not None:
                started.set()
            service.update_trip(trip_id, TripUpdate.model_validate(payload))
        except BaseException as exc:  # pragma: no cover - surfaced below
            with errors_lock:
                errors.append(exc)

    first_thread = threading.Thread(
        target=run_update,
        name="trip-update-first",
        args=({"destination": "Canberra Region"},),
    )
    second_thread = threading.Thread(
        target=run_update,
        name="trip-update-second",
        args=({"notes": "Updated by a second concurrent patch."},),
        kwargs={"started": second_started},
    )

    first_thread.start()
    assert first_read_ready.wait(timeout=2)

    second_thread.start()
    assert second_started.wait(timeout=2)
    assert not second_read_reached.wait(timeout=0.5)

    release_first_read.set()

    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    _assert_thread_successes(errors)

    updated_trip = service.get_trip(trip_id)
    assert updated_trip["destination"] == "Canberra Region"
    assert updated_trip["notes"] == "Updated by a second concurrent patch."


def test_item_patch_serialises_concurrent_updates_and_preserves_both_changes(
    service: DatabaseService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.initialize()
    trip_id = "trip_concurrent_item_01"
    item_id = "item_concurrent_item_01"
    service.create_trip(TripCreate.model_validate(create_trip_payload(id=trip_id)))
    service.create_itinerary_item(
        trip_id,
        ItineraryItemCreate.model_validate(
            create_item_payload(id=item_id, date="2027-05-02"),
        ),
    )

    first_read_ready = threading.Event()
    release_first_read = threading.Event()
    second_started = threading.Event()
    second_read_reached = threading.Event()
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    original_get_item_row = DatabaseService._get_item_row

    def controlled_get_item_row(self, connection, current_item_id):
        row = original_get_item_row(self, connection, current_item_id)
        if current_item_id != item_id:
            return row

        thread_name = threading.current_thread().name
        if thread_name == "item-update-first":
            first_read_ready.set()
            assert release_first_read.wait(timeout=2)
        elif thread_name == "item-update-second":
            second_read_reached.set()

        return row

    monkeypatch.setattr(DatabaseService, "_get_item_row", controlled_get_item_row)

    def run_update(
        payload: dict[str, object],
        *,
        started: threading.Event | None = None,
    ) -> None:
        try:
            if started is not None:
                started.set()
            service.update_itinerary_item(
                item_id,
                ItineraryItemUpdate.model_validate(payload),
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            with errors_lock:
                errors.append(exc)

    first_thread = threading.Thread(
        target=run_update,
        name="item-update-first",
        args=({"title": "Museum Visit and Gardens"},),
    )
    second_thread = threading.Thread(
        target=run_update,
        name="item-update-second",
        args=({"notes": "Bring the printed booking confirmation."},),
        kwargs={"started": second_started},
    )

    first_thread.start()
    assert first_read_ready.wait(timeout=2)

    second_thread.start()
    assert second_started.wait(timeout=2)
    assert not second_read_reached.wait(timeout=0.5)

    release_first_read.set()

    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    _assert_thread_successes(errors)

    updated_item = service.get_itinerary_item(item_id)
    assert updated_item["title"] == "Museum Visit and Gardens"
    assert updated_item["notes"] == "Bring the printed booking confirmation."


def test_patch_returns_busy_error_with_bounded_timeout(database_path) -> None:
    settings = Settings(
        sqlite_path=database_path,
        sqlite_timeout_seconds=0.1,
    )
    setup_service = DatabaseService(settings)
    setup_service.initialize()
    setup_service.create_trip(
        TripCreate.model_validate(create_trip_payload(id="trip_busy_patch_01")),
    )

    with TestClient(create_app(settings)) as client:
        with sqlite3.connect(database_path, timeout=0.1) as locker:
            locker.execute("PRAGMA foreign_keys = ON")
            locker.execute("PRAGMA busy_timeout = 100")
            locker.execute("BEGIN IMMEDIATE")

            started_at = perf_counter()
            response = client.patch(
                "/internal/trips/trip_busy_patch_01",
                json={"notes": "This write should fail fast while the DB is locked."},
            )
            elapsed = perf_counter() - started_at

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "DATABASE_BUSY",
            "message": (
                "The database is busy processing another write request. Please retry."
            ),
            "details": [],
        },
    }
    assert elapsed < 1
