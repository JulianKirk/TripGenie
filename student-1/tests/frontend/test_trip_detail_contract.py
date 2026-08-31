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
