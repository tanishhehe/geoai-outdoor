"""Personal profiles tighten the limits for that user. Guidance only, never medical advice."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    pattern: str
    heat_shift: float = 0.0     # degC subtracted from heat thresholds
    cold_shift: float = 0.0     # degC added to cold thresholds
    aqi_factor: float = 1.0     # AQI thresholds are multiplied by this
    uv_factor: float = 1.0
    wind_factor: float = 1.0
    notes: tuple = ()


PROFILES = {p.key: p for p in [
    Profile("asthma", "asthma / respiratory condition",
            r"\b(asthma|asthmatic|copd|wheez\w*|bronchitis|breathing (problem|issue)s?|respiratory)\b",
            heat_shift=-3, cold_shift=3, aqi_factor=.55,
            notes=("Keep your reliever inhaler with you and follow your own action plan.",
                   "Cold, dry air and high-pollution days can trigger symptoms; warm up slowly.")),
    Profile("senior", "senior",
            r"\b(senior|seniors|elderly|old age|aged|grand(mother|father|parents?)|parents|retired|pensioner)\b",
            heat_shift=-4, cold_shift=4, aqi_factor=.7, wind_factor=.8,
            notes=("Prefer shaded, flat routes with seating, and go with a companion.",
                   "Hydrate before you start; slow down or stop at the first sign of dizziness.")),
    Profile("child", "child",
            r"\b(kid|kids|child|children|toddler|school|son|daughter|boys|girls)\b|\bkids'",
            heat_shift=-3, aqi_factor=.7, uv_factor=.7,
            notes=("Plan water and shade breaks every 20-30 minutes; children overheat faster than adults.",)),
    Profile("pregnancy", "pregnancy", r"\b(pregnant|pregnancy|expecting|expectant)\b",
            heat_shift=-4, aqi_factor=.7, uv_factor=.8,
            notes=("Avoid overheating, keep the pace conversational and check with your doctor if unsure.",)),
    Profile("heart", "heart / blood-pressure condition",
            r"\b(heart|cardiac|hypertension|blood pressure|bp)\b",
            heat_shift=-4, cold_shift=3, aqi_factor=.7,
            notes=("Keep intensity low and follow your doctor's exercise advice.",)),
]}


def detect_profiles(text: str) -> list[str]:
    t = text.lower()
    return [k for k, p in PROFILES.items() if re.search(p.pattern, t)]


def combine(keys: list[str]) -> Profile:
    ps = [PROFILES[k] for k in keys if k in PROFILES]
    if not ps:
        return Profile("none", "general adult", "")
    return Profile(
        "+".join(p.key for p in ps), " + ".join(p.label for p in ps), "",
        heat_shift=min(p.heat_shift for p in ps), cold_shift=max(p.cold_shift for p in ps),
        aqi_factor=min(p.aqi_factor for p in ps), uv_factor=min(p.uv_factor for p in ps),
        wind_factor=min(p.wind_factor for p in ps), notes=tuple(n for p in ps for n in p.notes))
