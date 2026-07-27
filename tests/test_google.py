"""Google Maps integration: response parsing and graceful fallback (mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.enums import Region, StopType
from app.services import google_maps, providers
from app.services.google_maps import GoogleMapsService
from app.services.maps_service import Coordinate, RouteStopInput

# Capture the real client BEFORE any monkeypatch (google_maps.httpx is the shared
# httpx module, so patching its AsyncClient would otherwise recurse into itself).
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_client(handler):
    return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    host = request.url.host
    if host == "maps.googleapis.com":  # Geocoding
        return httpx.Response(200, json={"status": "OK", "results": [
            {"geometry": {"location": {"lat": -33.87, "lng": 151.2}}}
        ]})
    if host == "places.googleapis.com":  # Places API (New)
        return httpx.Response(200, json={"places": [
            {
                "displayName": {"text": "Single Origin Roasters"},
                "formattedAddress": "Surry Hills NSW",
                "location": {"latitude": -33.88, "longitude": 151.21},
                "rating": 4.6,
                "types": ["cafe", "coffee_shop"],
                "regularOpeningHours": {"weekdayDescriptions": ["Mon: 7am-4pm"]},
                "editorialSummary": {"text": "Specialty coffee roaster"},
            },
            {
                "displayName": {"text": "Sydney Opera House"},
                "location": {"latitude": -33.8568, "longitude": 151.2153},
                "rating": 4.7,
                "types": ["tourist_attraction"],
            },
        ]})
    if host == "routes.googleapis.com":  # Routes API
        return httpx.Response(200, json={"routes": [
            {
                "optimizedIntermediateWaypointIndex": [1, 0],
                "legs": [
                    {"distanceMeters": 10000, "duration": "600s"},
                    {"distanceMeters": 20000, "duration": "1200s"},
                    {"distanceMeters": 30000, "duration": "1800s"},
                ],
            }
        ]})
    return httpx.Response(404)


@pytest.fixture
def mock_google(monkeypatch):
    def factory(*args, **kwargs):
        return _mock_client(_handler)

    monkeypatch.setattr(google_maps.httpx, "AsyncClient", factory)


def _svc() -> GoogleMapsService:
    return GoogleMapsService(api_key="test-key", timeout=5)


async def test_geocode_parses_coordinate(mock_google):
    coord = await _svc().geocode("Sydney", region_code="AU")
    assert coord == Coordinate(latitude=-33.87, longitude=151.2)


async def test_search_places_maps_fields_and_types(mock_google):
    places = await _svc().search_places(text_query="cafes near Sydney", default_stop_type=StopType.CAFE)
    assert places[0].name == "Single Origin Roasters"
    assert places[0].stop_type is StopType.CAFE
    assert places[0].rating == 4.6
    assert places[0].opening_hours == "Mon: 7am-4pm"
    # tourist_attraction maps to ATTRACTION even under a CAFE default.
    assert places[1].stop_type is StopType.ATTRACTION


async def test_optimise_route_uses_google_waypoint_order(mock_google):
    stops = [
        RouteStopInput(name="A", latitude=-33.7, longitude=150.3),
        RouteStopInput(name="B", latitude=-34.2, longitude=150.9),
    ]
    plan = await _svc().optimise_route(stops, origin=Coordinate(latitude=-33.87, longitude=151.2))
    # optimizedIntermediateWaypointIndex [1,0] => visit B then A.
    assert [s.name for s in plan.ordered] == ["B", "A"]
    assert plan.ordered[0].distance_from_prev_km == 10.0
    assert plan.ordered[0].drive_minutes_from_prev == 10
    # Return leg (legs[2], 30km) is dropped: total = 10 + 20 km.
    assert plan.total_distance_km == 30.0
    assert plan.total_drive_minutes == 30


async def test_leg_estimate_parses_route(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"routes": [{"distanceMeters": 15000, "duration": "900s"}]})

    monkeypatch.setattr(google_maps.httpx, "AsyncClient", lambda *a, **k: _mock_client(handler))
    km, minutes = await _svc().leg_estimate(
        Coordinate(latitude=0, longitude=0), Coordinate(latitude=1, longitude=1)
    )
    assert km == 15.0
    assert minutes == 15


async def test_provider_prefers_google_when_enabled(mock_google):
    settings = Settings(google_maps_api_key="test-key", prefer_google=True)
    assert settings.google_enabled
    results = await providers.find_attractions(
        settings, region=Region.AUSTRALIA, destination="Sydney",
        traveller_type=None, moods=["coffee"], near=None, limit=5,
    )
    # Came from Google mock, not the curated catalog.
    assert "Single Origin Roasters" in {p.name for p in results}


async def test_provider_falls_back_on_google_error(monkeypatch):
    def failing(request):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(google_maps.httpx, "AsyncClient", lambda *a, **k: _mock_client(failing))
    settings = Settings(google_maps_api_key="test-key", prefer_google=True)
    results = await providers.find_attractions(
        settings, region=Region.AUSTRALIA, destination="Blue Mountains",
        traveller_type=None, moods=["scenic"], near=None, limit=3,
    )
    # Google 500 => fell back to the curated catalog (Blue Mountains spots).
    assert results
    assert any("blue mountains" in p.haystack() for p in results)
