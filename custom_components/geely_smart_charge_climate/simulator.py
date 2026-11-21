"""Pure charging decision simulation; NO Home Assistant or vehicle APIs.

This models potential decisions, not an active charging session. In particular,
100% belongs to the vehicle and must never cause a controller STOP command.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil, isfinite
from typing import Literal

Action = Literal[
    "WAIT", "START", "STOP_AT_TARGET", "VEHICLE_MANAGED",
    "COMPLETE", "BLOCKED", "NO_CHARGE_NEEDED", "UNKNOWN",
]


@dataclass(frozen=True)
class Simulation:
    action: Action
    reason: str
    start_at: datetime | None
    ready_by: datetime
    remaining_minutes: int | None
    termination: str


def next_deadline(now: datetime, time_of_day: str) -> datetime:
    """Resolve the next occurrence of a local wall-clock deadline."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    try:
        hour, minute = (int(part) for part in time_of_day.split(":"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Time must be HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be HH:MM")
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if deadline <= now:
        deadline += timedelta(days=1)
    return deadline


def simulate(
    *,
    now: datetime,
    ready_by: datetime,
    soc: float | None,
    target: float,
    effective_kw: float,
    usable_kwh: float,
    charging: bool,
    enabled: bool = True,
    plugged: bool | None = None,
    emergency: bool = False,
    public_mode: bool = False,
    completed: bool = False,
    buffer_minutes: int = 15,
) -> Simulation:
    """Compute an advisory decision. Never calls a device service."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if ready_by.tzinfo is None or ready_by.utcoffset() is None:
        raise ValueError("ready_by must be timezone-aware")
    if not 50 <= target <= 100:
        raise ValueError("Target outside 50-100")
    if not (isfinite(effective_kw) and effective_kw > 0 and isfinite(usable_kwh) and usable_kwh > 0):
        raise ValueError("Invalid rate or capacity")
    if buffer_minutes < 0:
        raise ValueError("Negative buffer")

    termination = "vehicle_managed" if target == 100 else "controller_stop"

    def outcome(action: Action, reason: str, start: datetime | None = None,
                remaining: int | None = None) -> Simulation:
        return Simulation(action, reason, start, ready_by, remaining, termination)

    if soc is None or not isfinite(soc) or not (0 <= soc <= 100):
        return outcome("UNKNOWN", "Battery reading unavailable")
    remaining = ceil(max(0, target - soc) / 100 * usable_kwh / effective_kw * 60)
    start_at = ready_by - timedelta(minutes=remaining + (buffer_minutes if remaining else 0))

    # Safety and explicit completion suppress any simulated restart.
    if emergency or public_mode or not enabled:
        return outcome("BLOCKED", "Charging is not authorised", start_at, remaining)
    if completed:
        return outcome("COMPLETE", "This session already completed", start_at, remaining)

    # A full-charge session is never cut off by HA on the basis of SOC or deadline.
    if target == 100 and soc >= 100:
        return outcome("VEHICLE_MANAGED" if charging else "COMPLETE",
                       "Leave termination to the vehicle" if charging
                       else "Vehicle full-charge completion", start_at, remaining)

    if target < 100 and soc >= target:
        return outcome("STOP_AT_TARGET" if charging else "NO_CHARGE_NEEDED",
                       "Target achieved", start_at, remaining)

    if charging:
        return outcome("VEHICLE_MANAGED" if target == 100 else "WAIT",
                       "Charging already in progress; do not issue another start",
                       start_at, remaining)

    if plugged is False:
        return outcome("BLOCKED", "Vehicle not plugged in", start_at, remaining)
    if plugged is None:
        return outcome("UNKNOWN", "Plug status not configured; cannot authorise start",
                       start_at, remaining)
    if now >= start_at and now < ready_by:
        return outcome("START", "Within planned charge window", start_at, remaining)
    if now >= ready_by:
        return outcome("BLOCKED", "Deadline passed; no automatic late start",
                       start_at, remaining)
    return outcome("WAIT", "Waiting for estimated start time", start_at, remaining)
