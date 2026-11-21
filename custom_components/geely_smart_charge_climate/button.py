"""Explicit user-pressed manual charging test commands.

Buttons are inert unless a live test is armed. They do not activate a weekly
schedule or any climate preset.
"""
from homeassistant.components.button import ButtonEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([
        LiveTestButton(entry, "start"),
        LiveTestButton(entry, "stop"),
    ])


class LiveTestButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, action):
        self.entry = entry
        self.action = action
        self._attr_unique_id = f"{entry.entry_id}_live_test_{action}"
        self._attr_name = f"Live test {action}"
        self._attr_icon = "mdi:play-circle-outline" if action == "start" else "mdi:stop-circle-outline"

    async def async_press(self):
        controller = self.entry.runtime_data
        if self.action == "start":
            await controller.async_start()
        else:
            await controller.async_stop()
