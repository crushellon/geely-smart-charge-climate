"""Exercise actual async live-controller behavior using a fake HA runtime.

This compiles the production class body without importing Home Assistant;
it checks real start, stop, retry/confirmation, and 100%-termination semantics.
"""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import importlib.util
from math import isfinite
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"

spec = importlib.util.spec_from_file_location("geely_safety_runtime", ROOT / "live_safety.py")
safety = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = safety
spec.loader.exec_module(safety)

tree = ast.parse((ROOT / "live_control.py").read_text(encoding="utf-8"))
body = next(node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "LiveChargeController")
env = {
    "asyncio": asyncio,
    "isfinite": isfinite,
    "timedelta": timedelta,
    "dt_util": SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc)),
    "callback": lambda fn: fn,
    "CONF_BATTERY_ENTITY": "battery_entity",
    "CONF_CHARGING_SWITCH": "charging_switch",
    "CONF_CHARGING_POWER": "charging_power",
    "discover_plug_entity": lambda hass, sensor: "binary_sensor.plug",
    "start_preflight": safety.start_preflight,
    "should_stop_owned_session": safety.should_stop_owned_session,
    "MONITORED_GUARDS": (
        safety.LEGACY_CONTROLLER, safety.LEGACY_ACTIVE,
        safety.OLD_FULL_CHARGE, safety.PUBLIC_MODE, safety.EMERGENCY_STOP,
    ),
    "PUBLIC_MODE": safety.PUBLIC_MODE,
    "_LOGGER": SimpleNamespace(exception=lambda *a: None),
}
exec(compile(ast.Module(body=[body], type_ignores=[]), "live_control.py", "exec"), env)
LiveChargeController = env["LiveChargeController"]


class FakeServices:
    def __init__(self, states):
        self.states = states
        self.calls = []

    async def async_call(self, domain, service, data, blocking):
        self.calls.append((domain, service, data["entity_id"]))
        self.states.data["switch.car"] = SimpleNamespace(
            state="on" if service == "turn_on" else "off"
        )
        self.states.data["sensor.power"] = SimpleNamespace(
            state="6.5" if service == "turn_on" else "0.0"
        )


class FakeStates:
    def __init__(self):
        self.data = {
            "sensor.battery": SimpleNamespace(state="72"),
            "switch.car": SimpleNamespace(state="off"),
            "sensor.power": SimpleNamespace(state="0"),
            "binary_sensor.plug": SimpleNamespace(state="on"),
            **{key: SimpleNamespace(state="off")
               for key in env["MONITORED_GUARDS"]},
        }

    def get(self, entity_id):
        return self.data.get(entity_id)


class LiveControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        states = FakeStates()
        services = FakeServices(states)
        hass = SimpleNamespace(states=states, services=services)
        entry = SimpleNamespace(data={
            "battery_entity": "sensor.battery",
            "charging_switch": "switch.car",
            "charging_power": "sensor.power",
        })
        self.controller = LiveChargeController(hass, entry)
        self.states = states
        self.services = services

    async def test_no_automatic_commands_when_disarmed(self):
        await self.controller.async_tick()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.status, "DISARMED")

    async def test_old_controller_blocks_start_even_if_armed(self):
        self.states.data[safety.LEGACY_CONTROLLER].state = "on"
        await self.controller.async_arm(True)
        await self.controller.async_start()
        self.assertEqual(self.controller.status, "BLOCKED")
        self.assertEqual(self.services.calls, [])

    async def test_one_percent_charge_stops_at_target_and_confirms(self):
        await self.controller.async_arm(True)
        await self.controller.async_set_target(73)
        await self.controller.async_start()
        self.assertEqual(self.services.calls[-1][1], "turn_on")
        self.assertEqual(self.controller.status, "RUNNING")

        self.states.data["sensor.battery"].state = "73"
        await self.controller.async_tick()
        self.assertEqual(self.services.calls[-1][1], "turn_off")
        self.assertTrue(self.controller.owned)
        self.assertEqual(self.controller.status, "STOP_REQUESTED")

        await self.controller.async_tick()
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "STOPPED")
        self.assertFalse(self.controller.owned)
        self.assertFalse(self.controller.armed)

    async def test_100_never_auto_stops(self):
        await self.controller.async_arm(True)
        await self.controller.async_set_target(100)
        await self.controller.async_start()
        self.states.data["sensor.battery"].state = "100"
        await self.controller.async_tick()
        self.assertEqual([call[1] for call in self.services.calls], ["turn_on"])
        self.assertTrue(self.controller.owned)

        await self.controller.async_stop()
        self.assertEqual(self.services.calls[-1][1], "turn_off")

    async def test_manual_disarm_stops_owned_session(self):
        await self.controller.async_arm(True)
        await self.controller.async_start()
        await self.controller.async_arm(False)
        self.assertEqual(self.services.calls[-1][1], "turn_off")
        self.assertFalse(self.controller.armed)

    async def test_public_mode_blocks_start(self):
        self.states.data[safety.PUBLIC_MODE].state = "on"
        await self.controller.async_arm(True)
        await self.controller.async_start()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
