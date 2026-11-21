"""Pure local-time weekly charging targets for an advisory-only simulator.

Days refer to the DAY THE VEHICLE MUST BE READY. All days start disabled;
the public integration must not import the developer's personal schedule.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class NextCharge:
    day: str
    target: int
    ready_by: datetime


def default_schedule() -> dict[str, dict]:
    """Neutral defaults, deliberately disabled until users opt in."""
    return {
        day: {"enabled": False, "target": 80, "ready_time": "06:30"}
        for day in DAY_NAMES
    }


def validate_day(settings: Mapping) -> dict:
    """Validate and normalise an individual day's UI settings."""
    enabled = settings.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("Enabled must be a boolean")
    target = settings.get("target", 80)
    if isinstance(target, bool) or not isinstance(target, (int, float)) or int(target) != target:
        raise ValueError("Target must be an integer")
    target = int(target)
    if not 50 <= target <= 100:
        raise ValueError("Target must be 50-100")
    ready_time = settings.get("ready_time", "06:30")
    if not isinstance(ready_time, str) or len(ready_time) != 5:
        raise ValueError("Time must be HH:MM")
    try:
        hours, minutes = [int(part) for part in ready_time.split(":")]
    except (ValueError, AttributeError) as exc:
        raise ValueError("Time must be HH:MM") from exc
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError("Time must be HH:MM")
    return {"enabled": enabled, "target": target, "ready_time": f"{hours:02}:{minutes:02}"}


def next_charge(now: datetime, schedule: Mapping) -> NextCharge | None:
    """Return the next *future* enabled deadline in HA's local time zone.

    Handles midnight crossover by selecting calendar-day ready-by deadlines,
    rather than assuming charging starts on the same weekday. No day enabled
    means no plan, not an implicit daily 80% charge.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Local timestamp must be timezone-aware")
    candidates: list[NextCharge] = []
    for index, day in enumerate(DAY_NAMES):
        settings = validate_day(schedule.get(day, {}))
        if not settings["enabled"]:
            continue
        hours, minutes = map(int, settings["ready_time"].split(":"))
        offset = (index - now.weekday()) % 7
        deadline = (now + timedelta(days=offset)).replace(
            hour=hours, minute=minutes, second=0, microsecond=0
        )
        if deadline <= now:
            deadline += timedelta(days=7)
        candidates.append(NextCharge(day, settings["target"], deadline))
    return min(candidates, key=lambda value: value.ready_by) if candidates else None
