"""Real weekly scheduled Geely climate without charging-switch authority.

Independent slots are allowed regardless of charge cable; charging-linked
comfort follows an enabled vehicle-ready schedule. State is persisted across
HA restart so a previously applied climate session isn't fired repeatedly.
"""
import asyncio
from datetime import datetime, timedelta

from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

MANUAL_COMFORT_MAX = timedelta(minutes=30)
MANUAL_OFF_RETRY = timedelta(seconds=60)
MANUAL_OFF_MAX_ATTEMPTS = 3

from .climate_windows import candidate_windows


class ScheduledClimateController:
    def __init__(self, manual):
        self.manual = manual
        self.entry = manual.entry
        self.hass = manual.hass
        self._lock = asyncio.Lock()
        saved = self.entry.options.get("scheduled_climate_session", {})
        self.active = saved if isinstance(saved, dict) and saved.get("active") else None
        self.completed = list(self.entry.options.get("climate_completed_occurrences", []))
        self.manual_override = (
            self.entry.options.get("manual_climate_override", False) is True
        )
        saved_expiry = self.entry.options.get("manual_climate_expires_at")
        try:
            self.manual_expires_at = datetime.fromisoformat(saved_expiry)
            if self.manual_expires_at.tzinfo is None:
                raise ValueError("Timezone missing")
        except (TypeError, ValueError):
            # Previous versions could leave a permanent MANUAL override.
            # Expire such legacy overrides on next startup tick.
            self.manual_expires_at = (
                dt_util.now() if self.manual_override else None
            )
        self._manual_off_retry_at = None
        self._manual_off_attempts = 0
        self._manual_timer_unsub = None
        self.suppressed_key = self.entry.options.get("climate_suppressed_occurrence")
        self.status = "RECOVERING" if self.active else "IDLE"
        self.message = (
            "Restored scheduled climate session; no duplicate ON sent"
            if self.active else "Ready for scheduled comfort"
        )

    def _push_climate(self, action, session, success=True):
        notifier = getattr(self.manual, "push", None)
        if notifier is None:
            return
        climate_entity = self.manual.climate.entities.get("climate")
        reading = self.manual._raw(climate_entity)
        notifier.climate_event(
            key=session["key"], action=action, kind=session["kind"],
            setting=session.get("settings"),
            time=session.get("ready_by"),
            vehicle_state=reading, success=success,
        )

    def _arm_manual_expiry(self):
        """Schedule exact cutoff; periodic 15-second tick is fallback.

        An already-expired session is handled on the next normal tick/restore.
        The Home Assistant timer is cancelled and replaced on each press.
        """
        if self._manual_timer_unsub is not None:
            self._manual_timer_unsub()
            self._manual_timer_unsub = None
        if not self.manual_override:
            return
        due = self._manual_off_retry_at or self.manual_expires_at
        if due is None or due <= dt_util.now():
            return

        def expire(_now):
            self._manual_timer_unsub = None
            self.hass.async_create_task(self.async_tick())

        self._manual_timer_unsub = async_track_point_in_time(
            self.hass, expire, due
        )

    async def async_shutdown(self):
        """Cancel process timer; persisted deadline survives HA restart."""
        if self._manual_timer_unsub is not None:
            self._manual_timer_unsub()
            self._manual_timer_unsub = None

    async def async_manual_result(self, action, success):
        """Keep auto-OFF even when Geely cloud did not acknowledge manual ON.

        A failed service request can still reach the car asynchronously.
        Immediately clearing the timer on failure could then leave cabin
        climate on indefinitely. The existing 30-minute expiry stays armed.
        """
        if action == "off" or success:
            return
        async with self._lock:
            self.status = "ERROR"
            self.message = (
                "Manual comfort command unconfirmed by Geely; "
                "automatic 30-minute OFF remains armed"
            )
            self.manual._notify()

    def _persist(self, **changes):
        self.manual._save_options(**changes)
        self.manual._notify()

    def _mark_finished(self, key):
        if key and key not in self.completed:
            self.completed.append(key)
            self.completed = self.completed[-35:]
        self._persist(
            scheduled_climate_session={"active": False},
            climate_completed_occurrences=list(self.completed),
        )

    async def async_manual_override(self, action):
        """Manual Cool/Warm/Custom takes priority; Off releases it for later slots."""
        async with self._lock:
            # Do not turn off cabin when a manual command is about to replace
            # scheduled commands. Suppress this occurrence, so an OFF command
            # cannot cause a currently open schedule to immediately restart.
            candidates = candidate_windows(dt_util.now(), self.entry.options)
            key = self.active["key"] if self.active else (
                candidates[0]["key"] if candidates else None
            )
            if key:
                self.suppressed_key = key
            if self.active:
                self._mark_finished(self.active["key"])
                self.active = None
            self.manual_override = action != "off"
            self.manual_expires_at = (
                dt_util.now() + MANUAL_COMFORT_MAX
                if self.manual_override else None
            )
            self._manual_off_attempts = 0
            self._manual_off_retry_at = None
            self._arm_manual_expiry()
            self.status = "MANUAL" if self.manual_override else "IDLE"
            self.message = (
                "Manual climate active; automatic OFF in 30 minutes"
                if self.manual_override else
                "Manual climate stopped; future schedules remain enabled"
            )
            self._persist(
                manual_climate_override=self.manual_override,
                manual_climate_expires_at=(
                    self.manual_expires_at.isoformat()
                    if self.manual_expires_at is not None else None
                ),
                climate_suppressed_occurrence=self.suppressed_key,
                manual_climate_timeout_error=None,
            )

    async def async_tick(self):
        async with self._lock:
            now = dt_util.now()
            emergency = (
                self.entry.options.get("emergency_stop", False) is True
                or self.manual._raw("input_boolean.ev_emergency_stop") == "on"
            )
            # The Climate Scheduler master switch belongs ONLY to the
            # independent appointments on that tab. Charging-linked comfort
            # belongs to its charging day and has its own enabled switch.
            # Previously this master suppressed both types and silently
            # disabled Monday's enabled Cool/Warm departure comfort.
            independent_enabled = (
                self.entry.options.get("scheduled_climate_enabled", False) is True
            )
            candidates = (
                candidate_windows(now, self.entry.options)
                if not emergency else []
            )
            if not independent_enabled:
                candidates = [
                    c for c in candidates if c["kind"] != "independent"
                ]
            if self.manual.public_mode():
                candidates = [
                    c for c in candidates if c["kind"] != "linked"
                ]
            available = {c["key"]: c for c in candidates}

            if self.manual_override:
                # Every manual Cool/Warm/Custom starts a fresh absolute
                # 30-minute limit. The clock survives Home Assistant restarts.
                if (self.manual_expires_at is None
                        or now >= self.manual_expires_at):
                    if (self._manual_off_retry_at is not None
                            and now < self._manual_off_retry_at):
                        self._arm_manual_expiry()
                        return
                    self._manual_off_retry_at = None
                    self._manual_off_attempts += 1
                    # Uses the SAME real Climate + seats OFF service path;
                    # never calls any Geely charging switch.
                    off_ok = await self.manual.climate.apply("off")
                    if off_ok:
                        if hasattr(self.manual, "push"):
                            self.manual.push.emit(
                                f"manual:climate:timeout:{self.manual_expires_at}",
                                "Geely manual comfort timed out",
                                "30 minutes elapsed. Cabin, driver/passenger "
                                "seats and steering-wheel OFF requests accepted; "
                                "check Geely's actual climate state if needed.",
                            )
                        self.manual_override = False
                        self.manual_expires_at = None
                        self._manual_off_attempts = 0
                        self._arm_manual_expiry()
                        self.status = "IDLE"
                        self.message = (
                            "Manual comfort automatically switched OFF after 30 minutes; "
                            "future climate schedules enabled"
                        )
                        self._persist(
                            manual_climate_override=False,
                            manual_climate_expires_at=None,
                        )
                        return
                    if self._manual_off_attempts >= MANUAL_OFF_MAX_ATTEMPTS:
                        if hasattr(self.manual, "push"):
                            self.manual.push.emit(
                                f"manual:climate:timeout-failed:{self.manual_expires_at}",
                                "Geely manual comfort OFF FAILED",
                                "Automatic 30-minute OFF was attempted three "
                                "times without complete service acknowledgement. "
                                "Check vehicle cabin, seats and wheel directly.",
                            )
                        # Do not leave the scheduling controller locked in
                        # MANUAL forever, but preserve a visible failure.
                        self.manual_override = False
                        self.manual_expires_at = None
                        self._arm_manual_expiry()
                        self.status = "ERROR"
                        self.message = (
                            "Manual comfort auto-OFF failed three times; "
                            "inspect Geely vehicle climate directly"
                        )
                        self._persist(
                            manual_climate_override=False,
                            manual_climate_expires_at=None,
                            manual_climate_timeout_error=self.message,
                        )
                        return
                    self._manual_off_retry_at = now + MANUAL_OFF_RETRY
                    self._arm_manual_expiry()
                    self.status = "ERROR"
                    self.message = (
                        f"Manual climate auto-OFF unconfirmed; attempt "
                        f"{self._manual_off_attempts} of {MANUAL_OFF_MAX_ATTEMPTS}, "
                        "retrying in one minute"
                    )
                    self.manual._notify()
                    return

                if self._manual_timer_unsub is None:
                    self._arm_manual_expiry()
                self.status = "MANUAL"
                self.message = (
                    "Manual comfort active until "
                    f"{self.manual_expires_at.astimezone(now.tzinfo).strftime('%H:%M:%S')}"
                )
                self.manual._notify()
                return

            if self.active:
                key = self.active["key"]
                if key in available and self.active.get("applied", False):
                    desired = available[key]
                    # Keep an active occurrence through schedule overlaps.
                    # Live profile edits are reapplied only if materially
                    # different, with a 60-second command cooldown.
                    old = self.active.get("settings")
                    new = {
                        k: desired[k] for k in
                        ("temperature", "driver_seat", "passenger_seat", "steering_heat")
                    }
                    try:
                        last = datetime.fromisoformat(self.active["last_applied_at"])
                    except (KeyError, TypeError, ValueError):
                        last = now
                    if old != new and (now - last) >= timedelta(seconds=60):
                        success = await self.manual.climate.apply_scheduled(new)
                        if success:
                            self.active = {
                                **self.active, "settings": new,
                                "last_applied_at": now.isoformat(),
                            }
                            self._persist(scheduled_climate_session=self.active)
                        else:
                            self.status = "ERROR"
                            self.message = "Unable to apply updated scheduled comfort"
                            self.manual._notify()
                            return
                    self.status = "RUNNING"
                    self.message = f"Scheduled cabin comfort active: {key}"
                    self.manual._notify()
                    return

                if key in available and not self.active.get("applied", False):
                    # A crash can occur between recording intent and sending
                    # Geely cloud requests. Make one idempotent recovery attempt.
                    desired = available[key]
                    success = await self.manual.climate.apply_scheduled(desired)
                    if success:
                        self.active = {
                            **self.active, "applied": True,
                            "settings": {
                                k: desired[k] for k in
                                ("temperature", "driver_seat",
                                 "passenger_seat", "steering_heat")
                            },
                            "last_applied_at": now.isoformat(),
                        }
                        self._persist(scheduled_climate_session=self.active)
                        self.status = "RUNNING"
                        self._push_climate("on", self.active)
                    else:
                        self.active = None
                        self._mark_finished(key)
                        self.status = "ERROR"
                    self.manual._notify()
                    return

                # Existing schedule expired, was disabled, changed time or
                # emergency interlock engaged. Never stop a manual override.
                finished = dict(self.active)
                success = await self.manual.climate.stop_scheduled()
                self._push_climate("off", finished, success=success)
                old_key = self.active["key"]
                self.active = None
                self._mark_finished(old_key)
                self.status = "IDLE" if success else "ERROR"
                self.message = (
                    "Scheduled climate finished and cabin off"
                    if success else "Scheduled climate OFF unconfirmed; check vehicle"
                )
                self.manual._notify()
                return

            if emergency:
                self.status = "BLOCKED"
                self.message = "Emergency interlock; climate schedules suppressed"
                self.manual._notify()
                return
            if not independent_enabled and not candidates:
                # The independent scheduler is disabled, but do not imply
                # Monday's linked comfort is disabled: it has its own switch.
                linked_settings = self.entry.options.get(
                    "charging_linked_comfort", {}
                )
                charge_days = self.entry.options.get("weekly_schedule", {})
                linked_configured = (
                    self.entry.options.get("automatic_charging_enabled") is True
                    and not self.manual.public_mode()
                    and any(
                        isinstance(config, dict)
                        and config.get("enabled") is True
                        and charge_days.get(day, {}).get("enabled") is True
                        for day, config in linked_settings.items()
                    )
                )
                self.status = "WAITING" if linked_configured else "DISABLED"
                self.message = (
                    "Independent appointments off; awaiting charging-linked comfort"
                    if linked_configured else
                    "Independent climate appointments disabled"
                )
                self.manual._notify()
                return

            choice = next(
                (candidate for candidate in candidates
                 if candidate["key"] != self.suppressed_key
                 and candidate["key"] not in self.completed),
                None,
            )
            if choice is None:
                self.status = "WAITING" if candidates else "IDLE"
                self.message = (
                    "Current occurrence already completed or suppressed"
                    if candidates else "Awaiting next climate appointment"
                )
                self.manual._notify()
                return

            settings = {
                k: choice[k] for k in
                ("temperature", "driver_seat", "passenger_seat", "steering_heat")
            }
            self.active = {
                "active": True, "key": choice["key"],
                "kind": choice["kind"],
                "ready_by": choice["ready_by"].isoformat(),
                "end_at": choice["end_at"].isoformat(),
                "settings": settings, "applied": False,
                "last_applied_at": now.isoformat(),
            }
            # Record ownership BEFORE a potentially long Geely cloud call.
            # After restart this occurrence isn't blindly started twice.
            self._persist(scheduled_climate_session=self.active)
            self.status = "STARTING"
            self.message = f"Starting {choice['kind']} climate {choice['key']}"
            self.manual._notify()
            success = await self.manual.climate.apply_scheduled(settings)
            if not success:
                key = self.active["key"]
                self.active = None
                self._mark_finished(key)
                self.status = "ERROR"
                self.message = f"Geely climate command failed for {key}"
                self.manual._notify()
                return
            self.active = {
                **self.active, "applied": True, "last_applied_at": now.isoformat()
            }
            self._persist(scheduled_climate_session=self.active)
            self.status = "RUNNING"
            self.message = f"{choice['kind']} comfort scheduled until {choice['end_at'].isoformat()}"
            self._push_climate("on", self.active)
            self.manual._notify()
