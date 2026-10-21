"""Turn raw OSM context into a *time-dependent* local exposure index.

For every pollution source (busy road, industry) we look at where the wind is blowing *from* at that hour:
a source upwind of the venue counts fully, a crosswind one partly, a downwind one barely. Wind speed dilutes,
and road traffic follows a rush-hour profile, so the same ground can be bad at 8 AM and fine by evening.
This is a transparent heuristic layered on a ~11-40 km air-quality model, not a measured concentration.
"""
import math

from .geo import angdiff, compass


def traffic_factor(hour: int) -> float:
    if 7 <= hour <= 10 or 17 <= hour <= 21:
        return 1.0
    if 11 <= hour <= 16 or hour == 6:
        return 0.6
    return 0.25


def exposure(ctx, wind_from: float | None, wind_kmh: float | None, hour: int):
    """-> (index 0..1, top contributors [{label, dist_m, bearing, relation, weight}])."""
    if ctx is None:
        return 0.0, []
    calm = wind_kmh is None or wind_kmh < 5 or wind_from is None
    dil = 1.0 if (wind_kmh is None or wind_kmh < 5) else max(0.4, 1 - (wind_kmh - 5) / 40)
    total, contribs = 0.0, []
    for s in ctx.sources:
        prox = max(0.0, 1 - s.dist_m / {"traffic": 1500, "industry": 3000}[s.kind])
        if s.strength < .5 and s.kind == "traffic":
            prox = max(0.0, 1 - s.dist_m / 600)
        if calm:
            align, rel = 0.5, "calm air"
        else:
            delta = angdiff(s.bearing, wind_from)
            align = 0.15 + 0.85 * max(0.0, math.cos(math.radians(delta)))
            rel = "upwind" if delta <= 45 else "downwind" if delta >= 135 else "crosswind"
        temporal = traffic_factor(hour) if s.kind == "traffic" else 1.0
        w = s.strength * prox * align * dil * temporal
        total += w
        if w > 0.01:
            contribs.append({"label": s.label, "dist_m": round(s.dist_m), "dir": compass(s.bearing),
                             "relation": rel, "weight": round(w, 3), "lat": s.lat, "lon": s.lon})
    contribs.sort(key=lambda c: -c["weight"])
    return 1 - math.exp(-1.5 * total), contribs[:3]
