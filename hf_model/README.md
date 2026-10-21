---
license: apache-2.0
base_model: {{BASE}}
library_name: transformers
pipeline_tag: text-generation
language: [en]
tags: [geoai, outdoor-activities, weather, openstreetmap, small-language-model, hackathon]
---

# GeoAI Outdoor SLM

The language component of the **GeoAI Outdoor Assistant** (GeoAI Hackathon @ CSRE, IIT Bombay).

| | |
|---|---|
| Base model | `{{BASE}}` |
| Parameters | {{PARAMS}} (limit: 3B) |
| Changes | {{CHANGES}} |
| Licence | Apache-2.0 (inherited from the base model; verify on the base model card) |

## Intended use
This model is **not** a knowledge source. In the assistant it does two narrow jobs, always on top of live data fetched per query
(Open-Meteo weather and air quality, OpenStreetMap geometry, OSRM routing):

1. **Query understanding** - turn a messy question into `{"activity","location","radius_km"}` JSON. Output is validated: a location must appear verbatim in the user's text.
2. **Grounded narration** - explain a recommendation that a deterministic scoring engine already made, citing evidence ids (`[E3]`) and referring to venues only by codes (`P1`, `P2`). A verifier rejects any narration containing a number, place or evidence id that is not in the evidence pack and falls back to a template.

Ranking, thresholds and safety vetoes are **not** decided by the model.

## Out-of-scope / limitations
- Do not use it to answer weather, geography or health questions from memory; it will be wrong.
- Not medical advice. Personal-profile adjustments (asthma, senior, child, pregnancy, heart condition) are conservative heuristics.
- English only; Indian place-name geocoding relies on OpenStreetMap coverage.

## Load
```python
from transformers import AutoModelForCausalLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained("THIS_REPO"); model = AutoModelForCausalLM.from_pretrained("THIS_REPO")
```
Code, scoring method and data sources: see the project repository linked in the submission.
