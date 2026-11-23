"""Pure, restart-safe battery SOC charging-rate learning.

Only completed uninterrupted intervals with positive SOC gain are accepted.
No vehicle controls and no dependency on a charger integration.
"""

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from statistics import median

MAX_SAMPLES = 20
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 240
MIN_GAIN_POINTS = 2
MAX_SOC_FOR_NORMAL_LEARNING = 90
MIN_VALID_SAMPLES = 2


def effective_fallback_kw(rated_kw: float) -> float:
    """Use an internal provisional battery-side effective power estimate."""
    if not isfinite(rated_kw) or not 1 <= rated_kw <= 22:
        raise ValueError("Charger power must be between 1 and 22 kW")
    return rated_kw * (6.5 / 7.0)


@dataclass
class RateLearner:
    """Collect recent reliable SOC progression intervals."""
    samples: list[float] = field(default_factory=list)
    anchor_soc: float | None = None
    anchor_at: datetime | None = None
    active: bool = False

    def observe(self, *, soc: float | None, charging: bool, at: datetime) -> bool:
        """Observe one HA state update; return True if a sample was saved.

        The caller must only supply timestamps when actual source state events
        arrive, not periodic polling. Gaps/interruptions reset the anchor.
        """
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        valid = soc is not None and isfinite(soc) and 0 <= soc <= 100
        if not charging or not valid:
            self.anchor_soc = None
            self.anchor_at = None
            self.active = False
            return False
        assert soc is not None
        if not self.active or self.anchor_soc is None or self.anchor_at is None:
            self.anchor_soc, self.anchor_at, self.active = soc, at, True
            return False
        elapsed = (at - self.anchor_at).total_seconds() / 60
        delta = soc - self.anchor_soc
        if elapsed <= 0 or delta < 0 or elapsed > MAX_INTERVAL_MINUTES:
            self.anchor_soc, self.anchor_at = soc, at
            return False
        if elapsed < MIN_INTERVAL_MINUTES or delta < MIN_GAIN_POINTS:
            return False
        if soc > MAX_SOC_FOR_NORMAL_LEARNING:
            # Near-full top-off may be tapered; do not distort normal scheduling.
            self.anchor_soc, self.anchor_at = soc, at
            return False
        rate = delta * 60 / elapsed
        self.anchor_soc, self.anchor_at = soc, at
        if not (0 < rate <= 40):
            return False
        # A single distorted Geely update cannot skew the moving median.
        self.samples.append(rate)
        del self.samples[:-MAX_SAMPLES]
        return True

    @property
    def learned_rate(self) -> float | None:
        """Use a robust median only after several valid observations."""
        return median(self.samples) if len(self.samples) >= MIN_VALID_SAMPLES else None

    def to_storage(self) -> dict:
        """Persist valid samples only, never assume an active session survived restart."""
        return {"samples": list(self.samples)}

    @classmethod
    def from_storage(cls, payload: dict | None) -> "RateLearner":
        values = (payload or {}).get("samples", [])
        if not isinstance(values, list):
            return cls()
        clean = [
            float(v) for v in values
            if isinstance(v, (int, float)) and isfinite(v) and 0 < v <= 40
        ]
        return cls(samples=clean[-MAX_SAMPLES:])
