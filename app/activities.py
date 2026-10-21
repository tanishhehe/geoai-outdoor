"""Activity catalogue: what each activity is sensitive to, and which OSM features are venues for it.

Thresholds are (good, bad) pairs: risk 0 at/below `good`, 1 at/above `bad` (linear between).
Units follow Open-Meteo defaults: degC, km/h, %, US AQI, UV index.
These are transparent, editable heuristics, not medical or sporting standards.
"""
import re
from dataclasses import dataclass, field

BASE_W = dict(heat=.25, cold=.12, rain=.25, wind=.12, aqi=.22, uv=.08, light=.25, cloud=0.0, moon=0.0, travel=.10)


@dataclass(frozen=True)
class Activity:
    key: str
    label: str
    pattern: str                 # regex used by the rule-based parser
    osm: tuple                   # Overpass selectors that define candidate venues
    radius_km: float             # default search radius
    duration_h: int
    heat: tuple                  # apparent temperature (good, bad) degC
    cold: tuple                  # apparent temperature: no cold risk above good, full risk at/below bad
    gust: tuple
    pop: tuple                   # precipitation probability %
    aqi: tuple
    uv: tuple
    dark_risk: float             # risk if it is dark (0..1) unless the venue is lit
    travel_ok_min: int           # travel time people accept without complaint
    w: dict = field(default_factory=dict)  # weight overrides
    default_hours: tuple | None = None   # focus hours when the user gives no time of day (h0 > h1 wraps midnight)

    def weights(self) -> dict:
        return {**BASE_W, **self.w}


def _a(**kw) -> Activity:
    return Activity(**kw)


ACTIVITIES: dict[str, Activity] = {a.key: a for a in [
    _a(key="running", label="Running or jogging",
       pattern=r"\b(run|runs|running|jog|jogging|jogger|marathon|5k|10k)\b",
       osm=('["leisure"="park"]', '["leisure"="track"]', '["leisure"="nature_reserve"]',
            '["leisure"="stadium"]["sport"~"athletics"]'),
       radius_km=5, duration_h=1, heat=(22, 33), cold=(6, -6), gust=(28, 55), pop=(30, 70),
       aqi=(55, 130), uv=(6, 9), dark_risk=.5, travel_ok_min=15),
    _a(key="cycling", label="Cycling (leisure or commute)",
       pattern=r"\b(cycle|cycling|cyclist|bike|biking|bicycle|bicycling)\b",
       osm=('["leisure"="park"]', '["highway"="cycleway"]', '["sport"="cycling"]'),
       radius_km=10, duration_h=2, heat=(24, 35), cold=(8, -1), gust=(25, 45), pop=(25, 60),
       aqi=(65, 140), uv=(7, 10), dark_risk=.6, travel_ok_min=20),
    _a(key="golf", label="Golf", pattern=r"\bgolf\b", osm=('["leisure"="golf_course"]',),
       radius_km=25, duration_h=4, heat=(30, 38), cold=(12, 3), gust=(25, 45), pop=(20, 55),
       aqi=(100, 170), uv=(7, 10), dark_risk=1.0, travel_ok_min=45, w=dict(rain=.3)),
    _a(key="cricket", label="Cricket (recreational match or practice)", pattern=r"\bcricket\b",
       osm=('["sport"="cricket"]',), radius_km=10, duration_h=3, heat=(30, 38), cold=(10, 2),
       gust=(30, 55), pop=(20, 55), aqi=(90, 150), uv=(8, 11), dark_risk=1.0, travel_ok_min=30,
       w=dict(rain=.3)),
    _a(key="football", label="Outdoor football or five-a-side",
       pattern=r"\b(football|footy|soccer|futsal|five[- ]a[- ]side|5[- ]a[- ]side|5v5)\b",
       osm=('["sport"~"^(soccer|football|futsal)$"]',), radius_km=8, duration_h=2, heat=(28, 36),
       cold=(8, 0), gust=(35, 60), pop=(35, 70), aqi=(75, 140), uv=(7, 10), dark_risk=.7,
       travel_ok_min=25),
    _a(key="tennis", label="Outdoor tennis", pattern=r"\btennis\b", osm=('["sport"="tennis"]',),
       radius_km=8, duration_h=2, heat=(30, 38), cold=(10, 2), gust=(20, 38), pop=(25, 60),
       aqi=(90, 150), uv=(8, 11), dark_risk=.8, travel_ok_min=25),
    _a(key="hiking", label="Hiking or a nature walk",
       pattern=r"\b(hike|hiking|hikes|trek|trekking|trail|nature walk|hill walk)\b",
       osm=('["natural"="peak"]', '["leisure"="nature_reserve"]', '["tourism"="viewpoint"]',
            '["boundary"="protected_area"]'),
       radius_km=40, duration_h=4, heat=(27, 35), cold=(4, -6), gust=(35, 60), pop=(25, 60),
       aqi=(90, 150), uv=(7, 10), dark_risk=1.0, travel_ok_min=75, w=dict(rain=.3, light=.3)),
    _a(key="picnic", label="Picnic or park outing",
       pattern=r"\b(picnic|picnics|park outing|family outing|outing)\b",
       osm=('["tourism"="picnic_site"]', '["leisure"="park"]', '["leisure"="garden"]',
            '["leisure"="nature_reserve"]'),
       radius_km=15, duration_h=3, heat=(30, 37), cold=(12, 4), gust=(30, 50), pop=(15, 50),
       aqi=(100, 150), uv=(8, 11), dark_risk=1.0, travel_ok_min=40, w=dict(rain=.3)),
    _a(key="event", label="Outdoor event or gathering",
       pattern=r"\b(wedding|fair|mela|event|gathering|party|birthday|reception|festival|barbecue|bbq|function|ceremony)\b",
       osm=('["amenity"="events_venue"]', '["amenity"="community_centre"]', '["leisure"="garden"]',
            '["leisure"="park"]'),
       radius_km=15, duration_h=4, heat=(31, 38), cold=(12, 5), gust=(25, 45), pop=(10, 45),
       aqi=(110, 170), uv=(9, 11), dark_risk=.25, travel_ok_min=40, w=dict(rain=.35, wind=.15)),
    _a(key="photography", label="Outdoor photography session",
       pattern=r"\b(photo|photos|photograph|photography|photoshoot|photo ?shoot|golden hour|shoot)\b",
       osm=('["tourism"="viewpoint"]', '["natural"="beach"]', '["natural"="peak"]', '["leisure"="park"]',
            '["historic"~"^(monument|castle|fort|memorial)$"]', '["man_made"="lighthouse"]'),
       radius_km=20, duration_h=2, heat=(34, 42), cold=(0, -8), gust=(40, 70), pop=(40, 80),
       aqi=(150, 250), uv=(9, 12), dark_risk=1.0, travel_ok_min=45,
       w=dict(cloud=.2, light=.3, aqi=.10, heat=.10, rain=.12)),
    _a(key="walking", label="Walking (park or neighbourhood)",
       pattern=r"\b(walk|walks|walking|stroll|promenade)\b",
       osm=('["leisure"="park"]', '["leisure"="garden"]', '["leisure"="nature_reserve"]',
            '["leisure"="track"]'),
       radius_km=4, duration_h=1, heat=(28, 36), cold=(8, 0), gust=(35, 60), pop=(30, 70),
       aqi=(70, 150), uv=(6, 9), dark_risk=.8, travel_ok_min=15),
    _a(key="badminton", label="Outdoor badminton", pattern=r"\b(badminton|shuttlecock)\b", osm=('["sport"="badminton"]',),
       radius_km=6, duration_h=2, heat=(30, 38), cold=(10, 3), gust=(10, 22), pop=(20, 55), aqi=(80, 140),
       uv=(8, 11), dark_risk=.8, travel_ok_min=25, w=dict(wind=.3)),
    _a(key="basketball", label="Outdoor basketball", pattern=r"\b(basketball|hoops)\b", osm=('["sport"="basketball"]',),
       radius_km=8, duration_h=2, heat=(28, 36), cold=(8, 0), gust=(35, 60), pop=(30, 65), aqi=(75, 140),
       uv=(7, 10), dark_risk=.7, travel_ok_min=25),
    _a(key="swimming", label="Outdoor swimming", pattern=r"\b(swim|swimming|swimmer|laps)\b",
       osm=('["leisure"="swimming_pool"]["access"!~"^(private|no)$"]', '["leisure"="water_park"]'),
       radius_km=10, duration_h=2, heat=(37, 43), cold=(27, 19), gust=(35, 60), pop=(35, 75), aqi=(100, 170),
       uv=(7, 10), dark_risk=.8, travel_ok_min=25, w=dict(cold=.3, heat=.12, uv=.12)),
    _a(key="yoga", label="Outdoor yoga or workout",
       pattern=r"\b(yoga|workout|work out|calisthenics|outdoor gym|zumba|aerobics|pilates|tai chi|stretching)\b",
       osm=('["leisure"="park"]', '["leisure"="garden"]', '["leisure"="fitness_station"]'),
       radius_km=4, duration_h=1, heat=(24, 34), cold=(10, 2), gust=(35, 60), pop=(30, 70), aqi=(50, 110),
       uv=(6, 9), dark_risk=.6, travel_ok_min=15),
    _a(key="camping", label="Camping", pattern=r"\b(camp|camping|campsite|campfire|glamping|tent)\b",
       osm=('["tourism"="camp_site"]', '["tourism"="caravan_site"]'), radius_km=50, duration_h=12,
       heat=(32, 40), cold=(14, 5), gust=(30, 50), pop=(15, 45), aqi=(100, 160), uv=(8, 11), dark_risk=0.0,
       travel_ok_min=120, default_hours=(15, 20), w=dict(rain=.3, cold=.2, wind=.15, uv=.03, travel=.06)),
    _a(key="stargazing", label="Stargazing",
       pattern=r"\b(star ?gazing|stargaz\w*|milky way|astro\w*|night sky|meteor shower|telescope)\b",
       osm=('["tourism"="viewpoint"]', '["natural"="peak"]', '["leisure"="nature_reserve"]', '["leisure"="park"]'),
       radius_km=40, duration_h=3, heat=(34, 42), cold=(12, 4), gust=(40, 70), pop=(20, 50), aqi=(70, 140),
       uv=(99, 100), dark_risk=1.0, travel_ok_min=60, default_hours=(20, 5),
       w=dict(cloud=.35, moon=.15, light=.3, aqi=.15, heat=.05, wind=.05, uv=0.0, rain=.25, travel=.08)),
    _a(key="birdwatching", label="Birdwatching", pattern=r"\b(bird ?watch\w*|birding|ornitholog\w*)\b",
       osm=('["leisure"="nature_reserve"]', '["natural"="wetland"]', '["leisure"="bird_hide"]', '["leisure"="park"]'),
       radius_km=25, duration_h=3, heat=(28, 36), cold=(8, 0), gust=(20, 40), pop=(25, 60), aqi=(90, 150),
       uv=(8, 11), dark_risk=1.0, travel_ok_min=45, default_hours=(5, 10), w=dict(wind=.2, light=.2)),
]}

# order matters: specific sports before generic words ("wedding photoshoot" is photography, not an event)
DETECTION_ORDER = ["golf", "cricket", "tennis", "badminton", "basketball", "football", "swimming", "stargazing",
                   "birdwatching", "camping", "cycling", "running", "yoga", "photography", "hiking", "picnic", "event",
                   "walking"]


def detect_activity(text: str) -> str | None:
    t = text.lower()
    for key in DETECTION_ORDER:
        if re.search(ACTIVITIES[key].pattern, t):
            return key
    return None


# words that end a location phrase ("near Powai running ..."); curated so place names like "Koregaon Park" survive
ACTIVITY_WORDS = set("""run running jog jogging golf cricket tennis football soccer futsal cycle cycling bike biking
hike hiking trek trekking picnic wedding birthday photo photos photography photoshoot walk walking stroll event
gathering festival badminton basketball swim swimming yoga workout camp camping stargazing birdwatching birding""".split())

EXAMPLES = {
    "running": "Where can I go running tomorrow evening near Koregaon Park?", "cycling": "Is it okay to cycle to work at 8 AM near Hinjewadi?",
    "golf": "Good place and time for golf on Saturday within 40 km of Andheri?", "cricket": "Best time this weekend for a kids' cricket match near Whitefield?",
    "football": "Where can we play five-a-side football on Sunday evening near Baner?", "tennis": "Outdoor tennis after work today near Hinjewadi?",
    "badminton": "Is it windy for outdoor badminton this evening near Powai?", "basketball": "Where can I shoot hoops tomorrow evening near Indiranagar?",
    "swimming": "Which outdoor pool near Gachibowli is best for a swim on Sunday?", "yoga": "Where can I do outdoor yoga tomorrow morning near Aundh?",
    "hiking": "Is Saturday or Sunday better for a hike near Lonavala?", "birdwatching": "Best morning for birdwatching within 25 km of Thane?",
    "camping": "Where can I go camping this weekend within 50 km of Pune?", "stargazing": "Where can I go stargazing tonight within 40 km of Pune?",
    "picnic": "Where should we have a family picnic on Sunday near Kothrud?", "event": "Planning an outdoor birthday party on Sunday afternoon in Pune, what should I keep in mind?",
    "photography": "Where can I take sunset photos this evening around Bandra?", "walking": "When is it safe for my parents to walk outdoors tomorrow in Bengaluru?",
}
