"""Open-Meteo forecast + air-quality (free, no key). One multi-point call per kind keeps request volume low."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import get_settings
from .http import UpstreamError, request_json

HOURLY = ("temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,precipitation,"
          "weather_code,cloud_cover,visibility,wind_speed_10m,wind_gusts_10m,wind_direction_10m,uv_index,is_day")
AQ_HOURLY = "pm2_5,pm10,us_aqi,ozone,nitrogen_dioxide"
RENAME = {"temperature_2m": "temp", "apparent_temperature": "feels", "relative_humidity_2m": "rh",
          "precipitation_probability": "pop", "precipitation": "precip", "weather_code": "code",
          "cloud_cover": "cloud", "visibility": "vis", "wind_speed_10m": "wind", "wind_gusts_10m": "gust",
          "wind_direction_10m": "wdir", "uv_index": "uv", "is_day": "is_day",
          "pm2_5": "pm25", "pm10": "pm10", "us_aqi": "aqi", "ozone": "o3", "nitrogen_dioxide": "no2"}


async def timezone_for(lat: float, lon: float) -> str:
    s = get_settings()
    try:
        js = await request_json("GET", f"{s.open_meteo_url}/forecast", ttl=86400, params={
            "latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}", "current": "temperature_2m",
            "forecast_days": 1, "timezone": "auto"})
        return js["timezone"]
    except (UpstreamError, KeyError):
        return s.default_tz


def _listify(js):
    return js if isinstance(js, list) else [js]


def _rows(block: dict, tz: ZoneInfo, rows: dict):
    times = block.get("time", [])
    for i, ts in enumerate(times):
        t = datetime.fromisoformat(ts).replace(tzinfo=tz)
        r = rows.setdefault(t, {})
        for k, name in RENAME.items():
            if k in block:
                r[name] = block[k][i]


async def fetch_series(points: list[tuple[float, float]], days: int) -> tuple[list[dict], list[str]]:
    """Returns (per-point series, data_gaps). series = {"tz", "rows": {datetime: {...}}, "sun": {date: (sr, ss)}}."""
    s = get_settings()
    lat = ",".join(f"{p[0]:.4f}" for p in points)
    lon = ",".join(f"{p[1]:.4f}" for p in points)
    gaps: list[str] = []
    wx = await request_json("GET", f"{s.open_meteo_url}/forecast", ttl=900, params={
        "latitude": lat, "longitude": lon, "hourly": HOURLY, "daily": "sunrise,sunset", "timezone": "auto",
        "forecast_days": min(days, 16), "wind_speed_unit": "kmh"})
    wx = _listify(wx)
    aq = None
    try:
        aq = _listify(await request_json("GET", f"{s.open_meteo_aq_url}/air-quality", ttl=900, params={
            "latitude": lat, "longitude": lon, "hourly": AQ_HOURLY, "timezone": "auto",
            "forecast_days": min(days, 7)}))
    except UpstreamError as exc:
        gaps.append(f"Air-quality forecast unavailable ({exc}); AQI was not scored.")
    out = []
    for i, w in enumerate(wx):
        tz = ZoneInfo(w["timezone"])
        rows: dict = {}
        _rows(w["hourly"], tz, rows)
        if aq and i < len(aq):
            _rows(aq[i]["hourly"], tz, rows)
        sun = {}
        d = w.get("daily", {})
        for dt, sr, ss in zip(d.get("time", []), d.get("sunrise", []), d.get("sunset", [])):
            sun[date.fromisoformat(dt)] = (datetime.fromisoformat(sr).replace(tzinfo=tz),
                                           datetime.fromisoformat(ss).replace(tzinfo=tz))
        out.append({"tz": w["timezone"], "rows": rows, "sun": sun})
    if days > 7:
        gaps.append("Air-quality forecasts only reach ~5-7 days; later days were scored without AQI.")
    return out, gaps
