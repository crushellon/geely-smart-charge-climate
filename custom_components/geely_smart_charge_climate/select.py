"""Comfort seat modes exposed as native Home Assistant dropdowns.

Only changes the integration's stored preferences; no car service calls.
"""
from homeassistant.components.select import SelectEntity

from .comfort import PROFILES
from .comfort_display import SEAT_OPTIONS, get_seat_mode, set_seat_mode


async def async_setup_entry(hass, entry, async_add_entities):
    """Expose driver and passenger seat selectors for both comfort profiles."""
    async_add_entities([
        ComfortSeatSelect(hass, entry, profile, occupant)
        for profile in PROFILES for occupant in ("driver", "passenger")
    ])


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
