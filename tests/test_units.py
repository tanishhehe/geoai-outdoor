from datetime import datetime, timedelta

import pytest

from app import nlu
from app.activities import ACTIVITIES
from app.geo import angdiff, bearing_deg, compass
from app.geo_context import exposure
from app.overpass import Source, VenueContext
from app.profiles import combine
from app.scoring import eval_hour
from app.timeparse import TimeError, parse_time
from tests.fakes import NOW

EXAMPLES = [  # question -> (activity, location, radius, profiles, mode)
    ("Where can I go running tomorrow evening near Koregaon Park?", "running", "Koregaon Park", None, [], "venues"),
    ("Best time this weekend for a kids' cricket match within 15 km of Whitefield?", "cricket", "Whitefield", 15, ["child"], "venues"),
    ("I have mild asthma, where's good for a morning walk near Powai in the next two days?", "walking", "Powai", None, ["asthma"], "venues"),
    ("Is it okay to cycle to work at 8 AM near Hinjewadi?", "cycling", "Hinjewadi", None, [], "gonogo"),
    ("Planning an outdoor birthday party on Sunday afternoon in Pune, what should I keep in mind?", "event", "Pune", None, [], "venues"),
    ("Good place and time for golf on Saturday within 40 km of Andheri?", "golf", "Andheri", 40, [], "venues"),
    ("Where can I take sunset photos this evening around Bandra?", "photography", "Bandra", None, [], "venues"),
    ("Is Saturday or Sunday better for a hike near Lonavala?", "hiking", "Lonavala", None, [], "venues"),
    ("When is it safe for my parents to walk outdoors tomorrow in Bengaluru?", "walking", "Bengaluru", None, ["senior"], "venues"),
    ("Outdoor tennis after work today near Hinjewadi, any good spots?", "tennis", "Hinjewadi", None, [], "venues"),
    ("running near koregaon park tomorrow", "running", "koregaon park", None, [], "venues"),
]


@pytest.mark.parametrize("q,act,loc,rad,prof,mode", EXAMPLES)
def test_rule_parser(q, act, loc, rad, prof, mode):
    p = nlu.parse_rules(q)
    assert (p.activity, p.location_text, p.radius_km, p.profiles, p.mode) == (act, loc, rad, prof, mode)


def test_missing_location_and_out_of_scope():
    assert nlu.parse_rules("Is it okay to cycle to work at 8 AM?").location_text is None
    assert nlu.parse_query("what is the capital of France").out_of_scope
    assert nlu.parse_rules("I want to go outside tomorrow in Pune").generic_outdoor


class FakeSlm:
    available = True

    def __init__(self, out):
        self.out = out

    def generate(self, m, max_new_tokens=None):
        return self.out


def test_slm_extraction_is_grounded():
    # SLM proposes a place that is NOT in the user's text -> rejected (no invented places)
    p = nlu.parse_query("somewhere to jog tomorrow", FakeSlm('{"activity":"running","location":"Eiffel Tower","radius_km":null}'))
    assert p.activity == "running" and p.location_text is None
    # a place that does occur in the text is accepted
    p = nlu.parse_query("jog at Lodhi Garden tomorrow".replace("at ", "~ "), FakeSlm('{"activity":"running","location":"Lodhi Garden","radius_km":null}'))
    assert p.location_text == "Lodhi Garden"


def test_time_windows():
    w = parse_time("running tomorrow evening", NOW)
    assert (w.start.day, w.start.hour, w.end.hour) == (22, 16, 21)
    w = parse_time("this weekend", NOW)
    assert (w.start.day, w.end.day) == (24, 25) and w.compare_days
    w = parse_time("cycle at 8 AM", NOW)
    assert w.focus.hour == 8 and w.focus.day == 22 and w.assumptions
    w = parse_time("sunset photos this evening", NOW)
    assert w.goal == "sunset"
    w = parse_time("morning walk in the next two days", NOW)
    assert w.daily_hours == (5, 11)
    late = parse_time("tonight", NOW.replace(hour=23, minute=59))       # part of day already over -> tomorrow, said out loud
    assert late.start.day == 22 and any("already passed" in a for a in late.assumptions)


def test_geometry():
    assert angdiff(350, 10) == 20 and compass(270) == "W"
    assert abs(bearing_deg(18.5, 73.9, 18.6, 73.9)) < 1


def test_exposure_depends_on_wind_and_hour():
    ctx = VenueContext(sources=[Source("traffic", "expressway", 1.0, 500, 270.0)])   # source lies due west
    up, _ = exposure(ctx, 270, 12, 8)      # wind FROM the west -> upwind, rush hour
    down, _ = exposure(ctx, 90, 12, 8)     # wind from the east -> downwind
    night, _ = exposure(ctx, 270, 12, 2)   # same wind, no traffic
    assert up > down * 2 and up > night * 2


def _row(**kw):
    r = dict(temp=26, feels=28, pop=5, precip=0, wind=10, gust=18, wdir=90, uv=3, cloud=20, aqi=50, code=1, is_day=1)
    r.update(kw)
    return r


SUN = (NOW.replace(hour=6, minute=20), NOW.replace(hour=18, minute=5))


def test_profile_tightens_limits():
    act = ACTIVITIES["running"]
    t = NOW.replace(hour=17, minute=0)
    adult = eval_hour(act, combine([]), t, _row(aqi=100), None, SUN, False, None)
    asthma = eval_hour(act, combine(["asthma"]), t, _row(aqi=100), None, SUN, False, None)
    assert asthma.risks["aqi"] > adult.risks["aqi"] and asthma.score < adult.score
    senior_heat = eval_hour(act, combine(["senior"]), t, _row(feels=29), None, SUN, False, None)
    adult_heat = eval_hour(act, combine([]), t, _row(feels=29), None, SUN, False, None)
    assert senior_heat.score < adult_heat.score


def test_vetoes():
    act = ACTIVITIES["golf"]
    assert "thunderstorm forecast" in eval_hour(act, combine([]), NOW.replace(hour=11), _row(code=95), None, SUN, False, None).vetoes
    dark = eval_hour(act, combine([]), NOW.replace(hour=21), _row(is_day=0), None, SUN, False, None)
    assert "too dark" in dark.vetoes and dark.score <= 25
    lit = eval_hour(ACTIVITIES["football"], combine([]), NOW.replace(hour=21), _row(is_day=0), None, SUN, True, None)
    unlit = eval_hour(ACTIVITIES["football"], combine([]), NOW.replace(hour=21), _row(is_day=0), None, SUN, False, None)
    assert lit.score > unlit.score


def test_sunset_photography_prefers_golden_hour():
    act = ACTIVITIES["photography"]
    golden = eval_hour(act, combine([]), NOW.replace(hour=17), _row(), None, SUN, False, "sunset")
    noon = eval_hour(act, combine([]), NOW.replace(hour=12), _row(), None, SUN, False, "sunset")
    assert golden.score > noon.score + 20
