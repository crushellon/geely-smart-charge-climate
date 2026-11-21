"""Create a dedicated Lovelace EV dashboard with only built-in cards.

The dashboard is created once, without touching other dashboards. Existing
dashboards (including a user's edited EV dashboard) are never overwritten.
No vehicle commands are issued by creation or by simulation views.
"""

import logging

from homeassistant.components import frontend, lovelace
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.const import CONF_ICON

from .weekly_schedule import DAY_NAMES

_LOGGER = logging.getLogger(__name__)
DASHBOARD_URL = "geely-ev-control"


def _entity_rows(entities: list[str]) -> dict:
    return {"type": "entities", "show_header_toggle": False, "entities": entities}


def build_dashboard(entry) -> dict:
    """Generate stable four-tab dashboard using configured Geely sources.

    Do not include vehicle speed; Geely Connect may mark it unavailable in park.
    """
    battery = entry.data["battery_entity"]
    charging = entry.data["charging_switch"]
    power = entry.data.get("charging_power")
    charge_entities = [battery, charging]
    if power:
        charge_entities.append(power)

    schedule_cards = [
        {"type": "entities", "title": day.title(),
         "show_header_toggle": False, "entities": [
             f"switch.{day}_enabled",
             f"number.{day}_target",
             f"time.{day}_ready_time",
         ]}
        for day in DAY_NAMES
    ]

    return {
        "title": "EV Control Centre",
        "views": [
            {
                "title": "Charging",
                "path": "charging",
                "icon": "mdi:ev-station",
                "cards": [
                    {"type": "markdown", "content":
                     "## Geely Smart Charge & Climate\n"
                     "**Read-only preview:** vehicle charging remains controlled by your existing automations."},
                    {"type": "gauge", "entity": battery,
                     "name": "Battery", "min": 0, "max": 100,
                     "severity": {"green": 50, "yellow": 20, "red": 0}},
                    {"type": "entities", "title": "Live vehicle and charging",
                     "show_header_toggle": False,
                     "entities": charge_entities + [
                         "sensor.observer_status",
                         "sensor.simulation_decision",
                     ]},
                    {"type": "entities", "title": "Simulated charge plan",
                     "entities": [
                         {"entity": "sensor.simulation_decision",
                          "name": "Advisory decision"},
                     ]},
                ],
            },
            {
                "title": "Climate",
                "path": "climate",
                "icon": "mdi:air-conditioner",
                "cards": [
                    {"type": "markdown", "content":
                     "## Climate\n"
                     "Climate presets, seat comfort and departure scheduling "
                     "will be added after the vehicle integration safety checks. "
                     "This development version does not issue climate commands."},
                ],
            },
            {
                "title": "Schedule",
                "path": "schedule",
                "icon": "mdi:calendar-clock",
                "cards": [
                    {"type": "markdown", "content":
                     "## Weekly charging schedule\n"
                     "Enable a day, set a battery target, and choose when the car "
                     "must be ready. **Simulation only**: changing these controls "
                     "does not start or stop charging."},
                    *schedule_cards,
                ],
            },
            {
                "title": "Statistics",
                "path": "statistics",
                "icon": "mdi:chart-line",
                "cards": [
                    {"type": "markdown", "content":
                     "## Charging statistics\n"
                     "Charging-rate learning and simulation diagnostics. "
                     "No driving-speed telemetry is collected."},
                    {"type": "history-graph", "title": "Battery charge history",
                     "hours_to_show": 48, "entities": [battery]},
                    _entity_rows(["sensor.simulation_decision",
                                  "sensor.observer_status"]),
                ],
            },
        ],
    }


async def async_ensure_dashboard(hass, entry) -> None:
    """Register the sidebar dashboard without overwriting the user's UI.

    Home Assistant's Lovelace collection writes dashboard metadata, and its
    LovelaceStorage saves views. Existing path collisions are left untouched.
    """
    if LOVELACE_DATA not in hass.data:
        _LOGGER.warning("Lovelace not ready; dashboard can be added later")
        return

    data = hass.data[LOVELACE_DATA]
    if DASHBOARD_URL in data.dashboards:
        return

    collection = lovelace_dashboard.DashboardsCollection(hass)
    await collection.async_load()
    existing = next(
        (item for item in collection.async_items()
         if item.get("url_path") == DASHBOARD_URL), None
    )
    if existing is not None:
        # The Lovelace component owns this dashboard; don't overwrite it.
        return
    if frontend.async_panel_exists(hass, DASHBOARD_URL):
        _LOGGER.warning("Dashboard path %s already in use", DASHBOARD_URL)
        return

    item = await collection.async_create_item({
        "url_path": DASHBOARD_URL,
        "title": "EV Control Centre",
        CONF_ICON: "mdi:car-electric",
        "show_in_sidebar": True,
        "require_admin": False,
    })
    store = lovelace_dashboard.LovelaceStorage(hass, item)
    data.dashboards[DASHBOARD_URL] = store
    await store.async_save(build_dashboard(entry))
    frontend.async_register_built_in_panel(
        hass,
        lovelace.DOMAIN,
        frontend_url_path=DASHBOARD_URL,
        sidebar_title="EV Control Centre",
        sidebar_icon="mdi:car-electric",
        config={"mode": "storage"},
    )
