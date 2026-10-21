"""Evidence pack, deterministic advice, avoid-windows, SLM prompt + hallucination guard, template fallback."""
import re
from datetime import timedelta

from .geo import compass
from .routing import congestion_factor
from .scoring import band, ramp

AIR_SRC = "Open-Meteo Air Quality (CAMS model)"
WX_SRC = "Open-Meteo Forecast"
OSM_SRC = "OpenStreetMap contributors via Overpass"


def _rng(vals, nd=0, unit=""):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    lo, hi = min(v), max(v)
    f = (lambda x: f"{x:.{nd}f}")
    return f"{f(lo)}{unit}" if f(lo) == f(hi) else f"{f(lo)}\u2013{f(hi)}{unit}"


def slot_stats(slot) -> dict:
    rows = [h.row for h in slot.hours]
    g = lambda k: [r.get(k) for r in rows]
    mx = lambda k: max([x for x in g(k) if x is not None], default=None)
    mn = lambda k: min([x for x in g(k) if x is not None], default=None)
    return {"feels": g("feels"), "temp": g("temp"), "pop_max": mx("pop"), "precip_sum": sum(x or 0 for x in g("precip")),
            "wind": g("wind"), "gust_max": mx("gust"), "uv_max": mx("uv"), "cloud": g("cloud"),
            "aqi": g("aqi"), "pm25": g("pm25"), "aqi_eff": [h.aqi_eff for h in slot.hours],
            "feels_max": mx("feels"), "feels_min": mn("feels"), "wdir": rows[0].get("wdir"),
            "dark": any(h.light in ("dark", "dark (lit venue)") for h in slot.hours),
            "moon": max([h.moon for h in slot.hours if h.moon is not None], default=None), "codes": g("code"),
            "exposure": max(h.exposure for h in slot.hours), "contribs": slot.hours[0].contributors}


def _weather_text(name, slot, st):
    parts = []
    if (r := _rng(st["feels"], 1)):
        parts.append(f"feels-like {r} \u00b0C")
    if st["pop_max"] is not None:
        parts.append(f"rain chance up to {st['pop_max']:.0f}% ({st['precip_sum']:.1f} mm)")
    if (r := _rng(st["wind"], 0)) and st["wdir"] is not None:
        parts.append(f"wind {r} km/h from the {compass(st['wdir'])} ({st['wdir']:.0f}\u00b0)")
    if st["gust_max"] is not None:
        parts.append(f"gusts up to {st['gust_max']:.0f} km/h")
    if st["uv_max"] is not None:
        parts.append(f"UV up to {st['uv_max']:.0f}")
    if (r := _rng(st["cloud"], 0)):
        parts.append(f"cloud cover {r}%")
    if st.get("moon") is not None:
        parts.append(f"moon about {st['moon']:.0f}% lit (computed from the lunar cycle)")
    return f"{slot.start:%a %d %b %H:%M}\u2013{slot.end:%H:%M} at {name}: " + ", ".join(parts) + "."


def _geo_text(name, ctx, st):
    bits = [f"{c['label']} {c['dist_m']} m to the {c['dir']} ({c['relation']})" for c in st["contribs"]]
    bits = bits or ["no major road or industrial source in OSM near the venue"]
    if ctx is not None:
        bits.append(f"green cover index {ctx.green_idx:.1f}")
        if ctx.water_m is not None:
            bits.append(f"water body {ctx.water_m:.0f} m away")
        if ctx.power_line:
            bits.append("overhead power line within 300 m")
    return (f"Surroundings of {name} at the start hour: " + "; ".join(bits)
            + f". Local pollution-exposure index {st['exposure']:.2f} (0 = clean, 1 = heavy).")


def reason_for(h) -> str:
    """Human reason a given hour is poor, from its largest weighted risks."""
    r, row = h.risks, h.row
    if h.vetoes and "thunderstorm forecast" in h.vetoes:
        return "thunderstorm forecast"
    phr = {"heat": lambda: f"feels-like {row.get('feels', 0):.0f} \u00b0C", "cold": lambda: f"feels-like {row.get('feels', 0):.0f} \u00b0C (cold)",
           "rain": lambda: f"rain chance {row.get('pop') or 0:.0f}%", "wind": lambda: f"gusts {row.get('gust') or 0:.0f} km/h",
           "aqi": lambda: f"AQI about {h.aqi_eff}", "uv": lambda: f"UV {row.get('uv') or 0:.0f}",
           "light": lambda: h.light, "cloud": lambda: f"cloud cover {row.get('cloud') or 0:.0f}%",
           "moon": lambda: f"bright moon ({h.moon}% lit)"}
    top = sorted(((v, k) for k, v in r.items() if v >= .5 and k in phr), reverse=True)[:2]
    return ", ".join(phr[k]() for _, k in top) or "overall marginal conditions"


def avoid_windows(ve, threshold=40) -> list[dict]:
    out, cur = [], None
    for h in ve.hours:
        bad = h.score < threshold or bool(h.vetoes)
        if bad and cur and h.t - cur["last"] <= timedelta(hours=1):
            cur["last"] = h.t
            cur["hs"].append(h)
        elif bad:
            cur = {"first": h.t, "last": h.t, "hs": [h]}
            out.append(cur)
        else:
            cur = None
    res = []
    for c in out:
        worst = min(c["hs"], key=lambda x: x.score)
        res.append({"from": c["first"].isoformat(), "to": (c["last"] + timedelta(hours=1)).isoformat(),
                    "label": f"{c['first']:%a %d %b %H:%M}\u2013{(c['last'] + timedelta(hours=1)):%H:%M}",
                    "reason": reason_for(worst)})
    return res


def build_evidence(act, center_name, ranked, top_n=3):
    """-> (evidence list, venue-code map). Evidence ids are what the SLM must cite."""
    ev, ids, codes = [], {}, {}

    def add(kind, option, text, source):
        e = {"id": f"E{len(ev) + 1}", "kind": kind, "option": option, "text": text, "source": source}
        ev.append(e)
        return e["id"]

    for i, ve in enumerate(ranked[:top_n], 1):
        v, s = ve.venue, ve.best
        if s is None:
            continue
        codes[v.id] = f"P{i}"
        st = slot_stats(s)
        d = ids.setdefault(i, {})
        elev = f", elevation {v.elevation_m:.0f} m" if v.elevation_m is not None else ""
        d["venue"] = add("venue", i, f"{v.name} ({v.kind}{', floodlit' if v.lit else ''}{elev}) is {v.dist_km:.1f} km from {center_name}.", OSM_SRC)
        if v.travel_free_min is not None and i == 1:
            d["travel"] = add("travel", i, f"Drive from {center_name}: {v.travel_km:.1f} km, about {v.travel_free_min:.0f} min free-flow ({v.travel_method}); "
                              f"about {s.travel_min} min at {s.start:%H:%M} using a rush-hour heuristic.", "OSRM + congestion heuristic")
        d["weather"] = add("weather", i, _weather_text(v.name, s, st), WX_SRC)
        if i == 1:
            if (r := _rng(st["aqi"], 0)):
                eff = _rng(st["aqi_eff"], 0)
                d["air"] = add("air", i, f"Air quality: US AQI {r}" + (f", PM2.5 {_rng(st['pm25'], 0)} \u00b5g/m\u00b3" if _rng(st["pm25"], 0) else "")
                               + f" (model); adjusted for local sources the effective AQI is about {eff}.", AIR_SRC)
            d["geo"] = add("geo", i, _geo_text(v.name, ve.ctx, st), OSM_SRC)
    return ev, ids, codes


def build_advice(act, prof, ve, tw, ids, sun_text):
    s = ve.best
    st = slot_stats(s)
    carry, watch = [], []
    E = ids.get(1, {})

    def add(lst, text, *keys):
        lst.append({"text": text, "evidence": [E[k] for k in keys if k in E]})

    fm, fmin = st["feels_max"], st["feels_min"]
    hg, hb = act.heat[0] + prof.heat_shift, act.heat[1] + prof.heat_shift
    if fm is not None and fm >= hg - 4:
        add(carry, "Water: at least 1 litre per person, more for long or intense sessions; add electrolytes if it is humid.", "weather")
    if fm is not None and ramp(fm, hg, hb) >= .25:
        add(watch, f"Heat: feels-like reaches {fm:.1f} \u00b0C. Take shade breaks and stop if you feel dizzy or nauseous.", "weather")
    if st["uv_max"] is not None and st["uv_max"] >= 6:
        add(carry, "Sunscreen (SPF 30+), a cap and sunglasses.", "weather")
    if (st["pop_max"] or 0) >= 30 or st["precip_sum"] >= 0.5:
        add(carry, "Light rain jacket or poncho and a waterproof bag for phone and keys.", "weather")
        add(watch, f"Rain chance reaches {st['pop_max']:.0f}%. Check a radar nowcast before leaving.", "weather")
    if any(c == 95 or c == 96 or c == 99 for c in st["codes"] if c is not None):
        add(watch, "Thunderstorm in the forecast: do not start; if caught outdoors, shelter in a building or car.", "weather")
    eff = [x for x in st["aqi_eff"] if x is not None]
    ag, ab = act.aqi[0] * prof.aqi_factor, act.aqi[1] * prof.aqi_factor
    if eff and ramp(max(eff), ag, ab) >= .45:
        add(carry, "A well-fitted N95/FFP2 mask if you must go; otherwise lower the intensity.", "air")
    if eff and ramp(max(eff), ag, ab) >= .2:
        add(watch, f"Air quality: effective AQI reaches about {max(eff)}. Reduce effort or move the session if you feel throat/chest irritation.", "air")
    if "asthma" in prof.key:
        add(carry, "Reliever inhaler (and spacer) within reach.", "air")
    if fmin is not None and fmin <= act.cold[0] + prof.cold_shift:
        add(carry, f"A warm layer: feels-like drops to {fmin:.1f} \u00b0C.", "weather")
    if act.key == "stargazing":
        cl = [x for x in st["cloud"] if x is not None]
        if cl and sum(cl) / len(cl) >= 30:
            add(watch, f"Cloud cover averages {sum(cl) / len(cl):.0f}% and will hide stars; check a satellite view before driving out.", "weather")
        if st.get("moon") is not None and st["moon"] >= 60:
            add(watch, f"The moon is about {st['moon']:.0f}% lit and washes out faint objects; moonless nights are better.", "weather")
    if st["dark"] and act.key not in ("stargazing", "camping"):
        add(carry, "Torch/headlamp and reflective gear; part of this slot is after dark.", "weather")
        if sun_text:
            E_sun = ids.get("sun")
            watch.append({"text": f"Daylight is limited. {sun_text}", "evidence": [E_sun] if E_sun else []})
    if st["gust_max"] is not None and st["gust_max"] >= act.gust[0] * prof.wind_factor:
        add(watch, f"Gusts up to {st['gust_max']:.0f} km/h: secure tents/decor, expect wind effects on ball sports and cycling.", "weather")
    free = ve.venue.travel_free_min
    if s.travel_min and s.travel_min > act.travel_ok_min and free and s.travel_min / free > 1.2:
        add(watch, f"Travel takes about {s.travel_min} min at that hour; leave early or shift the start.", "travel")
    for c in st["contribs"][:1]:
        if c["relation"] in ("upwind", "calm air") and c["weight"] > .15:
            add(watch, f"{c['label'].capitalize()} {c['dist_m']} m to the {c['dir']} is {c['relation'] if c['relation'] == 'upwind' else 'close and the air is calm'}: keep away from the roadside side of the venue.", "geo")
    carry.append({"text": {
        "running": "Light, reflective clothing and shoes suited to the surface.", "cycling": "Helmet, lights and a puncture kit.",
        "golf": "Rain cover for the bag; leave the course at the first thunder.", "cricket": "Hat, spare water for the whole team, a covered area for kit.",
        "football": "Shin guards and a spare shirt; agree a heat-break rule for kids.", "tennis": "Spare grip/overgrip and a towel; wind affects the ball.",
        "hiking": "Offline map, tell someone your route, sturdy shoes and a head-torch.", "picnic": "A shade sheet and sealed food containers.",
        "event": "A covered fallback area and a contact for the venue manager.", "photography": "Lens cloth, tripod and spare battery.",
        "walking": "Comfortable shoes and a phone with emergency contacts.", "badminton": "Spare shuttles (plastic ones cope better with wind) and a towel.",
        "basketball": "Water, a ball pump and a check of the court for wet or slippery patches.", "swimming": "Sunscreen, cap, towel; leave the water at the first thunder.",
        "yoga": "A mat, a light towel and a flat shaded patch of ground.", "camping": "Tent pegs and guy-lines rated for the wind, torch, power bank and first-aid kit.",
        "stargazing": "Red-light torch, a warm layer and an offline star-map app.", "birdwatching": "Binoculars, muted clothing and quiet footwear."}[act.key], "evidence": []})
    return {"carry": carry, "watch": watch, "avoid": avoid_windows(ve),
            "profile_notes": list(prof.notes) + (["General guidance only, not medical advice."] if prof.key != "none" else [])}


# ------------------------------------------------------------------ SLM narration + hallucination guard
SYSTEM = ("You are the narrator of an outdoor-activity recommender. A scoring engine has already chosen the places and "
          "times from live data; you only explain them. Rules: use ONLY facts from EVIDENCE; refer to places only by their "
          "codes (P1, P2, P3); put the evidence id like [E2] after each fact; copy numbers and times exactly as written in "
          "EVIDENCE (24-hour HH:MM); never invent weather, places or numbers; if the best option is rated 'avoid' or "
          "'marginal', say so plainly. Write 3-5 sentences, at most 110 words, plain prose, no lists.")


def prompt_for(question, act, prof, tw, ranked, ev, codes, mapping_names):
    lines = []
    for ve in ranked[:3]:
        if ve.venue.id in codes and ve.best:
            s = ve.best
            lines.append(f"{codes[ve.venue.id]} | {s.start:%a %d %b %H:%M}\u2013{s.end:%H:%M} | score {s.score} ({s.band})"
                         + (f" | drive about {s.travel_min} min" if s.travel_min else ""))
    ev_txt = "\n".join(f"[{e['id']}] {e['text']}" for e in ev)
    for name, code in sorted(mapping_names.items(), key=lambda kv: -len(kv[0])):
        ev_txt = ev_txt.replace(name, code)
    user = (f"QUESTION: {question}\nACTIVITY: {act.label}\nPERSON: {prof.label}\nWINDOW: {tw.label}\n"
            f"RANKED OPTIONS:\n" + "\n".join(lines) + f"\n\nEVIDENCE:\n{ev_txt}\n\n"
            "Answer: start with the recommendation (place code and start time), then why it beats the alternatives, "
            "then the single biggest risk.")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], user


NUM_RE = re.compile(r"(?<![\w\[.])(\d+(?:\.\d+)?)")
ALLOW_CAPS = {"AQI", "UV", "PM", "OSM", "OSRM", "IST", "I", "The", "A", "It", "If", "Rain", "Heat", "Air"}


def verify(text: str, prompt_user: str, n_codes: int, n_ev: int) -> list[str]:
    issues = []
    if not (12 <= len(text.split()) <= 170):
        issues.append("length out of range")
    cited = {int(x) for x in re.findall(r"\[E(\d+)\]", text)}
    if not cited:
        issues.append("no evidence citations")
    if any(not 1 <= c <= n_ev for c in cited):
        issues.append("cites a non-existent evidence id")
    if any(not 1 <= int(c) <= n_codes for c in re.findall(r"\bP(\d+)\b", text)):
        issues.append("refers to an unknown place code")
    body = re.sub(r"\[E\d+\]|\bP\d+\b", " ", text)
    allowed = [float(x) for x in NUM_RE.findall(re.sub(r"\[E\d+\]|\bP\d+\b", " ", prompt_user))]
    for m in NUM_RE.findall(body):
        n = float(m)
        if not any(abs(n - a) < 1e-6 or (abs(n - a) <= 0.5 and "." in str(a) and round(a) == n) for a in allowed):
            issues.append(f"number {m} not in evidence")
            break
    vocab = set(re.findall(r"[A-Za-z]+", prompt_user))
    for sent in re.split(r"(?<=[.!?])\s+", body):
        for i, w in enumerate(re.findall(r"[A-Za-z][A-Za-z'\u2019]*", sent)):
            if i and w[0].isupper() and not w.isupper() and w not in vocab and w not in ALLOW_CAPS:
                issues.append(f"unfamiliar proper noun '{w}'")
                return issues
    return issues


def template_answer(act, ranked, ev, ids, codes, avoid) -> str:
    """Deterministic, fully grounded fallback (also used when the SLM is unavailable)."""
    top = ranked[0]
    s, v = top.best, top.venue
    E = ids.get(1, {})
    cite = lambda k: f" [{E[k]}]" if k in E else ""
    out = [f"Best option: {v.name}, {s.start:%a %d %b} {s.start:%H:%M}\u2013{s.end:%H:%M}, rated {s.band} ({s.score}/100){cite('weather')}."]
    if s.band in ("marginal", "avoid"):
        out.append("No slot in your window is clearly good, so treat this as the least-bad choice or widen the time range.")
    out.append(f"It is {v.dist_km:.1f} km away{cite('venue')}" + (f", about {s.travel_min} min by road at that hour{cite('travel')}." if s.travel_min else "."))
    if "geo" in E:
        out.append(f"Local surroundings and wind were checked against nearby roads and industry{cite('geo')}.")
    if len(ranked) > 1 and ranked[1].best:
        r = ranked[1]
        out.append(f"Next best: {r.venue.name} at {r.best.start:%a %H:%M} ({r.best.score}/100).")
    if avoid:
        out.append(f"Avoid {avoid[0]['label']}: {avoid[0]['reason']}.")
    return " ".join(out)
