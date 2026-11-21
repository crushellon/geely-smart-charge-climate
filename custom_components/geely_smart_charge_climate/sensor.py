"""Read-only observer and hypothetical charging simulation sensors.

No charging or climate commands are issued by this module.
"""

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
        LiveTestStatusSensor(entry),
        AutomaticChargeStatusSensor(entry),
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
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_rate_learning")

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
            "simulation_only": True,
            "vehicle_commands_sent": False,
            "schedule_source": "configured weekly schedule (simulation only)",
            "next_schedule_day": plan.day if plan else None,
            "target_percent": plan.target if plan else None,
            "ready_time": plan.ready_by.strftime("%H:%M") if plan else None,
            "charger_rated_kw": self._rated_kw,
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

        def record_change(event) -> None:
            """Record live source changes, not periodic ticks."""
            charging_state = self.hass.states.get(self._switch)
            charge_active = bool(charging_state and charging_state.state == "on")
            if self._power:
                power_state = self.hass.states.get(self._power)
                try:
                    charge_active = charge_active and power_state is not None and float(power_state.state) > 0
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

        def minute_tick(now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, minute_tick, timedelta(minutes=1))
        )


class ClimateNextSessionSensor(SensorEntity):
    """Show hypothetical next climate session; never control the vehicle."""

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
            return {"simulation_only": True, "vehicle_commands_sent": False,
                    "reason": "No climate slots enabled"}
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

        def minute_tick(now):
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, minute_tick, timedelta(minutes=1))
        )


class LiveTestStatusSensor(SensorEntity):
    """Observable state of the opt-in manual test controller."""

    _attr_has_entity_name = True
    _attr_name = "Live test status"
    _attr_icon = "mdi:shield-car"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_live_test_status"

    @property
    def native_value(self):
        return self.entry.runtime_data.status

    @property
    def extra_state_attributes(self):
        live = self.entry.runtime_data
        return {
            "message": live.message,
            "armed": live.armed,
            "owns_session": live.owned,
            "manual_target": live.target,
            "active_target": live.active_target,
            "vehicle_commands_sent_by_simulation": False,
            "automatic_scheduling_enabled": live.auto.mode == "Active",
            "plug_state": live._raw(live.plug),
            "legacy_controller_state": live._raw("input_boolean.ev_controller_enabled"),
            "legacy_automation_state": live._raw("binary_sensor.ev_legacy_charging_controllers_active"),
            "public_charging_mode": live.public_mode(),
            "public_mode_source": (
                "integration switch" if self.entry.options.get("public_charging_mode") is True
                else "legacy helper" if live._raw("input_boolean.ev_public_charging_mode") == "on"
                else "off"
            ),
            "preflight": live.preflight(),
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.entry.runtime_data.listen(self.async_write_ha_state))


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
            "linked_comfort_commands_enabled": False,
            "stop_attempts": auto.stop_attempts,
            "stop_confirmation_pending": auto.stop_requested_at is not None,
            "last_event": auto.last_event,
            "restarts_disarm_controller": True,
            "climate_commands_enabled": False,
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
        def refresh(_now):
            if auto.mode == "Monitor":
                self.hass.async_create_task(auto.async_tick())
            else:
                self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, refresh, timedelta(seconds=15))
        )
