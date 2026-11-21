"""Check charging windows and authorisation without importing Home Assistant."""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import unittest
import types

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
pkg = types.ModuleType("auth_test_package")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
for name in ("weekly_schedule", "authorization"):
    spec = importlib.util.spec_from_file_location(
        f"auth_test_package.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

auth = sys.modules["auth_test_package.authorization"]


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 22, 23, tzinfo=ZoneInfo("Australia/Brisbane"))
        self.schedule = {"monday": {"enabled": True, "target": 80, "ready_time": "07:00"}}
        self.params = dict(
            now=self.now, schedule=self.schedule, soc=60, charging=False,
            at_home=True, plugged=True,
        )

    def test_next_morning_charging_window(self):
        d = auth.decide(**(self.params | {"now": self.now + timedelta(hours=6)}))
        self.assertEqual(d.action, "START")
        self.assertEqual(d.target, 80)
        self.assertEqual(d.day, "monday")

    def test_3am_tuesday_deadline_authorises_monday_evening(self):
        # Charging 20% -> 80% needs around 6h 19m at 6.5 kW,
        # so Monday evening belongs to Tuesday's 03:00 ready-by schedule.
        schedule = {"tuesday": {"enabled": True, "target": 80, "ready_time": "03:00"}}
        monday_evening = datetime(2026, 11, 23, 22, tzinfo=ZoneInfo("Australia/Brisbane"))
        decision = auth.decide(**(self.params | {
            "now": monday_evening, "soc": 20, "schedule": schedule,
        }))
        self.assertEqual(decision.action, "START")
        self.assertEqual(decision.day, "tuesday")
        self.assertEqual(decision.ready_by, datetime(
            2026, 11, 24, 3, tzinfo=ZoneInfo("Australia/Brisbane")))
        self.assertEqual(decision.start_at.date(), monday_evening.date())

    def test_10pm_ready_time_allows_same_day_start(self):
        schedule = {"wednesday": {"enabled": True, "target": 80, "ready_time": "22:00"}}
        tz = ZoneInfo("Australia/Brisbane")
        before = auth.decide(**(self.params | {
            "now": datetime(2026, 11, 25, 17, tzinfo=tz),
            "soc": 60, "schedule": schedule,
        }))
        during = auth.decide(**(self.params | {
            "now": datetime(2026, 11, 25, 20, tzinfo=tz),
            "soc": 60, "schedule": schedule,
        }))
        self.assertEqual(before.action, "WAIT")
        self.assertEqual(during.action, "START")
        self.assertEqual(during.day, "wednesday")
        self.assertEqual(during.start_at.date(), during.ready_by.date())

    def test_completed_target_does_not_restart_within_window(self):
        schedule = {"wednesday": {"enabled": True, "target": 80, "ready_time": "22:00"}}
        decision = auth.decide(**(self.params | {
            "now": datetime(2026, 11, 25, 20, tzinfo=ZoneInfo("Australia/Brisbane")),
            "soc": 80, "charging": False, "schedule": schedule,
        }))
        self.assertNotEqual(decision.action, "START")

    def test_unauthorised_charge_outside_window(self):
        d = auth.decide(**(self.params | {"charging": True}))
        self.assertEqual(d.action, "STOP")
        self.assertIn("Unexpected charging", d.reason)

    def test_100_percent_does_not_stop_at_target(self):
        schedule = {"monday": {"enabled": True, "target": 100, "ready_time": "07:00"}}
        d = auth.decide(**(self.params | dict(
            schedule=schedule, soc=100, charging=True,
            now=self.now + timedelta(hours=7))))
        self.assertNotEqual(d.action, "STOP")
        # At target, no additional START requests are issued.
        waiting = auth.decide(**(self.params | dict(
            schedule=schedule, soc=100, charging=False,
            now=self.now + timedelta(hours=7))))
        self.assertNotEqual(waiting.action, "START")

    def test_never_control_public_or_unverified_home(self):
        for extra in (
            {"at_home": None}, {"at_home": False}, {"plugged": None},
            {"public_mode": True}, {"emergency": True},
            {"legacy_clear": False}, {"soc": None},
        ):
            with self.subTest(extra=extra):
                d = auth.decide(**(self.params | extra | {"charging": True}))
                self.assertNotIn(d.action, ("START", "STOP"))

    def test_manually_owned_charge_takes_precedence(self):
        d = auth.decide(**(self.params | {"manual_owned": True, "charging": True}))
        self.assertEqual(d.action, "AUTHORISED")

    def test_no_schedule_does_not_start(self):
        d = auth.decide(**(self.params | {"schedule": {}}))
        self.assertEqual(d.action, "WAIT")


if __name__ == "__main__":
    unittest.main()
