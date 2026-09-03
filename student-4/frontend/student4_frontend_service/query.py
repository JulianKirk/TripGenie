from __future__ import annotations

from decimal import Decimal, InvalidOperation

from starlette.datastructures import QueryParams

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class QueryInputError(ValueError):
    """A contradictory browser form that cannot form a backend query."""


def _text(params: QueryParams, name: str) -> str | None:
    value = params.get(name, "").strip()
    return value or None


def _integer(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _money(value: str) -> str:
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return value
    exponent = decimal.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -2:
        return value
    return f"{decimal:.2f}"


def _page(value: str | None, *, default: int, minimum: int, maximum: int | None) -> int:
    try:
        parsed = int(value) if value is not None else default
    except ValueError:
        return default
    parsed = max(parsed, minimum)
    return min(parsed, maximum) if maximum is not None else parsed


def _range(
    params: QueryParams,
    minimum_name: str,
    maximum_name: str,
    *,
    money: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for form_name, key in ((minimum_name, "min"), (maximum_name, "max")):
        value = _text(params, form_name)
        if value is not None:
            result[key] = _money(value) if money else _integer(value)
    return result


def _bool_value(value: str) -> bool | str:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return value


def _add_text_and_location(body: dict[str, object], params: QueryParams) -> None:
    text = _text(params, "text")
    if text is not None:
        body["text"] = text

    location = {
        key: value
        for key in ("country", "city", "street")
        if (value := _text(params, key)) is not None
    }
    if "country" not in location:
        location.pop("city", None)
    if location:
        body["location"] = location


def _add_categories(body: dict[str, object], params: QueryParams) -> None:
    categories = list(
        dict.fromkeys(
            value.strip() for value in params.getlist("category") if value.strip()
        )
    )
    if categories:
        body["categories"] = {
            "codes": categories,
            "match": _text(params, "category_match") or "ANY",
        }


def _add_numeric_filters(body: dict[str, object], params: QueryParams) -> None:
    price = _range(params, "price_min", "price_max", money=True)
    if price:
        body["price"] = price
    duration = _range(params, "duration_min", "duration_max")
    if duration:
        body["duration_minutes"] = duration

    for name in ("party_size", "youngest_age", "oldest_age"):
        value = _text(params, name)
        if value is not None:
            body[name] = _integer(value)


def _add_boolean_filters(body: dict[str, object], params: QueryParams) -> None:
    booking = _text(params, "booking_required")
    if booking is not None:
        body["booking_required"] = _bool_value(booking)

    accessibility = {
        name: True
        for name in (
            "wheelchair_accessible",
            "step_free_access",
            "accessible_toilet",
        )
        if _text(params, name) is not None
    }
    if accessibility:
        body["accessibility"] = accessibility


def _add_availability(body: dict[str, object], params: QueryParams) -> None:
    date = _text(params, "date")
    start_time = _text(params, "start_time")
    end_time = _text(params, "end_time")
    if (start_time or end_time) and not date:
        message = "A date is required when filtering by time."
        raise QueryInputError(message)
    if bool(start_time) != bool(end_time):
        message = "Earliest and latest time must be supplied together."
        raise QueryInputError(message)
    if date:
        availability: dict[str, object] = {"date": date}
        if start_time and end_time:
            availability.update(start_time=start_time, end_time=end_time)
        body["availability"] = availability


def build_search_body(params: QueryParams) -> dict[str, object]:
    """Translate the HTML filter form into the backend's nested QUERY body."""
    body: dict[str, object] = {}
    _add_text_and_location(body, params)
    _add_categories(body, params)
    _add_numeric_filters(body, params)
    _add_boolean_filters(body, params)
    _add_availability(body, params)

    sort = _text(params, "sort")
    if sort is not None:
        body["sort"] = sort
    if _text(params, "include_inactive") in {"true", "on", "1"}:
        body["include_inactive"] = True

    body["limit"] = _page(
        params.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT
    )
    body["offset"] = _page(params.get("offset"), default=0, minimum=0, maximum=None)
    return body


def _append_param(
    pairs: list[tuple[str, str]], name: str, value: object | None
) -> None:
    if value is not None:
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        pairs.append((name, rendered))


def _append_location_and_categories(
    pairs: list[tuple[str, str]], body: dict[str, object]
) -> None:
    location = body.get("location")
    if isinstance(location, dict):
        for name in ("country", "city", "street"):
            _append_param(pairs, name, location.get(name))

    categories = body.get("categories")
    if isinstance(categories, dict):
        codes = categories.get("codes")
        if isinstance(codes, list):
            pairs.extend(("category", str(code)) for code in codes)
        _append_param(pairs, "category_match", categories.get("match"))


def _append_ranges_and_party(
    pairs: list[tuple[str, str]], body: dict[str, object]
) -> None:

    for key, prefix in (("price", "price"), ("duration_minutes", "duration")):
        bounds = body.get(key)
        if isinstance(bounds, dict):
            _append_param(pairs, f"{prefix}_min", bounds.get("min"))
            _append_param(pairs, f"{prefix}_max", bounds.get("max"))

    for name in ("party_size", "youngest_age", "oldest_age", "booking_required"):
        _append_param(pairs, name, body.get(name))


def _append_accessibility_and_availability(
    pairs: list[tuple[str, str]], body: dict[str, object]
) -> None:

    accessibility = body.get("accessibility")
    if isinstance(accessibility, dict):
        for name in (
            "wheelchair_accessible",
            "step_free_access",
            "accessible_toilet",
        ):
            if accessibility.get(name) is True:
                _append_param(pairs, name, True)

    availability = body.get("availability")
    if isinstance(availability, dict):
        for name in ("date", "start_time", "end_time"):
            _append_param(pairs, name, availability.get(name))


def search_body_to_params(body: dict[str, object]) -> QueryParams:
    """Represent a validated backend query in the existing HTML filter form."""
    pairs: list[tuple[str, str]] = []
    _append_param(pairs, "text", body.get("text"))
    _append_location_and_categories(pairs, body)
    _append_ranges_and_party(pairs, body)
    _append_accessibility_and_availability(pairs, body)

    _append_param(pairs, "sort", body.get("sort"))
    _append_param(pairs, "limit", body.get("limit"))
    offset = body.get("offset")
    if isinstance(offset, int) and offset > 0:
        _append_param(pairs, "offset", offset)
    return QueryParams(pairs)
