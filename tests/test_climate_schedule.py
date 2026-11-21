"""Seven independent climate schedule regression checks, without HA imports."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

path = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate/climate_schedule.py"
spec = importlib.util.spec_from_file_location("climate_schedule_test", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ClimateScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 21, 20, tzinfo=ZoneInfo("Australia/Brisbane"))

    def test_initially_disabled(self):
        self.assertIsNone(module.next_event(self.now, {}))
        self.assertFalse(module.get_slot({}, 1)["enabled"])

    def test_two_slots_same_day_and_independent_settings(self):
        o = {}
        for slot, hour in ((1, "07:30"), (2, "08:00")):
            for field, value in (("enabled", True), ("day", "Sunday"),
                                 ("ready_time", hour)):
                o = module.update_slot(o, slot, field, value)
        o = module.update_slot(o, 1, "driver_seat", "Vent High")
        o = module.update_slot(o, 2, "temperature", 23.5)
        self.assertEqual(module.get_slot(o, 1)["driver_seat"], "Vent High")
        self.assertEqual(module.get_slot(o, 2)["driver_seat"], "Off")
        self.assertEqual(module.next_event(self.now, o)["slot"], 1)
        self.assertEqual(module.next_event(self.now, o)["start_at"].hour, 7)
        self.assertEqual(module.next_event(self.now, o)["start_at"].minute, 18)

    def test_cross_midnight_lead_time(self):
        o = module.update_slot({}, 3, "enabled", True)
        o = module.update_slot(o, 3, "day", "Sunday")
        o = module.update_slot(o, 3, "ready_time", "00:15")
        o = module.update_slot(o, 3, "lead_minutes", 30)
        event = module.next_event(self.now, o)
        self.assertEqual(event["start_at"].weekday(), 5)
        self.assertEqual(event["start_at"].strftime("%H:%M"), "23:45")

    def test_weekly_rollover(self):
        o = module.update_slot({}, 1, "enabled", True)
        o = module.update_slot(o, 1, "day", "Saturday")
        o = module.update_slot(o, 1, "ready_time", "06:00")
        event = module.next_event(self.now, o)
        self.assertEqual(event["ready_by"].date(), (self.now + timedelta(days=7)).date())

    def test_validation(self):
        for field, value in (("ready_time", "25:00"), ("temperature", 22.25),
                             ("lead_minutes", 125), ("day", "Funday"),
                             ("enabled", "on"), ("driver_seat", "Vent Extreme")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.update_slot({}, 1, field, value)

    def test_no_vehicle_commands(self):
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("hass.services", source)
        self.assertNotIn("geely_connect", source)
        self.assertNotIn("speed", source)


if __name__ == "__main__":
    unittest.main()
