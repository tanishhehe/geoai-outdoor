"""Place x hour scoring.

Every (venue, hour) gets a 0-100 score built from transparent component risks (0 = ideal, 1 = unacceptable):
heat, cold, rain, wind, air quality, UV, light, cloud (photography) and travel. Personal profiles shift the
thresholds. Hard "vetoes" (thunderstorm, dangerous heat/AQI/gusts, no light) cap the score regardless of the rest.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .activities import Activity
from .geo_context import exposure
from .routing import congestion_factor

THUNDER = {95, 96, 99}


def ramp(x, lo, hi) -> float:
    if x is None:
        return 0.0
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def moon_illumination(t: datetime) -> int:
    """Approximate % of the moon lit (synodic-month formula, good to a few %). Computed, not fetched."""
    jd = t.timestamp() / 86400 + 2440587.5
    phase = ((jd - 2451550.26) / 29.530588853) % 1
    return round(50 * (1 - math.cos(2 * math.pi * phase)))


def in_daily(hour: int, d) -> bool:
    if d is None:
        return True
    return d[0] <= hour < d[1] if d[0] < d[1] else (hour >= d[0] or hour < d[1])


def band(score: float) -> str:
    return "great" if score >= 75 else "good" if score >= 55 else "marginal" if score >= 35 else "avoid"


@dataclass
class HourEval:
    t: datetime
    score: float
    risks: dict
    vetoes: list
    row: dict
    aqi_eff: float | None
    exposure: float
    contributors: list
    light: str = "day"
    moon: int | None = None


@dataclass
class Slot:
    start: datetime
    end: datetime
    score: float
    band: str
    hours: list
    travel_min: float | None
    vetoes: list


@dataclass
class VenueEval:
    venue: object
    ctx: object
    hours: list = field(default_factory=list)
    slots: list = field(default_factory=list)

    @property
    def best(self):
        return max(self.slots, key=lambda s: (s.score, -s.start.timestamp()), default=None)


def _light(act: Activity, mid: datetime, sun, row, lit: bool, goal):
    """-> (risk, label)"""
    if sun:
        sr, ss = sun
        dark = mid < sr - timedelta(minutes=15) or mid > ss + timedelta(minutes=15)
    else:
        dark = not row.get("is_day", 1)
    if act.key == "stargazing":
        ok = (mid >= sun[1] + timedelta(minutes=90) or mid <= sun[0] - timedelta(minutes=90)) if sun else not row.get("is_day", 1)
        return (0.0, "dark sky") if ok else (1.0, "not dark enough")
    if act.key == "birdwatching":
        if dark:
            return 1.0, "dark"
        if sun and sun[0] - timedelta(minutes=30) <= mid <= sun[0] + timedelta(minutes=150):
            return 0.0, "dawn chorus"
        return 0.35, "daylight"
    if act.key == "photography":
        if dark:
            return 1.0, "dark"
        if sun:
            sr, ss = sun
            golden = (ss - timedelta(minutes=70) <= mid <= ss + timedelta(minutes=25)
                      or sr - timedelta(minutes=25) <= mid <= sr + timedelta(minutes=70))
            if goal == "sunset":
                return (0.0, "golden hour") if ss - timedelta(minutes=70) <= mid <= ss + timedelta(minutes=25) else (0.85, "off-target light")
            if goal == "sunrise":
                return (0.0, "golden hour") if sr - timedelta(minutes=25) <= mid <= sr + timedelta(minutes=70) else (0.85, "off-target light")
            if golden:
                return 0.0, "golden hour"
        return (0.45, "harsh midday light") if 10.5 <= mid.hour + mid.minute / 60 <= 15.5 else (0.2, "daylight")
    if dark:
        return act.dark_risk * (0.3 if lit else 1.0), "dark (lit venue)" if lit else "dark"
    return 0.0, "day"


def eval_hour(act: Activity, prof, t: datetime, row: dict, ctx, sun, lit: bool, goal) -> HourEval:
    feels = row.get("feels", row.get("temp"))
    green, water = (ctx.green_idx if ctx else 0.0), (ctx is not None and ctx.water_m is not None)
    cool = 0.0
    if feels is not None and feels >= 25:
        cool = (1.0 if green >= .66 else .5 if green >= .33 else 0.0) + (.5 if water else 0.0)
    fe = None if feels is None else feels - cool
    wdir, wind = row.get("wdir"), row.get("wind")
    exp_idx, contribs = exposure(ctx, wdir, wind, t.hour)

    aqi = row.get("aqi")
    aqi_eff = None if aqi is None else aqi * (1 + 0.35 * exp_idx) * (1 - 0.08 * green)
    mid = t + timedelta(minutes=30)
    light_r, light_lbl = _light(act, mid, sun, row, lit, goal)
    is_day = light_lbl not in ("dark", "dark (lit venue)", "dark sky")
    star = act.key == "stargazing"
    moon_pct = moon_illumination(t + timedelta(minutes=30)) if star else None
    pop, precip, code = row.get("pop"), row.get("precip"), row.get("code")

    risks = {
        "heat": ramp(fe, act.heat[0] + prof.heat_shift, act.heat[1] + prof.heat_shift),
        "cold": ramp((act.cold[0] + prof.cold_shift) - fe, 0, act.cold[0] - act.cold[1]) if fe is not None else 0.0,
        "rain": max(ramp(pop, *act.pop), ramp(precip, 0.2, 3.0)),
        "wind": ramp(row.get("gust"), act.gust[0] * prof.wind_factor, act.gust[1] * prof.wind_factor),
        "aqi": ramp(aqi_eff, act.aqi[0] * prof.aqi_factor, act.aqi[1] * prof.aqi_factor),
        "uv": ramp(row.get("uv"), act.uv[0] * prof.uv_factor, act.uv[1] * prof.uv_factor) if is_day else 0.0,
        "light": light_r,
        "cloud": ramp(row.get("cloud"), *((25, 75) if star else (65, 95))) if (is_day or star) else 0.0,
        "moon": (moon_pct / 100 if (star and not is_day) else 0.0),
    }
    vetoes = []
    if code in THUNDER:
        risks["rain"] = 1.0
        vetoes.append("thunderstorm forecast")
    if risks["heat"] >= .999:
        vetoes.append("dangerous heat for this activity/profile")
    if risks["aqi"] >= .999:
        vetoes.append("air quality too poor for this activity/profile")
    if risks["wind"] >= .999:
        vetoes.append("gusts too strong")
    if risks["light"] >= .999:
        vetoes.append("sky not dark enough" if star else "too dark")
    if risks["rain"] >= .999 and act.weights()["rain"] >= .25 and "thunderstorm forecast" not in vetoes:
        vetoes.append("heavy/likely rain")
    w = act.weights()
    score = 100 * (1 - min(1.0, sum(w[k] * r for k, r in risks.items() if k in w)))
    if vetoes:
        score = min(score, 25.0)
    return HourEval(t, round(score, 1), {k: round(v, 2) for k, v in risks.items()}, vetoes, row,
                    None if aqi_eff is None else round(aqi_eff), round(exp_idx, 3), contribs, light_lbl, moon_pct)


def evaluate_venue(act, prof, venue, ctx, series, tw, *, goal=None, t_from=None, t_to=None,
                   duration=None) -> VenueEval:
    rows, sun_by_date = series["rows"], series["sun"]
    t_from, t_to = t_from or tw.start, t_to or tw.end
    daily = tw.daily_hours
    ve = VenueEval(venue, ctx)
    times = sorted(t for t in rows if t_from <= t < t_to and in_daily(t.hour, daily))
    for t in times:
        ve.hours.append(eval_hour(act, prof, t, rows[t], ctx, sun_by_date.get(t.date()), venue.lit, goal))
    by_t = {h.t: h for h in ve.hours}
    dur = duration or act.duration_h
    for h in ve.hours:
        span = [by_t.get(h.t + timedelta(hours=i)) for i in range(dur)]
        if any(s is None for s in span):
            # allow slots that run past the window edge if the forecast has those hours
            span = [by_t.get(h.t + timedelta(hours=i)) or (
                eval_hour(act, prof, h.t + timedelta(hours=i), rows[h.t + timedelta(hours=i)],
                          ctx, sun_by_date.get((h.t + timedelta(hours=i)).date()), venue.lit, goal)
                if (h.t + timedelta(hours=i)) in rows else None) for i in range(dur)]
            if any(s is None for s in span):
                continue
        if goal in ("sunset", "sunrise") and act.key == "photography" and h.light == "off-target light":
            continue
        scores = [s.score for s in span]
        base = 0.6 * (sum(scores) / len(scores)) + 0.4 * min(scores)
        tmin = None
        pen = 0.0
        if venue.travel_free_min is not None:
            tmin = venue.travel_free_min * congestion_factor(h.t.hour)
            pen = 100 * act.weights()["travel"] * ramp(tmin, act.travel_ok_min, act.travel_ok_min * 2.2)
        vetoes = sorted({v for s in span for v in s.vetoes})
        sc = max(0.0, base - pen)
        if vetoes:
            sc = min(sc, 25.0)
        ve.slots.append(Slot(h.t, h.t + timedelta(hours=dur), round(sc), band(sc), span,
                             None if tmin is None else round(tmin), vetoes))
    return ve
