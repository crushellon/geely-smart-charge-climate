"""Pure profile preference and non-control tests."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
spec = importlib.util.spec_from_file_location("geely_comfort_test", ROOT / "comfort.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ComfortTests(unittest.TestCase):
    def test_warm_cool_defaults_independent(self):
        self.assertEqual(module.get_value({}, "warm", "temperature"), 24)
        self.assertEqual(module.get_value({}, "cool", "temperature"), 20)

    def test_single_change_preserves_other_values(self):
        options = module.set_value({}, "warm", "driver_seat_heat", 3)
        options = module.set_value(options, "cool", "temperature", 19)
        self.assertEqual(module.get_value(options, "warm", "driver_seat_heat"), 3)
        self.assertEqual(module.get_value(options, "cool", "temperature"), 19)
        self.assertEqual(module.get_value(options, "warm", "temperature"), 24)

    def test_invalid_settings_rejected(self):
        for field, value in (("temperature", 40), ("driver_seat_heat", 4),
                             ("steering_heat", 2), ("temperature", 21.5)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                module.validate_field(field, value)

    def test_avoids_vehicle_commands(self):
        for path in ("comfort.py", "number.py", "dashboard_content.py"):
            source = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("hass.services.async_call", source)
            self.assertNotIn("my_geely_ex5_4034_speed", source)


if __name__ == "__main__":
    unittest.main()
