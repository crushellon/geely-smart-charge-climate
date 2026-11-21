"""Local-time windows for independent and charging-linked cabin schedules.

Pure planning: the controller issues Geely actions separately. Each ready-by
weekday names the day the user needs the car, even when lead crosses midnight.
"""
from datetime import datetime, timedelta
from .weekly_schedule import DAY_NAMES, validate_day
from .climate_schedule import SLOTS, DAYS, get_slot
from .charge_climate import get_value as linked_value, get_timing, snapshot


def candidate_windows(now: datetime, options: dict) -> list[dict]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Climate scheduling requires timezone-aware local time")
    choices = []
    # Includes very early departures whose preconditioning starts yesterday.
    for offset in (-1, 0, 1):
        date = (now + timedelta(days=offset)).date()
        for slot in SLOTS:
            setting = get_slot(options, slot)
            if not setting["enabled"] or DAYS.index(setting["day"]) != date.weekday():
                continue
            hour, minute = map(int, setting["ready_time"].split(":"))
            ready = datetime.combine(date, datetime.min.time(), tzinfo=now.tzinfo)
            ready = ready.replace(hour=hour, minute=minute)
            start = ready - timedelta(minutes=setting["lead_minutes"])
            end = ready + timedelta(minutes=setting["hold_minutes"])
            if start <= now < end:
                choices.append({
                    "key": f"ind:{slot}:{ready.isoformat()}",
                    "kind": "independent", "slot": slot,
                    "ready_by": ready, "start_at": start, "end_at": end,
                    "temperature": setting["temperature"],
                    "driver_seat": setting["driver_seat"],
                    "passenger_seat": setting["passenger_seat"],
                    "steering_heat": setting["steering_heat"],
                })
        if (options.get("automatic_charging_enabled", False) is not True
                or options.get("public_charging_mode", False) is True):
            continue
        day = DAY_NAMES[date.weekday()]
        charge = validate_day(options.get("weekly_schedule", {}).get(day, {}))
        if not charge["enabled"] or not linked_value(options, day, "enabled"):
            continue
        h, m = map(int, charge["ready_time"].split(":"))
        ready = datetime.combine(date, datetime.min.time(), tzinfo=now.tzinfo)
        ready = ready.replace(hour=h, minute=m)
        start = ready - timedelta(minutes=get_timing(options, "lead_minutes"))
        end = ready + timedelta(minutes=get_timing(options, "hold_minutes"))
        if start <= now < end:
            profile = snapshot(options, day)
            choices.append({
                "key": f"linked:{day}:{ready.isoformat()}",
                "kind": "linked", "day": day,
                "ready_by": ready, "start_at": start, "end_at": end,
                "temperature": profile["temperature"],
                "driver_seat": profile["driver_seat"],
                "passenger_seat": profile["passenger_seat"],
                "steering_heat": profile["steering_heat"],
            })
    # Independent events take priority when simultaneous, then earlier ending
    # event; an already-running session can be retained by the caller.
    return sorted(choices, key=lambda event: (
        event["kind"] != "independent", event["ready_by"], event["key"]
    ))
