"""Deterministic fake upstreams (Nominatim, Overpass, Open-Meteo, OSRM) behind httpx.MockTransport."""
import json
import math
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 21, 10, 30, tzinfo=TZ)
CENTER = (18.5362, 73.8940)   # "Koregaon Park"
M = 1 / 111_000               # one metre in degrees latitude

PARKS = [  # name, lat, lon
    ("Osho Teerth Park", 18.5400, 73.8960), ("Riverfront Track", 18.5300, 73.9100),
    ("Empress Garden", 18.5180, 73.8780), ("Far Hill Park", 18.6000, 73.8000)]


def _hourly(i, days, extra=None):
    base = NOW.replace(hour=0, minute=0)
    times, d = [], {k: [] for k in ["temperature_2m", "apparent_temperature", "relative_humidity_2m", "precipitation_probability",
                                    "precipitation", "weather_code", "cloud_cover", "visibility", "wind_speed_10m",
                                    "wind_gusts_10m", "wind_direction_10m", "uv_index", "is_day"]}
    for h in range(days * 24):
        t = base + timedelta(hours=h)
        hr = t.hour
        temp = 24 + 8 * math.sin(math.pi * (hr - 8) / 12) if 8 <= hr <= 20 else 22 - (0.3 if hr < 8 else 0.5 * (hr - 20))
        times.append(t.strftime("%Y-%m-%dT%H:%M"))
        d["temperature_2m"].append(round(temp, 1)); d["apparent_temperature"].append(round(temp + 2, 1))
        d["relative_humidity_2m"].append(55); d["precipitation_probability"].append(10)
        d["precipitation"].append(0.0); d["weather_code"].append(1); d["cloud_cover"].append(25)
        d["visibility"].append(10000); d["wind_speed_10m"].append(11); d["wind_gusts_10m"].append(19)
        d["wind_direction_10m"].append(270 if hr < 15 else 90)      # wind shifts from W to E in the afternoon
        d["uv_index"].append(round(max(0, 9 * math.sin(math.pi * (hr - 6) / 12)), 1) if 6 <= hr <= 18 else 0)
        d["is_day"].append(1 if 6 <= hr < 18 else 0)
    d["time"] = times
    if extra:
        extra(d)
    return d


def _aq(days):
    base = NOW.replace(hour=0, minute=0)
    times = [(base + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(days * 24)]
    aqi = [130 if 7 <= (h % 24) <= 10 else 95 if 11 <= (h % 24) <= 16 else 70 for h in range(days * 24)]
    return {"time": times, "pm2_5": [a * .5 for a in aqi], "pm10": [a * .9 for a in aqi], "us_aqi": aqi,
            "ozone": [40] * len(aqi), "nitrogen_dioxide": [20] * len(aqi)}


def _daily(days):
    d0 = NOW.date()
    ds = [(d0 + timedelta(days=i)) for i in range(days)]
    return {"time": [x.isoformat() for x in ds], "sunrise": [f"{x}T06:20" for x in ds], "sunset": [f"{x}T18:05" for x in ds]}


def context_elements():
    c = CENTER
    return [
        {"type": "way", "id": 9001, "center": {"lat": 18.5400, "lon": 73.8960 - 450 * M * 1.05}, "tags": {"highway": "motorway", "ref": "NH48"}},
        {"type": "way", "id": 9002, "center": {"lat": 18.5300 + 900 * M, "lon": 73.9100 + 900 * M}, "tags": {"landuse": "industrial"}},
        {"type": "way", "id": 9003, "center": {"lat": 18.5180, "lon": 73.8790}, "tags": {"leisure": "park"}},
        {"type": "way", "id": 9004, "center": {"lat": 18.5185, "lon": 73.8775}, "tags": {"landuse": "grass"}},
        {"type": "way", "id": 9005, "center": {"lat": 18.5176, "lon": 73.8785}, "tags": {"natural": "wood"}},
        {"type": "way", "id": 9006, "center": {"lat": 18.5300, "lon": 73.9105}, "tags": {"waterway": "river"}},
    ]


def make_transport(*, fail=(), calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        host = req.url.host
        if calls is not None:
            calls.append(host)
        if any(f in host for f in fail):
            return httpx.Response(500, json={"error": "boom"})
        q = dict(urllib.parse.parse_qsl(req.url.query.decode()))
        if "nominatim" in host:
            name = q.get("q", "")
            if "atlantis" in name.lower():
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"lat": str(CENTER[0]), "lon": str(CENTER[1]), "display_name": name + ", Pune, India"}])
        if "overpass" in host:
            data = urllib.parse.parse_qs(req.content.decode())["data"][0]
            if "out center tags 150" in data:
                els = [{"type": "way", "id": 100 + i, "center": {"lat": la, "lon": lo},
                        "tags": {"name": n, "leisure": "park", **({"lit": "yes"} if i == 0 else {})}} for i, (n, la, lo) in enumerate(PARKS)]
                return httpx.Response(200, json={"elements": els})
            return httpx.Response(200, json={"elements": context_elements()})
        if "air-quality" in host:
            n = len(q["latitude"].split(","))
            days = int(q["forecast_days"])
            out = [{"timezone": "Asia/Kolkata", "hourly": _aq(days)} for _ in range(n)]
            return httpx.Response(200, json=out if n > 1 else out[0])
        if "open-meteo" in host and url.split("?")[0].endswith("/elevation"):
            n = len(q["latitude"].split(","))
            return httpx.Response(200, json={"elevation": [560.0 + 40 * i for i in range(n)]})
        if "open-meteo" in host:
            if "current" in q:
                return httpx.Response(200, json={"timezone": "Asia/Kolkata", "current": {"temperature_2m": 28}})
            n = len(q["latitude"].split(","))
            days = int(q["forecast_days"])
            out = [{"timezone": "Asia/Kolkata", "hourly": _hourly(i, days), "daily": _daily(days)} for i in range(n)]
            return httpx.Response(200, json=out if n > 1 else out[0])
        if "osrm" in host:
            n = url.split("/driving/")[1].split("?")[0].count(";") + 1
            return httpx.Response(200, json={"durations": [[0] + [300 + 400 * i for i in range(n - 1)]],
                                             "distances": [[0] + [2500 + 3000 * i for i in range(n - 1)]]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def install(**kw):
    from app import http
    http.clear_cache()
    http.set_client(httpx.AsyncClient(transport=make_transport(**kw), headers={"User-Agent": "tests"}))


class FakeSLM:
    available = True
    model_id = "fake/slm"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def generate(self, messages, max_new_tokens=None):
        self.calls.append(messages)
        r = self.reply(messages) if callable(self.reply) else self.reply
        return r
