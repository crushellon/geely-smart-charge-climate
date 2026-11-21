"""Pure, fail-closed checks for explicitly armed live charging tests.

The first live milestone supports manual charging only. Scheduled charging and
climate commands are NOT authorised by this module.
"""
from math import isfinite

LEGACY_CONTROLLER = "input_boolean.ev_controller_enabled"
LEGACY_ACTIVE = "binary_sensor.ev_legacy_charging_controllers_active"
OLD_FULL_CHARGE = "input_boolean.ev_manual_full_charge"
PUBLIC_MODE = "input_boolean.ev_public_charging_mode"
EMERGENCY_STOP = "input_boolean.ev_emergency_stop"
LEGACY_GUARDS = (LEGACY_CONTROLLER, LEGACY_ACTIVE, OLD_FULL_CHARGE)


def start_preflight(
    *, armed: bool, battery, plugged, charging,
    target: int, legacy_states: dict[str, str | None],
) -> str | None:
    """Return a blocking reason, or None if a manual test may start.

    All observable legacy switches must be OFF. Unavailable/unknown is blocked.
    Old deployments without these helpers can still use explicit opt-in.
    """
    if not armed:
        return "Live test is disarmed"
    if isinstance(target, bool) or not isinstance(target, int) or not 50 <= target <= 100:
        return "Invalid target"
    for entity, state in legacy_states.items():
        if state is None:
            continue
        if state != "off":
            return f"Safety interlock not clear: {entity} ({state})"
    if plugged != "on":
        return "Vehicle plug must be positively confirmed connected"
    if charging != "off":
        return "Vehicle charging must be positively confirmed stopped"
    try:
        soc = float(battery)
    except (TypeError, ValueError):
        return "Battery reading missing"
    if not isfinite(soc) or not 0 <= soc <= 100:
        return "Battery reading invalid"
    if soc >= target:
        return "Battery already at or above target"
    return None


def should_stop_owned_session(*, target: int, soc: float | None,
                              emergency: bool, manual_stop: bool = False) -> bool:
    """A 100% session NEVER stops automatically at target or time."""
    if manual_stop or emergency:
        return True
    if target == 100:
        return False
    if soc is None:
        return True  # Lost battery telemetry on an owned sub-100% test.
    try:
        return not isfinite(float(soc)) or float(soc) >= target
    except (ValueError, TypeError):
        return True
