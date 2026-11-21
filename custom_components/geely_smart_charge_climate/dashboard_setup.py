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
    CONF_CHARGING_SWITCH,
    DOMAIN,
)
from .discovery import discover_plug_entity, discover_charging_power_entity
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
        "live_test_status": ("sensor", f"{entry.entry_id}_live_test_status"),
        "automatic_charge_decision": ("sensor", f"{entry.entry_id}_automatic_charge_decision"),
        "automatic_charge_mode": ("select", f"{entry.entry_id}_automatic_charge_mode"),
        "live_test_armed": ("switch", f"{entry.entry_id}_live_test_armed"),
        "live_test_target": ("number", f"{entry.entry_id}_live_test_target"),
        "live_test_start": ("button", f"{entry.entry_id}_live_test_start"),
        "live_test_stop": ("button", f"{entry.entry_id}_live_test_stop"),
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


def _optional_vehicle_sensors(hass, entry) -> dict[str, str]:
    """Discover available EX5 telemetry owned by the selected Geely entry.

    Only exact vehicle-matching registry entities are shown. Speed is excluded.
    """
    registry = er.async_get(hass)
    battery_id = entry.data[CONF_BATTERY_ENTITY]
    battery = registry.async_get(battery_id)
    if battery is None or not battery_id.endswith("_battery"):
        return {}
    stem = battery_id[len("sensor."):-len("_battery")]
    keys = (
        "electric_range", "range_at_full_charge", "total_mileage",
        "trip_meter", "trip_consumption", "average_consumption", "efficiency",
        "interior_temperature", "exterior_temperature", "cabin_humidity",
        "tire_front_left", "tire_front_right", "tire_rear_left",
        "tire_rear_right", "tire_temperature_fl", "tire_temperature_fr",
        "tire_temperature_rl", "tire_temperature_rr",
        "12v_battery", "12v_voltage", "days_to_service",
        "distance_to_service", "last_updated", "car_reported_at",
        "charge_current", "charge_voltage", "time_to_full_charge",
    )
    result = {}
    for key in keys:
        entity_id = f"sensor.{stem}_{key}"
        entity = registry.async_get(entity_id)
        if (
            entity is not None
            and entity.disabled_by is None
            and (
                (battery.device_id and entity.device_id == battery.device_id)
                or (
                    battery.config_entry_id
                    and entity.config_entry_id == battery.config_entry_id
                )
            )
        ):
            result[key] = entity_id
    return result


def _optional_wall_connector_sensors(hass) -> dict[str, str]:
    """Show connected Tesla wall connector measurements only if present.

    Optional: this integration does not require any smart wallbox.
    """
    registry = er.async_get(hass)
    candidates = {
        "power": "sensor.tesla_wall_connector_total_power",
        "connected": "binary_sensor.tesla_wall_connector_vehicle_connected",
        "session_energy": "sensor.tesla_wall_connector_session_energy",
        "energy": "sensor.tesla_wall_connector_energy",
        "status": "sensor.tesla_wall_connector_status",
    }
    out = {}
    for field, entity_id in candidates.items():
        ent = registry.async_get(entity_id)
        if ent is not None and ent.disabled_by is None:
            out[field] = entity_id
    return out


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
        charging_power=(entry.data.get(CONF_CHARGING_POWER)
                        or discover_charging_power_entity(hass, entry.data[CONF_BATTERY_ENTITY])),
        charging_switch=entry.data.get(CONF_CHARGING_SWITCH),
        extra_sensors=_optional_vehicle_sensors(hass, entry),
        charger_sensors=_optional_wall_connector_sensors(hass),
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
        # Refresh generated layouts in place for updated styling and telemetry.
        if not _is_generated_four_page_dashboard(views):
            _LOGGER.info("Four-page dashboard was customized; preserving layout")
            return
        await _refresh_generated_dashboard(hass, entry, stored_dashboard)
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
    # Recognize v0.1.4–0.1.7 generated layouts; never overwrite edits.
    old_placeholder = (
        len(climate) == 1
        and climate[0].get("type") == "markdown"
        and "Climate controls and heated-seat profiles" in climate[0].get("content", "")
    )
    old_sliders = (
        len(climate) == 3
        and climate[0].get("type") == "markdown"
        and "Cabin comfort profiles" in climate[0].get("content", "")
        and [c.get("title") for c in climate[1:]] == ["Warm profile", "Cool profile"]
    )
    old_comfort = (
        len(climate) == 5
        and climate[0].get("type") == "markdown"
        and "Cabin comfort settings" in climate[0].get("content", "")
        and [c.get("type") for c in climate[1:]]
        == ["entities", "conditional", "entities", "conditional"]
    )
    old_with_slots = (
        len(climate) == 14
        and climate[0].get("type") == "markdown"
        and "Cabin comfort settings" in climate[0].get("content", "")
        and climate[7].get("title") == "Climate schedule 1"
        and climate[13].get("title") == "Climate schedule 7"
    )
    if not (old_placeholder or old_sliders or old_comfort or old_with_slots):
        _LOGGER.info("Climate layout customized; preserving it")
        return

    ids = _dashboard_entity_ids(hass, entry)
    if ids is None:
        return
    new_config = dashboard_config(
        ids,
        battery=entry.data[CONF_BATTERY_ENTITY],
        plug=discover_plug_entity(hass, entry.data[CONF_BATTERY_ENTITY]),
        charging_power=(entry.data.get(CONF_CHARGING_POWER)
                        or discover_charging_power_entity(hass, entry.data[CONF_BATTERY_ENTITY])),
        charging_switch=entry.data.get(CONF_CHARGING_SWITCH),
        extra_sensors=_optional_vehicle_sensors(hass, entry),
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


def _is_generated_four_page_dashboard(views) -> bool:
    """Only allow auto-refresh of layouts produced by this integration."""
    try:
        left = views[0]["sections"][0]["cards"]
        right = views[0]["sections"][1]["cards"]
        comfort = views[1]["sections"][1]["cards"]
        slots = [
            card for section in views[2]["sections"]
            for card in section["cards"]
            if card.get("title", "").startswith("Climate schedule ")
        ]
    except (KeyError, IndexError, TypeError):
        return False
    return (
        len(views) == 4
        and len(left) >= 4
        and left[0].get("type") == "markdown"
        and "Geely Smart Charge & Climate" in left[0].get("content", "")
        and bool(right)
        and right[0].get("title") == "Seven-day charging schedule"
        and len(slots) == 7
        and len(comfort) >= 3
        and [card.get("title") for card in comfort[-2:]]
        == ["Cool profile", "Warm profile"]
    )


async def _refresh_generated_dashboard(hass, entry, stored_dashboard) -> None:
    """Update our known generated layout; never rewrite other dashboards."""
    ids = _dashboard_entity_ids(hass, entry)
    if ids is None:
        return
    new_config = dashboard_config(
        ids,
        battery=entry.data[CONF_BATTERY_ENTITY],
        plug=discover_plug_entity(hass, entry.data[CONF_BATTERY_ENTITY]),
        charging_power=(entry.data.get(CONF_CHARGING_POWER)
                        or discover_charging_power_entity(hass, entry.data[CONF_BATTERY_ENTITY])),
        charging_switch=entry.data.get(CONF_CHARGING_SWITCH),
        extra_sensors=_optional_vehicle_sensors(hass, entry),
    )
    try:
        old = await stored_dashboard.async_load(False)
        # Avoid redundant disk writes on ordinary integration reloads.
        if old != new_config:
            await stored_dashboard.async_save(new_config)
            _LOGGER.info("Refreshed generated Geely dashboard and Vehicle Data")
    except Exception:
        _LOGGER.exception("Could not refresh the generated dashboard")
