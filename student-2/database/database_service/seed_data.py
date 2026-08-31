"""Starter accommodations, inserted on first start.

The service ships with an empty SQLite file, so without these the frontend's
list, filters and pager have nothing to show. Rows go in through the same
`AccommodationCreateRequest` -> `Accommodation.from_message` path a POST takes,
so a seed row cannot be shaped differently to a created one.

ponytail: a literal tuple, not a fixtures file or a CLI. It is demo data for
Release 0; delete the module once there is a real import path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from database_service.models import Accommodation
from database_service.schemas import AccommodationCreateRequest

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SEED_ACCOMMODATIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "Harbour View Hotel",
        "type": "hotel",
        "description": "Rooms over Circular Quay with the bridge in the window.",
        "price_per_night": 320.00,
        "availability_status": "available",
        "rating": 4.6,
        "amenities": ["wifi", "pool", "gym", "breakfast"],
        "location_details": {
            "country": "australia",
            "city": "sydney",
            "street": "george street",
            "street_number": 12,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 1,
            "bed_types": ["king"],
            "description": "King room with harbour aspect.",
        },
    },
    {
        "name": "Bondi Surf Hostel",
        "type": "hostel",
        "description": "Bunk rooms two streets back from the beach.",
        "price_per_night": 45.00,
        "availability_status": "available",
        "rating": 3.9,
        "amenities": ["wifi", "laundry", "kitchen"],
        "location_details": {
            "country": "australia",
            "city": "sydney",
            "street": "campbell parade",
            "street_number": 180,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 6,
            "bed_types": ["bunk"],
            "description": "Six-bed mixed dorm.",
        },
    },
    {
        "name": "Darlinghurst Studio Apartment",
        "type": "apartment",
        "description": "Self-contained studio with a small kitchen and a desk.",
        "price_per_night": 165.00,
        "availability_status": "available",
        "rating": 4.2,
        "amenities": ["wifi", "kitchen", "air_conditioning"],
        "location_details": {
            "country": "australia",
            "city": "sydney",
            "street": "victoria street",
            "street_number": 44,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 1,
            "bed_types": ["queen"],
            "description": "Studio with a sofa bed for a third guest.",
        },
    },
    {
        "name": "Southbank Riverside Hotel",
        "type": "hotel",
        "description": "Business hotel on the south bank of the Yarra.",
        "price_per_night": 240.00,
        "availability_status": "available",
        "rating": 4.4,
        "amenities": ["wifi", "gym", "parking", "breakfast"],
        "location_details": {
            "country": "australia",
            "city": "melbourne",
            "street": "southbank boulevard",
            "street_number": 8,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 2,
            "bed_types": ["queen", "single"],
            "description": "Twin-share room facing the river.",
        },
    },
    {
        "name": "Fitzroy Terrace Guesthouse",
        "type": "guesthouse",
        "description": "Restored terrace with four rooms and a shared courtyard.",
        "price_per_night": 130.00,
        "availability_status": "available",
        "rating": 4.7,
        "amenities": ["wifi", "breakfast", "kitchen"],
        "location_details": {
            "country": "australia",
            "city": "melbourne",
            "street": "brunswick street",
            "street_number": 221,
        },
        "room_details": {
            "room_count": 4,
            "bed_count": 5,
            "bed_types": ["double", "single"],
            "description": "Whole-house booking, four bedrooms.",
        },
    },
    {
        "name": "Great Ocean Road Campground",
        "type": "camping",
        "description": "Powered and unpowered sites a short walk from the cliffs.",
        "price_per_night": 35.00,
        "availability_status": "available",
        "rating": 4.1,
        "amenities": ["parking", "laundry"],
        "location_details": {
            "country": "australia",
            "city": "apollo bay",
            "street": "great ocean road",
            "street_number": 4200,
        },
    },
    {
        "name": "Whitsunday Island Resort",
        "type": "resort",
        "description": "Beachfront villas with reef tours from the private jetty.",
        "price_per_night": 690.00,
        "availability_status": "sold_out",
        "rating": 4.8,
        "amenities": ["wifi", "pool", "spa", "breakfast", "parking"],
        "location_details": {
            "country": "australia",
            "city": "airlie beach",
            "street": "shingley drive",
            "street_number": 3,
        },
        "room_details": {
            "room_count": 2,
            "bed_count": 3,
            "bed_types": ["king", "single"],
            "description": "Two-bedroom villa with a plunge pool.",
        },
    },
    {
        "name": "Brisbane Riverwalk Apartment",
        "type": "apartment",
        "description": "Two-bedroom apartment on the New Farm riverwalk.",
        "price_per_night": 210.00,
        "availability_status": "available",
        "rating": 4.3,
        "amenities": ["wifi", "pool", "kitchen", "parking"],
        "location_details": {
            "country": "australia",
            "city": "brisbane",
            "street": "brunswick street",
            "street_number": 96,
        },
        "room_details": {
            "room_count": 2,
            "bed_count": 3,
            "bed_types": ["queen", "single"],
            "description": "Second bedroom has two singles.",
        },
    },
    {
        "name": "Adelaide Hills Guesthouse",
        "type": "guesthouse",
        "description": "Vineyard guesthouse with breakfast on the verandah.",
        "price_per_night": 175.00,
        "availability_status": "unavailable",
        "rating": 4.5,
        "amenities": ["wifi", "breakfast", "parking"],
        "location_details": {
            "country": "australia",
            "city": "adelaide",
            "street": "greenhill road",
            "street_number": 512,
        },
        "room_details": {
            "room_count": 3,
            "bed_count": 4,
            "bed_types": ["queen", "double"],
            "description": "Three rooms, each with an ensuite.",
        },
    },
    {
        "name": "Queenstown Alpine Lodge",
        "type": "hotel",
        "description": "Ski-season lodge ten minutes from the gondola.",
        "price_per_night": 285.00,
        "availability_status": "available",
        "rating": 4.4,
        "amenities": ["wifi", "spa", "parking", "breakfast"],
        "location_details": {
            "country": "new zealand",
            "city": "queenstown",
            "street": "brecon street",
            "street_number": 21,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 2,
            "bed_types": ["king", "sofa_bed"],
            "description": "Lake-facing room with a fold-out sofa.",
        },
    },
    {
        "name": "Wellington Harbour Hostel",
        "type": "hostel",
        "description": "Central hostel above a cafe on the waterfront.",
        "price_per_night": 52.00,
        "availability_status": "available",
        "rating": 3.8,
        "amenities": ["wifi", "kitchen", "laundry"],
        "location_details": {
            "country": "new zealand",
            "city": "wellington",
            "street": "cable street",
            "street_number": 63,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 4,
            "bed_types": ["bunk"],
            "description": "Four-bed dorm, female only.",
        },
    },
    {
        "name": "Rotorua Thermal Resort",
        "type": "resort",
        "description": "Geothermal pools and forest walks on the doorstep.",
        "price_per_night": 395.00,
        "availability_status": "available",
        "rating": 4.6,
        "amenities": ["wifi", "pool", "spa", "gym", "breakfast"],
        "location_details": {
            "country": "new zealand",
            "city": "rotorua",
            "street": "fenton street",
            "street_number": 1030,
        },
        "room_details": {
            "room_count": 2,
            "bed_count": 2,
            "bed_types": ["king", "queen"],
            "description": "Two-bedroom suite with a private thermal pool.",
        },
    },
    {
        "name": "Shinjuku Capsule Hostel",
        "type": "hostel",
        "description": "Capsule beds a two-minute walk from Shinjuku station.",
        "price_per_night": 38.00,
        "availability_status": "available",
        "rating": 4.0,
        "amenities": ["wifi", "laundry", "air_conditioning"],
        "location_details": {
            "country": "japan",
            "city": "tokyo",
            "street": "kabukicho",
            "street_number": 17,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 1,
            "bed_types": ["single"],
            "description": "Single capsule with a locker.",
        },
    },
    {
        "name": "Asakusa Riverside Apartment",
        "type": "apartment",
        "description": "Tatami apartment with a view of the Sumida river.",
        "price_per_night": 155.00,
        "availability_status": "available",
        "rating": 4.5,
        "amenities": ["wifi", "kitchen", "air_conditioning", "laundry"],
        "location_details": {
            "country": "japan",
            "city": "tokyo",
            "street": "kaminarimon",
            "street_number": 2,
        },
        "room_details": {
            "room_count": 2,
            "bed_count": 3,
            "bed_types": ["double", "single"],
            "description": "Futons stored in the closet, laid out nightly.",
        },
    },
    {
        "name": "Kyoto Machiya Guesthouse",
        "type": "guesthouse",
        "description": "Traditional townhouse near Nishiki market.",
        "price_per_night": 198.00,
        "availability_status": "sold_out",
        "rating": 4.9,
        "amenities": ["wifi", "breakfast", "kitchen"],
        "location_details": {
            "country": "japan",
            "city": "kyoto",
            "street": "takakura dori",
            "street_number": 384,
        },
        "room_details": {
            "room_count": 3,
            "bed_count": 4,
            "bed_types": ["double", "single"],
            "description": "Whole machiya, sleeps four.",
        },
    },
    {
        "name": "Mount Fuji Lakeside Campsite",
        "type": "camping",
        "description": "Lake Kawaguchi sites with Fuji straight across the water.",
        "price_per_night": 28.00,
        "availability_status": "available",
        "rating": 4.2,
        "amenities": ["parking"],
        "location_details": {
            "country": "japan",
            "city": "fujikawaguchiko",
            "street": "kawaguchiko",
            "street_number": 1122,
        },
    },
    {
        "name": "Marina Bay Skyline Hotel",
        "type": "hotel",
        "description": "Rooftop pool over the bay, fifteen floors up.",
        "price_per_night": 430.00,
        "availability_status": "available",
        "rating": 4.7,
        "amenities": ["wifi", "pool", "gym", "spa", "breakfast", "parking"],
        "location_details": {
            "country": "singapore",
            "city": "singapore",
            "street": "raffles avenue",
            "street_number": 10,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 1,
            "bed_types": ["king"],
            "description": "Deluxe king with a bay view.",
        },
    },
    {
        "name": "Little India Budget Apartment",
        "type": "apartment",
        "description": "Compact apartment above the Serangoon Road markets.",
        "price_per_night": 88.00,
        "availability_status": "unavailable",
        "rating": 3.6,
        "amenities": ["wifi", "kitchen", "air_conditioning"],
        "location_details": {
            "country": "singapore",
            "city": "singapore",
            "street": "serangoon road",
            "street_number": 217,
        },
        "room_details": {
            "room_count": 1,
            "bed_count": 2,
            "bed_types": ["double", "sofa_bed"],
            "description": "One bedroom plus a sofa bed in the lounge.",
        },
    },
)


def seed(session: Session) -> int:
    """Insert the starter rows if the table is empty. Returns how many went in.

    Empty-only, so a restart against the mounted volume does not duplicate
    them and does not fight whatever a caller has since created or deleted.
    """
    if session.scalar(select(func.count()).select_from(Accommodation)):
        return 0
    for payload in SEED_ACCOMMODATIONS:
        message = AccommodationCreateRequest.model_validate(payload)
        session.add(Accommodation.from_message(session, message))
    session.commit()
    return len(SEED_ACCOMMODATIONS)
