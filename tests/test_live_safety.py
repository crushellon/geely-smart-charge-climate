"""Manual-only live test safety policies (pure Python, no Home Assistant)."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
spec = importlib.util.spec_from_file_location("geely_live_safety_test", ROOT / "live_safety.py")
safety = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = safety
spec.loader.exec_module(safety)


class LiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.good = {
            "armed": True, "battery": "72.0", "plugged": "on",
            "charging": "off", "target": 73,
            "legacy_states": {
                "input_boolean.ev_controller_enabled": "off",
                "binary_sensor.ev_legacy_charging_controllers_active": "off",
                "input_boolean.ev_manual_full_charge": "off",
                "input_boolean.ev_public_charging_mode": "off",
                "input_boolean.ev_emergency_stop": "off",
            },
        }

    def test_one_percent_manual_charge_authorised(self):
        self.assertIsNone(safety.start_preflight(**self.good))

    def test_never_start_when_unarmed(self):
        self.assertIn("disarmed", safety.start_preflight(**(self.good | {"armed": False})))

    def test_old_controllers_must_be_off(self):
        for entity in self.good["legacy_states"]:
            for state in ("on", "unavailable", "unknown"):
                with self.subTest(entity=entity, state=state):
                    legacy = {**self.good["legacy_states"], entity: state}
                    self.assertIsNotNone(
                        safety.start_preflight(**(self.good | {"legacy_states": legacy}))
                    )

    def test_no_plug_or_unavailable_battery_or_active_charger(self):
        for values in (
            {"plugged": "off"}, {"plugged": "unavailable"},
            {"battery": "unavailable"}, {"battery": "NaN"},
            {"battery": "80"}, {"charging": "on"},
            {"charging": "unknown"},
        ):
            with self.subTest(values=values):
                self.assertIsNotNone(safety.start_preflight(**(self.good | values)))

    def test_stop_80_at_target_and_on_telemetry_loss(self):
        self.assertTrue(safety.should_stop_owned_session(
            target=80, soc=80, emergency=False))
        self.assertTrue(safety.should_stop_owned_session(
            target=80, soc=None, emergency=False))
        self.assertFalse(safety.should_stop_owned_session(
            target=80, soc=79, emergency=False))

    def test_never_auto_stop_full_charge(self):
        for soc in (99, 100, None):
            with self.subTest(soc=soc):
                self.assertFalse(safety.should_stop_owned_session(
                    target=100, soc=soc, emergency=False))
        self.assertTrue(safety.should_stop_owned_session(
            target=100, soc=100, emergency=True))
        self.assertTrue(safety.should_stop_owned_session(
            target=100, soc=99, emergency=False, manual_stop=True))

    def test_no_unattended_start_or_climate_commands(self):
        source = (ROOT / "live_control.py").read_text(encoding="utf-8")
        self.assertNotIn("climate.turn_on", source)
        self.assertNotIn("schedule.start", source)
        self.assertNotIn("speed", source)
        self.assertIn("async_start", source)
        self.assertIn("async_stop", source)


if __name__ == "__main__":
    unittest.main()
