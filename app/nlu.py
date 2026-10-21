"""Query understanding.

Rules do the heavy lifting (fast, deterministic). The small language model is only consulted when the rules
leave a gap, and its output is *validated*: a location must literally occur in the user's text, and the
activity must be one of ours. So the SLM can never inject an invented place.
"""
import json
import re
from dataclasses import dataclass, field

from .activities import ACTIVITIES, ACTIVITY_WORDS, detect_activity
from .profiles import PROFILES, detect_profiles
from .timeparse import WEEKDAYS

MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"}
STOP = set("""today tonight tomorrow morning evening afternoon night noon weekend week weekday this next the a an on
for with within to after before during by and or please what where when which who how is are can could should would
will do does any good best safe okay ok i my we me our it its there here some around near in at of from close nearby
outside outdoors outdoor then than if but also kids kid children child parents time spot spots place places day days
hours hour km kms kilometres kilometers miles mile radius sunset sunrise party""".split()) | set(WEEKDAYS) | MONTHS | ACTIVITY_WORDS
PREPS = {"near", "around", "in", "at", "of", "from", "nearby", "by"}
TOKEN = re.compile(r"[A-Za-z0-9\u2019'.\-]+|[,?!;:()]")


@dataclass
class Parsed:
    activity: str | None = None
    location_text: str | None = None
    coords: tuple | None = None
    radius_km: float | None = None
    profiles: list = field(default_factory=list)
    mode: str = "venues"                 # venues | gonogo
    out_of_scope: bool = False
    generic_outdoor: bool = False
    slm_used: list = field(default_factory=list)


def extract_location(text: str) -> str | None:
    toks = TOKEN.findall(text)
    low = [t.lower().strip(".'\u2019-") for t in toks]
    for i, tok in enumerate(low):
        if tok not in PREPS:
            continue
        loc: list[str] = []
        j = i + 1
        while j < len(toks) and len(loc) < 6:
            w, wl = toks[j], low[j]
            if w == ",":
                nxt = toks[j + 1] if j + 1 < len(toks) else ""
                if loc and nxt[:1].isupper() and low[j + 1] not in STOP:
                    loc.append(",")
                    j += 1
                    continue
                break
            if w in "?!;:()" or wl in STOP or w[0].isdigit() or not wl:
                break
            loc.append(w.strip("."))
            j += 1
        name = " ".join(loc).replace(" ,", ",").strip(", ")
        if name:
            return name
    return None


def extract_radius(text: str) -> float | None:
    t = text.lower()
    m = (re.search(r"(?:within|up to|upto|under|radius of|around|less than)\s+(\d+(?:\.\d+)?)\s*(km|kms|kilomet\w+|miles?|mi)\b", t)
         or re.search(r"(\d+(?:\.\d+)?)\s*(km|kms|kilomet\w+|miles?|mi)\s+(?:radius|of|from|around)\b", t))
    if not m:
        return None
    v = float(m[1])
    return round(v * 1.609, 1) if m[2].startswith("mi") else v


def extract_coords(text: str):
    m = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", text)
    return (float(m[1]), float(m[2])) if m else None


def parse_rules(text: str) -> Parsed:
    t = text.lower()
    p = Parsed(activity=detect_activity(text), coords=extract_coords(text), radius_km=extract_radius(text),
               profiles=detect_profiles(text))
    p.location_text = None if p.coords else extract_location(text)
    commute = bool(re.search(r"(cycle|bike|ride|walk|run|jog)\w*\s+to\s+(work|office)|commut", t))
    asks_ok = bool(re.search(r"\b(is it|will it be|would it be)\s+(okay|ok|safe|fine|alright|good|alright)\b", t))
    wants_place = bool(re.search(r"\b(where|when|best (place|spot|park)|good (place|spot|park)|which (park|place))\b", t))
    p.mode = "gonogo" if (commute or (asks_ok and not wants_place)) else "venues"
    p.generic_outdoor = p.activity is None and bool(re.search(r"\b(outdoor|outdoors|outside|go out|fresh air)\b", t))
    return p


SLM_PROMPT = """Extract fields from the user's question about an outdoor activity.
Reply with ONE line of JSON only, no explanation:
{{"activity": <one of {acts} or "none">, "location": <text copied exactly from the question, or null>, "radius_km": <number or null>}}
Use "none" if the question is not about planning an outdoor activity.
Question: {q}"""


def slm_extract(slm, text: str) -> dict:
    """Ask the SLM to fill gaps; return only validated fields."""
    raw = slm.generate([{"role": "user", "content": SLM_PROMPT.format(acts=list(ACTIVITIES), q=text)}],
                       max_new_tokens=70)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    if d.get("activity") in ACTIVITIES or d.get("activity") == "none":
        out["activity"] = d["activity"]
    loc = d.get("location")
    if isinstance(loc, str) and loc.strip() and loc.strip().lower() in text.lower():
        out["location"] = loc.strip()           # grounding check: must appear in the user's own words
    if isinstance(d.get("radius_km"), (int, float)) and 0 < d["radius_km"] <= 100:
        out["radius_km"] = float(d["radius_km"])
    return out


def parse_query(text: str, slm=None) -> Parsed:
    p = parse_rules(text)
    if (p.activity is None or (p.location_text is None and p.coords is None)) and slm is not None:
        try:
            got = slm_extract(slm, text)
        except Exception:  # the SLM is an assistant here, never a single point of failure
            got = {}
        if got:
            p.slm_used.append("query-parsing")
            if p.activity is None and got.get("activity") in ACTIVITIES:
                p.activity = got["activity"]
            if p.activity is None and got.get("activity") == "none" and not p.generic_outdoor:
                p.out_of_scope = True
            if p.location_text is None and p.coords is None and got.get("location"):
                p.location_text = got["location"]
            if p.radius_km is None and got.get("radius_km"):
                p.radius_km = got["radius_km"]
    if p.activity is None and not p.generic_outdoor:
        p.out_of_scope = True
    return p
