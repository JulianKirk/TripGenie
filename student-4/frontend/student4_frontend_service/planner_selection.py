"""Human selection presentation and explicit itinerary scheduling for Smart Planner."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlencode
from uuid import UUID

from .models import ItinerarySelectionWrite

if TYPE_CHECKING:
    from starlette.datastructures import FormData, QueryParams

    from .planner_models import PlannerResponse


@dataclass
class Selection:
    explicit: bool = False
    ids: list[str] = field(default_factory=list)
    trip_id: str = ""
    dates: dict[str, str] = field(default_factory=dict)
    times: dict[str, str] = field(default_factory=dict)
    feedback: str = ""
    previous_run_id: str = ""

    @classmethod
    def from_fields(cls, fields: FormData | QueryParams) -> Selection:
        parent = str(fields.get("previous_run_id", ""))
        ids = list(
            dict.fromkeys(str(value) for value in fields.getlist("selected_ids"))
        )
        return cls(
            explicit=str(fields.get("selection", "")) == "1",
            ids=ids,
            trip_id=str(fields.get("trip_id", "")),
            dates={
                key[5:]: str(value)
                for key, value in fields.items()
                if key.startswith("date_")
            },
            times={
                key[11:]: str(value)
                for key, value in fields.items()
                if key.startswith("start_time_")
            },
            feedback=str(fields.get("feedback", "")),
            previous_run_id=parent
            if re.fullmatch(r"magent_[0-9a-f]{12}", parent)
            else "",
        )

    def resolve(self, result: PlannerResponse) -> None:
        # Presentation IDs always come from the backend's grounded answer.
        available = result.answer.activities
        self.ids = (
            [key for key in self.ids if key in available]
            if self.explicit
            else list(available)
        )
        self.trip_id = self.trip_id or result.run.trip_id or ""
        self.previous_run_id = result.previous_run_id or self.previous_run_id

    def url(self, run_id: str, *, without: str | None = None) -> str:
        fields = (
            [
                ("selection", "1"),
                *[("selected_ids", key) for key in self.ids if key != without],
            ]
            if self.explicit
            else []
        )
        if self.trip_id:
            fields.append(("trip_id", self.trip_id))
        if self.previous_run_id:
            fields.append(("previous_run_id", self.previous_run_id))
        query = "?" + urlencode(fields) if fields else ""
        return f"/planner/{run_id}{query}"


def unchanged_narrative_after_dismissal(result: PlannerResponse) -> bool:
    if result.run.status != "completed" or result.run.result is None:
        return False
    original = result.run.result.get("parts")
    if not isinstance(original, list):
        return False
    cards = {
        str(part.get("activity_id"))
        for part in original
        if isinstance(part, dict) and part.get("type") == "activity"
    }
    texts = [
        part.get("text")
        for part in original
        if isinstance(part, dict) and part.get("type") == "text"
    ]
    displayed = [part.text for part in result.answer.parts if part.type == "text"]
    return set(result.answer.activities) != cards and displayed == texts


def scheduling_body(form: FormData, activity_ids: list[str]) -> dict[str, object]:
    selections: list[dict[str, object]] = []
    for key in activity_ids:
        schedule = ItinerarySelectionWrite.model_validate(
            {
                "date": str(form.get(f"date_{key}", "")).strip() or None,
                "start_time": str(form.get(f"start_time_{key}", "")).strip() or None,
            }
        )
        selections.append(
            {"activity_id": str(UUID(key)), **schedule.model_dump(mode="json")}
        )
    body: dict[str, object] = {"selections": selections}
    if trip_id := str(form.get("trip_id", "")).strip():
        body["trip_id"] = trip_id
    return body
