"""End-to-end orchestration: parse -> geocode -> venues -> (weather, AQ, OSM context, routing) -> score -> explain."""
import asyncio
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import http, nlu, weather
from .activities import ACTIVITIES
from .config import get_settings
from .explain import (WX_SRC, avoid_windows, build_advice, build_evidence, prompt_for, reason_for,
                      template_answer, verify)
from .geo import compass
from .geocode import geocode
from .http import UpstreamError
from .overpass import Venue, fetch_context, fetch_elevation, find_venues
from .profiles import PROFILES, combine
from .routing import travel_times
from .scoring import evaluate_venue
from .timeparse import TimeError, apply_activity_defaults, parse_time

ATTRIBUTION = "\u00a9 OpenStreetMap contributors"
SOURCES = [
    {"name": "OpenStreetMap via Overpass API", "use": "venues, roads, industry, water, green cover", "url": "https://overpass-api.de"},
    {"name": "Nominatim (OSM)", "use": "geocoding place names", "url": "https://nominatim.openstreetmap.org"},
    {"name": "Open-Meteo Forecast", "use": "hourly weather, sunrise/sunset, elevation", "url": "https://open-meteo.com"},
    {"name": "Open-Meteo Air Quality (CAMS)", "use": "hourly PM2.5, PM10, US AQI", "url": "https://open-meteo.com/en/docs/air-quality-api"},
    {"name": "OSRM (OSM road network)", "use": "free-flow travel time", "url": "https://project-osrm.org"},
]


def _msg(status, question, **kw):
    return {"status": status, "question": question, "attribution": ATTRIBUTION, **kw}


async def answer(question: str, slm, *, lat=None, lon=None, now=None, radius_km=None) -> dict:
    t0 = time.time()
    s = get_settings()
    question = (question or "").strip()
    if len(question) < 4:
        return _msg("needs_clarification", question, missing=["question"], message="Ask me about an outdoor activity, e.g. \u201cWhere can I run tomorrow evening near Powai?\u201d")
    parsed = await asyncio.to_thread(nlu.parse_query, question, slm if slm.available else None)

    if parsed.out_of_scope:
        return _msg("out_of_scope", question, message="I only plan outdoor activities (" + ", ".join(a.label for a in ACTIVITIES.values())
                    + "). Try asking where and when to do one of these.")
    if parsed.activity is None:
        return _msg("needs_clarification", question, missing=["activity"],
                    message="Which outdoor activity do you have in mind?", options=[a.label for a in ACTIVITIES.values()])
    act = ACTIVITIES[parsed.activity]

    # ---- location
    try:
        if parsed.coords:
            center = {"name": "the given coordinates", "lat": parsed.coords[0], "lon": parsed.coords[1]}
        elif parsed.location_text:
            center = await geocode(parsed.location_text)
            if center is None:
                return _msg("needs_clarification", question, missing=["location"],
                            message=f"I couldn't find \u201c{parsed.location_text}\u201d on OpenStreetMap. Could you give a nearby landmark or area name?")
        elif lat is not None and lon is not None:
            center = {"name": "your location", "lat": lat, "lon": lon}
        else:
            return _msg("needs_clarification", question, missing=["location"],
                        message="Where should I look? Give me an area or landmark (e.g. \u201cnear Powai\u201d) or send lat/lon.")
    except UpstreamError as exc:
        return _msg("data_unavailable", question, message=f"Geocoding service unavailable: {exc}")

    # ---- time
    tzname = await weather.timezone_for(center["lat"], center["lon"])
    tz = ZoneInfo(tzname)
    now = (now.astimezone(tz) if now else datetime.now(tz))
    try:
        tw = apply_activity_defaults(parse_time(question, now), act)
    except TimeError as exc:
        return _msg("needs_clarification", question, missing=["time"], message=str(exc))

    prof = combine(parsed.profiles)
    radius = min(60.0, parsed.radius_km or radius_km or act.radius_km)
    gaps: list[str] = []
    slm_used = list(parsed.slm_used)

    # ---- candidate places
    try:
        if parsed.mode == "gonogo":
            venues = [Venue("point/0", center["name"], center["lat"], center["lon"], "location")]
        else:
            venues = await find_venues(act, center["lat"], center["lon"], radius, s.max_venues)
            if not venues and radius < 40:
                radius = min(60.0, radius * 2)
                gaps.append(f"No named venues within the first radius; widened the search to {radius:g} km.")
                venues = await find_venues(act, center["lat"], center["lon"], radius, s.max_venues)
            if not venues:
                return _msg("no_venues", question, message=f"OpenStreetMap lists no named {act.label.lower()} venues within {radius:g} km of {center['name']}. Try a larger radius or a nearby area.",
                            interpretation={"activity": act.key, "location": center, "radius_km": radius})
    except UpstreamError as exc:
        return _msg("data_unavailable", question, message=f"Map data (Overpass) unavailable right now: {exc}")

    # ---- live data in parallel; weather is mandatory, the rest degrades gracefully and says so
    days = (tw.end.date() - now.date()).days + 3
    tasks = [weather.fetch_series([(v.lat, v.lon) for v in venues], days)]
    tasks.append(fetch_context(venues))
    tasks.append(travel_times((center["lat"], center["lon"]), venues) if parsed.mode != "gonogo" else asyncio.sleep(0, "skip"))
    tasks.append(fetch_elevation(venues) if act.key in ("hiking", "photography") else asyncio.sleep(0))
    wx, ctx, route, _ = await asyncio.gather(*tasks, return_exceptions=True)
    if isinstance(wx, Exception):
        return _msg("data_unavailable", question, message=f"Weather data unavailable right now ({wx}). I won't guess the weather; please retry shortly.")
    series_list, wgaps = wx
    gaps += wgaps
    if isinstance(ctx, Exception):
        ctx = {}
        gaps.append("OpenStreetMap surroundings (roads, industry, green, water) could not be fetched; local pollution exposure was not modelled.")
    if route == "fallback":
        gaps.append("Road routing was unavailable; travel times are straight-line estimates.")
    elif isinstance(route, Exception):
        gaps.append("Road routing failed; travel time was not scored.")

    goal = tw.goal if act.key == "photography" else None
    dur = 1 if (parsed.mode == "gonogo" or goal) else None
    evals = []
    for v, series in zip(venues, series_list):
        ve = evaluate_venue(act, prof, v, ctx.get(v.id), series, tw, goal=goal, duration=dur)
        if ve.slots:
            evals.append((ve, series))
    if not evals:
        return _msg("data_unavailable", question, message="The forecast returned no usable hours for that window.")
    evals.sort(key=lambda p: (-p[0].best.score, p[0].venue.dist_km))
    ranked = [p[0] for p in evals]
    series_of = {p[0].venue.id: p[1] for p in evals}
    top = ranked[0]

    # focus-hour verdict, later alternative
    verdict = None
    if tw.focus:
        f = tw.focus.replace(minute=0)
        slot = next((sl for sl in top.slots if sl.start == f), None)
        if slot:
            verdict = {"at": f.isoformat(), "score": slot.score, "band": slot.band, "vetoes": slot.vetoes}
    later = None
    if top.best.score < 55:
        alt = evaluate_venue(act, prof, top.venue, top.ctx, series_of[top.venue.id], tw, goal=goal, duration=dur,
                             t_from=tw.end, t_to=tw.end + timedelta(hours=48))
        if alt.best and alt.best.score >= top.best.score + 10:
            later = {"venue": top.venue.name, "start": alt.best.start.isoformat(), "end": alt.best.end.isoformat(),
                     "score": alt.best.score, "band": alt.best.band}

    # ---- evidence, advice, narrative
    ev, ids, codes = build_evidence(act, center["name"], ranked)
    best_date = top.best.start.date()
    sun = series_of[top.venue.id]["sun"].get(best_date)
    sun_text = f"Sunrise {sun[0]:%H:%M}, sunset {sun[1]:%H:%M} on {best_date:%a %d %b}." if sun else ""
    if sun_text:
        ev.append({"id": f"E{len(ev) + 1}", "kind": "sun", "option": 1, "text": sun_text, "source": WX_SRC})
        ids["sun"] = ev[-1]["id"]
    avoids = avoid_windows(top)
    if avoids:
        ev.append({"id": f"E{len(ev) + 1}", "kind": "avoid", "option": 1, "source": WX_SRC + " + scoring",
                   "text": f"At {top.venue.name}, hours scoring poorly: " + "; ".join(f"{a['label']} ({a['reason']})" for a in avoids[:4]) + "."})
    advice = build_advice(act, prof, top, tw, ids, sun_text)

    narrative_src, issues, text = "template", [], None
    if slm.available:
        names = {ve.venue.name: codes[ve.venue.id] for ve in ranked if ve.venue.id in codes}
        messages, user_txt = prompt_for(question, act, prof, tw, ranked, ev, codes, names)
        try:
            raw = await asyncio.to_thread(slm.generate, messages)
            issues = verify(raw, user_txt, len(codes), len(ev))
            if not issues:
                text = re.sub(r"\bP(\d+)\b", lambda m: next((n for n, c in names.items() if c == m.group(0)), m.group(0)), raw)
                narrative_src = "slm"
                slm_used.append("grounded-narration")
        except Exception as exc:       # model failure must never break the answer
            issues = [f"slm error: {exc}"]
    if text is None:
        text = template_answer(act, ranked, ev, ids, codes, avoids)

    # ---- structured response
    def hourly(ve):
        return [{"time": h.t.isoformat(), "score": h.score, "band": band_of(h.score), "feels_c": h.row.get("feels"),
                 "rain_chance": h.row.get("pop"), "wind_kmh": h.row.get("wind"), "wind_from": h.row.get("wdir"),
                 "gust_kmh": h.row.get("gust"), "uv": h.row.get("uv"), "aqi_model": h.row.get("aqi"), "aqi_effective": h.aqi_eff,
                 "exposure": h.exposure, "light": h.light, "vetoes": h.vetoes, "risks": h.risks, "moon": h.moon,
                 "sources": h.contributors, "reason": reason_for(h) if h.score < 55 else None} for h in ve.hours[:120]]

    from .scoring import band as band_of
    options = []
    for i, ve in enumerate(ranked[:3], 1):
        v, sl = ve.venue, ve.best
        options.append({"rank": i, "code": codes.get(v.id), "venue": {"name": v.name, "lat": v.lat, "lon": v.lon, "kind": v.kind, "osm_url": v.osm_url,
                        "distance_km": v.dist_km, "elevation_m": v.elevation_m, "floodlit": v.lit},
                        "best_window": {"start": sl.start.isoformat(), "end": sl.end.isoformat(), "score": sl.score, "band": sl.band,
                                        "travel_min": sl.travel_min, "vetoes": sl.vetoes},
                        "geospatial": {"exposure_at_start": sl.hours[0].exposure, "upwind_sources": sl.hours[0].contributors,
                                       "green_index": None if ve.ctx is None else round(ve.ctx.green_idx, 2),
                                       "water_m": None if ve.ctx is None else ve.ctx.water_m,
                                       "power_line_near": None if ve.ctx is None else ve.ctx.power_line},
                        "hourly": hourly(ve)})
    by_day = {}
    for sl in top.slots:
        d = sl.start.date()
        if d not in by_day or sl.score > by_day[d].score:
            by_day[d] = sl
    day_summary = [{"date": d.isoformat(), "best_start": sl.start.isoformat(), "score": sl.score, "band": sl.band}
                   for d, sl in sorted(by_day.items())]

    resp = {
        "status": "ok", "question": question, "answer": text,
        "interpretation": {"activity": act.key, "activity_label": act.label, "location": center, "radius_km": radius,
                           "window": {"start": tw.start.isoformat(), "end": tw.end.isoformat(), "label": tw.label, "timezone": tzname,
                                      "goal": tw.goal, "focus": tw.focus.isoformat() if tw.focus else None},
                           "profiles": [PROFILES[k].label for k in parsed.profiles], "mode": parsed.mode,
                           "assumptions": tw.assumptions},
        "recommendation": {"venue": top.venue.name, "start": top.best.start.isoformat(), "end": top.best.end.isoformat(),
                           "score": top.best.score, "band": top.best.band, "focus_verdict": verdict, "later_alternative": later},
        "extras": {"sunrise": sun[0].isoformat() if sun else None, "sunset": sun[1].isoformat() if sun else None,
                   "moon_illumination_pct": top.best.hours[0].moon},
        "options": options, "day_summary": day_summary, "advice": advice, "evidence": ev, "data_gaps": gaps,
        "sources": SOURCES, "attribution": ATTRIBUTION,
        "meta": {"model": slm.model_id, "narrative_source": narrative_src, "slm_used_for": slm_used,
                 "verification_issues": issues, "elapsed_s": round(time.time() - t0, 2), "cache": dict(http.stats),
                 "scoring": "heuristic v1 (see docs/METHOD.md)"},
    }
    resp["markdown"] = render_markdown(resp)
    return resp


def render_markdown(r: dict) -> str:
    rec, adv = r["recommendation"], r["advice"]
    i = r["interpretation"]
    L = [f"**{i['activity_label']}** near **{i['location']['name']}** \u2014 {i['window']['label']}"
         + (f" \u2014 profile: {', '.join(i['profiles'])}" if i["profiles"] else ""), "", r["answer"], ""]
    if rec.get("focus_verdict"):
        v = rec["focus_verdict"]
        L += [f"**At your requested time:** {v['band']} ({v['score']}/100)" + (f" \u2014 {', '.join(v['vetoes'])}" if v["vetoes"] else ""), ""]
    if rec.get("later_alternative"):
        a = rec["later_alternative"]
        L += [f"**Later option:** {a['venue']} from {a['start'][:16].replace('T', ' ')} ({a['score']}/100).", ""]
    for title, key in (("Carry", "carry"), ("Watch for", "watch")):
        if adv[key]:
            L += [f"**{title}**"] + [f"- {x['text']}" + (f" [{', '.join(x['evidence'])}]" if x["evidence"] else "") for x in adv[key]] + [""]
    if adv["avoid"]:
        L += ["**Avoid**"] + [f"- {a['label']}: {a['reason']}" for a in adv["avoid"][:5]] + [""]
    if adv["profile_notes"]:
        L += [f"- {n}" for n in adv["profile_notes"]] + [""]
    if r["data_gaps"]:
        L += ["**Data gaps:** " + " ".join(r["data_gaps"]), ""]
    L.append(f"_Sources: Open-Meteo, OpenStreetMap/Overpass/Nominatim, OSRM. {r['attribution']}._")
    return "\n".join(L)
