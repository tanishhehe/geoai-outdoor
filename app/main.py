import asyncio
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import pipeline
from .activities import ACTIVITIES, EXAMPLES
from .config import get_settings
from .slm import make_slm

app = FastAPI(title="GeoAI Outdoor Assistant", version="1.0",
              description="Where and when to head outdoors: live weather + OSM geospatial context + a small language model (<=3B).")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
slm = make_slm()
STATIC = Path(__file__).resolve().parent.parent / "static"


class AskRequest(BaseModel):
    question: str = Field(..., examples=["Where can I go running tomorrow evening near Koregaon Park?"])
    lat: float | None = Field(None, description="optional: user's location, used when the question has no place")
    lon: float | None = None
    radius_km: float | None = Field(None, gt=0, le=60)
    now: datetime | None = Field(None, description="optional ISO time to evaluate 'now' (testing/reproducibility)")


@app.on_event("startup")
def _warm():
    if getattr(slm, "available", False):
        threading.Thread(target=slm.load, daemon=True).start()   # load weights in the background; /health shows progress


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "model": slm.model_id, "backend": s.slm_backend, "model_loaded": getattr(slm, "loaded", False),
            "activities": list(ACTIVITIES)}


@app.get("/activities")
def activities():
    return [{"key": a.key, "label": a.label, "default_radius_km": a.radius_km, "example": EXAMPLES.get(a.key, "")} for a in ACTIVITIES.values()]


@app.post("/ask")
async def ask(req: AskRequest):
    try:
        out = await asyncio.wait_for(pipeline.answer(req.question, slm, lat=req.lat, lon=req.lon, now=req.now, radius_km=req.radius_km),
                                     get_settings().overall_timeout)
    except asyncio.TimeoutError:
        return JSONResponse({"status": "timeout", "message": "The upstream services were too slow; please retry."}, status_code=504)
    return out


@app.get("/ask")
async def ask_get(q: str = Query(..., min_length=3), lat: float | None = None, lon: float | None = None):
    return await ask(AskRequest(question=q, lat=lat, lon=lon))


@app.get("/")
def ui():
    return FileResponse(STATIC / "index.html")
