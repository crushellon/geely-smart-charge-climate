"""Read-only Geely Smart Charge & Climate integration.

No vehicle charging or climate commands are issued by this milestone.
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .dashboard_setup import async_ensure_dashboard

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TIME
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load diagnostic sensors and schedule controls, then add a dashboard."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    try:
        await async_ensure_dashboard(hass, entry)
    except Exception:
        _LOGGER.exception("Could not provision optional EV Control Centre dashboard")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the read-only integration entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
