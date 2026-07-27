"""Curated place catalog and geocoding gazetteer.

In production the places/restaurant services would call an external Places
provider (e.g. Google Places, ATDW). For the MVP we ship a curated, versioned
reference dataset of real landmarks with approximate public coordinates. The
agent never invents locations — it only ever returns rows selected from here.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.enums import Region, StopType

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Coordinates for common trip origins/destinations, used to geocode free-text
# origins supplied by the driver. Real, well-known city/town centres.
GAZETTEER: dict[str, tuple[float, float]] = {
    # Australia
    "sydney": (-33.8688, 151.2093),
    "katoomba": (-33.7148, 150.3120),
    "blue mountains": (-33.7148, 150.3120),
    "wollongong": (-34.4278, 150.8931),
    "melbourne": (-37.8136, 144.9631),
    "torquay": (-38.3333, 144.3167),
    "geelong": (-38.1499, 144.3617),
    "apollo bay": (-38.7550, 143.6680),
    "port campbell": (-38.6190, 142.9980),
    "newcastle": (-32.9283, 151.7817),
    "canberra": (-35.2809, 149.1300),
    # Nepal
    "kathmandu": (27.7172, 85.3240),
    "thamel": (27.7154, 85.3123),
    "pokhara": (28.2096, 83.9856),
    "bandipur": (27.9370, 84.4130),
    "kurintar": (27.8760, 84.5320),
    "chitwan": (27.5291, 84.3542),
    "bhaktapur": (27.6710, 85.4298),
}


class Place(BaseModel):
    """A single catalog entry."""

    name: str
    stop_type: StopType
    area: str
    latitude: float
    longitude: float
    moods: list[str] = Field(default_factory=list)
    traveller_types: list[str] = Field(default_factory=list)
    rating: float | None = None
    opening_hours: str | None = None
    family_friendly: bool = True
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)

    def haystack(self) -> str:
        """Lower-cased text used for destination keyword matching."""
        parts = [self.name, self.area, *self.keywords]
        return " ".join(parts).lower()


class Catalog(BaseModel):
    region: Region
    source: str
    places: list[Place]


@lru_cache
def load_catalog(region: Region) -> Catalog:
    """Load and cache the reference catalog for a region."""
    path = _DATA_DIR / f"{region.value}.json"
    if not path.exists():
        raise FileNotFoundError(f"No catalog data for region {region.value!r}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Catalog.model_validate(raw)


def geocode(name: str) -> tuple[float, float] | None:
    """Resolve a free-text place name to (lat, lon) via the gazetteer.

    Falls back to a case-insensitive substring match so "downtown Sydney"
    still resolves to Sydney.
    """
    if not name:
        return None
    key = name.strip().lower()
    if key in GAZETTEER:
        return GAZETTEER[key]
    for gz_name, coords in GAZETTEER.items():
        if gz_name in key or key in gz_name:
            return coords
    return None
