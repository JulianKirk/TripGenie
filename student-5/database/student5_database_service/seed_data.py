from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


def _id(kind: str, number: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"tripgenie/student-5/{kind}/{number}"))


_TRIPS = (
    ("trip_2026_sydney_long_weekend", "2026-10-03"),
    ("trip_2026_melbourne_food_trail", "2026-11-13"),
    ("trip_2027_tokyo_spring_visit", "2027-03-29"),
    ("trip_2026_gold_coast_family_break", "2026-12-22"),
    ("trip_2027_queenstown_ski_escape", "2027-07-11"),
    ("trip_2026_singapore_stopover", "2026-09-02"),
    ("trip_2026_perth_workcation", "2026-08-20"),
    ("trip_2026_hobart_weekend_escape", "2026-06-12"),
    ("trip_2027_brisbane_city_break", "2027-01-22"),
    ("trip_2027_adelaide_festival_week", "2027-02-27"),
)


SEED_BUDGETS = [
    {
        "budget_id": _id("budget", number),
        "trip_id": trip_id,
        "currency": "AUD",
        "total_budget": f"{2000 + number * 500}.00",
        "accommodation_budget": f"{700 + number * 100}.00",
        "transport_budget": f"{400 + number * 50}.00",
        "activities_budget": f"{200 + number * 25}.00",
        "food_budget": f"{300 + number * 50}.00",
        "other_budget": "100.00",
    }
    for number, (trip_id, _) in enumerate(_TRIPS, start=1)
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
        "trip_id": trip_id,
        "category": _CATEGORIES[(number - 1) % len(_CATEGORIES)],
        "description": f"Demonstration expense {number:02d}",
        "amount": f"{25 + number * 10}.00",
        "currency": "AUD",
        "date": expense_date,
        "payment_method": "card",
        "notes": "Deterministic Release 0 seed data.",
    }
    for number, (trip_id, expense_date) in enumerate(_TRIPS, start=1)
]
