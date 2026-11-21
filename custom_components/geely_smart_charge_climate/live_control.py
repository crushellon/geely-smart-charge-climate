"""Shared Geely-only charge/climate runtime and persistent owner coordination.

Automatic charging uses saved user intent, manual commands temporarily
take priority, and scheduled cabin commands never control Tesla hardware.
"""
import asyncio
from datetime import datetime, timedelta
import logging
from math import isfinite

from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change_event, async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import CONF_BATTERY_ENTITY, CONF_CHARGING_SWITCH, CONF_CHARGING_POWER
from .discovery import discover_plug_entity, discover_charging_power_entity
from .auto_control import AutomaticChargeController
from .manual_climate import ManualClimateController
from .scheduled_climate import ScheduledClimateController
from .vehicle_activity import vehicle_activity
from .live_safety import (
    EMERGENCY_STOP, LEGACY_ACTIVE, LEGACY_CONTROLLER, OLD_FULL_CHARGE,
    PUBLIC_MODE, start_preflight, should_stop_owned_session,
)

_LOGGER = logging.getLogger(__name__)
MANUAL_STOP_SETTLE = timedelta(seconds=30)
MANUAL_STOP_WATCH = timedelta(minutes=5)
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
        self.charging_power = (entry.data.get(CONF_CHARGING_POWER)
                               or discover_charging_power_entity(hass, self.battery))
        self.plug = discover_plug_entity(hass, self.battery)
        # Manual charging is a normal user action, not a staged armed test.
        # 'armed' only remains for compatibility with existing pure policy.
        self.armed = False
        self.owned = False
        saved_target = entry.options.get("manual_charge_target", 80)
        self.target = (int(saved_target)
                       if isinstance(saved_target, (int, float))
                       and not isinstance(saved_target, bool)
                       and 50 <= saved_target <= 100 else 80)
        self.unmanaged_charge = False
        self._unmanaged_stop_observations = 0
        # Cloud states may arrive after integration setup. Do not claim an
        # existing charge is unauthorised before restart telemetry settles.
        self._startup_observation_until = None
        self.active_target = None
        self.started_at = None
        self._manual_recovery_started = None
        self.observed_active = False
        self.stop_requested_at = None
        self.stop_started_at = None
        self.stop_watch_until = None
        self.stop_attempts = 0
        self.stop_note = ""
        self.off_observations = 0
        self.status = "IDLE"
        self.message = "Manual charging ready"
        self._lock = asyncio.Lock()
        self._callbacks = []
        self._unsubs = []
        self.auto = AutomaticChargeController(self)
        self.climate = ManualClimateController(hass, entry, self._notify)
        self.scheduled_climate = ScheduledClimateController(self)
        self._manual_recovery_started = None

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

    def vehicle_activity(self):
        """Read-only physical Geely indication, never charging ownership."""
        return vehicle_activity(
            self._raw(self.charging_switch), self._raw(self.charging_power)
        )

    def _vehicle_indicates_charging(self):
        return self.vehicle_activity()[0] in ("CHARGING", "CHARGING_REPORTED")

    def _observe_unmanaged(self):
        """Keep a pre-existing/unattributed charge outside controller control."""
        if self.owned or self.auto.owned or self.public_mode():
            return
        activity, _ = self.vehicle_activity()
        if self.unmanaged_charge:
            if activity == "STOPPED":
                self._unmanaged_stop_observations += 1
                if self._unmanaged_stop_observations >= 2:
                    self.unmanaged_charge = False
                    self._unmanaged_stop_observations = 0
                    if self.status in ("EXTERNAL", "STOP_REQUESTED"):
                        self.status = "IDLE"
                        self.message = "Previous charge has stopped"
                    self._notify()
                    if hasattr(self.hass, "async_create_task"):
                        self.hass.async_create_task(
                            self.async_reconcile_automatic()
                        )
            else:
                self._unmanaged_stop_observations = 0
        elif (self._startup_observation_until is not None
              and dt_util.utcnow() <= self._startup_observation_until
              and activity in ("CHARGING", "CHARGING_REPORTED")):
            self.unmanaged_charge = True
            self.status = "EXTERNAL"
            self.message = (
                "Charging observed after integration reload; "
                "previous controller ownership not available"
            )
            self._notify()


    def public_mode(self):
        """Persistent integration switch or existing legacy helper is ON."""
        return (
            self.entry.options.get("public_charging_mode", False) is True
            or self._raw(PUBLIC_MODE) == "on"
        )

    def preflight(self):
        if self.entry.options.get("emergency_stop", False) is True:
            return "Emergency stop is latched; release it before charging"
        if self.public_mode():
            return "Public charging mode is enabled"
        guards = self._guards()
        # A deliberately missing legacy helper on a new HA installation is
        # harmless. An existing failed/unavailable helper blocks live testing.
        power = self._raw(self.charging_power)
        if self.charging_power:
            try:
                measured_kw = float(power)
                if not isfinite(measured_kw) or measured_kw < 0:
                    return "Charging power reading invalid"
                if measured_kw > 0.25:
                    return "Geely reports charging power already flowing"
            except (ValueError, TypeError):
                return "Charging power unavailable: refresh vehicle data"
        return start_preflight(
            armed=True,
            battery=self._raw(self.battery),
            plugged=self._raw(self.plug),
            charging=self._raw(self.charging_switch),
            target=self.target,
            legacy_states=guards,
        )

    def _save_options(self, **changes):
        """Persist user preference/session snapshots, not transient mode."""
        if hasattr(self.hass, "config_entries"):
            self.hass.config_entries.async_update_entry(
                self.entry, options={**self.entry.options, **changes}
            )

    def _remember_manual_session(self, active):
        self._save_options(manual_session=(
            {"active": True, "target": self.active_target,
             "started_at": self.started_at.isoformat() if self.started_at else None}
            if active else {"active": False}
        ))

    async def async_set_automatic_enabled(self, enabled):
        """Automatic charging is persistent user intent, not a test mode."""
        self._save_options(automatic_charging_enabled=bool(enabled))
        await self.async_reconcile_automatic(deliberate=bool(enabled))

    async def async_reconcile_automatic(self, deliberate=False):
        """After manual, emergency, public or restart restore user's intent."""
        wanted = self.entry.options.get("automatic_charging_enabled", False) is True
        blocked = (self.owned or self.stop_requested_at is not None
                   or self.auto.stop_requested_at is not None
                   or self.unmanaged_charge
                   or self.public_mode()
                   or self.entry.options.get("emergency_stop", False) is True)
        target_mode = "Active" if wanted and not blocked else "Off"
        if self.auto.mode != target_mode:
            await self.auto.async_set_mode(target_mode, deliberate=deliberate)
        elif target_mode == "Active":
            await self.auto.async_tick()
        self._notify()

    async def async_restore(self):
        """Observe on startup, restore known manual charge and protect unknowns.

        Pre-v0.3.11 did not persist manual-session ownership. Never claim
        that a visible pre-existing charge was started by this integration.
        """
        self._startup_observation_until = (
            dt_util.utcnow() + timedelta(seconds=120)
        )
        saved = self.entry.options.get("manual_session", {})
        if isinstance(saved, dict) and saved.get("active") is True:
            target = saved.get("target")
            if (isinstance(target, (int, float)) and not isinstance(target, bool)
                    and 50 <= target <= 100):
                self.owned = True
                self.active_target = int(target)
                try:
                    self.started_at = datetime.fromisoformat(saved["started_at"])
                except (KeyError, TypeError, ValueError):
                    self.started_at = dt_util.utcnow()
                self.observed_active = False
                self._manual_recovery_started = dt_util.utcnow()
                if saved.get("stop_pending") is True:
                    # An explicit STOP was already requested before reload.
                    # Keep ownership and resume confirmation/retries.
                    self.stop_requested_at = dt_util.utcnow()
                    self.stop_started_at = dt_util.utcnow()
                    self.stop_note = "Restoring previous manual STOP request"
                    self.status = "STOP_REQUESTED"
                    self.message = "Confirming prior manual stop after reload"
                else:
                    self.status = "RECOVERING"
                    self.message = "Recovering manual charge; no duplicate START"
                self._notify()
        await self.auto.async_restore()
        self._observe_unmanaged()
        await self.async_reconcile_automatic()
        await self.scheduled_climate.async_tick()

    async def async_start_listening(self):
        entities = [self.battery, self.charging_switch, *MONITORED_GUARDS]
        if self.charging_power:
            entities.append(self.charging_power)
        if self.plug:
            entities.append(self.plug)

        @callback
        def changed(_event):
            self._observe_unmanaged()
            self.hass.async_create_task(self.async_tick())
            self.hass.async_create_task(self.auto.async_tick())
            self.hass.async_create_task(self.scheduled_climate.async_tick())

        @callback
        def periodic(_now):
            self._observe_unmanaged()
            self.hass.async_create_task(self.async_tick())
            self.hass.async_create_task(self.auto.async_tick())
            self.hass.async_create_task(self.scheduled_climate.async_tick())

        async def options_changed(_hass, _entry):
            await self.async_reconcile_automatic()
            await self.scheduled_climate.async_tick()
            self._notify()

        self._unsubs.append(
            self.entry.add_update_listener(options_changed)
        )
        self._unsubs.append(
            async_track_state_change_event(self.hass, entities, changed)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, periodic, timedelta(seconds=15))
        )

    async def async_arm(self, enabled):
        """Legacy HA helper method; no arming or test entity is exposed."""
        self.armed = bool(enabled)
        self._notify()

    async def async_set_target(self, value):
        if isinstance(value, bool) or int(value) != value or not 50 <= value <= 100:
            raise ValueError("Manual charging target must be 50–100%")
        self.target = int(value)
        self._save_options(manual_charge_target=self.target)
        self._notify()

    async def async_emergency_stop(self):
        """Explicit user STOP, even if no controller owns the session."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, "emergency_stop": True},
        )
        if self.auto.mode != "Off":
            await self.auto.async_set_mode("Off")
        # Exactly one controller may issue the emergency OFF command.
        # The manual owner retains responsibility for manual stop verification;
        # otherwise the automatic safety controller owns the emergency stop.
        if self.owned and not self.public_mode():
            async with self._lock:
                if self.stop_requested_at is None:
                    await self._stop_locked("Emergency STOP requested")
        else:
            async with self.auto._lock:
                if self.public_mode():
                    self.auto._update(
                        "BLOCKED",
                        "Emergency stop latched, but Public Mode blocks vehicle commands",
                    )
                elif self.auto.stop_requested_at is None:
                    await self.auto._request_stop("Emergency STOP requested")
        self._notify()

    async def async_release_emergency_stop(self):
        """Release the latch and restore the previously enabled schedule."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, "emergency_stop": False},
        )
        await self.async_reconcile_automatic()
        self._notify()

    async def async_start_manual(self, target=None):
        """Normal user button: one explicit manual charge, no test arming UI.

        An already-owned schedule cannot be interrupted and replaced with
        an immediate ON; the user must first stop it and wait for confirmation.
        Manual start disables automatic mode until Resume schedule is pressed.
        """
        if self.auto.owned or self.auto.stop_requested_at is not None:
            self.status = "BLOCKED"
            self.message = "Stop the active schedule and verify OFF before manual charging"
            self._notify()
            return
        if self.unmanaged_charge or self._vehicle_indicates_charging():
            self.status = "BLOCKED"
            self.message = (
                "Vehicle is already charging; Stop manual or stop in Geely "
                "before starting a new charge"
            )
            self._notify()
            return
        if self.auto.mode != "Off":
            await self.auto.async_set_mode("Off")
        if target is not None:
            await self.async_set_target(target)
        await self.async_start()
        if not self.owned:
            await self.async_reconcile_automatic()
            self._notify()

    async def async_manual_climate(self, action):
        if (action != "off" and (
                self.entry.options.get("emergency_stop", False) is True
                or self._raw(EMERGENCY_STOP) == "on")):
            self.climate.status = "BLOCKED"
            self.climate.message = "Release Emergency Stop before activating cabin climate"
            self._notify()
            return
        await self.scheduled_climate.async_manual_override(action)
        await self.climate.apply(action)

    async def async_resume_schedule(self):
        """Deliberate return from manual charging to automatic scheduling."""
        if self.owned or self.stop_requested_at is not None:
            self.message = "Stop manual charging and wait for verification first"
            self._notify()
            return
        await self.async_set_automatic_enabled(True)
        self._notify()

    async def async_start(self):
        async with self._lock:
            if self.auto.owned or self.auto.stop_requested_at is not None:
                self.status = "BLOCKED"
                self.message = "Automatic controller has an active session or stop request"
                self._notify()
                return
            if self.owned:
                self.message = "Manual charging already active"
                self._notify()
                return
            reason = self.preflight()
            if reason:
                self.status = "BLOCKED"
                self.message = reason
                self._notify()
                return
            # Transfer vehicle authority atomically to the explicit manual
            # charge. Without this, an earlier automatic STOP's five-minute
            # delayed-start watchdog sees the manual START and issues OFF.
            # Do not clear the watchdog if preflight was blocked, and do not
            # take over a still-pending automatic stop verification.
            async with self.auto._lock:
                if self.auto.owned or self.auto.stop_requested_at is not None:
                    self.status = "BLOCKED"
                    self.message = (
                        "Automatic charge stop is still being verified; "
                        "manual start is blocked"
                    )
                    self._notify()
                    return
                self.auto.stop_watch_until = None
                self.auto.unexpected_since = None
                self.owned = True
                self.unmanaged_charge = False
            self.stop_watch_until = None
            self.active_target = self.target
            self.started_at = dt_util.utcnow()
            self._remember_manual_session(True)
            # This authorised manual charge supersedes any stale automatic
            # ownership record left by an interrupted reload.
            self._save_options(automatic_session={"active": False})
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
                _LOGGER.exception("Geely manual charge start failed")
                # The request may have reached the vehicle before HA errored.
                await self._stop_locked("Start failed; attempted safe stop")
                self.status = "ERROR"
                self.message = f"Start service error: {type(exc).__name__}"
                self._notify()
                return
            self.status = "RUNNING"
            self.message = (f"Manual charge active, {self.active_target}% target"
                            if self.active_target < 100
                            else "Manual full charge: Geely controls termination")
            self._notify()

    async def _stop_locked(self, reason):
        """Request stop and retain session ownership until confirmed.

        Geely cloud acknowledgements are not proof that charging has stopped.
        """
        if not self.owned:
            self.message = "No integration-owned charge session to stop"
            self._notify()
            return
        if self.public_mode():
            self._finish("BLOCKED", "Public mode enabled; manual stop suppressed")
            return
        if self.stop_requested_at is None:
            self.stop_attempts = 0
            self.stop_started_at = dt_util.utcnow()
            self.stop_note = reason
        self.stop_requested_at = dt_util.utcnow()
        self.stop_attempts += 1
        self._save_options(manual_session={
            "active": True,
            "target": self.active_target,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stop_pending": True,
        })
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
            _LOGGER.exception("Failed to stop integration-owned manual charging")
            self.status = "ERROR"
            self.message = f"Stop service error: {type(exc).__name__}; verify in car"
            self._notify()
            return  # Keep ownership and allow another explicit stop.

    def _finish(self, status, message):
        """Finish only after vehicle state indicates charging has stopped."""
        if (status == "STOPPED" and self.stop_started_at is not None
                and self.stop_watch_until is None):
            self.stop_watch_until = dt_util.utcnow() + MANUAL_STOP_WATCH
        self.owned = False
        self.armed = False
        self.active_target = None
        self.started_at = None
        self.observed_active = False
        self.stop_requested_at = None
        self.stop_started_at = None
        self.stop_attempts = 0
        self.off_observations = 0
        self.status = status
        self.message = message
        self._remember_manual_session(False)
        self._notify()
        if hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(self.async_reconcile_automatic())

    def _power_active(self):
        if not self.charging_power:
            return False
        try:
            return float(self._raw(self.charging_power)) > 0.25
        except (TypeError, ValueError):
            return False

    def _stopped_state(self):
        """Require fresh post-request Geely switch OFF and no power."""
        if self.stop_started_at is None:
            return False
        for entity in (self.charging_switch, self.charging_power):
            if not entity:
                continue
            state = self._state(entity)
            timestamp = (getattr(state, "last_reported", None)
                         or getattr(state, "last_updated", None))
            if (not isinstance(timestamp, datetime) or timestamp.tzinfo is None
                    or timestamp <= self.stop_started_at):
                return False
        if self._raw(self.charging_switch) != "off":
            return False
        if not self.charging_power:
            return True
        try:
            power = float(self._raw(self.charging_power))
            return isfinite(power) and 0 <= power <= 0.25
        except (TypeError, ValueError):
            return False  # Unknown power is not positive stop confirmation.

    async def async_stop(self):
        """Explicit manual STOP also works for an observed older-version charge.

        The user's request to Stop manual is a real vehicle command, not a
        requirement that the current process previously issued START.
        """
        if self.owned:
            async with self._lock:
                await self._stop_locked("User requested manual stop")
            return
        if self.public_mode():
            self.status = "BLOCKED"
            self.message = "Public charging mode: use Geely to stop public charging"
            self._notify()
            return
        if self._vehicle_indicates_charging() or self.unmanaged_charge:
            # Use the automatic safety controller's already hardened STOP
            # verification path, without claiming manual ownership.
            async with self.auto._lock:
                if self.auto.stop_requested_at is None:
                    await self.auto._request_stop(
                        "Explicit Stop manual for observed charging"
                    )
            self.status = "STOP_REQUESTED"
            self.message = "Stopping observed charge; waiting for Geely verification"
            self._notify()
            return
        self.status = "IDLE"
        self.message = "No charge detected to stop"
        self._notify()

    async def async_tick(self):
        """Observe manual ownership and verify stops; never blind-start."""
        self._observe_unmanaged()
        async with self._lock:
            if self.public_mode():
                self.stop_watch_until = None
            if self.stop_watch_until is not None and not self.owned:
                if self.auto.owned:
                    # A new, authorised automatic charge supersedes the old
                    # manual cancellation watchdog; never stop that session.
                    self.stop_watch_until = None
                elif dt_util.utcnow() >= self.stop_watch_until:
                    self.stop_watch_until = None
                elif (self._raw(self.charging_switch) == "on"
                      or self._power_active()):
                    self.owned = True
                    await self._stop_locked(
                        "Delayed charging after manual stop; enforcing cancellation"
                    )
                    return
            if not self.owned:
                return
            guards = self._guards()
            if self.public_mode():
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
                if (self.off_observations >= 2 and self.stop_started_at is not None
                        and dt_util.utcnow() - self.stop_started_at >= MANUAL_STOP_SETTLE):
                    self._finish("STOPPED", f"{self.stop_note}; Geely reports stopped")
                    return
                if (
                    dt_util.utcnow() - self.stop_requested_at >= timedelta(seconds=30)
                ):
                    if self._stopped_state():
                        return
                    if self.stop_attempts < 3:
                        await self._stop_locked("Retrying stop confirmation")
                    else:
                        self.status = "ERROR"
                        self.message = "Stop unconfirmed after 3 attempts: verify in car"
                        self._notify()
                return

            if (self.entry.options.get("emergency_stop", False) is True
                    or any(guards.get(key) not in (None, "off") for key in MONITORED_GUARDS)):
                await self._stop_locked("Safety interlock activated")
                return

            if self._manual_recovery_started is not None:
                if self._raw(self.charging_switch) == "on" or self._power_active():
                    self.observed_active = True
                    self._manual_recovery_started = None
                elif dt_util.utcnow() - self._manual_recovery_started < timedelta(seconds=90):
                    self.status = "RECOVERING"
                    self.message = "Checking prior manual charge; no duplicate START"
                    self._notify()
                    return
                else:
                    raw_soc = self._raw(self.battery)
                    try:
                        restored_soc = float(raw_soc)
                    except (TypeError, ValueError):
                        restored_soc = None
                    if (restored_soc is None
                            or self._raw(self.charging_switch) not in ("on", "off")):
                        self.status = "RECOVERING"
                        self.message = "Cannot classify old charge until Geely refreshes"
                        self._notify()
                        return
                    if restored_soc >= self.active_target or (
                            self.active_target == 100 and restored_soc >= 99):
                        self._finish("COMPLETED", "Previous manual charge finished in vehicle")
                    else:
                        self._finish("INTERRUPTED", "Previous manual charge ended below target")
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
                if soc is not None and (
                        soc >= self.active_target
                        or (self.active_target == 100 and soc >= 99)):
                    self._finish("COMPLETED", "Geely ended charge at target")
                else:
                    self._finish("INTERRUPTED", "Geely ended manual charge below target")
                return

    async def async_shutdown(self):
        await self.auto.async_shutdown()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        # Reload/restart is NOT a user request to stop a real charging
        # session. Owner and explicit pending-stop markers are persisted.
        # On next setup, recovery will observe Geely before issuing commands.
        self._notify()
