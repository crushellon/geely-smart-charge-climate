"""Real weekly scheduled Geely climate without charging-switch authority.

Independent slots are allowed regardless of charge cable; charging-linked
comfort follows an enabled vehicle-ready schedule. State is persisted across
HA restart so a previously applied climate session isn't fired repeatedly.
"""
import asyncio
from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

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
        self.suppressed_key = self.entry.options.get("climate_suppressed_occurrence")
        self.status = "RECOVERING" if self.active else "IDLE"
        self.message = (
            "Restored scheduled climate session; no duplicate ON sent"
            if self.active else "Ready for scheduled comfort"
        )

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
            self.status = "MANUAL" if self.manual_override else "IDLE"
            self.message = (
                "Manual climate has priority; scheduled climate paused"
                if self.manual_override else
                "Manual climate stopped; future schedules remain enabled"
            )
            self._persist(
                manual_climate_override=self.manual_override,
                climate_suppressed_occurrence=self.suppressed_key,
            )

    async def async_tick(self):
        async with self._lock:
            now = dt_util.now()
            emergency = (
                self.entry.options.get("emergency_stop", False) is True
                or self.manual._raw("input_boolean.ev_emergency_stop") == "on"
            )
            candidates = [] if emergency else candidate_windows(now, self.entry.options)
            available = {c["key"]: c for c in candidates}

            if self.manual_override:
                self.status = "MANUAL"
                self.message = "Manual climate owns cabin settings"
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
                    else:
                        self.active = None
                        self._mark_finished(key)
                        self.status = "ERROR"
                    self.manual._notify()
                    return

                # Existing schedule expired, was disabled, changed time or
                # emergency interlock engaged. Never stop a manual override.
                success = await self.manual.climate.stop_scheduled()
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
                "kind": choice["kind"], "end_at": choice["end_at"].isoformat(),
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
            self.manual._notify()
