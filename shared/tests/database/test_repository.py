"""Unit tests for the shared reference repositories and the id rule.

These drive the models and repositories directly against an in-memory SQLite
database -- no HTTP. The wire contract is covered in test_internal_api.py.
"""

from __future__ import annotations

from uuid import uuid4

from shared_database_service import ids
from shared_database_service.models import City, Country
from shared_database_service.schemas import (
    City as CityMessage,
)
from shared_database_service.schemas import (
    CityQueryRequest,
    CountryQueryRequest,
)
from shared_database_service.schemas import (
    Country as CountryMessage,
)


class TestIds:
    def test_country_id_is_stable_for_a_name(self):
        assert ids.country_id("australia") == ids.country_id("australia")

    def test_country_id_ignores_case_and_padding(self):
        # The whole point of the rule: two services spelling a place two ways
        # must still arrive at one row.
        assert ids.country_id("  Australia ") == ids.country_id("australia")

    def test_city_id_is_scoped_to_its_country(self):
        assert ids.city_id("australia", "sydney") != ids.city_id("canada", "sydney")


class TestCountryRepository:
    def test_add_is_idempotent(self, countries):
        first, created = countries.add("australia")
        second, again = countries.add("Australia")
        assert created is True
        assert again is False
        assert first.id == second.id

    def test_add_stores_the_normalised_name(self, countries):
        country, _ = countries.add("  Australia ")
        assert country.name == "australia"

    def test_get_by_the_derived_id(self, countries, australia):
        assert countries.get(ids.country_id("australia")) is australia

    def test_get_missing_is_none(self, countries):
        assert countries.get(uuid4()) is None

    def test_search_matches_name_as_a_substring(self, countries, australia):
        rows, total = countries.search(
            CountryQueryRequest(country=CountryMessage(name="AUSTRAL"))
        )
        assert total == 1
        assert rows == [australia]

    def test_search_without_filters_returns_everything(self, countries, session):
        for name in ("australia", "japan", "france"):
            Country.get_or_create(session, name)
        rows, total = countries.search(CountryQueryRequest())
        assert total == 3
        # Ordered by name so a page is stable.
        assert [row.name for row in rows] == ["australia", "france", "japan"]

    def test_search_pages(self, countries, session):
        for name in ("australia", "japan", "france"):
            Country.get_or_create(session, name)
        rows, total = countries.search(CountryQueryRequest(limit=1, offset=1))
        assert total == 3
        assert [row.name for row in rows] == ["france"]


class TestCityRepository:
    def test_add_is_idempotent(self, cities, australia):
        first, created = cities.add("sydney", australia)
        second, again = cities.add("Sydney", australia)
        assert created is True
        assert again is False
        assert first.id == second.id

    def test_same_city_name_under_two_countries_is_two_rows(self, cities, session):
        australia = Country.get_or_create(session, "australia")
        canada = Country.get_or_create(session, "canada")
        one, _ = cities.add("sydney", australia)
        other, _ = cities.add("sydney", canada)
        assert one.id != other.id

    def test_search_filters_by_country(self, cities, session):
        australia = Country.get_or_create(session, "australia")
        japan = Country.get_or_create(session, "japan")
        City.get_or_create(session, "sydney", australia)
        City.get_or_create(session, "tokyo", japan)
        session.commit()
        rows, total = cities.search(
            CityQueryRequest(city=CityMessage(country_id=japan.id))
        )
        assert total == 1
        assert [row.name for row in rows] == ["tokyo"]

    def test_search_matches_name_as_a_substring(self, cities, sydney):
        rows, total = cities.search(CityQueryRequest(city=CityMessage(name="SYD")))
        assert total == 1
        assert rows == [sydney]
