"""Thin HTTP routes for activity aggregate persistence and search."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, status

from student4_database_service.dependencies import SessionDep
from student4_database_service.repository import ActivityRepository
from student4_database_service.schemas import (
    ActivityQueryRequest,
    ActivityQueryResponse,
    ActivityRecord,
    ActivityWrite,
    CategoryListResponse,
    DeleteResponse,
)

router = APIRouter(prefix="/internal/activity", tags=["activity"])


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "activity not found")


@router.get(
    "/categories",
    response_model=CategoryListResponse,
    response_model_exclude_none=True,
)
def list_categories(session: SessionDep) -> CategoryListResponse:
    return CategoryListResponse(
        categories=ActivityRepository(session).list_categories()
    )


@router.get(
    "/{activity_id}",
    response_model=ActivityRecord,
    response_model_exclude_none=True,
)
def get_activity(activity_id: UUID, session: SessionDep) -> ActivityRecord:
    record = ActivityRepository(session).get(activity_id)
    if record is None:
        raise _not_found()
    return record


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=ActivityQueryResponse,
    response_model_exclude_none=True,
)
def query_activities(
    session: SessionDep,
    query: ActivityQueryRequest = Body(default_factory=ActivityQueryRequest),
) -> ActivityQueryResponse:
    rows, total = ActivityRepository(session).search(query)
    return ActivityQueryResponse(
        activities=rows, total=total, limit=query.limit, offset=query.offset
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ActivityRecord,
    response_model_exclude_none=True,
)
def create_activity(payload: ActivityWrite, session: SessionDep) -> ActivityRecord:
    try:
        return ActivityRepository(session).add(payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.put(
    "/{activity_id}",
    response_model=ActivityRecord,
    response_model_exclude_none=True,
)
def replace_activity(
    activity_id: UUID, payload: ActivityWrite, session: SessionDep
) -> ActivityRecord:
    try:
        record = ActivityRepository(session).replace(activity_id, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if record is None:
        raise _not_found()
    return record


@router.delete("/{activity_id}", response_model=DeleteResponse)
def delete_activity(activity_id: UUID, session: SessionDep) -> DeleteResponse:
    if not ActivityRepository(session).delete(activity_id):
        raise _not_found()
    return DeleteResponse(id=activity_id, deleted=True)
