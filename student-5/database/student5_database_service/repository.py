from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from .config import Settings
from .errors import conflict, invalid_update, not_found
from .models import (
    BudgetCreate,
    BudgetFields,
    BudgetRecord,
    BudgetUpdate,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseFields,
    ExpenseRecord,
    ExpenseUpdate,
)
from .seed_data import SEED_BUDGETS, SEED_EXPENSES

BUDGET_COLUMNS = (
    "budget_id",
    "trip_id",
    "currency",
    "total_budget",
    "accommodation_budget",
    "transport_budget",
    "activities_budget",
    "food_budget",
    "other_budget",
    "created_at",
    "updated_at",
)
EXPENSE_COLUMNS = (
    "expense_id",
    "trip_id",
    "category",
    "description",
    "amount",
    "currency",
    "date",
    "payment_method",
    "notes",
    "created_at",
    "updated_at",
)
MONEY_COLUMNS = (
    "total_budget",
    "accommodation_budget",
    "transport_budget",
    "activities_budget",
    "food_budget",
    "other_budget",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS budgets (
    budget_id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL UNIQUE,
    currency TEXT NOT NULL CHECK (
        length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'
    ),
    total_budget TEXT NOT NULL CHECK (CAST(total_budget AS NUMERIC) >= 0),
    accommodation_budget TEXT NOT NULL CHECK (
        CAST(accommodation_budget AS NUMERIC) >= 0
    ),
    transport_budget TEXT NOT NULL CHECK (CAST(transport_budget AS NUMERIC) >= 0),
    activities_budget TEXT NOT NULL CHECK (CAST(activities_budget AS NUMERIC) >= 0),
    food_budget TEXT NOT NULL CHECK (CAST(food_budget AS NUMERIC) >= 0),
    other_budget TEXT NOT NULL CHECK (CAST(other_budget AS NUMERIC) >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        CAST(accommodation_budget AS NUMERIC)
        + CAST(transport_budget AS NUMERIC)
        + CAST(activities_budget AS NUMERIC)
        + CAST(food_budget AS NUMERIC)
        + CAST(other_budget AS NUMERIC)
        <= CAST(total_budget AS NUMERIC)
    )
);

CREATE TABLE IF NOT EXISTS expenses (
    expense_id TEXT PRIMARY KEY,
    trip_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN (
            'accommodation', 'transport', 'activities',
            'food', 'shopping', 'other'
        )
    ),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    amount TEXT NOT NULL CHECK (CAST(amount AS NUMERIC) > 0),
    currency TEXT NOT NULL CHECK (
        length(currency) = 3 AND currency NOT GLOB '*[^A-Z]*'
    ),
    date TEXT NOT NULL,
    payment_method TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_budgets_trip ON budgets (trip_id);
CREATE INDEX IF NOT EXISTS idx_expenses_trip_date ON expenses (trip_id, date);
CREATE INDEX IF NOT EXISTS idx_expenses_category_date ON expenses (category, date);
"""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _record_values(model: BudgetFields | ExpenseFields) -> dict[str, Any]:
    values = model.model_dump(mode="json")
    for field in MONEY_COLUMNS:
        if field in values:
            values[field] = _money(getattr(model, field))
    if "amount" in values:
        values["amount"] = _money(model.amount)
    return values


def _fields_from_record(
    record: BudgetRecord | ExpenseRecord,
    model_type: type[BudgetFields] | type[ExpenseFields],
) -> dict[str, Any]:
    return {field: getattr(record, field) for field in model_type.model_fields}


class DatabaseRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        self.settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.settings.sqlite_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            if self.settings.seed_data:
                now = _timestamp()
                for budget in SEED_BUDGETS:
                    self._insert_budget(
                        connection,
                        budget | {"created_at": now, "updated_at": now},
                        ignore=True,
                    )
                for expense in SEED_EXPENSES:
                    self._insert_expense(
                        connection,
                        expense | {"created_at": now, "updated_at": now},
                        ignore=True,
                    )

    def _insert_budget(
        self,
        connection: sqlite3.Connection,
        values: dict[str, Any],
        *,
        ignore: bool = False,
    ) -> None:
        command = "INSERT OR IGNORE" if ignore else "INSERT"
        columns = ", ".join(BUDGET_COLUMNS)
        placeholders = ", ".join(f":{column}" for column in BUDGET_COLUMNS)
        connection.execute(
            f"{command} INTO budgets ({columns}) VALUES ({placeholders})", values
        )

    def _insert_expense(
        self,
        connection: sqlite3.Connection,
        values: dict[str, Any],
        *,
        ignore: bool = False,
    ) -> None:
        command = "INSERT OR IGNORE" if ignore else "INSERT"
        columns = ", ".join(EXPENSE_COLUMNS)
        placeholders = ", ".join(f":{column}" for column in EXPENSE_COLUMNS)
        connection.execute(
            f"{command} INTO expenses ({columns}) VALUES ({placeholders})", values
        )

    def list_budgets(self, trip_id: str | None = None) -> list[BudgetRecord]:
        query = "SELECT * FROM budgets"
        parameters: tuple[str, ...] = ()
        if trip_id is not None:
            query += " WHERE trip_id = ?"
            parameters = (trip_id,)
        query += " ORDER BY trip_id, budget_id"
        with self.connect() as connection:
            return [
                BudgetRecord.model_validate(dict(row))
                for row in connection.execute(query, parameters)
            ]

    def get_budget(self, budget_id: UUID) -> BudgetRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM budgets WHERE budget_id = ?", (str(budget_id),)
            ).fetchone()
        if row is None:
            raise not_found("Budget", str(budget_id))
        return BudgetRecord.model_validate(dict(row))

    def create_budget(self, payload: BudgetCreate) -> BudgetRecord:
        budget_id = payload.budget_id or uuid4()
        now = _timestamp()
        fields = payload.model_dump(exclude={"budget_id"})
        values = _record_values(BudgetFields.model_validate(fields)) | {
            "budget_id": str(budget_id),
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.connect() as connection:
                self._insert_budget(connection, values)
        except sqlite3.IntegrityError as exc:
            raise conflict(
                "A budget already exists for this trip or identifier.", "trip_id"
            ) from exc
        return self.get_budget(budget_id)

    def update_budget(self, budget_id: UUID, payload: BudgetUpdate) -> BudgetRecord:
        if not payload.model_fields_set:
            raise invalid_update()
        current = self.get_budget(budget_id)
        changes = payload.model_dump(exclude_unset=True)
        if any(value is None for value in changes.values()):
            raise invalid_update()
        current_fields = _fields_from_record(current, BudgetFields)
        updated = BudgetFields.model_validate(current_fields | changes)
        values = _record_values(updated) | {
            "budget_id": str(budget_id),
            "updated_at": _timestamp(),
        }
        assignments = ", ".join(
            f"{field} = :{field}"
            for field in (*BudgetFields.model_fields, "updated_at")
        )
        try:
            with self.connect() as connection:
                connection.execute(
                    f"UPDATE budgets SET {assignments} WHERE budget_id = :budget_id",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise conflict("A budget already exists for this trip.", "trip_id") from exc
        return self.get_budget(budget_id)

    def delete_budget(self, budget_id: UUID) -> None:
        self.get_budget(budget_id)
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM budgets WHERE budget_id = ?", (str(budget_id),)
            )

    def list_expenses(
        self,
        trip_id: str | None = None,
        category: ExpenseCategory | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ExpenseRecord]:
        clauses: list[str] = []
        parameters: list[str] = []
        for clause, value in (
            ("trip_id = ?", trip_id),
            ("category = ?", category.value if category else None),
            ("date >= ?", date_from.isoformat() if date_from else None),
            ("date <= ?", date_to.isoformat() if date_to else None),
        ):
            if value is not None:
                clauses.append(clause)
                parameters.append(value)
        query = "SELECT * FROM expenses"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY date, expense_id"
        with self.connect() as connection:
            return [
                ExpenseRecord.model_validate(dict(row))
                for row in connection.execute(query, parameters)
            ]

    def get_expense(self, expense_id: UUID) -> ExpenseRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM expenses WHERE expense_id = ?", (str(expense_id),)
            ).fetchone()
        if row is None:
            raise not_found("Expense", str(expense_id))
        return ExpenseRecord.model_validate(dict(row))

    def create_expense(self, payload: ExpenseCreate) -> ExpenseRecord:
        expense_id = payload.expense_id or uuid4()
        now = _timestamp()
        fields = payload.model_dump(exclude={"expense_id"})
        values = _record_values(ExpenseFields.model_validate(fields)) | {
            "expense_id": str(expense_id),
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.connect() as connection:
                self._insert_expense(connection, values)
        except sqlite3.IntegrityError as exc:
            raise conflict(
                "An expense with this identifier already exists.", "expense_id"
            ) from exc
        return self.get_expense(expense_id)

    def update_expense(self, expense_id: UUID, payload: ExpenseUpdate) -> ExpenseRecord:
        if not payload.model_fields_set:
            raise invalid_update()
        current = self.get_expense(expense_id)
        changes = payload.model_dump(exclude_unset=True)
        required = {"trip_id", "category", "description", "amount", "currency", "date"}
        if any(changes.get(field, True) is None for field in required):
            raise invalid_update()
        current_fields = _fields_from_record(current, ExpenseFields)
        updated = ExpenseFields.model_validate(current_fields | changes)
        values = _record_values(updated) | {
            "expense_id": str(expense_id),
            "updated_at": _timestamp(),
        }
        assignments = ", ".join(
            f"{field} = :{field}"
            for field in (*ExpenseFields.model_fields, "updated_at")
        )
        with self.connect() as connection:
            connection.execute(
                f"UPDATE expenses SET {assignments} WHERE expense_id = :expense_id",
                values,
            )
        return self.get_expense(expense_id)

    def delete_expense(self, expense_id: UUID) -> None:
        self.get_expense(expense_id)
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM expenses WHERE expense_id = ?", (str(expense_id),)
            )
