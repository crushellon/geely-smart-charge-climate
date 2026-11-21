"""Map human-friendly comfort settings onto stored local profile values.

These preferences never call a vehicle service. Existing numeric profile
values continue to be readable without a migration.
"""
from .comfort import PROFILES, get_value, set_value

SEAT_OPTIONS = (
    "Off", "Heat Low", "Heat Medium", "Heat High",
    "Vent Low", "Vent Medium", "Vent High",
)
LEVEL_NAMES = ("Off", "Low", "Medium", "High")
PREFERENCES_KEY = "comfort_display"
PROFILE_VISIBILITY_DEFAULT = True


def get_seat_mode(options: dict, profile: str, occupant: str) -> str:
    """Represent existing heating/ventilation values with one select."""
    if occupant not in ("driver", "passenger") or profile not in PROFILES:
        raise ValueError("Unsupported seat")
    heat = get_value(options, profile, f"{occupant}_seat_heat")
    vent = get_value(options, profile, f"{occupant}_seat_vent")
    if heat:
        return f"Heat {LEVEL_NAMES[heat]}"
    if vent:
        return f"Vent {LEVEL_NAMES[vent]}"
    return "Off"


def set_seat_mode(options: dict, profile: str, occupant: str, mode: str) -> dict:
    """Save one chosen mode and clear the conflicting opposite mode."""
    if mode not in SEAT_OPTIONS or occupant not in ("driver", "passenger"):
        raise ValueError("Unsupported seat mode")
    heat = vent = 0
    if mode.startswith("Heat "):
        heat = LEVEL_NAMES.index(mode.removeprefix("Heat "))
    elif mode.startswith("Vent "):
        vent = LEVEL_NAMES.index(mode.removeprefix("Vent "))
    updated = set_value(options, profile, f"{occupant}_seat_heat", heat)
    return set_value(updated, profile, f"{occupant}_seat_vent", vent)


def get_profile_visible(options: dict, profile: str) -> bool:
    if profile not in PROFILES:
        raise ValueError("Unsupported comfort profile")
    value = options.get(PREFERENCES_KEY, {}).get(f"show_{profile}", PROFILE_VISIBILITY_DEFAULT)
    return value if isinstance(value, bool) else PROFILE_VISIBILITY_DEFAULT


def set_profile_visible(options: dict, profile: str, visible: bool) -> dict:
    if profile not in PROFILES or not isinstance(visible, bool):
        raise ValueError("Unsupported visibility setting")
    prefs = options.get(PREFERENCES_KEY, {})
    return {**options, PREFERENCES_KEY: {**prefs, f"show_{profile}": visible}}
