import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from geely_smart_charge_climate import ChargeSample, estimate_charge_rate, plan_charge, termination_policy


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo("Australia/Brisbane")
        self.deadline = datetime(2026, 11, 23, 6, 30, tzinfo=self.tz)
        self.fallback = estimate_charge_rate([], fallback_kw=6.5, usable_capacity_kwh=68.39)

    def test_100_percent_vehicle_managed(self):
        self.assertEqual(termination_policy(100), "vehicle_managed")
        self.assertEqual(termination_policy(80), "controller_stop")

    def test_100_percent_plan(self):
        plan = plan_charge(current_soc=50, target_soc=100, ready_by=self.deadline, estimate=self.fallback)
        self.assertEqual(plan.termination, "vehicle_managed")
        self.assertLess(plan.start_at, plan.ready_by)

    def test_higher_target_starts_earlier(self):
        a = plan_charge(current_soc=50, target_soc=80, ready_by=self.deadline, estimate=self.fallback)
        b = plan_charge(current_soc=50, target_soc=95, ready_by=self.deadline, estimate=self.fallback)
        self.assertLess(b.start_at, a.start_at)

    def test_no_charge_needed(self):
        plan = plan_charge(current_soc=90, target_soc=80, ready_by=self.deadline, estimate=self.fallback)
        self.assertEqual(plan.required_minutes, 0)
        self.assertEqual(plan.start_at, self.deadline)

    def test_learning_ignores_short_samples(self):
        samples = [ChargeSample(40, 50, 60), ChargeSample(50, 60, 60), ChargeSample(60, 61, 3)]
        est = estimate_charge_rate(samples, fallback_kw=6.5, usable_capacity_kwh=68.39)
        self.assertEqual(est.source, "learned")
        self.assertEqual(est.percentage_points_per_hour, 10)
        self.assertEqual(est.sample_count, 2)

    def test_fallback_if_invalid_samples(self):
        est = estimate_charge_rate([ChargeSample(60, 55, 60)], fallback_kw=6.5, usable_capacity_kwh=68.39)
        self.assertEqual(est.source, "fallback")

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            plan_charge(current_soc=50, target_soc=80, ready_by=datetime(2026, 11, 23, 6, 30), estimate=self.fallback)

    def test_invalid_values_rejected(self):
        with self.assertRaises(ValueError):
            termination_policy(105)
        with self.assertRaises(ValueError):
            estimate_charge_rate([], fallback_kw=0, usable_capacity_kwh=68.39)


if __name__ == "__main__":
    unittest.main()
