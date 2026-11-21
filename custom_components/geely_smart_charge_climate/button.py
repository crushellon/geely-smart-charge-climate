"""Explicit normal user charge, emergency and manual cabin buttons.

No exposed arm-test button is required; native controls call Geely services.
"""
from homeassistant.components.button import ButtonEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
         *[ManualChargeButton(entry, action) for action in
          ("start", "stop", "quick80", "quick100", "resume")],
        EmergencyActionButton(entry, "stop"),
        EmergencyActionButton(entry, "release"),
        *[ManualClimateButton(entry, action) for action in
          ("Cool", "Warm", "custom", "off")],
    ])


class ManualChargeButton(ButtonEntity):
    """The production manual charging actions, without staged arming."""

    _attr_has_entity_name = True

    def __init__(self, entry, action):
        self.entry = entry
        self.action = action
        names = {
            "start": ("Start chosen target", "mdi:play"),
            "stop": ("Stop manual", "mdi:stop"),
            "quick80": ("Quick 80%", "mdi:battery-80"),
            "quick100": ("Quick 100%", "mdi:battery-charging-100"),
            "resume": ("Resume schedule", "mdi:calendar-check"),
        }
        self._attr_unique_id = f"{entry.entry_id}_manual_charge_{action}"
        self._attr_name, self._attr_icon = names[action]

    async def async_press(self):
        controller = self.entry.runtime_data
        if self.action == "start":
            await controller.async_start_manual()
        elif self.action == "quick80":
            await controller.async_start_manual(80)
        elif self.action == "quick100":
            await controller.async_start_manual(100)
        elif self.action == "stop":
            await controller.async_stop()
        else:
            await controller.async_resume_schedule()


class EmergencyActionButton(ButtonEntity):
    """Explicit emergency latch and separate release; never auto-resume."""

    _attr_has_entity_name = True

    def __init__(self, entry, action):
        self.entry = entry
        self.action = action
        self._attr_unique_id = f"{entry.entry_id}_emergency_{action}"
        self._attr_name = (
            "Emergency STOP" if action == "stop" else "Release emergency stop"
        )
        self._attr_icon = (
            "mdi:alert-octagon" if action == "stop" else "mdi:lock-open"
        )

    async def async_press(self):
        runtime = self.entry.runtime_data
        if self.action == "stop":
            await runtime.async_emergency_stop()
        else:
            await runtime.async_release_emergency_stop()


class ManualClimateButton(ButtonEntity):
    """User-operated Geely climate preset; not a scheduled climate command."""

    _attr_has_entity_name = True

    def __init__(self, entry, action):
        self.entry = entry
        self.action = action
        names = {
            "Cool": ("Comfort Cool", "mdi:snowflake"),
            "Warm": ("Comfort Warm", "mdi:weather-sunny"),
            "custom": ("Custom temperature ON", "mdi:thermometer"),
            "off": ("Climate + seats OFF", "mdi:power"),
        }
        self._attr_unique_id = f"{entry.entry_id}_manual_climate_{action.lower()}"
        self._attr_name, self._attr_icon = names[action]

    async def async_press(self):
        await self.entry.runtime_data.async_manual_climate(self.action)
