"""One shared async HTTP client + a small TTL cache (be polite to free APIs)."""
import asyncio
import json
import time

import httpx

from .config import get_settings


class UpstreamError(RuntimeError):
    """A free data source failed. We report this; we never fill the gap with invented data."""


_client: httpx.AsyncClient | None = None
_cache: dict = {}
stats = {"hits": 0, "misses": 0}


def set_client(c: httpx.AsyncClient | None) -> None:
    global _client
    _client = c


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = httpx.AsyncClient(headers={"User-Agent": s.user_agent},
                                    timeout=s.request_timeout, follow_redirects=True)
    return _client


def clear_cache() -> None:
    _cache.clear()
    stats.update(hits=0, misses=0)


async def request_json(method: str, url: str, *, params=None, data=None,
                       ttl: float = 600, retries: int = 1):
    key = (method, url, json.dumps(params, sort_keys=True, default=str),
           json.dumps(data, sort_keys=True, default=str))
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        stats["hits"] += 1
        return hit[1]
    stats["misses"] += 1
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = await client().request(method, url, params=params, data=data)
            if r.status_code == 429 or r.status_code >= 500:
                raise UpstreamError(f"HTTP {r.status_code}")
            r.raise_for_status()
            js = r.json()
            if len(_cache) > 4000:
                _cache.clear()
            _cache[key] = (time.time() + ttl, js)
            return js
        except (httpx.HTTPError, ValueError, UpstreamError) as exc:
            last = exc
            if attempt < retries:
                await asyncio.sleep(0.7 * (attempt + 1))
    raise UpstreamError(f"{url}: {last}")
