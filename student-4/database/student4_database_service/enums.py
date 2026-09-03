"""Stable values used by the Student 4 database contract."""

from enum import StrEnum


class PricingBasis(StrEnum):
    PER_PERSON = "PER_PERSON"
    FLAT_ADMISSION = "FLAT_ADMISSION"


class DayOfWeek(StrEnum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class CategoryCode(StrEnum):
    ADVENTURE = "ADVENTURE"
    CULTURE = "CULTURE"
    FAMILY = "FAMILY"
    FOOD_DRINK = "FOOD_DRINK"
    NIGHTLIFE = "NIGHTLIFE"
    OUTDOOR = "OUTDOOR"
    SHOPPING = "SHOPPING"
    TOUR = "TOUR"
    WELLNESS = "WELLNESS"
    WILDLIFE = "WILDLIFE"


class CategoryMatch(StrEnum):
    ANY = "ANY"
    ALL = "ALL"


class ActivitySort(StrEnum):
    NAME_ASC = "NAME_ASC"
    PRICE_ASC = "PRICE_ASC"
    PRICE_DESC = "PRICE_DESC"
    DURATION_ASC = "DURATION_ASC"
    DURATION_DESC = "DURATION_DESC"
