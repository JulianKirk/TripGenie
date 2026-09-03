"""Add to Trip -- the form modal that opens over the details one.

What matters is the same thing the rest of the frontend tests care about: the
JSON turning into the right HTML. Here that means the chosen trip's window
reaching the date inputs, the nightly total being arithmetic this service did,
and a rejected submission coming back with the user's input still in it.
"""

from __future__ import annotations

import httpx

from .conftest import DETAIL

ACCOMMODATION_ID = DETAIL["id"]
DETAIL_URL = f"/accommodation/{ACCOMMODATION_ID}"
STAY = f"/accommodation/{ACCOMMODATION_ID}/stay"
ADD = f"/accommodation/{ACCOMMODATION_ID}/itineraries"


class TestTheButton:
    def test_the_details_modal_offers_add_to_trip_and_nothing_else(
        self, client, backend
    ):
        """The trip list is gone from here: the details modal is what you were
        reading, and adding is its own task in its own dialog."""
        response = client.get(DETAIL_URL)

        assert "Add to Trip" in response.text
        assert 'hx-target="#stay-modal"' in response.text
        # No trip list, so nothing is fetched to fill one.
        assert backend.itinerary_calls == []

    def test_opening_the_form_does_not_disturb_the_details_modal(self, client):
        """It is a second dialog, so the first one is still underneath."""
        response = client.get(STAY)

        assert response.text.count("<dialog") == 1
        assert "showModal()" in response.text


class TestTheForm:
    def test_every_trip_is_offered(self, client):
        text = client.get(STAY).text

        assert "Sydney Getaway" in text
        assert "Tokyo City Break" in text
        assert "Perth Workcation" in text

    def test_it_asks_for_both_dates_and_both_times(self, client):
        text = client.get(STAY).text

        assert text.count('type="date"') == 2
        assert text.count('type="time"') == 2
        for field in ("check_in", "check_in_time", "check_out", "check_out_time"):
            assert f'name="{field}"' in text

    def test_the_dates_are_bounded_by_the_chosen_trip(self, client):
        text = client.get(f"{STAY}?itinerary_id=trip_perth").text

        assert 'min="2027-08-18"' in text
        assert 'max="2027-08-24"' in text

    def test_changing_a_field_re_renders_the_form(self, client):
        """That is what keeps the total honest -- the arithmetic is done here,
        not by a script that could disagree with what gets stored."""
        text = client.get(STAY).text

        assert 'hx-trigger="change from:closest form"' in text
        assert 'hx-include="closest form"' in text


class TestTheTotal:
    def test_two_nights_at_the_nightly_rate(self, client):
        """DETAIL prices at 320.00 a night."""
        text = client.get(
            f"{STAY}?itinerary_id=trip_sydney&check_in=2027-04-01&check_out=2027-04-03"
        ).text

        assert "$640.00" in text
        assert "2 nights" in text

    def test_one_night_is_not_pluralised(self, client):
        text = client.get(
            f"{STAY}?itinerary_id=trip_sydney&check_in=2027-04-01&check_out=2027-04-02"
        ).text

        assert "1 night " in text or "1 night\n" in text
        assert "1 nights" not in text

    def test_no_check_out_means_no_total_rather_than_zero(self, client):
        text = client.get(f"{STAY}?itinerary_id=trip_sydney&check_in=2027-04-01").text

        assert "Pick a check-out date for the total." in text
        assert "$" not in text.split('class="stay__total"')[1].split("</div>")[0]

    def test_a_same_day_stay_says_so_rather_than_showing_zero(self, client):
        text = client.get(
            f"{STAY}?itinerary_id=trip_sydney&check_in=2027-04-01&check_out=2027-04-01"
        ).text

        assert "no nights, no charge" in text

    def test_an_unpriced_accommodation_says_so(self, client, backend):
        backend.response_detail = {**DETAIL, "price_per_night": None}

        text = client.get(
            f"{STAY}?itinerary_id=trip_sydney&check_in=2027-04-01&check_out=2027-04-03"
        ).text

        assert "No nightly rate recorded" in text


class TestSubmitting:
    def test_the_stay_reaches_the_backend(self, client, backend):
        client.put(
            f"{ADD}/trip_sydney",
            data={
                "check_in": "2027-04-01",
                "check_in_time": "15:00",
                "check_out": "2027-04-03",
                "check_out_time": "10:00",
            },
        )

        assert backend.itinerary_bodies == [
            {
                "check_in": "2027-04-01",
                "check_in_time": "15:00",
                "check_out": "2027-04-03",
                "check_out_time": "10:00",
            },
        ]

    def test_blank_optional_fields_are_sent_as_nothing_not_as_blank(
        self, client, backend
    ):
        """An untouched time input posts "", which is not a time. It has to
        become null on the way out or the backend rejects the whole stay."""
        client.put(f"{ADD}/trip_sydney", data={"check_in": "2027-04-01"})

        assert backend.itinerary_bodies == [
            {
                "check_in": "2027-04-01",
                "check_in_time": None,
                "check_out": None,
                "check_out_time": None,
            },
        ]

    def test_success_closes_the_form_and_toasts_into_the_details_modal(self, client):
        """The toast is position:fixed, and only a descendant of an open modal
        paints above its backdrop -- so it goes out-of-band into the dialog
        that is still there, not into the one being removed."""
        response = client.put(
            f"{ADD}/trip_sydney",
            data={"check_in": "2027-04-01", "trip": "Sydney Getaway"},
        )

        assert "<dialog" not in response.text
        assert 'hx-swap-oob="true"' in response.text
        assert 'id="modal-toast"' in response.text
        assert "Added to Sydney Getaway." in response.text


class TestErrors:
    def test_a_rejected_stay_keeps_what_the_user_typed(self, client, backend):
        backend.itinerary_write_response = httpx.Response(
            422, json={"detail": "Stay dates must fall inside the trip."}
        )

        response = client.put(
            f"{ADD}/trip_sydney",
            data={
                "check_in": "2027-09-09",
                "check_in_time": "15:00",
                "check_out": "2027-09-10",
                "check_out_time": "10:00",
            },
        )

        assert response.status_code == 200
        assert "Stay dates must fall inside the trip." in response.text
        # The dialog comes back rather than closing, with every value in place.
        assert "<dialog" in response.text
        for value in ("2027-09-09", "15:00", "2027-09-10", "10:00"):
            assert f'value="{value}"' in response.text

    def test_no_trips_says_so_rather_than_an_empty_form(self, client, backend):
        backend.itinerary_response = httpx.Response(200, json={"itineraries": []})

        text = client.get(STAY).text

        assert "No trips yet" in text
        assert '<form id="stay-form"' not in text


class TestDeepLink:
    """?accommodation=<id> opens that one's modal with the page.

    It is how the trip page links to a single accommodation: the modal is a
    fragment, so a bare link to it would be a page with no page around it.
    """

    def test_it_opens_the_modal_on_arrival(self, client):
        response = client.get(f"/?accommodation={ACCOMMODATION_ID}")

        assert response.status_code == 200
        assert "<dialog" in response.text
        assert "Harbour View Hotel" in response.text
        assert "showModal()" in response.text

    def test_the_plain_page_opens_no_modal(self, client):
        response = client.get("/")

        assert "<dialog" not in response.text

    def test_an_unknown_id_still_gives_the_list(self, client, backend):
        """The link came from another service's data, so a stale id is its
        problem to have, not a reason to lose the page."""
        backend.detail_response = httpx.Response(404, json={"detail": "not found"})
        missing = "3f1c8b52-0000-0000-0000-000000000000"

        response = client.get(f"/?accommodation={missing}")

        assert response.status_code == 200
        assert "could not be found" in response.text
        # The list is still there.
        assert "Harbour View Hotel" in response.text
