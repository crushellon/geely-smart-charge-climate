"""Charging-linked comfort preferences for each ready-by weekday.

These settings share the charging deadline, so there is no second clock.
They affect dashboard and simulations only. No vehicle commands are sent.
"""
from .weekly_schedule import DAY_NAMES

KEY = "charging_linked_comfort"
PROFILES = ("Cool", "Warm")


def get_value(options: dict, day: str, field: str):
    if day not in DAY_NAMES or field not in ("enabled", "profile"):
        raise ValueError("Unsupported charging-linked comfort setting")
    default = False if field == "enabled" else "Cool"
    return options.get(KEY, {}).get(day, {}).get(field, default)


def set_value(options: dict, day: str, field: str, value):
    if day not in DAY_NAMES:
        raise ValueError("Unknown weekday")
    if field == "enabled":
        if not isinstance(value, bool):
            raise ValueError("Enabled must be on/off")
    elif field == "profile":
        if value not in PROFILES:
            raise ValueError("Unknown comfort profile")
    else:
        raise ValueError("Unknown setting")
    all_days = options.get(KEY, {})
    updated = {**all_days, day: {**all_days.get(day, {}), field: value}}
    return {**options, KEY: updated}
