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
            source = file.read_text(encoding="utf-8")
            self.assertNotIn("hass.services.async_call", source)
            self.assertNotIn("async_call_service", source)

    def test_manifest_marks_config_flow(self):
        import json
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["config_flow"])


if __name__ == "__main__":
    unittest.main()
