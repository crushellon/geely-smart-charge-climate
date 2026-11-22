"""Static guard for Home Assistant event-loop callback registration.

Fake-HA controller tests cannot reproduce HA worker-thread scheduling, so
these tests inspect decorator usage on every known event/timer callback.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"


class EventCallbackSafetyTests(unittest.TestCase):
    def _callback_names(self, filename):
        tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        functions = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        return {
            node.name
            for node in functions
            if any(isinstance(decorator, ast.Name) and decorator.id == "callback"
                   for decorator in node.decorator_list)
        }

    def test_sensor_state_and_timer_callbacks_run_on_event_loop(self):
        marked = self._callback_names("sensor.py")
        for name in ("changed", "record_change", "minute_tick",
                     "refresh", "wallbox_changed"):
            with self.subTest(name=name):
                self.assertIn(name, marked)

    def test_manual_climate_expiry_schedules_async_task_on_event_loop(self):
        self.assertIn("expire", self._callback_names("scheduled_climate.py"))


if __name__ == "__main__":
    unittest.main()
