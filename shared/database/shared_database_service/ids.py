"""Deterministic ids for the reference rows.

A place's id is derived from its name rather than drawn at random, so a service
that cannot call this one can still name a place. That is not a convenience:
the accommodation database service seeds itself at startup and has no HTTP
client, yet its rows have to point at the same country and city rows this
service serves.

The live path still asks this service -- the rule exists so an *offline* seed
can reference a place. Both sides compute it from the same two functions, and
the rule is documented in ../../docs/object-model.md so a third service can
implement it in four lines.

ponytail: uuid5 over a shared namespace, not a registry or a synchronised id
allocator. Names are the natural key already. If a place ever needs to be
renamed while keeping its id, this rule is what has to go first.
"""

from __future__ import annotations

from uuid import UUID, uuid5

NAMESPACE = UUID("9a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b")


def normalise(name: str) -> str:
    """The form a name is hashed and stored in. Case and padding are how the
    same place arrives spelled two ways; neither should make a second row."""
    return name.strip().lower()


def normalise_code(code: str) -> str:
    """The form a currency code is stored in. ISO 4217 codes are conventionally
    upper case, and a caller typing `aud` means `AUD`."""
    return code.strip().upper()


def country_id(name: str) -> UUID:
    return uuid5(NAMESPACE, f"country:{normalise(name)}")


def city_id(country: str, name: str) -> UUID:
    """Scoped to the country -- Sydney, Australia and Sydney, Canada are two
    places, so they must be two ids."""
    return uuid5(NAMESPACE, f"city:{normalise(country)}/{normalise(name)}")


def currency_id(country: str, name: str) -> UUID:
    """Scoped to the country for the same reason a city is: a currency belongs
    to exactly one country here, and France's euro and Italy's euro are two
    rows under that rule."""
    return uuid5(NAMESPACE, f"currency:{normalise(country)}/{normalise(name)}")
