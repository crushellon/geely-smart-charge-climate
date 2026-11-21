"""Regression tests for the original four-tab EV Control Centre design."""
import importlib.util
import json
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
            "climate_next": "sensor.climate_next",
            "live_test_status": "sensor.live_test_status",
            "manual_charge_status": "sensor.manual_charge_status",
            "vehicle_charging_status": "sensor.vehicle_charging_status",
            "automatic_charge_mode": "select.test_controller_mode",
            "automatic_charge_decision": "sensor.automatic_charge_decision",
            "public_charging_mode": "switch.public_charging_mode",
            "automatic_charging_enabled": "switch.automatic_charging_enabled",
            "manual_charge_target": "number.manual_charge_target",
            "manual_cabin_temperature": "number.manual_cabin_temperature",
            "manual_climate_status": "sensor.manual_climate_status",
            "scheduled_climate_status": "sensor.scheduled_climate_status",
            "scheduled_climate_enabled": "switch.scheduled_climate_enabled",
        }
        for day in module.DAYS:
            for role, domain in (
                ("enabled", "switch"), ("target", "number"), ("ready_time", "time")
            ):
                self.ids[f"{day}_{role}"] = f"{domain}.{day}_{role}"
            self.ids[f"{day}_linked_comfort_enabled"] = f"switch.{day}_linked_comfort_enabled"
            self.ids[f"{day}_linked_comfort_profile"] = f"select.{day}_linked_comfort_profile"
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
        for field in ("lead_minutes", "hold_minutes"):
            self.ids[f"linked_comfort_{field}"] = f"number.linked_comfort_{field}"
        for slot in range(1, 8):
            for field, domain in (
                ("enabled", "switch"), ("day", "select"), ("ready_time", "time"),
                ("temperature", "number"), ("driver_seat", "select"),
                ("passenger_seat", "select"), ("steering_heat", "switch"),
                ("lead_minutes", "number"), ("hold_minutes", "number"),
            ):
                self.ids[f"climate_slot_{slot}_{field}"] = f"{domain}.climate_slot_{slot}_{field}"
        for action in ("start", "stop", "quick80", "quick100", "resume"):
            self.ids[f"manual_charge_{action}"] = f"button.manual_charge_{action}"
        for action in ("stop", "release"):
            self.ids[f"emergency_{action}"] = f"button.emergency_{action}"
        for action in ("cool", "warm", "custom", "off"):
            self.ids[f"manual_climate_{action}"] = f"button.manual_climate_{action}"
        self.config = module.dashboard_config(
            self.ids, "sensor.my_geely_ex5_4034_battery",
            "binary_sensor.my_geely_ex5_4034_charger_plug",
            "sensor.my_geely_ex5_4034_charging_power",
            charging_switch="switch.my_geely_ex5_4034_charging",
            climate_entity="climate.my_geely_ex5_4034_climate",
        )

    def left(self):
        return self.config["views"][0]["sections"][0]["cards"]

    def right(self):
        return self.config["views"][0]["sections"][1]["cards"]

    def test_four_reference_views_and_two_column_layout(self):
        self.assertEqual([v["path"] for v in self.config["views"]],
                         ["charging", "comfort", "climate-scheduler", "data"])
        self.assertEqual([v["title"] for v in self.config["views"]],
                         ["EV Control", "Comfort Settings", "Climate Scheduler", "EX5 Stats"])
        self.assertEqual(self.config["title"], "Geely EV Control Centre")
        for view in self.config["views"]:
            self.assertEqual(view["type"], "sections")
            self.assertEqual(view["max_columns"], 2)
            self.assertEqual(len(view["sections"]), 2)

    def test_main_page_reproduces_reference_layout(self):
        cards = self.left()
        self.assertIn("Geely EX5", cards[0]["content"])
        self.assertEqual(cards[1]["title"], "Charging and safety")
        self.assertIn("switch.automatic_charging_enabled", str(cards[1]))
        self.assertIn("switch.public_charging_mode", str(cards[1]))
        self.assertEqual(cards[2]["type"], "grid")
        self.assertEqual(cards[3]["title"], "Manual charge")
        self.assertIn("Manual charge preview", cards[4]["content"])
        self.assertEqual(cards[6]["title"], "Manual climate")
        self.assertEqual(cards[7]["type"], "grid")

    def test_normal_actions_replace_all_testing_controls(self):
        text = json.dumps(self.config)
        for name in ("manual_charge_start", "manual_charge_stop",
                     "manual_charge_quick80", "manual_charge_quick100",
                     "manual_charge_resume", "manual_climate_cool",
                     "manual_climate_warm", "manual_climate_custom",
                     "manual_climate_off", "emergency_stop", "emergency_release"):
            self.assertIn(f"button.{name}", text)
        for name in ("button.live_test_start", "button.live_test_stop",
                     "switch.live_test_armed", "select.test_controller_mode"):
            self.assertNotIn(name, text)
        start = self.left()[5]["cards"][0]
        self.assertEqual(start["tap_action"]["perform_action"], "button.press")
        self.assertIn("confirmation", start["tap_action"])

    def test_scheduled_days_attached_to_ready_by_day_not_night(self):
        schedule = self.right()[0]
        self.assertEqual(schedule["title"], "Seven-day charging schedule")
        rows = schedule["entities"]
        self.assertEqual(len(rows), 42)
        self.assertEqual(rows[0]["label"], "Monday — ready-by deadline")
        self.assertEqual(rows[3]["name"], "Ready by (any time)")
        self.assertEqual(rows[5]["entity"], "select.monday_linked_comfort_profile")
        self.assertIn("Sunday — ready-by deadline", str(rows))
        self.assertNotIn("night →", str(rows))

    def test_comfort_expanders_match_original(self):
        cards = self.config["views"][1]["sections"][1]["cards"]
        self.assertEqual([c["type"] for c in cards[:4]],
                         ["entities", "conditional", "entities", "conditional"])
        self.assertEqual(cards[0]["title"], "Comfort Cool — expand settings")
        self.assertEqual(cards[1]["card"]["title"], "Cool profile")
        self.assertEqual(cards[2]["title"], "Comfort Warm — expand settings")
        self.assertEqual(cards[3]["card"]["title"], "Warm profile")
        self.assertIn("select.cool_driver_seat_mode", str(cards[1]))
        self.assertIn("select.warm_passenger_seat_mode", str(cards[3]))

    def test_seven_independent_climate_slots_retained(self):
        all_cards = sum(
            (section["cards"] for section in self.config["views"][2]["sections"]), []
        )
        slots = [x for x in all_cards if x.get("title", "").startswith("Climate schedule ")]
        self.assertEqual(len(slots), 7)
        self.assertEqual([c["title"] for c in slots],
                         ["Climate schedule 1", "Climate schedule 3",
                          "Climate schedule 5", "Climate schedule 7",
                          "Climate schedule 2", "Climate schedule 4",
                          "Climate schedule 6"])
        self.assertIn("select.climate_slot_1_driver_seat", str(slots[0]))

    def test_telemetry_never_exposes_raw_geely_charging_toggle(self):
        text = json.dumps(self.config)
        self.assertIn("switch.my_geely_ex5_4034_charging", text)
        self.assertNotIn('"entity": "switch.my_geely_ex5_4034_charging"', text)
        self.assertIn("Geely power", text)
        self.assertIn("power not confirmed", text)
        self.assertIn("sensor.my_geely_ex5_4034_charging_power", text)

    def test_optional_tesla_telemetry_is_informational(self):
        rich = module.dashboard_config(
            self.ids, "sensor.example_battery",
            charging_switch="switch.example_charging",
            charging_power="sensor.example_charging_power",
            charger_sensors={
                "power": "sensor.tesla_wall_connector_total_power",
                "connected": "binary_sensor.tesla_wall_connector_vehicle_connected",
            },
        )
        left = rich["views"][0]["sections"][0]["cards"]
        self.assertIn("sensor.tesla_wall_connector_total_power", left[0]["content"])
        self.assertIn("binary_sensor.tesla_wall_connector_vehicle_connected",
                      str(left[1]))
        stats = sum((s["cards"] for s in rich["views"][3]["sections"]), [])
        self.assertIn("Wall Connector", str(stats))
        self.assertNotIn("average_speed", str(stats))

    def test_optional_sensors_can_be_absent(self):
        result = module.dashboard_config(self.ids, "sensor.example_battery")
        self.assertEqual(len(result["views"]), 4)

    def test_data_has_gauges_and_full_history(self):
        rich = module.dashboard_config(
            self.ids, "sensor.example_battery",
            extra_sensors={
                "electric_range": "sensor.example_electric_range",
                "tire_front_left": "sensor.example_tire_front_left",
                "tire_temperature_fl": "sensor.example_tire_temp_fl",
                "12v_battery": "sensor.example_12v_battery",
            }
        )
        cards = sum((s["cards"] for s in rich["views"][3]["sections"]), [])
        self.assertIn("BATTERY", str(cards))
        self.assertIn("ESTIMATED RANGE", str(cards))
        self.assertIn("Tyre temperatures", str(cards))
        self.assertIn("Battery level — 7 days", str(cards))
        self.assertNotIn("average_speed", str(cards))

    def test_only_native_lovelace_cards(self):
        allowed = {"markdown", "entities", "gauge", "grid", "tile",
                   "history-graph", "heading", "entity", "conditional", "button"}
        def check(card):
            self.assertIn(card["type"], allowed)
            if card["type"] == "grid":
                for child in card["cards"]:
                    check(child)
            if card["type"] == "conditional":
                check(card["card"])
        for view in self.config["views"]:
            for section in view["sections"]:
                for card in section["cards"]:
                    check(card)


if __name__ == "__main__":
    unittest.main()
