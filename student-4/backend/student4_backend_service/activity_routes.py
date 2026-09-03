from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID  # noqa: TC003 (FastAPI reads this at runtime)

from fastapi import APIRouter, Body, HTTPException, Query, status

from .dependencies import DbDep, LocationDep  # noqa: TC001 (FastAPI runtime)
from .schemas import (
    Activity,
    ActivityQuery,
    ActivitySummary,
    ActivityWrite,
    CategoryList,
    DeleteResponse,
    InternalActivity,
    InternalSummary,
    QueryResponse,
)

router = APIRouter(prefix="/activity", tags=["activity"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


async def _internal_write(
    payload: ActivityWrite, location: LocationDep
) -> dict[str, Any]:
    body = payload.model_dump(mode="json", exclude_none=True)
    public_location = body.pop("location_details")
    ids = await location.ids(public_location["country"], public_location["city"])
    if ids is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown country or city")
    country_id, city_id = ids
    if city_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown country or city")
    body["location_details"] = {
        "country_id": str(country_id),
        "city_id": str(city_id),
        **{
            key: value
            for key, value in public_location.items()
            if key not in {"country", "city"}
        },
    }
    return body


async def _public_activity(record: InternalActivity, location: LocationDep) -> Activity:
    body = record.model_dump(mode="json", exclude_none=True)
    place = body.pop("location_details")
    names = await location.names(
        [record.location_details.country_id, record.location_details.city_id]
    )
    body["location_details"] = {
        **{
            key: value
            for key, value in place.items()
            if key not in {"id", "country_id", "city_id"}
        },
    }
    if country := names.get(record.location_details.country_id):
        body["location_details"]["country"] = country
    if city := names.get(record.location_details.city_id):
        body["location_details"]["city"] = city
    return Activity.model_validate(body)


async def _public_summaries(
    records: list[InternalSummary], location: LocationDep
) -> list[ActivitySummary]:
    ids = [
        place_id
        for record in records
        for place_id in (
            record.location_details.country_id,
            record.location_details.city_id,
        )
    ]
    names = await location.names(ids)
    result: list[ActivitySummary] = []
    for record in records:
        body = record.model_dump(mode="json", exclude_none=True)
        place = body.pop("location_details")
        body["location_details"] = {
            **{
                key: value
                for key, value in place.items()
                if key not in {"country_id", "city_id"}
            },
        }
        if country := names.get(record.location_details.country_id):
            body["location_details"]["country"] = country
        if city := names.get(record.location_details.city_id):
            body["location_details"]["city"] = city
        result.append(ActivitySummary.model_validate(body))
    return result


async def _query(
    query: ActivityQuery, db: DbDep, location: LocationDep
) -> QueryResponse:
    body = query.model_dump(mode="json", exclude_none=True)
    include_inactive = body.pop("include_inactive")
    if not include_inactive:
        body["is_active"] = True
    place = body.pop("location", None)
    if place:
        body["location_details"] = {
            **{
                key: value
                for key, value in place.items()
                if key not in {"country", "city"}
            },
        }
        if place.get("country"):
            ids = await location.ids(place["country"], place.get("city"))
            if ids is None:
                return QueryResponse(
                    activities=[], total=0, limit=query.limit, offset=query.offset
                )
            country_id, city_id = ids
            body["location_details"]["country_id"] = str(country_id)
            if city_id is not None:
                body["location_details"]["city_id"] = str(city_id)
    result = await db.query(body)
    return QueryResponse(
        activities=await _public_summaries(result.activities, location),
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/categories", response_model=CategoryList)
async def categories(db: DbDep) -> CategoryList:
    return await db.categories()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Activity,
    response_model_exclude_none=True,
)
async def create(payload: ActivityWrite, db: DbDep, location: LocationDep) -> Activity:
    return await _public_activity(
        await db.create(await _internal_write(payload, location)), location
    )


@router.get("", response_model=QueryResponse, response_model_exclude_none=True)
async def list_activities(
    db: DbDep, location: LocationDep, limit: Limit = 20, offset: Offset = 0
) -> QueryResponse:
    return await _query(ActivityQuery(limit=limit, offset=offset), db, location)


@router.api_route(
    "",
    methods=["QUERY"],
    response_model=QueryResponse,
    response_model_exclude_none=True,
)
async def query_activities(
    db: DbDep,
    location: LocationDep,
    query: ActivityQuery = Body(default_factory=ActivityQuery),
) -> QueryResponse:
    return await _query(query, db, location)


@router.get("/{activity_id}", response_model=Activity, response_model_exclude_none=True)
async def get(activity_id: UUID, db: DbDep, location: LocationDep) -> Activity:
    return await _public_activity(await db.get(activity_id), location)


@router.put("/{activity_id}", response_model=Activity, response_model_exclude_none=True)
async def replace(
    activity_id: UUID,
    payload: ActivityWrite,
    db: DbDep,
    location: LocationDep,
) -> Activity:
    return await _public_activity(
        await db.replace(activity_id, await _internal_write(payload, location)),
        location,
    )


@router.delete("/{activity_id}", response_model=DeleteResponse)
async def delete(activity_id: UUID, db: DbDep) -> DeleteResponse:
    return await db.delete(activity_id)
