"""Travel time via OSRM (OpenStreetMap road network). OSRM has no live traffic, so we expose the free-flow
time and apply a *documented* time-of-day congestion factor on top, clearly labelled as an estimate."""
from .config import get_settings
from .geo import haversine_km
from .http import UpstreamError, request_json


def congestion_factor(hour: int) -> float:
    if 8 <= hour <= 10:
        return 1.5
    if 17 <= hour <= 20:
        return 1.7
    if 11 <= hour <= 16:
        return 1.15
    return 1.0


async def travel_times(origin: tuple[float, float], venues) -> str:
    s = get_settings()
    coords = ";".join([f"{origin[1]:.5f},{origin[0]:.5f}"] + [f"{v.lon:.5f},{v.lat:.5f}" for v in venues])
    try:
        js = await request_json("GET", f"{s.osrm_url}/table/v1/driving/{coords}", ttl=3600,
                                params={"sources": "0", "annotations": "duration,distance"})
        for v, dur, dist in zip(venues, js["durations"][0][1:], js["distances"][0][1:]):
            if dur is None:
                raise KeyError("no route")
            v.travel_free_min, v.travel_km, v.travel_method = dur / 60, dist / 1000, "OSRM road routing"
        return "OSRM"
    except (UpstreamError, KeyError, IndexError, TypeError):
        for v in venues:
            km = haversine_km(origin[0], origin[1], v.lat, v.lon) * 1.35
            v.travel_free_min, v.travel_km, v.travel_method = km / 30 * 60, km, "straight-line estimate (routing unavailable)"
        return "fallback"
