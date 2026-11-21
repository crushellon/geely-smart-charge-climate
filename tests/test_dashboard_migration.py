"""Ensure generated dashboard upgrades without touching user modifications."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate"
tree = ast.parse((ROOT / "dashboard_setup.py").read_text(encoding="utf-8"))
func = next(x for x in tree.body
            if isinstance(x, ast.FunctionDef)
            and x.name == "_is_generated_four_page_dashboard")
env = {}
exec(compile(ast.Module(body=[func], type_ignores=[]), "dashboard_setup.py", "exec"), env)
is_generated = env["_is_generated_four_page_dashboard"]


def fixture(marker="Geely EX5", normal=True):
    return [
        {"sections": [
            {"cards": [
                {"type": "markdown", "content": f"### {marker}"},
                {}, {}, {}, {},
            ]},
            {"cards": [{"title": "Seven-day charging schedule"}]},
        ]},
        {"sections": [
            {"cards": []},
            {"cards": [
                {"title": "Comfort Cool — expand settings"},
                {"type": "conditional", "card": {"title": "Cool profile"}},
                {"title": "Comfort Warm — expand settings"},
                {"type": "conditional", "card": {"title": "Warm profile"}},
            ]},
        ]},
        {"sections": [
            {"cards": [
                {"title": f"Climate schedule {n}"} for n in (1, 3, 5, 7)
            ]},
            {"cards": [
                {"title": f"Climate schedule {n}"} for n in (2, 4, 6)
            ]},
        ]},
        {"sections": [{"cards": []}, {"cards": []}]},
    ]


class DashboardMigrationTests(unittest.TestCase):
    def test_product_generated_layout_is_refreshable(self):
        self.assertTrue(is_generated(fixture()))

    def test_old_test_dashboard_is_refreshable(self):
        views = fixture("Geely Smart Charge & Climate")
        views[1]["sections"][1]["cards"] = [
            {"title": "Comfort preferences"},
            {"title": "Cool profile"},
            {"title": "Warm profile"},
        ]
        self.assertTrue(is_generated(views))

    def test_custom_dashboard_is_preserved(self):
        self.assertFalse(is_generated(fixture("My fully customized dashboard")))

    def test_missing_schedule_or_climate_slots_not_overwritten(self):
        views = fixture()
        views[0]["sections"][1]["cards"][0]["title"] = "My planning panel"
        self.assertFalse(is_generated(views))
        views = fixture()
        views[2]["sections"][0]["cards"].pop()
        self.assertFalse(is_generated(views))


if __name__ == "__main__":
    unittest.main()
