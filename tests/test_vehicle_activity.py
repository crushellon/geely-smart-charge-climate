"""Vehicle telemetry classification remains independent of charging owner."""
import importlib.util
from pathlib import Path
import sys
import unittest

FILE = (Path(__file__).resolve().parents[1]
        / "custom_components/geely_smart_charge_climate/vehicle_activity.py")
spec = importlib.util.spec_from_file_location("vehicle_activity_test", FILE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class VehicleActivityTests(unittest.TestCase):
    def test_positive_geely_power_confirms_charging(self):
        self.assertEqual(module.vehicle_activity("off", "6.89"), ("CHARGING", 6.89))

    def test_switch_on_with_delayed_power_is_reported_not_confirmed(self):
        self.assertEqual(module.vehicle_activity("on", "0"), ("CHARGING_REPORTED", 0.0))

    def test_fresh_off_and_zero_proves_stopped_telemetry(self):
        self.assertEqual(module.vehicle_activity("off", "0"), ("STOPPED", 0.0))

    def test_unavailable_is_not_asserted_off(self):
        self.assertEqual(module.vehicle_activity("unavailable", "unknown"),
                         ("UNKNOWN", None))
        self.assertEqual(module.vehicle_activity("off", "unavailable"),
                         ("UNKNOWN", None))
        self.assertEqual(module.vehicle_activity(None, None), ("UNKNOWN", None))

    def test_invalid_power_never_counts_as_charging(self):
        for invalid in ("nan", "inf", "-1", "bad"):
            with self.subTest(invalid=invalid):
                self.assertNotEqual(
                    module.vehicle_activity("off", invalid)[0], "CHARGING"
                )


if __name__ == "__main__":
    unittest.main()
