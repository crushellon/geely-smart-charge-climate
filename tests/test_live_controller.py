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

activity_spec = importlib.util.spec_from_file_location(
    "geely_vehicle_activity_test", ROOT / "vehicle_activity.py"
)
activity = importlib.util.module_from_spec(activity_spec)
sys.modules[activity_spec.name] = activity
activity_spec.loader.exec_module(activity)

tree = ast.parse((ROOT / "live_control.py").read_text(encoding="utf-8"))
body = next(node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "LiveChargeController")
class DummyAutomatic:
    def __init__(self, manual):
        self.manual = manual
        self.owned = False
        self.stop_requested_at = None
        self.mode = "Off"
        self.stop_watch_until = None
        self.unexpected_since = None
        self._lock = asyncio.Lock()

    async def async_set_mode(self, mode, deliberate=True):
        self.mode = mode

    async def _request_stop(self, message):
        return None

    def _update(self, status, message):
        return None

    async def async_tick(self):
        return None

    async def async_shutdown(self):
        return None

    async def async_restore(self):
        return None


class DummyScheduledClimate:
    def __init__(self, manual):
        self.status = "IDLE"
        self.message = "No schedule"
        self.active = None

    async def async_tick(self):
        return None

    async def async_manual_override(self, action):
        return None


class DummyClimate:
    def __init__(self, hass, entry, notify):
        self.status = "IDLE"
        self.message = "No commands sent"

    async def apply(self, action):
        self.status = action


env = {
    "AutomaticChargeController": DummyAutomatic,
    "ManualClimateController": DummyClimate,
    "ScheduledClimateController": DummyScheduledClimate,
    "vehicle_activity": activity.vehicle_activity,
    "MANUAL_STOP_SETTLE": timedelta(0),
    "MANUAL_STOP_WATCH": timedelta(minutes=5),
    "datetime": datetime,
    "asyncio": asyncio,
    "isfinite": isfinite,
    "timedelta": timedelta,
    "dt_util": SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc)),
    "callback": lambda fn: fn,
    "CONF_BATTERY_ENTITY": "battery_entity",
    "CONF_CHARGING_SWITCH": "charging_switch",
    "CONF_CHARGING_POWER": "charging_power",
    "discover_plug_entity": lambda hass, sensor: "binary_sensor.plug",
    "discover_charging_power_entity": lambda hass, sensor: None,
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
        old = self.data.get(entity_id)
        if old is None:
            return None
        return SimpleNamespace(
            state=old.state,
            last_reported=datetime.now(timezone.utc) + timedelta(seconds=1),
        )


class LiveControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        states = FakeStates()
        services = FakeServices(states)
        hass = SimpleNamespace(
            states=states, services=services, async_create_task=asyncio.create_task,
            config_entries=SimpleNamespace(async_update_entry=
                                   lambda entry, options: setattr(entry, "options", options)))
        entry = SimpleNamespace(data={
            "battery_entity": "sensor.battery",
            "charging_switch": "switch.car",
            "charging_power": "sensor.power",
        }, options={})
        self.controller = LiveChargeController(hass, entry)
        self.states = states
        self.services = services

    async def test_no_automatic_commands_when_disarmed(self):
        await self.controller.async_tick()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.status, "IDLE")

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

    async def test_old_arm_flag_is_not_a_vehicle_stop_control(self):
        # There is no normal arm-test button; changing this legacy in-memory
        # flag must not stop a real vehicle session.
        await self.controller.async_start_manual()
        await self.controller.async_arm(False)
        self.assertEqual([c[1] for c in self.services.calls], ["turn_on"])
        self.assertTrue(self.controller.owned)

    async def test_new_manual_target_is_saved_across_controller_instances(self):
        await self.controller.async_set_target(87)
        self.assertEqual(self.controller.entry.options["manual_charge_target"], 87)
        rebuilt = LiveChargeController(self.controller.hass, self.controller.entry)
        self.assertEqual(rebuilt.target, 87)

    async def test_preexisting_charge_is_detected_without_claiming_manual_target(self):
        self.states.data["switch.car"].state = "on"
        self.states.data["sensor.power"].state = "6.5"
        await self.controller.async_restore()
        self.assertTrue(self.controller.unmanaged_charge)
        self.assertFalse(self.controller.owned)
        self.assertEqual(self.controller.status, "EXTERNAL")
        self.assertEqual(self.services.calls, [])
        await self.controller.async_start_manual(80)
        self.assertEqual(self.controller.status, "BLOCKED")
        self.assertEqual(self.services.calls, [])

    async def test_manual_stop_explicitly_stops_preexisting_unmanaged_charge(self):
        self.states.data["switch.car"].state = "on"
        self.states.data["sensor.power"].state = "6.5"
        await self.controller.async_restore()
        await self.controller.async_stop()
        self.assertEqual([c[1] for c in self.services.calls], ["turn_off"])
        self.assertEqual(self.controller.status, "STOP_REQUESTED")

    async def test_reload_does_not_interrupt_sub_100_manual_charge(self):
        await self.controller.async_set_target(80)
        await self.controller.async_start_manual()
        self.assertEqual(self.services.calls[-1][1], "turn_on")
        await self.controller.async_shutdown()
        self.assertEqual([c[1] for c in self.services.calls], ["turn_on"])
        self.assertTrue(self.controller.entry.options["manual_session"]["active"])
        recovered = LiveChargeController(self.controller.hass, self.controller.entry)
        await recovered.async_restore()
        self.assertTrue(recovered.owned)
        self.assertEqual(self.services.calls[-1][1], "turn_on")

    async def test_product_manual_start_does_not_require_arm_toggle(self):
        self.assertFalse(self.controller.armed)
        await self.controller.async_set_target(73)
        await self.controller.async_start_manual()
        self.assertTrue(self.controller.owned)
        self.assertEqual(self.services.calls[-1][1], "turn_on")
        self.assertEqual(self.controller.active_target, 73)
        await self.controller.async_stop()
        self.assertEqual(self.services.calls[-1][1], "turn_off")
        await self.controller.async_tick()
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "STOPPED")

    async def test_authorised_manual_start_cancels_old_auto_rebound_watch(self):
        # Recreate a prior automatic STOP followed by a genuine manual START.
        self.controller.auto.stop_watch_until = (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        await self.controller.async_start_manual(80)
        self.assertTrue(self.controller.owned)
        self.assertIsNone(self.controller.auto.stop_watch_until)
        self.assertEqual([call[1] for call in self.services.calls], ["turn_on"])

    async def test_blocked_manual_start_preserves_old_auto_rebound_watch(self):
        # Do not silently disable protection for a manual request that fails
        # preflight (for example, unplugged vehicle).
        watch = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.controller.auto.stop_watch_until = watch
        self.states.data["binary_sensor.plug"].state = "off"
        await self.controller.async_start_manual(80)
        self.assertFalse(self.controller.owned)
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.auto.stop_watch_until, watch)

    async def test_manual_start_waits_for_pending_automatic_stop_confirmation(self):
        self.controller.auto.stop_requested_at = datetime.now(timezone.utc)
        await self.controller.async_start_manual(80)
        self.assertFalse(self.controller.owned)
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.status, "BLOCKED")

    async def test_manual_start_pauses_auto_until_resume(self):
        self.controller.auto.mode = "Active"
        await self.controller.async_start_manual(80)
        self.assertEqual(self.controller.auto.mode, "Off")
        await self.controller.async_stop()
        await self.controller.async_tick()
        await self.controller.async_tick()
        await self.controller.async_resume_schedule()
        self.assertEqual(self.controller.auto.mode, "Active")

    async def test_product_manual_stop_rejects_early_cloud_confirmation(self):
        real_utc = env["dt_util"].utcnow
        real_settle = env["MANUAL_STOP_SETTLE"]
        clock = {"now": datetime.now(timezone.utc)}
        env["dt_util"].utcnow = lambda: clock["now"]
        env["MANUAL_STOP_SETTLE"] = timedelta(seconds=30)
        self.addCleanup(setattr, env["dt_util"], "utcnow", real_utc)
        self.addCleanup(env.__setitem__, "MANUAL_STOP_SETTLE", real_settle)
        await self.controller.async_start_manual(80)
        await self.controller.async_stop()
        await self.controller.async_tick()
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "STOP_REQUESTED")
        clock["now"] += timedelta(seconds=31)
        await self.controller.async_tick()
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "STOPPED")
        self.assertIsNotNone(self.controller.stop_watch_until)

    async def test_manual_stop_watchdog_catches_delayed_charge(self):
        await self.controller.async_start_manual(80)
        await self.controller.async_stop()
        await self.controller.async_tick()
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "STOPPED")
        self.states.data["switch.car"].state = "on"
        self.states.data["sensor.power"].state = "6.8"
        await self.controller.async_tick()
        self.assertEqual(self.controller.status, "STOP_REQUESTED")
        self.assertEqual(
            [c[1] for c in self.services.calls],
            ["turn_on", "turn_off", "turn_off"],
        )

    async def test_native_emergency_stops_charge_and_latches(self):
        await self.controller.async_start_manual(80)
        self.assertTrue(self.controller.owned)
        await self.controller.async_emergency_stop()
        self.assertTrue(self.controller.entry.options["emergency_stop"])
        self.assertEqual([c[1] for c in self.services.calls], ["turn_on", "turn_off"])
        await self.controller.async_release_emergency_stop()
        self.assertFalse(self.controller.entry.options["emergency_stop"])
        self.assertEqual(self.controller.auto.mode, "Off")

    async def test_automatic_preference_persists_across_restart(self):
        await self.controller.async_set_automatic_enabled(True)
        self.assertTrue(self.controller.entry.options["automatic_charging_enabled"])
        self.assertEqual(self.controller.auto.mode, "Active")
        replacement = LiveChargeController(self.controller.hass, self.controller.entry)
        await replacement.async_restore()
        self.assertEqual(replacement.auto.mode, "Active")
        self.assertEqual(self.services.calls, [])

    async def test_manual_stop_restores_previously_enabled_schedule(self):
        await self.controller.async_set_automatic_enabled(True)
        await self.controller.async_start_manual(80)
        self.assertTrue(self.controller.entry.options["automatic_charging_enabled"])
        self.assertEqual(self.controller.auto.mode, "Off")
        await self.controller.async_stop()
        await self.controller.async_tick()
        await self.controller.async_tick()
        await asyncio.sleep(0)
        self.assertEqual(self.controller.status, "STOPPED")
        self.assertEqual(self.controller.auto.mode, "Active")
        self.assertFalse(self.controller.entry.options["manual_session"]["active"])

    async def test_manually_disabled_preference_stays_off_after_manual_stop(self):
        await self.controller.async_set_automatic_enabled(False)
        await self.controller.async_start_manual(80)
        await self.controller.async_stop()
        await self.controller.async_tick()
        await self.controller.async_tick()
        await asyncio.sleep(0)
        self.assertEqual(self.controller.auto.mode, "Off")

    async def test_emergency_release_restores_saved_auto_intent(self):
        await self.controller.async_set_automatic_enabled(True)
        await self.controller.async_emergency_stop()
        self.assertEqual(self.controller.auto.mode, "Off")
        self.assertTrue(self.controller.entry.options["emergency_stop"])
        await self.controller.async_release_emergency_stop()
        self.assertEqual(self.controller.auto.mode, "Active")
        self.assertTrue(self.controller.entry.options["automatic_charging_enabled"])

    async def test_restart_adopts_manual_charge_without_duplicate_start(self):
        self.controller.entry.options["manual_session"] = {
            "active": True, "target": 100,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.states.data["switch.car"].state = "on"
        self.states.data["sensor.power"].state = "6.5"
        new = LiveChargeController(self.controller.hass, self.controller.entry)
        await new.async_restore()
        self.assertTrue(new.owned)
        self.assertEqual(new.active_target, 100)
        self.assertEqual(self.services.calls, [])
        await new.async_tick()
        self.assertEqual(self.services.calls, [])
        self.assertTrue(new.observed_active)

    async def test_native_public_mode_blocks_manual_start(self):
        self.controller.entry.options["public_charging_mode"] = True
        await self.controller.async_arm(True)
        await self.controller.async_start()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.status, "BLOCKED")

    async def test_public_mode_releases_owned_manual_charge_without_stopping(self):
        await self.controller.async_arm(True)
        await self.controller.async_start()
        self.assertEqual(self.services.calls[-1][1], "turn_on")
        self.controller.entry.options["public_charging_mode"] = True
        await self.controller.async_tick()
        self.assertEqual([c[1] for c in self.services.calls], ["turn_on"])
        self.assertFalse(self.controller.owned)

    async def test_public_mode_blocks_start(self):
        self.states.data[safety.PUBLIC_MODE].state = "on"
        await self.controller.async_arm(True)
        await self.controller.async_start()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.controller.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
