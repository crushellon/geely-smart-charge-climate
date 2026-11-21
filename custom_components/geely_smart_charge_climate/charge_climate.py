"""Charging-linked comfort preferences for each ready-by weekday.

These settings share the charging deadline. The scheduled-climate controller
uses them to send Geely cabin commands independently of charging power.
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


TIMING_KEY = "charging_linked_timing"


def get_timing(options: dict, field: str) -> int:
    """Charging-linked cabin comfort starts before/ends after ready-by."""
    if field not in ("lead_minutes", "hold_minutes"):
        raise ValueError("Unsupported timing setting")
    default = 10 if field == "lead_minutes" else 15
    return options.get(TIMING_KEY, {}).get(field, default)


def set_timing(options: dict, field: str, value) -> dict:
    if field not in ("lead_minutes", "hold_minutes"):
        raise ValueError("Unsupported timing field")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or int(value) != value or not 0 <= value <= 120):
        raise ValueError("Timing must be 0–120 whole minutes")
    existing = options.get(TIMING_KEY, {})
    return {**options, TIMING_KEY: {**existing, field: int(value)}}

def snapshot(options: dict, day: str) -> dict:
    """Read the current charging-linked comfort configuration for diagnostics.

    Configuration only: this does not run climate or send vehicle commands.
    Both the active session and dashboard read fresh persisted settings.
    """
    from .comfort import get_value as get_profile_value
    from .comfort_display import get_seat_mode

    enabled = get_value(options, day, "enabled")
    profile = get_value(options, day, "profile")
    selected = profile.lower()
    return {
        "enabled": enabled,
        "profile": profile,
        "temperature": get_profile_value(options, selected, "temperature"),
        "driver_seat": get_seat_mode(options, selected, "driver"),
        "passenger_seat": get_seat_mode(options, selected, "passenger"),
        "steering_heat": bool(get_profile_value(options, selected, "steering_heat")),
        "lead_minutes": get_timing(options, "lead_minutes"),
        "hold_minutes": get_timing(options, "hold_minutes"),
        "commands_enabled": False,
    }
