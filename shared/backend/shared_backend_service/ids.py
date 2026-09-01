"""The country id rule, as this service needs it.

A deliberate copy of `shared_database_service/ids.py`, not an import: the two
services are separately deployable and this one does not ship the database
package. The rule is published in ../../docs/object-model.md precisely so it can
be copied -- student 2's accommodation seed carries the same four lines.

It earns its place here in exactly one endpoint. `GET /currency/country`
takes a country *name*, and the country search matches names as substrings, so
resolving one that way would make `?name=a` ambiguous. Hashing the name gives
the id outright, and the look-up becomes an exact `GET` that is either there or
a 404.
"""

from __future__ import annotations

from uuid import UUID, uuid5

NAMESPACE = UUID("9a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b")


def normalise(name: str) -> str:
    return name.strip().lower()


def country_id(name: str) -> UUID:
    return uuid5(NAMESPACE, f"country:{normalise(name)}")
