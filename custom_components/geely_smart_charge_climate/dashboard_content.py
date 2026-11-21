"""Built-in Lovelace dashboard layout for the read-only EX5 preview.

Only native Home Assistant cards are used. No custom frontend resources, YAML
file edits, or vehicle commands are required. Personal schedules are never
hard-coded into the dashboard.
"""
from __future__ import annotations

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def schedule_card(day: str, entity_ids: dict[str, str]) -> dict:
    """One editable day, using integration-owned switch/number/time entities."""
    title = day.title()
    return {
        "type": "entities",
        "title": title,
        "show_header_toggle": False,
        "entities": [
            {"entity": entity_ids[f"{day}_enabled"], "name": "Schedule enabled"},
            {"entity": entity_ids[f"{day}_target"], "name": "Battery target"},
            {"entity": entity_ids[f"{day}_ready_time"], "name": "Ready by"},
        ],
    }


def comfort_cards(entity_ids: dict[str, str]) -> list[dict]:
    """Comfort controls resembling the original EV Control Centre.

    Temperature uses a slider, seats use named dropdowns, steering heat and
    visibility use switches. Everything here edits preferences only.
    """
    result = [
        {
            "type": "markdown",
            "content": "## Cabin comfort settings\\n"
            "**Simulation-only preferences.** Nothing here starts the climate "
            "system or changes your existing EV automations.",
        },
    ]
    for profile in ("cool", "warm"):
        show = entity_ids[f"show_{profile}_settings"]
        result.append({
            "type": "entities",
            "title": f"Comfort {profile.title()} — expand settings",
            "show_header_toggle": False,
            "entities": [
                {"entity": show, "name": f"Show {profile.title()} settings"},
            ],
        })
        result.append({
            "type": "conditional",
            "conditions": [{"entity": show, "state": "on"}],
            "card": {
                "type": "entities",
                "title": f"{profile.title()} profile",
                "show_header_toggle": False,
                "entities": [
                    {"entity": entity_ids[f"{profile}_temperature"],
                     "name": "Cabin temperature"},
                    {"entity": entity_ids[f"{profile}_driver_seat_mode"],
                     "name": "Driver seat"},
                    {"entity": entity_ids[f"{profile}_passenger_seat_mode"],
                     "name": "Passenger seat"},
                    {"entity": entity_ids[f"{profile}_steering_toggle"],
                     "name": "Steering wheel heating"},
                ],
            },
        })
    return result


def independent_climate_schedule_cards(entity_ids: dict[str, str]) -> list[dict]:
    """Seven separately editable, weekly climate-only schedule cards."""
    cards = [
        {
            "type": "markdown",
            "content": "## Independent cabin comfort\\n"
            "Seven independent, once-per-week schedule slots. They do not "
            "depend on charging or being plugged in. Multiple slots may "
            "share the same weekday. All slots start disabled.\\n\\n"
            "**Simulation only:** no vehicle climate commands are sent.",
        },
        {
            "type": "entity",
            "entity": entity_ids["climate_next"],
            "name": "Next climate schedule (simulation)",
        },
    ]
    for slot in range(1, 8):
        pre = f"climate_slot_{slot}_"
        cards.append({
            "type": "entities",
            "title": f"Climate schedule {slot}",
            "show_header_toggle": False,
            "entities": [
                {"entity": entity_ids[pre + "enabled"], "name": "Schedule enabled"},
                {"entity": entity_ids[pre + "day"], "name": "Day of week"},
                {"entity": entity_ids[pre + "ready_time"], "name": "Cabin ready by"},
                {"type": "section", "label": "Cabin & comfort"},
                {"entity": entity_ids[pre + "temperature"], "name": "Cabin temperature"},
                {"entity": entity_ids[pre + "driver_seat"], "name": "Driver seat"},
                {"entity": entity_ids[pre + "passenger_seat"], "name": "Passenger seat"},
                {"entity": entity_ids[pre + "steering_heat"], "name": "Steering wheel heating"},
                {"type": "section", "label": "Timing"},
                {"entity": entity_ids[pre + "lead_minutes"], "name": "Start before ready"},
                {"entity": entity_ids[pre + "hold_minutes"], "name": "Keep running after ready"},
            ],
        })
    return cards



def dashboard_config(
    entity_ids: dict[str, str],
    battery: str,
    plug: str | None = None,
    charging_power: str | None = None,
) -> dict:
    """Construct a native, mobile-friendly four-view Lovelace dashboard.

    The configured Geely charging switch is NEVER rendered as a toggle.
    All writable dashboard entities edit this integration's hypothetical
    schedule; they cannot call the vehicle's control APIs.
    """
    status = entity_ids["observer_status"]
    simulation = entity_ids["simulation_decision"]

    charging_cards = [
        {
            "type": "markdown",
            "content": "## Geely Smart Charge & Climate\n"
            "**Simulation only.** This integration does not start, stop, "
            "heat or cool your vehicle. Your existing charging automations "
            "remain independent.",
        },
        {"type": "gauge", "entity": battery, "name": "Battery", "min": 0, "max": 100},
        {
            "type": "entities",
            "title": "Vehicle and connection",
            "show_header_toggle": False,
            "entities": (
                [battery]
                + ([plug] if plug else [])
                + ([charging_power] if charging_power else [])
                + [status]
            ),
        },
        {
            "type": "entity",
            "entity": simulation,
            "name": "Next charging simulation",
            "icon": "mdi:calendar-clock",
        },
        {
            "type": "markdown",
            "content": "### Simulated planning\n"
            f"Next scheduled day: **{{{{ state_attr('{simulation}', 'next_schedule_day') or 'None' }}}}**  \n"
            f"Battery target: **{{{{ state_attr('{simulation}', 'target_percent') or '—' }}}}%**  \n"
            f"Ready by: **{{{{ state_attr('{simulation}', 'ready_by') or '—' }}}}**  \n"
            f"Estimated start: **{{{{ state_attr('{simulation}', 'estimated_start') or '—' }}}}**  \n"
            f"Reason: {{{{ state_attr('{simulation}', 'reason') or '—' }}}}",
        },
    ]

    schedule_cards = [
        {
            "type": "markdown",
            "content": "## Weekly charging schedule\n"
            "Set the day the vehicle needs to be **ready**, the battery target, "
            "and the time. These controls affect the **simulation only**. "
            "No charging commands will be sent.",
        },
        *[schedule_card(day, entity_ids) for day in DAYS],
    ]

    stats_cards = [
        {
            "type": "entities",
            "title": "Simulation status",
            "show_header_toggle": False,
            "entities": [status, simulation, battery]
            + ([charging_power] if charging_power else []),
        },
        {
            "type": "markdown",
            "content": "### Charging-rate learning\n"
            f"Charger rated power: **{{{{ state_attr('{simulation}', 'charger_rated_kw') }}}} kW**  \n"
            f"Rate source: **{{{{ state_attr('{simulation}', 'charge_rate_source') }}}}**  \n"
            f"Learned rate: **{{{{ state_attr('{simulation}', 'learned_percentage_points_per_hour') or 'Not yet learned' }}}} %/hr**  \n"
            f"Samples: **{{{{ state_attr('{simulation}', 'learning_sample_count') or 0 }}}}**",
        },
        {
            "type": "history-graph",
            "title": "Battery history",
            "hours_to_show": 48,
            "entities": [battery],
        },
    ]
    if charging_power:
        stats_cards.append(
            {
                "type": "history-graph",
                "title": "Charging power history",
                "hours_to_show": 48,
                "entities": [charging_power],
            }
        )

    return {
        "title": "EV Control Centre",
        "views": [
            {
                "title": "Charging",
                "path": "charging",
                "icon": "mdi:ev-station",
                "type": "masonry",
                "cards": charging_cards,
            },
            {
                "title": "Climate",
                "path": "climate",
                "icon": "mdi:car-defrost-front",
                "type": "masonry",
                "cards": comfort_cards(entity_ids) + independent_climate_schedule_cards(entity_ids),
            },
            {
                "title": "Schedule",
                "path": "schedule",
                "icon": "mdi:calendar-clock",
                "type": "masonry",
                "cards": schedule_cards,
            },
            {
                "title": "Statistics",
                "path": "statistics",
                "icon": "mdi:chart-line",
                "type": "masonry",
                "cards": stats_cards,
            },
        ],
    }
