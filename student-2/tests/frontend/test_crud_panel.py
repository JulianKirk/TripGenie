"""The create/edit/delete surface on the accommodation page.

What these cover is the translation the frontend service exists to do: the
create/edit form's inputs into the accommodation message the backend documents,
and the answer back into the fragments HTMX swaps. The backend is the fake in
conftest.py -- the real write path is exercised in tests/e2e.
"""

from __future__ import annotations

import httpx

from tests.frontend.conftest import DETAIL, LISTING

NEW = "/accommodation/new"
EDIT = f"/accommodation/{LISTING['id']}/edit"
ONE = f"/accommodation/{LISTING['id']}"

FORM = {
    "name": "Blue Mountains Cabin",
    "type": "camping",
    "description": "A cabin.",
    "price_per_night": "120.50",
    "availability_status": "available",
    "rating": "4.2",
    "country": "australia",
    "city": "katoomba",
    "street": "cliff drive",
    "street_number": "3",
    "room_count": "2",
    "bed_count": "3",
    "room_description": "Two bedrooms.",
    "amenities": ["wifi", "parking"],
    "bed_types": ["queen", "bunk"],
}


class TestForm:
    def test_new_renders_an_empty_create_form(self, client):
        page = client.get(NEW)
        assert page.status_code == 200
        assert 'hx-post="http://testserver/accommodation"' in page.text
        assert "New accommodation" in page.text
        # Nothing prefilled, and no stale id to PUT to.
        assert "hx-put" not in page.text

    def test_edit_prefills_from_the_stored_accommodation(self, client):
        page = client.get(EDIT)
        assert f'hx-put="http://testserver{ONE}"' in page.text
        assert DETAIL["name"] in page.text
        assert 'value="sydney"' in page.text
        assert 'value="george street"' in page.text
        # The stored type, amenities and bed types come back chosen.
        assert '<option value="hotel" selected>' in page.text
        assert page.text.count("checked") == len(DETAIL["amenities"]) + len(
            DETAIL["room_details"]["bed_types"]
        )

    def test_edit_says_a_blank_field_is_not_a_clear(self, client):
        # The backend's PUT is a merge with no way to unset a field, so the
        # form has to say so rather than look like it lost the value.
        assert "keep their saved value" in client.get(EDIT).text

    def test_edit_surfaces_a_backend_failure(self, client, backend):
        backend.detail_response = httpx.Response(404, json={"detail": "gone"})
        assert "gone" in client.get(EDIT).text


class TestCreate:
    def test_sends_the_form_as_the_accommodation_message(self, client, backend):
        client.post("/accommodation", data=FORM)
        method, path, body = backend.writes[-1]
        assert (method, path) == ("POST", "/accommodation")
        assert body == {
            "name": "Blue Mountains Cabin",
            "type": "camping",
            "description": "A cabin.",
            "price_per_night": "120.50",
            "availability_status": "available",
            "rating": "4.2",
            "amenities": ["wifi", "parking"],
            "location_details": {
                "country": "australia",
                "city": "katoomba",
                "street": "cliff drive",
                "street_number": "3",
            },
            "room_details": {
                "room_count": "2",
                "bed_count": "3",
                "description": "Two bedrooms.",
                "bed_types": ["queen", "bunk"],
            },
        }

    def test_a_blank_optional_field_is_not_sent(self, client, backend):
        client.post("/accommodation", data={**FORM, "rating": "", "street": " "})
        _, _, body = backend.writes[-1]
        # An empty input is "not given", not an empty string the backend would
        # have to store.
        assert "rating" not in body
        assert "street" not in body["location_details"]

    def test_success_closes_the_dialog_and_refreshes_the_list(self, client):
        saved = client.post("/accommodation", data=FORM)
        assert saved.headers["HX-Trigger"] == "accommodations-changed"
        # No <dialog> in the body, so the swap that targets the form's dialog
        # removes it.
        assert "<dialog" not in saved.text
        assert "Added Blue Mountains Cabin." in saved.text

    def test_a_rejected_create_comes_back_with_the_error_and_the_values(
        self, client, backend
    ):
        backend.write_response = httpx.Response(400, json={"detail": "unknown country"})
        page = client.post("/accommodation", data={**FORM, "country": "narnia"})
        assert "unknown country" in page.text
        # Everything typed is still there to correct.
        assert 'value="Blue Mountains Cabin"' in page.text
        assert 'value="narnia"' in page.text
        assert "New accommodation" in page.text


class TestUpdate:
    def test_sends_only_what_the_form_holds(self, client, backend):
        client.put(ONE, data={"name": "Renamed", "rating": "5"})
        method, path, body = backend.writes[-1]
        assert (method, path) == ("PUT", ONE)
        # A merge: the fields the form did not carry are simply absent.
        assert body == {"name": "Renamed", "rating": "5"}

    def test_success_closes_both_dialogs_and_refreshes(self, client):
        saved = client.put(ONE, data=FORM)
        assert saved.headers["HX-Trigger"] == "accommodations-changed"
        # The details dialog behind the form is showing a stale row, so it goes
        # out of band with the form itself.
        assert '<div id="modal" hx-swap-oob="true"></div>' in saved.text
        assert "Saved Blue Mountains Cabin." in saved.text

    def test_a_rejected_edit_comes_back_as_the_edit_form(self, client, backend):
        backend.write_response = httpx.Response(
            400, json={"detail": "city requires country"}
        )
        page = client.put(ONE, data={"city": "sydney"})
        assert "city requires country" in page.text
        # Still the edit form, so a retry goes back to the same accommodation.
        assert f'hx-put="http://testserver{ONE}"' in page.text


class TestDelete:
    def test_calls_the_backend_and_refreshes(self, client, backend):
        gone = client.delete(ONE)
        assert backend.writes[-1][:2] == ("DELETE", ONE)
        assert gone.headers["HX-Trigger"] == "accommodations-changed"
        assert "Accommodation deleted." in gone.text
        assert '<div id="modal" hx-swap-oob="true"></div>' in gone.text

    def test_shows_what_the_backend_said_when_it_fails(self, client, backend):
        backend.write_response = httpx.Response(404, json={"detail": "not found"})
        assert "not found" in client.delete(ONE).text


class TestPage:
    def test_offers_a_create_button_and_a_place_for_the_form(self, client):
        page = client.get("/").text
        assert "Add accommodation" in page
        assert 'id="form-modal"' in page
        assert 'id="page-toast"' in page

    def test_the_filter_form_refreshes_itself_after_a_write(self, client):
        # How the list gets back in step without any write route knowing the
        # filters currently on screen.
        assert "accommodations-changed from:body" in client.get("/").text

    def test_the_detail_modal_offers_edit_and_delete(self, client):
        modal = client.get(ONE).text
        assert f'hx-get="http://testserver{EDIT}"' in modal
        assert f'hx-delete="http://testserver{ONE}"' in modal
        # Deleting is not undoable, so it asks first.
        assert "hx-confirm" in modal
