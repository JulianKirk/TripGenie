"""The Add-to-Itinerary picker.

What matters here is the same thing the rest of the frontend tests care about:
the JSON turning into the right HTML. The ticked state has to pick the verb the
button sends, because that is the whole of the toggle -- there is no JS deciding
it at click time.
"""

from __future__ import annotations

import httpx

from .conftest import DETAIL

ACCOMMODATION_ID = DETAIL["id"]
PICKER = f"/accommodation/{ACCOMMODATION_ID}/itineraries"


class TestModal:
    def test_the_modal_offers_the_disclosure_without_fetching_the_list(
        self, client, backend
    ):
        """The list is fetched on first open, not with the modal: most opens
        are a read of the facts, not an edit."""
        response = client.get(f"/accommodation/{ACCOMMODATION_ID}")

        assert "Add to Itinerary" in response.text
        assert "<details" in response.text
        assert backend.itinerary_calls == []


class TestPicker:
    def test_an_unticked_itinerary_offers_to_add_it(self, client):
        response = client.get(PICKER)

        assert response.status_code == 200
        assert "Sydney Getaway" in response.text
        button = _button(response.text, "Sydney Getaway")
        assert 'aria-checked="false"' in button
        assert "hx-put=" in button
        assert "hx-delete=" not in button

    def test_a_ticked_itinerary_offers_to_remove_it(self, client):
        button = _button(client.get(PICKER).text, "Tokyo City Break")

        assert 'aria-checked="true"' in button
        assert "hx-delete=" in button
        assert "hx-put=" not in button
        assert "✓" in button

    def test_adding_repaints_the_whole_picker_with_the_new_tick(self, client, backend):
        response = client.put(f"{PICKER}/trip_sydney")

        assert response.status_code == 200
        assert backend.itinerary_calls == [("PUT", f"{PICKER}/trip_sydney")]
        # Both rows come back, so one response repaints the dropdown.
        assert 'aria-checked="true"' in _button(response.text, "Sydney Getaway")
        assert 'aria-checked="true"' in _button(response.text, "Tokyo City Break")

    def test_removing_repaints_the_whole_picker_without_the_tick(self, client, backend):
        response = client.delete(f"{PICKER}/trip_tokyo")

        assert response.status_code == 200
        assert backend.itinerary_calls == [("DELETE", f"{PICKER}/trip_tokyo")]
        assert 'aria-checked="false"' in _button(response.text, "Tokyo City Break")

    def test_no_itineraries_says_so_rather_than_rendering_nothing(
        self, client, backend
    ):
        backend.itinerary_response = httpx.Response(200, json={"itineraries": []})

        response = client.get(PICKER)

        assert "No itineraries yet" in response.text


class TestConfirmBeforeRemoving:
    """Removing asks first; adding does not. hx-confirm is htmx's own
    window.confirm(), so the OK/Cancel pair is the browser's."""

    def test_a_ticked_itinerary_asks_before_removing(self, client):
        button = _button(client.get(PICKER).text, "Tokyo City Break")

        assert "hx-confirm=" in button
        assert "Remove this accommodation from Tokyo City Break?" in button

    def test_an_unticked_itinerary_does_not_ask(self, client):
        button = _button(client.get(PICKER).text, "Sydney Getaway")

        assert "hx-confirm=" not in button

    def test_the_prompt_follows_the_state_after_a_toggle(self, client):
        """The button that was just added becomes the one that asks."""
        added = _button(client.put(f"{PICKER}/trip_sydney").text, "Sydney Getaway")

        assert "Remove this accommodation from Sydney Getaway?" in added


class TestToast:
    def test_adding_announces_which_itinerary_it_landed_on(self, client):
        response = client.put(f"{PICKER}/trip_sydney")

        assert 'class="toast"' in response.text
        assert 'role="status"' in response.text
        assert "Added to Sydney Getaway." in response.text

    def test_removing_shows_no_toast(self, client):
        """The confirm already covered that decision -- announcing it after the
        fact is a second interruption for the same click."""
        response = client.delete(f"{PICKER}/trip_tokyo")

        assert 'class="toast"' not in response.text

    def test_merely_opening_the_picker_shows_no_toast(self, client):
        assert 'class="toast"' not in client.get(PICKER).text

    def test_the_toast_sits_inside_the_swapped_fragment(self, client):
        """It has to be a descendant of the modal <dialog> to paint above the
        backdrop, and the fragment is what gets swapped into it."""
        text = client.put(f"{PICKER}/trip_sydney").text

        assert text.index('id="itinerary-picker"') < text.index('class="toast"')
        assert text.rstrip().endswith("</div>")


class TestErrors:
    def test_an_unreachable_itinerary_service_degrades_only_the_picker(
        self, client, backend
    ):
        backend.itinerary_response = httpx.Response(
            503, json={"detail": "itinerary service unavailable"}
        )

        response = client.get(PICKER)

        assert response.status_code == 200
        assert "itinerary service unavailable" in response.text
        assert "hx-put=" not in response.text

    def test_a_bad_accommodation_id_is_a_404_from_routing(self, client, backend):
        assert client.get("/accommodation/not-a-uuid/itineraries").status_code == 404
        assert backend.itinerary_calls == []


def _button(html: str, label: str) -> str:
    """The one <button> whose label is `label`."""
    for fragment in html.split("<button"):
        if label in fragment:
            return fragment.split("</button>")[0]
    missing = f"no button labelled {label!r}"
    raise AssertionError(missing)
