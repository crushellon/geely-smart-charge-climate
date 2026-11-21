"""Dashboard target-percentage controls; never command charging."""
from homeassistant.components.number import NumberEntity, NumberMode

from .schedule_entities import ScheduleEntity
from .comfort import PROFILES, FIELDS, get_value, set_value
from .weekly_schedule import DAY_NAMES


async def async_setup_entry(hass, entry, async_add_entities):
    """Create per-day battery targets."""
    async_add_entities(
        [DayTargetNumber(hass, entry, day, "target") for day in DAY_NAMES]
        + [ComfortPreferenceNumber(hass, entry, profile, field)
           for profile in PROFILES for field in FIELDS]
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


class ComfortPreferenceNumber(NumberEntity):
    """Edit one local climate/seat preference, never vehicle climate itself."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:car-seat"

    def __init__(self, hass, entry, profile: str, field: str):
        self.hass = hass
        self.entry = entry
        self.profile = profile
        self.field = field
        self._attr_unique_id = f"{entry.entry_id}_{profile}_{field}"
        self._attr_name = f"{profile.title()} {field.replace('_', ' ')}"
        self._attr_native_min_value = FIELDS[field]["min"]
        self._attr_native_max_value = FIELDS[field]["max"]
        self._attr_native_step = 0.5 if field == "temperature" else 1
        if "unit" in FIELDS[field]:
            self._attr_native_unit_of_measurement = FIELDS[field]["unit"]

    @property
    def native_value(self):
        return get_value(self.entry.options, self.profile, self.field)

    async def async_set_native_value(self, value):
        """Save preference only, without calling any external service."""
        self.hass.config_entries.async_update_entry(
            self.entry,
            options=set_value(self.entry.options, self.profile, self.field, value),
        )
        self.async_write_ha_state()
