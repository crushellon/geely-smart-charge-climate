"""Standalone test of the persistent public charging interlock switch."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
tree = ast.parse((ROOT / "switch.py").read_text(encoding="utf-8"))
cls = next(x for x in tree.body if isinstance(x, ast.ClassDef)
           and x.name == "PublicChargingModeSwitch")

class FakeSwitch:
    def async_write_ha_state(self):
        pass

env = {"SwitchEntity": FakeSwitch}
exec(compile(ast.Module(body=[cls], type_ignores=[]), "switch.py", "exec"), env)
PublicMode = env["PublicChargingModeSwitch"]


class PublicChargingModeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.auto_tick = AsyncMock()
        self.manual_tick = AsyncMock()
        self.entry = SimpleNamespace(
            entry_id="vehicle-1",
            options={"weekly_schedule": {"monday": {"enabled": True}}},
            runtime_data=SimpleNamespace(
                async_tick=self.manual_tick,
                auto=SimpleNamespace(async_tick=self.auto_tick),
            ),
        )
        def save(entry, options):
            entry.options = options
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=save))
        self.switch = PublicMode(self.hass, self.entry)

    async def test_switch_is_persistent_and_preserves_schedules(self):
        self.assertFalse(self.switch.is_on)
        await self.switch.async_turn_on()
        self.assertTrue(self.switch.is_on)
        self.assertTrue(self.entry.options["public_charging_mode"])
        self.assertIn("weekly_schedule", self.entry.options)
        # New entity instance after HA restart reads persisted options.
        restored = PublicMode(self.hass, self.entry)
        self.assertTrue(restored.is_on)
        await restored.async_turn_off()
        self.assertFalse(restored.is_on)
        self.assertFalse(self.entry.options["public_charging_mode"])
        self.assertEqual(self.manual_tick.await_count, 2)
        self.assertEqual(self.auto_tick.await_count, 2)
