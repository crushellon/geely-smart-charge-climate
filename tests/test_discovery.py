"""Pure regression checks for entity naming and safety conventions.

Home Assistant registry behavior must additionally be tested inside HA.
"""

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "geely_smart_charge_climate"


class DiscoveryStaticTests(unittest.TestCase):
    def test_integration_python_parses(self):
        for file in ROOT.glob("*.py"):
            with self.subTest(file=file.name):
                ast.parse(file.read_text(encoding="utf-8"))

    def test_no_device_control_actions_in_observer(self):
        for file in ROOT.glob("*.py"):
            # The only authorised writer is the opt-in manual live controller.
            if file.name in ("live_control.py", "auto_control.py"):
                continue
            source = file.read_text(encoding="utf-8")
            self.assertNotIn("hass.services.async_call", source)
            self.assertNotIn("async_call_service", source)
        live = (ROOT / "live_control.py").read_text(encoding="utf-8")
        self.assertIn("start_preflight(", live)
        self.assertIn("self.armed = False", live)
        self.assertIn("should_stop_owned_session(", live)
        auto = (ROOT / "auto_control.py").read_text(encoding="utf-8")
        self.assertIn("if self.mode == \"Off\"", auto)
        self.assertIn("if self.mode == \"Monitor\"", auto)
        self.assertIn("start_preflight(", auto)

    def test_automatic_authorisation_rechecks_on_timer_options_and_geely(self):
        """Monitor must refresh even if the vehicle doesn't change state."""
        tree = ast.parse((ROOT / "live_control.py").read_text(encoding="utf-8"))
        controller = next(node for node in tree.body
                          if isinstance(node, ast.ClassDef)
                          and node.name == "LiveChargeController")
        listening = next(node for node in controller.body
                         if isinstance(node, ast.AsyncFunctionDef)
                         and node.name == "async_start_listening")
        periodic = next(node for node in listening.body
                        if isinstance(node, ast.FunctionDef)
                        and node.name == "periodic")
        options_changed = next(node for node in listening.body
                               if isinstance(node, ast.AsyncFunctionDef)
                               and node.name == "options_changed")
        def auto_tick_present(node):
            return any(isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "async_tick"
                       and isinstance(n.func.value, ast.Attribute)
                       and n.func.value.attr == "auto"
                       for n in ast.walk(node))
        self.assertTrue(auto_tick_present(periodic))
        self.assertTrue(auto_tick_present(options_changed))
        self.assertIn("self._notify()", ast.unparse(options_changed))
        source = ast.unparse(listening)
        self.assertIn("add_update_listener(options_changed)", source)
        self.assertIn("entities.append(self.plug)", source)
        self.assertNotIn("tesla_wall_connector_vehicle_connected", source)

    def test_schedule_controls_instead_of_configure_menu(self):
        """Day settings belong in dashboard entities, not Configure."""
        tree = ast.parse((ROOT / "config_flow.py").read_text(encoding="utf-8"))
        flow = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == "GeelySmartChargeClimateConfigFlow")
        names = {node.name for node in flow.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertNotIn("async_get_options_flow", names)
        init = (ROOT / "__init__.py").read_text(encoding="utf-8")
        for platform in ("SWITCH", "NUMBER", "TIME"):
            self.assertIn(f"Platform.{platform}", init)

    def test_no_vehicle_commands_in_weekly_controls(self):
        for name in ("schedule_entities.py", "switch.py", "number.py", "time.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("hass.services.async_call", source)
            self.assertNotIn("my_geely_ex5", source)

    def test_manifest_marks_config_flow(self):
        import json
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["config_flow"])


if __name__ == "__main__":
    unittest.main()
