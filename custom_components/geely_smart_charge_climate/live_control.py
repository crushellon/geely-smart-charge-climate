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

from .const import CONF_BATTERY_ENTITY, CONF_CHARGING_SWITCH, CONF_CHARGING_POWER
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
        self.charging_power = entry.data.get(CONF_CHARGING_POWER)
        self.plug = discover_plug_entity(hass, self.battery)
        self.armed = False  # Never persisted, auto-disarmed at HA startup.
        self.owned = False
        self.target = 80  # Requested next manual test; not a scheduled target.
        self.active_target = None
        self.started_at = None
        self.observed_active = False
        self.stop_requested_at = None
        self.stop_attempts = 0
        self.stop_note = ""
        self.off_observations = 0
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
        power = self._raw(self.charging_power)
        if self.charging_power:
            try:
                if float(power) > 0.25:
                    return "Geely reports charging power already flowing"
                if float(power) < 0:
                    return "Charging power reading invalid"
            except (ValueError, TypeError):
                return "Charging power unavailable: refresh vehicle data"
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
        if self.charging_power:
            entities.append(self.charging_power)
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
            self.observed_active = False
            self.stop_requested_at = None
            self.stop_attempts = 0
            self.off_observations = 0
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
        """Request stop and retain session ownership until confirmed.

        Geely cloud acknowledgements are not proof that charging has stopped.
        """
        if not self.owned:
            self.message = "No integration-owned charge session to stop"
            self._notify()
            return
        self.stop_note = reason
        self.stop_requested_at = dt_util.utcnow()
        self.stop_attempts += 1
        self.status = "STOP_REQUESTED"
        self.message = f"{reason}; checking Geely confirmation"
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
            self.message = f"Stop service error: {type(exc).__name__}; verify in car"
            self._notify()
            return  # Keep ownership and allow another explicit stop.

    def _finish(self, status, message):
        """Finish only after vehicle state indicates charging has stopped."""
        self.owned = False
        self.armed = False
        self.active_target = None
        self.started_at = None
        self.observed_active = False
        self.stop_requested_at = None
        self.stop_attempts = 0
        self.off_observations = 0
        self.status = status
        self.message = message
        self._notify()

    def _power_active(self):
        if not self.charging_power:
            return False
        try:
            return float(self._raw(self.charging_power)) > 0.25
        except (TypeError, ValueError):
            return False

    def _stopped_state(self):
        """Require positive switch OFF plus no known charging power."""
        return (
            self._raw(self.charging_switch) == "off"
            and not self._power_active()
        )

    async def async_stop(self):
        async with self._lock:
            await self._stop_locked("User requested manual test stop")

    async def async_tick(self):
        """Watch an owned session; never schedule an unattended start."""
        async with self._lock:
            if not self.owned:
                return
            guards = self._guards()
            if guards.get(PUBLIC_MODE) == "on":
                # Avoid commanding a public charge if the car was relocated.
                self._finish(
                    "BLOCKED",
                    "Public mode enabled; live test released. Check charge manually",
                )
                return

            if self.stop_requested_at is not None:
                self.off_observations = (
                    self.off_observations + 1 if self._stopped_state() else 0
                )
                if self.off_observations >= 2:
                    self._finish("STOPPED", f"{self.stop_note}; Geely reports stopped")
                    return
                if (
                    dt_util.utcnow() - self.stop_requested_at >= timedelta(seconds=30)
                ):
                    if self.stop_attempts < 3:
                        await self._stop_locked("Retrying stop confirmation")
                    else:
                        self.status = "ERROR"
                        self.message = "Stop unconfirmed after 3 attempts: verify in car"
                        self._notify()
                return

            if any(guards.get(key) not in (None, "off") for key in MONITORED_GUARDS):
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

            if self._raw(self.charging_switch) == "on" or self._power_active():
                self.observed_active = True
                self.off_observations = 0
            elif self.observed_active:
                self.off_observations += 1

            elapsed = (
                dt_util.utcnow() - self.started_at
                if self.started_at else timedelta(0)
            )
            if not self.observed_active and elapsed >= timedelta(minutes=3):
                await self._stop_locked("Charge did not confirm after 3 minutes")
                return
            if self.observed_active and self.off_observations >= 2 and elapsed >= timedelta(seconds=60):
                self._finish("COMPLETED", "Geely reports charging ended")
                return

    async def async_shutdown(self):
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self.owned and self.active_target is not None and self.active_target < 100:
            async with self._lock:
                await self._stop_locked("Integration unloading: stop owned test")
        self.armed = False
        self._notify()
