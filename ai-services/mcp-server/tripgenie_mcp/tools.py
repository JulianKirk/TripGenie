"""Bounded tools backed by public student APIs."""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BeforeValidator, Field, ValidationError

from .activity_models import Activity, ActivityFilters, ActivityWrite
from .provider import ProviderClient, ProviderError, request_correlation

TRIP_ID = re.compile(r"trip_[A-Za-z0-9][A-Za-z0-9_-]{2,63}\Z")
ITEM_ID = re.compile(r"item_[A-Za-z0-9][A-Za-z0-9_-]{2,63}\Z")
TRANSPORT_ID = re.compile(r"transport_[A-Za-z0-9][A-Za-z0-9_-]{2,53}\Z")
CORRELATION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
CATEGORIES = {"accommodation", "transport", "activities", "food", "shopping", "other"}
EXACT_MONEY = re.compile(r"-?\d+\.\d{2}\Z")
CURRENCY = re.compile(r"[A-Z]{3}\Z")


def explicit_confirmation(value: object) -> bool:
    if value is not True:
        raise ValueError("Deletion requires the boolean true")
    return True


def invalid(message: str) -> None:
    raise ProviderError("VALIDATION_ERROR", message)


def identifier(value: str, kind: str) -> str:
    if not isinstance(value, str):
        invalid("Invalid identifier")
    if kind == "uuid":
        try:
            UUID(value)
        except ValueError:
            invalid("Expected a UUID")
    elif kind == "trip":
        if not TRIP_ID.fullmatch(value):
            invalid("Invalid trip ID")
    elif kind == "item":
        if not ITEM_ID.fullmatch(value):
            invalid("Invalid itinerary item ID")
    elif kind == "transport":
        if not TRANSPORT_ID.fullmatch(value):
            invalid("Invalid transport ID")
    elif not 1 <= len(value) <= 100 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        invalid("Invalid identifier")
    return value


def limit_value(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 50:
        invalid("Limit must be between 1 and 50")
    return value


def record(value: object, *fields: str) -> dict:
    if not isinstance(value, dict) or any(field not in value for field in fields):
        raise ProviderError("INVALID_RESPONSE", "Malformed provider record")
    return value


def matching(value: object, field: str, expected: str) -> dict:
    item = record(value, field)
    if item[field] != expected:
        raise ProviderError("INVALID_RESPONSE", "Provider returned a different ID")
    return item


def money(value: object) -> str:
    try:
        decimal = Decimal(str(value))
        if not decimal.is_finite() or decimal < 0 or decimal.as_tuple().exponent < -2:
            raise InvalidOperation
        return f"{decimal:.2f}"
    except (InvalidOperation, ValueError):
        raise ProviderError("INVALID_RESPONSE", "Invalid provider price") from None


def exact_money(value: object, *, signed: bool = False) -> None:
    if not isinstance(value, str) or not EXACT_MONEY.fullmatch(value):
        raise ProviderError("INVALID_RESPONSE", "Invalid money representation")
    if not signed and value.startswith("-"):
        raise ProviderError("INVALID_RESPONSE", "Negative provider cost")


def currency(value: object) -> None:
    if not isinstance(value, str) or not CURRENCY.fullmatch(value):
        raise ProviderError("INVALID_RESPONSE", "Invalid currency")


def committed(value: object) -> dict:
    result = record(value, "committed_cost_total", "currency", "items")
    exact_money(result["committed_cost_total"])
    currency(result["currency"])
    if not isinstance(result["items"], list):
        raise ProviderError("INVALID_RESPONSE", "Invalid committed-cost items")
    for item in result["items"]:
        record(item, "item_id", "amount", "currency")
        exact_money(item["amount"])
        currency(item["currency"])
    return result


def page(
    value: object, key: str | None, limit: int, id_field: str, kind: str
) -> dict[str, object]:
    if key is None:
        rows, total = value, None
    else:
        payload = record(value, key, "total")
        rows, total = payload[key], payload["total"]
        if type(total) is not int or total < 0:
            raise ProviderError("INVALID_RESPONSE", "Invalid result count")
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get(id_field), str)
        for row in rows
    ):
        raise ProviderError("INVALID_RESPONSE", "Invalid result items")
    for row in rows:
        try:
            identifier(row[id_field], kind)
        except ProviderError:
            raise ProviderError("INVALID_RESPONSE", "Invalid provider ID") from None
    return {
        "items": rows[:limit],
        "count": min(len(rows), limit),
        "truncated": total > limit if total is not None else len(rows) > limit,
    }


class DomainTools:
    def __init__(self, provider: ProviderClient):
        self.provider = provider

    def execute(self, owner: str, action, correlation_id: str | None = None) -> dict:
        correlation_id = correlation_id or f"mcp-{uuid4().hex[:12]}"
        if not CORRELATION_ID.fullmatch(correlation_id):
            correlation_id = f"mcp-{uuid4().hex[:12]}"
        token = request_correlation.set(correlation_id)
        try:
            data = action()
            if len(json.dumps(data, ensure_ascii=True).encode()) > 32768:
                raise ProviderError("INVALID_RESPONSE", "Tool result exceeds 32 KB")
            return {
                "ok": True,
                "data": data,
                "correlation_id": correlation_id,
                "source": owner,
            }
        except ProviderError as exc:
            return {
                "ok": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                },
                "correlation_id": correlation_id,
                "source": owner,
            }

        finally:
            request_correlation.reset(token)

    def trip_get_context(self, trip_id: str) -> dict:
        value = self.provider.read(
            "student-1", f"/api/trips/{identifier(trip_id, 'trip')}"
        )
        return matching(value, "id", trip_id)

    def trips_list_itinerary_items(self, trip_id: str, limit: int = 20) -> dict:
        limit_value(limit)
        value = self.provider.read(
            "student-1", f"/api/trips/{identifier(trip_id, 'trip')}/itinerary-items"
        )
        return page(value, None, limit, "id", "item")

    def accommodations_search(
        self, country: str | None = None, city: str | None = None, limit: int = 20
    ) -> dict:
        limit_value(limit)
        if city and not country:
            invalid("City requires country")
        for value in (country, city):
            if value is not None and (not value.strip() or len(value) > 100):
                invalid("Invalid location filter")
        if country:
            query = {"accommodation": {"location_details": {"country": country}}}
            if city:
                query["accommodation"]["location_details"]["city"] = city
            query["limit"] = limit
            value = self.provider.read("student-2", "/accommodation", query=query)
        else:
            value = self.provider.read(
                "student-2", "/accommodation", params={"limit": limit}
            )
        result = page(value, "accommodations", limit, "id", "uuid")
        for item in result["items"]:
            item["price_per_night"] = money(
                record(item, "price_per_night")["price_per_night"]
            )
        return result

    def accommodations_get(self, accommodation_id: str) -> dict:
        value = self.provider.read(
            "student-2", f"/accommodation/{identifier(accommodation_id, 'uuid')}"
        )
        item = matching(value, "id", accommodation_id)
        record(item, "price_per_night")
        item["price_per_night"] = money(item["price_per_night"])
        return item

    def accommodations_committed_costs(self, trip_id: str) -> dict:
        value = self.provider.read(
            "student-2",
            f"/accommodation/trips/{identifier(trip_id, 'trip')}/committed-costs",
        )
        return committed(value)

    def transport_search(
        self, origin: str | None = None, destination: str | None = None, limit: int = 20
    ) -> dict:
        limit_value(limit)
        params = {}
        for field, value in (("origin", origin), ("destination", destination)):
            if value is not None:
                if not value.strip() or len(value) > 255:
                    invalid("Invalid transport filter")
                params[field] = value
        value = self.provider.read("student-3", "/api/transport-options", params=params)
        result = page(value, None, limit, "id", "transport")
        for item in result["items"]:
            item["price"] = money(record(item, "price", "pricing_basis")["price"])
        return result

    def transport_get(self, transport_id: str) -> dict:
        value = self.provider.read(
            "student-3",
            f"/api/transport-options/{identifier(transport_id, 'transport')}",
        )
        item = matching(value, "id", transport_id)
        record(item, "price", "pricing_basis")
        item["price"] = money(item["price"])
        return item

    def transport_compare(self, ids: list[str]) -> dict:
        if not isinstance(ids, list) or not 1 <= len(ids) <= 4:
            invalid("Select one to four transport IDs")
        cleaned = [identifier(value, "transport") for value in ids]
        if len(set(cleaned)) != len(cleaned):
            invalid("Transport IDs must be unique")
        value = self.provider.read(
            "student-3",
            "/api/transport-options/compare",
            params={"ids": ",".join(cleaned)},
        )
        result = page(value, None, 4, "id", "transport")
        if {item["id"] for item in result["items"]} != set(cleaned):
            raise ProviderError("INVALID_RESPONSE", "Comparison IDs do not match")
        for item in result["items"]:
            item["price"] = money(record(item, "price", "pricing_basis")["price"])
        return result

    def transport_trip_costs(self, trip_id: str) -> dict:
        value = self.provider.read(
            "student-3", f"/api/trips/{identifier(trip_id, 'trip')}/transport"
        )
        summary = matching(value, "trip_id", trip_id)
        record(
            summary,
            "currency",
            "entry_count",
            "active_entry_count",
            "estimated_cost_total",
            "planned",
        )
        if not isinstance(summary["planned"], list):
            raise ProviderError("INVALID_RESPONSE", "Invalid transport costs")
        summary["estimated_cost_total"] = money(summary["estimated_cost_total"])
        for item in summary["planned"]:
            record(item, "entry", "option", "estimated_cost")
            entry = record(item["entry"], "transport_id")
            option = matching(item["option"], "id", entry["transport_id"])
            record(option, "price", "pricing_basis")
            try:
                identifier(option["id"], "transport")
            except ProviderError:
                raise ProviderError(
                    "INVALID_RESPONSE", "Invalid transport ID"
                ) from None
            option["price"] = money(option["price"])
            item["estimated_cost"] = money(item["estimated_cost"])
        return summary

    def activities_search(
        self,
        text: str | None = None,
        limit: Annotated[int, Field(ge=1, le=50, strict=True)] = 20,
        offset: Annotated[int, Field(ge=0, strict=True)] = 0,
        filters: ActivityFilters | None = None,
    ) -> dict:
        limit_value(limit)
        if type(offset) is not int or offset < 0:
            invalid("Offset must be non-negative")
        if text is not None and (not text.strip() or len(text) > 255):
            invalid("Invalid search text")
        query = filters.model_dump(mode="json", exclude_unset=True) if filters else {}
        if text:
            query["text"] = text
        query.update(limit=limit, offset=offset)
        value = self.provider.read(
            "student-4",
            "/activity",
            query=query if filters is not None or text else None,
            params={"limit": limit, "offset": offset}
            if filters is None and not text
            else None,
        )
        result = page(value, "activities", limit, "id", "uuid")
        result["truncated"] = value["total"] > offset + len(result["items"])
        for item in result["items"]:
            exact_money(record(item, "price", "pricing_basis")["price"])
            if item["pricing_basis"] not in ("PER_PERSON", "FLAT_ADMISSION"):
                raise ProviderError(
                    "INVALID_RESPONSE", "Invalid activity pricing basis"
                )
        return result

    def _activity_write(
        self, method: str, activity: ActivityWrite, activity_id: str | None = None
    ) -> dict:
        path = (
            "/activity"
            if activity_id is None
            else f"/activity/{identifier(activity_id, 'uuid')}"
        )
        body = activity.model_dump(mode="json")
        # Reserve the generated record and schedule UUIDs before mutating anything.
        projected = body | {"id": str(UUID(int=0))}
        projected["availability_schedules"] = [
            schedule | {"id": str(UUID(int=0))}
            for schedule in body["availability_schedules"]
        ]
        if len(json.dumps(projected, ensure_ascii=True).encode()) > 32768:
            invalid("Activity including generated IDs must fit within 32 KB")
        value = self.provider.write(path, method=method, body=body)
        try:
            parsed = Activity.model_validate(value)
            if activity_id is not None and parsed.id != UUID(activity_id):
                raise ValueError("Mismatched activity ID")
            result = parsed.model_dump(mode="json")
            if len(json.dumps(result, ensure_ascii=True).encode()) > 32768:
                raise ValueError("Oversized write acknowledgement")
            return result
        except (ValidationError, ValueError) as exc:
            raise ProviderError(
                "WRITE_OUTCOME_UNKNOWN",
                "Invalid write acknowledgement; inspect the catalogue before retrying",
            ) from exc

    def activities_create(self, activity: ActivityWrite) -> dict:
        return self._activity_write("POST", activity)

    def activities_update(self, activity_id: UUID, activity: ActivityWrite) -> dict:
        return self._activity_write("PUT", activity, str(activity_id))

    def activities_delete(
        self,
        activity_id: UUID,
        confirm: Annotated[Literal[True], BeforeValidator(explicit_confirmation)],
    ) -> dict:
        if confirm is not True:
            invalid("Deletion requires confirm=true")
        activity_id = identifier(str(activity_id), "uuid")
        value = self.provider.write(f"/activity/{activity_id}", method="DELETE")
        if (
            value.get("id") != activity_id
            or value.get("deleted") is not True
            or set(value) != {"id", "deleted"}
        ):
            raise ProviderError(
                "WRITE_OUTCOME_UNKNOWN",
                "Invalid deletion acknowledgement; "
                "inspect the catalogue before retrying",
            )
        return value

    def activities_get(self, activity_id: str) -> dict:
        value = self.provider.read(
            "student-4", f"/activity/{identifier(activity_id, 'uuid')}"
        )
        item = matching(value, "id", activity_id)
        exact_money(record(item, "price", "pricing_basis")["price"])
        if item["pricing_basis"] not in ("PER_PERSON", "FLAT_ADMISSION"):
            raise ProviderError("INVALID_RESPONSE", "Invalid activity pricing basis")
        return item

    def activities_list_categories(self) -> dict:
        value = self.provider.read("student-4", "/activity/categories")
        return record(value, "categories")

    def activities_committed_costs(self, trip_id: str) -> dict:
        value = self.provider.read(
            "student-4",
            f"/activity/trips/{identifier(trip_id, 'trip')}/committed-costs",
        )
        return committed(value)

    def budgets_list(self, trip_id: str | None = None, limit: int = 20) -> dict:
        limit_value(limit)
        if trip_id is not None and not 1 <= len(trip_id) <= 100:
            invalid("Invalid trip ID")
        value = self.provider.read(
            "student-5",
            "/api/v1/budgets",
            params={"trip_id": trip_id} if trip_id else None,
        )
        result = page(value, None, limit, "budget_id", "uuid")
        for item in result["items"]:
            record(item, "trip_id", "currency", "total_budget")
            currency(item["currency"])
            exact_money(item["total_budget"])
        return {
            "budgets": [
                {
                    key: record(
                        item, "budget_id", "trip_id", "currency", "total_budget"
                    )[key]
                    for key in ("budget_id", "trip_id", "currency", "total_budget")
                }
                for item in result["items"]
            ],
            "count": result["count"],
            "truncated": result["truncated"],
        }

    def budgets_get_summary(self, budget_id: str) -> dict:
        value = self.provider.read(
            "student-5", f"/api/v1/budgets/{identifier(budget_id, 'uuid')}/summary"
        )
        summary = record(
            value,
            "budget_id",
            "trip_id",
            "currency",
            "total_budget",
            "actual_spending",
            "committed_costs",
            "remaining_budget",
            "category_totals",
            "providers",
            "actual_spending_complete",
            "committed_costs_complete",
            "remaining_budget_complete",
            "unconverted_expense_count",
        )
        matching(summary, "budget_id", budget_id)
        currency(summary["currency"])
        for field in ("total_budget", "actual_spending", "committed_costs"):
            exact_money(summary[field])
        exact_money(summary["remaining_budget"], signed=True)
        if not isinstance(summary["category_totals"], dict):
            raise ProviderError("INVALID_RESPONSE", "Invalid category totals")
        for amount in summary["category_totals"].values():
            exact_money(amount)
        flags = (
            "actual_spending_complete",
            "committed_costs_complete",
            "remaining_budget_complete",
        )
        if any(type(summary[field]) is not bool for field in flags) or (
            type(summary["unconverted_expense_count"]) is not int
            or summary["unconverted_expense_count"] < 0
        ):
            raise ProviderError("INVALID_RESPONSE", "Invalid summary completeness")
        if not isinstance(summary["providers"], dict) or any(
            not isinstance(provider, dict)
            or provider.get("status")
            not in ("available", "unavailable", "invalid_response")
            or (
                provider["status"] != "available"
                and provider.get("subtotal") is not None
            )
            for provider in summary["providers"].values()
        ):
            raise ProviderError("INVALID_RESPONSE", "Invalid provider availability")
        for provider in summary["providers"].values():
            if provider["status"] == "available":
                exact_money(provider.get("subtotal"))
                currency(provider.get("currency"))
        return summary

    def expenses_list(
        self,
        trip_id: str,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> dict:
        limit_value(limit)
        if not isinstance(trip_id, str) or not 1 <= len(trip_id) <= 100:
            invalid("Invalid trip ID")
        if category is not None and category not in CATEGORIES:
            invalid("Invalid expense category")
        for value in (date_from, date_to):
            if value is not None:
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except (TypeError, ValueError):
                    invalid("Invalid ISO date")
        if date_from and date_to and date_from > date_to:
            invalid("Date range is reversed")
        params = {"trip_id": trip_id}
        params.update(
            {
                key: value
                for key, value in (
                    ("category", category),
                    ("date_from", date_from),
                    ("date_to", date_to),
                )
                if value is not None
            }
        )
        value = self.provider.read("student-5", "/api/v1/expenses", params=params)
        result = page(value, None, limit, "expense_id", "uuid")
        fields = (
            "expense_id",
            "trip_id",
            "category",
            "description",
            "amount",
            "currency",
            "date",
        )
        for item in result["items"]:
            record(item, *fields)
            exact_money(item["amount"])
            currency(item["currency"])
        return {
            "expenses": [
                {key: record(item, *fields)[key] for key in fields}
                for item in result["items"]
            ],
            "count": result["count"],
            "truncated": result["truncated"],
        }
