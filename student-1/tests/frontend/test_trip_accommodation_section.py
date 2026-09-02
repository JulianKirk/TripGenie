"""The Accommodation section on the trip page.

A trip stores an accommodation's id; the name and the price come from student 2
by way of this service's backend. What matters here is that the page draws the
stay, links out to the accommodation service for the detail, and offers a way
to take it back off the trip.
"""

from __future__ import annotations

SYDNEY = "trip_2027_sydney_getaway"


class TestTheSection:
    def test_a_booked_stay_shows_its_name_dates_and_price(self, client, backend_api):
        backend_api.pin_accommodation(
            SYDNEY,
            accommodation_id="acc_harbour",
            name="Harbour View Hotel",
            date="2027-04-01",
            check_out="2027-04-03",
            price_per_night=220.0,
            total_price=440.0,
        )

        response = client.get(f"/trips/{SYDNEY}")

        assert response.status_code == 200
        assert "Harbour View Hotel" in response.text
        assert "2027-04-01" in response.text
        assert "2027-04-03" in response.text
        assert "$440.00" in response.text

    def test_a_row_links_to_the_accommodation_service(self, client, backend_api):
        """Clicking the row opens that accommodation on student 2's own page,
        which is the service that owns it."""
        backend_api.pin_accommodation(SYDNEY, accommodation_id="acc_harbour")

        response = client.get(f"/trips/{SYDNEY}")

        assert "http://localhost:9003/?accommodation=acc_harbour" in response.text

    def test_the_row_link_opts_out_of_boosting(self, client, backend_api):
        """The shell sets hx-boost on every anchor inside it. This one leaves
        for another origin, so boosted it becomes a cross-origin XHR that CORS
        blocks -- the click does nothing at all. It has to opt out."""
        backend_api.pin_accommodation(SYDNEY, accommodation_id="acc_harbour")

        response = client.get(f"/trips/{SYDNEY}")
        row = response.text[response.text.index('class="stay-row__link"') :]

        assert 'hx-boost="false"' in row[: row.index(">")]

    def test_every_row_offers_a_bin(self, client, backend_api):
        backend_api.pin_accommodation(
            SYDNEY, accommodation_id="acc_harbour", name="Harbour View Hotel"
        )

        response = client.get(f"/trips/{SYDNEY}")

        assert (
            f"/trips/{SYDNEY}/accommodations/acc_harbour/remove" in response.text
        )
        assert "Remove Harbour View Hotel from this trip" in response.text

    def test_an_unnamed_stay_falls_back_to_its_id(self, client, backend_api):
        """Student 2 was unreachable when the backend built this, so the row
        shows what we have rather than an empty line."""
        backend_api.pin_accommodation(SYDNEY, accommodation_id="acc_unknown")

        response = client.get(f"/trips/{SYDNEY}")

        assert "acc_unknown" in response.text

    def test_a_stay_with_no_checkout_says_so_rather_than_showing_a_blank(
        self, client, backend_api
    ):
        backend_api.pin_accommodation(
            SYDNEY, accommodation_id="acc_harbour", check_out=None
        )

        response = client.get(f"/trips/{SYDNEY}")

        assert "no check-out recorded" in response.text

    def test_a_trip_with_no_accommodation_says_so(self, client):
        response = client.get(f"/trips/{SYDNEY}")

        assert "No accommodation booked for this trip yet" in response.text


class TestRemoving:
    def test_the_bin_asks_before_removing(self, client, backend_api):
        """Same as deleting an itinerary item: a confirmation screen, not a
        one-click destructive action."""
        backend_api.pin_accommodation(
            SYDNEY, accommodation_id="acc_harbour", name="Harbour View Hotel"
        )

        response = client.get(f"/trips/{SYDNEY}/accommodations/acc_harbour/remove")

        assert response.status_code == 200
        assert "Remove accommodation" in response.text
        assert "Harbour View Hotel" in response.text
        # The accommodation itself survives; only the pin goes.
        assert "not deleted" in response.text

    def test_confirming_removes_it_and_returns_to_the_trip(self, client, backend_api):
        backend_api.pin_accommodation(SYDNEY, accommodation_id="acc_harbour")

        response = client.post(
            f"/trips/{SYDNEY}/accommodations/acc_harbour/remove",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"].endswith(f"/trips/{SYDNEY}")
        assert backend_api.accommodations[SYDNEY] == []

    def test_removing_one_that_is_not_there_shows_an_error_not_a_crash(
        self, client
    ):
        response = client.post(
            f"/trips/{SYDNEY}/accommodations/acc_missing/remove",
            follow_redirects=False,
        )

        assert response.status_code == 404
        assert "Unable to remove accommodation" in response.text
