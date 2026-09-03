"""SQLAlchemy tables for the activity aggregate."""

from __future__ import annotations

import datetime as dt
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from student4_database_service.enums import CategoryCode, DayOfWeek, PricingBasis
from student4_database_service.schemas import (
    ActivityRecord,
    ActivitySummary,
    ActivityWrite,
    LocationRecord,
    LocationSummary,
    ScheduleRecord,
    ScheduleWrite,
)


class Base(DeclarativeBase):
    pass


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_activity_duration_positive"),
        CheckConstraint(
            "minimum_age IS NULL OR minimum_age >= 0", name="ck_activity_min_age"
        ),
        CheckConstraint(
            "maximum_age IS NULL OR maximum_age >= 0", name="ck_activity_max_age"
        ),
        CheckConstraint(
            "minimum_age IS NULL OR maximum_age IS NULL OR maximum_age >= minimum_age",
            name="ck_activity_age_order",
        ),
        CheckConstraint("minimum_participants >= 1", name="ck_activity_min_party"),
        CheckConstraint(
            "maximum_participants IS NULL OR "
            "maximum_participants >= minimum_participants",
            name="ck_activity_party_order",
        ),
        CheckConstraint(
            "price NOT GLOB '*[^0-9.]*' "
            "AND length(price) - length(replace(price, '.', '')) = 1 "
            "AND instr(price, '.') > 1 "
            "AND length(price) - instr(price, '.') = 2 "
            "AND (substr(price, 1, 1) != '0' OR instr(price, '.') = 2)",
            name="ck_activity_price",
        ),
        CheckConstraint(
            "booking_required IN (0, 1)", name="ck_activity_booking_required"
        ),
        CheckConstraint(
            "wheelchair_accessible IS NULL OR wheelchair_accessible IN (0, 1)",
            name="ck_activity_wheelchair_accessible",
        ),
        CheckConstraint(
            "step_free_access IS NULL OR step_free_access IN (0, 1)",
            name="ck_activity_step_free_access",
        ),
        CheckConstraint(
            "accessible_toilet IS NULL OR accessible_toilet IN (0, 1)",
            name="ck_activity_accessible_toilet",
        ),
        CheckConstraint("is_active IN (0, 1)", name="ck_activity_is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str]
    description: Mapped[str]
    price: Mapped[str] = mapped_column(String)
    pricing_basis: Mapped[PricingBasis] = mapped_column(
        SAEnum(
            PricingBasis,
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            name="pricing_basis",
        )
    )
    duration_minutes: Mapped[int]
    minimum_age: Mapped[int | None] = mapped_column(default=None)
    maximum_age: Mapped[int | None] = mapped_column(default=None)
    minimum_participants: Mapped[int]
    maximum_participants: Mapped[int | None] = mapped_column(default=None)
    booking_required: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_notes: Mapped[str | None] = mapped_column(default=None)
    wheelchair_accessible: Mapped[bool | None] = mapped_column(Boolean, default=None)
    step_free_access: Mapped[bool | None] = mapped_column(Boolean, default=None)
    accessible_toilet: Mapped[bool | None] = mapped_column(Boolean, default=None)
    accessibility_notes: Mapped[str | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    location_details: Mapped[LocationDetails] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    category_links: Mapped[list[ActivityCategory]] = relationship(
        back_populates="activity", cascade="all, delete-orphan", lazy="selectin"
    )
    availability_schedules: Mapped[list[ActivityAvailabilitySchedule]] = relationship(
        back_populates="activity", cascade="all, delete-orphan", lazy="selectin"
    )

    @classmethod
    def from_message(cls, message: ActivityWrite) -> Activity:
        activity = cls()
        activity.apply(message)
        activity.location_details = LocationDetails.from_message(message)
        activity.category_links = [
            ActivityCategory(category_code=code) for code in message.categories
        ]
        activity.availability_schedules = [
            ActivityAvailabilitySchedule.from_message(schedule)
            for schedule in message.availability_schedules
        ]
        return activity

    def apply(self, message: ActivityWrite) -> None:
        for field in (
            "name",
            "description",
            "pricing_basis",
            "duration_minutes",
            "minimum_age",
            "maximum_age",
            "minimum_participants",
            "maximum_participants",
            "booking_required",
            "booking_notes",
            "wheelchair_accessible",
            "step_free_access",
            "accessible_toilet",
            "accessibility_notes",
            "is_active",
        ):
            setattr(self, field, getattr(message, field))
        self.price = f"{message.price:.2f}"

    def to_record(self) -> ActivityRecord:
        categories = sorted(
            (link.category_code for link in self.category_links),
            key=lambda code: code.value,
        )
        schedules = sorted(
            (schedule.to_record() for schedule in self.availability_schedules),
            key=lambda item: (
                item.recurring_weekly,
                item.day_of_week.value if item.day_of_week else "",
                item.date.isoformat() if item.date else "",
                item.start_time,
            ),
        )
        return ActivityRecord(
            id=self.id,
            name=self.name,
            description=self.description,
            price=self.price,
            pricing_basis=self.pricing_basis,
            duration_minutes=self.duration_minutes,
            minimum_age=self.minimum_age,
            maximum_age=self.maximum_age,
            minimum_participants=self.minimum_participants,
            maximum_participants=self.maximum_participants,
            booking_required=self.booking_required,
            booking_notes=self.booking_notes,
            wheelchair_accessible=self.wheelchair_accessible,
            step_free_access=self.step_free_access,
            accessible_toilet=self.accessible_toilet,
            accessibility_notes=self.accessibility_notes,
            is_active=self.is_active,
            location_details=self.location_details.to_record(),
            categories=categories,
            availability_schedules=schedules,
        )

    def to_summary(self) -> ActivitySummary:
        record = self.to_record()
        return ActivitySummary(
            id=record.id,
            name=record.name,
            description=record.description,
            price=f"{record.price:.2f}",
            pricing_basis=record.pricing_basis,
            duration_minutes=record.duration_minutes,
            minimum_age=record.minimum_age,
            maximum_age=record.maximum_age,
            minimum_participants=record.minimum_participants,
            maximum_participants=record.maximum_participants,
            booking_required=record.booking_required,
            wheelchair_accessible=record.wheelchair_accessible,
            step_free_access=record.step_free_access,
            accessible_toilet=record.accessible_toilet,
            is_active=record.is_active,
            location_details=LocationSummary(
                country_id=record.location_details.country_id,
                city_id=record.location_details.city_id,
            ),
            categories=record.categories,
        )


class LocationDetails(Base):
    __tablename__ = "location_details"
    __table_args__ = (
        UniqueConstraint("activity_id", name="uq_location_activity"),
        Index("ix_location_country_city", "country_id", "city_id"),
        CheckConstraint(
            "street_number IS NULL OR street_number >= 0",
            name="ck_location_street_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    country_id: Mapped[UUID] = mapped_column(Uuid)
    city_id: Mapped[UUID] = mapped_column(Uuid)
    street: Mapped[str | None] = mapped_column(default=None)
    street_number: Mapped[int | None] = mapped_column(default=None)

    activity: Mapped[Activity] = relationship(back_populates="location_details")

    @classmethod
    def from_message(cls, message: ActivityWrite) -> LocationDetails:
        location = cls()
        location.apply(message)
        return location

    def apply(self, message: ActivityWrite) -> None:
        location = message.location_details
        self.country_id = location.country_id
        self.city_id = location.city_id
        self.street = location.street
        self.street_number = location.street_number

    def to_record(self) -> LocationRecord:
        return LocationRecord(
            id=self.id,
            country_id=self.country_id,
            city_id=self.city_id,
            street=self.street,
            street_number=self.street_number,
        )


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("display_order >= 0", name="ck_category_display_order"),
    )

    code: Mapped[CategoryCode] = mapped_column(
        SAEnum(
            CategoryCode,
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            name="category_code",
        ),
        primary_key=True,
    )
    label: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    display_order: Mapped[int]


class ActivityCategory(Base):
    __tablename__ = "activity_categories"
    __table_args__ = (
        Index("ix_activity_category_code_activity", "category_code", "activity_id"),
    )

    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    category_code: Mapped[CategoryCode] = mapped_column(
        SAEnum(CategoryCode, native_enum=False, validate_strings=True),
        ForeignKey("categories.code"),
        primary_key=True,
    )

    activity: Mapped[Activity] = relationship(back_populates="category_links")


class ActivityAvailabilitySchedule(Base):
    __tablename__ = "activity_availability_schedules"
    __table_args__ = (
        Index("ix_schedule_activity", "activity_id"),
        Index(
            "uq_schedule_weekly_identity",
            "activity_id",
            "day_of_week",
            "start_time",
            "end_time",
            unique=True,
            sqlite_where=text("recurring_weekly = 1"),
        ),
        Index(
            "uq_schedule_one_off_identity",
            "activity_id",
            "date",
            "start_time",
            "end_time",
            unique=True,
            sqlite_where=text("recurring_weekly = 0"),
        ),
        CheckConstraint("start_time < end_time", name="ck_schedule_time_order"),
        CheckConstraint(
            "date IS NULL OR "
            "(date(date, '+0 days') IS NOT NULL AND date(date, '+0 days') = date)",
            name="ck_schedule_valid_date",
        ),
        CheckConstraint(
            "typeof(start_time) = 'text' AND length(start_time) = 15 "
            "AND start_time GLOB "
            "'[0-2][0-9]:[0-5][0-9]:[0-5][0-9]."
            "[0-9][0-9][0-9][0-9][0-9][0-9]' "
            "AND substr(start_time, 1, 2) BETWEEN '00' AND '23'",
            name="ck_schedule_valid_start_time",
        ),
        CheckConstraint(
            "typeof(end_time) = 'text' AND length(end_time) = 15 "
            "AND end_time GLOB "
            "'[0-2][0-9]:[0-5][0-9]:[0-5][0-9]."
            "[0-9][0-9][0-9][0-9][0-9][0-9]' "
            "AND substr(end_time, 1, 2) BETWEEN '00' AND '23'",
            name="ck_schedule_valid_end_time",
        ),
        CheckConstraint(
            "(recurring_weekly = 1 AND day_of_week IS NOT NULL AND date IS NULL) OR "
            "(recurring_weekly = 0 AND day_of_week IS NULL AND date IS NOT NULL)",
            name="ck_schedule_recurrence",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE")
    )
    recurring_weekly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    day_of_week: Mapped[DayOfWeek | None] = mapped_column(
        SAEnum(
            DayOfWeek,
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            name="day_of_week",
        ),
        default=None,
    )
    date: Mapped[dt.date | None] = mapped_column(Date, default=None)
    start_time: Mapped[dt.time] = mapped_column(Time)
    end_time: Mapped[dt.time] = mapped_column(Time)

    activity: Mapped[Activity] = relationship(back_populates="availability_schedules")

    @classmethod
    def from_message(cls, message: ScheduleWrite) -> ActivityAvailabilitySchedule:
        return cls(
            recurring_weekly=message.recurring_weekly,
            day_of_week=message.day_of_week,
            date=message.date,
            start_time=message.start_time,
            end_time=message.end_time,
        )

    def to_record(self) -> ScheduleRecord:
        return ScheduleRecord(
            id=self.id,
            recurring_weekly=self.recurring_weekly,
            day_of_week=self.day_of_week,
            date=self.date,
            start_time=self.start_time.strftime("%H:%M"),
            end_time=self.end_time.strftime("%H:%M"),
        )
