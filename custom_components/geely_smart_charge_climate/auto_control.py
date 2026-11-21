"""Explicitly enabled EX5 charging scheduler and authorisation guard.

Three modes: Off (default after every HA restart), Monitor (decisions only),
Active (real ON/OFF commands after interlocks). All commands use the same
selected Geely switch as the successful attended manual test.

Do not enable unattended charging until integration/restart recovery is proven.
"""
import asyncio
from datetime import timedelta
from math import isfinite
import logging

from homeassistant.components import persistent_notification
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry as er

from .authorization import ChargeDecision, decide
from .weekly_schedule import validate_day
from .live_safety import (
    LEGACY_CONTROLLER, LEGACY_ACTIVE, OLD_FULL_CHARGE,
    PUBLIC_MODE, EMERGENCY_STOP, start_preflight,
)
from .const import DOMAIN, DEFAULT_EFFECTIVE_KW, DEFAULT_USABLE_CAPACITY_KWH

_LOGGER = logging.getLogger(__name__)
MODES = ("Off", "Monitor", "Active")
INTERLOCKS = (
    LEGACY_CONTROLLER, LEGACY_ACTIVE, OLD_FULL_CHARGE,
    PUBLIC_MODE, EMERGENCY_STOP,
)
UNEXPECTED_GRACE = timedelta(seconds=30)
STOP_RETRY = timedelta(seconds=30)


class AutomaticChargeController:
    """Observes first, commands only after a deliberate change to Active."""

    def __init__(self, manual):
        self.manual = manual
        self.hass = manual.hass
        self.entry = manual.entry
        self.mode = "Off"  # Volatile until restart and intentionally fail-closed.
        self.status = "OFF"
        self.message = "Automatic controller is off"
        self.decision = None
        self.owned = False
        self.owned_target = None
        self.owned_day = None
        self.owned_deadline = None
        self.started_at = None
        self.saw_charging = False
        self.off_checks = 0
        self.unexpected_since = None
        self.stop_requested_at = None
        self.stop_attempts = 0
        self.stop_context = ""
        self.last_event = "No automatic charging action"
        self.completed_deadlines = set()
        self._lock = asyncio.Lock()
        self._last_notification = None

    def _raw(self, name):
        return self.manual._raw(name)

    def _public_mode(self):
        """User-operated public charging boundary, including legacy helper."""
        return (
            self.entry.options.get("public_charging_mode", False) is True
            or self._raw(PUBLIC_MODE) == "on"
        )

    def _power(self):
        if not self.manual.charging_power:
            return None
        try:
            value = float(self._raw(self.manual.charging_power))
            return value if isfinite(value) and value >= 0 else None
        except (TypeError, ValueError):
            return None

    def _soc(self):
        try:
            value = float(self._raw(self.manual.battery))
            return value if isfinite(value) and 0 <= value <= 100 else None
        except (TypeError, ValueError):
            return None

    def _charging(self):
        state = self._raw(self.manual.charging_switch)
        power = self._power()
        return state == "on" or (power is not None and power > 0.25)

    def _stopped(self):
        power = self._power()
        # The Geely charging switch is mandatory; Geely power is optional.
        # Where valid power is present, require corroboration.
        return self._raw(self.manual.charging_switch) == "off" and (
            power is None or power <= 0.25
        )

    def _legacy_clear(self):
        return all(self._raw(key) in (None, "off") for key in INTERLOCKS)

    def _notice(self, code, message):
        """Single identified notification per event; no spam on periodic ticks."""
        event = f"{code}:{message}"
        if event == self._last_notification:
            return
        self._last_notification = event
        self.last_event = message
        try:
            persistent_notification.async_create(
                self.hass,
                message,
                title="Geely charging controller",
                notification_id=f"geely_auto_{self.entry.entry_id}_{code}",
            )
            self.hass.bus.async_fire(
                "geely_smart_charge_decision",
                {"event": code, "message": message, "mode": self.mode},
            )
        except Exception:
            _LOGGER.exception("Could not publish charging controller notification")

    def _update(self, status, message, decision=None):
        changed = (self.status != status or self.message != message or
                   (decision is not None and decision != self.decision))
        self.status = status
        self.message = message
        if decision is not None:
            self.decision = decision
        if changed:
            self.manual._notify()

    def _effective_kw(self):
        """Use the existing real charging-rate learner when available."""
        try:
            registry = er.async_get(self.hass)
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{self.entry.entry_id}_simulation_decision"
            )
            state = self.hass.states.get(entity_id) if entity_id else None
            value = (
                float(state.attributes.get("assumed_effective_kw"))
                if state and state.attributes.get("assumed_effective_kw") is not None
                else DEFAULT_EFFECTIVE_KW
            )
            if isfinite(value) and 1 <= value <= 22:
                return value
        except (TypeError, ValueError, AttributeError):
            pass
        return DEFAULT_EFFECTIVE_KW

    def _policy(self):
        return decide(
            now=dt_util.now(),
            schedule=self.entry.options.get("weekly_schedule", {}),
            soc=self._soc(), charging=self._charging(),
            plugged=self._raw(self.manual.plug) == "on" if self.manual.plug else None,
            rate_kw=self._effective_kw(),
            capacity_kwh=DEFAULT_USABLE_CAPACITY_KWH,
            public_mode=self._public_mode(),
            emergency=self._raw(EMERGENCY_STOP) == "on",
            legacy_clear=self._legacy_clear(),
            manual_owned=self.manual.owned or self.manual.armed,
        )

    async def async_set_mode(self, mode):
        if mode not in MODES:
            raise ValueError("Unsupported automatic controller mode")
        async with self._lock:
            self.mode = mode
            self.unexpected_since = None
            if self.owned and mode != "Active":
                # Never stop a public charge, even on a mode change.
                if self._public_mode():
                    self._release("BLOCKED", "Public charging mode; session released")
                else:
                    await self._request_stop("Automatic control disabled by user")
            elif self.stop_requested_at is None:
                self._update(
                    "OFF" if mode == "Off" else "MONITORING",
                    "Automatic charging disabled" if mode == "Off"
                    else ("Monitoring only; no vehicle commands" if mode == "Monitor"
                          else "Active mode selected; checking safety interlocks"),
                )
            self.manual._notify()
        if mode != "Off":
            await self.async_tick()

    async def _request_start(self, plan):
        """Start only when Geely telemetry and user-operated guards permit."""
        if self.mode != "Active" or self.manual.armed or self.manual.owned:
            return
        # One session per departure calendar day, even if the user edits
        # the target or ready-by clock time after starting.
        deadline_key = (plan.day, plan.ready_by.date().isoformat())
        if deadline_key in self.completed_deadlines:
            self._update("COMPLETED", "This scheduled charging session already ended")
            return
        if self._public_mode() or not self._legacy_clear():
            self._update("BLOCKED", "Cannot start: public mode or safety interlock")
            return
        reason = start_preflight(
            armed=True, battery=self._raw(self.manual.battery),
            plugged=self._raw(self.manual.plug),
            charging=self._raw(self.manual.charging_switch),
            target=plan.target,
            legacy_states={k: self._raw(k) for k in INTERLOCKS},
        )
        if reason:
            self._update("BLOCKED", reason)
            return
        power = self._power()
        if power is not None and power > 0.25:
            self._update("BLOCKED", "Charging power already flowing")
            return
        self.owned = True
        self.owned_target = plan.target
        self.owned_day = plan.day
        self.owned_deadline = plan.ready_by
        self.started_at = dt_util.utcnow()
        self.saw_charging = False
        self.off_checks = 0
        self._update("STARTING", f"Starting {plan.day} charge to {plan.target}%", plan)
        self._notice("start", f"Starting scheduled charging to {plan.target}% for {plan.day}")
        try:
            await self.hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": self.manual.charging_switch}, blocking=True,
            )
        except Exception as exc:
            _LOGGER.exception("Automatic scheduled start failed")
            await self._request_stop("Start returned an error; attempting safe stop")
            self._update("ERROR", f"Start error: {type(exc).__name__}")
            self._notice("error", "Scheduled start failed; check vehicle status")
            return
        self._update("CHARGING", f"Scheduled charge requested: {plan.target}%")

    async def _request_stop(self, reason):
        """Keep stop ownership until Geely confirms a stopped state."""
        if self._public_mode():
            # The user has designated this a public session; do not send OFF.
            self._release("BLOCKED", "Public mode enabled; stop command suppressed")
            return
        if self.stop_requested_at is None:
            self.stop_attempts = 0
        self.stop_requested_at = dt_util.utcnow()
        self.stop_attempts += 1
        self.off_checks = 0
        self.stop_context = reason
        self._update("STOP_REQUESTED", f"{reason}; awaiting Geely confirmation")
        self._notice("stop_requested", f"Geely charging STOP requested: {reason}")
        try:
            await self.hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": self.manual.charging_switch}, blocking=True,
            )
        except Exception as exc:
            _LOGGER.exception("Automatic stop service failed")
            self._update("ERROR", f"Stop error: {type(exc).__name__}; verify in vehicle")
            self._notice("error", "Automatic stop failed; verify charging directly")

    def _release(self, state, message):
        if self.owned and self.owned_day and self.owned_deadline:
            self.completed_deadlines.add((self.owned_day, self.owned_deadline.date().isoformat()))
        self.owned = False
        self.owned_target = None
        self.owned_day = None
        self.owned_deadline = None
        self.started_at = None
        self.saw_charging = False
        self.off_checks = 0
        self.stop_requested_at = None
        self.stop_attempts = 0
        self.unexpected_since = None
        self._update(state, message)

    async def _reconcile_owned_schedule(self):
        """Apply current schedule edits to an already-running charge.

        Do not recalculate the ownership day from the current clock. The
        existing session belongs to its original departure date; this makes
        cross-midnight sessions stable when their target or ready-by time changes.
        A pending STOP is never reversed by editing the schedule.
        """
        try:
            schedule = self.entry.options.get("weekly_schedule", {})
            settings = validate_day(schedule.get(self.owned_day, {}))
        except (ValueError, TypeError, AttributeError):
            await self._request_stop("Scheduled charge settings invalid")
            return False

        if not settings["enabled"]:
            await self._request_stop("Scheduled charge disabled while running")
            return False

        hours, minutes = map(int, settings["ready_time"].split(":"))
        deadline = self.owned_deadline.replace(
            hour=hours, minute=minutes, second=0, microsecond=0
        )
        changed = (settings["target"] != self.owned_target or
                   deadline != self.owned_deadline)
        self.owned_target = settings["target"]
        self.owned_deadline = deadline

        active_decision = ChargeDecision(
            action="AUTHORISED",
            reason=("100% charge: Geely controls completion" if self.owned_target == 100
                    else "Running scheduled charge to current target"),
            day=self.owned_day, target=self.owned_target,
            start_at=(self.decision.start_at if self.decision is not None
                      and self.decision.day == self.owned_day else None),
            ready_by=self.owned_deadline,
        )
        self._update(
            "CHARGING",
            f"Scheduled charge active: target {self.owned_target}%",
            active_decision,
        )
        if changed:
            self._notice(
                "schedule_changed",
                f"Active {self.owned_day} charge updated to {self.owned_target}% "
                f"by {self.owned_deadline.strftime('%H:%M')}",
            )
        return True

    async def async_tick(self):
        """Decide, log, and (only when Active) act on non-public charging."""
        async with self._lock:
            if self.mode == "Off" and self.stop_requested_at is None:
                return

            # A public-mode change must block ALL further automatic commands,
            # including pending stop retries and emergency interventions.
            if self._public_mode():
                if self.owned or self.stop_requested_at is not None:
                    self._release("BLOCKED", "Public mode enabled; ownership released")
                else:
                    self._update("BLOCKED", "Public charging mode; commands suppressed")
                return

            # Confirmation/retry must run even after the user disables active
            # mode, otherwise an in-flight stop could be abandoned.
            if self.stop_requested_at is not None:
                self.off_checks = self.off_checks + 1 if self._stopped() else 0
                if self.off_checks >= 2:
                    context = self.stop_context
                    self._release("STOPPED", f"Verified charging stopped: {context}")
                    self._notice("stop_verified", f"Charging stopped and verified: {context}")
                    return
                elapsed = dt_util.utcnow() - self.stop_requested_at
                if elapsed >= STOP_RETRY:
                    if self.stop_attempts < 3:
                        await self._request_stop("Retrying unconfirmed stop")
                    else:
                        self._update("ERROR", "Stop not verified; check vehicle immediately")
                        self._notice("error", "Automatic stop remains unconfirmed")
                return

            if self.owned:
                # A latched session remains authorised after the calculated
                # start time shifts with rising SOC and after ready-by.
                if self._raw(EMERGENCY_STOP) == "on" or not self._legacy_clear():
                    await self._request_stop("Safety interlock activated")
                    return
                if self.mode != "Active":
                    await self._request_stop("Automatic mode no longer active")
                    return
                if not await self._reconcile_owned_schedule():
                    return
                soc = self._soc()
                if self.owned_target < 100 and (soc is None or soc >= self.owned_target):
                    await self._request_stop(
                        "Scheduled battery target reached" if soc is not None
                        else "Battery telemetry lost"
                    )
                    return
                if (
                    self.owned_target < 100
                    and self.owned_deadline is not None
                    and dt_util.now() >= self.owned_deadline + timedelta(hours=3)
                ):
                    await self._request_stop("Scheduled charge exceeded maximum overrun")
                    return
                if self._charging():
                    self.saw_charging = True
                    self.off_checks = 0
                elif self.saw_charging:
                    self.off_checks += 1
                if self.saw_charging and self.off_checks >= 2:
                    self._release("COMPLETED", "Geely charging session ended")
                    self._notice("complete", "Scheduled charging completed")
                    return
                if (
                    not self.saw_charging and self.started_at
                    and dt_util.utcnow() - self.started_at >= timedelta(minutes=3)
                ):
                    await self._request_stop("Charge start not confirmed in three minutes")
                return

            # Emergency stop can intervene in an observed charging session
            # only while the user has NOT designated public charging mode.
            if self._raw(EMERGENCY_STOP) == "on":
                if (self.mode == "Active" and not self.manual.owned
                        and self._charging()):
                    await self._request_stop("Emergency stop requested")
                else:
                    self._update("BLOCKED", "Emergency stop active; starts suppressed")
                return

            # Never command while a manual test is armed or owns the vehicle.
            policy = self._policy()
            # The visible decision must refresh even if the status text stays
            # unchanged (for example, a target edit during WAIT/CHARGING).
            if policy != self.decision:
                self.decision = policy
                self.manual._notify()
            if self.mode == "Monitor":
                self._update("MONITORING", f"{policy.action}: {policy.reason}", policy)
                return
            if self.manual.armed or self.manual.owned:
                self._update("BLOCKED", "Manual live charge takes priority", policy)
                return
            if policy.action in ("BLOCKED", "UNKNOWN"):
                self.unexpected_since = None
                self._update(policy.action, policy.reason, policy)
                return
            if policy.action == "START":
                self.unexpected_since = None
                await self._request_start(policy)
                return
            if policy.action == "STOP":
                # User owns the public/home declaration. Wait for stable
                # unexpected charging before intervening.
                if not self._legacy_clear():
                    self._update("BLOCKED", "Cannot intervene with safety interlocks active")
                    return
                if self.unexpected_since is None:
                    self.unexpected_since = dt_util.utcnow()
                    self._update("CHECKING", f"Checking charging authorisation: {policy.reason}", policy)
                    self._notice("unexpected", f"Unexpected charging detected: {policy.reason}")
                    return
                if dt_util.utcnow() - self.unexpected_since >= UNEXPECTED_GRACE:
                    await self._request_stop("Unauthorised charging at home")
                return

            self.unexpected_since = None
            self._update("WAITING", f"{policy.action}: {policy.reason}", policy)

    async def async_shutdown(self):
        """Unload safely. No unattended charge control survives restart."""
        if self.owned or self.stop_requested_at is not None:
            async with self._lock:
                if self._public_mode():
                    self._release("BLOCKED", "Public mode enabled during unload")
                elif self.owned and self.owned_target == 100:
                    # A Home Assistant reload is not a user request to cancel
                    # 100% charging. Let Geely finish the session itself.
                    self._release(
                        "OFF", "Home Assistant unloaded; 100% termination left to Geely"
                    )
                elif self._charging():
                    await self._request_stop("Integration unloading")
        self.mode = "Off"
        self.manual._notify()
