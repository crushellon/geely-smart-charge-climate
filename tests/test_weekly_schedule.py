"""Pure seven-day schedule tests; no Home Assistant dependency."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

p = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate/weekly_schedule.py"
spec = importlib.util.spec_from_file_location("weekly_schedule_test", p)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class WeeklyScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo("Australia/Brisbane")
        self.now = datetime(2026, 11, 21, 23, 0, tzinfo=self.tz)  # Saturday
        self.schedule = module.default_schedule()

    def test_all_days_start_disabled(self):
        self.assertIsNone(module.next_charge(self.now, self.schedule))
        self.assertTrue(all(not item["enabled"] for item in self.schedule.values()))

    def test_sunday_morning_uses_next_calendar_day(self):
        self.schedule["sunday"] = {"enabled": True, "target": 100, "ready_time": "06:30"}
        next_day = module.next_charge(self.now, self.schedule)
        self.assertEqual(next_day.day, "sunday")
        self.assertEqual(next_day.target, 100)
        self.assertEqual(next_day.ready_by, datetime(2026, 11, 22, 6, 30, tzinfo=self.tz))

    def test_shift_worker_3am_deadline_belongs_to_tuesday(self):
        now = datetime(2026, 11, 23, 21, tzinfo=self.tz)  # Monday evening
        self.schedule["tuesday"] = {"enabled": True, "target": 80, "ready_time": "03:00"}
        event = module.next_charge(now, self.schedule)
        self.assertEqual(event.day, "tuesday")
        self.assertEqual(event.ready_by, datetime(2026, 11, 24, 3, tzinfo=self.tz))

    def test_evening_deadline_stays_on_same_calendar_day(self):
        now = datetime(2026, 11, 25, 16, tzinfo=self.tz)  # Wednesday afternoon
        self.schedule["wednesday"] = {"enabled": True, "target": 80, "ready_time": "22:00"}
        event = module.next_charge(now, self.schedule)
        self.assertEqual(event.day, "wednesday")
        self.assertEqual(event.ready_by, datetime(2026, 11, 25, 22, tzinfo=self.tz))

    def test_past_deadline_rolls_to_next_week(self):
        self.schedule["saturday"] = {"enabled": True, "target": 80, "ready_time": "06:30"}
        deadline = module.next_charge(self.now, self.schedule).ready_by
        self.assertEqual(deadline, datetime(2026, 11, 28, 6, 30, tzinfo=self.tz))

    def test_closest_schedule_wins(self):
        self.schedule["monday"] = {"enabled": True, "target": 80, "ready_time": "06:30"}
        self.schedule["sunday"] = {"enabled": True, "target": 100, "ready_time": "06:30"}
        self.assertEqual(module.next_charge(self.now, self.schedule).day, "sunday")

    def test_validates_time_and_target(self):
        for bad in [{"enabled": True, "target": 110},
                    {"enabled": True, "ready_time": "25:00"},
                    {"enabled": "on"}, {"enabled": True, "ready_time": "06:99"}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                module.validate_day(bad)

    def test_100_percent_accepted(self):
        self.assertEqual(module.validate_day({"enabled": True, "target": 100, "ready_time": "06:30"})["target"], 100)


if __name__ == "__main__":
    unittest.main()
