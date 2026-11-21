"""Dashboard target-percentage controls; never command charging."""
from homeassistant.components.number import NumberEntity, NumberMode

from .schedule_entities import ScheduleEntity
from .weekly_schedule import DAY_NAMES


async def async_setup_entry(hass, entry, async_add_entities):
    """Create per-day battery targets."""
    async_add_entities(
        [DayTargetNumber(hass, entry, day, "target") for day in DAY_NAMES]
    )


class DayTargetNumber(ScheduleEntity, NumberEntity):
    """Set a simulated schedule target."""

    _attr_native_min_value = 50
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:battery-charging"

    @property
    def native_value(self):
        return self.current

    async def async_set_native_value(self, value):
        await self.save(int(value))
