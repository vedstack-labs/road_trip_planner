"""Geospatial helpers: distance, drive-time estimation, and route optimisation.

Real computation (haversine + nearest-neighbour with 2-opt improvement), not a
stub. A production deployment would swap ``estimate_leg`` for a Directions API
call; the interface stays the same.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from pydantic import BaseModel

# Average effective road speed (km/h). Scenic roads are slower, so we bias the
# estimate down a little when scenic preference is requested.
DEFAULT_SPEED_KMH = 75.0
SCENIC_SPEED_KMH = 60.0
# Winding-road factor: straight-line km under-estimates real driving distance.
ROAD_WINDING_FACTOR = 1.25
REST_BREAK_INTERVAL_MINUTES = 120


class Coordinate(BaseModel):
    latitude: float
    longitude: float


class RouteLeg(BaseModel):
    from_name: str
    to_name: str
    distance_km: float
    drive_minutes: int


class OrderedStop(BaseModel):
    order: int
    name: str
    latitude: float
    longitude: float
    distance_from_prev_km: float
    drive_minutes_from_prev: int


class RoutePlan(BaseModel):
    ordered: list[OrderedStop]
    legs: list[RouteLeg]
    total_distance_km: float
    total_drive_minutes: int
    recommended_rest_breaks: int


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance between two coordinates in kilometres."""
    radius = 6371.0088
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def estimate_leg(a: Coordinate, b: Coordinate, *, scenic: bool = False) -> tuple[float, int]:
    """Return (road_distance_km, drive_minutes) between two coordinates."""
    straight = haversine_km(a, b)
    road_km = straight * ROAD_WINDING_FACTOR
    speed = SCENIC_SPEED_KMH if scenic else DEFAULT_SPEED_KMH
    minutes = int(round(road_km / speed * 60)) if road_km > 0 else 0
    return round(road_km, 1), minutes


class DriveEstimate(BaseModel):
    distance_km: float
    drive_minutes: int
    eta: datetime


def estimate_drive_time(
    origin: Coordinate,
    destination: Coordinate,
    *,
    depart_at: datetime,
    scenic: bool = False,
) -> DriveEstimate:
    """Estimate distance, driving time, and ETA for a single leg."""
    distance_km, minutes = estimate_leg(origin, destination, scenic=scenic)
    return DriveEstimate(
        distance_km=distance_km,
        drive_minutes=minutes,
        eta=depart_at + timedelta(minutes=minutes),
    )


def _total_distance(order: list[int], coords: list[Coordinate]) -> float:
    return sum(
        haversine_km(coords[order[i]], coords[order[i + 1]])
        for i in range(len(order) - 1)
    )


def _nearest_neighbour(coords: list[Coordinate], start: int) -> list[int]:
    n = len(coords)
    unvisited = set(range(n))
    unvisited.discard(start)
    order = [start]
    current = start
    while unvisited:
        nxt = min(unvisited, key=lambda j: haversine_km(coords[current], coords[j]))
        order.append(nxt)
        unvisited.discard(nxt)
        current = nxt
    return order


def _two_opt(order: list[int], coords: list[Coordinate]) -> list[int]:
    """Improve an open path with 2-opt swaps, keeping the start fixed."""
    best = order[:]
    improved = True
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for k in range(i + 1, len(best)):
                candidate = best[:i] + best[i : k + 1][::-1] + best[k + 1 :]
                if _total_distance(candidate, coords) + 1e-9 < _total_distance(best, coords):
                    best = candidate
                    improved = True
    return best


class RouteStopInput(BaseModel):
    name: str
    latitude: float
    longitude: float


def optimise_route(
    stops: list[RouteStopInput],
    *,
    origin: Coordinate | None = None,
    scenic: bool = False,
) -> RoutePlan:
    """Order stops to minimise total driving distance.

    The route starts at ``origin`` (the trip's starting point) when provided;
    otherwise it starts at the first supplied stop. Uses nearest-neighbour to
    seed a tour then 2-opt to refine it.
    """
    if not stops:
        return RoutePlan(
            ordered=[], legs=[], total_distance_km=0.0,
            total_drive_minutes=0, recommended_rest_breaks=0,
        )

    coords = [Coordinate(latitude=s.latitude, longitude=s.longitude) for s in stops]
    names = [s.name for s in stops]

    if origin is not None:
        coords = [origin] + coords
        names = ["__origin__"] + names

    seed = _nearest_neighbour(coords, start=0)
    order = _two_opt(seed, coords)

    # Drop the synthetic origin node from the emitted ordering, but keep its
    # leg into the first real stop.
    ordered: list[OrderedStop] = []
    legs: list[RouteLeg] = []
    total_km = 0.0
    total_min = 0
    seq = 0
    for pos in range(1, len(order)):
        prev_idx = order[pos - 1]
        cur_idx = order[pos]
        distance_km, minutes = estimate_leg(coords[prev_idx], coords[cur_idx], scenic=scenic)
        total_km += distance_km
        total_min += minutes
        legs.append(
            RouteLeg(
                from_name=names[prev_idx],
                to_name=names[cur_idx],
                distance_km=distance_km,
                drive_minutes=minutes,
            )
        )
        seq += 1
        ordered.append(
            OrderedStop(
                order=seq,
                name=names[cur_idx],
                latitude=coords[cur_idx].latitude,
                longitude=coords[cur_idx].longitude,
                distance_from_prev_km=distance_km,
                drive_minutes_from_prev=minutes,
            )
        )

    rest_breaks = int(total_min // REST_BREAK_INTERVAL_MINUTES)
    return RoutePlan(
        ordered=ordered,
        legs=legs,
        total_distance_km=round(total_km, 1),
        total_drive_minutes=total_min,
        recommended_rest_breaks=rest_breaks,
    )
