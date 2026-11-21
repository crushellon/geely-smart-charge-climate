"""Reusable persistence for climate schedule dashboard entities only."""
from .climate_schedule import get_slot, update_slot


class ClimateScheduleSetting:
    """Shared config-entry options storage for independent one-week slots."""

    _attr_has_entity_name = True

    def __init__(self, hass, entry, slot, field):
        self.hass = hass
        self.entry = entry
        self.slot = slot
        self.field = field
        self._attr_unique_id = f"{entry.entry_id}_climate_slot_{slot}_{field}"
        self._attr_name = f"Climate {slot} {field.replace('_', ' ')}"

    @property
    def current(self):
        return get_slot(self.entry.options, self.slot)[self.field]

    async def save(self, value):
        self.hass.config_entries.async_update_entry(
            self.entry,
            options=update_slot(self.entry.options, self.slot, self.field, value),
        )
        self.async_write_ha_state()
