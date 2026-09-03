"""A question in English, as a search this service already knows how to run.

The model produces *filters* and a sentence, never results. What it returns is
validated as `AiSearchAnswer` -- `AccommodationQueryRequest`, the message
`QUERY /accommodation` takes, plus a `reply` for the reader -- and then the
ordinary search runs. So every row a caller sees came out of the
database, and the worst a bad answer can do is search for the wrong thing.

`AiSearchAnswer`'s own JSON Schema (less the fields in `UNASKABLE`)
is handed to AI-Mode as the output schema, which forwards it to Ollama as its
`format`. Two things fall out of that: the answer is JSON of that shape rather
than prose to be scraped, and the filter vocabulary -- every field, every enum
value -- has exactly one definition (schemas.py) instead of a copy inside a
prompt that drifts.

ponytail: the retry loop below only checks that the answer parses and validates.
It does not judge whether the filters are a *good* reading of the question --
nothing here could. If searches come back plainly wrong, the fix is a better
model (AI_MODE_DEFAULT_MODEL) or a better prompt asset, not more code.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from pydantic import ValidationError

from backend_service.schemas import AiSearchAnswer

if TYPE_CHECKING:
    from backend_service.ai_client import AiClient
    from backend_service.config import Settings
    from backend_service.location_client import LocationClient

LOGGER = logging.getLogger(__name__)

PROMPT_ASSET = "accommodation_search_v1.md"
UNUSABLE = "ai mode returned an unusable search"
NO_NOTES = ""


@lru_cache(maxsize=1)
def _template() -> str:
    """The prompt asset, read once. It ships in the package (see the
    package-data entry in pyproject.toml), so `resources` rather than a path
    relative to this file -- the container installs the package, it does not
    copy the source tree."""
    return (
        resources.files("backend_service")
        .joinpath("prompts", PROMPT_ASSET)
        .read_text(encoding="utf-8")
    )


# Filters a sentence cannot honestly specify. Constrained decoding fills in
# whatever the schema offers, so offering these is asking to be told the street
# number of a hotel nobody named -- and every one of them is an exact match that
# would empty the result. Removed from what the model sees, not from the search:
# a caller who really does know the street can still send a QUERY, and the
# filter form on the page still offers every one of them.
#
# `city` is not among them, but it is not offered raw either: both it and
# `country` are narrowed to an enum of the names the shared reference service
# actually has (see `_schema`). Asked about Japan with a free-text field,
# qwen2.5:0.5b answers "kyoto"; asked about Australia, "canberra" -- confident,
# plausible, and nothing there, because an invented city is an exact match on a
# place with no listings. An enum makes that unrepresentable during decoding
# rather than merely discouraged in the prompt.
UNASKABLE = {
    "AiSearchAnswer": ("limit", "offset"),
    "Accommodation": ("id", "name", "description", "room_details"),
    "Location": ("street", "street_number"),
}


@lru_cache(maxsize=1)
def _schema(countries: tuple[str, ...], cities: tuple[str, ...]) -> dict:
    """What the model is allowed to answer with: the filter contract, minus the
    fields above, with the two place fields narrowed to what exists.

    Derived from `AiSearchAnswer` rather than written out, so a new
    filter is offered to the model the moment it exists in schemas.py, and the
    enum vocabularies stay in one place. AI-Mode passes this to Ollama as the
    decoding `format`, so the cuts are enforced during decoding rather than
    argued for in the prompt.

    `room_details` goes but `room_count_min` / `bed_count_min` stay: "sleeps
    four" is a lower bound, and the exact-match version of it finds nothing.

    `country` and `city` become enums of the real names. That is what makes
    "cheap things around adelaide" a search for Adelaide rather than a shrug:
    the field exists, and the only values decoding can put in it are places that
    have listings.

    Cached on the vocabularies themselves, so a place the shared service gains
    reaches the model on the next call rather than at the next restart.
    """
    schema = AiSearchAnswer.model_json_schema()
    definitions = schema["$defs"] | {"AiSearchAnswer": schema}
    for name, fields in UNASKABLE.items():
        properties = definitions[name]["properties"]
        for field in fields:
            del properties[field]
    # An empty enum is a field nothing can be decoded into, so a shared service
    # with no cities in it drops the field rather than offering an impossible
    # one.
    location = schema["$defs"]["Location"]["properties"]
    for field, vocabulary in (("country", countries), ("city", cities)):
        if vocabulary:
            location[field] = {"type": "string", "enum": list(vocabulary)}
        else:
            del location[field]
    # Every filter is optional, which makes `{"reply": "..."}` -- no filters at
    # all -- the shortest completion the grammar allows, and a small model takes
    # it: measured, "cheap things around adelaide" came back with the sentence
    # and an empty search, and "under 200 a night" with no price bound.
    # Requiring the top level forces a decision on each one instead of letting
    # the model close the object early.
    #
    # Only the top level. Required *everywhere* was measured too, and it is
    # worse than optional: with no way to skip a field, the model fills the
    # match template with invention -- `price_per_night: 0`, a type nobody
    # asked for, tokyo for a question about Japan -- and every one of those is
    # an exact match that empties the result. Inside the template, skipping is
    # how the model says "the question did not imply this".
    schema["required"] = list(schema["properties"])
    del schema["$defs"]["Room"]  # only `room_details` referred to it
    return schema


def render_prompt(
    question: str,
    countries: list[str],
    cities: list[str],
    notes: str = NO_NOTES,
) -> str:
    """The prompt asset, filled in.

    The asset is a handful of worked `Question:` / `JSON:` pairs ending on a
    bare `JSON:` cue, and it is shaped that way because of how AI-Mode calls
    Ollama: with `raw=True`, so no chat template is applied and the model is
    doing plain completion rather than answering an instruction. Three things
    follow, all of them measured against qwen2.5:0.5b rather than guessed:

    - Examples beat rules. Told the rules in prose, the model returns filters
      with no `country` in them; shown four examples, it gets the country, the
      price bound and the rating together.
    - The prompt must not end on whitespace. AI-Mode strips trailing whitespace
      off a prompt, and a prompt ending on a blank line gets `{ }` back every
      time -- valid against the schema, and a search for nothing at all. Hence
      `.strip()` here rather than trusting the asset's last byte to survive an
      editor.
    - The schema is not in the prompt. It reaches Ollama as the decoding
      `format`, which constrains the answer far more reliably than 4KB of JSON
      Schema in front of a small model's context ever did.

    ponytail: four string replacements, not a template engine. Jinja is already
    a dependency of the *frontend* service; importing it here to fill four
    holes would buy nothing.
    """
    return (
        _template()
        .replace("{{KNOWN_COUNTRIES}}", ", ".join(countries) or "none")
        .replace("{{KNOWN_CITIES}}", ", ".join(cities) or "none")
        .replace("{{ADAPTATION_NOTES}}", notes)
        .replace("{{USER_QUERY}}", question)
        .strip()
    )


async def filters_for(
    question: str,
    ai: AiClient,
    location: LocationClient,
    settings: Settings,
) -> AiSearchAnswer:
    """The filters the question asks for and the sentence that says so, or a
    502 if the model cannot produce an answer this service can use.

    Both place lists come from the shared reference service's cache, so the
    prompt names the places that actually have listings and the schema will not
    decode anything else.
    """
    countries = await location.countries()
    cities = await location.cities()
    schema = _schema(tuple(countries), tuple(cities))
    notes = NO_NOTES
    for attempt in range(1, settings.ai_max_attempts + 1):
        answer = await ai.generate(
            render_prompt(question, countries, cities, notes), schema
        )
        try:
            return _tidy(
                AiSearchAnswer.model_validate_json(_with_country(answer, location))
            )
        except ValidationError as exc:
            reason = _reason(exc)
            LOGGER.info(
                "ai_search attempt=%s of=%s outcome=rejected reason=%s",
                attempt,
                settings.ai_max_attempts,
                reason,
            )
            notes = (
                "Your previous answer could not be used. Reason: "
                f"{reason}. Start again and return only JSON matching the "
                "schema."
            )
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, UNUSABLE)


# What a bound has to sit between to be a bound the question actually asked
# for. Below the low end it excludes nothing; at or above the high end it
# excludes everything -- and `price_max: 0`, measured, is a search for nothing
# at all.
#
# Both are the same thing happening: the top-level fields are required (see
# `_schema`), so a model with no bound to give has to answer anyway, and it
# answers in extremes -- `price_min: 0`, `rating_max: 5`, `price_max: 0`,
# `price_max: 1000000000`. Harmless or ruinous to search on, noise either way to
# read, and the page prints the filters back to the reader, so they come off
# here.
#
# ponytail: 10_000 is a nightly price no listing in this data reaches, not a
# principle. If a room ever costs more than that a night, raise it.
NO_BOUND = {
    "price_min": (0, 10_000),
    "price_max": (0, 10_000),
    "rating_min": (0, 5),
    "rating_max": (0, 5),
    "room_count_min": (1, None),
    "bed_count_min": (1, None),
}


def _tidy(answer: AiSearchAnswer) -> AiSearchAnswer:
    """The same search, with the bounds that bound nothing -- or everything --
    taken off."""
    dropped = {}
    for field, (low, high) in NO_BOUND.items():
        value = getattr(answer, field)
        if value is not None and (value <= low or (high is not None and value >= high)):
            dropped[field] = None
    return answer.model_copy(update=dropped)


def _with_country(answer: str, location: LocationClient) -> str:
    """The answer, with the country a named city is in filled in.

    "cheap things around adelaide" names a city and no country, which the
    contract rejects -- `city requires country`, because Sydney is in two of
    them. The country is not something the traveller has to say, though: this
    service is holding the list that maps one to the other, so it looks it up
    rather than spending a retry asking the model to be more complete.

    A city in more than one country is dropped instead: guessing which Sydney
    somebody meant is worse than searching the whole country list for them. Left
    alone if the answer is not JSON at all -- `model_validate_json` below is
    what reports that, and the retry loop needs its message.
    """
    try:
        data = json.loads(answer)
    except ValueError:
        return answer
    place = (data.get("accommodation") or {}).get("location_details")
    if not isinstance(place, dict) or place.get("country") or not place.get("city"):
        return answer
    country = location.country_of(place["city"])
    if country:
        place["country"] = country
    else:
        del place["city"]
    return json.dumps(data)


def _reason(exc: ValidationError) -> str:
    """Why the answer was rejected -- short enough for a prompt and a log line,
    and carrying none of the question's own text, which never gets logged."""
    first = exc.errors()[0]
    if first["type"] == "json_invalid":
        return "the answer was not valid JSON"
    field = ".".join(str(part) for part in first["loc"]) or "the object"
    return f"{field}: {first['msg']}"[:200]
