from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Any

import pytest
from student4_backend_service.assistant_constraints import (
    ClarificationError,
    RequestConstraints,
    parse_constraints,
    party_total,
)
from student4_backend_service.schemas import Activity

from .test_assistant import DETAIL


def activity(**changes: Any) -> Activity:
    return Activity.model_validate({**DETAIL, **changes})


@pytest.mark.parametrize(
    "question",
    [
        "Find an activity for 4 adults with a total budget of 100 AUD.",
        "What can four people do with no more than AUD 100 total?",
        "For a party of four, find something under $100 in total.",
    ],
)
def test_party_budget_is_extracted_and_checked_with_decimal(question: str) -> None:
    constraints = parse_constraints(question)
    assert constraints.party_size == 4
    assert constraints.total_budget
    assert not constraints.accepts(activity(price="30.00"))
    assert constraints.accepts(activity(price="22.00"))
    assert constraints.accepts(activity(price="80.00", pricing_basis="FLAT_ADMISSION"))


def test_total_and_listed_bounds_are_different_and_strict_under_is_respected() -> None:
    total = parse_constraints("For two people under $90 total")
    listed = parse_constraints("For two people no more than $45 per person")
    assert not total.accepts(activity())
    assert listed.accepts(activity())
    assert total.price_max == Decimal("89.99")


@pytest.mark.parametrize(
    "question",
    [
        "At least $100 and no more than $20",
        "Under $50 or over $100",
        "For 2 adults and 3 children under $100 total",
        "Under $100 in total and $20 per person",
        "Find something on 2026-02-30",
    ],
)
def test_ambiguous_or_conflicting_constraints_require_clarification(
    question: str,
) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(question)


def test_missing_party_size_for_total_budget_requires_clarification() -> None:
    with pytest.raises(ClarificationError):
        parse_constraints("Under $100 total").ready()


def test_inactive_and_party_capacity_are_rejected() -> None:
    constraints = parse_constraints("For four people")
    assert not constraints.accepts(activity(is_active=False))
    assert not constraints.accepts(activity(maximum_participants=3))
    assert not constraints.accepts(activity(minimum_participants=5))


def test_weekly_and_one_off_schedules_match_inclusive_date_range() -> None:
    constraints = RequestConstraints(
        start_date=date(2026, 10, 5), end_date=date(2026, 10, 7)
    )
    assert not constraints.accepts(activity())  # Saturday
    schedule = {**DETAIL["availability_schedules"][0], "day_of_week": "TUESDAY"}
    assert constraints.accepts(activity(availability_schedules=[schedule]))
    one_off = {
        **schedule,
        "recurring_weekly": False,
        "day_of_week": None,
        "date": "2026-10-07",
    }
    assert constraints.accepts(activity(availability_schedules=[one_off]))
    one_off["date"] = "2026-10-08"
    assert not constraints.accepts(activity(availability_schedules=[one_off]))


def test_window_must_fit_whole_activity_duration() -> None:
    constraints = parse_constraints("On 2026-10-10 from 10:30 to 11:00")
    assert not constraints.accepts(activity())
    constraints = parse_constraints("On 2026-10-10 from 10:00 to 11:00")
    assert constraints.accepts(activity())


def test_search_arguments_cannot_change_locked_budget_or_invent_filters() -> None:
    constraints = parse_constraints("For 4 adults under $100 total")
    result = constraints.search_arguments(
        {
            "filters": {
                "price": {"max": "999.00"},
                "party_size": 1,
                "accessibility": {"wheelchair_accessible": True},
                "availability": {"date": "2023-03-01"},
                "location": {"country": "Australia", "city": "Sydney"},
            }
        }
    )
    assert result["filters"]["price"] == {"max": "99.99"}
    assert result["filters"]["party_size"] == 4
    assert "accessibility" not in result["filters"]
    assert "availability" not in result["filters"]
    assert result["filters"]["location"]["city"] == "Sydney"


def test_selected_trip_supplies_party_and_dates_without_model_input() -> None:
    constraints = parse_constraints("Find activities under $100 total")
    constraints = constraints.with_trip(
        {"start_date": "2026-10-05", "end_date": "2026-10-07", "traveller_count": 4}
    )
    constraints.ready()
    assert constraints.party_size == 4
    assert constraints.start_date == date(2026, 10, 5)
    assert not constraints.accepts(activity(price="22.00"))  # wrong weekday


@pytest.mark.parametrize(
    "question",
    [
        "Under $1,000",
        "Under $100.999",
        "Under $-50",
        "For twenty five people under $100 total",
        "For -4 people under $100 total",
        "On 5 October 2026",
        "Not before 2026-10-10",
        "On 2026-10-10 or 2026-10-17",
        "On 2026-10-10 from 1:00 pm to 3:00 pm",
    ],
)
def test_unsupported_forms_never_become_partial_constraints(question: str) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(question)


def test_no_booking_required_is_not_inverted() -> None:
    assert (
        parse_constraints("Activities with no booking required").booking_required
        is False
    )


@pytest.mark.parametrize(
    "question",
    [
        "Under AUD 1,000",
        "Under 100.999 dollars",
        "Under -50 dollars",
        "For one hundred people",
        "For 2.555 people",
        "For 25-30 people",
        "Wheelchair access is not needed",
        "No step-free requirement",
        "On 2026-10-10 except 2026-10-11",
        "On 10/10/2026",
        "On 2026-10-10 after 10:00",
        "On 2026-10-10 from 10am to noon",
        "Under $50k",
        "A budget of 100 for four people",
    ],
)
def test_unsupported_constraint_tokens_require_clarification(question: str) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(question)


@pytest.mark.parametrize(
    "question",
    [
        "Under $50abc",
        "Under AUD lots",
        "Under $50 and over $many",
        "On 2026-10-10 and 2026-10-17",
    ],
)
def test_partial_money_and_discrete_dates_are_rejected(question: str) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(question)


def test_valid_accessibility_and_inclusive_price_are_not_negation() -> None:
    value = parse_constraints("Wheelchair activities no more than $50")
    assert value.accessibility == ("wheelchair_accessible",)
    assert value.price_max == Decimal(50)


def test_normal_polite_request_is_not_a_month_name() -> None:
    assert parse_constraints("May I see activities under $50?").price_max == Decimal(
        "49.99"
    )


@pytest.mark.parametrize(
    "question",
    [
        "On Friday 2026-10-10",
        "On 2026-10-10 at 10:00 or 12:00",
        "On 2026-10-10 not from 10:00 to 12:00",
    ],
)
def test_temporal_qualifiers_cannot_be_silently_discarded(question: str) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(question)


def test_checked_summary_includes_accessibility_and_booking() -> None:
    constraints = parse_constraints("Wheelchair activities without booking")
    assert "wheelchair accessible" in constraints.summary()
    assert "no booking required" in constraints.summary()


@pytest.mark.parametrize(
    "question",
    ["Activities under 100", "Under EUR 100", "Under 100 euros", "At most USD 50"],
)
def test_unconfirmed_price_currency_needs_clarification(question: str) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(question)


@pytest.mark.parametrize(
    ("bound", "expected_min", "expected_max"),
    [
        ("under", None, "123456789012345678901234567890.11"),
        ("above", "123456789012345678901234567890.13", None),
        ("at most", None, "123456789012345678901234567890.12"),
    ],
)
def test_large_price_bounds_preserve_exact_cents(
    bound: str,
    expected_min: str | None,
    expected_max: str | None,
) -> None:
    constraints = parse_constraints(f"{bound} AUD 123456789012345678901234567890.12")
    assert constraints.price_min == (Decimal(expected_min) if expected_min else None)
    assert constraints.price_max == (Decimal(expected_max) if expected_max else None)


@pytest.mark.parametrize(
    ("price", "people", "budget"),
    [
        ("123456789012345678901234567890.12", 3, "370370367037037036703703703670.35"),
        ("0.01", 10**30 + 1, "10000000000000000000000000000.00"),
    ],
)
def test_large_party_totals_cannot_round_down_into_budget(
    price: str,
    people: int,
    budget: str,
) -> None:
    constraints = RequestConstraints(
        party_size=people, total_budget=True, price_max=Decimal(budget)
    )
    assert not constraints.accepts(activity(price=price))


def test_exact_arithmetic_does_not_mutate_callers_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 6
        assert party_total(Decimal("123456789.12"), 3) == Decimal("370370367.36")
        assert parse_constraints("under AUD 123456789.12").price_max == Decimal(
            "123456789.11"
        )
        assert context.prec == 6


def test_no_less_than_is_an_inclusive_lower_bound() -> None:
    constraints = parse_constraints("Find activities for no less than AUD 100")
    assert constraints.price_min == Decimal(100)
    assert constraints.price_max is None
    assert not constraints.accepts(activity(price="99.99"))
    assert constraints.accepts(activity(price="100.00"))
    assert constraints.accepts(activity(price="100.01"))


@pytest.mark.parametrize(
    "bound",
    [
        "over",
        "above",
        "less than",
        "at least",
        "at most",
        "no less than",
        "no more than",
        "up to",
    ],
)
def test_negated_price_bounds_do_not_reverse_the_requested_budget(bound: str) -> None:
    with pytest.raises(ClarificationError):
        parse_constraints(f"Find activities not {bound} AUD 100")
