"""Regression tests for side-effect-free charging decisions."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

PATH = Path(__file__).resolve().parents[1] / "custom_components" / "geely_smart_charge_climate" / "simulator.py"
spec = importlib.util.spec_from_file_location("standalone_simulator", PATH)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)
simulate = module.simulate
next_deadline = module.next_deadline


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, 23, 0, tzinfo=ZoneInfo("Australia/Brisbane"))
        self.ready = self.now + timedelta(hours=7, minutes=30)
        self.args = dict(now=self.now, ready_by=self.ready, soc=50,
                         target=80, effective_kw=6.5, usable_kwh=68.39,
                         charging=False, plugged=True)

    def check(self, action, **kwargs):
        self.assertEqual(simulate(**(self.args | kwargs)).action, action)

    def test_start_when_authorised(self):
        self.check("START")

    def test_wait_before_window(self):
        self.check("WAIT", soc=79)

    def test_no_plug_or_unknown_plug(self):
        self.check("BLOCKED", plugged=False)
        self.check("UNKNOWN", plugged=None)

    def test_manual_and_emergency_guards(self):
        self.check("BLOCKED", emergency=True)
        self.check("BLOCKED", public_mode=True)
        self.check("BLOCKED", enabled=False)
        self.check("COMPLETE", completed=True)

    def test_stop_sub_100_only(self):
        self.check("STOP_AT_TARGET", soc=80, charging=True)
        self.check("NO_CHARGE_NEEDED", soc=80)

    def test_100_never_controller_stop(self):
        for soc, charging in ((99, True), (100, True), (100, False)):
            with self.subTest(soc=soc, charging=charging):
                result = simulate(**(self.args | dict(target=100, soc=soc, charging=charging)))
                self.assertNotEqual(result.action, "STOP_AT_TARGET")
                self.assertEqual(result.termination, "vehicle_managed")

    def test_completed_full_charge_is_not_restarted(self):
        self.check("COMPLETE", target=100, soc=100, charging=False)

    def test_no_start_after_deadline(self):
        self.check("BLOCKED", now=self.ready + timedelta(minutes=1))

    def test_bad_data_rejected(self):
        self.check("UNKNOWN", soc=None)
        with self.assertRaises(ValueError):
            simulate(**(self.args | dict(effective_kw=0)))

    def test_next_deadline(self):
        self.assertEqual(next_deadline(self.now, "06:30"), self.ready)
        self.assertEqual(next_deadline(self.now, "23:30"), self.now + timedelta(minutes=30))


if __name__ == "__main__":
    unittest.main()
