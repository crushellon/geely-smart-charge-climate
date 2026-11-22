"""Exercise real scheduled climate state machine without Home Assistant imports."""
import ast
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import types
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
pkg = types.ModuleType("climate_runtime_test_package")
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg
for name in ("weekly_schedule", "climate_schedule", "charge_climate",
             "comfort", "comfort_display", "climate_windows"):
    spec = importlib.util.spec_from_file_location(
        f"{pkg.__name__}.{name}", ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
win = sys.modules[f"{pkg.__name__}.climate_windows"]
slots = sys.modules[f"{pkg.__name__}.climate_schedule"]
linked = sys.modules[f"{pkg.__name__}.charge_climate"]
comfort = sys.modules[f"{pkg.__name__}.comfort"]
comfort_display = sys.modules[f"{pkg.__name__}.comfort_display"]

clock = {"now": datetime(2026, 11, 21, 23, 50,
                         tzinfo=ZoneInfo("Australia/Brisbane"))}
alarm_events = []

def schedule_exact(hass, callback, deadline):
    alarm = {"callback": callback, "at": deadline, "cancelled": False}
    alarm_events.append(alarm)
    def unsubscribe():
        alarm["cancelled"] = True
    return unsubscribe
tree = ast.parse((ROOT / "scheduled_climate.py").read_text())
cls = next(x for x in tree.body if isinstance(x, ast.ClassDef)
           and x.name == "ScheduledClimateController")
env = {"asyncio": asyncio, "datetime": datetime, "timedelta": timedelta,
       "dt_util": SimpleNamespace(now=lambda: clock["now"]),
       "candidate_windows": win.candidate_windows,
       "MANUAL_COMFORT_MAX": timedelta(minutes=30),
       "MANUAL_OFF_RETRY": timedelta(seconds=60),
       "MANUAL_OFF_MAX_ATTEMPTS": 3,
       "async_track_point_in_time": schedule_exact}
exec(compile(ast.Module(body=[cls], type_ignores=[]), "scheduled_climate.py", "exec"), env)
Controller = env["ScheduledClimateController"]


class FakeCabin:
    def __init__(self):
        self.calls = []
        self.succeed = True
        self.manual_off_succeeds = True

    async def apply(self, action):
        self.calls.append(("manual_" + action, None))
        return self.manual_off_succeeds

    async def apply_scheduled(self, settings):
        self.calls.append(("on", dict(settings)))
        return self.succeed

    async def stop_scheduled(self):
        self.calls.append(("off", None))
        return True


class ScheduledClimateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        clock["now"] = datetime(2026, 11, 21, 23, 50,
                                 tzinfo=ZoneInfo("Australia/Brisbane"))
        alarm_events.clear()
        self.entry = SimpleNamespace(options={"scheduled_climate_enabled": True})
        self.climate = FakeCabin()
        self.messages = []
        self.manual = SimpleNamespace(
            entry=self.entry, hass=SimpleNamespace(
                async_create_task=asyncio.create_task
            ),
            climate=self.climate,
            _save_options=lambda **vals: self.entry.options.update(vals),
            _raw=lambda entity: "off",
            public_mode=lambda: False,
            _notify=lambda: self.messages.append("changed"),
        )
        self.controller = Controller(self.manual)

    def configure_independent(self):
        o = slots.update_slot(self.entry.options, 1, "enabled", True)
        o = slots.update_slot(o, 1, "day", "Sunday")
        o = slots.update_slot(o, 1, "ready_time", "00:15")
        o = slots.update_slot(o, 1, "lead_minutes", 30)
        o = slots.update_slot(o, 1, "hold_minutes", 10)
        self.entry.options = o

    async def test_simulation_migration_does_not_activate_climate_without_optin(self):
        self.configure_independent()
        self.entry.options["scheduled_climate_enabled"] = False
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "DISABLED")
        self.assertEqual(self.climate.calls, [])
        self.entry.options["scheduled_climate_enabled"] = True
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])

    async def test_disabling_master_while_climate_active_sends_off(self):
        self.configure_independent()
        await self.controller.async_tick()
        self.entry.options["scheduled_climate_enabled"] = False
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "DISABLED")

    async def test_independent_start_once_and_stop_after_hold(self):
        self.configure_independent()
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "RUNNING")
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        self.assertTrue(self.entry.options["scheduled_climate_session"]["active"])
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        clock["now"] += timedelta(minutes=36)
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])
        self.assertIsNone(self.controller.active)
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])

    async def test_ha_restart_does_not_duplicate_climate_start(self):
        self.configure_independent()
        await self.controller.async_tick()
        restarted = Controller(self.manual)
        await restarted.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        self.assertEqual(restarted.status, "RUNNING")
        clock["now"] += timedelta(minutes=36)
        await restarted.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])

    async def test_manual_priority_suppresses_same_appointment(self):
        self.configure_independent()
        await self.controller.async_tick()
        await self.controller.async_manual_override("Cool")
        self.assertTrue(self.controller.manual_override)
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        await self.controller.async_manual_override("off")
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        self.assertFalse(self.controller.manual_override)

    async def test_manual_comfort_auto_off_at_30_minutes_and_unlocks_schedules(self):
        start = clock["now"]
        await self.controller.async_manual_override("Cool")
        self.assertTrue(self.controller.manual_override)
        self.assertEqual(
            self.controller.manual_expires_at, start + timedelta(minutes=30)
        )
        self.assertEqual(
            self.entry.options["manual_climate_expires_at"],
            (start + timedelta(minutes=30)).isoformat()
        )
        self.assertEqual(len(alarm_events), 1)
        self.assertEqual(alarm_events[-1]["at"], start + timedelta(minutes=30))

        clock["now"] = start + timedelta(minutes=29, seconds=59)
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [])
        self.assertTrue(self.controller.manual_override)

        clock["now"] = start + timedelta(minutes=30)
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])
        self.assertFalse(self.controller.manual_override)
        self.assertIsNone(self.controller.manual_expires_at)
        self.assertFalse(self.entry.options["manual_climate_override"])
        self.assertIsNone(self.entry.options["manual_climate_expires_at"])
        self.assertIn("automatically switched OFF", self.controller.message)

        # Without another ON press, no repeated cloud OFF commands.
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])

    async def test_real_deadline_callback_executes_without_waiting_for_periodic_tick(self):
        await self.controller.async_manual_override("Cool")
        alarm = alarm_events[-1]
        clock["now"] = alarm["at"]
        alarm["callback"](clock["now"])
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(self.climate.calls, [("manual_off", None)])
        self.assertFalse(self.controller.manual_override)
        self.assertIsNone(self.controller.manual_expires_at)

    async def test_each_manual_press_resets_the_30_minute_timer(self):
        start = clock["now"]
        await self.controller.async_manual_override("Cool")
        first = alarm_events[-1]
        clock["now"] += timedelta(minutes=20)
        await self.controller.async_manual_override("Warm")
        self.assertTrue(first["cancelled"])
        self.assertEqual(
            self.controller.manual_expires_at, clock["now"] + timedelta(minutes=30)
        )
        clock["now"] = start + timedelta(minutes=30)
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [])
        clock["now"] = start + timedelta(minutes=50)
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])

    async def test_custom_temperature_button_also_expires_after_30_minutes(self):
        start = clock["now"]
        await self.controller.async_manual_override("custom")
        self.assertTrue(self.controller.manual_override)
        self.assertEqual(
            self.controller.manual_expires_at,
            start + timedelta(minutes=30)
        )
        clock["now"] += timedelta(minutes=30)
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])

    async def test_explicit_manual_off_cancels_timer_and_override(self):
        await self.controller.async_manual_override("Warm")
        current_alarm = alarm_events[-1]
        await self.controller.async_manual_override("off")
        self.assertTrue(current_alarm["cancelled"])
        self.assertFalse(self.controller.manual_override)
        self.assertIsNone(self.controller.manual_expires_at)
        clock["now"] += timedelta(minutes=31)
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [])

    async def test_restart_recovers_original_deadline_without_extending_it(self):
        start = clock["now"]
        await self.controller.async_manual_override("Cool")
        old_deadline = self.controller.manual_expires_at
        await self.controller.async_shutdown()
        self.assertTrue(alarm_events[-1]["cancelled"])
        clock["now"] += timedelta(minutes=12)
        restarted = Controller(self.manual)
        await restarted.async_tick()
        self.assertEqual(restarted.status, "MANUAL")
        self.assertEqual(restarted.manual_expires_at, old_deadline)
        clock["now"] = start + timedelta(minutes=30)
        await restarted.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])
        self.assertFalse(restarted.manual_override)

    async def test_restart_after_expiry_sends_off_immediately(self):
        await self.controller.async_manual_override("Warm")
        clock["now"] += timedelta(minutes=38) # HA was down after expiry.
        recovered = Controller(self.manual)
        await recovered.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])
        self.assertFalse(recovered.manual_override)

    async def test_legacy_stuck_manual_override_expires_on_upgrade(self):
        self.entry.options["manual_climate_override"] = True
        self.entry.options.pop("manual_climate_expires_at", None)
        restored = Controller(self.manual)
        await restored.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])
        self.assertFalse(restored.manual_override)

    async def test_failed_off_retries_three_times_then_unblocks_with_error(self):
        self.climate.manual_off_succeeds = False
        await self.controller.async_manual_override("Cool")
        clock["now"] += timedelta(minutes=30)
        await self.controller.async_tick()
        self.assertTrue(self.controller.manual_override)
        self.assertEqual(self.controller.status, "ERROR")
        self.assertEqual(len(self.climate.calls), 1)
        clock["now"] += timedelta(seconds=59)
        await self.controller.async_tick()
        self.assertEqual(len(self.climate.calls), 1)
        clock["now"] += timedelta(seconds=1)
        await self.controller.async_tick()
        self.assertEqual(len(self.climate.calls), 2)
        clock["now"] += timedelta(seconds=60)
        await self.controller.async_tick()
        self.assertEqual(len(self.climate.calls), 3)
        self.assertFalse(self.controller.manual_override)
        self.assertIn("failed three times", self.controller.message)
        self.assertIn("inspect Geely", self.controller.message)
        self.assertFalse(self.entry.options["manual_climate_override"])

    async def test_unconfirmed_manual_on_keeps_auto_off_to_prevent_delayed_cloud_start(self):
        await self.controller.async_manual_override("Cool")
        deadline = self.controller.manual_expires_at
        await self.controller.async_manual_result("Cool", False)
        self.assertTrue(self.controller.manual_override)
        self.assertEqual(self.controller.manual_expires_at, deadline)
        self.assertEqual(self.controller.status, "ERROR")
        self.assertIn("OFF remains armed", self.controller.message)
        # The Geely command may take effect even after its API call errors.
        # An OFF still goes out at the original 30-minute deadline.
        clock["now"] = deadline
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [("manual_off", None)])
        self.assertFalse(self.controller.manual_override)

    async def test_normal_future_schedules_continue_after_manual_expiry(self):
        start = clock["now"]
        await self.controller.async_manual_override("Cool")
        clock["now"] += timedelta(minutes=30)
        await self.controller.async_tick()
        self.assertFalse(self.controller.manual_override)
        # A different, later appointment is allowed to activate.
        options = slots.update_slot(self.entry.options, 2, "enabled", True)
        options = slots.update_slot(options, 2, "day", "Sunday")
        options = slots.update_slot(options, 2, "ready_time", "00:25")
        self.entry.options = options
        await self.controller.async_tick()
        self.assertEqual(
            [x[0] for x in self.climate.calls],
            ["manual_off", "on"]
        )

    async def test_linked_charge_preconditioning_runs_even_when_not_actively_charging(self):
        clock["now"] = datetime(2026, 11, 23, 6, 55,
                                 tzinfo=ZoneInfo("Australia/Brisbane"))
        o = {"scheduled_climate_enabled": False,
             "automatic_charging_enabled": True, "weekly_schedule": {
            "monday": {"enabled": True, "target": 80, "ready_time": "07:00"},
        }}
        self.entry.options = linked.set_value(o, "monday", "enabled", True)
        self.entry.options = linked.set_value(
            self.entry.options, "monday", "profile", "Warm")
        await self.controller.async_tick()
        self.assertEqual(self.controller.active["kind"], "linked")
        self.assertEqual(self.climate.calls[0][1]["temperature"], 24)
        # Changing the profile while active should take effect after cooldown.
        self.entry.options = linked.set_value(
            self.entry.options, "monday", "profile", "Cool")
        clock["now"] += timedelta(seconds=62)
        await self.controller.async_tick()
        self.assertEqual(len(self.climate.calls), 2)
        self.assertEqual(self.climate.calls[1][1]["temperature"], 20)

    async def test_monday_cool_runs_0640_to_0730_without_independent_master(self):
        # User's actual configuration: Monday 07:00 car-ready deadline,
        # linked Cool ON, 20-minute lead, 30-minute hold, independent OFF.
        clock["now"] = datetime(2026, 11, 23, 6, 39,
                                 tzinfo=ZoneInfo("Australia/Brisbane"))
        opts = {
            "scheduled_climate_enabled": False,
            "automatic_charging_enabled": True,
            "weekly_schedule": {"monday": {
                "enabled": True, "target": 100, "ready_time": "07:00"
            }},
        }
        opts = linked.set_value(opts, "monday", "enabled", True)
        opts = linked.set_value(opts, "monday", "profile", "Cool")
        opts = linked.set_timing(opts, "lead_minutes", 20)
        opts = linked.set_timing(opts, "hold_minutes", 30)
        opts = comfort.set_value(opts, "cool", "temperature", 16)
        opts = comfort_display.set_seat_mode(opts, "cool", "driver", "Vent High")
        opts = comfort_display.set_seat_mode(opts, "cool", "passenger", "Vent High")
        self.entry.options = opts
        await self.controller.async_tick()
        self.assertEqual(self.climate.calls, [])
        clock["now"] += timedelta(minutes=1)
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "RUNNING")
        self.assertEqual(self.controller.active["kind"], "linked")
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        self.assertEqual(self.climate.calls[0][1]["temperature"], 16)
        self.assertEqual(self.climate.calls[0][1]["driver_seat"], "Vent High")
        self.assertEqual(self.climate.calls[0][1]["passenger_seat"], "Vent High")
        clock["now"] = datetime(2026, 11, 23, 7, 29,
                                tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])
        clock["now"] += timedelta(minutes=1)
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])

    async def test_independent_remains_disabled_while_linked_comfort_works(self):
        clock["now"] = datetime(2026, 11, 23, 6, 55,
                                 tzinfo=ZoneInfo("Australia/Brisbane"))
        opts = {
            "scheduled_climate_enabled": False,
            "automatic_charging_enabled": True,
            "weekly_schedule": {"monday": {
                "enabled": True, "target": 80, "ready_time": "07:00"
            }},
        }
        opts = linked.set_value(opts, "monday", "enabled", True)
        opts = slots.update_slot(opts, 1, "enabled", True)
        opts = slots.update_slot(opts, 1, "day", "Monday")
        opts = slots.update_slot(opts, 1, "ready_time", "07:00")
        self.entry.options = opts
        await self.controller.async_tick()
        self.assertEqual(self.controller.active["kind"], "linked")
        self.assertTrue(self.controller.active["key"].startswith("linked:"))
        self.assertEqual(len(self.climate.calls), 1)

    async def test_linked_comfort_waiting_does_not_claim_disabled(self):
        clock["now"] = datetime(2026, 11, 23, 3, 0,
                                 tzinfo=ZoneInfo("Australia/Brisbane"))
        opts = {
            "scheduled_climate_enabled": False,
            "automatic_charging_enabled": True,
            "weekly_schedule": {"monday": {
                "enabled": True, "target": 100, "ready_time": "07:00"
            }},
        }
        self.entry.options = linked.set_value(opts, "monday", "enabled", True)
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "WAITING")
        self.assertIn("awaiting charging-linked comfort", self.controller.message)
        self.assertEqual(self.climate.calls, [])

    async def test_disabling_active_schedule_stops_cabin(self):
        self.configure_independent()
        await self.controller.async_tick()
        self.entry.options = slots.update_slot(
            self.entry.options, 1, "enabled", False)
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])

    async def test_emergency_stops_scheduled_climate_and_prevents_new(self):
        self.configure_independent()
        await self.controller.async_tick()
        self.entry.options["emergency_stop"] = True
        await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on", "off"])
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "BLOCKED")

    async def test_command_error_does_not_spam_start_requests(self):
        self.configure_independent()
        self.climate.succeed = False
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "ERROR")
        for _ in range(3):
            await self.controller.async_tick()
        self.assertEqual([x[0] for x in self.climate.calls], ["on"])


if __name__ == "__main__":
    unittest.main()
