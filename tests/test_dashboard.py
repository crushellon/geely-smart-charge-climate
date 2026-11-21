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
        self.config = module.dashboard_config(
            self.ids, "sensor.my_geely_ex5_4034_battery",
            "binary_sensor.my_geely_ex5_4034_charger_plug",
            "sensor.my_geely_ex5_4034_charging_power",
        )

    def test_four_views(self):
        self.assertEqual(
            [v["path"] for v in self.config["views"]],
            ["charging", "climate", "schedule", "statistics"],
        )

    def test_seven_editable_day_cards(self):
        schedule = self.config["views"][2]["cards"]
        self.assertEqual(len(schedule), 8)
        for day, card in zip(module.DAYS, schedule[1:]):
            self.assertEqual(
                [item["entity"] for item in card["entities"]],
                [self.ids[f"{day}_{r}"] for r in ("enabled", "target", "ready_time")],
            )

    def test_never_exposes_vehicle_charging_switch_as_control(self):
        from json import dumps
        text = dumps(self.config)
        self.assertNotIn("switch.my_geely_ex5_4034_charging", text)
        self.assertNotIn("climate.my_geely", text)
        self.assertIn("Simulation only", text)

    def test_optional_sensors_can_be_absent(self):
        result = module.dashboard_config(self.ids, "sensor.example_battery")
        self.assertEqual(len(result["views"]), 4)

    def test_uses_only_native_cards(self):
        native = {"markdown", "gauge", "entities", "entity", "history-graph"}
        for view in self.config["views"]:
            for card in view["cards"]:
                self.assertIn(card["type"], native)


if __name__ == "__main__":
    unittest.main()
