"""Location context providers.

Each region can enrich recommendations with authoritative destination context —
for Australia this is sourced live from Tourism Australia (australia.com). The
registry is extensible: add a provider and register it for a new region.
"""

from __future__ import annotations

from app.enums import Region
from app.locations.australia import AustraliaContextProvider
from app.locations.base import LocationContext, LocationProvider
from app.locations.nepal import NepalContextProvider

_PROVIDERS: dict[Region, LocationProvider] = {
    Region.AUSTRALIA: AustraliaContextProvider(),
    Region.NEPAL: NepalContextProvider(),
}


def get_location_provider(region: Region) -> LocationProvider:
    """Return the context provider for a region."""
    return _PROVIDERS[region]


__all__ = [
    "LocationContext",
    "LocationProvider",
    "get_location_provider",
]
