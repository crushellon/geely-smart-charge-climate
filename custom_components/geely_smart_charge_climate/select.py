"""Comfort seat modes exposed as native Home Assistant dropdowns.

Only changes the integration's stored preferences; no car service calls.
"""
from homeassistant.components.select import SelectEntity

from .comfort import PROFILES
from .weekly_schedule import DAY_NAMES as DAYS_OF_WEEK
from .comfort_display import SEAT_OPTIONS, get_seat_mode, set_seat_mode
from .climate_schedule import SLOTS, DAYS
from .climate_schedule_entities import ClimateScheduleSetting
from .charge_climate import PROFILES as LINKED_PROFILES, get_value as get_linked, set_value as set_linked


async def async_setup_entry(hass, entry, async_add_entities):
    """Expose driver and passenger seat selectors for both comfort profiles."""
    async_add_entities([
        ComfortSeatSelect(hass, entry, profile, occupant)
        for profile in PROFILES for occupant in ("driver", "passenger")
    ] + [ClimateSlotSelect(hass, entry, slot, field)
         for slot in SLOTS for field in ('day', 'driver_seat', 'passenger_seat')]
        + [ChargingLinkedComfortSelect(hass, entry, day) for day in DAYS_OF_WEEK]
        )


class ComfortSeatSelect(SelectEntity):
    """One dropdown for heating or ventilation levels."""

    _attr_has_entity_name = True
    _attr_options = list(SEAT_OPTIONS)
    _attr_icon = "mdi:car-seat"

    def __init__(self, hass, entry, profile, occupant):
        self.hass = hass
        self.entry = entry
        self.profile = profile
        self.occupant = occupant
        self._attr_unique_id = f"{entry.entry_id}_{profile}_{occupant}_seat_mode"
        self._attr_name = f"{profile.title()} {occupant} seat"

    @property
    def current_option(self):
        return get_seat_mode(self.entry.options, self.profile, self.occupant)

    async def async_select_option(self, option):
        updated = set_seat_mode(
            self.entry.options, self.profile, self.occupant, option
        )
        self.hass.config_entries.async_update_entry(self.entry, options=updated)
        self.async_write_ha_state()


class ClimateSlotSelect(ClimateScheduleSetting, SelectEntity):
    """Per-slot weekday and seat comfort dropdowns."""

    _attr_icon = "mdi:calendar"

    def __init__(self, hass, entry, slot, field):
        super().__init__(hass, entry, slot, field)
        self._attr_options = list(DAYS if field == "day" else SEAT_OPTIONS)

    @property
    def current_option(self):
        return self.current

    async def async_select_option(self, option):
        await self.save(option)


class ChargingLinkedComfortSelect(SelectEntity):
    """Choose Warm/Cool profile using the existing charge ready-by time."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:car-seat"
    _attr_options = list(LINKED_PROFILES)

    def __init__(self, hass, entry, day):
        self.hass = hass
        self.entry = entry
        self.day = day
        self._attr_unique_id = f"{entry.entry_id}_{day}_linked_comfort_profile"
        self._attr_name = f"{day.title()} charging comfort profile"

    @property
    def current_option(self):
        return get_linked(self.entry.options, self.day, "profile")

    async def async_select_option(self, option):
        self.hass.config_entries.async_update_entry(
            self.entry, options=set_linked(self.entry.options, self.day, "profile", option)
        )
        self.async_write_ha_state()


