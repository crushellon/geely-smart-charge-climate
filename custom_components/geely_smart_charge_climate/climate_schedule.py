"""Seven independent weekly climate schedules, for simulation only.

Each slot occurs at most once per calendar week. Slots can share the same
weekday, and have their own temperature, seat and wheel preferences. No state
here triggers a service or requires a charge cable.
"""
from datetime import datetime, timedelta
from math import isfinite

SLOTS = tuple(range(1, 8))
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SEAT_MODES = ("Off", "Heat Low", "Heat Medium", "Heat High",
              "Vent Low", "Vent Medium", "Vent High")
STORE_KEY = "climate_schedules"
DEFAULT = {
    "enabled": False, "day": "Monday", "ready_time": "07:30",
    "temperature": 22.0, "driver_seat": "Off", "passenger_seat": "Off",
    "steering_heat": False, "lead_minutes": 12, "hold_minutes": 5,
}
TIMING_FIELDS = ("lead_minutes", "hold_minutes")
SEAT_FIELDS = ("driver_seat", "passenger_seat")


def get_slot(options: dict, slot: int) -> dict:
    if slot not in SLOTS:
        raise ValueError("Unknown climate schedule")
    saved = options.get(STORE_KEY, {}).get(str(slot), {})
    return {**DEFAULT, **saved}


def validate_field(field: str, value):
    if field in ("enabled", "steering_heat"):
        if not isinstance(value, bool):
            raise ValueError(f"{field} must be on/off")
    elif field == "day":
        if value not in DAYS:
            raise ValueError("Invalid weekday")
    elif field == "ready_time":
        if not isinstance(value, str):
            raise ValueError("Time must be HH:MM")
        parts = value.split(":")
        if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
            raise ValueError("Time must be HH:MM")
        try:
            hour, minute = map(int, parts)
        except ValueError as exc:
            raise ValueError("Time must be HH:MM") from exc
        if hour > 23 or minute > 59:
            raise ValueError("Time must be HH:MM")
    elif field == "temperature":
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not isfinite(value) or not 16 <= value <= 30
                or (value * 2) % 1):
            raise ValueError("Temperature must be 16–30 in 0.5°C steps")
        value = float(value)
    elif field in SEAT_FIELDS:
        if value not in SEAT_MODES:
            raise ValueError("Invalid seat mode")
    elif field in TIMING_FIELDS:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not isfinite(value) or not value.is_integer() if isinstance(value, float)
                else False):
            raise ValueError("Minutes must be whole numbers")
        if not isinstance(value, int) and not isinstance(value, float):
            raise ValueError("Minutes must be numeric")
        if int(value) != value or not 0 <= value <= 120:
            raise ValueError("Minutes must be 0–120")
        value = int(value)
    else:
        raise ValueError("Unsupported climate schedule field")
    return value


def update_slot(options: dict, slot: int, field: str, value) -> dict:
    value = validate_field(field, value)
    saved = options.get(STORE_KEY, {})
    new_slot = {**saved.get(str(slot), {}), field: value}
    return {**options, STORE_KEY: {**saved, str(slot): new_slot}}


def next_event(now: datetime, options: dict) -> dict | None:
    """Earliest future occurrence, measured by ready-by time.

    Return the start and end times even when a lead time crosses midnight.
    This function is advisory: it never starts a climate session.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Need timezone-aware local time")
    candidates = []
    for slot in SLOTS:
        schedule = get_slot(options, slot)
        if not schedule["enabled"]:
            continue
        day = DAYS.index(schedule["day"])
        hour, minute = map(int, schedule["ready_time"].split(":"))
        offset = (day - now.weekday()) % 7
        ready = (now + timedelta(days=offset)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if ready <= now:
            ready += timedelta(days=7)
        lead = timedelta(minutes=schedule["lead_minutes"])
        hold = timedelta(minutes=schedule["hold_minutes"])
        candidates.append({
            "slot": slot, "day": schedule["day"], "ready_by": ready,
            "start_at": ready - lead, "end_at": ready + hold,
            "temperature": schedule["temperature"],
            "driver_seat": schedule["driver_seat"],
            "passenger_seat": schedule["passenger_seat"],
            "steering_heat": schedule["steering_heat"],
        })
    return min(candidates, key=lambda item: (item["ready_by"], item["slot"])) if candidates else None
