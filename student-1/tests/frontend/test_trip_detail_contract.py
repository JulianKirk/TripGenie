"""The frontend mirrors the backend's models with `extra="forbid"`, so a field
the backend starts sending is a parse failure here until it is mirrored too.
This is the guard for that: it fails if the mirror drifts.
"""

from __future__ import annotations

from frontend_service.models import TripDetail


def test_trip_detail_accepts_the_accommodations_the_backend_now_sends() -> None:
    detail = TripDetail.model_validate(
        {
            "id": "trip_2027_sydney_getaway",
            "name": "Sydney Getaway",
            "destination": "Sydney",
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
            "traveller_count": 2,
            "status": "planned",
            "notes": None,
            "days": [],
            "accommodations": [
                {
                    "trip_id": "trip_2027_sydney_getaway",
                    "accommodation_id": "0f2b1c4e-aaaa-bbbb-cccc-000000000001",
                    "date": "2027-04-01",
                },
            ],
        },
    )

    assert detail.accommodations[0].accommodation_id == (
        "0f2b1c4e-aaaa-bbbb-cccc-000000000001"
    )


def test_trip_detail_accepts_populated_activities() -> None:
    detail = TripDetail.model_validate(
        {
            "id": "trip_2027_sydney_getaway",
            "name": "Sydney Getaway",
            "destination": "Sydney",
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
            "traveller_count": 2,
            "status": "planned",
            "days": [],
            "activities": [
                {
                    "trip_id": "trip_2027_sydney_getaway",
                    "activity_id": "activity_harbour_cruise",
                    "date": "2027-04-02",
                    "start_time": "14:30",
                    "name": "Harbour Cruise",
                    "price": "89.00",
                    "pricing_basis": "PER_PERSON",
                    "duration_minutes": 90,
                }
            ],
        }
    )

    assert detail.activities[0].name == "Harbour Cruise"
    assert detail.activities[0].price == "89.00"


def test_trip_detail_accepts_empty_activities() -> None:
    detail = TripDetail.model_validate(
        {
            "id": "trip_2027_sydney_getaway",
            "name": "Sydney Getaway",
            "destination": "Sydney",
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
            "traveller_count": 2,
            "status": "planned",
            "days": [],
            "activities": [],
        }
    )

    assert detail.activities == []


def test_trip_detail_accepts_populated_transport() -> None:
    detail = TripDetail.model_validate(
        {
            "id": "trip_2027_sydney_getaway",
            "name": "Sydney Getaway",
            "destination": "Sydney",
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
            "traveller_count": 2,
            "status": "planned",
            "days": [],
            "transport": [
                {
                    "trip_id": "trip_2027_sydney_getaway",
                    "transport_id": "transport_sydney_train",
                    "traveller_count": 2,
                    "plan_status": "confirmed",
                    "added_on": "2027-04-01",
                    "notes": "Quiet carriage requested.",
                    "origin": "Central",
                    "destination": "Circular Quay",
                    "provider": "Sydney Trains",
                    "type": "train",
                    "departure_time": "2027-04-01T10:00:00+11:00",
                    "arrival_time": "2027-04-01T10:15:00+11:00",
                    "duration_minutes": 15,
                    "price": 5.20,
                    "pricing_basis": "per_traveller",
                    "estimated_cost": 10.40,
                }
            ],
        }
    )

    assert detail.transport[0].provider == "Sydney Trains"
    assert detail.transport[0].estimated_cost == 10.40


def test_trip_detail_still_parses_without_accommodations() -> None:
    """Older responses, and the day-selection routes, omit the field entirely."""
    detail = TripDetail.model_validate(
        {
            "id": "trip_2027_sydney_getaway",
            "name": "Sydney Getaway",
            "destination": "Sydney",
            "start_date": "2027-04-01",
            "end_date": "2027-04-03",
            "traveller_count": 2,
            "status": "planned",
            "days": [],
        },
    )

    assert detail.accommodations == []
    assert detail.activities == []
    assert detail.transport == []
