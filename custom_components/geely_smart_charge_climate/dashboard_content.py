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
            "content": "## Independent cabin comfort\n"
            "Seven independent, once-per-week schedule slots. They do not "
            "depend on charging or being plugged in. Multiple slots may "
            "share the same weekday. All slots start disabled.\n\n"
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
    """Ready-by day/time schedules; starts need not be overnight."""
    rows = []
    for day in DAYS:
        rows.extend([
            {"type": "section", "label": f"{day.title()} — ready-by deadline"},
            {"entity": entity_ids[f"{day}_enabled"], "name": "Schedule enabled"},
            {"entity": entity_ids[f"{day}_target"], "name": "Battery target %"},
            {"entity": entity_ids[f"{day}_ready_time"], "name": "Ready by (any time)"},
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
    charging_switch: str | None = None,
    extra_sensors: dict[str, str] | None = None,
    charger_sensors: dict[str, str] | None = None,
) -> dict:
    """Construct a native, mobile-friendly four-view Lovelace dashboard.

    The configured Geely charging switch is NEVER rendered as a toggle.
    All writable dashboard entities edit this integration's hypothetical
    schedule; they cannot call the vehicle's control APIs.
    """
    status = entity_ids["observer_status"]
    simulation = entity_ids["simulation_decision"]

    automatic_panel = [
        {
            "type": "markdown",
            "content": "### Automatic charging authorisation\n"
            "**Off:** no automatic commands. "
            "**Monitor:** records decisions without touching the car. "
            "**Active:** permits scheduled charging and verified stopping of "
            "unauthorised charging while Public Mode is OFF. "
            "This testing-stage mode resets to Off after a Home Assistant restart. "
            "Do not leave it unattended yet.",
        },
        {
            "type": "entities",
            "title": "Automatic controller & audit",
            "show_header_toggle": False,
            "entities": [
                {"entity": entity_ids["public_charging_mode"],
                 "name": "Public charging mode — turn ON when away/public"},
                {"entity": entity_ids["automatic_charge_mode"],
                 "name": "Controller mode"},
                {"entity": entity_ids["automatic_charge_decision"],
                 "name": "Latest authorisation decision"},
            ],
        },
        {
            "type": "markdown",
            "content": "#### Latest decision\n"
            f"Status: **{{{{ states('{entity_ids['automatic_charge_decision']}') }}}}**  \n"
            f"Reason: {{{{ state_attr('{entity_ids['automatic_charge_decision']}', 'message') or '—' }}}}  \n"
            f"Public charging: {{{{ state_attr('{entity_ids['automatic_charge_decision']}', 'public_charging_mode') }}}}  \n"
            f"Next ready by: {{{{ state_attr('{entity_ids['automatic_charge_decision']}', 'ready_by') or '—' }}}}  \n"
            f"Enabled days: {{{{ state_attr('{entity_ids['automatic_charge_decision']}', 'enabled_schedule_days') or [] }}}}  \n"
            f"Live policy: {{{{ state_attr('{entity_ids['automatic_charge_decision']}', 'live_policy_reason') or '—' }}}}",
        },
    ]

    live_panel = [
        {
            "type": "markdown",
            "content": "### Live manual charging test\n"
            "**Opt-in test only.** The new controller does not run schedules "
            "or climate. First disable your old charging controller and verify "
            "it is inactive. Then arm this test and use Start. "
            "Stay present for the first short charge.",
        },
        {
            "type": "entities",
            "title": "Manual test and safety",
            "show_header_toggle": False,
            "entities": [
                {"entity": entity_ids["live_test_status"], "name": "Test status"},
                {"entity": entity_ids["live_test_armed"], "name": "Arm live test"},
                {"entity": entity_ids["live_test_target"], "name": "Test battery target"},
            ],
        },
        {
            "type": "grid",
            "columns": 2,
            "square": False,
            "cards": [
                {
                    "type": "button",
                    "entity": entity_ids["live_test_start"],
                    "name": "Start test",
                    "icon": "mdi:play-circle",
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "button.press",
                        "target": {"entity_id": entity_ids["live_test_start"]},
                        "confirmation": {
                            "text": "Start a real Geely charge? Old charging control must be disabled."
                        },
                    },
                },
                {
                    "type": "button",
                    "entity": entity_ids["live_test_stop"],
                    "name": "Stop test",
                    "icon": "mdi:stop-circle",
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "button.press",
                        "target": {"entity_id": entity_ids["live_test_stop"]},
                    },
                },
            ],
        },
    ]


    # Use Markdown instead of a switch entity row to prevent accidental toggles.
    status_line = (
        f"**Geely charging:** {{{{ states('{charging_switch}') | title }}}}  \n"
        if charging_switch else "**Geely charging:** Not configured  \n"
    )
    power_line = (
        f"**Charging power:** {{{{ states('{charging_power}') }}}} "
        f"{{{{ state_attr('{charging_power}', 'unit_of_measurement') or 'kW' }}}}  \n"
        if charging_power else "**Charging power:** Not configured  \n"
    )
    plug_line = (
        f"**Cable connected:** {{{{ states('{plug}') | title }}}}  \n"
        if plug else "**Cable connected:** Not detected  \n"
    )
    live_status_card = {
        "type": "markdown",
        "content": "### Live Geely charging status\n"
        + f"**Battery:** {{{{ states('{battery}') }}}}%  \n"
        + status_line + power_line + plug_line
        + "*Read-only telemetry; use the armed live-test controls below.*",
    }

    charging_cards = [
        {
            "type": "markdown",
            "content": "## Geely Smart Charge & Climate\n"
            "**Climate remains simulation-only.** Charging commands require explicit "
            "manual arming or Active automatic mode; Monitor is read-only. "
            "**Turn Public charging mode ON before connecting to a public charger; "
            "turn it OFF at home. No location is detected automatically.** "
            "Keep your old controller disabled during testing.",
        },
        {"type": "gauge", "entity": battery, "name": "Battery", "min": 0, "max": 100},
        live_status_card,
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
            "Choose the **day and time the battery must be ready**, not when "
            "charging starts. Evenings and shift-work deadlines are supported. "
            "Charging may begin earlier on the same day or the previous day. "
            "Monitor makes no commands; Active enables automatic control.",
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
    charger_sensors = charger_sensors or {}

    def heading(title, icon):
        return {
            "type": "heading", "heading": title,
            "heading_style": "title", "icon": icon,
        }

    def tiles(items, columns=2):
        return {
            "type": "grid", "columns": columns, "square": False,
            "cards": [
                {
                    "type": "tile", "entity": extra_sensors[key],
                    "name": label, "icon": icon,
                }
                for key, label, icon in items if key in extra_sensors
            ],
        }

    grouped = (
        ("Range & driving", "mdi:map-marker-distance", (
            ("range_at_full_charge", "Range at 100%", "mdi:battery-arrow-up"),
            ("total_mileage", "Odometer", "mdi:counter"),
            ("trip_meter", "Trip meter", "mdi:map-marker-distance"),
            ("trip_consumption", "Trip consumption", "mdi:lightning-bolt"),
        )),
        ("Energy efficiency", "mdi:leaf", (
            ("average_consumption", "Average consumption", "mdi:chart-line"),
            ("efficiency", "Efficiency", "mdi:leaf"),
        )),
        ("Climate & temperatures", "mdi:thermometer", (
            ("interior_temperature", "Cabin temperature", "mdi:car-seat"),
            ("exterior_temperature", "Outside temperature", "mdi:weather-sunny"),
            ("cabin_humidity", "Cabin humidity", "mdi:water-percent"),
        )),
        ("Tyre pressures", "mdi:car-tire-alert", (
            ("tire_front_left", "Front left", "mdi:car-tire-alert"),
            ("tire_front_right", "Front right", "mdi:car-tire-alert"),
            ("tire_rear_left", "Rear left", "mdi:car-tire-alert"),
            ("tire_rear_right", "Rear right", "mdi:car-tire-alert"),
        )),
        ("Vehicle health", "mdi:car-cog", (
            ("12v_battery", "12V battery", "mdi:car-battery"),
            ("12v_voltage", "12V voltage", "mdi:current-dc"),
            ("days_to_service", "Days to service", "mdi:calendar-clock"),
            ("distance_to_service", "Distance to service", "mdi:road"),
            ("last_updated", "Last update", "mdi:clock-outline"),
            ("car_reported_at", "Last vehicle report", "mdi:car-clock"),
        )),
        ("Charging measurements", "mdi:ev-station", (
            ("charge_current", "Charging current", "mdi:current-ac"),
            ("charge_voltage", "Charging voltage", "mdi:sine-wave"),
            ("time_to_full_charge", "Time to full", "mdi:timer-outline"),
        )),
    )

    # Preserve the original diagnostics in a secondary region, while making
    # the main stats page primarily vehicle telemetry.
    vehicle_cards = [
        {"type": "markdown", "content":
         "# ⚡ GEELY EX5\n"
         "**Vehicle telemetry · Battery · Charging · Health**\n\n"
         "*Read-only status. No vehicle commands are sent.*"},
        {
            "type": "grid", "columns": 2, "square": False, "cards": [
                {"type": "gauge", "entity": battery, "name": "BATTERY",
                 "min": 0, "max": 100, "needle": True,
                 "severity": {"red": 0, "yellow": 25, "green": 60}},
            ] + ([
                {"type": "gauge", "entity": extra_sensors["electric_range"],
                 "name": "ESTIMATED RANGE", "min": 0, "max": 500,
                 "needle": True,
                 "severity": {"red": 0, "yellow": 100, "green": 200}},
            ] if "electric_range" in extra_sensors else []),
        },
        heading("Charging telemetry", "mdi:ev-station"),
        {"type": "entities", "title": "Live charging status",
         "show_header_toggle": False, "entities":
         [battery] + ([plug] if plug else [])
         + ([charging_power] if charging_power else []) + [status, simulation]},
    ]

    # Keep each useful section immediately under its own heading. Empty
    # categories are omitted instead of showing errors from missing sensors.
    for title, icon, items in grouped[:2]:
        grid = tiles(items)
        if grid["cards"]:
            vehicle_cards.extend([heading(title, icon), grid])

    right_cards = []
    for title, icon, items in grouped[2:4]:
        grid = tiles(items)
        if grid["cards"]:
            right_cards.extend([heading(title, icon), grid])

    temperature_items = [
        ("tire_temperature_fl", "Front left"),
        ("tire_temperature_fr", "Front right"),
        ("tire_temperature_rl", "Rear left"),
        ("tire_temperature_rr", "Rear right"),
    ]
    tyre_temps = [
        {"entity": extra_sensors[key], "name": title}
        for key, title in temperature_items if key in extra_sensors
    ]
    if tyre_temps:
        right_cards.extend([
            heading("Tyre temperatures", "mdi:thermometer"),
            {"type": "entities", "title": "Tyre temperatures",
             "show_header_toggle": False, "entities": tyre_temps},
        ])

    for title, icon, items in grouped[4:]:
        grid = tiles(items)
        if grid["cards"]:
            right_cards.extend([heading(title, icon), grid])

    if charger_sensors:
        charger_rows = [
            {"entity": charger_sensors[key], "name": name}
            for key, name in (
                ("connected", "Wall Connector vehicle connected"),
                ("status", "Wall Connector status"),
                ("session_energy", "Current session energy"),
                ("energy", "Total delivered energy"),
            )
            if key in charger_sensors
        ]
        if charger_rows:
            right_cards.extend([
                heading("Wall Connector", "mdi:ev-plug-type2"),
                {"type": "entities", "title": "Optional charger telemetry",
                 "show_header_toggle": False, "entities": charger_rows},
            ])
        if "power" in charger_sensors:
            vehicle_cards.extend([
                heading("Charger power", "mdi:flash"),
                {"type": "grid", "columns": 2, "square": False,
                 "cards": (
                    [{"type": "gauge", "entity": charging_power,
                      "name": "GEELY CHARGING", "min": 0, "max": 11,
                      "needle": True}] if charging_power else []
                 ) + [
                    {"type": "gauge", "entity": charger_sensors["power"],
                     "name": "WALL CONNECTOR", "min": 0, "max": 11,
                     "needle": True},
                 ]},
            ])

    right_cards.extend([
        heading("Energy & battery history", "mdi:chart-line"),
        {"type": "history-graph", "title": "Battery level — 7 days",
         "hours_to_show": 168, "entities": [battery]},
    ])
    power_series = (
        ([charging_power] if charging_power else [])
        + ([charger_sensors["power"]] if "power" in charger_sensors else [])
    )
    if power_series:
        right_cards.append({
            "type": "history-graph", "title": "Charging power — 24 hours",
            "hours_to_show": 24, "entities": power_series,
        })
    right_cards.extend([
        heading("Charge planning diagnostics", "mdi:information-outline"),
        {
            "type": "markdown",
            "content": "### Charging-rate learning\n"
            f"Charger rating: **{{{{ state_attr('{simulation}', 'charger_rated_kw') }}}} kW**  \n"
            f"Rate source: **{{{{ state_attr('{simulation}', 'charge_rate_source') }}}}**  \n"
            f"Learned rate: **{{{{ state_attr('{simulation}', 'learned_percentage_points_per_hour') or 'Not yet learned' }}}} %/hr**  \n"
            f"Samples: **{{{{ state_attr('{simulation}', 'learning_sample_count') or 0 }}}}",
        },
    ])
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
                    _section(charging_cards + automatic_panel + live_panel),
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
                    _section(vehicle_cards),
                    _section(right_cards),
                ],
            },
        ],
    }
