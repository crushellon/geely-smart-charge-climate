"""Provision the first native Lovelace EV Control Centre dashboard.

Creates a dashboard once, preserving existing dashboards and user edits.
Uses Home Assistant's built-in cards and storage; never issues vehicle commands.
"""
import logging

from homeassistant.components import frontend
from homeassistant.components.lovelace import LOVELACE_DATA
from homeassistant.components.lovelace.dashboard import (
    DashboardsCollection,
    LovelaceStorage,
)
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CHARGING_POWER,
    DOMAIN,
)
from .discovery import discover_plug_entity
from .dashboard_content import DAYS, dashboard_config

_LOGGER = logging.getLogger(__name__)
DASHBOARD_PATH = "geely-ev-control-centre"


def _dashboard_entity_ids(hass, entry) -> dict[str, str] | None:
    """Resolve registry-assigned IDs, supporting user-renamed entities."""
    registry = er.async_get(hass)
    unique_ids = {
        "observer_status": ("sensor", f"{entry.entry_id}_observer_status"),
        "simulation_decision": ("sensor", f"{entry.entry_id}_simulation_decision"),
    }
    for day in DAYS:
        unique_ids.update({
            f"{day}_enabled": ("switch", f"{entry.entry_id}_{day}_enabled"),
            f"{day}_target": ("number", f"{entry.entry_id}_{day}_target"),
            f"{day}_ready_time": ("time", f"{entry.entry_id}_{day}_ready_time"),
        })
    result = {}
    for key, (platform, unique_id) in unique_ids.items():
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id is None:
            _LOGGER.warning("Dashboard creation deferred: missing %s entity", key)
            return None
        result[key] = entity_id
    return result


async def async_ensure_dashboard(hass, entry) -> None:
    """Create one non-destructive dashboard in the sidebar.

    If a user already has a dashboard at this path, it is NEVER overwritten.
    Existing installations keep their configuration entries and entity IDs.
    """
    if LOVELACE_DATA not in hass.data:
        _LOGGER.warning("Lovelace is unavailable; EV dashboard not created")
        return
    data = hass.data[LOVELACE_DATA]
    if DASHBOARD_PATH in data.dashboards or frontend.async_panel_exists(
        hass, DASHBOARD_PATH
    ):
        return

    # Avoid collisions with any dashboard already stored under this path.
    collection = DashboardsCollection(hass)
    await collection.async_load()
    if any(
        item.get("url_path") == DASHBOARD_PATH
        for item in collection.async_items()
    ):
        _LOGGER.info("EV dashboard already exists; not overwriting it")
        return

    entity_ids = _dashboard_entity_ids(hass, entry)
    if entity_ids is None:
        return

    display = dashboard_config(
        entity_ids,
        battery=entry.data[CONF_BATTERY_ENTITY],
        plug=discover_plug_entity(hass, entry.data[CONF_BATTERY_ENTITY]),
        charging_power=entry.data.get(CONF_CHARGING_POWER),
    )
    # Dashboard metadata registration persists across Home Assistant restarts.
    item = await collection.async_create_item(
        {
            "url_path": DASHBOARD_PATH,
            "title": "EV Control Centre",
            "icon": "mdi:ev-station",
            "show_in_sidebar": True,
            "require_admin": False,
        }
    )
    storage_dashboard = LovelaceStorage(hass, item)
    data.dashboards[DASHBOARD_PATH] = storage_dashboard
    frontend.async_register_built_in_panel(
        hass,
        "lovelace",
        frontend_url_path=DASHBOARD_PATH,
        require_admin=False,
        show_in_sidebar=True,
        sidebar_title="EV Control Centre",
        sidebar_icon="mdi:ev-station",
        config={"mode": "storage"},
    )
    await storage_dashboard.async_save(display)
    _LOGGER.info("Created native EV Control Centre dashboard at /%s", DASHBOARD_PATH)
