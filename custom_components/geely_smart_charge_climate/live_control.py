"""Opt-in, manual-only live EX5 charging test controller.

No scheduled starts, no climate commands, and no commands until a user
explicitly arms AND presses Start test. Never controls Tesla wallboxes.
"""
import asyncio
from datetime import timedelta
import logging

from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change_event, async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import CONF_BATTERY_ENTITY, CONF_CHARGING_SWITCH
from .discovery import discover_plug_entity
from .live_safety import (
    EMERGENCY_STOP, LEGACY_ACTIVE, LEGACY_CONTROLLER, OLD_FULL_CHARGE,
    PUBLIC_MODE, start_preflight, should_stop_owned_session,
)

_LOGGER = logging.getLogger(__name__)
MONITORED_GUARDS = (
    LEGACY_CONTROLLER, LEGACY_ACTIVE, OLD_FULL_CHARGE, PUBLIC_MODE,
    EMERGENCY_STOP,
)


class LiveChargeController:
    """Conservative, ephemeral owner of explicitly started charge sessions."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.battery = entry.data[CONF_BATTERY_ENTITY]
        self.charging_switch = entry.data[CONF_CHARGING_SWITCH]
        self.plug = discover_plug_entity(hass, self.battery)
        self.armed = False  # Never persisted, auto-disarmed at HA startup.
        self.owned = False
        self.target = 80  # Requested next manual test; not a scheduled target.
        self.active_target = None
        self.started_at = None
        self.status = "DISARMED"
        self.message = "Manual live charging test is disarmed"
        self._lock = asyncio.Lock()
        self._callbacks = []
        self._unsubs = []

    def listen(self, callback_fn):
        self._callbacks.append(callback_fn)

        def remove():
            if callback_fn in self._callbacks:
                self._callbacks.remove(callback_fn)
        return remove

    @callback
    def _notify(self):
        for fn in tuple(self._callbacks):
            fn()

    def _state(self, entity_id):
        return self.hass.states.get(entity_id) if entity_id else None

    def _raw(self, entity_id):
        state = self._state(entity_id)
        return state.state if state else None

    def _guards(self):
        return {key: self._raw(key) for key in MONITORED_GUARDS}

    def preflight(self):
        guards = self._guards()
        # A deliberately missing legacy helper on a new HA installation is
        # harmless. An existing failed/unavailable helper blocks live testing.
        return start_preflight(
            armed=self.armed,
            battery=self._raw(self.battery),
            plugged=self._raw(self.plug),
            charging=self._raw(self.charging_switch),
            target=self.target,
            legacy_states=guards,
        )

    async def async_start_listening(self):
        entities = [self.battery, self.charging_switch, *MONITORED_GUARDS]
        if self.plug:
            entities.append(self.plug)

        @callback
        def changed(_event):
            self.hass.async_create_task(self.async_tick())

        @callback
        def periodic(_now):
            self.hass.async_create_task(self.async_tick())

        self._unsubs.append(
            async_track_state_change_event(self.hass, entities, changed)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, periodic, timedelta(seconds=15))
        )

    async def async_arm(self, enabled):
        async with self._lock:
            if not enabled and self.owned:
                await self._stop_locked("User disarmed live test")
            self.armed = bool(enabled)
            if not self.owned:
                self.status = "ARMED" if enabled else "DISARMED"
                self.message = ("Press Start test to issue a manual charge request"
                                if enabled else "Live test is disarmed")
            self._notify()

    async def async_set_target(self, value):
        if isinstance(value, bool) or int(value) != value or not 50 <= value <= 100:
            raise ValueError("Manual test target must be 50–100%")
        self.target = int(value)
        self._notify()

    async def async_start(self):
        async with self._lock:
            if self.owned:
                self.message = "Already managing a live test session"
                self._notify()
                return
            reason = self.preflight()
            if reason:
                self.status = "BLOCKED"
                self.message = reason
                self._notify()
                return
            self.owned = True
            self.active_target = self.target
            self.started_at = dt_util.utcnow()
            self.status = "STARTING"
            self.message = f"Sending Geely charging start for target {self.active_target}%"
            self._notify()
            try:
                await self.hass.services.async_call(
                    "switch", "turn_on",
                    {"entity_id": self.charging_switch},
                    blocking=True,
                )
            except Exception as exc:
                _LOGGER.exception("Geely live test start failed")
                # The request may have reached the vehicle before HA errored.
                await self._stop_locked("Start failed; attempted safe stop")
                self.status = "ERROR"
                self.message = f"Start service error: {type(exc).__name__}"
                self._notify()
                return
            self.status = "RUNNING"
            self.message = (f"Live manual test active, {self.active_target}% target"
                            if self.active_target < 100
                            else "Live 100% test: Geely controls termination")
            self._notify()

    async def _stop_locked(self, reason):
        if not self.owned:
            self.message = "No integration-owned charge session to stop"
            self._notify()
            return
        self.status = "STOPPING"
        self.message = reason
        self._notify()
        try:
            await self.hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": self.charging_switch},
                blocking=True,
            )
        except Exception as exc:
            _LOGGER.exception("Failed to stop integration-owned charging test")
            self.status = "ERROR"
            self.message = f"Stop service error: {type(exc).__name__}"
            self._notify()
            return  # Keep ownership so stop can be retried.
        self.owned = False
        self.armed = False
        self.active_target = None
        self.started_at = None
        self.status = "STOPPED"
        self.message = reason
        self._notify()

    async def async_stop(self):
        async with self._lock:
            await self._stop_locked("User requested manual test stop")

    async def async_tick(self):
        """Watch an owned session; never schedule an unattended start."""
        async with self._lock:
            if not self.owned:
                return
            guards = self._guards()
            if any(guards.get(key) not in (None, "off") for key in MONITORED_GUARDS):
                # If public mode is enabled, do not issue a command that could
                # affect public charging; disarm and require manual inspection.
                if guards.get(PUBLIC_MODE) == "on":
                    self.armed = False
                    self.owned = False
                    self.status = "BLOCKED"
                    self.message = "Public charging mode enabled; live control released"
                    self._notify()
                    return
                await self._stop_locked("Safety interlock activated")
                return

            raw = self._raw(self.battery)
            try:
                soc = float(raw)
            except (ValueError, TypeError):
                soc = None
            if should_stop_owned_session(
                target=self.active_target, soc=soc, emergency=False
            ):
                await self._stop_locked(
                    "Target reached or battery telemetry unavailable"
                )
                return

            # Only after an initial Geely response grace period can an observed
            # switch OFF mean the car completed or ended the session.
            if (
                self.started_at
                and dt_util.utcnow() - self.started_at >= timedelta(seconds=60)
                and self._raw(self.charging_switch) == "off"
            ):
                self.owned = False
                self.armed = False
                self.active_target = None
                self.status = "COMPLETED"
                self.message = "Geely reports charging stopped"
                self._notify()

    async def async_shutdown(self):
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self.owned and self.active_target is not None and self.active_target < 100:
            async with self._lock:
                await self._stop_locked("Integration unloading: stop owned test")
        self.armed = False
        self._notify()
