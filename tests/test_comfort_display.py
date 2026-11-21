"""Test human-readable comfort options without Home Assistant dependencies."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
package = types.ModuleType("comfort_testpackage")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
spec_comfort = importlib.util.spec_from_file_location(
    "comfort_testpackage.comfort", ROOT / "comfort.py"
)
comfort = importlib.util.module_from_spec(spec_comfort)
sys.modules[spec_comfort.name] = comfort
spec_comfort.loader.exec_module(comfort)
spec = importlib.util.spec_from_file_location(
    "comfort_testpackage.comfort_display", ROOT / "comfort_display.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ComfortDisplayTests(unittest.TestCase):
    def test_default_warm_cool_modes(self):
        self.assertEqual(module.get_seat_mode({}, "warm", "driver"), "Heat Medium")
        self.assertEqual(module.get_seat_mode({}, "cool", "driver"), "Vent Medium")

    def test_switch_from_heat_to_vent_clears_heat(self):
        options = module.set_seat_mode({}, "warm", "driver", "Vent High")
        self.assertEqual(comfort.get_value(options, "warm", "driver_seat_heat"), 0)
        self.assertEqual(comfort.get_value(options, "warm", "driver_seat_vent"), 3)
        self.assertEqual(module.get_seat_mode(options, "warm", "driver"), "Vent High")

    def test_off_clears_both(self):
        options = module.set_seat_mode({}, "cool", "driver", "Heat Low")
        options = module.set_seat_mode(options, "cool", "driver", "Off")
        self.assertEqual(module.get_seat_mode(options, "cool", "driver"), "Off")

    def test_profiles_are_independent(self):
        options = module.set_seat_mode({}, "warm", "passenger", "Heat High")
        self.assertEqual(module.get_seat_mode(options, "cool", "passenger"), "Off")

    def test_expand_toggle_is_only_preference(self):
        options = module.set_profile_visible({}, "cool", False)
        self.assertFalse(module.get_profile_visible(options, "cool"))
        self.assertTrue(module.get_profile_visible(options, "warm"))

    def test_bad_seat_modes_are_rejected(self):
        for invalid in ("Heat Extreme", "Vent 4", "Cooling", ""):
            with self.assertRaises(ValueError):
                module.set_seat_mode({}, "cool", "driver", invalid)


if __name__ == "__main__":
    unittest.main()
