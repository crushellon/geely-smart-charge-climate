"""Standard-library tests of native dashboard structure and safety."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
spec = importlib.util.spec_from_file_location("geely_dashboard_content_test", ROOT / "dashboard_content.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.ids = {
            "observer_status": "sensor.observer_status",
            "simulation_decision": "sensor.simulation_decision",
        }
        for day in module.DAYS:
            for role in ("enabled", "target", "ready_time"):
                self.ids[f"{day}_{role}"] = (
                    {"enabled": "switch", "target": "number", "ready_time": "time"}[role]
                    + f".{day}_{role}"
                )
        for profile in ("warm", "cool"):
            for field in (
                "temperature", "driver_seat_heat", "passenger_seat_heat",
                "driver_seat_vent", "passenger_seat_vent", "steering_heat",
            ):
                self.ids[f"{profile}_{field}"] = f"number.{profile}_{field}"
            for occupant in ("driver", "passenger"):
                self.ids[f"{profile}_{occupant}_seat_mode"] = f"select.{profile}_{occupant}_seat_mode"
            self.ids[f"{profile}_steering_toggle"] = f"switch.{profile}_steering_toggle"
            self.ids[f"show_{profile}_settings"] = f"switch.show_{profile}_settings"
        for day in module.DAYS:
            self.ids[f"{day}_linked_comfort_enabled"] = f"switch.{day}_linked_comfort_enabled"
            self.ids[f"{day}_linked_comfort_profile"] = f"select.{day}_linked_comfort_profile"
        self.ids["linked_comfort_lead_minutes"] = "number.linked_comfort_lead_minutes"
        self.ids["linked_comfort_hold_minutes"] = "number.linked_comfort_hold_minutes"
        self.ids.update({
            "live_test_status": "sensor.live_test_status",
            "automatic_charge_mode": "select.automatic_charge_mode",
            "public_charging_mode": "switch.public_charging_mode",
            "automatic_charge_decision": "sensor.automatic_charge_decision",
            "live_test_armed": "switch.live_test_armed",
            "live_test_target": "number.live_test_target",
            "live_test_start": "button.live_test_start",
            "live_test_stop": "button.live_test_stop",
        })
        self.ids["climate_next"] = "sensor.climate_next"
        for slot in range(1, 8):
            for field, prefix in (
                ("enabled", "switch"), ("day", "select"),
                ("ready_time", "time"), ("temperature", "number"),
                ("driver_seat", "select"), ("passenger_seat", "select"),
                ("steering_heat", "switch"), ("lead_minutes", "number"),
                ("hold_minutes", "number"),
            ):
                self.ids[f"climate_slot_{slot}_{field}"] = (
                    f"{prefix}.climate_slot_{slot}_{field}"
                )
        self.config = module.dashboard_config(
            self.ids, "sensor.my_geely_ex5_4034_battery",
            "binary_sensor.my_geely_ex5_4034_charger_plug",
            "sensor.my_geely_ex5_4034_charging_power",
            charging_switch="switch.my_geely_ex5_4034_charging",
        )

    def test_four_focused_views(self):
        self.assertEqual(
            [v["path"] for v in self.config["views"]],
            ["charging", "comfort", "climate-scheduler", "data"],
        )
        self.assertEqual(
            [v["title"] for v in self.config["views"]],
            ["Charging & Schedule", "Comfort Settings", "Climate Scheduler", "Vehicle Data"],
        )
        for view in self.config["views"]:
            self.assertEqual(view["type"], "sections")
            self.assertEqual(len(view["sections"]), 2)

    def test_cool_warm_directly_visible(self):
        sections = self.config["views"][1]["sections"]
        cards = sections[1]["cards"]
        self.assertEqual([c["title"] for c in cards[1:]],
                         ["Cool profile", "Warm profile"])
        self.assertNotIn("conditional", [c["type"] for c in cards])
        self.assertIn(
            "select.cool_driver_seat_mode",
            [r["entity"] for r in cards[1]["entities"]],
        )

    def test_charging_schedule_single_card(self):
        sections = self.config["views"][0]["sections"]
        cards = sections[1]["cards"]
        self.assertEqual(cards[0]["title"], "Seven-day charging schedule")
        rows = cards[0]["entities"]
        self.assertEqual(len(rows), 7 * 6)
        self.assertEqual(rows[0]["label"], "Monday — ready-by deadline")
        self.assertEqual(rows[3]["name"], "Ready by (any time)")
        self.assertNotIn("night →", str(rows))
        self.assertEqual(rows[1]["entity"], "switch.monday_enabled")
        self.assertEqual(rows[4]["entity"], "switch.monday_linked_comfort_enabled")
        self.assertEqual(rows[5]["entity"], "select.monday_linked_comfort_profile")

    def test_seven_independent_climate_slots_on_own_page(self):
        sections = self.config["views"][2]["sections"]
        all_cards = sum((section["cards"] for section in sections), [])
        slots = [c for c in all_cards
                 if c.get("title", "").startswith("Climate schedule ")]
        self.assertEqual(len(slots), 7)
        self.assertEqual(
            [c["title"] for c in slots],
            ["Climate schedule 1", "Climate schedule 3", "Climate schedule 5",
             "Climate schedule 7", "Climate schedule 2", "Climate schedule 4",
             "Climate schedule 6"],
        )
        self.assertIn(
            "select.climate_slot_1_driver_seat",
            [r["entity"] for r in slots[0]["entities"] if "entity" in r],
        )

    def test_public_charging_mode_visible(self):
        charging = self.config["views"][0]["sections"][0]["cards"]
        self.assertIn("switch.public_charging_mode", str(charging))
        self.assertNotIn("Home confirmed", str(charging))

    def test_live_decision_displays_active_schedule_and_comfort(self):
        cards = self.config["views"][0]["sections"][0]["cards"]
        decision = next(card for card in cards
                        if card.get("type") == "markdown"
                        and "#### Latest decision" in card.get("content", ""))
        content = decision["content"]
        for attribute in (
            "active_target", "active_ready_by", "linked_comfort_enabled",
            "linked_comfort_profile", "linked_comfort_temperature",
            "linked_comfort_driver_seat", "linked_comfort_passenger_seat",
            "linked_comfort_steering_heat", "linked_comfort_lead_minutes",
            "linked_comfort_hold_minutes",
        ):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, content)
        self.assertIn("automatic climate commands are not enabled yet", content)
        self.assertNotIn("\\\\n", content)

    def test_live_manual_test_requires_explicit_user_button(self):
        sections = self.config["views"][0]["sections"]
        cards = sections[0]["cards"]
        actions = [card for card in cards if card.get("type") == "grid"
                   and any(c.get("type") == "button" for c in card["cards"])]
        self.assertEqual(len(actions), 1)
        entities = [c["entity"] for c in actions[0]["cards"]]
        self.assertEqual(entities, ["button.live_test_start", "button.live_test_stop"])
        self.assertIn("confirmation", actions[0]["cards"][0]["tap_action"])
        self.assertIn("Arm live test", str(cards))

    def test_read_only_live_charge_telemetry_without_bypass_toggle(self):
        from json import dumps
        charging = self.config["views"][0]["sections"][0]["cards"]
        live = [card for card in charging
                if card.get("type") == "markdown"
                and "Live Geely charging status" in card.get("content", "")]
        self.assertEqual(len(live), 1)
        content = live[0]["content"]
        self.assertIn("switch.my_geely_ex5_4034_charging", content)
        self.assertIn("sensor.my_geely_ex5_4034_charging_power", content)
        self.assertIn("binary_sensor.my_geely_ex5_4034_charger_plug", content)
        self.assertIn("states(", content)
        all_cards = dumps(self.config)
        self.assertNotIn('"entity": "switch.my_geely_ex5_4034_charging"', all_cards)
        self.assertNotIn("climate.my_geely", all_cards)
        self.assertIn("simulation-only", all_cards)

    def test_available_vehicle_data_in_its_own_page(self):
        rich = module.dashboard_config(
            self.ids, "sensor.example_battery",
            extra_sensors={
                "electric_range": "sensor.example_electric_range",
                "range_at_full_charge": "sensor.example_full_range",
                "efficiency": "sensor.example_efficiency",
                "interior_temperature": "sensor.example_interior_temperature",
                "tire_front_left": "sensor.example_tire_front_left",
                "tire_temperature_fl": "sensor.example_tire_temperature_fl",
                "12v_battery": "sensor.example_12v_battery",
            },
        )
        cards = sum(
            (section["cards"] for section in rich["views"][3]["sections"]), []
        )
        headings = [card.get("heading") for card in cards]
        for title in ("Range & driving", "Energy efficiency",
                      "Climate & temperatures", "Tyre pressures",
                      "Tyre temperatures", "Vehicle health",
                      "Energy & battery history"):
            self.assertIn(title, headings)
        gauges = [card for card in cards if card.get("type") == "grid"
                  and any(item.get("type") == "gauge" for item in card["cards"])]
        self.assertEqual(len(gauges[0]["cards"]), 2)
        self.assertNotIn("average_speed", str(cards))

    def test_wall_connector_remains_optional(self):
        config = module.dashboard_config(
            self.ids, "sensor.example_battery",
            charging_power="sensor.example_charge_power",
            charger_sensors={
                "power": "sensor.tesla_wall_connector_total_power",
                "connected": "binary_sensor.tesla_wall_connector_vehicle_connected",
                "session_energy": "sensor.tesla_wall_connector_session_energy",
            },
        )
        data_cards = sum(
            (section["cards"] for section in config["views"][3]["sections"]), []
        )
        self.assertTrue(any(card.get("heading") == "Wall Connector"
                            for card in data_cards))
        graph = next(c for c in data_cards
                     if c.get("title") == "Charging power — 24 hours")
        self.assertEqual(len(graph["entities"]), 2)
        self.assertNotIn("average_speed", str(data_cards))

    def test_optional_sensors_can_be_absent(self):
        result = module.dashboard_config(self.ids, "sensor.example_battery")
        self.assertEqual(len(result["views"]), 4)

    def test_uses_only_native_cards(self):
        native = {"markdown", "gauge", "entities", "entity", "history-graph", "heading", "grid", "tile"}
        for view in self.config["views"]:
            for section in view["sections"]:
                for card in section["cards"]:
                    self.assertIn(card["type"], native)


if __name__ == "__main__":
    unittest.main()
