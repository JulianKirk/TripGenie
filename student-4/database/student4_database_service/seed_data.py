"""Idempotent category and sample-activity seeding."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from student4_database_service.enums import CategoryCode
from student4_database_service.models import Activity, Category
from student4_database_service.schemas import ActivityWrite

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CATEGORY_SEEDS = (
    (
        CategoryCode.ADVENTURE,
        "Adventure",
        "High-energy and adventurous experiences",
        10,
    ),
    (
        CategoryCode.CULTURE,
        "Culture",
        "Museums, galleries and cultural sites",
        20,
    ),
    (
        CategoryCode.FAMILY,
        "Family",
        "Experiences suitable for families and children",
        30,
    ),
    (
        CategoryCode.FOOD_DRINK,
        "Food and drink",
        "Dining, tastings and culinary experiences",
        40,
    ),
    (
        CategoryCode.NIGHTLIFE,
        "Nightlife",
        "Evening entertainment and social experiences",
        50,
    ),
    (
        CategoryCode.OUTDOOR,
        "Outdoor",
        "Activities primarily undertaken outdoors",
        60,
    ),
    (
        CategoryCode.SHOPPING,
        "Shopping",
        "Markets, local makers and shopping experiences",
        70,
    ),
    (CategoryCode.TOUR, "Tour", "Guided or self-guided tours", 80),
    (
        CategoryCode.WELLNESS,
        "Wellness",
        "Relaxation, fitness and wellbeing experiences",
        90,
    ),
    (
        CategoryCode.WILDLIFE,
        "Wildlife",
        "Animal encounters and nature observation",
        100,
    ),
)

SHARED_LOCATION_NAMESPACE = UUID("9a7c1f2e-3b4d-5e6f-8a9b-0c1d2e3f4a5b")
AUSTRALIA_ID = uuid5(SHARED_LOCATION_NAMESPACE, "country:australia")
ACTIVITY_SEED_NAMESPACE = UUID("cb327a7c-8a95-5fea-a895-4a04ca6d95da")


def _activity_seed_id(seed_key: str) -> UUID:
    return uuid5(
        ACTIVITY_SEED_NAMESPACE,
        f"activity:{seed_key}",
    )


SAMPLE_ACTIVITY_SEED_KEYS = (
    "sydney harbour guided walk",
    "melbourne museum discovery",
    "great barrier reef snorkelling",
    "barossa valley tasting tour",
    "blue mountains family hike",
    "salamanca market food walk",
    "darwin sunset wildlife cruise",
    "brisbane riverside sunrise yoga",
    "perth evening food crawl",
    "canberra national gallery visit",
)
SAMPLE_ACTIVITY_IDS = tuple(
    _activity_seed_id(seed_key) for seed_key in SAMPLE_ACTIVITY_SEED_KEYS
)
SYDNEY_HARBOUR_GUIDED_WALK_ID = SAMPLE_ACTIVITY_IDS[0]


def _location(city: str, street: str, street_number: int) -> dict[str, object]:
    normalised_city = city.strip().lower()
    return {
        "country_id": AUSTRALIA_ID,
        "city_id": uuid5(
            SHARED_LOCATION_NAMESPACE, f"city:australia/{normalised_city}"
        ),
        "street": street,
        "street_number": street_number,
    }


def _weekly(day: str, start: str, end: str) -> list[dict[str, object]]:
    return [
        {
            "recurring_weekly": True,
            "day_of_week": day,
            "start_time": start,
            "end_time": end,
        }
    ]


SAMPLE_ACTIVITY_DATA: tuple[dict[str, object], ...] = (
    {
        "name": "Sydney Harbour guided walk",
        "description": "A guided foreshore walk with harbour and Opera House views.",
        "price": "45.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
        "minimum_age": 8,
        "minimum_participants": 1,
        "maximum_participants": 12,
        "booking_required": True,
        "location_details": _location("Sydney", "Circular Quay", 1),
        "categories": ["OUTDOOR", "TOUR"],
        "availability_schedules": _weekly("SATURDAY", "09:00", "12:00"),
    },
    {
        "name": "Melbourne museum discovery",
        "description": "A hosted introduction to Victoria's history and collections.",
        "price": "30.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 90,
        "minimum_participants": 1,
        "maximum_participants": 20,
        "booking_required": False,
        "wheelchair_accessible": True,
        "step_free_access": True,
        "accessible_toilet": True,
        "location_details": _location("Melbourne", "Nicholson Street", 11),
        "categories": ["CULTURE", "FAMILY"],
        "availability_schedules": _weekly("SUNDAY", "10:00", "16:00"),
    },
    {
        "name": "Great Barrier Reef snorkelling",
        "description": "A supervised reef snorkelling trip departing from Cairns.",
        "price": "185.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 300,
        "minimum_age": 12,
        "minimum_participants": 2,
        "maximum_participants": 16,
        "booking_required": True,
        "location_details": _location("Cairns", "Spence Street", 1),
        "categories": ["ADVENTURE", "OUTDOOR", "WILDLIFE"],
        "availability_schedules": _weekly("WEDNESDAY", "07:30", "15:30"),
    },
    {
        "name": "Barossa Valley tasting tour",
        "description": "A small-group tour of local food producers and cellar doors.",
        "price": "140.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 360,
        "minimum_age": 18,
        "minimum_participants": 2,
        "maximum_participants": 10,
        "booking_required": True,
        "location_details": _location("Adelaide", "Gouger Street", 55),
        "categories": ["FOOD_DRINK", "TOUR"],
        "availability_schedules": _weekly("FRIDAY", "09:00", "17:00"),
    },
    {
        "name": "Blue Mountains family hike",
        "description": "A gentle guided bushwalk to lookouts and sandstone scenery.",
        "price": "75.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 180,
        "minimum_age": 6,
        "minimum_participants": 2,
        "maximum_participants": 14,
        "booking_required": True,
        "location_details": _location("Katoomba", "Katoomba Street", 81),
        "categories": ["FAMILY", "OUTDOOR", "TOUR"],
        "availability_schedules": _weekly("SATURDAY", "08:30", "13:00"),
    },
    {
        "name": "Salamanca Market food walk",
        "description": (
            "A guided walk through Hobart's market stalls and local produce."
        ),
        "price": "55.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 120,
        "minimum_participants": 1,
        "maximum_participants": 12,
        "booking_required": False,
        "location_details": _location("Hobart", "Salamanca Place", 20),
        "categories": ["FOOD_DRINK", "SHOPPING", "TOUR"],
        "availability_schedules": _weekly("SATURDAY", "09:00", "14:00"),
    },
    {
        "name": "Darwin sunset wildlife cruise",
        "description": (
            "An evening harbour cruise focused on coastal wildlife and sunset."
        ),
        "price": "95.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 150,
        "minimum_age": 5,
        "minimum_participants": 2,
        "maximum_participants": 24,
        "booking_required": True,
        "location_details": _location("Darwin", "Kitchener Drive", 7),
        "categories": ["OUTDOOR", "TOUR", "WILDLIFE"],
        "availability_schedules": _weekly("THURSDAY", "16:30", "20:00"),
    },
    {
        "name": "Brisbane riverside sunrise yoga",
        "description": "A relaxed riverside yoga session suitable for beginners.",
        "price": "25.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 60,
        "minimum_age": 14,
        "minimum_participants": 1,
        "maximum_participants": 25,
        "booking_required": False,
        "location_details": _location("Brisbane", "South Bank", 10),
        "categories": ["OUTDOOR", "WELLNESS"],
        "availability_schedules": _weekly("TUESDAY", "06:00", "08:00"),
    },
    {
        "name": "Perth evening food crawl",
        "description": (
            "A walking crawl through independent eateries and late-night venues."
        ),
        "price": "110.00",
        "pricing_basis": "PER_PERSON",
        "duration_minutes": 180,
        "minimum_age": 18,
        "minimum_participants": 2,
        "maximum_participants": 10,
        "booking_required": True,
        "location_details": _location("Perth", "William Street", 140),
        "categories": ["FOOD_DRINK", "NIGHTLIFE", "TOUR"],
        "availability_schedules": _weekly("FRIDAY", "18:00", "22:00"),
    },
    {
        "name": "Canberra national gallery visit",
        "description": "A guided highlights visit through Australian art collections.",
        "price": "20.00",
        "pricing_basis": "FLAT_ADMISSION",
        "duration_minutes": 90,
        "minimum_participants": 1,
        "maximum_participants": 15,
        "booking_required": False,
        "wheelchair_accessible": True,
        "step_free_access": True,
        "accessible_toilet": True,
        "location_details": _location("Canberra", "Parkes Place East", 1),
        "categories": ["CULTURE"],
        "availability_schedules": _weekly("MONDAY", "10:00", "15:00"),
    },
)


def seed_categories(session: Session) -> int:
    inserted = 0
    for code, label, description, display_order in CATEGORY_SEEDS:
        if session.get(Category, code) is None:
            session.add(
                Category(
                    code=code,
                    label=label,
                    description=description,
                    display_order=display_order,
                )
            )
            inserted += 1
    if inserted:
        session.commit()
    return inserted


def seed_activities(session: Session) -> int:
    inserted = 0
    for activity_id, payload in zip(
        SAMPLE_ACTIVITY_IDS,
        SAMPLE_ACTIVITY_DATA,
        strict=True,
    ):
        if session.get(Activity, activity_id) is not None:
            continue
        message = ActivityWrite.model_validate(payload)
        activity = Activity.from_message(message)
        activity.id = activity_id
        session.add(activity)
        inserted += 1
    if inserted:
        session.commit()
    return inserted


def seed_database(session: Session) -> int:
    return seed_categories(session) + seed_activities(session)
