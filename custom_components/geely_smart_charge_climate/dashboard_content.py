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
    """Display named Cool and Warm seat settings, without expand toggles."""
    result = [
        {"type": "markdown",
         "content": "## Comfort settings\n"
         "**Simulation only.** These preferences do not command the vehicle."}
    ]
    for profile in ("cool", "warm"):
        result.append({
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



def charging_schedule_card(entity_ids: dict[str, str]) -> dict:
    """One weekly schedule aligned to the night-before / ready-next-day model."""
    rows = []
    for index, day in enumerate(DAYS):
        previous = DAYS[(index - 1) % 7].title()
        rows.extend([
            {"type": "section", "label": f"{previous} night → {day.title()}"},
            {"entity": entity_ids[f"{day}_enabled"], "name": "Schedule enabled"},
            {"entity": entity_ids[f"{day}_target"], "name": "Finish battery %"},
            {"entity": entity_ids[f"{day}_ready_time"], "name": "Ready by (next morning)"},
            {"entity": entity_ids[f"{day}_linked_comfort_enabled"],
             "name": "Cabin comfort enabled"},
            {"entity": entity_ids[f"{day}_linked_comfort_profile"],
             "name": "Comfort profile (Cool / Warm)"},
        ])
    return {"type": "entities", "title": "Seven-day charging schedule",
            "show_header_toggle": False, "entities": rows}


def _section(cards: list[dict]) -> dict:
    return {"type": "grid", "cards": cards}


def dashboard_config(
    entity_ids: dict[str, str],
    battery: str,
    plug: str | None = None,
    charging_power: str | None = None,
    extra_sensors: dict[str, str] | None = None,
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

    comfort_timing = {
        "type": "entities",
        "title": "Charging-linked cabin comfort timing",
        "show_header_toggle": False,
        "entities": [
            {"entity": entity_ids["linked_comfort_lead_minutes"],
             "name": "Start before ready-by"},
            {"entity": entity_ids["linked_comfort_hold_minutes"],
             "name": "Keep running after ready-by"},
        ],
    }
    info = {"type": "markdown", "content":
        "**Charging-linked comfort** uses the same ready-by time as charging. "
        "Choose Cool/Warm on the charging schedule; its settings are on "
        "Comfort Settings. **Simulation only.**"}
    extra_sensors = extra_sensors or {}
    extras = []
    groups = (
        ("Range & efficiency", (
            ("electric_range", "Estimated range"),
            ("range_at_full_charge", "Range at 100%"),
            ("total_mileage", "Odometer"),
            ("trip_meter", "Trip meter"),
            ("trip_consumption", "Trip consumption"),
            ("average_consumption", "Average consumption"),
            ("efficiency", "Energy efficiency"),
        )),
        ("Climate & temperatures", (
            ("interior_temperature", "Cabin temperature"),
            ("exterior_temperature", "Outside temperature"),
            ("cabin_humidity", "Cabin humidity"),
        )),
        ("Tyre monitoring", (
            ("tire_front_left", "Front left pressure"),
            ("tire_front_right", "Front right pressure"),
            ("tire_rear_left", "Rear left pressure"),
            ("tire_rear_right", "Rear right pressure"),
            ("tire_temperature_fl", "Front left temperature"),
            ("tire_temperature_fr", "Front right temperature"),
            ("tire_temperature_rl", "Rear left temperature"),
            ("tire_temperature_rr", "Rear right temperature"),
        )),
        ("Vehicle health", (
            ("12v_battery", "12V battery"),
            ("12v_voltage", "12V voltage"),
            ("days_to_service", "Days to service"),
            ("distance_to_service", "Distance to service"),
            ("last_updated", "Last update"),
            ("car_reported_at", "Last vehicle report"),
        )),
        ("Charging measurements", (
            ("charge_current", "Charging current"),
            ("charge_voltage", "Charging voltage"),
            ("time_to_full_charge", "Time to full"),
        )),
    )
    for title, fields in groups:
        rows = [
            {"entity": extra_sensors[key], "name": name}
            for key, name in fields if key in extra_sensors
        ]
        if rows:
            extras.append({
                "type": "entities", "title": title,
                "show_header_toggle": False, "entities": rows,
            })
    data_cards = [
        {"type": "markdown", "content":
         "## Geely EX5 — vehicle data\n"
         "Telemetry, battery condition, charging and vehicle health."},
        {"type": "gauge", "entity": battery, "name": "Battery",
         "min": 0, "max": 100,
         "severity": {"red": 0, "yellow": 25, "green": 60}},
        {"type": "entities", "title": "Connection and charging",
         "show_header_toggle": False,
         "entities": [battery] + ([plug] if plug else [])
         + ([charging_power] if charging_power else []) + [status]},
        *stats_cards,
    ]
    all_climate = independent_climate_schedule_cards(entity_ids)
    return {
        "title": "Geely EV Control Centre (Test)",
        "views": [
            {
                "title": "Charging & Schedule",
                "path": "charging",
                "icon": "mdi:car-electric",
                "type": "sections",
                "max_columns": 2,
                "sections": [
                    _section(charging_cards),
                    _section([charging_schedule_card(entity_ids), info]),
                ],
            },
            {
                "title": "Comfort Settings",
                "path": "comfort",
                "icon": "mdi:tune",
                "type": "sections",
                "max_columns": 2,
                "sections": [
                    _section([comfort_timing]),
                    _section(comfort_cards(entity_ids)),
                ],
            },
            {
                "title": "Climate Scheduler",
                "path": "climate-scheduler",
                "icon": "mdi:car-seat-heater",
                "type": "sections",
                "max_columns": 2,
                "sections": [
                    _section(all_climate[:2] + all_climate[2::2]),
                    _section(all_climate[3::2]),
                ],
            },
            {
                "title": "Vehicle Data",
                "path": "data",
                "icon": "mdi:chart-box-outline",
                "type": "sections",
                "max_columns": 2,
                "sections": [
                    _section(data_cards[:4]),
                    _section(data_cards[4:] + extras),
                ],
            },
        ],
    }
