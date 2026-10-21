# Method

## Pipeline
1. **Understand** (`nlu.py`, `timeparse.py`): rules extract activity, place, radius, personal profile and a concrete time window
   in the venue's own timezone. The SLM is consulted only if rules leave a gap; its output is validated (a place must literally occur
   in the user's text). Every default we apply ("no time given, using next 24 h") is returned in `assumptions`.
2. **Fetch live** (all in parallel, cached, fail-soft except weather): Nominatim geocode, Overpass venues + surroundings,
   Open-Meteo weather and air quality (multi-point, one call each), OSRM travel times, Open-Meteo elevation (hiking, photography).
3. **Score place × hour** (`scoring.py`): component risks in [0,1] → weighted sum → 0-100. Slots of the activity's duration are scored
   as `0.6·mean + 0.4·min` of their hours minus a travel penalty; any veto caps a slot at 25.
4. **Geospatial exposure** (`geo_context.py`): for every busy road / industrial source within range, weight = strength × proximity ×
   wind alignment (is the source upwind *at that hour*?) × wind dilution × rush-hour factor (roads). Effective AQI =
   model AQI × (1 + 0.35·exposure) × (1 − 0.08·green). Green cover and water also cool the felt temperature by up to 1.5 °C.
5. **Explain** (`explain.py`): evidence pack with ids, deterministic advice (carry / watch / avoid windows) linked to evidence ids,
   then the SLM narrates using place codes P1..P3; the verifier rejects invented numbers, ids, codes or proper nouns → template fallback.

Bands: great ≥ 75, good ≥ 55, marginal ≥ 35, avoid < 35. Vetoes: thunderstorm code, heat/AQI/gust risk = 1, too dark (unlit venue), likely heavy rain.
Travel: OSRM free-flow time × heuristic congestion (×1.5 at 08-10 h, ×1.7 at 17-20 h, ×1.15 midday). OSRM has no live traffic; this is labelled as an estimate.
Special logic per activity:
- **Stargazing**: scored only when the sun is >90 min below the horizon; cloud cover (weight .35) and moonlight (illuminated fraction, computed from the lunar cycle, not fetched) matter most. Default focus 20:00-05:00.
- **Camping**: 12-hour overnight slot starting 15:00-20:00 by default; cold, rain and wind dominate, darkness is expected.
- **Swimming**: inverted comfort curve (warm is good, cool is penalised); thunder vetoes.
- **Birdwatching**: prefers sunrise-30 min to sunrise+150 min; gusts penalised (birds hide in wind). Default focus 05:00-10:00.
- **Badminton**: gust thresholds 10-22 km/h, far stricter than other sports.
- Photography: golden-hour logic from sunrise/sunset; "sunset"/"sunrise" in the question restricts slots to that light.

## Activity thresholds (editable in `app/activities.py`)
| Activity | Venues (OSM) | Radius km | Slot h | Heat feels-like °C (good→bad) | Gust km/h | Rain % | AQI (US) | Dark risk |
|---|---|---|---|---|---|---|---|---|
| Running or jogging | `leisure=park, leisure=track, leisure=nature_reserve…` | 5 | 1 | 22→33 | 28→55 | 30→70 | 55→130 | 0.5 |
| Cycling (leisure or commute) | `leisure=park, highway=cycleway, sport=cycling` | 10 | 2 | 24→35 | 25→45 | 25→60 | 65→140 | 0.6 |
| Golf | `leisure=golf_course` | 25 | 4 | 30→38 | 25→45 | 20→55 | 100→170 | 1.0 |
| Cricket (recreational match or practice) | `sport=cricket` | 10 | 3 | 30→38 | 30→55 | 20→55 | 90→150 | 1.0 |
| Outdoor football or five-a-side | `sport~^(soccer|football|futsal)$` | 8 | 2 | 28→36 | 35→60 | 35→70 | 75→140 | 0.7 |
| Outdoor tennis | `sport=tennis` | 8 | 2 | 30→38 | 20→38 | 25→60 | 90→150 | 0.8 |
| Hiking or a nature walk | `natural=peak, leisure=nature_reserve, tourism=viewpoint…` | 40 | 4 | 27→35 | 35→60 | 25→60 | 90→150 | 1.0 |
| Picnic or park outing | `tourism=picnic_site, leisure=park, leisure=garden…` | 15 | 3 | 30→37 | 30→50 | 15→50 | 100→150 | 1.0 |
| Outdoor event or gathering | `amenity=events_venue, amenity=community_centre, leisure=garden…` | 15 | 4 | 31→38 | 25→45 | 10→45 | 110→170 | 0.25 |
| Outdoor photography session | `tourism=viewpoint, natural=beach, natural=peak…` | 20 | 2 | 34→42 | 40→70 | 40→80 | 150→250 | 1.0 |
| Walking (park or neighbourhood) | `leisure=park, leisure=garden, leisure=nature_reserve…` | 4 | 1 | 28→36 | 35→60 | 30→70 | 70→150 | 0.8 |
| Outdoor badminton | `sport=badminton` | 6 | 2 | 30→38 | 10→22 | 20→55 | 80→140 | 0.8 |
| Outdoor basketball | `sport=basketball` | 8 | 2 | 28→36 | 35→60 | 30→65 | 75→140 | 0.7 |
| Outdoor swimming | `leisure=swimming_pool & access!~^(private|no)$, leisure=water_park` | 10 | 2 | 37→43 | 35→60 | 35→75 | 100→170 | 0.8 |
| Outdoor yoga or workout | `leisure=park, leisure=garden, leisure=fitness_station` | 4 | 1 | 24→34 | 35→60 | 30→70 | 50→110 | 0.6 |
| Camping | `tourism=camp_site, tourism=caravan_site` | 50 | 12 | 32→40 | 30→50 | 15→45 | 100→160 | 0.0 |
| Stargazing | `tourism=viewpoint, natural=peak, leisure=nature_reserve…` | 40 | 3 | 34→42 | 40→70 | 20→50 | 70→140 | 1.0 |
| Birdwatching | `leisure=nature_reserve, natural=wetland, leisure=bird_hide…` | 25 | 3 | 28→36 | 20→40 | 25→60 | 90→150 | 1.0 |

Weights default to heat .25, cold .12, rain .25, wind .12, AQI .22, UV .08, light .25, travel .10 (per-activity overrides in code).

## Personal profiles (applied on top of the above)
| Profile | Heat shift °C | Cold shift °C | AQI thresholds × | UV × | Gust × |
|---|---|---|---|---|---|
| asthma / respiratory condition | -3 | +3 | 0.55 | 1.0 | 1.0 |
| senior | -4 | +4 | 0.7 | 1.0 | 0.8 |
| child | -3 | +0 | 0.7 | 0.7 | 1.0 |
| pregnancy | -4 | +0 | 0.7 | 0.8 | 1.0 |
| heart / blood-pressure condition | -4 | +3 | 0.7 | 1.0 | 1.0 |

## What is heuristic, and what is not
Measured/forecast: weather, AQI model, sunrise/sunset, OSM geometry, OSRM road distance. **Heuristic**: all thresholds and weights,
the local exposure index, the congestion factor, the cooling effect of green cover. They are transparent and tunable, not validated
against ground-truth sensors or clinical guidance.
