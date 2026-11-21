"""Editable cabin comfort profiles stored locally; no vehicle control.

Two independent profiles are designed for use by eventual departure schedules.
A changed value is configuration only; it cannot call climate services.
"""

PROFILES = ("warm", "cool")
FIELDS = {
    "temperature": {"min": 16, "max": 30, "default": 22, "unit": "°C"},
    "driver_seat_heat": {"min": 0, "max": 3, "default": 0},
    "passenger_seat_heat": {"min": 0, "max": 3, "default": 0},
    "driver_seat_vent": {"min": 0, "max": 3, "default": 0},
    "passenger_seat_vent": {"min": 0, "max": 3, "default": 0},
    "steering_heat": {"min": 0, "max": 1, "default": 0},
}
DEFAULTS = {
    "warm": {
        "temperature": 24, "driver_seat_heat": 2,
        "passenger_seat_heat": 0, "driver_seat_vent": 0,
        "passenger_seat_vent": 0, "steering_heat": 1,
    },
    "cool": {
        "temperature": 20, "driver_seat_heat": 0,
        "passenger_seat_heat": 0, "driver_seat_vent": 2,
        "passenger_seat_vent": 0, "steering_heat": 0,
    },
}
STORAGE_KEY = "comfort_profiles"


def validate_field(field: str, value: float) -> int:
    """Accept only whole-number ranges supported by this profile model."""
    if field not in FIELDS:
        raise ValueError("Unsupported climate preference")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid comfort value")
    if not float(value).is_integer():
        raise ValueError("Comfort controls use integer values")
    if not FIELDS[field]["min"] <= value <= FIELDS[field]["max"]:
        raise ValueError("Comfort value outside allowed range")
    return int(value)


def get_value(options: dict, profile: str, field: str) -> int:
    """Read stored profile settings with safe defaults."""
    if profile not in PROFILES:
        raise ValueError("Unsupported profile")
    value = options.get(STORAGE_KEY, {}).get(profile, {}).get(
        field, DEFAULTS[profile][field]
    )
    return validate_field(field, value)


def set_value(options: dict, profile: str, field: str, value: float) -> dict:
    """Return new options with a single profile value updated."""
    if profile not in PROFILES:
        raise ValueError("Unsupported profile")
    validated = validate_field(field, value)
    profiles = options.get(STORAGE_KEY, {})
    updated = {
        **profiles,
        profile: {**profiles.get(profile, {}), field: validated},
    }
    return {**options, STORAGE_KEY: updated}
