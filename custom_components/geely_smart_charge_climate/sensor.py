"""Read-only observer and hypothetical charging simulation sensors.

No charging or climate commands are issued by this module.
"""

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BATTERY_ENTITY, CONF_CHARGING_POWER, CONF_CHARGING_SWITCH,
    CONF_CHARGER_RATED_KW, DEFAULT_CHARGER_RATED_KW,
    DEFAULT_USABLE_CAPACITY_KWH, DOMAIN,
)
from .rate_learning import RateLearner, effective_fallback_kw
from .discovery import discover_plug_entity
from .simulator import simulate
from .weekly_schedule import next_charge
from .climate_schedule import next_event
from .charge_climate import snapshot as linked_comfort_snapshot
from .vehicle_activity import vehicle_activity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose read-only and hypothetical results; never command devices."""
    async_add_entities([
        GeelyObservationSensor(hass, entry),
        GeelySimulationSensor(hass, entry),
        ClimateNextSessionSensor(hass, entry),
        AutomaticChargeStatusSensor(entry),
        ManualClimateStatusSensor(entry),
        ManualChargingStatusSensor(hass, entry),
        VehicleChargingStatusSensor(hass, entry),
        ScheduledClimateStatusSensor(entry),
    ])


class GeelyObservedBase(SensorEntity):
    """Handle source subscriptions shared by the passive sensors."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._battery = entry.data[CONF_BATTERY_ENTITY]
        self._switch = entry.data[CONF_CHARGING_SWITCH]
        self._power = entry.data.get(CONF_CHARGING_POWER)
        self._plug = discover_plug_entity(hass, self._battery)

    async def async_added_to_hass(self) -> None:
        """Refresh when selected source entities update."""
        await super().async_added_to_hass()
        entities = [self._battery, self._switch]
        if self._power:
            entities.append(self._power)
        if self._plug:
            entities.append(self._plug)

        @callback
        def changed(event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, entities, changed)
        )


class GeelyObservationSensor(GeelyObservedBase):
    """Report telemetry availability without writing to the vehicle."""

    _attr_name = "Observer status"
    _attr_icon = "mdi:eye-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_observer_status"

    @property
    def native_value(self) -> str:
        """Return passive source availability."""
        battery = self.hass.states.get(self._battery)
        charging = self.hass.states.get(self._switch)
        if battery is None or charging is None:
            return "Missing source"
        if battery.state in ("unknown", "unavailable") or charging.state in (
            "unknown", "unavailable"
        ):
            return "Source unavailable"
        return "Monitoring"

    @property
    def extra_state_attributes(self) -> dict:
        """Show selected sources and raw readings."""
        result = {
            "control_mode": ("automatic_active" if self.entry.runtime_data.auto.mode == "Active"
                             else "monitor" if self.entry.runtime_data.auto.mode == "Monitor"
                             else "read_only"),
            "battery_source": self._battery,
            "charging_switch_source": self._switch,
            "plug_source": self._plug,
        }
        for name, entity_id in (
            ("battery_state", self._battery),
            ("charging_switch_state", self._switch),
            ("charging_power_state", self._power),
            ("plug_state", self._plug),
        ):
            if entity_id:
                state = self.hass.states.get(entity_id)
                result[name] = state.state if state else "missing"
        return result


class GeelySimulationSensor(GeelyObservedBase):
    """Display hypothetical next charge timing, without issuing commands."""

    _attr_name = "Simulation decision"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_simulation_decision"
        self._rated_kw = float(entry.data.get(CONF_CHARGER_RATED_KW, DEFAULT_CHARGER_RATED_KW))
        self._learner = RateLearner()
        # Deliberately start with clean learning data after removal of
        # test-cycle/idle-power contamination. Legacy v1 samples are ignored.
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_rate_learning_geely_v2")

    def _result(self):
        now = dt_util.now()
        plan = next_charge(now, self.entry.options.get("weekly_schedule", {}))
        if plan is None:
            return None
        ready = plan.ready_by
        battery = self.hass.states.get(self._battery)
        charging = self.hass.states.get(self._switch)
        if battery is None or battery.state in ("unknown", "unavailable"):
            soc = None
        else:
            try:
                soc = float(battery.state)
            except (TypeError, ValueError):
                soc = None
        rate = self._learner.learned_rate
        if rate is None:
            rate = effective_fallback_kw(self._rated_kw) * 100 / DEFAULT_USABLE_CAPACITY_KWH
        effective_kw = rate * DEFAULT_USABLE_CAPACITY_KWH / 100
        plug_state = self.hass.states.get(self._plug) if self._plug else None
        plugged = (
            True if plug_state and plug_state.state == "on"
            else False if plug_state and plug_state.state == "off"
            else None
        )
        return simulate(
            now=now, ready_by=ready, soc=soc,
            target=plan.target, effective_kw=effective_kw,
            usable_kwh=DEFAULT_USABLE_CAPACITY_KWH,
            charging=bool(charging and charging.state == "on"),
            plugged=plugged,
        )

    @property
    def native_value(self) -> str:
        """Return the hypothetical outcome as an advisory state."""
        result = self._result()
        return result.action if result is not None else "NO_SCHEDULE"

    @property
    def extra_state_attributes(self) -> dict:
        """Describe assumptions rather than pretending to control a session."""
        plan = next_charge(dt_util.now(), self.entry.options.get("weekly_schedule", {}))
        result = self._result()
        return {
            "simulation_only": False,
            "vehicle_commands_sent": (
                self.entry.runtime_data.scheduled_climate.active is not None
                and self.entry.runtime_data.scheduled_climate.active.get("applied") is True
            ),
            "schedule_source": "configured weekly schedule (simulation only)",
            "next_schedule_day": plan.day if plan else None,
            "target_percent": plan.target if plan else None,
            "ready_time": plan.ready_by.strftime("%H:%M") if plan else None,
            "charger_rated_kw": self._rated_kw,
            "learning_data_generation": "geely_v2",
            "learning_power_source": self._power if self._power else "Geely switch only",
            "charge_rate_source": "learned" if self._learner.learned_rate is not None else "initial_estimate",
            "learned_percentage_points_per_hour": self._learner.learned_rate,
            "learning_sample_count": len(self._learner.samples),
            "assumed_effective_kw": (self._learner.learned_rate * DEFAULT_USABLE_CAPACITY_KWH / 100) if self._learner.learned_rate is not None else effective_fallback_kw(self._rated_kw),
            "assumed_usable_capacity_kwh": DEFAULT_USABLE_CAPACITY_KWH,
            "estimated_minutes": result.remaining_minutes if result else None,
            "estimated_start": result.start_at.isoformat() if result and result.start_at else None,
            "ready_by": result.ready_by.isoformat() if result else None,
            "termination_policy": result.termination if result else None,
            "reason": result.reason if result else "No schedule days enabled",
            "plug_status_configured": self._plug is not None,
            "plug_source": self._plug,
            "plug_state": (self.hass.states.get(self._plug).state if self._plug and self.hass.states.get(self._plug) else "unavailable"),
        }

    async def async_added_to_hass(self) -> None:
        """Recompute at least once each minute as the deadline approaches."""
        await super().async_added_to_hass()
        self._learner = RateLearner.from_storage(await self._store.async_load())

        @callback
        def record_change(event) -> None:
            """Record live source changes, not periodic ticks."""
            charging_state = self.hass.states.get(self._switch)
            charge_active = bool(charging_state and charging_state.state == "on")
            if self._power:
                power_state = self.hass.states.get(self._power)
                try:
                    charge_active = (charge_active and power_state is not None
                                     and float(power_state.state) >= 1.0)
                except (ValueError, TypeError):
                    charge_active = False
            battery_state = self.hass.states.get(self._battery)
            try:
                soc = float(battery_state.state) if battery_state is not None else None
            except (ValueError, TypeError):
                soc = None
            new_sample = self._learner.observe(
                soc=soc, charging=charge_active, at=dt_util.now()
            )
            if new_sample:
                self._store.async_delay_save(self._learner.to_storage, 5)
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._battery, self._switch]
                + ([self._power] if self._power else []),
                record_change,
            )
        )

        @callback
        def minute_tick(now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, minute_tick, timedelta(minutes=1))
        )


class ClimateNextSessionSensor(SensorEntity):
    """Display next independent climate appointment and runtime activity."""

    _attr_has_entity_name = True
    _attr_name = "Next climate session"
    _attr_icon = "mdi:car-defrost-front"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate_next"

    @property
    def native_value(self) -> str:
        session = next_event(dt_util.now(), self.entry.options)
        return f"Slot {session['slot']}" if session else "NO_SCHEDULE"

    @property
    def extra_state_attributes(self) -> dict:
        session = next_event(dt_util.now(), self.entry.options)
        if not session:
            return {"simulation_only": False, "vehicle_commands_sent": False,
                    "reason": "No independent climate slots enabled"}
        return {
            "simulation_only": True,
            "vehicle_commands_sent": False,
            "slot": session["slot"],
            "day": session["day"],
            "ready_by": session["ready_by"].isoformat(),
            "start_at": session["start_at"].isoformat(),
            "end_at": session["end_at"].isoformat(),
            "temperature": session["temperature"],
            "driver_seat": session["driver_seat"],
            "passenger_seat": session["passenger_seat"],
            "steering_heat": session["steering_heat"],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def minute_tick(now):
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, minute_tick, timedelta(minutes=1))
        )


class AutomaticChargeStatusSensor(SensorEntity):
    """Auditable authorisation decisions and command verification status."""

    _attr_has_entity_name = True
    _attr_name = "Automatic charging decision"
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_automatic_charge_decision"

    @property
    def native_value(self):
        return self.entry.runtime_data.auto.status

    @property
    def extra_state_attributes(self):
        auto = self.entry.runtime_data.auto
        decision = auto.decision
        day = auto.owned_day or (decision.day if decision else None)
        comfort = linked_comfort_snapshot(self.entry.options, day) if day else None
        return {
            "mode": auto.mode,
            "message": auto.message,
            "decision": decision.action if decision else None,
            "reason": decision.reason if decision else None,
            "schedule_day": decision.day if decision else None,
            "scheduled_target": decision.target if decision else None,
            "estimated_start": decision.start_at.isoformat()
                               if decision and decision.start_at else None,
            "ready_by": decision.ready_by.isoformat()
                        if decision and decision.ready_by else None,
            "public_charging_mode": auto._public_mode(),
            "public_charging_interlock": (
                "Integration switch" if self.entry.options.get("public_charging_mode") is True
                else "Legacy helper" if auto._raw("input_boolean.ev_public_charging_mode") == "on"
                else "Off"
            ),
            "vehicle_charging": auto._raw(auto.manual.charging_switch),
            "charging_power_kw": auto._power(),
            "battery_percent": auto._soc(),
            "owns_automatic_session": auto.owned,
            "active_target": auto.owned_target,
            "active_ready_by": auto.owned_deadline.isoformat()
                               if auto.owned_deadline else None,
            "linked_comfort_enabled": comfort["enabled"] if comfort else None,
            "linked_comfort_profile": comfort["profile"] if comfort else None,
            "linked_comfort_temperature": comfort["temperature"] if comfort else None,
            "linked_comfort_driver_seat": comfort["driver_seat"] if comfort else None,
            "linked_comfort_passenger_seat": comfort["passenger_seat"] if comfort else None,
            "linked_comfort_steering_heat": comfort["steering_heat"] if comfort else None,
            "linked_comfort_lead_minutes": comfort["lead_minutes"] if comfort else None,
            "linked_comfort_hold_minutes": comfort["hold_minutes"] if comfort else None,
            "linked_comfort_commands_enabled": (
                comfort["commands_enabled"] if comfort else False
            ),
            "stop_attempts": auto.stop_attempts,
            "stop_confirmation_pending": auto.stop_requested_at is not None,
            "stop_verification": (
                "Awaiting fresh Geely telemetry"
                if auto.stop_requested_at is not None and not auto._stop_telemetry_fresh()
                else "Charging still reported; stop not verified"
                if auto.stop_requested_at is not None and auto._charging()
                else "Settling and checking stop"
                if auto.stop_requested_at is not None
                else "Watching for delayed charging"
                if auto.stop_watch_until is not None
                   and dt_util.utcnow() < auto.stop_watch_until
                else "Idle"
            ),
            "stop_watch_until": auto.stop_watch_until.isoformat()
                                if auto.stop_watch_until else None,
            "last_event": auto.last_event,
            "restarts_disarm_controller": False,
            "automatic_enabled_preference": self.entry.options.get(
                "automatic_charging_enabled", False
            ) is True,
            "climate_commands_enabled": (
                self.entry.options.get("scheduled_climate_enabled", False) is True
                or any(
                    isinstance(config, dict)
                    and config.get("enabled") is True
                    and self.entry.options.get("automatic_charging_enabled") is True
                    and self.entry.options.get(
                        "weekly_schedule", {}
                    ).get(day, {}).get("enabled") is True
                    for day, config in self.entry.options.get(
                        "charging_linked_comfort", {}
                    ).items()
                )
            ),
            "independent_climate_commands_enabled": (
                self.entry.options.get("scheduled_climate_enabled", False) is True
            ),
            "enabled_schedule_days": [
                day for day, values in
                self.entry.options.get("weekly_schedule", {}).items()
                if isinstance(values, dict) and values.get("enabled") is True
            ],
            "live_policy_action": (
                auto._policy().action if auto.mode == "Monitor" else None
            ),
            "live_policy_reason": (
                auto._policy().reason if auto.mode == "Monitor" else None
            ),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        auto = self.entry.runtime_data.auto
        self.async_on_remove(self.entry.runtime_data.listen(self.async_write_ha_state))

        # Independent read-only Monitor refresh, in addition to the live
        # controller's central timer. Also updates schedule diagnostics.
        @callback
        def refresh(_now):
            if auto.mode == "Monitor":
                self.hass.async_create_task(auto.async_tick())
            else:
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, refresh, timedelta(seconds=15))
        )


class ManualClimateStatusSensor(SensorEntity):
    """Reports submitted manual cabin commands, not physical confirmation."""

    _attr_has_entity_name = True
    _attr_name = "Manual climate status"
    _attr_icon = "mdi:car-defrost-front"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_manual_climate_status"

    @property
    def native_value(self):
        return self.entry.runtime_data.climate.status

    @property
    def extra_state_attributes(self):
        scheduler = self.entry.runtime_data.scheduled_climate
        expires = scheduler.manual_expires_at
        remaining = (
            max(0, round((expires - dt_util.now()).total_seconds()))
            if scheduler.manual_override and expires is not None else None
        )
        return {
            "message": self.entry.runtime_data.climate.message,
            "manual_only": True,
            "manual_comfort_active": scheduler.manual_override,
            "auto_off_after_minutes": 30,
            "manual_comfort_expires_at": (
                expires.isoformat() if scheduler.manual_override and expires else None
            ),
            "manual_comfort_seconds_remaining": remaining,
            "scheduled_climate_active": scheduler.active is not None,
            "manual_comfort_timeout_error": self.entry.options.get(
                "manual_climate_timeout_error"
            ),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.entry.runtime_data.listen(self.async_write_ha_state))


class ManualChargingStatusSensor(GeelyObservedBase):
    """Manual ownership status never claims the vehicle is idle when charging.

    The integration can observe charging after an older version reload,
    without having enough historical data to prove a manual target.
    """

    _attr_has_entity_name = True
    _attr_name = "Manual charging status"
    _attr_icon = "mdi:battery-charging"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_manual_charge_status"

    @property
    def native_value(self):
        runtime = self.entry.runtime_data
        if runtime.owned:
            return {"RUNNING": "CHARGING", "DISARMED": "IDLE"}.get(
                runtime.status, runtime.status
            )
        if runtime.auto.stop_requested_at is not None:
            return "STOP_REQUESTED"
        if runtime.auto.owned:
            return "AUTOMATIC"
        activity, _ = runtime.vehicle_activity()
        if runtime.unmanaged_charge or activity in (
                "CHARGING", "CHARGING_REPORTED"):
            return "CHARGING_UNATTRIBUTED"
        return {"DISARMED": "IDLE", "ARMED": "IDLE",
                "RUNNING": "IDLE", "EXTERNAL": "IDLE"}.get(
                    runtime.status, runtime.status
                )

    @property
    def extra_state_attributes(self):
        runtime = self.entry.runtime_data
        return {
            "message": runtime.message,
            "target": runtime.target,
            "active_target": runtime.active_target,
            "owns_manual_session": runtime.owned,
            "stop_pending": runtime.stop_requested_at is not None,
            "automatic_charging_paused_during_manual": runtime.auto.mode == "Off",
            "charging_observed": runtime._vehicle_indicates_charging(),
            "charging_source": runtime.vehicle_activity()[0],
            "session_attribution": (
                "manual" if runtime.owned else
                "automatic" if runtime.auto.owned else
                "unknown" if runtime.unmanaged_charge
                or runtime._vehicle_indicates_charging() else "none"
            ),
            "unmanaged_charging": runtime.unmanaged_charge,
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.entry.runtime_data.listen(self.async_write_ha_state))


class VehicleChargingStatusSensor(GeelyObservedBase):
    """Vehicle charge indicator separate from automatic/manual owner state."""

    _attr_name = "Vehicle charging status"
    _attr_icon = "mdi:ev-station"

    def __init__(self, hass, entry):
        super().__init__(hass, entry)
        self._attr_unique_id = f"{entry.entry_id}_vehicle_charging_status"

    @property
    def native_value(self):
        return self.entry.runtime_data.vehicle_activity()[0]

    @property
    def extra_state_attributes(self):
        runtime = self.entry.runtime_data
        activity, power = runtime.vehicle_activity()
        geely_activity, geely_power = vehicle_activity(
            runtime._raw(runtime.charging_switch),
            runtime._raw(runtime.charging_power),
        )
        return {
            "geely_charging_switch": runtime._raw(runtime.charging_switch),
            "geely_power_kw": geely_power,
            "wallbox_power_kw": runtime._wallbox_kw(),
            "source": ("Geely charging power"
                       if activity == "CHARGING" else "Geely charging switch"
                       if activity == "CHARGING_REPORTED" else "Geely telemetry"),
            "attribution": (
                "manual" if runtime.owned else
                "automatic" if runtime.auto.owned else
                "unknown" if runtime.unmanaged_charge or
                activity in ("CHARGING", "CHARGING_REPORTED") else "none"
            ),
            "automatic_enabled_preference": (
                self.entry.options.get("automatic_charging_enabled", False) is True
            ),
            "controller_will_not_stop_unattributed_charge": (
                runtime.auto.mode != "Active" or runtime.public_mode()
            ),
            "unattributed_charge_policy": (
                "Public mode - vehicle commands suppressed"
                if runtime.public_mode() else
                "Automatic schedule - unexpected home charging checked and stopped"
                if runtime.auto.mode == "Active" else
                "Automatic charging disabled - observation only"
            ),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        wallbox = self.entry.runtime_data.wallbox_power
        if self.hass.states.get(wallbox) is not None:
            @callback
            def wallbox_changed(_event):
                self.async_write_ha_state()

            self.async_on_remove(async_track_state_change_event(
                self.hass, [wallbox], wallbox_changed
            ))


class ScheduledClimateStatusSensor(SensorEntity):
    """Scheduled cabin activity/owner and last command status."""

    _attr_has_entity_name = True
    _attr_name = "Scheduled climate status"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scheduled_climate_status"

    @property
    def native_value(self):
        return self.entry.runtime_data.scheduled_climate.status

    @property
    def extra_state_attributes(self):
        controller = self.entry.runtime_data.scheduled_climate
        return {
            "message": controller.message,
            "active_session": controller.active["key"] if controller.active else None,
            "session_end": controller.active.get("end_at") if controller.active else None,
            "manual_override": controller.manual_override,
            "suppressed_occurrence": controller.suppressed_key,
            "completed_occurrences": len(controller.completed),
            "vehicle_commands_live": True,
            "scheduled_climate_enabled": self.entry.options.get(
                "scheduled_climate_enabled", False
            ) is True,
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.entry.runtime_data.listen(self.async_write_ha_state)
        )
