from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest
from student4_backend_service.assistant_constraints import RequestConstraints
from student4_backend_service.assistant_final import resolve_cards
from student4_backend_service.assistant_models import AssistantResponse, FinalAction
from student4_backend_service.assistant_tools import AgentError, ToolExecutor

from tests.backend.test_assistant import ACTIVITY, DETAIL


class FinalExecutor(ToolExecutor):
    def __init__(self, *, price: str = "45.00", unavailable: bool = False) -> None:
        self.known_ids = {ACTIVITY}
        self.result = AssistantResponse(request_id="final-test")
        self.calls: list[str] = []
        self.price = price
        self.unavailable = unavailable
        self.pricing_basis = "PER_PERSON"

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name == "activities_get"
        self.calls.append(arguments["activity_id"])
        return {
            "ok": not self.unavailable,
            "data": {
                **DETAIL,
                "id": arguments["activity_id"],
                "price": self.price,
                "pricing_basis": self.pricing_basis,
            },
        }


def finish(
    executor: FinalExecutor,
    constraints: RequestConstraints,
    *,
    ids: list[str] | None = None,
    eligible: set[str] | None = None,
    requested: bool = True,
) -> dict[str, Any]:
    action = FinalAction.model_validate(
        {
            "type": "final",
            "parts": [{"type": "text", "text": "Unverified model claim"}]
            + [{"type": "activity", "activity_id": value} for value in ids or []],
        }
    )
    asyncio.run(
        resolve_cards(
            action,
            executor,
            constraints,
            eligible_ids=eligible or set(),
            activity_data_requested=requested,
        )
    )
    return executor.result.model_dump(mode="json")


def test_text_only_final_uses_fresh_eligible_cards_and_exact_party_total() -> None:
    executor = FinalExecutor()
    result = finish(
        executor,
        RequestConstraints(party_size=2, total_budget=True, price_max=Decimal(100)),
        eligible={ACTIVITY},
    )
    assert executor.calls == [ACTIVITY]
    assert result["activities"][ACTIVITY]["price"] == "45.00"
    assert result["parts"][1] == {"type": "activity", "activity_id": ACTIVITY}
    assert "AUD 90.00" in result["parts"][0]["text"]
    assert "Unverified" not in result["parts"][0]["text"]


@pytest.mark.parametrize("unavailable", [False, True])
def test_text_only_final_does_not_restore_rejected_or_unavailable_candidates(
    unavailable: bool,
) -> None:
    executor = FinalExecutor(price="200.00", unavailable=unavailable)
    result = finish(
        executor, RequestConstraints(price_max=Decimal(100)), eligible={ACTIVITY}
    )
    assert result["activities"] == {}
    assert len(result["parts"]) == 1
    assert "inspected results" in result["parts"][0]["text"]
    assert result["unavailable_activity_ids"] == ([ACTIVITY] if unavailable else [])


def test_price_claim_without_activity_read_is_suppressed() -> None:
    executor = FinalExecutor()
    result = finish(
        executor, RequestConstraints(price_max=Decimal(100)), requested=False
    )
    assert executor.calls == []
    assert "cannot verify" in result["parts"][0]["text"].lower()
    assert "Unverified" not in result["parts"][0]["text"]


def test_trip_factual_text_without_activity_read_is_preserved() -> None:
    result = finish(FinalExecutor(), RequestConstraints(party_size=2), requested=False)
    assert result["parts"] == [{"type": "text", "text": "Unverified model claim"}]


def test_explicit_unknown_card_is_rejected_before_lookup() -> None:
    executor = FinalExecutor()
    with pytest.raises(AgentError, match="outside this request"):
        finish(
            executor, RequestConstraints(), ids=["11111111-1111-1111-1111-111111111111"]
        )
    assert executor.calls == []


def test_explicit_duplicate_references_still_obey_six_card_limit() -> None:
    executor = FinalExecutor()
    with pytest.raises(AgentError, match="too many"):
        finish(executor, RequestConstraints(), ids=[ACTIVITY] * 7)
    assert executor.calls == []


def test_text_only_candidates_are_sorted_and_bounded_to_six_fresh_reads() -> None:
    executor = FinalExecutor()
    executor.known_ids = {f"11111111-1111-1111-1111-{index:012d}" for index in range(8)}
    result = finish(
        executor, RequestConstraints(party_size=2), eligible=executor.known_ids
    )
    assert executor.calls == sorted(executor.known_ids)[:6]
    assert len(result["activities"]) == 6
    assert len(result["parts"]) == 7
    assert len(result["parts"][0]["text"]) <= 1000


def test_flat_admission_party_total_is_not_multiplied() -> None:
    executor = FinalExecutor(price="45.01")
    executor.pricing_basis = "FLAT_ADMISSION"
    result = finish(executor, RequestConstraints(party_size=3), eligible={ACTIVITY})
    assert "AUD 45.01" in result["parts"][0]["text"]
    assert "AUD 135.03" not in result["parts"][0]["text"]


def test_unconstrained_failed_card_keeps_unavailable_reference() -> None:
    result = finish(
        FinalExecutor(unavailable=True), RequestConstraints(), ids=[ACTIVITY]
    )
    assert result["unavailable_activity_ids"] == [ACTIVITY]
    assert result["parts"][1] == {"type": "activity", "activity_id": ACTIVITY}


def test_no_eligible_activity_limits_no_match_statement_to_inspected_results() -> None:
    executor = FinalExecutor()
    result = finish(executor, RequestConstraints(price_max=Decimal(100)))
    assert executor.calls == []
    assert result["activities"] == {}
    assert "inspected results" in result["parts"][0]["text"]


def test_authored_party_total_preserves_more_than_28_digits() -> None:
    result = finish(
        FinalExecutor(price="123456789012345678901234567890.12"),
        RequestConstraints(party_size=3),
        eligible={ACTIVITY},
    )
    assert "AUD 370370367037037036703703703670.36" in result["parts"][0]["text"]
