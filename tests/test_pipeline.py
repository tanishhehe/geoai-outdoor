import pytest

from app import pipeline
from app.slm import NullSLM
from tests import fakes
from tests.fakes import NOW, FakeSLM

Q = "Where can I go running tomorrow evening near Koregaon Park?"


async def run(q, slm=None, **kw):
    fakes.install(**kw.pop("fake", {}))
    return await pipeline.answer(q, slm or NullSLM(), now=NOW, **kw)


@pytest.mark.asyncio
async def test_end_to_end_ok_with_template():
    r = await run(Q)
    assert r["status"] == "ok" and r["meta"]["narrative_source"] == "template"
    assert r["interpretation"]["activity"] == "running" and r["interpretation"]["window"]["timezone"] == "Asia/Kolkata"
    opts = r["options"]
    assert 1 <= len(opts) <= 3 and opts[0]["best_window"]["score"] >= opts[-1]["best_window"]["score"]
    assert all("Far Hill" not in o["venue"]["name"] for o in opts[:1])          # 9 km away + park out of the 5 km radius
    ids = {e["id"] for e in r["evidence"]}
    assert {"E1", "E2"} <= ids and all(any(e["kind"] == k for e in r["evidence"]) for k in ("venue", "weather", "air", "geo"))
    cited = {i for k in ("carry", "watch") for a in r["advice"][k] for i in a["evidence"]}
    assert cited <= ids
    assert "OpenStreetMap contributors" in r["attribution"] and r["markdown"]


@pytest.mark.asyncio
async def test_wind_and_rush_hour_shape_the_choice():
    """Osho Teerth Park has a motorway upwind (wind from W) until 15:00; the hour-by-hour exposure must flip."""
    r = await run("Where can I go running tomorrow near Koregaon Park?")
    osho = next(o for o in r["options"] if "Osho" in o["venue"]["name"])
    h = {x["time"][11:13]: x for x in osho["hourly"]}
    assert h["08"]["exposure"] > h["18"]["exposure"] + 0.2          # upwind motorway at rush hour vs downwind in the evening
    assert h["08"]["aqi_effective"] > h["08"]["aqi_model"] and h["18"]["score"] > h["08"]["score"]
    assert int(r["recommendation"]["start"][11:13]) >= 15 or r["recommendation"]["venue"] != "Osho Teerth Park"


@pytest.mark.asyncio
async def test_asthma_is_stricter_than_adult():
    a = await run("Where can I go for a run tomorrow morning near Koregaon Park?")
    b = await run("I have asthma, where can I go for a run tomorrow morning near Koregaon Park?")
    assert b["recommendation"]["score"] < a["recommendation"]["score"]
    assert any("inhaler" in x["text"] for x in b["advice"]["carry"])


@pytest.mark.asyncio
async def test_verified_slm_narrative_is_used():
    def reply(messages):
        u = messages[1]["content"]
        assert "P1" in u and "Osho" not in u and "Empress" not in u           # the model only ever sees place codes
        return "I recommend P1 at 17:00 because rain chance stays low [E3] and the air is cleaner then [E4]."
    r = await run(Q, FakeSLM(reply))
    assert r["meta"]["narrative_source"] == "slm" and "P1" not in r["answer"]
    assert r["recommendation"]["venue"] in r["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    "Go to Taj Mahal Gardens at 17:00 where it is lovely [E1].",                       # invented place
    "Go to P1, it will be 41 degrees with 99 percent rain [E3].",                      # invented numbers
    "Go to P1 for a great run, it is wonderful.",                                      # no citations
    "Go to P1 [E99] it is nice at 17:00 here for the evening run and the weather.",    # fake evidence id
])
async def test_hallucinated_narrative_is_rejected(bad):
    r = await run(Q, FakeSLM(bad))
    assert r["meta"]["narrative_source"] == "template" and r["meta"]["verification_issues"]


@pytest.mark.asyncio
async def test_clarifications_and_scope():
    r = await run("Is it okay to cycle to work at 8 AM?")
    assert r["status"] == "needs_clarification" and r["missing"] == ["location"]
    r = await run("What is the capital of France?")
    assert r["status"] == "out_of_scope"
    r = await run("running near Atlantis tomorrow")
    assert r["status"] == "needs_clarification" and "couldn't find" in r["message"]
    r = await run("I want to go outside tomorrow in Pune")
    assert r["status"] == "needs_clarification" and r["missing"] == ["activity"]


@pytest.mark.asyncio
async def test_commute_go_no_go_and_lat_lon():
    r = await run("Is it okay to cycle to work at 8 AM?", lat=18.5362, lon=73.894)
    assert r["status"] == "ok" and r["interpretation"]["mode"] == "gonogo"
    assert r["recommendation"]["focus_verdict"]["band"] in ("great", "good", "marginal", "avoid")


@pytest.mark.asyncio
async def test_weekend_compare_and_photography_sunset():
    r = await run("Is Saturday or Sunday better for a hike near Lonavala?")
    assert r["status"] == "ok" and len(r["day_summary"]) == 2
    r = await run("Where can I take sunset photos this evening around Bandra?")
    assert r["status"] == "ok"
    start = r["recommendation"]["start"]
    assert start[11:13] in ("17", "18"), start        # sunset 18:05 -> golden-hour start


@pytest.mark.asyncio
async def test_graceful_degradation_never_invents_data():
    r = await run(Q, fake={"fail": ("open-meteo.com",)})
    assert r["status"] == "data_unavailable" and "won't guess" in r["message"]
    r = await run(Q, fake={"fail": ("overpass",)})
    assert r["status"] == "data_unavailable"
    r = await run(Q, fake={"fail": ("air-quality",)})        # AQ missing: still answers, says so
    assert r["status"] == "ok" and any("Air-quality" in g for g in r["data_gaps"])
    r = await run(Q, fake={"fail": ("osrm",)})
    assert r["status"] == "ok" and any("routing" in g.lower() for g in r["data_gaps"])
