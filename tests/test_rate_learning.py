"""Standard library tests for the learning engine."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/geely_smart_charge_climate/rate_learning.py"
spec = importlib.util.spec_from_file_location("rate_learning_test", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
RateLearner = module.RateLearner


class RateLearningTests(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2026, 11, 21, 0, 0, tzinfo=timezone.utc)

    def test_default_nominal_7_effective_6_5(self):
        self.assertAlmostEqual(module.effective_fallback_kw(7), 6.5)

    def test_learning_and_persistence(self):
        learner = RateLearner()
        self.assertFalse(learner.observe(soc=40, charging=True, at=self.t))
        self.assertTrue(learner.observe(soc=45, charging=True, at=self.t + timedelta(minutes=30)))
        self.assertIsNone(learner.learned_rate)
        self.assertTrue(learner.observe(soc=50, charging=True, at=self.t + timedelta(minutes=60)))
        self.assertAlmostEqual(learner.learned_rate, 10.0)
        restored = RateLearner.from_storage(learner.to_storage())
        self.assertEqual(restored.samples, learner.samples)
        self.assertFalse(restored.active)

    def test_stop_breaks_session(self):
        learner = RateLearner()
        learner.observe(soc=40, charging=True, at=self.t)
        learner.observe(soc=42, charging=False, at=self.t + timedelta(minutes=20))
        learner.observe(soc=50, charging=True, at=self.t + timedelta(minutes=60))
        self.assertEqual(learner.samples, [])

    def test_exclude_near_full(self):
        learner = RateLearner()
        learner.observe(soc=86, charging=True, at=self.t)
        learner.observe(soc=91, charging=True, at=self.t + timedelta(minutes=30))
        self.assertEqual(learner.samples, [])

    def test_no_learning_without_soc_changes(self):
        learner = RateLearner()
        learner.observe(soc=60, charging=True, at=self.t)
        learner.observe(soc=60, charging=True, at=self.t + timedelta(minutes=60))
        self.assertEqual(learner.samples, [])

    def test_untrusted_storage_ignored(self):
        restored = RateLearner.from_storage({"samples": [9.2, -1, float("inf"), "8"]})
        self.assertEqual(restored.samples, [9.2])


if __name__ == "__main__":
    unittest.main()
