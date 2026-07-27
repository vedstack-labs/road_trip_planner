"""Unit tests for the geo/maps and places/restaurant services."""

from __future__ import annotations

from datetime import datetime, timezone

from app.enums import Mood, Region, StopType, TravellerType
from app.services import places_service, restaurant_service
from app.services.catalog import geocode
from app.services.maps_service import (
    Coordinate,
    RouteStopInput,
    estimate_drive_time,
    haversine_km,
    optimise_route,
)


def test_haversine_sydney_melbourne_known_distance():
    sydney = Coordinate(latitude=-33.8688, longitude=151.2093)
    melbourne = Coordinate(latitude=-37.8136, longitude=144.9631)
    km = haversine_km(sydney, melbourne)
    # Great-circle Sydney-Melbourne is ~714 km.
    assert 700 <= km <= 730


def test_estimate_drive_time_positive_and_eta_advances():
    a = Coordinate(latitude=-33.87, longitude=151.20)
    b = Coordinate(latitude=-33.73, longitude=150.30)
    depart = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    est = estimate_drive_time(a, b, depart_at=depart)
    assert est.distance_km > 0
    assert est.drive_minutes > 0
    assert est.eta > depart


def test_optimise_route_orders_all_stops_and_counts_rest_breaks():
    stops = [
        RouteStopInput(name="far", latitude=-38.6662, longitude=143.1044),
        RouteStopInput(name="near", latitude=-33.73, longitude=150.30),
        RouteStopInput(name="mid", latitude=-34.25, longitude=150.97),
    ]
    origin = Coordinate(latitude=-33.87, longitude=151.20)
    plan = optimise_route(stops, origin=origin, scenic=True)
    assert len(plan.ordered) == 3
    assert [s.order for s in plan.ordered] == [1, 2, 3]

    # The emitted order must be the distance-minimal path from the origin
    # (compare against brute force over all permutations).
    import itertools

    from app.services.maps_service import haversine_km

    def path_km(seq):
        pts = [origin] + [Coordinate(latitude=s.latitude, longitude=s.longitude) for s in seq]
        return sum(haversine_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    best = min(path_km(list(p)) for p in itertools.permutations(stops))
    produced = path_km(
        [next(s for s in stops if s.name == o.name) for o in plan.ordered]
    )
    assert abs(produced - best) < 1e-6
    # The far Victorian stop is last on the shortest path.
    assert plan.ordered[-1].name == "far"
    assert plan.total_drive_minutes > 0
    # Long total (includes a leg to Victoria) => at least one rest break.
    assert plan.recommended_rest_breaks >= 1


def test_geocode_matches_known_and_substring():
    assert geocode("Sydney") is not None
    assert geocode("downtown sydney cbd") == geocode("sydney")
    assert geocode("Atlantis") is None


def test_search_attractions_ranks_mood_and_destination():
    results = places_service.search_attractions(
        region=Region.AUSTRALIA,
        destination="Blue Mountains",
        traveller_type=TravellerType.FAMILY,
        moods=[Mood.SCENIC.value, Mood.NATURE.value],
        limit=5,
    )
    assert results
    assert len(results) <= 5
    # Top result should be a Blue Mountains scenic/nature spot.
    assert "blue mountains" in results[0].haystack()
    assert results[0].stop_type in {StopType.ATTRACTION, StopType.SCENIC_LOOKOUT}


def test_search_restaurants_coffee_prefers_cafe():
    results = restaurant_service.search_restaurants(
        region=Region.AUSTRALIA,
        destination="Sydney",
        moods=[Mood.COFFEE.value],
        limit=3,
    )
    assert results
    assert results[0].stop_type is StopType.CAFE


def test_nepal_catalog_available():
    results = places_service.search_attractions(
        region=Region.NEPAL, destination="Kathmandu", limit=3
    )
    assert results
    assert all(r.latitude and r.longitude for r in results)
