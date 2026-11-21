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
from .dashboard_content import DAYS, dashboard_config, comfort_cards
from .comfort import PROFILES, FIELDS

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
    for profile in PROFILES:
        for field in FIELDS:
            unique_ids[f"{profile}_{field}"] = (
                "number", f"{entry.entry_id}_{profile}_{field}"
            )
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
    if DASHBOARD_PATH in data.dashboards:
        await _maybe_upgrade_existing_dashboard(hass, entry, data.dashboards[DASHBOARD_PATH])
        return
    if frontend.async_panel_exists(hass, DASHBOARD_PATH):
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
            "title": "Geely EV Control Centre (Test)",
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
        sidebar_title="Geely EV Control Centre (Test)",
        sidebar_icon="mdi:ev-station",
        config={"mode": "storage"},
    )
    await storage_dashboard.async_save(display)
    _LOGGER.info("Created native EV Control Centre dashboard at /%s", DASHBOARD_PATH)


async def _maybe_upgrade_existing_dashboard(hass, entry, stored_dashboard) -> None:
    """Upgrade only the untouched v0.1.4 placeholder; preserve user edits.

    Never replace other views, or change the Climate view if the user has
    edited it. The user's original EV dashboard is at a different path.
    """
    ids = _dashboard_entity_ids(hass, entry)
    if ids is None:
        return
    try:
        config = await stored_dashboard.async_load(False)
    except Exception:
        _LOGGER.exception("Could not read the existing EV test dashboard")
        return
    if not isinstance(config, dict):
        return
    views = config.get("views", [])
    climate = next((view for view in views if view.get("path") == "climate"), None)
    if not climate:
        return
    current_cards = climate.get("cards", [])
    if len(current_cards) != 1 or current_cards[0].get("type") != "markdown":
        return
    old_text = current_cards[0].get("content", "")
    if (
        "Climate controls and heated-seat profiles will be" not in old_text
        or "This development release cannot command" not in old_text
    ):
        # Not the untouched generated placeholder: leave the dashboard alone.
        return
    from copy import deepcopy

    updated = deepcopy(config)
    view = next(view for view in updated["views"] if view.get("path") == "climate")
    view["cards"] = comfort_cards(ids)
    updated["title"] = "Geely EV Control Centre (Test)"
    await stored_dashboard.async_save(updated)

    # Rename only this known, generated test dashboard, not the user's original.
    collection = DashboardsCollection(hass)
    await collection.async_load()
    existing = next(
        (item for item in collection.async_items()
         if item.get("url_path") == DASHBOARD_PATH),
        None,
    )
    if existing and existing.get("title") == "EV Control Centre":
        await collection.async_update_item(
            existing["id"], {"title": "Geely EV Control Centre (Test)"}
        )
        if frontend.async_panel_exists(hass, DASHBOARD_PATH):
            frontend.async_register_built_in_panel(
                hass, "lovelace",
                frontend_url_path=DASHBOARD_PATH,
                require_admin=False,
                show_in_sidebar=True,
                sidebar_title="Geely EV Control Centre (Test)",
                sidebar_icon="mdi:ev-station",
                config={"mode": "storage"},
                update=True,
            )
    _LOGGER.info("Updated untouched test Climate tab with editable comfort profiles")
