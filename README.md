# GeoAI Outdoor Assistant

*GeoAI Hackathon @ CSRE, IIT Bombay.* Ask a free-form question; get the best **nearby place and time** for an outdoor activity,
what to carry, what to watch for, and when to avoid it, grounded in live weather, air quality and OpenStreetMap context and
explained by a **small language model (≤ 3B)** that we run ourselves.

> **Live API endpoint:** `https://<YOUR-SPACE-OR-HOST>/ask`  ·  **Model on Hugging Face:** `https://huggingface.co/<YOU>/geoai-outdoor-slm`
> *(fill these two lines in before submitting)*

## What it does
- **18 activities**: the required 10 (running, cycling, golf, cricket, football/five-a-side, tennis, hiking/nature walk, picnic/park outing, outdoor events, photography) plus walking, badminton, basketball, swimming, yoga/outdoor workout, camping, stargazing and birdwatching. Several have their own logic (night sky and moon for stargazing, dawn for birdwatching, overnight slots for camping, inverted heat curve for swimming).
- Understands messy input: missing place, vague time ("this weekend"), AM/PM-less times, out-of-scope questions → asks, states its assumptions, or declines. It never guesses a location or the weather.
- Reasons about **place × hour**: wind direction vs. nearby expressways/industry (time-dependent, with rush hour), green cover and water, daylight, travel time, UV, rain, gusts, AQI.
- Personal profiles (asthma, senior, child, pregnancy, heart condition) tighten the limits.
- Web console at `/`: activity picker, "use my location", verdict card, day-by-hour calendar, click any hour to see why it scores as it does, and a map that draws the wind direction and the upwind roads/industry for that hour. Shareable links (`/#question`).
- Every claim traces to **evidence ids** (`[E3]`) returned with the answer; the response also lists data gaps and sources.

## Architecture
```
question ──► NLU (rules + SLM gap-filler, validated) ──► Nominatim ─► Overpass venues
                                                                       │
        ┌── Open-Meteo weather + AQ ◄──────────────────────────────────┤ (parallel, cached)
        ├── Overpass surroundings (roads, industry, water, green)      │
        └── OSRM travel time, Open-Meteo elevation                     ▼
                    place × hour scoring engine (profiles, vetoes) ──► evidence pack + deterministic advice
                                                                       │
                       SLM narrates with place codes + [E#] citations ─┤
                       verifier rejects invented numbers/places ───────┘ (else template fallback)
```
Details and every threshold: [`docs/METHOD.md`](docs/METHOD.md).

## Run it
Full command-by-command guide (accounts, model publishing, deployment, submission): [`docs/STEP_BY_STEP.md`](docs/STEP_BY_STEP.md).

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
export CONTACT_EMAIL=you@example.com          # Nominatim/OSM usage policy asks for a contact in the User-Agent
export SLM_MODEL_ID=<YOU>/geoai-outdoor-slm   # your public HF repo (or Qwen/Qwen2.5-1.5B-Instruct to try)
uvicorn app.main:app --port 7860              # UI at http://localhost:7860, docs at /docs
```
```bash
curl -s localhost:7860/ask -H 'content-type: application/json' \
  -d '{"question":"Where can I go running tomorrow evening near Koregaon Park?"}' | jq .answer
```
Request: `{"question": str, "lat"?: float, "lon"?: float, "radius_km"?: number}`. `lat/lon` stands in for a missing place.
Response `status` is `ok | needs_clarification | out_of_scope | no_venues | data_unavailable`; for `ok` see `answer`, `markdown`,
`recommendation`, `extras` (sunrise/sunset, moon), `options[]` (hourly scores, geospatial context), `advice`, `evidence[]`, `data_gaps`, `sources`, `meta`.

`GET /activities` lists the supported activities with example questions.

Docker / Hugging Face Space (SDK = Docker, port 7860): `docker build -t geoai . && docker run -p 7860:7860 geoai`.
Faster CPU inference: `SLM_BACKEND=llama_cpp`, `SLM_MODEL_ID=<gguf repo>`, `SLM_GGUF_FILE=*q4_k_m.gguf`.

## Model
Base: **Qwen2.5-1.5B-Instruct** (≈1.5 B parameters, Apache-2.0), loaded with `from_pretrained` from our public repo.
Used unchanged unless you run the optional LoRA fine-tune in `training/` (query-parsing task, synthetic data, localities disjoint from the rulebook samples).
The model never decides rankings or safety limits; it parses messy questions and narrates a verified evidence pack. Model card: `hf_model/README.md`.

## Data sources (all free, no keys; fetched live per query)
| Source | Used for |
|---|---|
| OpenStreetMap via Overpass API | venues, roads, industry, water, green cover, power lines |
| Nominatim | geocoding |
| Open-Meteo Forecast | hourly weather, sunrise/sunset, elevation |
| Open-Meteo Air Quality (CAMS) | PM2.5, PM10, US AQI |
| OSRM public server | road distance and free-flow travel time |

**© OpenStreetMap contributors.** We cache responses (15 min – 24 h), throttle Nominatim to 1 req/s, send an identifying User-Agent and use Overpass mirrors with failover.

## Tests
`pip install -r requirements-dev.txt && pytest` (56 tests: parsing, time windows, scoring, wind/rush-hour logic, profiles, hallucination guard, graceful degradation, API). Upstream services are faked in tests; run `python scripts/smoke.py <url>` against the live deployment.

## Honest limitations
- AQ model is coarse (CAMS, tens of km). The local exposure index is a heuristic layered on top, not a sensor reading. WAQI/OpenAQ/CPCB stations are a natural next step.
- OSM coverage varies: some localities have few or unnamed pitches/courts (we skip unnamed features rather than invent names); road/industry geometry uses way centres.
- OSRM has no live traffic; rush-hour travel is a labelled estimate. Public OSRM/Overpass/Nominatim servers are rate-limited and can be slow.
- Thresholds are transparent heuristics, not clinical or sporting standards; not medical advice.
- A 1.5 B model on CPU is slow (tens of seconds); the answer's facts come from the evidence pack, so quality degrades gracefully to the template.
- English only. Forecast horizon ≈ 15 days (AQ ≈ 5-7 days).

## AI-assistance disclosure
Code was written with help from an AI coding assistant (Claude, Anthropic), as permitted for coding aid. No hosted LLM is called by the running assistant.
