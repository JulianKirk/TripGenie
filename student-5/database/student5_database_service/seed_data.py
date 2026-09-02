from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


def _id(kind: str, number: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"tripgenie/student-5/{kind}/{number}"))


SEED_BUDGETS = [
    {
        "budget_id": _id("budget", number),
        "trip_id": f"trip_student5_demo_{number:02d}",
        "currency": "AUD",
        "total_budget": f"{2000 + number * 500}.00",
        "accommodation_budget": f"{700 + number * 100}.00",
        "transport_budget": f"{400 + number * 50}.00",
        "activities_budget": f"{200 + number * 25}.00",
        "food_budget": f"{300 + number * 50}.00",
        "other_budget": "100.00",
    }
    for number in range(1, 11)
]

_CATEGORIES = (
    "accommodation",
    "transport",
    "activities",
    "food",
    "shopping",
    "other",
)

SEED_EXPENSES = [
    {
        "expense_id": _id("expense", number),
        "trip_id": f"trip_student5_demo_{number:02d}",
        "category": _CATEGORIES[(number - 1) % len(_CATEGORIES)],
        "description": f"Demonstration expense {number:02d}",
        "amount": f"{25 + number * 10}.00",
        "currency": "AUD",
        "date": f"2026-09-{number:02d}",
        "payment_method": "card",
        "notes": "Deterministic Release 0 seed data.",
    }
    for number in range(1, 11)
]
