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
    "decide": policy.decide, "start_preflight": safety.start_preflight,
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
    "HOME_WALL_CONNECTOR": "binary_sensor.tesla_wall_connector_vehicle_connected",
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
            "binary_sensor.tesla_wall_connector_vehicle_connected": "on",
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

    async def test_completed_session_does_not_restart_in_same_window(self):
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, ["turn_on"])
        await self.auto.async_tick()  # Observe charging ON before a later stop.
        # Geely ends the session before target (network or car decides).
        self.values["switch.car"] = "off"
        self.values["sensor.power"] = "0"
        await self.auto.async_tick()
        await self.auto.async_tick()
        self.assertEqual(self.auto.status, "COMPLETED")
        await self.auto.async_tick()
        self.assertEqual(self.services.calls, ["turn_on"])

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

    async def test_guard_detects_and_stops_unexpected_home_charge(self):
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

    async def test_guard_does_not_stop_without_home_confirmation(self):
        self.entry.options["weekly_schedule"] = {}
        self.values["switch.car"] = "on"
        self.values["sensor.power"] = "6"
        self.values["binary_sensor.tesla_wall_connector_vehicle_connected"] = "off"
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.status, "UNKNOWN")

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

    async def test_manual_priority(self):
        self.manual.armed = True
        await self.auto.async_set_mode("Active")
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.auto.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
