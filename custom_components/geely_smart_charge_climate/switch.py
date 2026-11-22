"""Dashboard day enable switches; not vehicle-charging switches."""
from homeassistant.components.switch import SwitchEntity

from .schedule_entities import ScheduleEntity
from .comfort import PROFILES, get_value, set_value
from .comfort_display import get_profile_visible, set_profile_visible
from .weekly_schedule import DAY_NAMES
from .charge_climate import get_value as get_linked, set_value as set_linked
from .climate_schedule import SLOTS
from .climate_schedule_entities import ClimateScheduleSetting


async def async_setup_entry(hass, entry, async_add_entities):
    """Create the seven daily enable toggles."""
    async_add_entities(
        [DayEnabledSwitch(hass, entry, day, "enabled") for day in DAY_NAMES]
        + [SteeringPreferenceSwitch(hass, entry, profile) for profile in PROFILES]
        + [ComfortExpandSwitch(hass, entry, profile) for profile in PROFILES]
        + [ClimateSlotEnabled(hass, entry, slot, 'enabled') for slot in SLOTS]
        + [ClimateSlotEnabled(hass, entry, slot, 'steering_heat') for slot in SLOTS]
        + [ChargingLinkedComfortSwitch(hass, entry, day) for day in DAY_NAMES]
        + [PublicChargingModeSwitch(hass, entry), AutomaticChargingEnabledSwitch(entry), ScheduledClimateEnabledSwitch(hass, entry), EmergencyStopSwitch(hass, entry)]
    )


class DayEnabledSwitch(ScheduleEntity, SwitchEntity):
    """Enable one vehicle-ready weekday in the charging schedule."""

    _attr_icon = "mdi:calendar-check"

    @property
    def is_on(self):
        return self.current

    async def async_turn_on(self, **kwargs):
        await self.save(True)

    async def async_turn_off(self, **kwargs):
        await self.save(False)


class SteeringPreferenceSwitch(SwitchEntity):
    """Persist steering heating preference, without controlling the vehicle."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:steering"

    def __init__(self, hass, entry, profile):
        self.hass = hass
        self.entry = entry
        self.profile = profile
        self._attr_name = f"{profile.title()} steering wheel heating"
        self._attr_unique_id = f"{entry.entry_id}_{profile}_steering_toggle"

    @property
    def is_on(self):
        return bool(get_value(self.entry.options, self.profile, "steering_heat"))

    async def _save(self, state):
        updated = set_value(
            self.entry.options, self.profile, "steering_heat", int(state)
        )
        self.hass.config_entries.async_update_entry(self.entry, options=updated)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._save(True)

    async def async_turn_off(self, **kwargs):
        await self._save(False)


class ComfortExpandSwitch(SwitchEntity):
    """Toggle dashboard profile visibility, not the vehicle's climate."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:unfold-more-horizontal"

    def __init__(self, hass, entry, profile):
        self.hass = hass
        self.entry = entry
        self.profile = profile
        self._attr_name = f"Show {profile.title()} settings"
        self._attr_unique_id = f"{entry.entry_id}_show_{profile}_settings"

    @property
    def is_on(self):
        return get_profile_visible(self.entry.options, self.profile)

    async def _save(self, state):
        updated = set_profile_visible(self.entry.options, self.profile, state)
        self.hass.config_entries.async_update_entry(self.entry, options=updated)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._save(True)

    async def async_turn_off(self, **kwargs):
        await self._save(False)


class ClimateSlotEnabled(ClimateScheduleSetting, SwitchEntity):
    """Enable a real independent weekly climate slot."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass, entry, slot, field):
        super().__init__(hass, entry, slot, field)
        if field == "steering_heat":
            self._attr_icon = "mdi:steering"

    @property
    def is_on(self):
        return self.current

    async def async_turn_on(self, **kwargs):
        await self.save(True)

    async def async_turn_off(self, **kwargs):
        await self.save(False)


class ChargingLinkedComfortSwitch(SwitchEntity):
    """Local per-day comfort association with the charging schedule."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:car-defrost-front"

    def __init__(self, hass, entry, day):
        self.hass = hass
        self.entry = entry
        self.day = day
        self._attr_unique_id = f"{entry.entry_id}_{day}_linked_comfort_enabled"
        self._attr_name = f"{day.title()} charging comfort enabled"

    @property
    def is_on(self):
        return get_linked(self.entry.options, self.day, "enabled")

    async def _save(self, enabled):
        self.hass.config_entries.async_update_entry(
            self.entry, options=set_linked(self.entry.options, self.day, "enabled", enabled)
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._save(True)

    async def async_turn_off(self, **kwargs):
        await self._save(False)


class PublicChargingModeSwitch(SwitchEntity):
    """User-declared public charging. Never infer vehicle location.

    Persists across restarts. The legacy public-mode helper, if installed,
    remains an additional interlock until users migrate it.
    """

    _attr_has_entity_name = True
    _attr_name = "Public charging mode"
    _attr_icon = "mdi:ev-station"

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_public_charging_mode"

    @property
    def is_on(self):
        return self.entry.options.get("public_charging_mode", False) is True

    async def _save(self, enabled):
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, "public_charging_mode": enabled},
        )
        self.async_write_ha_state()
        # Reconcile immediately, without waiting for the periodic tick.
        await self.entry.runtime_data.async_tick()
        await self.entry.runtime_data.auto.async_tick()

    async def async_turn_on(self, **kwargs):
        await self._save(True)

    async def async_turn_off(self, **kwargs):
        await self._save(False)


class AutomaticChargingEnabledSwitch(SwitchEntity):
    """Normal charging-schedule on/off control for the EV Control dashboard.

    Enabled preference is persisted. Vehicle ownership and command state
    recover by observation after a restart, subject to safety interlocks.
    """

    _attr_has_entity_name = True
    _attr_name = "Automatic charging enabled"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_automatic_charging_enabled"

    @property
    def is_on(self):
        return self.entry.options.get("automatic_charging_enabled", False) is True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            self.entry.runtime_data.listen(self.async_write_ha_state)
        )

    async def async_turn_on(self, **kwargs):
        await self.entry.runtime_data.async_set_automatic_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.entry.runtime_data.async_set_automatic_enabled(False)
        self.async_write_ha_state()


class EmergencyStopSwitch(SwitchEntity):
    """Persistent emergency interlock, with explicit release."""

    _attr_has_entity_name = True
    _attr_name = "Emergency stop"
    _attr_icon = "mdi:alert-octagon"

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_emergency_stop"

    @property
    def is_on(self):
        return self.entry.options.get("emergency_stop", False) is True

    async def async_turn_on(self, **kwargs):
        await self.entry.runtime_data.async_emergency_stop()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self.entry.runtime_data.async_release_emergency_stop()
        self.async_write_ha_state()


class ScheduledClimateEnabledSwitch(SwitchEntity):
    """Enable only seven independent cabin appointments, not linked comfort.

    Previously simulated independent slots remain inert on migration until
    the user enables them. Charging-linked Cool/Warm is controlled on its
    own ready-by weekday in EV Control.
    """

    _attr_has_entity_name = True
    _attr_name = "Independent climate schedules enabled"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_scheduled_climate_enabled"

    @property
    def is_on(self):
        return self.entry.options.get("scheduled_climate_enabled", False) is True

    async def _set(self, state):
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, "scheduled_climate_enabled": bool(state)},
        )
        self.async_write_ha_state()
        await self.entry.runtime_data.scheduled_climate.async_tick()

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
