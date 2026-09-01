"""Starter countries and cities, inserted on first start.

Unlike a per-student service's demo rows, these are not decoration: every other
service's seeded rows point at the ids these names hash to (see ids.py), so an
unseeded shared database leaves those rows referencing places nothing can name.
Everything student 2's `seed_data.py` uses is in here.

Rows go in through the same `get_or_create` path a POST takes, so a seed row
cannot be shaped differently to a created one.

ponytail: a literal mapping, not a fixtures file or a CLI. Replace it with a
real import (a geonames extract, say) when "which places exist" stops being a
question this team answers by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from shared_database_service.models import City, Country, Currency

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SEED_PLACES: dict[str, tuple[str, ...]] = {
    "australia": (
        "sydney",
        "melbourne",
        "brisbane",
        "adelaide",
        "perth",
        "hobart",
        "canberra",
        "cairns",
        "darwin",
        "apollo bay",
        "katoomba",
        "airlie beach",
    ),
    "new zealand": (
        "auckland",
        "wellington",
        "christchurch",
        "queenstown",
        "rotorua",
    ),
    "japan": (
        "tokyo",
        "kyoto",
        "osaka",
        "sapporo",
        "fujikawaguchiko",
    ),
    "singapore": ("singapore",),
    "indonesia": ("denpasar", "ubud", "jakarta"),
    "thailand": ("bangkok", "chiang mai", "phuket"),
    "united kingdom": ("london", "edinburgh", "manchester"),
    "united states": ("new york", "los angeles", "san francisco"),
    "france": ("paris", "lyon", "nice"),
    "italy": ("rome", "florence", "venice"),
}

# One currency per country: the name, the ISO 4217 code, the symbol a page
# renders, and how many units 1 AUD buys. France and Italy both spend euros and
# get a row each, both EUR -- see the one-to-one note in
# ../../docs/object-model.md.
#
# AUD is 1.0 because TripGenie is an Australian service: prices are quoted in
# AUD, so the local currency is the base and its row needs no special case.
#
# ponytail: the other rates are static, indicative, and stale the day they were
# written. They are here so a page can say "about \u00a59,800", not so anyone can
# be charged. Replace this table with a rates feed the moment a number has to be
# correct rather than illustrative.
SEED_CURRENCIES: dict[str, tuple[str, str, str, float]] = {
    "australia": ("australian dollar", "AUD", "$", 1.0),
    "new zealand": ("new zealand dollar", "NZD", "$", 1.09),
    "japan": ("japanese yen", "JPY", "\u00a5", 98.0),
    "singapore": ("singapore dollar", "SGD", "$", 0.85),
    "indonesia": ("indonesian rupiah", "IDR", "Rp", 10500.0),
    "thailand": ("thai baht", "THB", "\u0e3f", 21.5),
    "united kingdom": ("pound sterling", "GBP", "\u00a3", 0.49),
    "united states": ("united states dollar", "USD", "$", 0.66),
    "france": ("euro", "EUR", "\u20ac", 0.57),
    "italy": ("euro", "EUR", "\u20ac", 0.57),
}


def seed(session: Session) -> int:
    """Insert the starter rows if the tables are empty. Returns how many went in.

    Every country in `SEED_PLACES` needs an entry in `SEED_CURRENCIES` -- a
    `KeyError` here is a country somebody added to one and forgot in the other,
    which is exactly when you want to hear about it.

    Empty-only, so a restart against the mounted volume does not duplicate them
    and does not fight whatever a caller has since created.
    """
    if session.scalar(select(func.count()).select_from(Country)):
        return 0
    inserted = 0
    for country_name, city_names in SEED_PLACES.items():
        country = Country.get_or_create(session, country_name)
        inserted += 1
        for city_name in city_names:
            City.get_or_create(session, city_name, country)
            inserted += 1
        name, code, symbol, conversion_rate = SEED_CURRENCIES[country_name]
        Currency.get_or_create(session, name, code, symbol, conversion_rate, country)
        inserted += 1
    session.commit()
    return inserted
