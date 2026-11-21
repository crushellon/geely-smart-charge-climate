"""Pure charging authorisation policy, evaluated without vehicle commands.

A ready-by day may start charging on the previous date. An authorisation exists
only during a computed charging window; no day is enabled by default.
Public charging is excluded using an explicit user-operated switch, not location
inference. The vehicle owns normal 100% charge termination.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil, isfinite

from .weekly_schedule import DAY_NAMES, validate_day


@dataclass(frozen=True)
class ChargeDecision:
    action: str  # WAIT, START, AUTHORISED, STOP, BLOCKED, UNKNOWN
    reason: str
    day: str | None = None
    target: int | None = None
    start_at: datetime | None = None
    ready_by: datetime | None = None


def decide(
    *, now: datetime, schedule: dict, soc: float | None, charging: bool,
    plugged: bool | None,
    rate_kw: float = 6.5, capacity_kwh: float = 68.39,
    public_mode: bool = False, emergency: bool = False,
    legacy_clear: bool = True, manual_owned: bool = False,
    buffer_minutes: int = 15,
) -> ChargeDecision:
    """Evaluate user-authorised charging, without assuming vehicle location.

    The user must turn on Public Charging Mode whenever away/public charging.
    """
    def result(action, reason, plan=None):
        return ChargeDecision(
            action, reason,
            plan["day"] if plan else None,
            plan["target"] if plan else None,
            plan["start_at"] if plan else None,
            plan["ready_by"] if plan else None,
        )

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Local timezone-aware datetime required")
    if not isfinite(rate_kw) or rate_kw <= 0 or not isfinite(capacity_kwh) or capacity_kwh <= 0:
        return result("UNKNOWN", "Charging rate not available")
    if public_mode:
        return result("BLOCKED", "Public charging mode: vehicle commands suppressed")
    if emergency:
        return result("BLOCKED", "Emergency stop active")
    if not legacy_clear:
        return result("BLOCKED", "Another charging controller may be active")
    if manual_owned:
        return result("AUTHORISED", "Integration-owned manual charge is in progress")
    if plugged is not True:
        return result("UNKNOWN", "Vehicle charger connection not confirmed")
    if soc is None or not isfinite(soc) or not 0 <= soc <= 100:
        return result("UNKNOWN", "Battery state unavailable")

    candidates = []
    for index, day in enumerate(DAY_NAMES):
        item = validate_day(schedule.get(day, {}))
        if not item["enabled"]:
            continue
        hh, mm = map(int, item["ready_time"].split(":"))
        # Include this week's deadline and next week's so we don't mistake
        # yesterday-night-to-this-morning windows for next week.
        days_until = (index - now.weekday()) % 7
        next_ready = (now + timedelta(days=days_until)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if next_ready < now:
            next_ready += timedelta(days=7)
        for ready in (next_ready, next_ready - timedelta(days=7)):
            target = item["target"]
            remaining = max(0.0, target - soc)
            minutes = ceil(remaining / 100 * capacity_kwh / rate_kw * 60)
            start = ready - timedelta(minutes=minutes + (buffer_minutes if minutes else 0))
            candidates.append({
                "day": day, "target": target,
                "start_at": start, "ready_by": ready,
            })

    active = [
        x for x in candidates
        if x["start_at"] <= now < x["ready_by"]
    ]
    # If the car is still actively charging a scheduled 100% session, the
    # target itself must never trigger a stop. Real owned sessions are latched
    # separately by the controller until Geely ends them.
    if charging and soc >= 100:
        full = [
            x for x in candidates if x["target"] == 100
            and x["ready_by"].date() == now.date()
            and now < x["ready_by"]
        ]
        if full:
            full.sort(key=lambda x: x["ready_by"])
            return result("AUTHORISED", "Full-charge termination belongs to Geely", full[0])
    active.sort(key=lambda x: (x["ready_by"], x["day"]))
    if active:
        plan = active[0]
        if charging:
            if plan["target"] == 100:
                return result("AUTHORISED", "100% charging: Geely controls termination", plan)
            if soc >= plan["target"]:
                return result("STOP", "Scheduled target reached", plan)
            return result("AUTHORISED", "Charging within scheduled window", plan)
        if soc >= plan["target"]:
            return result("WAIT", "Target already reached; no restart", plan)
        return result("START", "Scheduled charging window open", plan)

    if charging:
        return result("STOP", "Unexpected charging outside authorised schedule")

    future = [p for p in candidates if p["ready_by"] > now]
    if future:
        soonest = min(future, key=lambda p: p["ready_by"])
        return result("WAIT", "Waiting for scheduled charging window", soonest)
    return result("WAIT", "No charging schedule enabled")
