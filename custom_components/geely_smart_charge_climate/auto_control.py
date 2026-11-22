"""Explicitly enabled EX5 charging scheduler and authorisation guard.

Three modes: Off (default after every HA restart), Monitor (decisions only),
Active (real ON/OFF commands after interlocks). All commands use the same
selected Geely switch as the successful attended manual test.

Do not enable unattended charging until integration/restart recovery is proven.
"""
import asyncio
from datetime import datetime, timedelta
from math import isfinite
import logging

from homeassistant.components import persistent_notification
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry as er

from .authorization import ChargeDecision, charge_start_at, decide
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
STOP_SETTLE = timedelta(seconds=30)
STOP_WATCH = timedelta(minutes=5)


class AutomaticChargeController:
    """Observes first, commands only after a deliberate change to Active."""

    def __init__(self, manual):
        self.manual = manual
        self.hass = manual.hass
        self.entry = manual.entry
        self.mode = "Off"  # Runtime policy, derived from persisted user preference.
        self.status = "OFF"
        self.message = "Automatic schedule disabled"
        self.decision = None
        self.owned = False
        self.owned_target = None
        self.owned_day = None
        self.owned_deadline = None
        self.started_at = None
        self.saw_charging = False
        # Only a 100% session with positive charging evidence BEFORE its
        # ready-by deadline may continue beyond it for Geely-managed balancing.
        # A missed morning departure may never resume from an evening plug-in.
        self.full_overrun_authorized = False
        self.off_checks = 0
        self.unexpected_since = None
        self.stop_requested_at = None
        self.stop_started_at = None
        self.stop_watch_until = None
        self.stop_attempts = 0
        self.stop_context = ""
        self.last_event = "No automatic charging action"
        # A finished session is not necessarily a completed target. Keep its
        # outcome, target and departure date to prevent accidental restart loops.
        self.finished_deadlines = {
            tuple(key.split("|", 1)): value
            for key, value in self.entry.options.get("finished_charge_sessions", {}).items()
            if isinstance(key, str) and "|" in key and isinstance(value, dict)
        }
        self._recovery_started_at = None
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

    def _emergency(self):
        return (self.entry.options.get("emergency_stop", False) is True
                or self._raw(EMERGENCY_STOP) == "on")

    def _soc(self):
        try:
            value = float(self._raw(self.manual.battery))
            return value if isfinite(value) and 0 <= value <= 100 else None
        except (TypeError, ValueError):
            return None

    def _confirmed_charge_power(self):
        """Positive Geely or optional read-only wallbox power, not switch ON alone."""
        power = self._power()
        wallbox = (self.manual._wallbox_kw()
                   if hasattr(self.manual, "_wallbox_kw") else None)
        return ((power is not None and power > 0.25)
                or (wallbox is not None and wallbox > 0.25))

    def _charging(self):
        state = self._raw(self.manual.charging_switch)
        power = self._power()
        wallbox = (self.manual._wallbox_kw()
                   if hasattr(self.manual, "_wallbox_kw") else None)
        return (state == "on" or (power is not None and power > 0.25)
                or (wallbox is not None and wallbox > 0.25))

    def _stop_telemetry_fresh(self):
        """Never verify STOP using cached states from before the command.

        Home Assistant exposes last_reported (fallback last_updated). Both
        Geely switch and configured power must have been reported after the
        first OFF command. Missing timestamps are *unconfirmed*, not OFF.
        """
        if self.stop_started_at is None:
            return False
        for entity_id in (self.manual.charging_switch, self.manual.charging_power):
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state is None:
                return False
            timestamp = (getattr(state, "last_reported", None)
                         or getattr(state, "last_updated", None))
            if (not isinstance(timestamp, datetime)
                    or timestamp.tzinfo is None
                    or timestamp <= self.stop_started_at):
                return False
        return True

    def _stopped(self):
        power = self._power()
        wallbox = (self.manual._wallbox_kw()
                   if hasattr(self.manual, "_wallbox_kw") else None)
        # Geely OFF/0 is not physical proof when an optional wallbox still
        # reports charging. This is corroboration only, not a requirement.
        return (
            self._stop_telemetry_fresh()
            and self._raw(self.manual.charging_switch) == "off"
            and (power is None or power <= 0.25)
            and (wallbox is None or wallbox <= 0.25)
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
            emergency=self._emergency(),
            legacy_clear=self._legacy_clear(),
            manual_owned=self.manual.owned or self.manual.armed,
        )

    @staticmethod
    def _deadline_key(plan):
        if plan is None or plan.ready_by is None:
            return None
        return (plan.day, plan.ready_by.date().isoformat())

    def _rearm_if_requested(self, plan, deliberate=False):
        """Release only the matching finished-session lock on fresh intent.

        An unchanged target/time cannot continually restart an interrupted
        charge. Raising target, re-enabling a disabled schedule, or deliberate
        Resume/Active action can re-arm, but never when SoC is unknown or
        already satisfies the new requested target.
        """
        key = self._deadline_key(plan)
        previous = self.finished_deadlines.get(key)
        soc = self._soc()
        if (previous is None or plan.action not in ("START", "WAIT")
                or soc is None or plan.target is None or soc >= plan.target):
            return False
        if (deliberate or plan.target > previous["target"]
                or previous["outcome"] == "disabled"
                or (previous["outcome"] == "deferred"
                    and plan.action == "START")):
            del self.finished_deadlines[key]
            return True
        return False

    def _persist_session(self, active):
        """Persist current vehicle ownership without saving transient mode."""
        session = (
            {"active": True, "target": self.owned_target,
             "day": self.owned_day, "deadline": self.owned_deadline.isoformat(),
             "stop_pending": self.stop_requested_at is not None,
             "full_overrun_authorized": self.full_overrun_authorized}
            if active and self.owned_deadline else {"active": False}
        )
        if hasattr(self.manual, "_save_options"):
            self.manual._save_options(automatic_session=session)

    def _persist_finished(self):
        history = {
            f"{day}|{date}": value
            for (day, date), value in list(self.finished_deadlines.items())[-35:]
        }
        if hasattr(self.manual, "_save_options"):
            self.manual._save_options(
                finished_charge_sessions=history,
                automatic_session={"active": False},
            )

    async def async_restore(self):
        """Restore session ownership, never send an unconditional START.

        A previous automatic session is RECOVERING until Geely's own switch,
        SoC and power can be read. The existing policy then decides whether
        more charging is authorised. Automatic user intent is separate.
        """
        saved = self.entry.options.get("automatic_session", {})
        if (not isinstance(saved, dict) or saved.get("active") is not True
                or self.manual.owned):
            return
        try:
            target = int(saved["target"])
            day = saved["day"]
            deadline = datetime.fromisoformat(saved["deadline"])
            if (not 50 <= target <= 100 or day not in
                    ("monday", "tuesday", "wednesday", "thursday",
                     "friday", "saturday", "sunday")
                    or deadline.tzinfo is None):
                raise ValueError("Invalid persisted charge session")
        except (KeyError, ValueError, TypeError):
            return
        self.owned = True
        self.owned_target = target
        self.owned_day = day
        self.owned_deadline = deadline
        self.full_overrun_authorized = (
            saved.get("full_overrun_authorized") is True and target == 100
        )
        self.started_at = dt_util.utcnow()
        if saved.get("stop_pending") is True:
            # Persisted explicit STOP survives reload. Never send START.
            self.stop_requested_at = dt_util.utcnow()
            self.stop_started_at = dt_util.utcnow()
            self.stop_context = "Restored pending automatic STOP"
            self._recovery_started_at = None
        else:
            self._recovery_started_at = dt_util.utcnow()
        self.saw_charging = False
        self.off_checks = 0
        if self.stop_requested_at is not None:
            self._update("STOP_REQUESTED", "Verifying previous automatic STOP after reload")
        else:
            self._update("RECOVERING", "Previous scheduled charge restored; checking Geely")

    async def async_request_resume(self):
        """Real Resume schedule action, even if already persistently enabled."""
        async with self._lock:
            if (self.mode != "Active" or self.owned
                    or self.stop_requested_at is not None
                    or getattr(self.manual, "unmanaged_charge", False)
                    or self.manual.owned):
                return
            self._rearm_if_requested(self._policy(), deliberate=True)
        await self.async_tick()

    async def async_set_mode(self, mode, deliberate=True):
        if mode not in MODES:
            raise ValueError("Unsupported automatic controller mode")
        async with self._lock:
            old_mode = self.mode
            self.mode = mode
            self.unexpected_since = None
            if (mode == "Active" and deliberate and old_mode != "Active"
                    and not self.owned and self.stop_requested_at is None):
                # For the temporary test UI, returning to Active is an
                # explicit request to resume a previously stopped charge.
                # Never re-arm without positive SoC, a current START policy
                # and an actual shortfall against its requested target.
                plan = self._policy()
                soc = self._soc()
                if soc is not None:
                    self._rearm_if_requested(plan, deliberate=True)
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
        """Start only before the exact ready-by cutoff and under all guards."""
        if self.mode != "Active" or self.manual.armed or self.manual.owned:
            return
        if plan.ready_by is None or dt_util.now() >= plan.ready_by:
            self._update(
                "EXPIRED",
                "The scheduled ready-by deadline has passed; no late START",
                plan,
            )
            return
        # One session per departure calendar day, even if its ready-by
        # time changes while that session is owned.
        deadline_key = self._deadline_key(plan)
        self._rearm_if_requested(plan)
        previous = self.finished_deadlines.get(deadline_key)
        if previous is not None:
            if previous["outcome"] == "completed":
                self._update(
                    "COMPLETED",
                    "Scheduled target already achieved for this departure; "
                    "increase target to request more charging",
                    plan,
                )
            elif previous["outcome"] == "deferred":
                self._update(
                    "WAITING",
                    "Schedule was edited: waiting for revised charge window",
                    plan,
                )
            else:
                self._update(
                    "PAUSED",
                    "Previous charge ended before target; use Resume schedule "
                    "when vehicle is safe to charge again",
                    plan,
                )
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
        # This is a deliberately new authorised session. It must not be
        # mistaken for a delayed rebound from a previous STOP.
        self.stop_watch_until = None
        # Symmetric ownership transfer: a prior manual STOP watchdog must not
        # cancel a newly authorised automatic charge.
        if hasattr(self.manual, "stop_watch_until"):
            self.manual.stop_watch_until = None
        self.owned = True
        self.owned_target = plan.target
        self.owned_day = plan.day
        self.owned_deadline = plan.ready_by
        self.started_at = dt_util.utcnow()
        self._recovery_started_at = None
        self.full_overrun_authorized = False
        self._persist_session(True)
        if hasattr(self.manual, "_save_options"):
            self.manual._save_options(manual_session={"active": False})
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
            self.stop_context = reason
            self.stop_started_at = dt_util.utcnow()
        # Preserve the original stop reason and first-request timestamp
        # across retries. The latter prevents stale OFF telemetry from
        # falsely verifying the stop.
        self.stop_requested_at = dt_util.utcnow()
        self.stop_attempts += 1
        self.off_checks = 0
        if self.owned:
            self._persist_session(True)
        self._update("STOP_REQUESTED", f"{self.stop_context}; awaiting Geely confirmation")
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
            soc = self._soc()
            reached_target = (
                state == "COMPLETED"
                or (state == "STOPPED" and
                    self.stop_context == "Scheduled battery target reached"
                    and soc is not None and soc >= self.owned_target)
            )
            outcome = (
                "completed" if reached_target
                else "expired" if self.stop_context in (
                    "Scheduled ready-by deadline reached",
                    "100% ready-by deadline passed without confirmed prior charging",
                    "100% session disconnected after ready-by; expired",
                )
                else "disabled" if self.stop_context == "Scheduled charge disabled while running"
                else "deferred" if self.stop_context == "Schedule revised; charging not yet needed"
                else "interrupted" if state == "INTERRUPTED"
                else "cancelled"
            )
            self.finished_deadlines[
                (self.owned_day, self.owned_deadline.date().isoformat())
            ] = {"target": self.owned_target, "soc": soc, "outcome": outcome}

        if (state == "STOPPED" and self.stop_started_at is not None
                and self.stop_watch_until is None):
            # A rebound does not extend this bounded watch indefinitely.
            self.stop_watch_until = dt_util.utcnow() + STOP_WATCH
        self.owned = False
        self.owned_target = None
        self.owned_day = None
        self.owned_deadline = None
        self.started_at = None
        self.saw_charging = False
        self.full_overrun_authorized = False
        self.off_checks = 0
        self.stop_requested_at = None
        self.stop_started_at = None
        self.stop_attempts = 0
        self.stop_context = ""
        self.unexpected_since = None
        self._recovery_started_at = None
        self._persist_finished()
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
        if changed:
            # A newly edited target/ready-by is fresh intent, not a license
            # to inherit a 100%-balancing extension from the old plan.
            self.full_overrun_authorized = False
            self._persist_session(True)

        if changed:
            soc = self._soc()
            # Only an explicit battery-target or ready-time edit can defer an
            # owned charge. Never pause because ordinary SoC updates move the
            # dynamically estimated start time. Continue an already-started
            # session otherwise; this avoids stop/start oscillation.
            if soc is not None and soc < self.owned_target:
                planned_start = charge_start_at(
                    deadline, target=self.owned_target, soc=soc,
                    rate_kw=self._effective_kw(),
                    capacity_kwh=DEFAULT_USABLE_CAPACITY_KWH,
                )
                if planned_start > dt_util.now():
                    revised = ChargeDecision(
                        action="WAIT",
                        reason="Revised schedule starts later; stopping until needed",
                        day=self.owned_day, target=self.owned_target,
                        start_at=planned_start, ready_by=deadline,
                    )
                    self._update(
                        "WAITING",
                        f"Schedule revised: charging needed from "
                        f"{planned_start.strftime('%H:%M')}",
                        revised,
                    )
                    await self._request_stop(
                        "Schedule revised; charging not yet needed"
                    )
                    return False

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
            # A public-mode change must block ALL further automatic commands,
            # including pending stop retries and emergency interventions.
            if self._public_mode():
                self.stop_watch_until = None
                if self.owned or self.stop_requested_at is not None:
                    self._release("BLOCKED", "Public mode enabled; ownership released")
                else:
                    self._update("BLOCKED", "Public charging mode; commands suppressed")
                return

            # Keep watching recent integration-owned stops even when Off:
            # a delayed Geely start can arrive AFTER initial OFF feedback.
            if self.stop_watch_until is not None:
                if self.manual.owned:
                    # An explicitly authorised manual charge is a NEW session,
                    # not a rebound from an earlier automatic STOP. The manual
                    # controller now owns both the vehicle and its eventual
                    # stop verification. Never cancel that charge here.
                    self.stop_watch_until = None
                elif dt_util.utcnow() >= self.stop_watch_until:
                    self.stop_watch_until = None
                elif self.stop_requested_at is None and self._charging():
                    await self._request_stop(
                        "Charging resumed after verified stop; enforcing cancellation"
                    )
                    return

            if self.mode == "Off" and self.stop_requested_at is None:
                return

            # Confirmation/retry must run even after the user disables active
            # mode, otherwise an in-flight stop could be abandoned.
            if self.stop_requested_at is not None:
                self.off_checks = self.off_checks + 1 if self._stopped() else 0
                if (self.off_checks >= 2 and self.stop_started_at is not None
                        and dt_util.utcnow() - self.stop_started_at >= STOP_SETTLE):
                    context = self.stop_context
                    self._release("STOPPED", f"Verified charging stopped: {context}")
                    self._notice("stop_verified", f"Charging stopped and verified: {context}")
                    return
                elapsed = dt_util.utcnow() - self.stop_requested_at
                if elapsed >= STOP_RETRY:
                    # When a fresh OFF/zero report has arrived, wait for the
                    # second observation instead of resetting its counter with
                    # a needless retry. A stale or positive power report still
                    # triggers bounded reassertion of the OFF command.
                    if self._stopped():
                        return
                    if self.stop_attempts < 3:
                        await self._request_stop("Retrying unconfirmed stop")
                    else:
                        self._update("ERROR", "Stop not verified; check vehicle immediately")
                        self._notice("error", "Automatic stop remains unconfirmed")
                return

            if self.owned:
                # The deadline closes the appointment absolutely, even while
                # recovering HA state. Non-100% sessions STOP at ready-by
                # regardless of SoC. For 100%, ONLY an established physical
                # charge already flowing before ready-by can keep running.
                # Never permit a previously missed charge to begin on a later
                # plug event, even if Geely has not reported a start yet.
                if self.owned_deadline is not None and dt_util.now() >= self.owned_deadline:
                    if self.owned_target < 100:
                        await self._request_stop("Scheduled ready-by deadline reached")
                        return
                    if not self.full_overrun_authorized:
                        await self._request_stop(
                            "100% ready-by deadline passed without confirmed prior charging"
                        )
                        return
                    if (self.manual.plug
                            and self._raw(self.manual.plug) == "off"
                            and not self._confirmed_charge_power()):
                        # A valid 100% charge may finish late, but only while
                        # the same physical session remains connected. Never
                        # carry a morning owner across an unplug/replug.
                        await self._request_stop(
                            "100% session disconnected after ready-by; expired"
                        )
                        return
                if self._recovery_started_at is not None:
                    # Cloud switch telemetry often lags actual wallbox power.
                    # Hold the previous ownership for a bounded grace period
                    # instead of issuing duplicate START or a false STOP.
                    if self._charging():
                        self.saw_charging = True
                        self._recovery_started_at = None
                    elif (dt_util.utcnow() - self._recovery_started_at
                          < timedelta(seconds=90)):
                        self._update(
                            "RECOVERING",
                            "Checking previous charge after Home Assistant restart",
                        )
                        return
                    elif self._soc() is None or self._raw(self.manual.charging_switch) not in ("on", "off"):
                        self._update("RECOVERING", "Geely telemetry unavailable on restart")
                        return
                    elif self._soc() >= self.owned_target:
                        self._release("COMPLETED", "Previous session reached target")
                        return
                    else:
                        # Clear a definitely inactive old session. The enabled
                        # schedule will be recalculated on the next tick; no
                        # duplicate ON is sent by restore itself.
                        self.stop_context = "Schedule revised; charging not yet needed"
                        self._release("INTERRUPTED", "Recovered stopped session below target")
                        return
                # A latched session remains authorised after the calculated
                # start time shifts with rising SOC and after ready-by.
                if self._emergency() or not self._legacy_clear():
                    await self._request_stop("Safety interlock activated")
                    return
                if self.mode != "Active":
                    await self._request_stop("Automatic mode no longer active")
                    return
                if not await self._reconcile_owned_schedule():
                    return
                # The schedule may have been edited on this tick. Reapply the
                # cutoff to the revised deadline before any continuation.
                if self.owned_deadline is not None and dt_util.now() >= self.owned_deadline:
                    if self.owned_target < 100:
                        await self._request_stop("Scheduled ready-by deadline reached")
                        return
                    if not self.full_overrun_authorized:
                        await self._request_stop(
                            "100% ready-by deadline passed without confirmed prior charging"
                        )
                        return
                if (self.owned_target == 100
                        and self.owned_deadline is not None
                        and dt_util.now() < self.owned_deadline
                        and self._confirmed_charge_power()
                        and not self.full_overrun_authorized):
                    self.full_overrun_authorized = True
                    self._persist_session(True)
                soc = self._soc()
                if self.owned_target < 100 and (soc is None or soc >= self.owned_target):
                    await self._request_stop(
                        "Scheduled battery target reached" if soc is not None
                        else "Battery telemetry lost"
                    )
                    return
                if self._charging():
                    self.saw_charging = True
                    self.off_checks = 0
                elif self.saw_charging:
                    self.off_checks += 1
                if self.saw_charging and self.off_checks >= 2:
                    soc = self._soc()
                    if soc is not None and (soc >= self.owned_target
                            or (self.owned_target == 100 and soc >= 99)):
                        # Geely may terminate balancing while cloud SoC
                        # rounds down to 99%. Require the observed OFF state;
                        # never use 99% alone to send a stop command.
                        self._release("COMPLETED", "Geely finished the scheduled target")
                        self._notice("complete", "Scheduled charging completed")
                    else:
                        # A charger/cloud interruption is NOT completion. Do
                        # not silently auto-restart on transient OFF readings:
                        # this session needs an explicit resume to avoid loops.
                        target = self.owned_target
                        self._release(
                            "INTERRUPTED",
                            f"Geely stopped before reaching {target}%; "
                            "explicit resume required",
                        )
                        self._notice(
                            "interrupted",
                            "Geely charging ended before target; review and resume",
                        )
                    return
                if (
                    not self.saw_charging and self.started_at
                    and dt_util.utcnow() - self.started_at >= timedelta(minutes=3)
                ):
                    await self._request_stop("Charge start not confirmed in three minutes")
                return

            # Emergency stop can intervene in an observed charging session
            # only while the user has NOT designated public charging mode.
            if self._emergency():
                if (self.mode == "Active" and not self.manual.owned
                        and self._charging()):
                    await self._request_stop("Emergency stop requested")
                else:
                    self._update("BLOCKED", "Emergency stop active; starts suppressed")
                return

            # Preserve a vehicle session already active when HA restarted
            # if the previous owner record could not be recovered. But do NOT
            # grant blanket protection to new plug-in charging hours later.
            # New observed charging must follow the schedule policy, so a
            # missed morning appointment cannot charge through the afternoon.
            if (not self.manual.owned and self.stop_watch_until is None
                    and getattr(self.manual, "unmanaged_charge", False)):
                self.unexpected_since = None
                self._update(
                    "EXTERNAL",
                    "Charging was already present during integration startup; "
                    "ownership unknown and not automatically interrupted",
                )
                return

            # The normal manual control takes priority over the schedule.
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
            # Accept an increased target/reenabled schedule as a new request
            # immediately, even when its estimated start time is in future.
            self._rearm_if_requested(policy)
            if policy.action in ("BLOCKED", "UNKNOWN"):
                self.unexpected_since = None
                self._update(policy.action, policy.reason, policy)
                return
            if policy.action == "START":
                self.unexpected_since = None
                await self._request_start(policy)
                return
            if (policy.action == "AUTHORISED" and policy.ready_by is not None
                    and policy.target is not None and self._charging()):
                # A car/wallbox may start automatically on plug-in while a
                # genuine scheduled window is open. Adopt the already-flowing
                # charge WITHOUT issuing a second ON, then enforce target and
                # ready-by using the normal owned-session logic.
                key = self._deadline_key(policy)
                self._rearm_if_requested(policy)
                if key in self.finished_deadlines:
                    self._update(
                        "PAUSED", "Earlier session ended; Resume schedule required",
                        policy,
                    )
                    return
                if self._soc() is not None and self._soc() < policy.target:
                    if dt_util.now() >= policy.ready_by:
                        self._update("EXPIRED", "Ready-by deadline already passed", policy)
                        return
                    self.owned = True
                    self.owned_target = policy.target
                    self.owned_day = policy.day
                    self.owned_deadline = policy.ready_by
                    self.started_at = dt_util.utcnow()
                    self.saw_charging = True
                    self.full_overrun_authorized = (
                        policy.target == 100 and self._confirmed_charge_power()
                    )
                    self.stop_watch_until = None
                    if hasattr(self.manual, "stop_watch_until"):
                        self.manual.stop_watch_until = None
                    self._persist_session(True)
                    self._update(
                        "CHARGING",
                        "Charging started during authorised schedule; "
                        "adopted without duplicate START",
                        policy,
                    )
                    return
            # A prior session can be finished even when the planner is
            # currently WAITing for a newly estimated start time. Keep the
            # actual outcome visible rather than replacing it with WAITING.
            if policy.action == "WAIT" and policy.ready_by is not None:
                key = (policy.day, policy.ready_by.date().isoformat())
                previous = self.finished_deadlines.get(key)
                if previous is not None:
                    if previous["outcome"] == "completed":
                        self._update(
                            "COMPLETED", "Scheduled target already achieved "
                            "for this departure; no repeat start", policy,
                        )
                    elif previous["outcome"] == "deferred":
                        self._update(
                            "WAITING",
                            "Schedule revised; waiting for its new start time",
                            policy,
                        )
                    else:
                        self._update(
                            "PAUSED", "Previous charge ended below target; "
                            "a deliberate resume is needed", policy,
                        )
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
        """Integration reload is never a user-requested vehicle STOP.

        Persisted session ownership and pending-stop state are resumed on
        setup. Do not clear 100% full-charge balancing or sub-100% charging.
        """
        if self.owned:
            self._persist_session(True)
        self.mode = "Off"
        self.manual._notify()
