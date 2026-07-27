"""Shared domain enums used across models, schemas, services, and the agent."""

from __future__ import annotations

from enum import Enum


class Region(str, Enum):
    """Supported trip regions. Extensible for future locations."""

    AUSTRALIA = "australia"
    NEPAL = "nepal"


class TripDuration(str, Enum):
    ONE_HOUR = "1_hour"
    HALF_DAY = "half_day"
    FULL_DAY = "full_day"
    WEEKEND = "weekend"
    MULTI_DAY = "multi_day"

    @property
    def minutes(self) -> int:
        """Approximate active planning budget in minutes."""
        return {
            TripDuration.ONE_HOUR: 60,
            TripDuration.HALF_DAY: 4 * 60,
            TripDuration.FULL_DAY: 8 * 60,
            TripDuration.WEEKEND: 2 * 8 * 60,
            TripDuration.MULTI_DAY: 3 * 8 * 60,
        }[self]


class TravellerType(str, Enum):
    SOLO = "solo"
    COUPLE = "couple"
    FAMILY = "family"
    FRIENDS = "friends"


class Mood(str, Enum):
    NATURE = "nature"
    SCENIC = "scenic"
    FOOD = "food"
    HISTORICAL = "historical"
    BEACHES = "beaches"
    ADVENTURE = "adventure"
    RELAXING = "relaxing"
    COFFEE = "coffee"
    KIDS = "kids"


class StopType(str, Enum):
    ATTRACTION = "attraction"
    SCENIC_LOOKOUT = "scenic_lookout"
    RESTAURANT = "restaurant"
    CAFE = "cafe"
    REST_STOP = "rest_stop"


class JourneyStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
