from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
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
    BOOKABLE_AVAILABILITY_STATUSES,
    CAPACITY_CONSUMING_BOOKING_STATUSES,
    MAX_TRANSPORT_DURATION_MINUTES,
    AvailabilityStatus,
    BookingStatus,
    TransportBookingCreate,
    TransportBookingRecord,
    TransportBookingUpdate,
    TransportOptionCreate,
    TransportOptionRecord,
    TransportOptionStored,
    TransportOptionUpdate,
    TransportType,
)
from .seed_data import SEED_TRANSPORT_BOOKINGS, SEED_TRANSPORT_OPTIONS

VALIDATION_MESSAGE = "One or more fields failed validation."

# Patching any of these invalidates a previously derived (or overridden)
# estimated_cost, so the per-traveller default is recalculated unless the caller
# sends an explicit estimated_cost in the same request.
ESTIMATED_COST_DRIVERS = frozenset({"traveller_count", "transport_id"})

OPTION_FIELDS = (
    "id",
    "type",
    "provider",
    "origin",
    "destination",
    "departure_time",
    "arrival_time",
    "departure_utc_offset",
    "arrival_utc_offset",
    "duration_minutes",
    "price",
    "capacity",
    "availability_status",
    "notes",
)
BOOKING_FIELDS = (
    "id",
    "trip_id",
    "transport_id",
    "traveller_count",
    "booking_date",
    "estimated_cost",
    "booking_status",
    "notes",
)

SEED_MARKER_KEY = "student3_demo_seed_v1"
SEED_MARKER_COMPLETED = "completed"
SEED_MARKER_SKIPPED_EXISTING_DATA = "skipped-existing-data"

_TRANSPORT_TYPE_SQL = ", ".join(f"'{item.value}'" for item in TransportType)
_AVAILABILITY_SQL = ", ".join(f"'{item.value}'" for item in AvailabilityStatus)
_BOOKING_STATUS_SQL = ", ".join(f"'{item.value}'" for item in BookingStatus)
_CAPACITY_CONSUMING_SQL = ", ".join(
    f"'{item.value}'" for item in sorted(CAPACITY_CONSUMING_BOOKING_STATUSES)
)

# seats_remaining is never stored: a stale copy would contradict the bookings
# table, so it is recomputed by this subquery on every read.
SEATS_REMAINING_SQL = f"""
    transport_options.capacity - COALESCE((
        SELECT SUM(booked.traveller_count)
        FROM transport_bookings AS booked
        WHERE booked.transport_id = transport_options.id
          AND booked.booking_status IN ({_CAPACITY_CONSUMING_SQL})
    ), 0) AS seats_remaining
"""

SCHEMA_STATEMENTS = (
    f"""
CREATE TABLE IF NOT EXISTS transport_options (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ({_TRANSPORT_TYPE_SQL})),
    provider TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    departure_time TEXT NOT NULL,
    arrival_time TEXT NOT NULL,
    departure_utc_offset INTEGER,
    arrival_utc_offset INTEGER,
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    price REAL NOT NULL CHECK (price >= 0),
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    availability_status TEXT NOT NULL CHECK (
        availability_status IN ({_AVAILABILITY_SQL})
    ),
    notes TEXT,
    CHECK (
        (departure_utc_offset IS NULL) = (arrival_utc_offset IS NULL)
    )
)
""",
    f"""
CREATE TABLE IF NOT EXISTS transport_bookings (
    id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    transport_id TEXT NOT NULL REFERENCES transport_options(id),
    traveller_count INTEGER NOT NULL CHECK (traveller_count > 0),
    booking_date TEXT NOT NULL,
    estimated_cost REAL NOT NULL CHECK (estimated_cost >= 0),
    booking_status TEXT NOT NULL CHECK (
        booking_status IN ({_BOOKING_STATUS_SQL})
    ),
    notes TEXT
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
CREATE INDEX IF NOT EXISTS idx_transport_options_route_departure
    ON transport_options (origin, destination, departure_time)
""",
    """
CREATE INDEX IF NOT EXISTS idx_transport_options_type_price
    ON transport_options (type, price)
""",
    """
CREATE INDEX IF NOT EXISTS idx_transport_bookings_trip
    ON transport_bookings (trip_id, booking_date)
""",
    """
CREATE INDEX IF NOT EXISTS idx_transport_bookings_transport_status
    ON transport_bookings (transport_id, booking_status)
""",
)

INSERT_OPTION_SQL = """
INSERT INTO transport_options (
    id,
    type,
    provider,
    origin,
    destination,
    departure_time,
    arrival_time,
    departure_utc_offset,
    arrival_utc_offset,
    duration_minutes,
    price,
    capacity,
    availability_status,
    notes
) VALUES (
    :id,
    :type,
    :provider,
    :origin,
    :destination,
    :departure_time,
    :arrival_time,
    :departure_utc_offset,
    :arrival_utc_offset,
    :duration_minutes,
    :price,
    :capacity,
    :availability_status,
    :notes
)
"""

UPDATE_OPTION_SQL = """
UPDATE transport_options
SET
    type = :type,
    provider = :provider,
    origin = :origin,
    destination = :destination,
    departure_time = :departure_time,
    arrival_time = :arrival_time,
    departure_utc_offset = :departure_utc_offset,
    arrival_utc_offset = :arrival_utc_offset,
    duration_minutes = :duration_minutes,
    price = :price,
    capacity = :capacity,
    availability_status = :availability_status,
    notes = :notes
WHERE id = :id
"""

INSERT_BOOKING_SQL = """
INSERT INTO transport_bookings (
    id,
    trip_id,
    transport_id,
    traveller_count,
    booking_date,
    estimated_cost,
    booking_status,
    notes
) VALUES (
    :id,
    :trip_id,
    :transport_id,
    :traveller_count,
    :booking_date,
    :estimated_cost,
    :booking_status,
    :notes
)
"""

UPDATE_BOOKING_SQL = """
UPDATE transport_bookings
SET
    trip_id = :trip_id,
    transport_id = :transport_id,
    traveller_count = :traveller_count,
    booking_date = :booking_date,
    estimated_cost = :estimated_cost,
    booking_status = :booking_status,
    notes = :notes
WHERE id = :id
"""

def duration_minutes(
    departure_time: str,
    arrival_time: str,
    departure_utc_offset: int | None = None,
    arrival_utc_offset: int | None = None,
) -> int:
    """Elapsed minutes between two validated ``YYYY-MM-DDTHH:MM`` timestamps.

    Timestamps are local wall-clock times, the way they appear on a ticket.
    When both UTC offsets are supplied each end is shifted to UTC first, so a
    leg that crosses time zones reports the journey length rather than the
    difference between two clocks in different zones.
    """
    departs = datetime.fromisoformat(departure_time)
    arrives = datetime.fromisoformat(arrival_time)

    if departure_utc_offset is not None and arrival_utc_offset is not None:
        departs -= timedelta(minutes=departure_utc_offset)
        arrives -= timedelta(minutes=arrival_utc_offset)

    return int((arrives - departs).total_seconds() // 60)


def default_estimated_cost(price: float, traveller_count: int) -> float:
    """Per-traveller fare total used when a booking omits ``estimated_cost``.

    Multiplication happens in whole cents so the result cannot inherit a
    binary floating point remainder from the fare.
    """
    return round(round(price * 100) * traveller_count) / 100


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

    def list_transport_options(
        self,
        *,
        transport_type: TransportType | None = None,
        provider: str | None = None,
        origin: str | None = None,
        destination: str | None = None,
        availability_status: AvailabilityStatus | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        departure_from: str | None = None,
        departure_to: str | None = None,
    ) -> list[dict[str, object]]:
        columns = ", ".join(f"transport_options.{name}" for name in OPTION_FIELDS)
        sql = f"SELECT {columns}, {SEATS_REMAINING_SQL} FROM transport_options"
        conditions: list[str] = []
        params: list[object] = []

        if transport_type is not None:
            conditions.append("type = ?")
            params.append(transport_type.value)

        if provider:
            conditions.append("LOWER(provider) = LOWER(?)")
            params.append(provider)

        if origin:
            conditions.append("LOWER(origin) = LOWER(?)")
            params.append(origin)

        if destination:
            conditions.append("LOWER(destination) = LOWER(?)")
            params.append(destination)

        if availability_status is not None:
            conditions.append("availability_status = ?")
            params.append(availability_status.value)

        if min_price is not None:
            conditions.append("price >= ?")
            params.append(min_price)

        if max_price is not None:
            conditions.append("price <= ?")
            params.append(max_price)

        if departure_from is not None:
            conditions.append("departure_time >= ?")
            params.append(departure_from)

        if departure_to is not None:
            conditions.append("departure_time <= ?")
            params.append(departure_to)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY departure_time ASC, price ASC, id ASC"

        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()

        return [self._serialise_option(row) for row in rows]

    def create_transport_option(
        self,
        payload: TransportOptionCreate,
    ) -> dict[str, object]:
        record = payload.model_dump(mode="json")
        record["id"] = record.get("id") or self._generate_id("transport")
        self._normalise_empty_payload(record)
        self._apply_option_derived_fields(record)
        self._validate_option_record(record)

        with self._connect() as connection:
            try:
                with self._write_transaction(connection):
                    connection.execute(INSERT_OPTION_SQL, record)
            except sqlite3.IntegrityError as exc:
                self._raise_integrity_error(
                    exc,
                    "transport option",
                    str(record["id"]),
                )

            option_row = self._get_option_view(connection, str(record["id"]))

        return self._serialise_option(option_row)

    def get_transport_option(self, transport_id: str) -> dict[str, object]:
        with self._connect() as connection:
            option_row = self._get_option_view(connection, transport_id)

        return self._serialise_option(option_row)

    def update_transport_option(
        self,
        transport_id: str,
        payload: TransportOptionUpdate,
    ) -> dict[str, object]:
        updates = payload.model_dump(exclude_unset=True, mode="json")
        if not updates:
            raise validation_error(
                VALIDATION_MESSAGE,
                [{"field": "body", "issue": "at least one field must be provided"}],
            )

        with self._connect() as connection:
            with self._write_transaction(connection):
                existing = dict(self._get_option_row(connection, transport_id))
                merged = existing | updates
                self._normalise_empty_payload(merged)
                self._apply_option_derived_fields(merged)
                self._validate_option_record(merged)
                self._ensure_capacity_covers_bookings(connection, merged)
                connection.execute(UPDATE_OPTION_SQL, merged)

            option_row = self._get_option_view(connection, transport_id)

        return self._serialise_option(option_row)

    def delete_transport_option(self, transport_id: str) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_option_row(connection, transport_id)
                booking_count = connection.execute(
                    "SELECT COUNT(*) FROM transport_bookings WHERE transport_id = ?",
                    (transport_id,),
                ).fetchone()[0]
                if booking_count:
                    raise conflict(
                        (
                            f"Transport option '{transport_id}' still has "
                            f"{booking_count} booking(s)."
                        ),
                        [
                            {
                                "field": "id",
                                "issue": (
                                    "delete the dependent bookings before "
                                    "deleting the transport option"
                                ),
                            },
                        ],
                    )

                connection.execute(
                    "DELETE FROM transport_options WHERE id = ?",
                    (transport_id,),
                )

        return {"id": transport_id, "deleted": True}

    def list_transport_bookings(
        self,
        *,
        trip_id: str | None = None,
        transport_id: str | None = None,
        booking_status: BookingStatus | None = None,
    ) -> list[dict[str, object]]:
        sql = f"SELECT {', '.join(BOOKING_FIELDS)} FROM transport_bookings"
        conditions: list[str] = []
        params: list[object] = []

        if trip_id is not None:
            conditions.append("trip_id = ?")
            params.append(trip_id)

        if transport_id is not None:
            conditions.append("transport_id = ?")
            params.append(transport_id)

        if booking_status is not None:
            conditions.append("booking_status = ?")
            params.append(booking_status.value)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY booking_date ASC, id ASC"

        with self._connect() as connection:
            if transport_id is not None:
                self._get_option_row(connection, transport_id)
            rows = connection.execute(sql, params).fetchall()

        return [self._serialise_booking(row) for row in rows]

    def create_transport_booking(
        self,
        payload: TransportBookingCreate,
    ) -> dict[str, object]:
        record = payload.model_dump(mode="json")
        record["id"] = record.get("id") or self._generate_id("booking")
        self._normalise_empty_payload(record)

        with self._connect() as connection:
            with self._write_transaction(connection):
                option = dict(
                    self._get_option_row(connection, str(record["transport_id"])),
                )
                self._apply_booking_derived_fields(record, option)
                self._validate_booking_record(record, option)
                self._ensure_option_accepts_new_booking(record, option)
                self._ensure_seats_available(connection, record, option)
                try:
                    connection.execute(INSERT_BOOKING_SQL, record)
                except sqlite3.IntegrityError as exc:
                    self._raise_integrity_error(
                        exc,
                        "transport booking",
                        str(record["id"]),
                    )

            booking_row = self._get_booking_row(connection, str(record["id"]))

        return self._serialise_booking(booking_row)

    def get_transport_booking(self, booking_id: str) -> dict[str, object]:
        with self._connect() as connection:
            booking_row = self._get_booking_row(connection, booking_id)

        return self._serialise_booking(booking_row)

    def update_transport_booking(
        self,
        booking_id: str,
        payload: TransportBookingUpdate,
    ) -> dict[str, object]:
        updates = payload.model_dump(exclude_unset=True, mode="json")
        if not updates:
            raise validation_error(
                VALIDATION_MESSAGE,
                [{"field": "body", "issue": "at least one field must be provided"}],
            )

        with self._connect() as connection:
            with self._write_transaction(connection):
                existing = dict(self._get_booking_row(connection, booking_id))
                merged = existing | updates
                self._normalise_empty_payload(merged)
                option = dict(
                    self._get_option_row(connection, str(merged["transport_id"])),
                )
                if "estimated_cost" not in updates and (
                    ESTIMATED_COST_DRIVERS & updates.keys()
                ):
                    merged["estimated_cost"] = None
                self._apply_booking_derived_fields(merged, option)
                self._validate_booking_record(merged, option)
                if self._is_reactivating_booking(existing, merged):
                    self._ensure_option_accepts_new_booking(merged, option)
                self._ensure_seats_available(connection, merged, option)
                connection.execute(UPDATE_BOOKING_SQL, merged)

            booking_row = self._get_booking_row(connection, booking_id)

        return self._serialise_booking(booking_row)

    def delete_transport_booking(self, booking_id: str) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_booking_row(connection, booking_id)
                connection.execute(
                    "DELETE FROM transport_bookings WHERE id = ?",
                    (booking_id,),
                )

        return {"id": booking_id, "deleted": True}

    def _get_option_row(
        self,
        connection: sqlite3.Connection,
        transport_id: str,
    ) -> sqlite3.Row:
        option_row = connection.execute(
            f"SELECT {', '.join(OPTION_FIELDS)} FROM transport_options WHERE id = ?",
            (transport_id,),
        ).fetchone()
        if option_row is None:
            raise not_found("Transport option", transport_id)

        return option_row

    def _get_option_view(
        self,
        connection: sqlite3.Connection,
        transport_id: str,
    ) -> sqlite3.Row:
        columns = ", ".join(f"transport_options.{name}" for name in OPTION_FIELDS)
        option_row = connection.execute(
            f"""
            SELECT {columns}, {SEATS_REMAINING_SQL}
            FROM transport_options
            WHERE transport_options.id = ?
            """,
            (transport_id,),
        ).fetchone()
        if option_row is None:
            raise not_found("Transport option", transport_id)

        return option_row

    def _get_booking_row(
        self,
        connection: sqlite3.Connection,
        booking_id: str,
    ) -> sqlite3.Row:
        booking_row = connection.execute(
            f"SELECT {', '.join(BOOKING_FIELDS)} FROM transport_bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()
        if booking_row is None:
            raise not_found("Transport booking", booking_id)

        return booking_row

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)

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

        options = [dict(option) for option in SEED_TRANSPORT_OPTIONS]
        for option in options:
            option.setdefault("notes", None)
            self._apply_option_derived_fields(option)
            self._validate_option_record(option)

        prices = {str(option["id"]): float(option["price"]) for option in options}
        bookings = [dict(booking) for booking in SEED_TRANSPORT_BOOKINGS]
        for booking in bookings:
            booking.setdefault("notes", None)
            transport_id = str(booking["transport_id"])
            if transport_id not in prices:
                raise internal_error(
                    "Seed data references an unknown transport option.",
                    [{"field": "transport_id", "issue": transport_id}],
                )

            if booking.get("estimated_cost") is None:
                booking["estimated_cost"] = default_estimated_cost(
                    prices[transport_id],
                    int(booking["traveller_count"]),
                )

            TransportBookingRecord.model_validate(booking)

        connection.executemany(INSERT_OPTION_SQL, options)
        connection.executemany(INSERT_BOOKING_SQL, bookings)
        self._set_schema_metadata(connection, SEED_MARKER_KEY, SEED_MARKER_COMPLETED)

    def _database_has_existing_rows(self, connection: sqlite3.Connection) -> bool:
        options_exist = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM transport_options LIMIT 1)",
        ).fetchone()[0]
        bookings_exist = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM transport_bookings LIMIT 1)",
        ).fetchone()[0]
        return bool(options_exist or bookings_exist)

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
        if record.get("notes") == "":
            record["notes"] = None

    @staticmethod
    def _option_utc_offsets(
        record: dict[str, object],
    ) -> tuple[int | None, int | None]:
        departure = record.get("departure_utc_offset")
        arrival = record.get("arrival_utc_offset")
        return (
            None if departure is None else int(departure),
            None if arrival is None else int(arrival),
        )

    @classmethod
    def _apply_option_derived_fields(cls, record: dict[str, object]) -> None:
        record.setdefault("departure_utc_offset", None)
        record.setdefault("arrival_utc_offset", None)
        departure_offset, arrival_offset = cls._option_utc_offsets(record)
        if (departure_offset is None) != (arrival_offset is None):
            raise validation_error(
                VALIDATION_MESSAGE,
                [
                    {
                        "field": "departure_utc_offset",
                        "issue": (
                            "must be provided together with arrival_utc_offset, "
                            "or both omitted"
                        ),
                    },
                ],
            )

        record["duration_minutes"] = duration_minutes(
            str(record["departure_time"]),
            str(record["arrival_time"]),
            departure_offset,
            arrival_offset,
        )

    @staticmethod
    def _apply_booking_derived_fields(
        record: dict[str, object],
        option: dict[str, object],
    ) -> None:
        if record.get("estimated_cost") is None:
            record["estimated_cost"] = default_estimated_cost(
                float(option["price"]),
                int(record["traveller_count"]),
            )

    def _validate_option_record(self, record: dict[str, object]) -> None:
        minutes = int(record["duration_minutes"])
        if minutes <= 0:
            raise validation_error(
                VALIDATION_MESSAGE,
                [
                    {
                        "field": "arrival_time",
                        "issue": "must be later than departure_time",
                    },
                ],
            )

        if minutes > MAX_TRANSPORT_DURATION_MINUTES:
            raise validation_error(
                VALIDATION_MESSAGE,
                [
                    {
                        "field": "arrival_time",
                        "issue": (
                            "must be within "
                            f"{MAX_TRANSPORT_DURATION_MINUTES} minutes of "
                            "departure_time"
                        ),
                    },
                ],
            )

        TransportOptionStored.model_validate(record)

    def _validate_booking_record(
        self,
        record: dict[str, object],
        option: dict[str, object],
    ) -> None:
        TransportBookingRecord.model_validate(record)

        booking_date = str(record["booking_date"])
        departure_date = str(option["departure_time"])[:10]
        if booking_date > departure_date:
            raise validation_error(
                VALIDATION_MESSAGE,
                [
                    {
                        "field": "booking_date",
                        "issue": (
                            "must be on or before the transport departure date "
                            f"({departure_date})"
                        ),
                    },
                ],
            )

    @staticmethod
    def _is_reactivating_booking(
        existing: dict[str, object],
        merged: dict[str, object],
    ) -> bool:
        was_active = (
            BookingStatus(str(existing["booking_status"]))
            in CAPACITY_CONSUMING_BOOKING_STATUSES
        )
        is_active = (
            BookingStatus(str(merged["booking_status"]))
            in CAPACITY_CONSUMING_BOOKING_STATUSES
        )
        changed_transport = existing["transport_id"] != merged["transport_id"]
        return is_active and (not was_active or changed_transport)

    @staticmethod
    def _ensure_option_accepts_new_booking(
        record: dict[str, object],
        option: dict[str, object],
    ) -> None:
        status = BookingStatus(str(record["booking_status"]))
        if status not in CAPACITY_CONSUMING_BOOKING_STATUSES:
            return

        availability = AvailabilityStatus(str(option["availability_status"]))
        if availability in BOOKABLE_AVAILABILITY_STATUSES:
            return

        raise validation_error(
            VALIDATION_MESSAGE,
            [
                {
                    "field": "transport_id",
                    "issue": (
                        "transport option is not bookable while its "
                        f"availability_status is '{availability.value}'"
                    ),
                },
            ],
        )

    def _ensure_seats_available(
        self,
        connection: sqlite3.Connection,
        record: dict[str, object],
        option: dict[str, object],
    ) -> None:
        status = BookingStatus(str(record["booking_status"]))
        if status not in CAPACITY_CONSUMING_BOOKING_STATUSES:
            return

        booked = connection.execute(
            f"""
            SELECT COALESCE(SUM(traveller_count), 0)
            FROM transport_bookings
            WHERE transport_id = ?
              AND id != ?
              AND booking_status IN ({_CAPACITY_CONSUMING_SQL})
            """,
            (record["transport_id"], record["id"]),
        ).fetchone()[0]

        capacity = int(option["capacity"])
        requested = int(record["traveller_count"])
        if booked + requested <= capacity:
            return

        raise conflict(
            (
                f"Transport option '{option['id']}' has "
                f"{max(capacity - booked, 0)} seat(s) remaining."
            ),
            [
                {
                    "field": "traveller_count",
                    "issue": (
                        f"exceeds remaining capacity ({capacity - booked} "
                        f"of {capacity})"
                    ),
                },
            ],
        )

    def _ensure_capacity_covers_bookings(
        self,
        connection: sqlite3.Connection,
        record: dict[str, object],
    ) -> None:
        booked = connection.execute(
            f"""
            SELECT COALESCE(SUM(traveller_count), 0)
            FROM transport_bookings
            WHERE transport_id = ?
              AND booking_status IN ({_CAPACITY_CONSUMING_SQL})
            """,
            (record["id"],),
        ).fetchone()[0]

        capacity = int(record["capacity"])
        if booked <= capacity:
            return

        raise validation_error(
            VALIDATION_MESSAGE,
            [
                {
                    "field": "capacity",
                    "issue": (
                        f"must be at least {booked} to cover existing bookings"
                    ),
                },
            ],
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
    def _serialise_option(row: sqlite3.Row) -> dict[str, object]:
        return TransportOptionRecord.model_validate(dict(row)).model_dump(mode="json")

    @staticmethod
    def _serialise_booking(row: sqlite3.Row) -> dict[str, object]:
        return TransportBookingRecord.model_validate(dict(row)).model_dump(mode="json")
