"""Resolve vague time phrases ("tomorrow evening", "this weekend", "at 8 AM") into a concrete window.

Everything is computed in the *venue's* local timezone. We never guess silently: each default we apply
is recorded in `assumptions` and shown to the user.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
       "eight": 8, "nine": 9, "ten": 10, "twelve": 12}
PARTS = [  # (name, regex, (start_hour, end_hour_exclusive))
    ("early morning", r"early[- ]morning|\bdawn\b", (5, 8)),
    ("after work", r"after (work|office)", (17, 21)),
    ("afternoon", r"\bafternoon\b", (12, 17)),
    ("evening", r"\bevening\b", (16, 21)),
    ("morning", r"\bmorning\b", (5, 11)),
    ("night", r"\b(tonight|night)\b", (19, 23)),
    ("midday", r"\b(noon|midday|lunch ?time)\b", (11, 15)),
]
DEFAULT_DAY = (5, 22)
HORIZON_DAYS = 15


class TimeError(ValueError):
    pass


@dataclass
class TimeWindow:
    start: datetime
    end: datetime                      # exclusive
    label: str
    daily_hours: tuple | None = None   # only hours in [h0, h1) of each day are considered
    focus: datetime | None = None      # an explicit clock time the user asked about
    goal: str | None = None            # "sunset" | "sunrise"
    compare_days: bool = False
    assumptions: list = field(default_factory=list)


def _at(day0: datetime, offset: int, hour: int, minute: int = 0) -> datetime:
    return (day0 + timedelta(days=offset)).replace(hour=0, minute=0) + timedelta(hours=hour, minutes=minute)


def _label(start: datetime, end: datetime, focus) -> str:
    last = end - timedelta(minutes=1)
    if focus is not None:
        return f"{focus:%a %d %b}, around {focus:%H:%M}"
    if start.date() == last.date():
        return f"{start:%a %d %b}, {start:%H:%M}\u2013{end:%H:%M}"
    return f"{start:%a %d %b} \u2013 {last:%a %d %b}"


def parse_time(text: str, now: datetime) -> TimeWindow:
    t = text.lower()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    floor_now = now.replace(minute=0, second=0, microsecond=0)
    assum: list[str] = []

    goal = "sunset" if re.search(r"sunset|golden hour|dusk", t) else "sunrise" if re.search(r"sunrise", t) else None
    pod = next(((n, r) for n, p, r in PARTS if re.search(p, t)), None)
    if pod is None and goal == "sunset":
        pod = ("sunset", (15, 20))
    if pod is None and goal == "sunrise":
        pod = ("sunrise", (4, 9))

    # ---- explicit clock time
    clock = None
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)", t)
    if m:
        clock = ((int(m[1]) % 12) + (12 if m[3].startswith("p") else 0), int(m[2] or 0))
    elif (m := re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", t)):
        clock = (int(m[1]), int(m[2]))
    elif (m := re.search(r"\bat (\d{1,2})\b(?!\s*(km|kilomet|mi\b|miles|%))", t)) and 1 <= int(m[1]) <= 12:
        h = int(m[1])
        if pod and pod[0] in ("evening", "night", "afternoon", "after work"):
            h = h % 12 + 12
        elif 1 <= h <= 4:
            h += 12
        clock = (h, 0)
        assum.append(f"No AM/PM given; read \u201cat {m[1]}\u201d as {h:02d}:00.")

    # ---- explicit day(s)
    offsets: list[int] = []
    if re.search(r"day after tomorrow", t):
        offsets.append(2)
    elif "tomorrow" in t:
        offsets.append(1)
    if re.search(r"\b(today|tonight|this (morning|afternoon|evening)|later today)\b", t):
        offsets.append(0)
    for i, w in enumerate(WEEKDAYS):
        if re.search(rf"\b{w}s?\b", t):
            offsets.append((i - now.weekday()) % 7)
    if re.search(r"\bweekend\b", t):
        wd = now.weekday()
        sat = (5 - wd) % 7 if wd != 6 else -1
        base = [0] if wd == 6 else [sat, sat + 1] if wd != 5 else [0, 1]
        if re.search(r"next weekend", t):
            base = [b + 7 for b in base]
        offsets += base
    week = re.search(r"\b(this|next) week\b", t)
    rng = re.search(r"(?:next|coming|upcoming|following)\s+(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
                    r"\s*(hour|hr|day)s?", t)

    daily = None
    focus = None
    if rng:
        n = int(rng[1]) if rng[1].isdigit() else NUM[rng[1]]
        start, end = floor_now, floor_now + (timedelta(hours=n) if rng[2] != "day" else timedelta(days=n))
        if pod and (end - start) > timedelta(hours=12):
            daily = pod[1]
        elif (end - start) > timedelta(hours=30):
            daily = DEFAULT_DAY
    elif week and not offsets:
        a = 0 if week[1] == "this" else 7 - now.weekday()
        start, end = _at(day0, a, 0), _at(day0, a + 7, 0)
        daily = DEFAULT_DAY
    elif offsets:
        lo, hi = min(offsets), max(offsets)
        if clock:
            daily = (max(0, clock[0] - 2), min(24, clock[0] + 3))
            if lo == hi:
                focus = _at(day0, lo, *clock)
        elif pod:
            daily = pod[1]
        else:
            daily = DEFAULT_DAY
            assum.append("No time of day given; considering 05:00\u201322:00.")
        start, end = _at(day0, lo, daily[0]), _at(day0, hi, daily[1])
        if lo == 0 and end <= now and lo == hi and not (week or rng):
            start, end = _at(day0, 1, daily[0]), _at(day0, 1, daily[1])
            assum.append("That part of today has already passed, so I used tomorrow.")
            if focus:
                focus += timedelta(days=1)
    elif clock:
        f = _at(day0, 0, *clock)
        if f <= now:
            f += timedelta(days=1)
            assum.append("That time has passed today; using tomorrow.")
        focus = f
        start, end = f - timedelta(hours=2), f + timedelta(hours=3)
    elif pod:
        off = 0 if now.hour < pod[1][1] - 1 else 1
        if off:
            assum.append(f"No day given and this {pod[0]} is mostly over; using tomorrow {pod[0]}.")
        else:
            assum.append(f"No day given; assuming today ({pod[0]}).")
        start, end = _at(day0, off, pod[1][0]), _at(day0, off, pod[1][1])
    else:
        start, end = floor_now, floor_now + timedelta(hours=24)
        assum.append("No time given; looking at the next 24 hours.")

    if start < floor_now:
        start = floor_now
    if end <= start:
        raise TimeError("The requested time is already in the past.")
    limit = day0 + timedelta(days=HORIZON_DAYS)
    if start >= limit:
        raise TimeError(f"Forecasts only reach about {HORIZON_DAYS} days ahead.")
    if end > limit:
        end = limit
        assum.append(f"Clipped to the {HORIZON_DAYS}-day forecast horizon.")
    compare = len(set(offsets)) >= 2 and not week
    return TimeWindow(start, end, _label(start, end, focus), daily, focus, goal, compare, assum)


def apply_activity_defaults(tw: TimeWindow, act) -> TimeWindow:
    """If the user gave no time of day, focus on when the activity actually makes sense (e.g. stargazing at night)."""
    hours = act.default_hours
    if not hours or tw.daily_hours != DEFAULT_DAY:
        return tw
    tw.daily_hours = hours
    last_day = (tw.end - timedelta(minutes=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    tw.end = last_day + (timedelta(days=1, hours=hours[1]) if hours[0] > hours[1] else timedelta(hours=hours[1]))
    tw.label = _label(tw.start, tw.end, tw.focus)
    tw.assumptions.append(f"{act.label} works best around {hours[0]:02d}:00\u2013{hours[1]:02d}:00, so I focused on those hours.")
    return tw
