"""Request-local constraints, independent of model-authored search arguments."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from .prompt_filters import NUMBER_WORDS

if TYPE_CHECKING:
    from .schemas import Activity, ActivitySummary

WORDS = {**NUMBER_WORDS, "zero": 0}
NUMBER = rf"(?:[0-9]+(?:\.[0-9]{{1,2}})?|{'|'.join(WORDS)})"
AMOUNT = re.compile(
    rf"(?:\$\s*({NUMBER})|\bAUD\s*({NUMBER})\b|\b({NUMBER})\s*(?:AUD|dollars?)\b)",
    re.IGNORECASE,
)
PARTY = re.compile(
    rf"\b(?:({NUMBER})\s+(?:people|adults?|children|travellers?|travelers?|participants?|guests?)|party\s+of\s+({NUMBER}))\b",
    re.IGNORECASE,
)
DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


class ClarificationError(Exception):
    """An authored clarification, never raw model or provider text."""


def _number(value: str) -> Decimal:
    return Decimal(WORDS.get(value.casefold(), value))


def _validate_numeric_tokens(question: str) -> None:
    # Never interpret a suffix of an unsupported compound or signed number.
    unsupported = (
        r"(?<![\w])[-+\u2212]\s*\d|\d[,.]\d+[,.]\d|\d,\d|"
        r"\d\.\d{3,}|\d+(?:\.\d+)?[kKmM]\b|"
        r"\b(?:thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
        r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b"
    )
    # Remove supported dates and time windows before checking number syntax.
    numeric_text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", question)
    if re.search(unsupported, numeric_text, re.IGNORECASE) or re.search(
        r"\b\d+\s*[-\u2013]\s*\d+\s+(?:people|adults?|children)",
        question,
        re.IGNORECASE,
    ):
        message = (
            "Please use unsigned numbers without grouping separators, at most "
            "two decimal places for AUD amounts, and one whole-number party "
            "size."
        )
        raise ClarificationError(message)
    if re.search(r"\bbudget\b", question, re.IGNORECASE) and not AMOUNT.search(
        question
    ):
        message = (
            "Please state the budget with its currency, for example 'at most "
            "AUD 100 total'."
        )
        raise ClarificationError(message)


def _price_tokens(question: str) -> list[re.Match[str]]:
    amounts = list(AMOUNT.finditer(question))
    for marker in re.finditer(r"\$|\b(?:AUD|dollars?)\b", question, re.IGNORECASE):
        if not any(m.start() <= marker.start() < m.end() for m in amounts):
            message = "Please use an explicit AUD amount with two decimal places."
            raise ClarificationError(message)
    if any(re.match(r"\w|[.,]\d", question[m.end() :]) for m in amounts):
        message = "Please use complete AUD amounts without numeric suffixes."
        raise ClarificationError(message)
    return amounts


def party_total(price: Decimal, party_size: int) -> Decimal:
    """Multiply exact catalogue money without inheriting the caller's precision."""
    with localcontext() as context:
        context.prec = len(price.as_tuple().digits) + len(str(party_size)) + 1
        return price * party_size


def _prices(question: str) -> tuple[Decimal | None, Decimal | None, bool]:
    # Literal amounts cannot contain more digits than the bounded request.
    # Reserve cents and a carry digit for strict upper/lower comparisons.
    with localcontext() as context:
        context.prec = len(question) + 3
        return _prices_in_context(question)


def _prices_in_context(question: str) -> tuple[Decimal | None, Decimal | None, bool]:
    amounts = _price_tokens(question)
    foreign_currency = re.search(
        r"\b(?:USD|EUR|GBP|NZD|CAD|JPY|euros?|pounds?|yen)\b", question, re.IGNORECASE
    )
    unitless_bound = not amounts and re.search(
        rf"\b(?:under|below|over|above|at most|at least)\s+{NUMBER}\b"
        r"(?!\s*(?:minutes?|mins?|hours?|hrs?|people|adults?|years?)\b)",
        question,
        re.IGNORECASE,
    )
    if foreign_currency or unitless_bound:
        message = (
            "Please state an AUD price limit with currency, such as 'under AUD 100'."
        )
        raise ClarificationError(message)
    total = bool(
        re.search(
            r"\b(?:total|altogether|entire (?:party|group))\b", question, re.IGNORECASE
        )
    )
    if amounts and re.search(
        r"\b(?:or|not\s+(?:under|below|over|above|less than|at least|at most|"
        r"no less than|no more than|up to|maximum|minimum|budget))\b",
        question,
        re.IGNORECASE,
    ):
        message = (
            "Please give one price range to apply, rather than alternative or "
            "negated ranges."
        )
        raise ClarificationError(message)
    if total and re.search(r"\bper (?:person|adult)|\beach\b", question, re.IGNORECASE):
        message = (
            "Please specify one budget basis: the whole party or the listed "
            "activity price."
        )
        raise ClarificationError(message)
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    for match in amounts:
        value = _number(next(group for group in match.groups() if group is not None))
        prefix = question[: match.start()].lower()
        upper = re.search(
            r"\b(under|below|less than|no more than|at most|up to|"
            r"maximum(?: of)?|budget(?: of| is)?)\s*$",
            prefix,
        )
        lower = re.search(
            r"\b(over|above|at least|no less than|minimum(?: of)?)\s*$", prefix
        )
        if lower:
            value += Decimal("0.01") if lower[1] in {"over", "above"} else 0
            minimum = value if minimum is None else max(minimum, value)
        elif upper:
            value -= (
                Decimal("0.01") if upper[1] in {"under", "below", "less than"} else 0
            )
            maximum = value if maximum is None else min(maximum, value)
        elif total and len(amounts) == 1:
            maximum = value
        else:
            message = (
                "Please express the price limit as 'at most AUD 100', 'under $100',"
                " or 'at least $20'."
            )
            raise ClarificationError(message)
    if maximum is not None and (
        maximum < 0 or (minimum is not None and minimum > maximum)
    ):
        message = (
            "The minimum price exceeds the maximum. Please provide a consistent"
            " price range."
        )
        raise ClarificationError(message)
    return minimum, maximum, total


def _people(question: str) -> int | None:
    matches = list(PARTY.finditer(question))
    if len(matches) > 1:
        message = "Please give one total party size, such as 'for 5 people'."
        raise ClarificationError(message)
    if not matches:
        return None
    value = _number(matches[0][1] or matches[0][2])
    if value < 1 or value != int(value):
        message = "Please give a positive whole number of people."
        raise ClarificationError(message)
    return int(value)


def _dates(question: str) -> tuple[dt.date | None, dt.date | None]:
    if re.search(
        r"\b(?:before|after|except|excluding|not|or)\b.*\d{4}-|"
        r"\d{4}-\d{2}-\d{2}.*\b(?:or|except|excluding)\b|"
        r"\b(?:january|february|march|april|june|july|august|september|"
        r"october|november|december)\b|\bmay\s+\d|\d\s+may\b|"
        r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
        question,
        re.IGNORECASE,
    ):
        message = (
            "Please give one local date or an inclusive date range in YYYY-MM-"
            "DD format, without alternatives or exclusions."
        )
        raise ClarificationError(message)
    values = list(
        dict.fromkeys(re.findall(r"\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b", question))
    )
    matches = list(re.finditer(r"\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b", question))
    if len(matches) == 2 and not re.fullmatch(
        r"\s*(?:to|through|until|[-\u2013])\s*",
        question[matches[0].end() : matches[1].start()],
        re.IGNORECASE,
    ):
        message = "Please give one date or a range joined by 'to'."
        raise ClarificationError(message)
    if len(values) > 2:
        message = "Please give one local date or one inclusive date range."
        raise ClarificationError(message)
    try:
        dates = [dt.date.fromisoformat(value) for value in values]
    except ValueError as exc:
        message = "Please give a valid local date in YYYY-MM-DD format."
        raise ClarificationError(message) from exc
    if dates and dates[0] > dates[-1]:
        message = "The start date must not be after the end date."
        raise ClarificationError(message)
    if re.search(
        r"\b(today|tomorrow|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        question,
        re.IGNORECASE,
    ):
        message = (
            "For date-specific recommendations, please give the local date in "
            "YYYY-MM-DD format."
        )
        raise ClarificationError(message)
    return (dates[0], dates[-1]) if dates else (None, None)


def _times(question: str) -> tuple[dt.time | None, dt.time | None]:
    if re.search(
        r"\b\d+(?::\d+)?\s*[ap]\.?m\.?\b|\b(?:noon|midnight|morning|afternoon|evening)\b",
        question,
        re.IGNORECASE,
    ):
        message = (
            "Please use a 24-hour local time window, such as 'from 13:00 to 15:00'."
        )
        raise ClarificationError(message)
    values = re.findall(r"\b[0-9]{1,2}:[0-9]{2}\b", question)
    if not values:
        return None, None
    matches = list(re.finditer(r"\b[0-9]{1,2}:[0-9]{2}\b", question))
    if re.search(r"\b(?:not|except|excluding)\b", question, re.IGNORECASE) or (
        len(matches) == 2
        and not re.fullmatch(
            r"\s*(?:to|until|[-\u2013])\s*",
            question[matches[0].end() : matches[1].start()],
            re.IGNORECASE,
        )
    ):
        message = "Please give one time window joined by 'to', without exclusions."
        raise ClarificationError(message)
    try:
        times = [dt.time.fromisoformat(value.zfill(5)) for value in values]
    except ValueError as exc:
        message = "Please give valid local times in HH:MM format."
        raise ClarificationError(message) from exc
    if len(times) != 2 or times[0] >= times[1]:
        message = "Please give one local time window, such as 'from 10:00 to 12:00'."
        raise ClarificationError(message)
    return times[0], times[1]


class TripConstraints(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start_date: dt.date
    end_date: dt.date
    traveller_count: int = Field(ge=1, strict=True)


class RequestConstraints(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    party_size: int | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    total_budget: bool = False
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    window_start: dt.time | None = None
    window_end: dt.time | None = None
    accessibility: tuple[str, ...] = ()
    booking_required: bool | None = None

    def ready(self) -> None:
        if (
            self.total_budget
            and (self.price_min is not None or self.price_max is not None)
            and self.party_size is None
        ):
            message = (
                "How many people should the total activity budget cover? Please "
                "include the party size in your request or select a trip."
            )
            raise ClarificationError(message)
        if self.window_start and self.start_date is None:
            message = (
                "Please include a local date (YYYY-MM-DD) with the requested time "
                "window."
            )
            raise ClarificationError(message)

    def with_trip(self, value: dict[str, Any]) -> RequestConstraints:
        trip = TripConstraints.model_validate(value)
        if trip.start_date > trip.end_date:
            message = "The selected trip has an invalid date range."
            raise ClarificationError(message)
        if (
            self.start_date
            and self.end_date
            and (self.start_date < trip.start_date or self.end_date > trip.end_date)
        ):
            message = (
                "The requested dates are outside the selected trip. Please change "
                "the dates or submit without that trip."
            )
            raise ClarificationError(message)
        return self.model_copy(
            update={
                "party_size": self.party_size or trip.traveller_count,
                "start_date": self.start_date or trip.start_date,
                "end_date": self.end_date or trip.end_date,
            }
        )

    def accepts_summary(self, activity: ActivitySummary | Activity) -> bool:
        if not activity.is_active:
            return False
        if self.party_size is not None and (
            activity.minimum_participants > self.party_size
            or (
                activity.maximum_participants is not None
                and activity.maximum_participants < self.party_size
            )
        ):
            return False
        cost = activity.price
        if self.total_budget and activity.pricing_basis == "PER_PERSON":
            if self.party_size is None:
                return False
            cost = party_total(cost, self.party_size)
        return (
            (self.price_min is None or cost >= self.price_min)
            and (self.price_max is None or cost <= self.price_max)
            and all(getattr(activity, field) is True for field in self.accessibility)
            and (
                self.booking_required is None
                or activity.booking_required == self.booking_required
            )
        )

    def accepts(self, activity: Activity) -> bool:
        return self.accepts_summary(activity) and (
            self.start_date is None or self._matches_schedule(activity)
        )

    def _matches_schedule(self, activity: Activity) -> bool:
        assert self.start_date is not None and self.end_date is not None
        for schedule in activity.availability_schedules:
            if schedule.recurring_weekly:
                assert schedule.day_of_week is not None
                delta = (
                    DAYS.index(schedule.day_of_week) - self.start_date.weekday()
                ) % 7
                date_matches = (self.end_date - self.start_date).days >= delta
            else:
                assert schedule.date is not None
                date_matches = self.start_date <= schedule.date <= self.end_date
            start = max(schedule.start_time, self.window_start or schedule.start_time)
            end = min(schedule.end_time, self.window_end or schedule.end_time)
            minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
            if date_matches and minutes >= activity.duration_minutes:
                return True
        return False

    def search_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        filters = dict(arguments.get("filters") or {})
        for key in (
            "price",
            "party_size",
            "availability",
            "accessibility",
            "booking_required",
        ):
            filters.pop(key, None)
        prices = {}
        # A total minimum cannot safely be applied to listed PER_PERSON prices.
        if self.price_min is not None and not self.total_budget:
            prices["min"] = f"{self.price_min:.2f}"
        if self.price_max is not None:
            prices["max"] = f"{self.price_max:.2f}"
        if prices:
            filters["price"] = prices
        if self.party_size is not None:
            filters["party_size"] = self.party_size
        if self.accessibility:
            filters["accessibility"] = dict.fromkeys(self.accessibility, True)
        if self.booking_required is not None:
            filters["booking_required"] = self.booking_required
        if self.start_date is not None and self.start_date == self.end_date:
            filters["availability"] = {"date": self.start_date.isoformat()}
        return {
            **arguments,
            "filters": filters,
            "limit": min(arguments.get("limit", 6), 6),
        }

    def summary(self) -> str:
        pieces = []
        if self.party_size:
            pieces.append(f"party size {self.party_size}")
        if self.price_min is not None:
            pieces.append(f"at least AUD {self.price_min:.2f}")
        if self.price_max is not None:
            pieces.append(f"at most AUD {self.price_max:.2f}")
        if self.price_min is not None or self.price_max is not None:
            pieces.append(
                "for the whole party" if self.total_budget else "listed price"
            )
        if self.start_date:
            pieces.append(
                f"a catalogue schedule within {self.start_date} to {self.end_date}"
            )
        if self.window_start and self.window_end:
            pieces.append(
                f"local time {self.window_start:%H:%M} to {self.window_end:%H:%M}"
            )
        if self.accessibility:
            pieces.append(
                "required accessibility: "
                + ", ".join(field.replace("_", " ") for field in self.accessibility)
            )
        if self.booking_required is not None:
            pieces.append(
                "booking required" if self.booking_required else "no booking required"
            )
        return "Checked: " + "; ".join(pieces) + "." if pieces else ""


def parse_constraints(question: str) -> RequestConstraints:
    _validate_numeric_tokens(question)
    if re.search(
        r"\b(?:wheelchair|step[ -]free|accessible toilets?)\b", question, re.IGNORECASE
    ) and re.search(
        r"\b(?:no|not|without)\s+(?:wheelchair|step[ -]free|accessible)\b|"
        r"\b(?:wheelchair|step[ -]free|accessible toilets?).{0,30}"
        r"\b(?:not|unnecessary)\b",
        question,
        re.IGNORECASE,
    ):
        message = (
            "Please state the accessibility features you require without negation."
        )
        raise ClarificationError(message)
    minimum, maximum, total = _prices(question)
    start, end = _dates(question)
    window_start, window_end = _times(question)
    accessibility = tuple(
        field
        for term, field in (
            (r"\bwheelchair\b", "wheelchair_accessible"),
            (r"\bstep[ -]free\b", "step_free_access"),
            (r"\baccessible toilets?\b", "accessible_toilet"),
        )
        if re.search(term, question, re.IGNORECASE)
    )
    booking = (
        False
        if re.search(
            r"\b(?:no|without) (?:advance )?booking\b", question, re.IGNORECASE
        )
        else None
    )
    if booking is None and re.search(
        r"\bbooking (?:is )?required\b", question, re.IGNORECASE
    ):
        booking = True
    return RequestConstraints(
        party_size=_people(question),
        price_min=minimum,
        price_max=maximum,
        total_budget=total,
        start_date=start,
        end_date=end,
        window_start=window_start,
        window_end=window_end,
        accessibility=accessibility,
        booking_required=booking,
    )
