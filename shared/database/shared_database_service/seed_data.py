"""Starter countries and cities, inserted on first start.

Unlike a per-student service's demo rows, these are not decoration: every other
service's seeded rows point at the ids these names hash to (see ids.py), so an
unseeded shared database leaves those rows referencing places nothing can name.
Everything student 2's `seed_data.py` uses is in here.

Rows go in through the same `Country.get_or_create` / `City.get_or_create` path
a POST takes, so a seed row cannot be shaped differently to a created one.

ponytail: a literal mapping, not a fixtures file or a CLI. Replace it with a
real import (a geonames extract, say) when "which places exist" stops being a
question this team answers by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from shared_database_service.models import City, Country

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


def seed(session: Session) -> int:
    """Insert the starter rows if the tables are empty. Returns how many went in.

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
    session.commit()
    return inserted
