from __future__ import annotations

import pytest
from starlette.datastructures import QueryParams
from student4_frontend_service.query import (
    QueryInputError,
    build_search_body,
    search_body_to_params,
)


def test_empty_form_has_only_default_paging() -> None:
    assert build_search_body(QueryParams()) == {"limit": 20, "offset": 0}


def test_search_body_to_params_refills_every_advanced_filter() -> None:
    params = search_body_to_params(
        {
            "text": "harbour",
            "location": {"country": "australia", "city": "sydney"},
            "categories": {"codes": ["OUTDOOR", "TOUR"], "match": "ALL"},
            "price": {"min": "10.00", "max": "90.00"},
            "duration_minutes": {"min": 30, "max": 180},
            "party_size": 2,
            "youngest_age": 8,
            "oldest_age": 70,
            "booking_required": False,
            "accessibility": {"wheelchair_accessible": True},
            "availability": {
                "date": "2027-04-02",
                "start_time": "09:00",
                "end_time": "12:00",
            },
            "sort": "PRICE_ASC",
            "limit": 20,
            "offset": 0,
        }
    )

    assert params.getlist("category") == ["OUTDOOR", "TOUR"]
    assert dict(params) == {
        "text": "harbour",
        "country": "australia",
        "city": "sydney",
        "category": "TOUR",
        "category_match": "ALL",
        "price_min": "10.00",
        "price_max": "90.00",
        "duration_min": "30",
        "duration_max": "180",
        "party_size": "2",
        "youngest_age": "8",
        "oldest_age": "70",
        "booking_required": "false",
        "wheelchair_accessible": "true",
        "date": "2027-04-02",
        "start_time": "09:00",
        "end_time": "12:00",
        "sort": "PRICE_ASC",
        "limit": "20",
    }


def test_complete_filter_form_builds_documented_nested_body() -> None:
    params = QueryParams(
        "text=harbour&country=australia&city=sydney&street=circular"
        "&category=OUTDOOR&category=TOUR&category=OUTDOOR&category_match=ALL"
        "&price_min=10&price_max=100&duration_min=60&duration_max=180"
        "&party_size=4&youngest_age=12&oldest_age=70&booking_required=true"
        "&accessible_toilet=on&date=2026-10-17&start_time=09%3A00"
        "&end_time=14%3A00&sort=PRICE_ASC&limit=10&offset=20"
    )

    assert build_search_body(params) == {
        "text": "harbour",
        "location": {
            "country": "australia",
            "city": "sydney",
            "street": "circular",
        },
        "categories": {"codes": ["OUTDOOR", "TOUR"], "match": "ALL"},
        "price": {"min": "10.00", "max": "100.00"},
        "duration_minutes": {"min": 60, "max": 180},
        "party_size": 4,
        "youngest_age": 12,
        "oldest_age": 70,
        "booking_required": True,
        "accessibility": {"accessible_toilet": True},
        "availability": {
            "date": "2026-10-17",
            "start_time": "09:00",
            "end_time": "14:00",
        },
        "sort": "PRICE_ASC",
        "limit": 10,
        "offset": 20,
    }


def test_blank_values_are_omitted_and_city_without_country_is_dropped() -> None:
    params = QueryParams("text=%20&country=&city=sydney&street=&price_max=")

    assert build_search_body(params) == {"limit": 20, "offset": 0}


def test_booking_false_is_a_real_boolean() -> None:
    assert build_search_body(QueryParams("booking_required=false")) == {
        "booking_required": False,
        "limit": 20,
        "offset": 0,
    }


def test_date_can_be_used_without_times() -> None:
    assert build_search_body(QueryParams("date=2027-04-01")) == {
        "availability": {"date": "2027-04-01"},
        "limit": 20,
        "offset": 0,
    }


@pytest.mark.parametrize(
    "query",
    [
        "start_time=09%3A00&end_time=10%3A00",
        "date=2027-04-01&start_time=09%3A00",
        "date=2027-04-01&end_time=10%3A00",
    ],
)
def test_server_rejects_unpaired_date_time_controls(query: str) -> None:
    with pytest.raises(QueryInputError, match=r"date|together"):
        build_search_body(QueryParams(query))


def test_invalid_numeric_values_are_forwarded_for_backend_validation() -> None:
    assert build_search_body(QueryParams("price_max=abc&party_size=many")) == {
        "price": {"max": "abc"},
        "party_size": "many",
        "limit": 20,
        "offset": 0,
    }


def test_management_and_paging_are_canonicalised() -> None:
    assert build_search_body(
        QueryParams("include_inactive=true&limit=999&offset=-4")
    ) == {"include_inactive": True, "limit": 100, "offset": 0}


def test_junk_paging_uses_defaults() -> None:
    assert build_search_body(QueryParams("limit=many&offset=later")) == {
        "limit": 20,
        "offset": 0,
    }
