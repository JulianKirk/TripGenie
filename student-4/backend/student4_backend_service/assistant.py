"""Submit to shared generation and resolve grounded activity cards for display."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from .ai_mode_client import GenerationError
from .ai_recommendations import _prompt_asset
from .assistant_models import ActivityPart, AssistantResponse, FinalAction

if TYPE_CHECKING:
    from .ai_mode_client import AiModeClient
    from .assistant_models import AssistantRequest, ToolTrace
    from .config import Settings
    from .schemas import Activity

ActivityLookup = Callable[[UUID], Awaitable["Activity"]]


def _activity_ids(trace: ToolTrace) -> set[str]:
    if trace.status != "success" or trace.result is None:
        return set()
    envelope = trace.result.get("structuredContent")
    if (
        not isinstance(envelope, dict)
        or envelope.get("source") != "student-4"
        or envelope.get("ok") is not True
    ):
        return set()
    data = envelope.get("data")
    if not isinstance(data, dict):
        return set()
    rows: list[Any] = data.get("items", [data])
    if not isinstance(rows, list):
        return set()
    return {
        str(UUID(str(row["id"])))
        for row in rows
        if isinstance(row, dict) and "id" in row
    }


async def answer(
    payload: AssistantRequest,
    settings: Settings,
    ai: AiModeClient,
    *,
    resolve_activity: ActivityLookup,
) -> AssistantResponse:
    result = AssistantResponse(request_id=f"student4-agent-{uuid4().hex[:16]}")
    if not settings.assistant_enabled:
        result.error = (
            "The activity assistant is disabled. "
            "Ordinary activity browsing is still available."
        )
        return result
    try:
        generated = await ai.generate(
            prompt=json.dumps(
                {"question": payload.question, "selected_trip_id": payload.trip_id}
            ),
            system=_prompt_asset(settings.ai_assistant_prompt_asset),
            schema=FinalAction.model_json_schema(),
            correlation_id=result.request_id,
            metadata={
                "service": settings.service_name,
                "feature": "activity-assistant",
            },
            request_timeout=settings.agent_timeout,
        )
        result.tools, result.model, result.provider = (
            generated.tools,
            generated.model,
            generated.provider,
        )
        action = FinalAction.model_validate_json(generated.response)
        known_ids = set().union(*(_activity_ids(trace) for trace in result.tools))
        references = [
            str(part.activity_id)
            for part in action.parts
            if isinstance(part, ActivityPart)
        ]
        if len(references) > 6 or any(
            activity_id not in known_ids for activity_id in references
        ):
            message = "Ungrounded or excessive activity references"
            raise ValueError(message)
        for activity_id in dict.fromkeys(references):
            try:
                activity = await resolve_activity(UUID(activity_id))
            except HTTPException:
                result.unavailable_activity_ids.append(activity_id)
                continue
            if str(activity.id) != activity_id:
                message = "Activity lookup returned another ID"
                raise ValueError(message)
            result.activities[activity_id] = activity
        result.parts, result.status = action.parts, "complete"
    except GenerationError as exc:
        result.tools = exc.tools
        result.error = str(exc.detail)
    except HTTPException as exc:
        result.error = str(exc.detail)
    except (ValueError, ValidationError):
        result.activities = {}
        result.error = (
            "The assistant returned an invalid or ungrounded answer. Please try again."
        )
    return result
