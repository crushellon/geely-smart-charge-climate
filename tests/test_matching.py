"""Check EX5 auto-detection without requiring Home Assistant installation."""

import importlib.util
from pathlib import Path
import sys
import unittest

module_path = (
    Path(__file__).resolve().parents[1]
    / "custom_components/geely_smart_charge_climate/matching.py"
)
spec = importlib.util.spec_from_file_location("geely_matching_test", module_path)
matching = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = matching
spec.loader.exec_module(matching)


class GeelyMatchingTests(unittest.TestCase):
    def setUp(self):
        self.entities = [
            "sensor.my_geely_ex5_4034_battery",
            "switch.my_geely_ex5_4034_charging",
            "sensor.my_geely_ex5_4034_charging_power",
        ]

    def test_known_ex5_entity_names(self):
        self.assertEqual(matching.unique_vehicle_mapping(self.entities), {
            "battery_entity": "sensor.my_geely_ex5_4034_battery",
            "charging_switch": "switch.my_geely_ex5_4034_charging",
            "charging_power": "sensor.my_geely_ex5_4034_charging_power",
        })

    def test_optional_power_is_not_required(self):
        result = matching.unique_vehicle_mapping(self.entities[:2])
        self.assertIn("battery_entity", result)
        self.assertNotIn("charging_power", result)

    def test_second_ex5_never_guessed(self):
        other = [item.replace("4034", "9999") for item in self.entities]
        self.assertEqual(matching.unique_vehicle_mapping(self.entities + other), {})

    def test_unrelated_battery_does_not_match(self):
        self.assertIsNone(matching.role_and_stem("sensor.phone_battery"))
        self.assertIsNone(matching.role_and_stem("sensor.my_geely_ex5_4034_12v_battery"))
        self.assertIsNone(matching.role_and_stem("sensor.my_geely_ex5_4034_tire_front_left"))

    def test_duplicate_role_is_not_silently_selected(self):
        duplicated = self.entities + [self.entities[0]]
        self.assertEqual(matching.unique_vehicle_mapping(duplicated), {})


if __name__ == "__main__":
    unittest.main()
