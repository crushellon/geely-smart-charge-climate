"""Dashboard day enable switches; not vehicle-charging switches."""
from homeassistant.components.switch import SwitchEntity

from .schedule_entities import ScheduleEntity
from .weekly_schedule import DAY_NAMES


async def async_setup_entry(hass, entry, async_add_entities):
    """Create the seven daily enable toggles."""
    async_add_entities(
        [DayEnabledSwitch(hass, entry, day, "enabled") for day in DAY_NAMES]
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
