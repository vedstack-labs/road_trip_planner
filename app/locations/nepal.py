"""Nepal context provider backed by the Nepal Tourism Board (ntb.gov.np).

Fetches the relevant destination guide page from ntb.gov.np and extracts the
official summary, mirroring the Australia provider. Fails soft to curated
blurbs on any network/parse error.
"""

from __future__ import annotations

from app.config import get_settings
from app.enums import Region
from app.locations.base import LocationContext, fetch_live_context

# Known destination -> ntb.gov.np guide path (from ntb.gov.np/places-to-go).
_GUIDE_PATHS: dict[str, str] = {
    "kathmandu": "/en/kathmandu-valley",
    "bhaktapur": "/en/kathmandu-valley",
    "patan": "/en/kathmandu-valley",
    "thamel": "/en/kathmandu-valley",
    "nagarkot": "/en/nagarkot-sunrise-and-sunset",
    "pokhara": "/en/pokhara",
    "annapurna": "/en/annapurna",
    "everest": "/en/everest",
    "chitwan": "/en/chitwan-national-park",
    "lumbini": "/en/lumbini-province",
    "janakpur": "/en/janakpur",
    "ilam": "/en/ilam",
    "bardiya": "/en/bardiya",
    "palpa": "/en/tansen--palpa",
    "bandipur": "/en/mid-hills",
}
_FALLBACK_PATH = "/places-to-go"

# Curated fallbacks used only when the live fetch is unavailable.
_FALLBACKS: dict[str, str] = {
    "kathmandu": (
        "Kathmandu Valley's three cities (Kathmandu, Patan, Bhaktapur) house seven "
        "UNESCO World Heritage shrines listed together as a World Heritage Site."
    ),
    "pokhara": (
        "Pokhara is a great destination for a weekend getaway or a long relaxing "
        "holiday, best known for stunning views of the Annapurna range."
    ),
    "chitwan": (
        "Chitwan National Park in Nepal's Terai offers jungle safaris, elephant "
        "rides, and bird watching amid rich wilderness."
    ),
}
_DEFAULT = (
    "Nepal offers Himalayan panoramas, UNESCO heritage temples, jungle safaris, and "
    "scenic drives. Recommendations prioritise official Nepal Tourism Board sites."
)


def _guide_path(destination: str) -> str:
    key = destination.strip().lower()
    for name, path in _GUIDE_PATHS.items():
        if name in key or key in name:
            return path
    return _FALLBACK_PATH


def _fallback_summary(destination: str) -> str:
    key = destination.strip().lower()
    for name, blurb in _FALLBACKS.items():
        if name in key or key in name:
            return blurb
    return _DEFAULT


class NepalContextProvider:
    region = Region.NEPAL

    async def get_context(self, destination: str) -> LocationContext:
        return await fetch_live_context(
            region=Region.NEPAL,
            destination=destination,
            base_url=get_settings().nepal_context_base_url,
            path=_guide_path(destination),
            source="Nepal Tourism Board (ntb.gov.np)",
            fallback_summary=_fallback_summary(destination),
            fallback_path=_FALLBACK_PATH,
        )
