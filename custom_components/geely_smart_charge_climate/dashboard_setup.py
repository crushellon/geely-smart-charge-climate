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
from .comfort import PROFILES, FIELDS
from .climate_schedule import SLOTS

_LOGGER = logging.getLogger(__name__)
DASHBOARD_PATH = "geely-ev-control-centre"


def _dashboard_entity_ids(hass, entry) -> dict[str, str] | None:
    """Resolve registry-assigned IDs, supporting user-renamed entities."""
    registry = er.async_get(hass)
    unique_ids = {
        "observer_status": ("sensor", f"{entry.entry_id}_observer_status"),
        "simulation_decision": ("sensor", f"{entry.entry_id}_simulation_decision"),
        "climate_next": ("sensor", f"{entry.entry_id}_climate_next"),
    }
    for day in DAYS:
        unique_ids.update({
            f"{day}_enabled": ("switch", f"{entry.entry_id}_{day}_enabled"),
            f"{day}_target": ("number", f"{entry.entry_id}_{day}_target"),
            f"{day}_ready_time": ("time", f"{entry.entry_id}_{day}_ready_time"),
        })
    for day in DAYS:
        unique_ids[f"{day}_linked_comfort_enabled"] = (
            "switch", f"{entry.entry_id}_{day}_linked_comfort_enabled"
        )
        unique_ids[f"{day}_linked_comfort_profile"] = (
            "select", f"{entry.entry_id}_{day}_linked_comfort_profile"
        )
    for field in ("lead_minutes", "hold_minutes"):
        unique_ids[f"linked_comfort_{field}"] = (
            "number", f"{entry.entry_id}_linked_comfort_{field}"
        )
    for profile in PROFILES:
        for field in FIELDS:
            unique_ids[f"{profile}_{field}"] = (
                "number", f"{entry.entry_id}_{profile}_{field}"
            )
    for profile in PROFILES:
        for occupant in ("driver", "passenger"):
            unique_ids[f"{profile}_{occupant}_seat_mode"] = (
                "select", f"{entry.entry_id}_{profile}_{occupant}_seat_mode"
            )
        unique_ids[f"{profile}_steering_toggle"] = (
            "switch", f"{entry.entry_id}_{profile}_steering_toggle"
        )
        unique_ids[f"show_{profile}_settings"] = (
            "switch", f"{entry.entry_id}_show_{profile}_settings"
        )
    for slot in SLOTS:
        for field, platform in (
            ("enabled", "switch"), ("day", "select"),
            ("ready_time", "time"), ("temperature", "number"),
            ("driver_seat", "select"), ("passenger_seat", "select"),
            ("steering_heat", "switch"), ("lead_minutes", "number"),
            ("hold_minutes", "number"),
        ):
            unique_ids[f"climate_slot_{slot}_{field}"] = (
                platform, f"{entry.entry_id}_climate_slot_{slot}_{field}"
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
    """Migrate only the integration-generated four-tab test layout.

    Protect other dashboards, including the user's original EV Control Centre,
    and leave manually modified test dashboards untouched.
    """
    try:
        current = await stored_dashboard.async_load(False)
    except Exception:
        _LOGGER.exception("Could not inspect test dashboard for safe migration")
        return
    if not isinstance(current, dict):
        return
    views = current.get("views", [])
    if not isinstance(views, list):
        return
    paths = [v.get("path") for v in views]
    if paths == ["charging", "comfort", "climate-scheduler", "data"]:
        return
    if paths != ["charging", "climate", "schedule", "statistics"]:
        _LOGGER.info("Test dashboard was customized; preserving current layout")
        return
    charging = views[0].get("cards", [])
    climate = views[1].get("cards", [])
    schedule = views[2].get("cards", [])
    if (
        not charging or charging[0].get("type") != "markdown"
        or "Geely Smart Charge & Climate" not in charging[0].get("content", "")
        or not schedule or schedule[0].get("type") != "markdown"
        or "Weekly charging schedule" not in schedule[0].get("content", "")
    ):
        _LOGGER.info("Test dashboard appears customized; migration skipped")
        return
    # Recognize only the known v0.1.7 generated Climate tab layout.
    if (
        len(climate) != 14
        or climate[0].get("type") != "markdown"
        or "Cabin comfort settings" not in climate[0].get("content", "")
        or climate[7].get("title") != "Climate schedule 1"
        or climate[13].get("title") != "Climate schedule 7"
    ):
        _LOGGER.info("Climate layout customized; preserving it")
        return

    ids = _dashboard_entity_ids(hass, entry)
    if ids is None:
        return
    new_config = dashboard_config(
        ids,
        battery=entry.data[CONF_BATTERY_ENTITY],
        plug=discover_plug_entity(hass, entry.data[CONF_BATTERY_ENTITY]),
        charging_power=entry.data.get(CONF_CHARGING_POWER),
    )
    await stored_dashboard.async_save(new_config)

    collection = DashboardsCollection(hass)
    await collection.async_load()
    stored = next(
        (item for item in collection.async_items()
         if item.get("url_path") == DASHBOARD_PATH), None
    )
    if stored and stored.get("title") in ("EV Control Centre", "Geely EV Control Centre (Test)"):
        await collection.async_update_item(
            stored["id"], {"title": "Geely EV Control Centre (Test)"}
        )
        if frontend.async_panel_exists(hass, DASHBOARD_PATH):
            frontend.async_register_built_in_panel(
                hass, "lovelace",
                frontend_url_path=DASHBOARD_PATH,
                require_admin=False, show_in_sidebar=True,
                sidebar_title="Geely EV Control Centre (Test)",
                sidebar_icon="mdi:ev-station",
                config={"mode": "storage"}, update=True,
            )
    _LOGGER.info("Migrated generated test dashboard to four focused pages")
