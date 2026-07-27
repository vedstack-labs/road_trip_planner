"""Australia context provider backed by Tourism Australia (australia.com)."""

from __future__ import annotations

from app.config import get_settings
from app.enums import Region
from app.locations.base import LocationContext, fetch_live_context

# Known destination -> australia.com guide path. Unmatched destinations fall
# back to the national "places to visit" hub.
_GUIDE_PATHS: dict[str, str] = {
    "sydney": "/en/places/sydney-and-surrounds/guide-to-sydney.html",
    "melbourne": "/en/places/melbourne-and-surrounds/guide-to-melbourne.html",
    "brisbane": "/en/places/brisbane-and-surrounds/guide-to-brisbane.html",
    "perth": "/en/places/perth-and-surrounds/guide-to-perth.html",
    "adelaide": "/en/places/adelaide-and-surrounds/guide-to-adelaide.html",
    "hobart": "/en/places/hobart-and-surrounds/guide-to-hobart.html",
    "canberra": "/en/places/canberra-and-surrounds/guide-to-canberra.html",
    "darwin": "/en/places/darwin-and-surrounds/guide-to-darwin.html",
    "great ocean road": "/en/trips-and-itineraries/self-drive-itineraries.html",
    "blue mountains": "/en/places/sydney-and-surrounds.html",
    "wollongong": "/en/places/sydney-and-surrounds.html",
}
_FALLBACK_PATH = "/en/places.html"
_FALLBACK = (
    "Australia offers world-class beaches, national parks, food and wine regions, "
    "and iconic road-trip routes. Recommendations prioritise official Tourism "
    "Australia destinations."
)


def _guide_path(destination: str) -> str:
    key = destination.strip().lower()
    for name, path in _GUIDE_PATHS.items():
        if name in key or key in name:
            return path
    return _FALLBACK_PATH


class AustraliaContextProvider:
    region = Region.AUSTRALIA

    async def get_context(self, destination: str) -> LocationContext:
        return await fetch_live_context(
            region=Region.AUSTRALIA,
            destination=destination,
            base_url=get_settings().australia_context_base_url,
            path=_guide_path(destination),
            source="Tourism Australia (australia.com)",
            fallback_summary=_FALLBACK,
            fallback_path=_FALLBACK_PATH,
        )
