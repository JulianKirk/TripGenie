from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
NUMBER = rf"(?:\d+(?:\.\d+)?|{'|'.join(NUMBER_WORDS)})"
UPPER_BOUND = r"(?:under|below|less than|no more than|up to|at most|maximum(?: of)?)"
LOWER_BOUND = (
    r"(?:over|above|(?<!no )more than|no less than|at least|minimum(?: of)?|from)"
)

CATEGORY_TERMS = {
    "ADVENTURE": (
        "adventure",
        "adventurous",
        "water",
        "water activity",
        "water activities",
        "kayak",
        "kayaking",
        "paddle",
        "paddling",
    ),
    "CULTURE": ("culture", "cultural", "museum", "museums", "gallery", "galleries"),
    "FAMILY": ("family", "families", "kid", "kids", "child", "children"),
    "FOOD_DRINK": ("food", "drink", "dining", "culinary", "tasting"),
    "NIGHTLIFE": ("nightlife", "night life"),
    "OUTDOOR": ("outdoor", "outdoors"),
    "SHOPPING": ("shopping", "market", "markets"),
    "TOUR": ("tour", "tours", "guided"),
    "WELLNESS": ("wellness", "fitness", "yoga", "relaxation"),
    "WILDLIFE": ("wildlife", "animal", "animals"),
}


def _number(value: str) -> Decimal:
    return Decimal(NUMBER_WORDS.get(value.casefold(), value))


def _money(value: str) -> str:
    return f"{_number(value):.2f}"


def _minutes(value: str, unit: str) -> int:
    amount = _number(value)
    multiplier = 60 if unit.casefold().startswith(("h", "hour")) else 1
    return int(amount * multiplier)


def _category_codes(question: str) -> list[str]:
    lowered = question.casefold()
    return [
        code
        for code, terms in CATEGORY_TERMS.items()
        if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in terms)
    ]


def _price_bounds(question: str) -> dict[str, str]:
    amount = rf"(?:\$\s*({NUMBER})|({NUMBER})\s*(?:dollars?|aud))"
    result: dict[str, str] = {}
    for key, marker in (("max", UPPER_BOUND), ("min", LOWER_BOUND)):
        match = re.search(rf"{marker}\s*{amount}", question, re.IGNORECASE)
        if match:
            result[key] = _money(match.group(1) or match.group(2))
    return result


def _duration_bounds(question: str) -> dict[str, int]:
    unit = r"(hours?|hrs?|minutes?|mins?)"
    result: dict[str, int] = {}
    for key, marker in (("max", UPPER_BOUND), ("min", LOWER_BOUND)):
        match = re.search(rf"{marker}\s*({NUMBER})\s*{unit}", question, re.IGNORECASE)
        if match:
            result[key] = _minutes(match.group(1), match.group(2))
    between = re.search(
        rf"between\s*({NUMBER})\s*(?:and|-)\s*({NUMBER})\s*{unit}",
        question,
        re.IGNORECASE,
    )
    if between:
        result = {
            "min": _minutes(between.group(1), between.group(3)),
            "max": _minutes(between.group(2), between.group(3)),
        }
    return result


def _party_size(question: str) -> int | None:
    match = re.search(
        rf"(?:for\s+({NUMBER})\s+(?:people|travellers?|travelers?|adults?|participants?|guests?)|party\s+of\s+({NUMBER}))",
        question,
        re.IGNORECASE,
    )
    return int(_number(match.group(1) or match.group(2))) if match else None


def _ages(question: str) -> tuple[int, int] | None:
    match = re.search(
        rf"ages?\s+({NUMBER})\s*(?:to|-)\s*({NUMBER})", question, re.IGNORECASE
    )
    if match is None:
        return None
    return int(_number(match.group(1))), int(_number(match.group(2)))


def _accessibility(question: str) -> dict[str, bool]:
    lowered = question.casefold()
    result: dict[str, bool] = {}
    if "wheelchair" in lowered:
        result["wheelchair_accessible"] = True
    if re.search(r"\bstep[ -]?free\b", lowered):
        result["step_free_access"] = True
    if re.search(r"\baccessible toilet\b", lowered):
        result["accessible_toilet"] = True
    if re.search(r"\baccessible\b", lowered) and not result:
        result = {
            "wheelchair_accessible": True,
            "step_free_access": True,
            "accessible_toilet": True,
        }
    return result


def _has_date_intent(question: str) -> bool:
    lowered = question.casefold()
    return bool(
        re.search(r"\b\d{4}-\d{2}-\d{2}\b", lowered)
        or re.search(
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)\b",
            lowered,
        )
        or re.search(r"\b(?:first|last) day\b", lowered)
    )


def _clean_text(text: str, result: dict[str, object], categories: list[str]) -> str:
    cleaned = text.casefold()
    cleaned = re.sub(
        r"^\s*(?:please\s+)?(?:suggest|find|recommend|show(?:\s+me)?)\s+",
        "",
        cleaned,
    )
    for code in categories:
        for term in CATEGORY_TERMS[code]:
            cleaned = re.sub(rf"\b{re.escape(term)}\b", " ", cleaned)
    location = result.get("location")
    if isinstance(location, dict):
        for value in location.values():
            if isinstance(value, str):
                cleaned = re.sub(rf"\b{re.escape(value.casefold())}\b", " ", cleaned)
    money = rf"(?:\$\s*{NUMBER}|{NUMBER}\s*(?:dollars?|aud))"
    duration = rf"{NUMBER}\s*(?:hours?|hrs?|minutes?|mins?)"
    cleaned = re.sub(rf"{UPPER_BOUND}\s*(?:{money}|{duration})", " ", cleaned)
    cleaned = re.sub(rf"{LOWER_BOUND}\s*(?:{money}|{duration})", " ", cleaned)
    cleaned = re.sub(
        rf"(?:for\s+{NUMBER}\s+(?:people|travellers?|travelers?|adults?|participants?|guests?)|party\s+of\s+{NUMBER})",
        " ",
        cleaned,
    )
    cleaned = re.sub(rf"ages?\s+{NUMBER}\s*(?:to|-)\s*{NUMBER}", " ", cleaned)
    cleaned = re.sub(
        r"\b(?:wheelchair(?: accessible)?|step[ -]?free(?: access)?|"
        r"accessible toilet|accessible|(?:no|without) (?:advance )?booking|"
        r"booking (?:is )?required)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"\b(?:from|between)\s+\d{1,2}:\d{2}\s+"
        r"(?:to|and|-)\s+\d{1,2}:\d{2}\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(
        r"\b(?:at|after|before|from|until|by)\s+\d{1,2}:\d{2}\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}\b", " ", cleaned)
    cleaned = re.sub(
        r"\b(?:(?:next|this)\s+)?(?:monday|tuesday|wednesday|thursday|"
        r"friday|saturday|sunday|today|tomorrow)\b",
        " ",
        cleaned,
    )
    if isinstance(result.get("availability"), dict):
        cleaned = re.sub(
            r"\b(?:(?:first|last)\s+day|morning|afternoon|evening)\b",
            " ",
            cleaned,
        )
    cleaned = re.sub(r"\bthat\s+lasts?\b", " ", cleaned)
    cleaned = re.sub(r"\bfor\s+(?:me|us)\b", " ", cleaned)
    cleaned = re.sub(r"\bactivit(?:y|ies)\b", " ", cleaned)
    words = re.findall(r"[\w'-]+", cleaned)
    filler = {"a", "an", "the", "that", "which", "with", "something"}
    return " ".join(word for word in words if word not in filler).strip()


def _requires_all_categories(question: str, categories: list[str]) -> bool:
    if len(categories) < 2:
        return False
    if re.search(
        r"\b(?:all (?:of )?(?:the )?(?:named |selected )?categories|"
        r"every (?:named |selected )?category)\b",
        question,
        re.IGNORECASE,
    ):
        return True
    terms = [term for code in categories for term in CATEGORY_TERMS[code]]
    category = "(?:" + "|".join(map(re.escape, terms)) + ")"
    return bool(
        re.search(
            rf"\bboth\s+{category}\s+(?:and|&)\s+{category}\b",
            question,
            re.IGNORECASE,
        )
    )


def _apply_ranges_and_categories(
    question: str, result: dict[str, object]
) -> tuple[list[str], bool]:
    categories = _category_codes(question)
    if categories:
        result["categories"] = {
            "codes": categories,
            "match": "ALL" if _requires_all_categories(question, categories) else "ANY",
        }
    else:
        result.pop("categories", None)

    recovered = bool(categories)
    for field, value in (
        ("price", _price_bounds(question)),
        ("duration_minutes", _duration_bounds(question)),
    ):
        if value:
            result[field] = value
            recovered = True
        else:
            result.pop(field, None)
    return categories, recovered


def _apply_people(question: str, result: dict[str, object]) -> bool:
    recovered = False
    party_size = _party_size(question)
    if party_size is not None:
        result["party_size"] = party_size
        recovered = True
    else:
        result.pop("party_size", None)

    ages = _ages(question)
    if ages is not None:
        result["youngest_age"], result["oldest_age"] = ages
        recovered = True
    elif not re.search(
        r"\b(?:age|ages|aged|youngest|oldest)\b", question, re.IGNORECASE
    ):
        result.pop("youngest_age", None)
        result.pop("oldest_age", None)
    return recovered


def _apply_access_and_booking(question: str, result: dict[str, object]) -> bool:
    recovered = False
    accessibility = _accessibility(question)
    if accessibility:
        current = result.get("accessibility")
        result["accessibility"] = (
            {**current, **accessibility} if isinstance(current, dict) else accessibility
        )
        recovered = True
    else:
        result.pop("accessibility", None)

    lowered = question.casefold()
    if re.search(r"\b(?:no|without) (?:advance )?booking\b", lowered):
        result["booking_required"] = False
        recovered = True
    elif re.search(r"\bbooking (?:is )?required\b", lowered):
        result["booking_required"] = True
        recovered = True
    elif "booking" not in lowered:
        result.pop("booking_required", None)
    return recovered


def _clean_model_extras(
    question: str,
    result: dict[str, object],
    categories: list[str],
    recovered: bool,
    implicit_date: str | None,
) -> None:
    app_owned = {"sort", "include_inactive", "limit", "offset"}
    had_structured_filters = any(
        key != "text" and key not in app_owned for key in result
    )
    if not _has_date_intent(question):
        if implicit_date is None:
            result.pop("availability", None)
        else:
            current = result.get("availability")
            result["availability"] = (
                {**current, "date": implicit_date}
                if isinstance(current, dict)
                else {"date": implicit_date}
            )

    text = result.get("text")
    if not isinstance(text, str):
        return
    if text.casefold() not in question.casefold():
        result.pop("text", None)
        return
    if not (recovered or had_structured_filters):
        return
    cleaned_text = _clean_text(text, result, categories)
    if cleaned_text:
        result["text"] = cleaned_text
    else:
        result.pop("text")


def apply_explicit_filters(
    question: str,
    query: dict[str, object],
    *,
    implicit_date: str | None = None,
) -> tuple[dict[str, object], bool]:
    """Make explicit supported constraints authoritative over model omissions."""
    result = deepcopy(query)
    categories, recovered_ranges = _apply_ranges_and_categories(question, result)
    recovered = any(
        (
            recovered_ranges,
            _apply_people(question, result),
            _apply_access_and_booking(question, result),
        )
    )
    _clean_model_extras(question, result, categories, recovered, implicit_date)
    return result, recovered
