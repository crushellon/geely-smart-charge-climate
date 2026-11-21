"""Dashboard day enable switches; not vehicle-charging switches."""
from homeassistant.components.switch import SwitchEntity

from .schedule_entities import ScheduleEntity
from .comfort import PROFILES, get_value, set_value
from .comfort_display import get_profile_visible, set_profile_visible
from .weekly_schedule import DAY_NAMES
from .climate_schedule import SLOTS
from .climate_schedule_entities import ClimateScheduleSetting


async def async_setup_entry(hass, entry, async_add_entities):
    """Create the seven daily enable toggles."""
    async_add_entities(
        [DayEnabledSwitch(hass, entry, day, "enabled") for day in DAY_NAMES]
        + [SteeringPreferenceSwitch(hass, entry, profile) for profile in PROFILES]
        + [ComfortExpandSwitch(hass, entry, profile) for profile in PROFILES]
        + [ClimateSlotEnabled(hass, entry, slot, 'enabled') for slot in SLOTS]
    )


class DayEnabledSwitch(ScheduleEntity, SwitchEntity):
    """Enable one day in the simulation schedule only."""

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
    """One independent weekly climate slot enable toggle (simulation-only)."""

    _attr_icon = "mdi:calendar-clock"

    @property
    def is_on(self):
        return self.current

    async def async_turn_on(self, **kwargs):
        await self.save(True)

    async def async_turn_off(self, **kwargs):
        await self.save(False)
