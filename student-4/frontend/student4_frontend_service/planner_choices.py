"""Pending human choices travel with the form until explicitly applied."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .models import ItinerarySelectionWrite

if TYPE_CHECKING:
    from starlette.datastructures import FormData

    from .planner_models import PlannerResponse


@dataclass
class Choices:
    decisions: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    dates: dict[str, str] = field(default_factory=dict)
    times: dict[str, str] = field(default_factory=dict)
    trip_ids: dict[str, str] = field(default_factory=dict)
    reviewer: str = ""
    trip_id: str = ""
    result_reason: str = ""

    @classmethod
    def from_form(cls, form: FormData) -> Choices:
        state = cls(
            reviewer=str(form.get("reviewer", "")).strip(),
            trip_id=str(form.get("trip_id", "")).strip(),
            result_reason=str(form.get("result_reason", "")).strip(),
        )
        for name, target in (
            ("trip_", state.trip_ids),
            ("choice_", state.decisions),
            ("reason_", state.reasons),
            ("date_", state.dates),
            ("start_time_", state.times),
        ):
            for key, value in form.multi_items():
                if key.startswith(name):
                    target[key.removeprefix(name)] = str(value).strip()
        return state

    def resolve(self, result: PlannerResponse) -> list[str]:
        ids = list(
            dict.fromkeys(
                str(part.activity_id)
                for part in result.answer.parts
                if part.type == "activity"
            )
        )
        self.decisions = {
            key: value
            for key, value in self.decisions.items()
            if key in ids and value in {"approve", "reject"}
        }
        self.reasons = {key: value for key, value in self.reasons.items() if key in ids}
        if result.item_decisions:
            self.decisions = {
                item.activity_id: item.decision for item in result.item_decisions
            }
            self.reasons = {
                item.activity_id: item.notes or "" for item in result.item_decisions
            }
            for item in result.item_decisions:
                if item.trip_id:
                    self.trip_ids[item.activity_id] = item.trip_id
                if item.date:
                    self.dates[item.activity_id] = item.date
                if item.start_time:
                    self.times[item.activity_id] = item.start_time
            if result.run.human:
                self.reviewer = result.run.human.reviewer
        self.trip_id = self.trip_id or result.run.trip_id or ""
        return ids

    def body(self, ids: list[str]) -> dict[str, object]:
        if not 1 <= len(self.reviewer) <= 60:
            msg = "Enter your name (1-60 characters) before applying decisions."
            raise ValueError(msg)
        if not ids:
            if len(self.result_reason) > 1000:
                msg = "Keep your rejection reason within 1000 characters."
                raise ValueError(msg)
            return {
                "decision": "reject",
                "reviewer": self.reviewer,
                "notes": self.result_reason or None,
            }
        if any(key not in self.decisions for key in ids):
            msg = "Approve or reject every suggestion before applying decisions."
            raise ValueError(msg)
        if any(len(reason) > 1000 for reason in self.reasons.values()):
            msg = "Keep each rejection reason within 1000 characters."
            raise ValueError(msg)
        approved = [key for key in ids if self.decisions[key] == "approve"]
        body: dict[str, object] = {
            "decision": "approve" if approved else "reject",
            "reviewer": self.reviewer,
            "item_decisions": [
                {
                    "activity_id": key,
                    "decision": self.decisions[key],
                    "notes": self.reasons.get(key) or None
                    if self.decisions[key] == "reject"
                    else None,
                }
                for key in ids
            ],
        }
        if approved:
            selections = []
            for key in approved:
                trip_id = self.trip_ids.get(key) or self.trip_id
                if not trip_id:
                    msg = "Choose an itinerary for each approved activity."
                    raise ValueError(msg)
                if not self.dates.get(key) or not self.times.get(key):
                    msg = "Choose a date and start time for each approved activity."
                    raise ValueError(msg)
                schedule = ItinerarySelectionWrite.model_validate(
                    {
                        "date": self.dates[key],
                        "start_time": self.times[key],
                    }
                ).model_dump(mode="json", exclude_none=True)
                selections.append({"activity_id": key, "trip_id": trip_id, **schedule})
            body["selections"] = selections
            body["item_decisions"] = [
                {**selection, "decision": "approve", "notes": None}
                for selection in selections
            ] + [
                {
                    "activity_id": key,
                    "decision": "reject",
                    "notes": self.reasons.get(key) or None,
                }
                for key in ids
                if self.decisions[key] == "reject"
            ]
        return body
