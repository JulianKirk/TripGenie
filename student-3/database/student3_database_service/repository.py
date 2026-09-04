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
    MAX_TRANSPORT_DURATION_MINUTES,
    AvailabilityStatus,
    PricingBasis,
    TransportOptionCreate,
    TransportOptionRecord,
    TransportOptionStored,
    TransportOptionUpdate,
    TransportType,
)
from .seed_data import SEED_TRANSPORT_OPTIONS

VALIDATION_MESSAGE = "One or more fields failed validation."

# Patching any of these invalidates a previously derived (or overridden)
# estimated_cost, so the per-traveller default is recalculated unless the caller
# sends an explicit estimated_cost in the same request.
_PRICING_BASIS_SQL = ", ".join(f"'{basis.value}'" for basis in PricingBasis)

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
    "pricing_basis",
    "notes",
)
SEED_MARKER_KEY = "student3_demo_seed_v1"
SEED_MARKER_COMPLETED = "completed"
SEED_MARKER_SKIPPED_EXISTING_DATA = "skipped-existing-data"

_TRANSPORT_TYPE_SQL = ", ".join(f"'{item.value}'" for item in TransportType)
_AVAILABILITY_SQL = ", ".join(f"'{item.value}'" for item in AvailabilityStatus)

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
    pricing_basis TEXT NOT NULL DEFAULT 'per_traveller' CHECK (
        pricing_basis IN ({_PRICING_BASIS_SQL})
    ),
    notes TEXT,
    CHECK (
        (departure_utc_offset IS NULL) = (arrival_utc_offset IS NULL)
    )
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
    pricing_basis,
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
    :pricing_basis,
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
    pricing_basis = :pricing_basis,
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
        sql = f"SELECT {columns} FROM transport_options"
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
                connection.execute(UPDATE_OPTION_SQL, merged)

            option_row = self._get_option_view(connection, transport_id)

        return self._serialise_option(option_row)

    def delete_transport_option(self, transport_id: str) -> dict[str, object]:
        with self._connect() as connection:
            with self._write_transaction(connection):
                self._get_option_row(connection, transport_id)
                connection.execute(
                    "DELETE FROM transport_options WHERE id = ?",
                    (transport_id,),
                )

        return {"id": transport_id, "deleted": True}

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
            SELECT {columns}
            FROM transport_options
            WHERE transport_options.id = ?
            """,
            (transport_id,),
        ).fetchone()
        if option_row is None:
            raise not_found("Transport option", transport_id)

        return option_row

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        self._migrate_pricing_basis(connection)
        self._drop_retired_selections_table(connection)

    @staticmethod
    def _drop_retired_selections_table(connection: sqlite3.Connection) -> None:
        """Remove `transport_bookings`, left behind by an older database file.

        Transport selections belong to the itinerary service now, and no code
        here has read this table since. Leaving it in place looked harmless and
        was not: the table still declares

            transport_id TEXT NOT NULL REFERENCES transport_options(id)

        so SQLite refused to delete any option an old row referenced, and the
        catalogue's delete broke for exactly the options the demo data had used.
        A fresh database never creates it; only a volume that predates the move
        has one.
        """
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("transport_bookings",),
        ).fetchone()
        if exists is None:
            return

        connection.execute("DROP TABLE transport_bookings")

    @staticmethod
    def _migrate_pricing_basis(connection: sqlite3.Connection) -> None:
        """Add `pricing_basis` to a table that predates it.

        `CREATE TABLE IF NOT EXISTS` leaves an existing table alone, so a
        database created before this column existed keeps its old shape and
        every insert then fails on the missing bind. A named volume outlives a
        deployment, so this has to migrate rather than assume a fresh file.

        The CHECK constraint that a fresh database gets cannot be added by
        ALTER TABLE. A migrated database therefore enforces the values in the
        model only -- the same trade Student 1 documents on their stay window.
        """
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(transport_options)")
        }
        if not columns or "pricing_basis" in columns:
            return

        connection.execute(
            "ALTER TABLE transport_options ADD COLUMN pricing_basis TEXT "
            f"NOT NULL DEFAULT '{PricingBasis.PER_TRAVELLER.value}'",
        )
        # Whole-vehicle hire is the case this column exists for, and the only
        # way to recognise it in older rows is the note that says so.
        connection.execute(
            "UPDATE transport_options SET pricing_basis = ? "
            "WHERE notes LIKE '%per vehicle%'",
            (PricingBasis.PER_VEHICLE.value,),
        )

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
            option.setdefault("pricing_basis", PricingBasis.PER_TRAVELLER.value)
            self._apply_option_derived_fields(option)
            self._validate_option_record(option)

        connection.executemany(INSERT_OPTION_SQL, options)
        self._set_schema_metadata(connection, SEED_MARKER_KEY, SEED_MARKER_COMPLETED)

    def _database_has_existing_rows(self, connection: sqlite3.Connection) -> bool:
        options_exist = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM transport_options LIMIT 1)",
        ).fetchone()[0]
        return bool(options_exist)

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
