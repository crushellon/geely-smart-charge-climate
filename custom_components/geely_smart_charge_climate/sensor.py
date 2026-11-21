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

from .const import CONF_BATTERY_ENTITY, CONF_CHARGING_POWER, CONF_CHARGING_SWITCH
from .simulator import next_deadline, simulate

# What-if demonstration inputs; NOT the user's active seven-day schedule.
DEMO_TARGET = 80.0
DEMO_RATE_KW = 6.5
DEMO_CAPACITY_KWH = 68.39
DEMO_READY_TIME = "06:30"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose read-only and hypothetical results; never command devices."""
    async_add_entities([
        GeelyObservationSensor(hass, entry),
        GeelySimulationSensor(hass, entry),
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

    async def async_added_to_hass(self) -> None:
        """Refresh when selected source entities update."""
        await super().async_added_to_hass()
        entities = [self._battery, self._switch]
        if self._power:
            entities.append(self._power)

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
            "control_mode": "read_only",
            "battery_source": self._battery,
            "charging_switch_source": self._switch,
        }
        for name, entity_id in (
            ("battery_state", self._battery),
            ("charging_switch_state", self._switch),
            ("charging_power_state", self._power),
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

    def _result(self):
        now = dt_util.now()
        ready = next_deadline(now, DEMO_READY_TIME)
        battery = self.hass.states.get(self._battery)
        charging = self.hass.states.get(self._switch)
        if battery is None or battery.state in ("unknown", "unavailable"):
            soc = None
        else:
            try:
                soc = float(battery.state)
            except (TypeError, ValueError):
                soc = None
        return simulate(
            now=now, ready_by=ready, soc=soc,
            target=DEMO_TARGET, effective_kw=DEMO_RATE_KW,
            usable_kwh=DEMO_CAPACITY_KWH,
            charging=bool(charging and charging.state == "on"),
            # Plug and session-state confirmation are intentionally absent.
            # No START can be authorised by this read-only preview.
            plugged=None,
        )

    @property
    def native_value(self) -> str:
        """Return the hypothetical outcome as an advisory state."""
        return self._result().action

    @property
    def extra_state_attributes(self) -> dict:
        """Describe assumptions rather than pretending to control a session."""
        result = self._result()
        return {
            "simulation_only": True,
            "vehicle_commands_sent": False,
            "schedule_source": "illustrative example, not active schedule",
            "example_target_percent": DEMO_TARGET,
            "example_ready_time": DEMO_READY_TIME,
            "assumed_effective_kw": DEMO_RATE_KW,
            "assumed_usable_capacity_kwh": DEMO_CAPACITY_KWH,
            "estimated_minutes": result.remaining_minutes,
            "estimated_start": result.start_at.isoformat() if result.start_at else None,
            "ready_by": result.ready_by.isoformat(),
            "termination_policy": result.termination,
            "reason": result.reason,
            "plug_status_configured": False,
        }

    async def async_added_to_hass(self) -> None:
        """Recompute at least once each minute as the deadline approaches."""
        await super().async_added_to_hass()

        def minute_tick(now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, minute_tick, timedelta(minutes=1))
        )
