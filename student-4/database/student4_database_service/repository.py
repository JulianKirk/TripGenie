"""Transactional persistence and composable activity search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Numeric, String, and_, cast, func, or_, select
from sqlalchemy.orm import selectinload

from student4_database_service.enums import ActivitySort, CategoryMatch, DayOfWeek
from student4_database_service.models import (
    Activity,
    ActivityAvailabilitySchedule,
    ActivityCategory,
    Category,
    LocationDetails,
)
from student4_database_service.schemas import (
    ActivityQueryRequest,
    ActivityRecord,
    ActivitySummary,
    ActivityWrite,
    CategoryRecord,
)

WEEKDAYS = (
    DayOfWeek.MONDAY,
    DayOfWeek.TUESDAY,
    DayOfWeek.WEDNESDAY,
    DayOfWeek.THURSDAY,
    DayOfWeek.FRIDAY,
    DayOfWeek.SATURDAY,
    DayOfWeek.SUNDAY,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import Select
    from sqlalchemy.orm import Session


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _with_aggregate() -> tuple[Any, ...]:
    return (
        selectinload(Activity.location_details),
        selectinload(Activity.category_links),
        selectinload(Activity.availability_schedules),
    )


def _substring_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _price_at_least(column: Any, value: Any) -> Any:
    wanted = f"{value:.2f}"
    wanted_digits = len(wanted.partition(".")[0])
    stored_digits = func.instr(column, ".") - 1
    return or_(
        stored_digits > wanted_digits,
        and_(stored_digits == wanted_digits, column >= wanted),
    )


def _price_at_most(column: Any, value: Any) -> Any:
    wanted = f"{value:.2f}"
    wanted_digits = len(wanted.partition(".")[0])
    stored_digits = func.instr(column, ".") - 1
    return or_(
        stored_digits < wanted_digits,
        and_(stored_digits == wanted_digits, column <= wanted),
    )


class ActivityRepository:
    def __init__(self, session: Session):
        self.session = session

    def _row(self, activity_id: UUID) -> Activity | None:
        statement = (
            select(Activity)
            .options(*_with_aggregate())
            .where(Activity.id == activity_id)
        )
        return self.session.scalar(statement)

    def _ensure_categories(self, message: ActivityWrite) -> None:
        wanted = set(message.categories)
        found = set(
            self.session.scalars(select(Category.code).where(Category.code.in_(wanted)))
        )
        missing = sorted(code.value for code in wanted - found)
        if missing:
            message_text = f"unsupported category: {', '.join(missing)}"
            raise ValueError(message_text)

    def list_categories(self) -> list[CategoryRecord]:
        rows = self.session.scalars(
            select(Category).order_by(Category.display_order, Category.code)
        )
        return [
            CategoryRecord(
                code=row.code,
                label=row.label,
                description=row.description,
                display_order=row.display_order,
            )
            for row in rows
        ]

    def add(self, message: ActivityWrite) -> ActivityRecord:
        self._ensure_categories(message)
        row = Activity.from_message(message)
        self.session.add(row)
        _commit(self.session)
        return row.to_record()

    def get(self, activity_id: UUID) -> ActivityRecord | None:
        row = self._row(activity_id)
        return None if row is None else row.to_record()

    def replace(
        self, activity_id: UUID, message: ActivityWrite
    ) -> ActivityRecord | None:
        row = self._row(activity_id)
        if row is None:
            return None
        self._ensure_categories(message)
        try:
            row.apply(message)
            row.location_details.apply(message)
            row.category_links.clear()
            row.availability_schedules.clear()
            self.session.flush()
            row.category_links = [
                ActivityCategory(category_code=code) for code in message.categories
            ]
            row.availability_schedules = [
                ActivityAvailabilitySchedule.from_message(schedule)
                for schedule in message.availability_schedules
            ]
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return row.to_record()

    def delete(self, activity_id: UUID) -> bool:
        row = self._row(activity_id)
        if row is None:
            return False
        self.session.delete(row)
        _commit(self.session)
        return True

    def search(self, query: ActivityQueryRequest) -> tuple[list[ActivitySummary], int]:
        statement = select(Activity).options(*_with_aggregate())
        statement = self._apply_filters(statement, query)
        count_statement = select(func.count()).select_from(
            statement.order_by(None).subquery()
        )
        total = self.session.scalar(count_statement) or 0
        statement = self._apply_order(statement, query)
        rows = self.session.scalars(statement.limit(query.limit).offset(query.offset))
        return [row.to_summary() for row in rows], total

    def _apply_filters(
        self, statement: Select[tuple[Activity]], query: ActivityQueryRequest
    ) -> Select[tuple[Activity]]:
        if query.text is not None:
            pattern = _substring_pattern(query.text.casefold())
            statement = statement.where(
                or_(
                    func.unicode_casefold(Activity.name).like(pattern, escape="\\"),
                    func.unicode_casefold(Activity.description).like(
                        pattern, escape="\\"
                    ),
                )
            )

        location = query.location_details
        if location is not None:
            location_clauses = []
            if location.country_id is not None:
                location_clauses.append(
                    LocationDetails.country_id == location.country_id
                )
            if location.city_id is not None:
                location_clauses.append(LocationDetails.city_id == location.city_id)
            if location.street is not None:
                location_clauses.append(
                    func.unicode_casefold(LocationDetails.street).like(
                        _substring_pattern(location.street.casefold()), escape="\\"
                    )
                )
            if location_clauses:
                statement = statement.where(
                    Activity.location_details.has(and_(*location_clauses))
                )

        categories = query.categories
        if categories is not None:
            category_clauses = [
                Activity.category_links.any(ActivityCategory.category_code == code)
                for code in categories.codes
            ]
            statement = statement.where(
                or_(*category_clauses)
                if categories.match is CategoryMatch.ANY
                else and_(*category_clauses)
            )

        price = query.price
        if price is not None:
            if price.min is not None:
                statement = statement.where(_price_at_least(Activity.price, price.min))
            if price.max is not None:
                statement = statement.where(_price_at_most(Activity.price, price.max))

        duration = query.duration_minutes
        if duration is not None:
            if duration.min is not None:
                statement = statement.where(Activity.duration_minutes >= duration.min)
            if duration.max is not None:
                statement = statement.where(Activity.duration_minutes <= duration.max)

        if query.party_size is not None:
            statement = statement.where(
                Activity.minimum_participants <= query.party_size,
                or_(
                    Activity.maximum_participants.is_(None),
                    Activity.maximum_participants >= query.party_size,
                ),
            )
        if query.youngest_age is not None:
            statement = statement.where(
                or_(
                    Activity.minimum_age.is_(None),
                    Activity.minimum_age <= query.youngest_age,
                )
            )
        if query.oldest_age is not None:
            statement = statement.where(
                or_(
                    Activity.maximum_age.is_(None),
                    Activity.maximum_age >= query.oldest_age,
                )
            )
        if query.booking_required is not None:
            statement = statement.where(
                Activity.booking_required == query.booking_required
            )

        accessibility = query.accessibility
        if accessibility is not None:
            for field in (
                "wheelchair_accessible",
                "step_free_access",
                "accessible_toilet",
            ):
                value = getattr(accessibility, field)
                if value is not None:
                    statement = statement.where(getattr(Activity, field) == value)

        if query.is_active is not None:
            statement = statement.where(Activity.is_active == query.is_active)
        if query.availability is not None:
            statement = statement.where(self._availability_clause(query))
        return statement

    def _availability_clause(self, query: ActivityQueryRequest) -> Any:
        availability = query.availability
        if availability is None:
            raise AssertionError("availability clause needs an availability filter")
        weekday = WEEKDAYS[availability.date.weekday()]
        schedule = ActivityAvailabilitySchedule
        clauses = [
            or_(
                and_(
                    schedule.recurring_weekly.is_(True),
                    schedule.day_of_week == weekday,
                ),
                and_(
                    schedule.recurring_weekly.is_(False),
                    schedule.date == availability.date,
                ),
            )
        ]
        if availability.start_time is not None and availability.end_time is not None:
            schedule_start = cast(
                func.strftime("%H", schedule.start_time), String
            ).cast(Numeric) * 60 + cast(
                func.strftime("%M", schedule.start_time), Numeric
            )
            schedule_end = cast(
                func.strftime("%H", schedule.end_time), Numeric
            ) * 60 + cast(func.strftime("%M", schedule.end_time), Numeric)
            requested_start = (
                availability.start_time.hour * 60 + availability.start_time.minute
            )
            requested_end = (
                availability.end_time.hour * 60 + availability.end_time.minute
            )
            clauses.extend(
                (
                    requested_start + Activity.duration_minutes <= requested_end,
                    schedule_start + Activity.duration_minutes <= requested_end,
                    requested_start + Activity.duration_minutes <= schedule_end,
                )
            )
        return Activity.availability_schedules.any(and_(*clauses))

    def _apply_order(
        self, statement: Select[tuple[Activity]], query: ActivityQueryRequest
    ) -> Select[tuple[Activity]]:
        name = func.unicode_casefold(Activity.name)
        if query.sort is ActivitySort.NAME_ASC:
            return statement.order_by(name, Activity.id)
        if query.sort is ActivitySort.PRICE_ASC:
            return statement.order_by(
                func.instr(Activity.price, "."), Activity.price, name, Activity.id
            )
        if query.sort is ActivitySort.PRICE_DESC:
            return statement.order_by(
                func.instr(Activity.price, ".").desc(),
                Activity.price.desc(),
                name,
                Activity.id,
            )
        duration = Activity.duration_minutes
        primary = (
            duration if query.sort is ActivitySort.DURATION_ASC else duration.desc()
        )
        return statement.order_by(primary, name, Activity.id)
