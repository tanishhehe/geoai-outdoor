import pytest

from app import pipeline
from app.activities import ACTIVITIES, EXAMPLES
from app.scoring import in_daily
from app.slm import NullSLM
from tests import fakes
from tests.fakes import NOW


async def run(q, **kw):
    fakes.install()
    return await pipeline.answer(q, NullSLM(), now=NOW, **kw)


def test_eighteen_activities_each_with_an_example():
    assert len(ACTIVITIES) == 18 and set(EXAMPLES) == set(ACTIVITIES)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", list(ACTIVITIES))
async def test_every_activity_answers_its_example(key):
    r = await run(EXAMPLES[key])
    assert r["status"] == "ok", r
    assert r["interpretation"]["activity"] == key
    assert r["options"] and r["evidence"] and r["advice"]["carry"]


def test_wrapping_daily_hours():
    assert in_daily(23, (20, 5)) and in_daily(2, (20, 5)) and not in_daily(12, (20, 5)) and in_daily(8, (5, 10))


@pytest.mark.asyncio
async def test_stargazing_chooses_dark_hours_and_reports_moon():
    r = await run("Where can I go stargazing tomorrow night near Koregaon Park?")
    start = int(r["recommendation"]["start"][11:13])
    assert start >= 20 or start <= 3, start
    assert r["extras"]["moon_illumination_pct"] is not None
    assert any("moon" in e["text"] for e in r["evidence"])
    daytime = [h for h in r["options"][0]["hourly"] if 8 <= int(h["time"][11:13]) <= 16]
    assert not daytime                                           # daytime hours are never considered


@pytest.mark.asyncio
async def test_birdwatching_and_camping_defaults():
    r = await run("Best day for birdwatching near Koregaon Park this weekend?")
    assert 5 <= int(r["recommendation"]["start"][11:13]) <= 8 and r["interpretation"]["assumptions"]
    r = await run("Where can I go camping this weekend near Koregaon Park?")
    s, e = r["recommendation"]["start"], r["recommendation"]["end"]
    assert (int(e[8:10]) - int(s[8:10]) == 1) or int(e[8:10]) == 1      # a 12-hour overnight slot
    assert not any("Torch" in a["text"] for a in r["advice"]["carry"])  # dark is expected when camping


@pytest.mark.asyncio
async def test_swimming_likes_heat_and_badminton_hates_wind():
    from app.activities import ACTIVITIES
    from app.profiles import combine
    from app.scoring import eval_hour
    from tests.test_units import SUN, _row
    t = NOW.replace(hour=14)
    hot, mild = _row(feels=34), _row(feels=22)
    sw = ACTIVITIES["swimming"]
    assert eval_hour(sw, combine([]), t, hot, None, SUN, False, None).score > eval_hour(sw, combine([]), t, mild, None, SUN, False, None).score
    bd = ACTIVITIES["badminton"]
    calm, windy = _row(gust=8), _row(gust=30)
    assert eval_hour(bd, combine([]), t, calm, None, SUN, False, None).score > eval_hour(bd, combine([]), t, windy, None, SUN, False, None).score + 25


@pytest.mark.asyncio
async def test_typed_place_beats_gps_and_sources_have_coordinates():
    r = await run("Where can I run tomorrow near Koregaon Park?", lat=10.0, lon=10.0)
    assert r["interpretation"]["location"]["lat"] == 18.5362
    hs = [h for o in r["options"] for h in o["hourly"] if h["sources"]]
    assert hs and all("lat" in s and "lon" in s for s in hs[0]["sources"])
