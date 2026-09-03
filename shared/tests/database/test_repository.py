"""Unit tests for the shared reference repositories and the id rule.

These drive the models and repositories directly against an in-memory SQLite
database -- no HTTP. The wire contract is covered in test_internal_api.py.
"""

from __future__ import annotations

from uuid import uuid4

from shared_database_service import ids
from shared_database_service.models import City, Country, Currency
from shared_database_service.schemas import (
    City as CityMessage,
)
from shared_database_service.schemas import (
    CityQueryRequest,
    CountryQueryRequest,
    CurrencyQueryRequest,
)
from shared_database_service.schemas import (
    Country as CountryMessage,
)
from shared_database_service.schemas import (
    Currency as CurrencyMessage,
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

    def test_currency_id_is_scoped_to_its_country(self):
        """France and Italy both spend euros, and under the one-to-one rule
        those are two rows -- so they must be two ids."""
        assert ids.currency_id("france", "euro") != ids.currency_id("italy", "euro")


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


class TestCurrencyRepository:
    def test_add_is_idempotent(self, currencies, australia):
        first, created = currencies.add("australian dollar", "AUD", "$", 1.0, australia)
        second, again = currencies.add("Australian Dollar", "AUD", "$", 1.0, australia)
        assert created is True
        assert again is False
        assert first.id == second.id

    def test_a_country_has_at_most_one(self, currencies, aud, australia):
        assert currencies.for_country(australia.id) is aud

    def test_for_country_is_none_when_there_is_none(self, currencies, session):
        japan = Country.get_or_create(session, "japan")
        assert currencies.for_country(japan.id) is None

    def test_the_same_currency_under_two_countries_is_two_rows(
        self, currencies, session
    ):
        """The real world's euro is shared; this model's is not, and that is
        the deliberate simplification."""
        france = Country.get_or_create(session, "france")
        italy = Country.get_or_create(session, "italy")
        one, _ = currencies.add("euro", "EUR", "\u20ac", 0.57, france)
        other, _ = currencies.add("euro", "EUR", "\u20ac", 0.57, italy)
        assert one.id != other.id
        # Same currency, two rows -- so the code cannot be the identity.
        assert one.name == other.name == "euro"
        assert one.code == other.code == "EUR"

    def test_a_code_is_stored_upper_case(self, currencies, australia):
        currency, _ = currencies.add("australian dollar", " aud ", "$", 1.0, australia)
        assert currency.code == "AUD"

    def test_an_existing_row_keeps_its_code_symbol_and_rate(
        self, currencies, aud, australia
    ):
        """POST is get-or-create, not an update -- which is also why there is
        no way to refresh a stale rate yet."""
        again, created = currencies.add(
            "australian dollar", "XXX", "A$", 99.0, australia
        )
        assert created is False
        assert (again.code, again.symbol, again.conversion_rate) == ("AUD", "$", 1.0)

    def test_search_matches_a_code_exactly_and_case_insensitively(
        self, currencies, session
    ):
        """`code` is the filter that answers "who spends euros" -- it is not
        unique, so it matches every country that uses it."""
        for country_name in ("france", "italy", "japan"):
            country = Country.get_or_create(session, country_name)
            name, code, symbol = (
                ("euro", "EUR", "\u20ac")
                if country_name != "japan"
                else ("japanese yen", "JPY", "\u00a5")
            )
            currencies.add(name, code, symbol, 1.0, country)
        rows, total = currencies.search(
            CurrencyQueryRequest(currency=CurrencyMessage(code="eur"))
        )
        assert total == 2
        assert {row.name for row in rows} == {"euro"}

    def test_search_matches_name_as_a_substring(self, currencies, aud):
        rows, total = currencies.search(
            CurrencyQueryRequest(currency=CurrencyMessage(name="DOLLAR"))
        )
        assert total == 1
        assert rows == [aud]

    def test_search_filters_by_country(self, currencies, aud, session):
        japan = Country.get_or_create(session, "japan")
        Currency.get_or_create(session, "japanese yen", "JPY", "\u00a5", 98.0, japan)
        session.commit()
        rows, total = currencies.search(
            CurrencyQueryRequest(currency=CurrencyMessage(country_id=japan.id))
        )
        assert total == 1
        assert [row.name for row in rows] == ["japanese yen"]

    def test_search_matches_symbol_exactly(self, currencies, aud, session):
        japan = Country.get_or_create(session, "japan")
        Currency.get_or_create(session, "japanese yen", "JPY", "\u00a5", 98.0, japan)
        session.commit()
        rows, total = currencies.search(
            CurrencyQueryRequest(currency=CurrencyMessage(symbol="\u00a5"))
        )
        assert total == 1
        assert [row.name for row in rows] == ["japanese yen"]
