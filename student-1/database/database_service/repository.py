from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .config import Settings
from .errors import (
    ApiError,
    conflict,
    database_busy,
    internal_error,
    not_found,
    validation_error,
)
from .models import (
    ItineraryCategory,
    ItineraryItemCreate,
    ItineraryItemRecord,
    ItineraryItemUpdate,
    TripAccommodationRecord,
    TripActivityRecord,
    TripCreate,
    TripRecord,
    TripStatus,
    TripUpdate,
)
from .seed_data import SEED_ITINERARY_ITEMS, SEED_TRIPS

TRIP_FIELDS = (
    "id",
    "name",
    "destination",
    "start_date",
    "end_date",
    "traveller_count",
    "status",
    "notes",
)
ITEM_FIELDS = (
    "id",
    "trip_id",
    "date",
    "start_time",
    "end_time",
    "title",
    "location",
    "description",
    "category",
    "notes",
)

TRIP_ACCOMMODATION_FIELDS = (
    "trip_id",
    "accommodation_id",
    "date",
    "check_in_time",
    "check_out",
    "check_out_time",
)

TRIP_ACTIVITY_FIELDS = (
    "trip_id",
    "activity_id",
    "date",
    "start_time",
)

SEED_MARKER_KEY = "student1_demo_seed_v1"
SEED_MARKER_COMPLETED = "completed"
SEED_MARKER_SKIPPED_EXISTING_DATA = "skipped-existing-data"

SCHEMA_STATEMENTS = (
    """
CREATE TABLE IF NOT EXISTS trips (
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
)
""",
    """
CREATE TABLE IF NOT EXISTS itinerary_items (
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
)
""",
    """
CREATE TABLE IF NOT EXISTS trip_accommodations (
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    accommodation_id TEXT NOT NULL,
    -- The stay window. `date` is the check-in, named that way since before
    -- there was a check-out to pair it with; renaming it is a table rebuild
    -- for no user-visible gain. NULL check_out means no departure recorded,
    -- which is what every row written before stay dates existed carries.
    date TEXT NOT NULL,
    check_in_time TEXT,
    check_out TEXT,
    check_out_time TEXT,
    -- ponytail: no CHECK on the ordering. ALTER TABLE ADD COLUMN cannot add
    -- one, so a fresh database would enforce it and a migrated database
    -- would not. TripAccommodationRecord validates it on both paths instead.
    PRIMARY KEY (trip_id, accommodation_id)
)
""",
    """
CREATE TABLE IF NOT EXISTS trip_activities (
    trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    activity_id TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT,
    PRIMARY KEY (trip_id, activity_id)
)
""",
    """
CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""",
    """
CREATE INDEX IF NOT EXISTS idx_trips_status_start_date
    ON trips (status, start_date)
""",
    """
CREATE INDEX IF NOT EXISTS idx_itinerary_items_trip_date
    ON itinerary_items (trip_id, date)
""",
    """
CREATE INDEX IF NOT EXISTS idx_itinerary_items_trip_category_date
    ON itinerary_items (trip_id, category, date)
""",
    # The reverse lookup -- "which trips hold this accommodation?" -- is what
    # the accommodation service's picker asks on every open, and the primary
    # key indexes the other direction only.
    """
CREATE INDEX IF NOT EXISTS idx_trip_accommodations_accommodation
    ON trip_accommodations (accommodation_id)
""",
    """
CREATE INDEX IF NOT EXISTS idx_trip_activities_activity
    ON trip_activities (activity_id)
""",
)

INSERT_TRIP_SQL = """
INSERT INTO trips (
    id,
    name,
    destination,
    start_date,
    end_date,
    traveller_count,
    status,
    notes
) VALUES (
    :id,
    :name,
    :destination,
    :start_date,
    :end_date,
    :traveller_count,
    :status,
    :notes
)
"""

UPDATE_TRIP_SQL = """
UPDATE trips
SET
    name = :name,
    destination = :destination,
    start_date = :start_date,
    end_date = :end_date,
    traveller_count = :traveller_count,
    status = :status,
    notes = :notes
WHERE id = :id
"""

INSERT_ITEM_SQL = """
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
) VALUES (
    :id,
    :trip_id,
    :date,
    :start_time,
    :end_time,
    :title,
    :location,
    :description,
    :category,
    :notes
)
"""

UPDATE_ITEM_SQL = """
UPDATE itinerary_items
SET
    date = :date,
    start_time = :start_time,
    end_time = :end_time,
    title = :title,
    location = :location,
    description = :description,
    category = :category,
    notes = :notes
WHERE id = :id
"""


class DatabaseService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
        database_path = self.settings.sqlite_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database_path,
            timeout=self.settings.sqlite_timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            f"PRAGMA busy_timeout = {int(self.settings.sqlite_timeout_seconds * 1000)}",
        )

        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_transaction(self, connection: sqlite3.Connection):
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise self._translate_operational_error(exc) from exc

        try:
            yield
        except Exception as exc:
            connection.rollback()
            if isinstance(exc, sqlite3.OperationalError):
                raise self._translate_operational_error(exc) from exc
            raise
        else:
            try:
                connection.commit()
            except sqlite3.OperationalError as exc:
                connection.rollback()
                raise self._translate_operational_error(exc) from exc

    def initialize(self) -> None:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._ensure_schema(connection)
                if self.settings.seed_data:
                    self._ensure_seed_data(connection)

    def health(self) -> dict[str, str]:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

        return {
            "status": "ok",
            "service": self.settings.service_name,
            "sqlite_path": str(self.settings.sqlite_path),
        }

    def list_trips(
        self,
        *,
        status: TripStatus | None = None,
        destination: str | None = None,
    ) -> list[dict[str, object]]:
        sql = f"SELECT {', '.join(TRIP_FIELDS)} FROM trips"
        conditions: list[str] = []
        params: list[object] = []

        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)

        if destination:
            conditions.append("LOWER(destination) = LOWER(?)")
            params.append(destination)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY start_date ASC, name COLLATE NOCASE ASC, id ASC"

        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()

        return [self._serialise_trip(row) for row in rows]

    def create_trip(self, payload: TripCreate) -> dict[str, object]:
        record = payload.model_dump(mode="json")
        record["id"] = record.get("id") or self._generate_id("trip")
        self._validate_trip_record(record)
        self._normalise_empty_payload(record)

        with self._connect() as connection:
            try:
                with self._write_transaction(connection):
                    connection.execute(INSERT_TRIP_SQL, record)
            except sqlite3.IntegrityError as exc:
                self._raise_integrity_error(exc, "trip", str(record["id"]))

            trip_row = self._get_trip_row(connection, str(record["id"]))

        return self._serialise_trip(trip_row)

    def get_trip(self, trip_id: str) -> dict[str, object]:
        with self._connect() as connection:
            trip_row = self._get_trip_row(connection, trip_id)

        return self._serialise_trip(trip_row)

    def update_trip(self, trip_id: str, payload: TripUpdate) -> dict[str, object]:
        updates = payload.model_dump(exclude_unset=True, mode="json")
        if not updates:
            raise validation_error(
                "One or more fields failed validation.",
                [{"field": "body", "issue": "at least one field must be provided"}],
            )

        with self._connect() as connection:
            with self._write_transaction(connection):
                existing = dict(self._get_trip_row(connection, trip_id))
                merged = existing | updates
                self._validate_trip_record(merged)
                self._ensure_trip_window_covers_items(connection, merged)
                self._ensure_trip_window_covers_activities(connection, merged)
                self._normalise_empty_payload(merged)
                connection.execute(UPDATE_TRIP_SQL, merged)

            trip_row = self._get_trip_row(connection, trip_id)

        return self._serialise_trip(trip_row)

    def delete_trip(self, trip_id: str) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_trip_row(connection, trip_id)
                connection.execute("DELETE FROM trips WHERE id = ?", (trip_id,))

        return {"id": trip_id, "deleted": True}

    def list_itinerary_items(
        self,
        trip_id: str,
        *,
        date: str | None = None,
        category: ItineraryCategory | None = None,
    ) -> list[dict[str, object]]:
        sql = f"SELECT {', '.join(ITEM_FIELDS)} FROM itinerary_items WHERE trip_id = ?"
        params: list[object] = [trip_id]

        if date is not None:
            sql += " AND date = ?"
            params.append(date)

        if category is not None:
            sql += " AND category = ?"
            params.append(category.value)

        sql += """
 ORDER BY
    date ASC,
    CASE WHEN start_time IS NULL THEN 1 ELSE 0 END ASC,
    start_time ASC,
    title COLLATE NOCASE ASC,
    id ASC
"""

        with self._connect() as connection:
            self._get_trip_row(connection, trip_id)
            rows = connection.execute(sql, params).fetchall()

        return [self._serialise_item(row) for row in rows]

    def create_itinerary_item(
        self,
        trip_id: str,
        payload: ItineraryItemCreate,
    ) -> dict[str, object]:
        record = payload.model_dump(mode="json")
        record["id"] = record.get("id") or self._generate_id("item")
        record["trip_id"] = trip_id
        self._normalise_empty_payload(record)

        with self._connect() as connection:
            with self._write_transaction(connection):
                trip = dict(self._get_trip_row(connection, trip_id))
                self._validate_item_record(record, trip)
                try:
                    connection.execute(INSERT_ITEM_SQL, record)
                except sqlite3.IntegrityError as exc:
                    self._raise_integrity_error(
                        exc,
                        "itinerary item",
                        str(record["id"]),
                    )

            item_row = self._get_item_row(connection, str(record["id"]))

        return self._serialise_item(item_row)

    def get_itinerary_item(self, item_id: str) -> dict[str, object]:
        with self._connect() as connection:
            item_row = self._get_item_row(connection, item_id)

        return self._serialise_item(item_row)

    def update_itinerary_item(
        self,
        item_id: str,
        payload: ItineraryItemUpdate,
    ) -> dict[str, object]:
        updates = payload.model_dump(exclude_unset=True, mode="json")
        if not updates:
            raise validation_error(
                "One or more fields failed validation.",
                [{"field": "body", "issue": "at least one field must be provided"}],
            )

        with self._connect() as connection:
            with self._write_transaction(connection):
                existing = dict(self._get_item_row(connection, item_id))
                trip = dict(self._get_trip_row(connection, existing["trip_id"]))
                merged = existing | updates
                self._normalise_empty_payload(merged)
                self._validate_item_record(merged, trip)
                connection.execute(UPDATE_ITEM_SQL, merged)

            item_row = self._get_item_row(connection, item_id)

        return self._serialise_item(item_row)

    def delete_itinerary_item(self, item_id: str) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_item_row(connection, item_id)
                connection.execute(
                    "DELETE FROM itinerary_items WHERE id = ?",
                    (item_id,),
                )

        return {"id": item_id, "deleted": True}

    def list_trip_accommodations(self, trip_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            self._get_trip_row(connection, trip_id)
            rows = connection.execute(
                f"SELECT {', '.join(TRIP_ACCOMMODATION_FIELDS)} "
                "FROM trip_accommodations WHERE trip_id = ? "
                "ORDER BY date ASC, accommodation_id ASC",
                (trip_id,),
            ).fetchall()

        return [self._serialise_trip_accommodation(row) for row in rows]

    def add_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
        date: str,
        check_out: str | None = None,
        check_in_time: str | None = None,
        check_out_time: str | None = None,
    ) -> dict[str, object]:
        """Replaces the pin, so re-sending the same body is a no-op and sending
        new dates moves the stay. It was DO NOTHING while the date was invented
        rather than chosen; now that a user picks it, silently keeping the old
        one would drop an edit the user watched themselves make."""
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_trip_row(connection, trip_id)
                connection.execute(
                    "INSERT INTO trip_accommodations "
                    "(trip_id, accommodation_id, date, check_in_time, "
                    "check_out, check_out_time) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (trip_id, accommodation_id) DO UPDATE SET "
                    "date = excluded.date, "
                    "check_in_time = excluded.check_in_time, "
                    "check_out = excluded.check_out, "
                    "check_out_time = excluded.check_out_time",
                    (
                        trip_id,
                        accommodation_id,
                        date,
                        check_in_time,
                        check_out,
                        check_out_time,
                    ),
                )

            row = connection.execute(
                f"SELECT {', '.join(TRIP_ACCOMMODATION_FIELDS)} "
                "FROM trip_accommodations WHERE trip_id = ? AND accommodation_id = ?",
                (trip_id, accommodation_id),
            ).fetchone()

        return self._serialise_trip_accommodation(row)

    def remove_trip_accommodation(
        self,
        trip_id: str,
        accommodation_id: str,
    ) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_trip_row(connection, trip_id)
                cursor = connection.execute(
                    "DELETE FROM trip_accommodations "
                    "WHERE trip_id = ? AND accommodation_id = ?",
                    (trip_id, accommodation_id),
                )
                if cursor.rowcount == 0:
                    raise not_found("Trip accommodation", accommodation_id)

        return {"id": accommodation_id, "deleted": True}

    def list_trips_for_accommodation(
        self,
        accommodation_id: str,
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {', '.join('trips.' + name for name in TRIP_FIELDS)} "
                "FROM trips JOIN trip_accommodations "
                "ON trip_accommodations.trip_id = trips.id "
                "WHERE trip_accommodations.accommodation_id = ? "
                "ORDER BY trips.start_date ASC, trips.name COLLATE NOCASE ASC, "
                "trips.id ASC",
                (accommodation_id,),
            ).fetchall()

        return [self._serialise_trip(row) for row in rows]

    def list_trip_activities(self, trip_id: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            self._get_trip_row(connection, trip_id)
            rows = connection.execute(
                f"SELECT {', '.join(TRIP_ACTIVITY_FIELDS)} "
                "FROM trip_activities WHERE trip_id = ? "
                "ORDER BY date ASC, activity_id ASC",
                (trip_id,),
            ).fetchall()

        return [self._serialise_trip_activity(row) for row in rows]

    def add_trip_activity(
        self,
        trip_id: str,
        activity_id: str,
        date: str,
        start_time: str | None = None,
    ) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                trip = self._get_trip_row(connection, trip_id)
                if date < trip["start_date"] or date > trip["end_date"]:
                    raise validation_error(
                        "One or more fields failed validation.",
                        [
                            {
                                "field": "date",
                                "issue": (
                                    f"must fall between {trip['start_date']} "
                                    f"and {trip['end_date']}"
                                ),
                            }
                        ],
                    )
                connection.execute(
                    "INSERT INTO trip_activities "
                    "(trip_id, activity_id, date, start_time) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (trip_id, activity_id) DO UPDATE SET "
                    "date = excluded.date, start_time = excluded.start_time",
                    (trip_id, activity_id, date, start_time),
                )

            row = connection.execute(
                f"SELECT {', '.join(TRIP_ACTIVITY_FIELDS)} "
                "FROM trip_activities WHERE trip_id = ? AND activity_id = ?",
                (trip_id, activity_id),
            ).fetchone()

        return self._serialise_trip_activity(row)

    def remove_trip_activity(
        self,
        trip_id: str,
        activity_id: str,
    ) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_trip_row(connection, trip_id)
                cursor = connection.execute(
                    "DELETE FROM trip_activities WHERE trip_id = ? AND activity_id = ?",
                    (trip_id, activity_id),
                )
                if cursor.rowcount == 0:
                    raise not_found("Trip activity", activity_id)

        return {"id": activity_id, "deleted": True}

    def list_trips_for_activity(
        self,
        activity_id: str,
    ) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {', '.join('trips.' + name for name in TRIP_FIELDS)} "
                "FROM trips JOIN trip_activities "
                "ON trip_activities.trip_id = trips.id "
                "WHERE trip_activities.activity_id = ? "
                "ORDER BY trips.start_date ASC, trips.name COLLATE NOCASE ASC, "
                "trips.id ASC",
                (activity_id,),
            ).fetchall()

        return [self._serialise_trip(row) for row in rows]

    def _get_trip_row(
        self,
        connection: sqlite3.Connection,
        trip_id: str,
    ) -> sqlite3.Row:
        trip_row = connection.execute(
            f"SELECT {', '.join(TRIP_FIELDS)} FROM trips WHERE id = ?",
            (trip_id,),
        ).fetchone()
        if trip_row is None:
            raise not_found("Trip", trip_id)

        return trip_row

    def _get_item_row(
        self,
        connection: sqlite3.Connection,
        item_id: str,
    ) -> sqlite3.Row:
        item_row = connection.execute(
            f"SELECT {', '.join(ITEM_FIELDS)} FROM itinerary_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if item_row is None:
            raise not_found("Itinerary item", item_id)

        return item_row

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        # CREATE TABLE IF NOT EXISTS does nothing to a table that already
        # exists, so a database written before a column was added never gains
        # it. Every deployment runs off a volume that predates check_out.
        #
        # ponytail: a PRAGMA and an ALTER, not a migration framework. The
        # PRAGMA is the check, so this is idempotent by construction -- there
        # is no metadata key to drift from what the table actually has. Grows
        # a line per added column; revisit when a change needs more than
        # ADD COLUMN, which SQLite cannot do in place anyway.
        for column in ("check_in_time", "check_out", "check_out_time"):
            self._ensure_column(connection, "trip_accommodations", column, "TEXT")

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _ensure_seed_data(self, connection: sqlite3.Connection) -> None:
        if self._get_schema_metadata(connection, SEED_MARKER_KEY) is not None:
            return

        if self._database_has_existing_rows(connection):
            self._set_schema_metadata(
                connection,
                SEED_MARKER_KEY,
                SEED_MARKER_SKIPPED_EXISTING_DATA,
            )
            return

        self._seed_trips(connection)
        self._seed_itinerary_items(connection)
        self._set_schema_metadata(connection, SEED_MARKER_KEY, SEED_MARKER_COMPLETED)

    def _seed_trips(self, connection: sqlite3.Connection) -> None:
        connection.executemany(INSERT_TRIP_SQL, SEED_TRIPS)

    def _seed_itinerary_items(self, connection: sqlite3.Connection) -> None:
        connection.executemany(INSERT_ITEM_SQL, SEED_ITINERARY_ITEMS)

    def _database_has_existing_rows(self, connection: sqlite3.Connection) -> bool:
        trips_exist = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM trips LIMIT 1)",
        ).fetchone()[0]
        items_exist = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM itinerary_items LIMIT 1)",
        ).fetchone()[0]
        return bool(trips_exist or items_exist)

    def _get_schema_metadata(
        self,
        connection: sqlite3.Connection,
        key: str,
    ) -> str | None:
        row = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        return str(row["value"])

    def _set_schema_metadata(
        self,
        connection: sqlite3.Connection,
        key: str,
        value: str,
    ) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO schema_metadata (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    @staticmethod
    def _generate_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:16]}"

    @staticmethod
    def _normalise_empty_payload(record: dict[str, object]) -> None:
        for field_name in ("notes", "location", "description"):
            if field_name in record and record[field_name] == "":
                record[field_name] = None

    def _validate_trip_record(self, record: dict[str, object]) -> None:
        TripRecord.model_validate(record)
        if str(record["start_date"]) > str(record["end_date"]):
            raise validation_error(
                "One or more fields failed validation.",
                [{"field": "start_date", "issue": "must be on or before end_date"}],
            )

    def _ensure_trip_window_covers_items(
        self,
        connection: sqlite3.Connection,
        record: dict[str, object],
    ) -> None:
        conflicting_rows = connection.execute(
            """
            SELECT id, date
            FROM itinerary_items
            WHERE trip_id = ?
              AND (date < ? OR date > ?)
            ORDER BY date ASC, id ASC
            LIMIT 3
            """,
            (
                record["id"],
                record["start_date"],
                record["end_date"],
            ),
        ).fetchall()
        if not conflicting_rows:
            return

        sample_dates = ", ".join(row["date"] for row in conflicting_rows)
        raise validation_error(
            "One or more fields failed validation.",
            [
                {
                    "field": "start_date",
                    "issue": (
                        f"cannot exclude existing itinerary item dates ({sample_dates})"
                    ),
                },
            ],
        )

    def _ensure_trip_window_covers_activities(
        self,
        connection: sqlite3.Connection,
        record: dict[str, object],
    ) -> None:
        conflicting_rows = connection.execute(
            """
            SELECT activity_id, date
            FROM trip_activities
            WHERE trip_id = ?
              AND (date < ? OR date > ?)
            ORDER BY date ASC, activity_id ASC
            LIMIT 3
            """,
            (record["id"], record["start_date"], record["end_date"]),
        ).fetchall()
        if not conflicting_rows:
            return

        sample_dates = ", ".join(row["date"] for row in conflicting_rows)
        raise validation_error(
            "One or more fields failed validation.",
            [
                {
                    "field": "start_date",
                    "issue": (
                        f"cannot exclude existing activity dates ({sample_dates})"
                    ),
                },
            ],
        )

    def _validate_item_record(
        self,
        record: dict[str, object],
        trip: dict[str, object],
    ) -> None:
        ItineraryItemRecord.model_validate(record)
        errors: list[dict[str, str]] = []

        item_date = str(record["date"])
        trip_start = str(trip["start_date"])
        trip_end = str(trip["end_date"])
        if item_date < trip_start or item_date > trip_end:
            errors.append(
                {
                    "field": "date",
                    "issue": f"must fall between {trip_start} and {trip_end}",
                },
            )

        start_time = record.get("start_time")
        end_time = record.get("end_time")
        if start_time is not None and end_time is not None and start_time >= end_time:
            errors.append(
                {
                    "field": "start_time",
                    "issue": "must be earlier than end_time when both are provided",
                },
            )

        if errors:
            raise validation_error(
                "One or more fields failed validation.",
                errors,
            )

    def _raise_integrity_error(
        self,
        exc: sqlite3.IntegrityError,
        resource: str,
        resource_id: str,
    ) -> None:
        message = str(exc)
        if "UNIQUE constraint failed" in message:
            raise conflict(
                f"{resource.capitalize()} '{resource_id}' already exists.",
                [{"field": "id", "issue": "already exists"}],
            ) from exc

        raise ApiError(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An unexpected database constraint failed.",
        ) from exc

    @staticmethod
    def _translate_operational_error(exc: sqlite3.OperationalError) -> ApiError:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            return database_busy(
                "The database is busy processing another write request. Please retry.",
            )

        return internal_error("An unexpected database operation failed.")

    @staticmethod
    def _serialise_trip(row: sqlite3.Row) -> dict[str, object]:
        return TripRecord.model_validate(dict(row)).model_dump(mode="json")

    @staticmethod
    def _serialise_item(row: sqlite3.Row) -> dict[str, object]:
        return ItineraryItemRecord.model_validate(dict(row)).model_dump(mode="json")

    @staticmethod
    def _serialise_trip_accommodation(row: sqlite3.Row) -> dict[str, object]:
        return TripAccommodationRecord.model_validate(dict(row)).model_dump(mode="json")

    @staticmethod
    def _serialise_trip_activity(row: sqlite3.Row) -> dict[str, object]:
        return TripActivityRecord.model_validate(dict(row)).model_dump(mode="json")
