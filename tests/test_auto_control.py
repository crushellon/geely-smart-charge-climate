"""Fake-HA checks for real guarded automatic charging controller behavior."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import importlib.util
import sys
import unittest
import types

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
package = types.ModuleType("auto_test_package")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
for name in ("weekly_schedule", "authorization", "live_safety"):
    spec = importlib.util.spec_from_file_location(
        f"auto_test_package.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
policy = sys.modules["auto_test_package.authorization"]
safety = sys.modules["auto_test_package.live_safety"]
now = datetime(2026, 11, 23, 6, tzinfo=ZoneInfo("Australia/Brisbane"))
logs = []
env = {
    "asyncio": asyncio, "timedelta": timedelta, "isfinite": isfinite,
    "dt_util": SimpleNamespace(now=lambda: now,
                               utcnow=lambda: datetime.now(timezone.utc)),
    "persistent_notification": SimpleNamespace(
        async_create=lambda *a, **kw: logs.append((a, kw))),
    "decide": policy.decide, "charge_start_at": policy.charge_start_at,
    "ChargeDecision": policy.ChargeDecision,
    "validate_day": sys.modules["auto_test_package.weekly_schedule"].validate_day,
    "start_preflight": safety.start_preflight,
    "LEGACY_CONTROLLER": safety.LEGACY_CONTROLLER,
    "LEGACY_ACTIVE": safety.LEGACY_ACTIVE,
    "OLD_FULL_CHARGE": safety.OLD_FULL_CHARGE,
    "PUBLIC_MODE": safety.PUBLIC_MODE,
    "EMERGENCY_STOP": safety.EMERGENCY_STOP,
    "DEFAULT_EFFECTIVE_KW": 6.5,
    "DOMAIN": "geely_smart_charge_climate",
    "er": SimpleNamespace(async_get=lambda hass: SimpleNamespace(
        async_get_entity_id=lambda *a: None)),
    "DEFAULT_USABLE_CAPACITY_KWH": 68.39,
    "MODES": ("Off", "Monitor", "Active"),
    "INTERLOCKS": (safety.LEGACY_CONTROLLER, safety.LEGACY_ACTIVE,
                   safety.OLD_FULL_CHARGE, safety.PUBLIC_MODE,
                   safety.EMERGENCY_STOP),
    "UNEXPECTED_GRACE": timedelta(seconds=30),
    "STOP_RETRY": timedelta(seconds=30),
    "_LOGGER": SimpleNamespace(exception=lambda *a: None),
}
tree = ast.parse((ROOT / "auto_control.py").read_text(encoding="utf-8"))
cls = next(x for x in tree.body if isinstance(x, ast.ClassDef)
           and x.name == "AutomaticChargeController")
exec(compile(ast.Module(body=[cls], type_ignores=[]), "auto_control.py", "exec"), env)
Auto = env["AutomaticChargeController"]


class FakeServices:
    def __init__(self, values):
        self.values = values
        self.calls = []

    async def async_call(self, domain, action, data, blocking):
        self.calls.append(action)
        self.values["switch.car"] = "on" if action == "turn_on" else "off"
        self.values["sensor.power"] = "6.5" if action == "turn_on" else "0"


class AutoControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.values = {
            "sensor.battery": "60",
            "switch.car": "off", "sensor.power": "0",
            "binary_sensor.plug": "on",
            **{key: "off" for key in env["INTERLOCKS"]},
        }
        self.services = FakeServices(self.values)
        self.hass = SimpleNamespace(
            states=SimpleNamespace(
                get=lambda entity: SimpleNamespace(state=self.values[entity])
                if entity in self.values else None),
            services=self.services,
            bus=SimpleNamespace(async_fire=lambda *a: None),
        )
        self.entry = SimpleNamespace(entry_id="abc", options={
            "weekly_schedule": {
                "monday": {"enabled": True, "target": 80, "ready_time": "07:00"},
            }
        })
        self.manual = SimpleNamespace(
            hass=self.hass, entry=self.entry,
            battery="sensor.battery", charging_switch="switch.car",
            charging_power="sensor.power", plug="binary_sensor.plug",
            armed=False, owned=False,
            _raw=lambda key: self.values.get(key),
            _notify=lambda: None,
        )
        self.auto = Auto(self.manual)

    async def test_default_off_no_commands(self):
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.mode, "Off")

    async def test_monitor_decides_without_acting(self):
        await self.auto.async_set_mode("Monitor")
        self.assertEqual(self.auto.decision.action, "START")
        self.assertEqual(self.services.calls, [])

    async def test_monitor_recalculates_after_weekly_schedule_edited(self):
        self.entry.options["weekly_schedule"] = {}
        await self.auto.async_set_mode("Monitor")
        self.assertEqual(self.auto.decision.reason, "No charging schedule enabled")
        self.entry.options["weekly_schedule"] = {
            "monday": {"enabled": True, "target": 100, "ready_time": "08:00"},
        }
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "MONITORING")
        self.assertIn(self.auto.decision.action, ("WAIT", "START"))
        self.assertEqual(self.auto.decision.day, "monday")
        self.assertEqual(self.auto.decision.target, 100)
        self.assertNotEqual(self.auto.decision.reason, "No charging schedule enabled")
        self.assertEqual(self.services.calls, [])

    async def test_active_starts_and_stops_at_80(self):
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertTrue(self.auto.owned)
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertFalse(self.auto.owned)

    async def test_editing_live_100_target_to_current_soc_stops_and_updates_decision(self):
        # Regression: user's active 100% charge continued after changing
        # Saturday's slider to the currently reported 78%.
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertEqual(self.auto.owned_target, 100)
        self.values["sensor.battery"] = "78"
        self.entry.options["weekly_schedule"]["monday"]["target"] = 78
        await self.auto.async_tick()  # Immediate schedule-change listener
        self.assertEqual(self.auto.decision.target, 78)
        self.assertEqual(self.auto.owned_target, 78)
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])

    async def test_editing_live_target_above_soc_refreshes_display_then_stops(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        # This edited 1% top-up is already inside its charging window:
        # 7 minutes of energy plus 15-minute buffer before 06:20.
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "06:20"
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "78"
        self.entry.options["weekly_schedule"]["monday"]["target"] = 79
        await self.auto.async_tick()
        self.assertEqual(self.auto.decision.target, 79)
        self.assertEqual(self.auto.owned_target, 79)
        self.assertEqual(self.auto.status, "CHARGING")
        self.assertIn("79%", self.auto.message)
        self.assertEqual(self.services.calls, ["turn_on"])
        self.values["sensor.battery"] = "79"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])

    async def test_reduce_live_100_to_two_percent_defers_until_new_start(self):
        # Actual user report: 100% required an immediate start, but after
        # reducing the target to a 2% top-up the computed start moves later.
        self.entry.options["weekly_schedule"]["monday"] = {
            "enabled": True, "target": 100, "ready_time": "07:00",
        }
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertTrue(self.auto.owned)
        self.entry.options["weekly_schedule"]["monday"]["target"] = 62
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.auto.decision.target, 62)
        self.assertEqual(self.auto.decision.action, "WAIT")
        self.assertEqual(self.auto.decision.ready_by.hour, 7)
        self.assertGreater(self.auto.decision.start_at, now)
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertEqual(self.auto.finished_deadlines[
            ("monday", "2026-11-23")]["outcome"], "deferred")
        # Do not restart until the new calculated charging window opens.
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "WAITING")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        earlier_clock = env["dt_util"].now
        env["dt_util"].now = lambda: datetime(
            2026, 11, 23, 6, 40, tzinfo=ZoneInfo("Australia/Brisbane"))
        self.addCleanup(setattr, env["dt_util"], "now", earlier_clock)
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_on"])
        self.assertTrue(self.auto.owned)
        self.assertEqual(self.auto.owned_target, 62)

    async def test_routine_soc_updates_never_defer_owned_charge(self):
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        # SoC rises but no schedule setting changes. Never oscillate.
        self.values["sensor.battery"] = "79"
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "CHARGING")
        self.assertEqual(self.services.calls, ["turn_on"])

    async def test_edited_time_can_defer_owned_session(self):
        # 60->80 by 07:00 requires starting immediately. With ready by 11:00
        # the new start shifts into the future.
        await self.auto.async_set_mode("Active")
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "11:00"
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertEqual(self.auto.decision.action, "WAIT")
        self.assertEqual(self.auto.decision.ready_by.hour, 11)

    async def test_repeated_ticks_while_deferred_do_not_restart(self):
        await self.auto.async_set_mode("Active")
        self.entry.options["weekly_schedule"]["monday"]["target"] = 62
        await self.auto.async_tick()
        await self.auto.async_tick()
        await self.auto.async_tick()
        for _ in range(5):
            await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertEqual(self.auto.status, "WAITING")

    async def test_editing_live_ready_by_time_updates_decision(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "08:00"
        await self.auto.async_tick()
        self.assertEqual(self.auto.decision.ready_by.hour, 8)
        self.assertEqual(self.auto.owned_deadline.hour, 8)
        self.assertEqual(self.services.calls, ["turn_on"])

    async def test_disabling_live_schedule_stops_its_charge(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        self.entry.options["weekly_schedule"]["monday"]["enabled"] = False
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])

    async def test_changing_target_after_stop_request_does_not_cancel_stop(self):
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])

    async def test_monitor_target_change_notifies_even_when_status_unchanged(self):
        notifications = []
        self.manual._notify = lambda: notifications.append(True)
        await self.auto.async_set_mode("Monitor")
        initial_count = len(notifications)
        self.entry.options["weekly_schedule"]["monday"]["target"] = 85
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "MONITORING")
        self.assertEqual(self.auto.decision.target, 85)
        self.assertGreater(len(notifications), initial_count)
        self.assertEqual(self.services.calls, [])

    async def test_completed_session_is_not_restarted_after_ready_time_edit(self):
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "08:00"
        self.values["sensor.battery"] = "70"  # Simulate stale battery rollback
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])

    async def test_100_is_vehicle_managed(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "100"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on"])
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "COMPLETED")

    async def test_early_geely_stop_is_interrupted_and_does_not_loop(self):
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        await self.auto.async_tick()  # Observe charging ON before a later stop.
        # Geely ends the session at 60%, below the 80% requested target.
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "INTERRUPTED")
        self.assertEqual(self.auto.finished_deadlines[
            ("monday", "2026-11-23")]["outcome"], "interrupted")
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "PAUSED")
        self.assertEqual(self.services.calls, ["turn_on"])
        # Explicitly returning to Active is an attended request to resume.
        await self.auto.async_set_mode("Off")
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on", "turn_on"])
        self.assertEqual(self.auto.owned_target, 80)

    async def test_stopped_below_new_100_target_can_start_again(self):
        # Recreate user journey: reach 79%, stop; update departure to 100%.
        self.entry.options["weekly_schedule"]["monday"]["target"] = 79
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "79"
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertEqual(self.auto.finished_deadlines[
            ("monday", "2026-11-23")]["outcome"], "completed")
        # Merely editing ready-by clock time must not restart target 79%.
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "08:00"
        self.values["sensor.battery"] = "78"  # Stale SoC rollback
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertEqual(self.auto.status, "COMPLETED")
        # Raising target is a new explicit charging request, even on same date.
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_on"])
        self.assertTrue(self.auto.owned)
        self.assertEqual(self.auto.owned_target, 100)

    async def test_manual_mode_cancellation_requires_deliberate_rearm(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertEqual(self.auto.finished_deadlines[
            ("monday", "2026-11-23")]["outcome"], "cancelled")
        # Mode was already Off; merely ticking does not re-start.
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        # Explicitly choosing Active again after stop confirmation re-arms.
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_on"])

    async def test_disabling_and_reenabling_schedule_is_new_request(self):
        await self.auto.async_set_mode("Active")
        self.entry.options["weekly_schedule"]["monday"]["enabled"] = False
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertEqual(self.auto.finished_deadlines[
            ("monday", "2026-11-23")]["outcome"], "disabled")
        self.entry.options["weekly_schedule"]["monday"]["enabled"] = True
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_on"])

    async def test_resume_before_charge_window_rearms_but_waits_until_due(self):
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        # Move ready time further into future so rearm must not START yet.
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "09:00"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.auto.status, "WAITING")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertNotIn(("monday", "2026-11-23"),
                         self.auto.finished_deadlines)
        # Change ready-by closer again: same rearmed request now starts.
        self.entry.options["weekly_schedule"]["monday"]["ready_time"] = "07:00"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_on"])

    async def test_unknown_soc_never_rearms_cancelled_session(self):
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.values["sensor.battery"] = "unavailable"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertIn(("monday", "2026-11-23"), self.auto.finished_deadlines)

    async def test_true_100_completion_does_not_restart_without_new_request(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "100"
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        # First observe active charge, then Geely finishing.
        self.auto.saw_charging = True
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "COMPLETED")
        self.assertEqual(self.auto.finished_deadlines[
            ("monday", "2026-11-23")]["outcome"], "completed")
        self.values["sensor.battery"] = "99"  # Telemetry step-down.
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertEqual(self.auto.status, "COMPLETED")

    async def test_100_survives_graceful_reload(self):
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        await self.auto.async_shutdown()
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertEqual(self.auto.mode, "Off")

    async def test_user_turning_off_auto_stops_its_owned_charge(self):
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertIsNotNone(self.auto.stop_requested_at)

    async def test_guard_detects_and_stops_unexpected_geely_charge(self):
        self.entry.options["weekly_schedule"] = {}
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.auto.status, "CHECKING")
        self.assertEqual(self.services.calls, [])
        self.auto.unexpected_since = datetime.now(timezone.utc) - timedelta(seconds=40)
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_off"])
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertIn("Unauthorised", self.auto.message)

    async def test_geely_only_works_without_charging_power_entity(self):
        self.manual.charging_power = None
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")

    async def test_emergency_stops_unowned_home_charge_immediately(self):
        self.entry.options["weekly_schedule"] = {}
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6"
        self.values[safety.EMERGENCY_STOP] = "on"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_off"])
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")

    async def test_public_mode_prevents_commands(self):
        self.values[safety.PUBLIC_MODE] = "on"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.status, "BLOCKED")

    async def test_native_public_mode_blocks_start(self):
        self.entry.options["public_charging_mode"] = True
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.status, "BLOCKED")

    async def test_native_public_mode_blocks_unexpected_charge_stop(self):
        self.entry.options["weekly_schedule"] = {}
        self.entry.options["public_charging_mode"] = True
        self.values["switch.car"] = "on"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.status, "BLOCKED")

    async def test_public_mode_releases_owned_charge_without_stop(self):
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        self.entry.options["public_charging_mode"] = True
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertFalse(self.auto.owned)
        self.assertEqual(self.auto.status, "BLOCKED")

    async def test_public_mode_cancels_pending_stop_retry(self):
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.entry.options["public_charging_mode"] = True
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertIsNone(self.auto.stop_requested_at)

    async def test_manual_priority(self):
        self.manual.armed = True
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
