"""Native Lovelace EV Control Centre based on the original four-tab layout.

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
    """Cool/Warm expanders and profiles from the original EV Control Centre."""
    result = []
    for profile in ("cool", "warm"):
        marker = entity_ids[f"show_{profile}_settings"]
        result.extend([
            {
                "type": "entities",
                "title": f"Comfort {profile.title()} — expand settings",
                "show_header_toggle": False,
                "entities": [{"entity": marker, "name": f"Show {profile.title()} settings"}],
            },
            {
                "type": "conditional",
                "conditions": [{"condition": "state", "entity": marker, "state": "on"}],
                "card": {
                    "type": "entities",
                    "title": f"{profile.title()} profile",
                    "show_header_toggle": False,
                    "entities": [
                        {"entity": entity_ids[f"{profile}_temperature"], "name": "Cabin temperature"},
                        {"entity": entity_ids[f"{profile}_driver_seat_mode"], "name": "Driver seat"},
                        {"entity": entity_ids[f"{profile}_passenger_seat_mode"], "name": "Passenger seat"},
                        {"entity": entity_ids[f"{profile}_steering_toggle"], "name": "Steering wheel heating"},
                    ],
                },
            },
        ])
    result.append({
        "type": "markdown",
        "content": "Comfort preferences are saved here. Manual Cool/Warm buttons "
        "on EV Control can send Geely commands. Scheduled climate and "
        "charging-linked preconditioning are still being developed.",
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
    climate_entity: str | None = None,
) -> dict:
    """Construct a native, mobile-friendly four-view Lovelace dashboard.

    The configured Geely charging switch is NEVER rendered as a toggle.
    All writable dashboard entities edit this integration's hypothetical
    schedule; they cannot call the vehicle's control APIs.
    """
    status = entity_ids["observer_status"]
    simulation = entity_ids["simulation_decision"]

    # Show independent telemetry sources honestly. Wallbox power may be
    # available when the Geely cloud reports 0 or has not updated yet.
    extra_sensors = extra_sensors or {}
    charger_sensors = charger_sensors or {}
    geely_power_id = charging_power or "sensor.geely_power_not_configured"
    wall_power_id = charger_sensors.get("power", "sensor.optional_wallbox_not_configured")
    switch_id = charging_switch or "switch.geely_charging_not_configured"
    range_id = extra_sensors.get("electric_range")

    def action_button(key: str, title: str, icon: str, confirmation: str | None = None) -> dict:
        card = {
            "type": "button", "entity": entity_ids[key],
            "name": title, "icon": icon,
            "tap_action": {
                "action": "perform-action",
                "perform_action": "button.press",
                "target": {"entity_id": entity_ids[key]},
            },
        }
        if confirmation:
            card["tap_action"]["confirmation"] = {"text": confirmation}
        return card

    range_line = (
        f" · **Range:** {{{{ states('{range_id}') }}}} km"
        if range_id else ""
    )
    summary = {
        "type": "markdown",
        "content": (
            "### Geely EX5\n"
            f"**Battery:** {{{{ states('{battery}') }}}}%"
            + range_line + "  \n"
            + f"{{% set gp = states('{geely_power_id}') | float(-1) %}}"
              f"{{% set wp = states('{wall_power_id}') | float(-1) %}}"
              f"{{% set enabled = is_state('{entity_ids['automatic_charging_enabled']}', 'on') %}}"
              f"**Charging:** {{% if wp > 0.25 %}}{{{{ wp | round(2) }}}} kW (charger)"
              f"{{% elif gp > 0.25 %}}{{{{ gp | round(2) }}}} kW (Geely)"
              f"{{% elif is_state('{switch_id}', 'on') %}}Requested — power not confirmed"
              f"{{% else %}}Off{{% endif %}}  \n"
              f"**Automatic charging:** {{% if enabled %}}Enabled{{% else %}}Disabled{{% endif %}}"
              f" · **Session:** {{{{ states('{entity_ids['automatic_charge_decision']}') }}}}  \n"
              f"**Next charge:** {{{{ state_attr('{simulation}', 'estimated_start') or 'Not calculated' }}}}  \n"
              f"**Ready by:** {{{{ state_attr('{simulation}', 'ready_by') or 'Not scheduled' }}}}"
              f" · **Target:** {{{{ state_attr('{simulation}', 'target_percent') or '—' }}}}%"
        ),
    }
    safety_rows = [
        {"entity": entity_ids["automatic_charging_enabled"],
         "name": "Automatic charging enabled"},
        {"entity": entity_ids["public_charging_mode"],
         "name": "Public charging mode"},
        {"entity": entity_ids["automatic_charge_decision"],
         "name": "Charging session"},
    ]
    if plug:
        safety_rows.append({"entity": plug, "name": "Geely plugged in"})
    if "connected" in charger_sensors:
        safety_rows.append({
            "entity": charger_sensors["connected"], "name": "Wall connector (optional)"
        })
    safety = {
        "type": "entities", "title": "Charging and safety",
        "show_header_toggle": False, "entities": safety_rows,
    }
    safety_buttons = {
        "type": "grid", "columns": 2, "square": False, "cards": [
            action_button(
                "emergency_stop", "Emergency STOP", "mdi:alert-octagon",
                "Stop Geely charging and latch the emergency lockout?",
            ),
            action_button(
                "emergency_release", "Release emergency stop", "mdi:lock-open",
                "Release the emergency lockout? Automatic charging will not be enabled by this action.",
            ),
        ],
    }
    manual_target_id = entity_ids["manual_charge_target"]
    manual_charge = {
        "type": "entities", "title": "Manual charge",
        "show_header_toggle": False,
        "entities": [
            {"entity": manual_target_id, "name": "Target percentage"},
            {"entity": entity_ids["manual_charge_status"], "name": "Manual charge status"},
        ],
    }
    manual_preview = {
        "type": "markdown",
        "content": (
            "### Manual charge preview\n"
            f"{{% set soc = states('{battery}') | float(-1) %}}"
            f"{{% set target = states('{manual_target_id}') | float(-1) %}}"
            f"{{% set capacity = state_attr('{simulation}', 'assumed_usable_capacity_kwh') | float(68.39) %}}"
            f"{{% set rate = state_attr('{simulation}', 'assumed_effective_kw') | float(6.5) %}}"
            "{% if soc >= 0 and target >= 0 and rate > 0 %}"
            "{% set energy = [target - soc, 0] | max * capacity / 100 %}"
            "{% set mins = (energy / rate * 60) | round(0, 'ceil') | int %}"
            "**{{ soc|round(0)|int }}% → {{ target|round(0)|int }}%**"
            " · **{{ energy | round(1) }} kWh** to battery  \n"
            "**Estimated duration:** {{ mins // 60 }} hr {{ mins % 60 }} min  \n"
            "{% if mins > 0 %}**If started now:** approximately "
            "{{ (now() + timedelta(minutes=mins)).strftime('%I:%M %p') }}"
            "{% endif %}"
            "{% else %}Waiting for live battery and target readings.{% endif %}\n\n"
            "*Estimated from configured battery capacity and charging rate; "
            "100% balancing may take longer.*"
        ),
    }
    manual_buttons = {
        "type": "grid", "columns": 2, "square": False, "cards": [
            action_button("manual_charge_start", "Start chosen target", "mdi:play",
                          "Start a manual Geely charge? Automatic schedule will pause until Resume schedule."),
            action_button("manual_charge_stop", "Stop manual", "mdi:stop",
                          "Stop the integration-owned manual charge?"),
            action_button("manual_charge_quick80", "Quick 80%", "mdi:battery-80"),
            action_button("manual_charge_quick100", "Quick 100%", "mdi:battery-charging-100"),
            action_button("manual_charge_resume", "Resume schedule", "mdi:calendar-check"),
        ],
    }
    climate_rows = [
        {"entity": entity_ids["manual_cabin_temperature"], "name": "Custom cabin temperature"},
        {"entity": entity_ids["manual_climate_status"], "name": "Manual climate status"},
    ]
    if climate_entity:
        climate_rows.insert(0, {"entity": climate_entity, "name": "Cabin climate"})
    manual_climate = {
        "type": "entities", "title": "Manual climate",
        "show_header_toggle": False, "entities": climate_rows,
    }
    manual_climate_buttons = {
        "type": "grid", "columns": 2, "square": False,
        "cards": [
            action_button("manual_climate_cool", "Comfort Cool", "mdi:snowflake"),
            action_button("manual_climate_warm", "Comfort Warm", "mdi:weather-sunny"),
            action_button("manual_climate_custom", "Custom temperature ON", "mdi:thermometer"),
            action_button("manual_climate_off", "Climate + seats OFF", "mdi:power"),
        ],
    }
    power_details = (
        f"**Geely switch:** {{{{ states('{switch_id}') }}}}"
        f" · **Geely power:** {{{{ states('{geely_power_id}') }}}} kW  \n"
        + (f"**Optional charger power:** {{{{ states('{wall_power_id}') }}}} kW  \n"
           if "power" in charger_sensors else "")
        + f"**Stop verification:** {{{{ state_attr('{entity_ids['automatic_charge_decision']}', 'stop_verification') or 'Idle' }}}}  \n"
        + "*Power readings can be delayed. A charging request is not proof that energy is flowing.*"
    )
    charging_cards = [
        summary, safety, safety_buttons, manual_charge, manual_preview,
        manual_buttons, manual_climate, manual_climate_buttons,
        {"type": "markdown", "content": "### Charging telemetry\n" + power_details},
        {"type": "markdown", "content":
         "**Testing limitation:** Automatic charging currently requires re-enabling "
         "after a Home Assistant restart; unattended restart recovery is not "
         "yet complete. Public charging mode must be ON for public sessions. "
         "Linked and independent climate schedules do not yet send commands."},
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
        "Comfort Settings. **Scheduled climate commands are not enabled yet.**"}
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
        "title": "Geely EV Control Centre",
        "views": [
            {
                "title": "EV Control",
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
                "title": "EX5 Stats",
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
