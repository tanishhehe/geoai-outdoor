"""Runtime configuration. Everything is overridable through environment variables."""
import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    contact: str
    slm_backend: str          # transformers | llama_cpp | none (none = tests only)
    slm_model_id: str         # HF repo id of YOUR published model/adapter-merged repo
    slm_gguf_file: str        # only for llama_cpp
    slm_dtype: str            # float32 | bfloat16 | float16
    slm_threads: int
    slm_max_new_tokens: int
    default_tz: str
    geocode_countries: str    # "in" first, then worldwide fallback. "" disables bias
    nominatim_url: str
    overpass_urls: tuple
    osrm_url: str
    open_meteo_url: str
    open_meteo_aq_url: str
    max_venues: int
    request_timeout: float
    overall_timeout: float

    @property
    def user_agent(self) -> str:
        return f"GeoAI-Outdoor-Assistant/1.0 (hackathon; contact: {self.contact})"


@lru_cache
def get_settings() -> Settings:
    e = os.getenv
    return Settings(
        contact=e("CONTACT_EMAIL", "set-CONTACT_EMAIL@example.com"),
        slm_backend=e("SLM_BACKEND", "transformers"),
        slm_model_id=e("SLM_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct"),
        slm_gguf_file=e("SLM_GGUF_FILE", "*q4_k_m.gguf"),
        slm_dtype=e("SLM_DTYPE", "float32"),
        slm_threads=int(e("SLM_THREADS", str(os.cpu_count() or 2))),
        slm_max_new_tokens=int(e("SLM_MAX_NEW_TOKENS", "230")),
        default_tz=e("DEFAULT_TZ", "Asia/Kolkata"),
        geocode_countries=e("GEOCODE_COUNTRIES", "in"),
        nominatim_url=e("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"),
        overpass_urls=tuple(
            e("OVERPASS_URLS",
              "https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter").split(",")),
        osrm_url=e("OSRM_URL", "https://router.project-osrm.org"),
        open_meteo_url=e("OPEN_METEO_URL", "https://api.open-meteo.com/v1"),
        open_meteo_aq_url=e("OPEN_METEO_AQ_URL", "https://air-quality-api.open-meteo.com/v1"),
        max_venues=int(e("MAX_VENUES", "7")),
        request_timeout=float(e("REQUEST_TIMEOUT", "35")),
        overall_timeout=float(e("OVERALL_TIMEOUT", "170")),
    )
