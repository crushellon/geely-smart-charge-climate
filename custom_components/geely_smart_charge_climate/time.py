"""Dashboard daily ready-by time controls; no vehicle actions."""
from datetime import time

from homeassistant.components.time import TimeEntity

from .schedule_entities import ScheduleEntity
from .weekly_schedule import DAY_NAMES
from .climate_schedule import SLOTS
from .climate_schedule_entities import ClimateScheduleSetting


async def async_setup_entry(hass, entry, async_add_entities):
    """Create editable ready-by times for each day."""
    async_add_entities(
        [DayReadyTime(hass, entry, day, "ready_time") for day in DAY_NAMES]
        + [ClimateSlotTime(hass, entry, slot, 'ready_time') for slot in SLOTS]
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


class ClimateSlotTime(ClimateScheduleSetting, TimeEntity):
    """Ready-by clock time for one independent climate slot."""

    _attr_icon = "mdi:clock-check-outline"

    @property
    def native_value(self):
        hh, mm = map(int, self.current.split(":"))
        return time(hour=hh, minute=mm)

    async def async_set_value(self, value: time):
        await self.save(value.strftime("%H:%M"))
