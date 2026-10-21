"""OpenStreetMap via the Overpass API: candidate venues for an activity + geospatial context around them."""
from dataclasses import dataclass, field

from .activities import Activity
from .config import get_settings
from .geo import bearing_deg, haversine_km
from .http import UpstreamError, request_json


@dataclass
class Venue:
    id: str
    name: str
    lat: float
    lon: float
    kind: str
    lit: bool = False
    osm_url: str = ""
    dist_km: float = 0.0
    travel_free_min: float | None = None
    travel_km: float | None = None
    travel_method: str = ""
    elevation_m: float | None = None


@dataclass
class Source:
    kind: str            # traffic | industry
    label: str
    strength: float
    dist_m: float
    bearing: float       # from venue towards the source
    lat: float | None = None
    lon: float | None = None


@dataclass
class VenueContext:
    sources: list = field(default_factory=list)
    n_green: int = 0
    water_m: float | None = None
    power_line: bool = False

    @property
    def green_idx(self) -> float:
        return min(1.0, self.n_green / 3)


async def _overpass(query: str, ttl: float = 1800):
    last = None
    for url in get_settings().overpass_urls:
        try:
            js = await request_json("POST", url, data={"data": query}, ttl=ttl, retries=0)
            return js.get("elements", [])
        except UpstreamError as exc:
            last = exc
    raise UpstreamError(f"all Overpass endpoints failed: {last}")


def _center(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else (None, None)


def _kind(tags: dict) -> str:
    for k in ("sport", "leisure", "natural", "tourism", "amenity", "historic", "man_made", "boundary", "highway"):
        if k in tags:
            return f"{k}={tags[k]}"
    return "place"


async def find_venues(act: Activity, lat: float, lon: float, radius_km: float, limit: int) -> list[Venue]:
    r = int(radius_km * 1000)
    parts = "".join(f"nwr{sel}(around:{r},{lat:.5f},{lon:.5f});" for sel in act.osm)
    elements = await _overpass(f"[out:json][timeout:30];({parts});out center tags 150;")
    cands: list[tuple[float, Venue]] = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        la, lo = _center(el)
        if not name or la is None:
            continue
        d = haversine_km(lat, lon, la, lo)
        v = Venue(id=f"{el['type']}/{el['id']}", name=name, lat=la, lon=lo, kind=_kind(tags),
                  lit=tags.get("lit") == "yes", osm_url=f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
                  dist_km=round(d, 2))
        notable = 0.5 if (tags.get("website") or tags.get("wikidata")) else 0.0
        cands.append((d - notable, v))
    cands.sort(key=lambda x: x[0])
    picked: list[Venue] = []
    for _, v in cands:
        if any(p.name.casefold() == v.name.casefold() and haversine_km(p.lat, p.lon, v.lat, v.lon) < 1.0
               or haversine_km(p.lat, p.lon, v.lat, v.lon) < 0.15 for p in picked):
            continue
        picked.append(v)
        if len(picked) >= limit:
            break
    return picked


HIGHWAY = {"motorway": 1.0, "trunk": .85, "primary": .6, "secondary": .35}
RADII = {"traffic": 1500, "industry": 3000, "water": 500, "green": 300, "line": 300}


def _classify(tags: dict):
    hw = tags.get("highway")
    if hw in HIGHWAY:
        label = {"motorway": "expressway/motorway", "trunk": "trunk road", "primary": "major road",
                 "secondary": "busy road"}[hw]
        return "traffic", HIGHWAY[hw], f"{label}{' ' + tags['ref'] if tags.get('ref') else ''}", tags.get("ref") or tags.get("name") or hw
    if tags.get("power") == "plant":
        return "industry", 1.0, "power plant", None
    if tags.get("landuse") == "industrial":
        return "industry", 1.0, "industrial area", None
    if tags.get("man_made") == "works":
        return "industry", .9, "factory/works", None
    if tags.get("landuse") == "landfill":
        return "industry", .8, "landfill", None
    if tags.get("natural") in ("water", "coastline") or tags.get("waterway") in ("river", "canal"):
        return "water", 1.0, "water body", None
    if tags.get("power") == "line":
        return "line", 0.0, "power line", None
    if (tags.get("leisure") in ("park", "garden", "nature_reserve")
            or tags.get("landuse") in ("forest", "grass", "meadow", "recreation_ground", "village_green")
            or tags.get("natural") in ("wood", "scrub", "grassland")):
        return "green", 0.0, "green space", None
    return None


def _context_query(venues: list[Venue]) -> str:
    q = []
    for v in venues:
        a = lambda r: f"(around:{r},{v.lat:.5f},{v.lon:.5f})"
        q += [f'way["highway"~"^(motorway|trunk|primary)$"]{a(1500)};', f'way["highway"="secondary"]{a(600)};',
              f'nwr["landuse"="industrial"]{a(3000)};', f'nwr["man_made"="works"]{a(3000)};',
              f'nwr["power"="plant"]{a(4000)};', f'nwr["landuse"="landfill"]{a(4000)};',
              f'nwr["natural"="water"]{a(500)};', f'way["waterway"~"^(river|canal)$"]{a(500)};',
              f'way["natural"="coastline"]{a(500)};',
              f'nwr["leisure"~"^(park|garden|nature_reserve)$"]{a(300)};',
              f'nwr["landuse"~"^(forest|grass|meadow|recreation_ground|village_green)$"]{a(300)};',
              f'nwr["natural"~"^(wood|scrub|grassland)$"]{a(300)};', f'way["power"="line"]{a(300)};']
    return "[out:json][timeout:45];(" + "".join(q) + ");out center tags qt;"


async def fetch_context(venues: list[Venue]) -> dict[str, VenueContext]:
    elements = await _overpass(_context_query(venues), ttl=3600)
    classified = []
    for el in elements:
        tags = el.get("tags", {})
        c = _classify(tags)
        la, lo = _center(el)
        if c and la is not None:
            classified.append((el, c, la, lo))
    out: dict[str, VenueContext] = {}
    for v in venues:
        ctx = VenueContext()
        roads: dict = {}
        seen_green = set()
        for el, (kind, strength, label, key), la, lo in classified:
            d = haversine_km(v.lat, v.lon, la, lo) * 1000
            if d > RADII[kind] or (kind in ("traffic",) and d > (600 if strength < .5 else 1500)):
                continue
            if v.lat == la and v.lon == lo and kind == "green" and el["id"] == int(v.id.split("/")[1]):
                continue  # the venue itself is not its own green cover
            if kind == "traffic":
                if key not in roads or d < roads[key].dist_m:
                    roads[key] = Source(kind, label, strength, d, bearing_deg(v.lat, v.lon, la, lo), la, lo)
            elif kind == "industry":
                ctx.sources.append(Source(kind, label, strength, d, bearing_deg(v.lat, v.lon, la, lo), la, lo))
            elif kind == "water":
                ctx.water_m = d if ctx.water_m is None else min(ctx.water_m, d)
            elif kind == "green":
                seen_green.add(el["id"])
            elif kind == "line":
                ctx.power_line = True
        ctx.sources += list(roads.values())
        ctx.n_green = len(seen_green)
        out[v.id] = ctx
    return out


async def fetch_elevation(venues: list[Venue]) -> None:
    s = get_settings()
    try:
        js = await request_json("GET", f"{s.open_meteo_url}/elevation", ttl=86400, params={
            "latitude": ",".join(f"{v.lat:.4f}" for v in venues),
            "longitude": ",".join(f"{v.lon:.4f}" for v in venues)})
        for v, e in zip(venues, js.get("elevation", [])):
            v.elevation_m = e
    except UpstreamError:
        pass
