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
    "asyncio": asyncio, "datetime": datetime,
    "timedelta": timedelta, "isfinite": isfinite,
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
    # Existing isolated tests focus on logic, not elapsed wall-clock time.
    # Dedicated regression tests below use real settlement time explicitly.
    "STOP_SETTLE": timedelta(0),
    "STOP_WATCH": timedelta(minutes=5),
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
        global now
        now = datetime(2026, 11, 23, 6, tzinfo=ZoneInfo("Australia/Brisbane"))
        self.values = {
            "sensor.battery": "60",
            "switch.car": "off", "sensor.power": "0",
            "binary_sensor.plug": "on",
            **{key: "off" for key in env["INTERLOCKS"]},
        }
        self.services = FakeServices(self.values)
        self.hass = SimpleNamespace(
            states=SimpleNamespace(
                get=lambda entity: SimpleNamespace(
                    state=self.values[entity],
                    last_reported=env["dt_util"].utcnow() + timedelta(milliseconds=1),
                ) if entity in self.values else None),
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

    async def test_80_percent_hard_stop_at_exact_ready_by_even_below_target(self):
        global now
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        # A 9:30 ready-by is the actual end, not up to three hours later.
        now = datetime(2026, 11, 23, 7, tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertIn("ready-by deadline", self.auto.stop_context)
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertFalse(self.auto.owned)
        self.assertEqual(
            self.auto.finished_deadlines[("monday", "2026-11-23")]["outcome"],
            "expired",
        )

    async def test_old_morning_charge_cannot_restart_on_afternoon_plug(self):
        global now
        await self.auto.async_set_mode("Active")
        now = datetime(2026, 11, 23, 7, tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        # Real time has moved past the old STOP's bounded rebound window.
        self.auto.stop_watch_until = env["dt_util"].utcnow() - timedelta(minutes=1)
        now = datetime(2026, 11, 23, 18, 33,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.5"
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "CHECKING")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.auto.unexpected_since = env["dt_util"].utcnow() - timedelta(seconds=40)
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_off"])
        self.assertIn("Unauthorised charging", self.auto.stop_context)

    async def test_100_percent_never_starts_after_missed_deadline(self):
        global now
        self.entry.options["weekly_schedule"]["monday"] = {
            "enabled": True, "target": 100, "ready_time": "09:30"
        }
        now = datetime(2026, 11, 23, 8, tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        # Geely never confirmed real power before 9:30.
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        now = datetime(2026, 11, 23, 9, 30,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertFalse(self.auto.full_overrun_authorized)
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])

    async def test_genuine_100_percent_session_can_balance_past_ready_by(self):
        global now
        self.entry.options["weekly_schedule"]["monday"] = {
            "enabled": True, "target": 100, "ready_time": "09:30"
        }
        self.manual._save_options = lambda **vals: self.entry.options.update(vals)
        now = datetime(2026, 11, 23, 8, tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_set_mode("Active")
        await self.auto.async_tick()  # Positive power BEFORE cutoff
        self.assertTrue(self.auto.full_overrun_authorized)
        self.assertTrue(self.entry.options["automatic_session"][
            "full_overrun_authorized"
        ])
        now = datetime(2026, 11, 23, 10, 0,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        now = datetime(2026, 11, 23, 18, 33,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertTrue(self.auto.owned)
        # But unplugging ends the exception: it cannot be picked up tonight.
        self.values["binary_sensor.plug"] = "off"
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertIn("disconnected after ready-by", self.auto.stop_context)

    async def test_100_can_finish_without_optional_power_sensor(self):
        global now
        self.entry.options["weekly_schedule"]["monday"] = {
            "enabled": True, "target": 100, "ready_time": "09:30"
        }
        self.manual.charging_power = None
        now = datetime(2026, 11, 23, 8,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_set_mode("Active")
        await self.auto.async_tick()
        self.assertTrue(self.auto.full_overrun_authorized)
        now = datetime(2026, 11, 23, 11,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertTrue(self.auto.owned)

    async def test_restore_expired_80_percent_does_not_wait_for_recovery_grace(self):
        global now
        now = datetime(2026, 11, 23, 18, 33,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        self.entry.options["automatic_session"] = {
            "active": True, "day": "monday", "target": 80,
            "deadline": "2026-11-23T09:30:00+10:00",
            "stop_pending": False,
        }
        await self.auto.async_restore()
        self.assertTrue(self.auto.owned)
        await self.auto.async_set_mode("Active", deliberate=False)
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, ["turn_off"])

    async def test_restore_expired_100_without_proof_of_early_power_stops(self):
        global now
        now = datetime(2026, 11, 23, 18, 33,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        self.entry.options["automatic_session"] = {
            "active": True, "day": "monday", "target": 100,
            "deadline": "2026-11-23T09:30:00+10:00",
            "full_overrun_authorized": False,
        }
        await self.auto.async_restore()
        await self.auto.async_set_mode("Active", deliberate=False)
        self.assertEqual(self.services.calls, ["turn_off"])
        self.assertEqual(self.auto.status, "STOP_REQUESTED")

    async def test_new_charge_inside_window_adopted_without_duplicate_start(self):
        global now
        self.values["binary_sensor.plug"] = "off"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.values["binary_sensor.plug"] = "on"
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.5"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, [])
        self.assertTrue(self.auto.owned)
        self.assertEqual(self.auto.owned_target, 80)
        self.assertIn("adopted", self.auto.message)
        now = datetime(2026, 11, 23, 7, 0,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_off"])

    async def test_adopt_already_balancing_100_percent_before_cutoff(self):
        global now
        self.entry.options["weekly_schedule"]["monday"] = {
            "enabled": True, "target": 100, "ready_time": "09:30"
        }
        now = datetime(2026, 11, 23, 9, 15,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        self.values["binary_sensor.plug"] = "off"
        await self.auto.async_set_mode("Active")
        self.values["binary_sensor.plug"] = "on"
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "1.2"
        self.values["sensor.battery"] = "100"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, [])
        self.assertTrue(self.auto.owned)
        self.assertTrue(self.auto.full_overrun_authorized)
        now = datetime(2026, 11, 23, 10, 0,
                       tzinfo=ZoneInfo("Australia/Brisbane"))
        await self.auto.async_tick()
        self.assertTrue(self.auto.owned)
        self.assertEqual(self.services.calls, [])

    async def test_auto_running_session_persists_and_restores_without_second_start(self):
        self.manual._save_options = lambda **vals: self.entry.options.update(vals)
        self.entry.options["automatic_charging_enabled"] = True
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        saved = self.entry.options["automatic_session"]
        self.assertTrue(saved["active"])
        self.assertEqual(saved["target"], 80)
        another = Auto(self.manual)
        await another.async_restore()
        self.assertTrue(another.owned)
        self.assertEqual(another.owned_target, 80)
        await another.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        self.assertEqual(another.mode, "Active")

    async def test_completed_session_persists_across_restart_no_duplicate_start(self):
        self.manual._save_options = lambda **vals: self.entry.options.update(vals)
        await self.auto.async_set_mode("Active")
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertFalse(self.entry.options["automatic_session"]["active"])
        self.assertEqual(self.entry.options["finished_charge_sessions"][
            "monday|2026-11-23"]["outcome"], "completed")
        another = Auto(self.manual)
        self.values["sensor.battery"] = "79"  # Stale cloud rollback
        await another.async_set_mode("Active", deliberate=False)
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertEqual(another.status, "COMPLETED")

    async def test_new_automatic_session_clears_previous_manual_stop_watch(self):
        self.manual.stop_watch_until = datetime.now(timezone.utc) + timedelta(minutes=5)
        await self.auto.async_set_mode("Active")
        self.assertIsNone(self.manual.stop_watch_until)
        self.assertEqual(self.services.calls, ["turn_on"])

    async def test_optional_wallbox_power_never_changes_stop_decision(self):
        await self.auto.async_set_mode("Active")
        # Unrelated charger may still report high idle or stale power.
        self.manual._wallbox_kw = lambda: 6.89
        self.values["sensor.battery"] = "80"
        await self.auto.async_tick()
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")

    async def test_optional_wallbox_cannot_claim_charging_when_geely_is_off(self):
        self.manual._wallbox_kw = lambda: 6.89
        self.assertFalse(self.auto._charging())
        self.assertFalse(self.auto._confirmed_charge_power())
        self.assertFalse(self.auto._stopped())

    async def test_immediate_off_does_not_verify_before_settling(self):
        # Reproduces START -> Off within moments, when cloud feedback is not
        # trustworthy enough to declare a verified physical stop.
        old_utc = env["dt_util"].utcnow
        old_settle = env["STOP_SETTLE"]
        clock = {"time": datetime(2026, 11, 23, 0, tzinfo=timezone.utc)}
        env["dt_util"].utcnow = lambda: clock["time"]
        env["STOP_SETTLE"] = timedelta(seconds=30)
        self.addCleanup(setattr, env["dt_util"], "utcnow", old_utc)
        self.addCleanup(env.__setitem__, "STOP_SETTLE", old_settle)

        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertEqual(self.auto.mode, "Off")
        # Both cloud sensors initially claim Off/0; not enough elapsed time.
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertTrue(self.auto.owned)
        # A delayed Geely start arrives while Off. It must NOT be marked stopped.
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.89"
        clock["time"] += timedelta(seconds=12)
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertTrue(self.auto.owned)
        self.assertEqual(self.auto.off_checks, 0)
        clock["time"] += timedelta(seconds=19)
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off", "turn_off"])
        self.assertEqual(self.auto.status, "STOP_REQUESTED")

    async def test_stale_cloud_readings_cannot_verify_stop(self):
        old_utc = env["dt_util"].utcnow
        old_settle = env["STOP_SETTLE"]
        clock = {"time": datetime(2026, 11, 23, 0, tzinfo=timezone.utc)}
        env["dt_util"].utcnow = lambda: clock["time"]
        env["STOP_SETTLE"] = timedelta(seconds=30)
        self.addCleanup(setattr, env["dt_util"], "utcnow", old_utc)
        self.addCleanup(env.__setitem__, "STOP_SETTLE", old_settle)
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        stale = clock["time"] - timedelta(seconds=20)
        self.hass.states.get = lambda entity: SimpleNamespace(
            state=self.values[entity], last_reported=stale
        ) if entity in self.values else None
        clock["time"] += timedelta(seconds=35)
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertNotEqual(self.auto.status, "STOPPED")
        self.assertIsNotNone(self.auto.stop_requested_at)

    async def test_late_charging_rebound_after_stopped_is_enforced_even_off(self):
        # Even after two legitimate OFF observations, a delayed ON signal
        # during the bounded watchdog must cause a new stop request.
        old_utc = env["dt_util"].utcnow
        old_settle = env["STOP_SETTLE"]
        clock = {"time": datetime(2026, 11, 23, 0, tzinfo=timezone.utc)}
        env["dt_util"].utcnow = lambda: clock["time"]
        env["STOP_SETTLE"] = timedelta(seconds=30)
        self.addCleanup(setattr, env["dt_util"], "utcnow", old_utc)
        self.addCleanup(env.__setitem__, "STOP_SETTLE", old_settle)
        self.entry.options["weekly_schedule"]["monday"]["target"] = 100
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        clock["time"] += timedelta(seconds=31)
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertIsNotNone(self.auto.stop_watch_until)
        self.assertEqual(self.auto.mode, "Off")
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.89"
        clock["time"] += timedelta(seconds=12)
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, [
            "turn_on", "turn_off", "turn_off"
        ])
        self.assertEqual(self.auto.mode, "Off")

    async def test_old_auto_stop_watchdog_never_stops_authorised_manual_charge(self):
        # Real incident: auto verified an earlier stop, then Comfort Cool was
        # pressed after a new manual charge. It was the old auto watchdog
        # (not the climate command) which issued the unwanted charging OFF.
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.assertIsNotNone(self.auto.stop_watch_until)
        # Manual controller has since authorised and started a NEW session.
        self.manual.owned = True
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.89"
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertIsNone(self.auto.stop_watch_until)
        self.assertIsNone(self.auto.stop_requested_at)

    async def test_auto_stop_watchdog_still_catches_unauthorised_rebound(self):
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertIsNotNone(self.auto.stop_watch_until)
        self.manual.owned = False
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.89"
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOP_REQUESTED")
        self.assertEqual(self.services.calls, [
            "turn_on", "turn_off", "turn_off",
        ])

    async def test_public_mode_suppresses_post_stop_watchdog(self):
        await self.auto.async_set_mode("Active")
        await self.auto.async_set_mode("Off")
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "STOPPED")
        self.entry.options["public_charging_mode"] = True
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6.89"
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on", "turn_off"])
        self.assertIsNone(self.auto.stop_watch_until)

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

    async def test_finished_product_resume_rearms_while_auto_already_enabled(self):
        await self.auto.async_set_mode("Active")
        await self.auto.async_tick()
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "INTERRUPTED")
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "PAUSED")
        # No developer Off/Active toggle: production button invokes this.
        await self.auto.async_request_resume()
        self.assertEqual(self.services.calls, ["turn_on", "turn_on"])
        self.assertTrue(self.auto.owned)

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

    async def test_startup_unowned_charge_outside_window_stops_after_grace(self):
        # Even a stale EXTERNAL marker cannot bypass an explicitly active
        # automatic controller. The 30-second debounce still applies.
        self.manual.unmanaged_charge = True
        self.entry.options["weekly_schedule"] = {}
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.auto.status, "CHECKING")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.decision.action, "STOP")
        self.auto.unexpected_since = env["dt_util"].utcnow() - timedelta(seconds=31)
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_off"])
        self.assertEqual(self.auto.status, "STOP_REQUESTED")

    async def test_startup_unowned_charge_inside_valid_window_is_adopted(self):
        self.manual.unmanaged_charge = True
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6"
        await self.auto.async_set_mode("Active")
        self.assertTrue(self.auto.owned)
        self.assertEqual(self.auto.status, "CHARGING")
        self.assertEqual(self.services.calls, [])

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
