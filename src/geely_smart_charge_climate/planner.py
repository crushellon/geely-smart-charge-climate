"""Pure, side-effect-free charging estimates and plans.

No charging commands are issued by this module.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Literal, Sequence

TerminationPolicy = Literal["controller_stop", "vehicle_managed"]


@dataclass(frozen=True)
class ChargeSample:
    """One completed, uninterrupted charging interval.

    Percentage points gained, not percent relative to the starting value.
    """
    start_soc: float
    end_soc: float
    elapsed_minutes: float


@dataclass(frozen=True)
class Estimate:
    percentage_points_per_hour: float
    source: Literal["learned", "fallback"]
    sample_count: int


@dataclass(frozen=True)
class ChargePlan:
    target_soc: float
    required_minutes: int
    start_at: datetime
    ready_by: datetime
    termination: TerminationPolicy
    rate_source: str


def termination_policy(target_soc: float) -> TerminationPolicy:
    if not 50 <= target_soc <= 100:
        raise ValueError("Target must be between 50% and 100%")
    return "vehicle_managed" if target_soc == 100 else "controller_stop"


def estimate_charge_rate(
    samples: Sequence[ChargeSample],
    *,
    fallback_kw: float,
    usable_capacity_kwh: float,
    min_soc_gain: float = 3.0,
    min_elapsed_minutes: float = 15.0,
) -> Estimate:
    """Robust baseline estimate from SOC progression.

    Deliberately excludes short/low-gain intervals and nonpositive rates.
    Samples should already be labelled as active, uninterrupted charging
    from the caller. This function does not infer charging activity.
    """
    if fallback_kw <= 0 or usable_capacity_kwh <= 0:
        raise ValueError("Fallback power and usable capacity must be positive")
    rates: list[float] = []
    for sample in samples:
        if not (0 <= sample.start_soc <= 100 and 0 <= sample.end_soc <= 100):
            continue
        delta = sample.end_soc - sample.start_soc
        if delta < min_soc_gain or sample.elapsed_minutes < min_elapsed_minutes:
            continue
        rate = 60.0 * delta / sample.elapsed_minutes
        if 0 < rate <= 100:  # reject obviously invalid telemetry
            rates.append(rate)
    if not rates:
        return Estimate(100 * fallback_kw / usable_capacity_kwh, "fallback", 0)
    return Estimate(float(median(rates)), "learned", len(rates))


def plan_charge(
    *,
    current_soc: float,
    target_soc: float,
    ready_by: datetime,
    estimate: Estimate,
    buffer_minutes: int = 15,
) -> ChargePlan:
    """Calculate a target completion time, without executing commands.

    Both times are timezone-aware. If late, the returned start time can be
    in the past: the caller should start immediately and flag the deadline risk.
    """
    if ready_by.tzinfo is None or ready_by.utcoffset() is None:
        raise ValueError("Ready-by must be timezone-aware")
    if not 0 <= current_soc <= 100 or not 50 <= target_soc <= 100:
        raise ValueError("Invalid battery percentage")
    if estimate.percentage_points_per_hour <= 0 or buffer_minutes < 0:
        raise ValueError("Invalid estimate or buffer")
    remaining = max(0.0, target_soc - current_soc)
    from math import ceil
    minutes = ceil(60.0 * remaining / estimate.percentage_points_per_hour)
    start_at = ready_by - timedelta(minutes=minutes + (buffer_minutes if minutes else 0))
    return ChargePlan(target_soc, minutes, start_at, ready_by,
                      termination_policy(target_soc), estimate.source)
