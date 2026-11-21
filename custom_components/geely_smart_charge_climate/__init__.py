"""Read-only Geely Smart Charge & Climate integration.

This first milestone MUST NOT control vehicle charging or climate.
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .dashboard import async_ensure_dashboard
import logging

from .dashboard_setup import async_ensure_dashboard

_LOGGER = logging.getLogger(__name__)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TIME]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one observation-only configuration entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    try:
        await async_ensure_dashboard(hass, entry)
    except Exception:
        # Never prevent the Geely observers from loading due to a Lovelace
        # dashboard issue. Dashboard provision is deliberately nonessential.
        _LOGGER.exception("Could not provision EV Control Centre dashboard")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload observation-only entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
