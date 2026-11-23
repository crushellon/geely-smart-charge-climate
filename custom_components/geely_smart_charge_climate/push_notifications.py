"""Real Home Assistant mobile-app push notifications for Geely EX5 events.

The normal HA Mobile App notify service is used (not HA's inbox).
Only source-confirmed state transitions are called 'confirmed'. Geely cloud
service acknowledgements are explicitly labelled as requests.
Deduplication IDs are persisted across HA restarts without new UI entities.
"""
from datetime import datetime, timezone
from math import isfinite
import logging

from homeassistant.components import persistent_notification
from homeassistant.util import dt as dt_util

from .const import DEFAULT_USABLE_CAPACITY_KWH

_LOGGER = logging.getLogger(__name__)

# The user's existing iPhone Companion App service, previously working in
# their YAML automations. This can be overridden through config entry options
# without adding a developer button to the four-tab product dashboard.
DEFAULT_NOTIFY_SERVICE = "mobile_app_tims_iphone"
MAX_RECENT_EVENTS = 120


def valid_soc(raw):
    try:
        n = float(raw)
        return n if isfinite(n) and 0 <= n <= 100 else None
    except (TypeError, ValueError):
        return None


def percent(raw):
    n = valid_soc(raw)
    return f"{n:g}%" if n is not None else "unknown battery %"


def battery_energy(start_soc, end_soc, capacity=DEFAULT_USABLE_CAPACITY_KWH):
    """Approximate battery energy gained, NOT grid-meter energy (kWh)."""
    first = valid_soc(start_soc)
    last = valid_soc(end_soc)
    if first is None or last is None or last < first:
        return None
    return round((last - first) * capacity / 100, 1)


def time_label(iso_or_dt):
    if iso_or_dt is None:
        return "time unknown"
    try:
        dt = (datetime.fromisoformat(iso_or_dt)
              if isinstance(iso_or_dt, str) else iso_or_dt)
        return dt_util.as_local(dt).strftime("%a %d %b, %I:%M %p")
    except (ValueError, TypeError, AttributeError):
        return str(iso_or_dt)


def fresh_event_id(category):
    return f"{category}:{dt_util.utcnow().isoformat(timespec='microseconds')}"


class VehiclePushNotifications:
    def __init__(self, runtime):
        self.runtime = runtime
        self.hass = runtime.hass
        self.entry = runtime.entry
        self.pending = set()
        self.failed = set()
        self.delivered = set(
            str(key) for key in self.entry.options.get("push_delivered_ids", [])
        )
        self.active_starts = set()
        self.options_snapshot = self._tracked_controls(self.entry.options)

    def _service(self):
        configured = self.entry.options.get(
            "phone_notification_service", DEFAULT_NOTIFY_SERVICE
        )
        if not isinstance(configured, str):
            return DEFAULT_NOTIFY_SERVICE
        service = configured.strip()
        if service.startswith("notify."):
            service = service.split(".", 1)[1]
        return service if service and "/" not in service else DEFAULT_NOTIFY_SERVICE

    def emit(self, event_id, title, message):
        """Queue exactly once per event, never from every 15-second tick."""
        if (event_id in self.delivered or event_id in self.pending
                or event_id in self.failed):
            return False
        self.pending.add(event_id)
        self.hass.async_create_task(
            self._send(event_id, title, message)
        )
        return True

    async def _send(self, event_id, title, message):
        service = self._service()
        try:
            if (hasattr(self.hass.services, "has_service")
                    and not self.hass.services.has_service("notify", service)):
                raise ValueError(f"notify.{service} is not registered")
            await self.hass.services.async_call(
                "notify", service,
                {"title": title, "message": message},
                blocking=True,
            )
        except Exception as exc:
            self.failed.add(event_id)
            _LOGGER.warning(
                "Geely iPhone notification %s failed using notify.%s: %s",
                event_id, service, exc,
            )
            # One inbox warning if the mobile service is missing. No
            # success message is falsely attributed to a failed push.
            persistent_notification.async_create(
                self.hass,
                f"Phone push failed using notify.{service}: {exc}. "
                "Check the Home Assistant Companion App notification service.",
                title="Geely iPhone notifications unavailable",
                notification_id=f"geely_push_unavailable_{self.entry.entry_id}",
            )
        else:
            self.delivered.add(event_id)
            history = list(self.entry.options.get("push_delivered_ids", []))
            history.append(event_id)
            # IDs are persisted before any restart, retaining only bounded
            # recent history. Avoid storing notification text or personal data.
            self.runtime._save_options(
                push_delivered_ids=list(dict.fromkeys(history))[-MAX_RECENT_EVENTS:]
            )
        finally:
            self.pending.discard(event_id)

    @staticmethod
    def _tracked_controls(options):
        days = options.get("weekly_schedule", {})
        linked = options.get("charging_linked_comfort", {})
        slots = options.get("climate_schedules", {})
        result = {
            "Automatic charging": options.get("automatic_charging_enabled") is True,
            "Public charging mode": options.get("public_charging_mode") is True,
            "Emergency STOP": options.get("emergency_stop") is True,
            "Independent climate schedules": (
                options.get("scheduled_climate_enabled") is True
            ),
        }
        for day in ("monday", "tuesday", "wednesday", "thursday",
                    "friday", "saturday", "sunday"):
            settings = days.get(day, {}) if isinstance(days, dict) else {}
            result[f"{day.title()} charging schedule"] = (
                isinstance(settings, dict) and settings.get("enabled") is True
            )
            linked_settings = linked.get(day, {}) if isinstance(linked, dict) else {}
            result[f"{day.title()} cabin comfort"] = (
                isinstance(linked_settings, dict)
                and linked_settings.get("enabled") is True
            )
        for slot in range(1, 8):
            settings = slots.get(str(slot), {}) if isinstance(slots, dict) else {}
            result[f"Independent climate slot {slot}"] = (
                isinstance(settings, dict) and settings.get("enabled") is True
            )
            result[f"Climate slot {slot} steering heat"] = (
                isinstance(settings, dict)
                and settings.get("steering_heat") is True
            )
        for profile in ("cool", "warm"):
            settings = options.get(profile, {})
            result[f"{profile.title()} steering heating preference"] = (
                isinstance(settings, dict)
                and bool(settings.get("steering_heat", False))
            )
        return result

    def check_control_changes(self):
        current = self._tracked_controls(self.entry.options)
        before = self.options_snapshot
        self.options_snapshot = current
        for name, value in current.items():
            if name not in before or before[name] == value:
                continue
            condition = "ON" if value else "OFF"
            message = f"{name} set {condition} in Home Assistant."
            if name == "Emergency STOP" and value:
                message += " Stop verification may still be pending; check real power."
            elif name == "Emergency STOP" and not value:
                message += " Previous automatic preference resumes only when safe."
            elif name == "Automatic charging" and value:
                message += " Waiting for the next eligible ready-by window."
            elif name == "Public charging mode" and value:
                message += " Automatic vehicle commands are suppressed."
            self.emit(
                fresh_event_id(f"toggle:{name}:{condition}"),
                "Geely control changed", message,
            )

    def _charge_start_message(self, name, target, ready_by, start_soc, current_soc,
                              power_confirmed=True):
        confirmation = (
            "charging power confirmed" if power_confirmed else
            "Geely charging switch reports ON (power sensor unavailable)"
        )
        return (
            f"{name} {confirmation} at {percent(current_soc)}. "
            f"Started at {percent(start_soc)}; target {percent(target)}."
            + (f" Ready by {time_label(ready_by)}." if ready_by else "")
        )

    def _fresh_vehicle_feedback(self, started_at):
        """Positive power must come from the SAME freshly reported sensor.

        A new Geely 0 kW report cannot make stale Tesla 6 kW valid.
        If neither power sensor exists, Geely switch ON is the fallback.
        """
        if started_at is None or not hasattr(self.hass, "states"):
            return False

        def fresh(state):
            if state is None:
                return False
            stamp = (getattr(state, "last_reported", None)
                     or getattr(state, "last_updated", None))
            return (isinstance(stamp, datetime) and stamp.tzinfo is not None
                    and stamp >= started_at)

        for entity in (
            self.runtime.charging_power,
            getattr(self.runtime, "wallbox_power", None),
        ):
            if not entity:
                continue
            state = self.hass.states.get(entity)
            if state is None or not fresh(state):
                continue
            try:
                power = float(state.state)
                if isfinite(power) and power > 0.25:
                    return True
            except (ValueError, TypeError):
                pass

        if (self.runtime.charging_power is None
                and self.runtime._wallbox_kw() is None):
            switch = self.hass.states.get(self.runtime.charging_switch)
            return fresh(switch) and switch.state == "on"
        return False

    def observe_charging(self):
        """Notify only after HA reports charging power or (sensorless) ON.

        A command having been accepted is not proof Geely started charging.
        """
        runtime = self.runtime
        activity, _power = runtime.vehicle_activity()
        real_power = activity == "CHARGING"
        fallback = (
            activity == "CHARGING_REPORTED" and
            runtime.charging_power is None and runtime._wallbox_kw() is None
        )
        if not (real_power or fallback):
            return
        auto = runtime.auto
        if runtime.owned and runtime.stop_requested_at is None:
            started = runtime.started_at
            if started is None:
                return
            if not self._fresh_vehicle_feedback(started):
                return
            key = f"manual:start:{started.isoformat()}"
            if self.emit(
                key, "Geely manual charging started",
                self._charge_start_message(
                    "Manual", runtime.active_target, None,
                    getattr(runtime, "session_start_soc", None),
                    runtime._raw(runtime.battery),
                    power_confirmed=real_power,
                ),
            ):
                self.active_starts.add(key)
        elif auto.owned and auto.stop_requested_at is None:
            if auto.owned_deadline is None:
                return
            if not self._fresh_vehicle_feedback(auto.started_at):
                return
            key = f"automatic:start:{auto.owned_deadline.isoformat()}:{auto.owned_target}"
            if self.emit(
                key, "Geely automatic charging started",
                self._charge_start_message(
                    f"{auto.owned_day.title()} automatic",
                    auto.owned_target, auto.owned_deadline,
                    getattr(auto, "session_start_soc", None),
                    runtime._raw(runtime.battery),
                    power_confirmed=real_power,
                ),
            ):
                self.active_starts.add(key)

    def charging_ended(self, *, automatic, session_id, start_soc, end_soc,
                       target, status, reason, ready_by=None):
        """Emit only after a controller has read STOP or verified cancellation."""
        name = "Automatic" if automatic else "Manual"
        gain = battery_energy(start_soc, end_soc)
        energy = f" · ~{gain:.1f} kWh added" if gain is not None else ""
        actual = valid_soc(end_soc)
        wanted = valid_soc(target)
        achieved = actual is not None and wanted is not None and actual >= wanted
        near_full = (
            wanted == 100 and actual is not None and 99 <= actual < 100
        )
        outcome = (
            "Target reached" if achieved else
            "Geely reports 99%; 100% target not verified" if near_full else
            "Target not reached" if status in ("STOPPED", "COMPLETED", "INTERRUPTED")
            else "Control released; vehicle stop not confirmed"
        )
        # Put the complete outcome in a short iPhone lock-screen message.
        # Detailed reason/ready-by remains in the HA controller history.
        if "geely" in str(reason).lower():
            cause = " · Ended by Geely"
        elif "deadline" in str(reason).lower() or "ready-by" in str(reason).lower():
            cause = " · Deadline"
        else:
            cause = ""
        title = (f"Geely {name.lower()} charge complete" if achieved
                 else f"Geely {name.lower()} charge ended")
        message = (f"{percent(start_soc)} → {percent(end_soc)} · "
                   f"{outcome} (target {percent(target)}){energy}{cause}")
        self.emit(f"{name.lower()}:end:{session_id}:{status}", title, message)

    def climate_event(self, *, key, action, kind, setting=None, time=None,
                      vehicle_state=None, success=True):
        when = f" Ready by {time_label(time)}." if time else ""
        requested = (
            "Geely climate reports active"
            if vehicle_state not in (None, "off", "unknown", "unavailable")
            else "Climate command accepted; vehicle feedback pending"
        )
        if action == "off":
            # The scheduler verifies the reported OFF separately. Routine
            # success is silent; this method is called on failed verification.
            if success:
                return
            requested = "OFF not confirmed; check the vehicle"
        elif not success:
            requested = "Geely climate command failed; check vehicle"
        label = "started" if action == "on" else "stopped"
        details = (
            f" Cabin {setting['temperature']}°C, driver seat "
            f"{setting['driver_seat']}, passenger seat "
            f"{setting['passenger_seat']}, steering heat "
            f"{'ON' if setting['steering_heat'] else 'OFF'}."
            if action == "on" and setting else ""
        )
        self.emit(
            f"climate:{action}:{key}",
            f"Geely {kind} climate {label}",
            f"{kind.title()} climate {label}. {requested}.{details}{when}",
        )
