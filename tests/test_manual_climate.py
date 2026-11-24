"""Pure tests for the explicit manual Geely comfort command adapter."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
tree = ast.parse((ROOT / "manual_climate.py").read_text(encoding="utf-8"))
nodes = [
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name == "geely_climate_entities"
    or isinstance(n, ast.ClassDef) and n.name == "ManualClimateController"
]


class FakeAsyncio:
    Lock = asyncio.Lock

    @staticmethod
    async def sleep(seconds):
        return None


def get_value(opts, profile, key):
    return opts[profile][key]


def get_seat_mode(opts, profile, seat):
    return opts[profile][seat]


env = {
    "asyncio": FakeAsyncio,
    "get_value": get_value,
    "get_seat_mode": get_seat_mode,
    "_LOGGER": SimpleNamespace(exception=lambda *args: None),
}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "manual_climate.py", "exec"), env)
ManualClimateController = env["ManualClimateController"]
entities = env["geely_climate_entities"]


class FakeServices:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, action, data, blocking):
        self.calls.append((domain, action, data))


class ManualClimateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.services = FakeServices()
        self.vehicle = entities("sensor.my_geely_ex5_4034_battery")
        self.hass = SimpleNamespace(
            services=self.services,
            states=SimpleNamespace(get=lambda ent: SimpleNamespace(state="off")
                                   if ent in self.vehicle.values() else None),
        )
        self.entry = SimpleNamespace(
            data={"battery_entity": "sensor.my_geely_ex5_4034_battery"},
            options={
                "manual_cabin_temperature": 22.5,
                "cool": {"temperature": 16.5, "driver": "Vent High",
                         "passenger": "Vent Low", "steering_heat": False},
                "warm": {"temperature": 24.0, "driver": "Heat High",
                         "passenger": "Heat Medium", "steering_heat": True},
            },
        )
        self.control = ManualClimateController(self.hass, self.entry, lambda: None)

    async def test_discovery_matches_geely_vehicle(self):
        self.assertEqual(self.vehicle["climate"], "climate.my_geely_ex5_4034_climate")
        self.assertEqual(self.vehicle["driver_vent"],
                         "select.my_geely_ex5_4034_seat_vent_driver")
        self.assertEqual(entities("sensor.not_battery_data"), {})

    async def test_cool_sends_temperature_ventilation_and_steering_off(self):
        await self.control.apply("Cool")
        self.assertEqual(self.control.status, "REQUESTED")
        self.assertIn(("climate", "set_temperature", {
            "entity_id": self.vehicle["climate"],
            "temperature": 16.5, "hvac_mode": "heat_cool",
        }), self.services.calls)
        self.assertIn(("select", "select_option", {
            "entity_id": self.vehicle["driver_vent"], "option": "High",
        }), self.services.calls)
        self.assertIn(("select", "select_option", {
            "entity_id": self.vehicle["passenger_vent"], "option": "Low",
        }), self.services.calls)
        self.assertNotIn(("switch", "turn_off", {
            "entity_id": self.vehicle["steering"],
        }), self.services.calls)
        self.assertNotIn(("select", "select_option", {
            "entity_id": self.vehicle["driver_heat"], "option": "Off",
        }), self.services.calls)

    async def test_busy_command_retries_and_succeeds(self):
        original = self.services.async_call
        attempts = []
        async def busy_once(domain, action, data, blocking):
            attempts.append(data["entity_id"])
            if len(attempts) == 1:
                raise RuntimeError("The last request has not yet been executed, please send the command later!")
            await original(domain, action, data, blocking)
        self.services.async_call = busy_once
        self.assertTrue(await self.control.apply("Cool"))
        self.assertEqual(attempts[:2], [self.vehicle["climate"]] * 2)

    async def test_partial_seat_failure_is_not_success(self):
        original = self.services.async_call
        async def fail_driver(domain, action, data, blocking):
            if data["entity_id"] == self.vehicle["driver_vent"]:
                raise RuntimeError("The last request has not yet been executed, please send the command later!")
            await original(domain, action, data, blocking)
        self.services.async_call = fail_driver
        self.assertFalse(await self.control.apply("Cool"))
        self.assertEqual(self.control.status, "ERROR")
        self.assertFalse(await self.control.apply_scheduled({
            "temperature": 16, "driver_seat": "Vent High",
            "passenger_seat": "Vent Low", "steering_heat": False,
        }))
        self.assertFalse(await self.control.stop_scheduled())

    async def test_off_confirmation_checks_every_actuator(self):
        self.assertTrue(self.control.off_confirmed())
        self.hass.states.get = lambda ent: SimpleNamespace(
            state="High" if ent == self.vehicle["driver_vent"] else "off"
        )
        self.assertFalse(self.control.off_confirmed())

    async def test_warm_heats_both_seats_and_steering(self):
        await self.control.apply("Warm")
        self.assertEqual(self.control.status, "REQUESTED")
        self.assertIn(("select", "select_option", {
            "entity_id": self.vehicle["driver_heat"], "option": "High",
        }), self.services.calls)
        self.assertIn(("switch", "turn_on", {
            "entity_id": self.vehicle["steering"],
        }), self.services.calls)

    async def test_custom_temperature_does_not_modify_seats(self):
        await self.control.apply("custom")
        self.assertEqual(len(self.services.calls), 1)
        self.assertEqual(self.services.calls[0], (
            "climate", "set_temperature", {
                "entity_id": self.vehicle["climate"],
                "temperature": 22.5, "hvac_mode": "heat_cool",
            }
        ))

    async def test_off_stops_climate_and_all_seat_modes(self):
        await self.control.apply("off")
        self.assertIn(("climate", "turn_off", {
            "entity_id": self.vehicle["climate"],
        }), self.services.calls)
        self.assertEqual(len([c for c in self.services.calls
                              if c[:2] == ("select", "select_option")]), 4)

    async def test_manual_off_reports_success_only_if_all_actuators_acknowledge(self):
        self.assertTrue(await self.control.apply("off"))
        self.assertEqual(self.control.status, "REQUESTED")

        # Missing passenger ventilation cannot be treated as completed OFF.
        self.services.calls.clear()
        self.hass.states.get = lambda entity: (
            None if entity == self.vehicle["passenger_vent"]
            else SimpleNamespace(state="off")
        )
        self.assertFalse(await self.control.apply("off"))
        self.assertEqual(self.control.status, "ERROR")
        self.assertIn(("climate", "turn_off", {
            "entity_id": self.vehicle["climate"],
        }), self.services.calls)
        self.assertIn(("switch", "turn_off", {
            "entity_id": self.vehicle["steering"],
        }), self.services.calls)
        self.assertTrue(all(
            item[2]["entity_id"] != "switch.my_geely_ex5_4034_charging"
            for item in self.services.calls
        ))

    async def test_main_cabin_unavailable_still_attempts_seats_and_wheel_off(self):
        self.hass.states.get = lambda entity: (
            None if entity == self.vehicle["climate"]
            else SimpleNamespace(state="off")
        )
        self.assertFalse(await self.control.apply("off"))
        self.assertIn(("select", "select_option", {
            "entity_id": self.vehicle["driver_vent"], "option": "Off",
        }), self.services.calls)
        self.assertIn(("switch", "turn_off", {
            "entity_id": self.vehicle["steering"],
        }), self.services.calls)

    async def test_scheduled_warm_then_off_never_touches_charging_switch(self):
        desired = {
            "temperature": 24.5, "driver_seat": "Heat Medium",
            "passenger_seat": "Vent Low", "steering_heat": True,
        }
        self.assertTrue(await self.control.apply_scheduled(desired))
        self.assertIn(("climate", "set_temperature", {
            "entity_id": self.vehicle["climate"],
            "temperature": 24.5, "hvac_mode": "heat_cool",
        }), self.services.calls)
        self.assertIn(("select", "select_option", {
            "entity_id": self.vehicle["driver_heat"], "option": "Medium",
        }), self.services.calls)
        self.assertIn(("select", "select_option", {
            "entity_id": self.vehicle["passenger_vent"], "option": "Low",
        }), self.services.calls)
        self.assertTrue(await self.control.stop_scheduled())
        self.assertIn(("climate", "turn_off", {
            "entity_id": self.vehicle["climate"],
        }), self.services.calls)
        self.assertTrue(all(
            call[2]["entity_id"] != "switch.my_geely_ex5_4034_charging"
            for call in self.services.calls
        ))

    async def test_scheduled_climate_unavailable_sends_no_cloud_commands(self):
        self.hass.states.get = lambda ent: None
        ok = await self.control.apply_scheduled({
            "temperature": 21, "driver_seat": "Off",
            "passenger_seat": "Off", "steering_heat": False,
        })
        self.assertFalse(ok)
        self.assertEqual(self.services.calls, [])

    async def test_climate_unavailable_never_issues_commands(self):
        self.hass.states.get = lambda ent: None
        await self.control.apply("Cool")
        self.assertEqual(self.control.status, "UNAVAILABLE")
        self.assertEqual(self.services.calls, [])


if __name__ == "__main__":
    unittest.main()
