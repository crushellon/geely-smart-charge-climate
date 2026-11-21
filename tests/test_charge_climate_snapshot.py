"""Charging-linked comfort snapshot uses saved preferences without vehicle calls."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
package = types.ModuleType("snapshot_test_package")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
for name in ("weekly_schedule", "comfort", "comfort_display", "charge_climate"):
    spec = importlib.util.spec_from_file_location(
        f"{package.__name__}.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
linked = sys.modules[f"{package.__name__}.charge_climate"]
comfort = sys.modules[f"{package.__name__}.comfort"]
display = sys.modules[f"{package.__name__}.comfort_display"]


class LinkedComfortSnapshotTests(unittest.TestCase):
    def test_editing_any_comfort_setting_is_visible_in_running_schedule(self):
        options = {}
        initial = linked.snapshot(options, "saturday")
        self.assertFalse(initial["enabled"])
        self.assertEqual(initial["profile"], "Cool")
        self.assertTrue(initial["commands_enabled"])
        options = linked.set_value(options, "saturday", "enabled", True)
        options = linked.set_value(options, "saturday", "profile", "Warm")
        options = comfort.set_value(options, "warm", "temperature", 24.5)
        options = display.set_seat_mode(options, "warm", "driver", "Heat Medium")
        options = display.set_seat_mode(options, "warm", "passenger", "Heat Low")
        options = comfort.set_value(options, "warm", "steering_heat", 1)
        options = linked.set_timing(options, "lead_minutes", 17)
        options = linked.set_timing(options, "hold_minutes", 23)
        updated = linked.snapshot(options, "saturday")
        self.assertTrue(updated["enabled"])
        self.assertEqual(updated["profile"], "Warm")
        self.assertEqual(updated["temperature"], 24.5)
        self.assertEqual(updated["driver_seat"], "Heat Medium")
        self.assertEqual(updated["passenger_seat"], "Heat Low")
        self.assertTrue(updated["steering_heat"])
        self.assertEqual(updated["lead_minutes"], 17)
        self.assertEqual(updated["hold_minutes"], 23)
        self.assertTrue(updated["commands_enabled"])

    def test_enabled_schedule_uses_own_day_comfort_profile(self):
        options = linked.set_value({}, "monday", "enabled", True)
        options = linked.set_value(options, "monday", "profile", "Cool")
        options = linked.set_value(options, "tuesday", "profile", "Warm")
        self.assertEqual(linked.snapshot(options, "monday")["profile"], "Cool")
        self.assertFalse(linked.snapshot(options, "tuesday")["enabled"])
        self.assertEqual(linked.snapshot(options, "tuesday")["profile"], "Warm")


if __name__ == "__main__":
    unittest.main()
