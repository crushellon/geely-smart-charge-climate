"""Source-grounded vehicle charging activity, independent from session ownership.

Geely Connect sometimes reports charging switch ON before positive power
appears. These signals are OBSERVATIONS, not proof of controller authorisation.
"""


def vehicle_activity(switch_state, power_state):
    """Return (status, numeric_power) for the Geely telemetry sources only.

    Tesla power is optionally displayed by the dashboard but never grants
    authority for Geely charging commands.
    """
    try:
        power = float(power_state)
        if not 0 <= power < float("inf"):
            power = None
    except (ValueError, TypeError):
        power = None
    if power is not None and power > 0.25:
        return "CHARGING", power
    if switch_state == "on":
        return "CHARGING_REPORTED", power
    if switch_state == "off" and power is not None and power <= 0.25:
        return "STOPPED", power
    return "UNKNOWN", power
