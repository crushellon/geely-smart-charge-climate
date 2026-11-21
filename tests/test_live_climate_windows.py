"""Live climate windows are tied to ready-by calendar dates (not nights)."""
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
import sys
import types
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
pkg = types.ModuleType("live_climate_window_test")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
for name in ("weekly_schedule", "climate_schedule", "charge_climate",
             "comfort", "comfort_display", "climate_windows"):
    spec = importlib.util.spec_from_file_location(
        f"{pkg.__name__}.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
window = sys.modules[f"{pkg.__name__}.climate_windows"]
slots = sys.modules[f"{pkg.__name__}.climate_schedule"]
linked = sys.modules[f"{pkg.__name__}.charge_climate"]
comfort = sys.modules[f"{pkg.__name__}.comfort"]
tz = ZoneInfo("Australia/Brisbane")


class LiveClimateWindowTests(unittest.TestCase):
    def test_independent_schedule_starts_previous_calendar_day(self):
        opts = slots.update_slot({}, 1, "enabled", True)
        opts = slots.update_slot(opts, 1, "day", "Sunday")
        opts = slots.update_slot(opts, 1, "ready_time", "00:15")
        opts = slots.update_slot(opts, 1, "lead_minutes", 30)
        opts = slots.update_slot(opts, 1, "hold_minutes", 10)
        start = datetime(2026, 11, 21, 23, 50, tzinfo=tz)
        active = window.candidate_windows(start, opts)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["slot"], 1)
        self.assertEqual(active[0]["start_at"].strftime("%H:%M"), "23:45")
        self.assertEqual(active[0]["ready_by"].date().isoformat(), "2026-11-22")
        self.assertEqual(active[0]["end_at"].strftime("%H:%M"), "00:25")
        self.assertFalse(window.candidate_windows(
            datetime(2026, 11, 22, 0, 25, tzinfo=tz), opts
        ))

    def test_independent_runs_without_auto_charging_or_plug(self):
        opts = slots.update_slot({}, 4, "enabled", True)
        opts = slots.update_slot(opts, 4, "day", "Monday")
        opts = slots.update_slot(opts, 4, "ready_time", "07:00")
        self.assertEqual(
            window.candidate_windows(
                datetime(2026, 11, 23, 6, 55, tzinfo=tz), opts
            )[0]["kind"],
            "independent",
        )

    def test_linked_requires_enabled_schedule_and_saved_automatic_preference(self):
        now = datetime(2026, 11, 23, 6, 55, tzinfo=tz)
        o = {"weekly_schedule": {
            "monday": {"enabled": True, "target": 80, "ready_time": "07:00"}
        }, "automatic_charging_enabled": True}
        o = linked.set_value(o, "monday", "enabled", True)
        o = linked.set_value(o, "monday", "profile", "Warm")
        o = comfort.set_value(o, "warm", "temperature", 24.5)
        self.assertEqual(window.candidate_windows(now, o)[0]["kind"], "linked")
        self.assertEqual(window.candidate_windows(now, o)[0]["temperature"], 24.5)
        self.assertEqual(window.candidate_windows(now, o)[0]["ready_by"].weekday(), 0)
        self.assertEqual(window.candidate_windows(now, {
            **o, "automatic_charging_enabled": False
        }), [])
        self.assertEqual(window.candidate_windows(now, {
            **o, "public_charging_mode": True
        }), [])
        o["weekly_schedule"]["monday"]["enabled"] = False
        self.assertEqual(window.candidate_windows(now, o), [])

    def test_independent_takes_priority_over_linked_same_clock(self):
        now = datetime(2026, 11, 23, 6, 55, tzinfo=tz)
        o = {"weekly_schedule": {
            "monday": {"enabled": True, "target": 80, "ready_time": "07:00"}
        }, "automatic_charging_enabled": True}
        o = linked.set_value(o, "monday", "enabled", True)
        o = slots.update_slot(o, 2, "enabled", True)
        o = slots.update_slot(o, 2, "day", "Monday")
        o = slots.update_slot(o, 2, "ready_time", "07:00")
        windows = window.candidate_windows(now, o)
        self.assertEqual([w["kind"] for w in windows],
                         ["independent", "linked"])

    def test_timezone_aware_only(self):
        with self.assertRaises(ValueError):
            window.candidate_windows(datetime(2026, 11, 23, 6), {})


if __name__ == "__main__":
    unittest.main()
