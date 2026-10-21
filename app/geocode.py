"""Nominatim geocoding (OSM). Usage policy: max 1 request/second, identifying User-Agent, cache results."""
import asyncio
import time

from .config import get_settings
from .http import UpstreamError, request_json

_lock = asyncio.Lock()
_last = 0.0


async def geocode(name: str) -> dict | None:
    global _last
    s = get_settings()
    tries = [s.geocode_countries, ""] if s.geocode_countries else [""]
    for cc in tries:
        params = {"q": name, "format": "jsonv2", "limit": 1}
        if cc:
            params["countrycodes"] = cc
        async with _lock:
            wait = 1.1 - (time.monotonic() - _last)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                res = await request_json("GET", s.nominatim_url, params=params, ttl=86400)
            finally:
                _last = time.monotonic()
        if res:
            r = res[0]
            return {"name": name, "lat": float(r["lat"]), "lon": float(r["lon"]),
                    "display_name": r.get("display_name", name)}
    return None
