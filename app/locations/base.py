"""Location provider interface, shared context model, and live-fetch helper."""

from __future__ import annotations

import html
import re
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings
from app.enums import Region


class LocationContext(BaseModel):
    """Authoritative destination context surfaced to the driver."""

    region: Region
    destination: str
    summary: str
    highlights: list[str] = Field(default_factory=list)
    source: str
    source_url: str | None = None
    live: bool = False  # True when fetched live from an official source this call


class LocationProvider(Protocol):
    region: Region

    async def get_context(self, destination: str) -> LocationContext:
        """Return destination context for the given free-text destination."""
        ...


_META_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*'
    r'content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Also handle attribute order with content before name/property.
_META_DESC_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
    r'(?:name|property)=["\'](?:description|og:description)["\']',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Process-lifetime cache keyed by region + base_url + destination.
_cache: dict[str, LocationContext] = {}


def _extract_summary(html_text: str) -> str | None:
    match = _META_DESC_RE.search(html_text) or _META_DESC_RE_ALT.search(html_text)
    return html.unescape(match.group(1).strip()) if match else None


def _extract_title(html_text: str) -> str | None:
    match = _TITLE_RE.search(html_text)
    if not match:
        return None
    return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip()) or None


async def fetch_live_context(
    *,
    region: Region,
    destination: str,
    base_url: str,
    path: str,
    source: str,
    fallback_summary: str,
    fallback_path: str | None = None,
) -> LocationContext:
    """Fetch an official tourism page and extract a concise summary.

    Fails soft: on disabled context, timeout, non-200, or a missing summary it
    returns ``fallback_summary``. Results are cached for the process lifetime.
    """
    settings = get_settings()
    cache_key = f"{region.value}|{base_url}|{destination.strip().lower()}"
    if cache_key in _cache:
        return _cache[cache_key]

    fallback = LocationContext(
        region=region,
        destination=destination,
        summary=fallback_summary,
        source=source,
        source_url=base_url.rstrip("/") + (fallback_path or path),
        live=False,
    )
    if not settings.enable_external_context:
        return fallback

    url = base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(
            timeout=settings.location_context_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Helpsonroad-TripPlanner/1.0"},
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return fallback
        summary = _extract_summary(resp.text)
        if not summary:
            return fallback
    except (httpx.HTTPError, OSError):
        return fallback

    title = _extract_title(resp.text)
    context = LocationContext(
        region=region,
        destination=destination,
        summary=summary,
        highlights=[title] if title else [],
        source=source,
        source_url=url,
        live=True,
    )
    _cache[cache_key] = context
    return context
