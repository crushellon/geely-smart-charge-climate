"""Editable schedule settings for dashboard entities; never operate vehicle.

Writes only to this integration's config-entry options. No Geely service calls.
"""
from datetime import time

from homeassistant.helpers.entity import Entity

from .weekly_schedule import default_schedule, validate_day

SCHEDULE_KEY = "weekly_schedule"


class ScheduleEntity(Entity):
    """Shared persisted options implementation."""

    _attr_has_entity_name = True

    def __init__(self, hass, entry, day, field):
        self.hass = hass
        self.entry = entry
        self.day = day
        self.field = field
        self._attr_unique_id = f"{entry.entry_id}_{day}_{field}"
        self._attr_name = f"{day.title()} {field.replace('_', ' ')}"
        self._attr_entity_category = None

    @property
    def current(self):
        """Read live persisted configuration; legacy options still work."""
        return {
            **default_schedule()[self.day],
            **self.entry.options.get(SCHEDULE_KEY, {}).get(self.day, {}),
        }[self.field]

    async def save(self, value):
        """Persist one option without reloading entity platforms."""
        current = self.entry.options.get(SCHEDULE_KEY, {})
        day = {
            **default_schedule()[self.day],
            **current.get(self.day, {}),
            self.field: value,
        }
        validated = validate_day(day)
        updated = {**current, self.day: validated}
        self.hass.config_entries.async_update_entry(
            self.entry,
            options={**self.entry.options, SCHEDULE_KEY: updated},
        )
        self.async_write_ha_state()
        # Refresh the automatic authorisation decision immediately after
        # committing the same weekly schedule used by the simulator.
        controller = getattr(self.entry, "runtime_data", None)
        if controller is not None and hasattr(controller, "auto"):
            await controller.auto.async_tick()
