"""Dashboard daily ready-by time controls; no vehicle actions."""
from datetime import time

from homeassistant.components.time import TimeEntity

from .schedule_entities import ScheduleEntity
from .weekly_schedule import DAY_NAMES


async def async_setup_entry(hass, entry, async_add_entities):
    """Create editable ready-by times for each day."""
    async_add_entities(
        [DayReadyTime(hass, entry, day, "ready_time") for day in DAY_NAMES]
    )


class DayReadyTime(ScheduleEntity, TimeEntity):
    """Expose a local wall-clock ready-by time."""

    _attr_icon = "mdi:clock-outline"

    @property
    def native_value(self):
        hours, minutes = (int(x) for x in self.current.split(":"))
        return time(hour=hours, minute=minutes)

    async def async_set_value(self, value: time):
        await self.save(value.strftime("%H:%M"))
