from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.crypto_research_quality import (causality_check, report,
                                            _resampled_returns)


def wealth(log_returns, initial=100.0):
    result = [initial]
    for value in log_returns:
        result.append(result[-1] * math.exp(value))
    return result


class ResearchQualityTests(unittest.TestCase):
    def test_sample_count_missing_data_and_strict_positive_finite_input(self):
        self.assertFalse(report([100.0] * 30)["available"])
        result = report([100.0] * 31)
        self.assertTrue(result["available"])
        self.assertEqual(result["sample_count"], 30)
        self.assertEqual(result["observed"], {"total_return": 0.0, "max_drawdown": 0.0})
        self.assertEqual(result["intervals"]["total_return"]["lower"], 0.0)
        missing = report([100.0] * 20 + [None] + [100.0] * 20)
        self.assertFalse(missing["available"])
        self.assertEqual(missing["reason"], "MISSING_EQUITY")
        self.assertEqual(missing["sample_count"], 38)
        self.assertIsNone(missing["observed"])
        for bad in (True, "100", 0, -1, float("nan"), float("inf"), 10**1000):
            with self.subTest(bad=type(bad).__name__), self.assertRaises(ValueError):
                report([100.0] * 31 + [bad])
        self.assertEqual(report([])["reason"], "INSUFFICIENT_RETURNS")

    def test_observed_known_answer_scale_invariance_and_no_mutation(self):
        equity = [100.0] * 29 + [120.0, 90.0, 110.0]
        frozen = deepcopy(equity)
        result = report(equity, seed=27)
        self.assertEqual(equity, frozen)
        self.assertAlmostEqual(result["observed"]["total_return"], 0.10)
        self.assertAlmostEqual(result["observed"]["max_drawdown"], 0.25)
        scaled = report([x * 5 for x in equity], seed=27)
        for key in ("total_return", "max_drawdown"):
            for bound in ("lower", "median", "upper"):
                self.assertAlmostEqual(result["intervals"][key][bound], scaled["intervals"][key][bound])
        json.dumps(result, allow_nan=False)

    def test_block_order_wraparound_and_truncated_final_block(self):
        class Starts:
            def __init__(self):
                self.starts = iter((3, 1))
            def randrange(self, size):
                self.size = size
                return next(self.starts)
        generator = Starts()
        sampled = list(_resampled_returns([10, 20, 30, 40, 50], generator, 3))
        self.assertEqual(sampled, [40, 50, 10, 20, 30])
        self.assertEqual(generator.size, 5)

    def test_serial_dependence_changes_uncertainty_and_full_block_total_is_fixed(self):
        # Long persistent regimes have wider return uncertainty with retained
        # long blocks than with shorter blocks; individual returns are identical.
        equity = wealth(([0.01] * 64 + [-0.01] * 64) * 2)
        short = report(equity, seed=4, replicas=256, block_size=2)
        long = report(equity, seed=4, replicas=256, block_size=32)
        a, b = short["intervals"]["total_return"], long["intervals"]["total_return"]
        self.assertGreater(b["upper"] - b["lower"], a["upper"] - a["lower"])
        complete = report(equity, seed=4, replicas=64, block_size=256)
        bounds = complete["intervals"]["total_return"]
        self.assertAlmostEqual(bounds["minimum"], bounds["maximum"], places=10)
        self.assertIn("degenerate", " ".join(complete["limits"]))

    def test_seed_repeatability_is_local_and_intervals_ordered(self):
        equity = wealth([0.03, -0.02, 0.01, -0.005] * 40)
        random.seed(99)
        before = random.getstate()
        first, second = report(equity, seed=42), report(equity, seed=42)
        self.assertEqual(random.getstate(), before)
        self.assertEqual(first, second)
        self.assertNotEqual(first["intervals"], report(equity, seed=43)["intervals"])
        self.assertEqual(first["completed_replicas"], 128)
        for metric, summary in first["intervals"].items():
            self.assertLessEqual(summary["minimum"], summary["lower"])
            self.assertLessEqual(summary["lower"], summary["median"])
            self.assertLessEqual(summary["median"], summary["upper"])
            self.assertLessEqual(summary["upper"], summary["maximum"])
            self.assertTrue(all(math.isfinite(x) for x in summary.values()))

    def test_work_caps_invalid_arguments_and_numeric_range(self):
        with self.assertRaises(ValueError):
            report([100] * 4097)
        for kwargs in ({"replicas": 257}, {"replicas": 0}, {"replicas": True},
                       {"block_size": 1}, {"block_size": True}, {"block_size": 100},
                       {"seed": True}, {"seed": 1.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                report([100.0] * 31, **kwargs)
        maximal = report([100] * 4096, replicas=256)
        self.assertEqual(maximal["sample_count"], 4095)
        self.assertEqual(maximal["completed_replicas"], 256)
        self.assertNotIn("paths", maximal)
        extreme = report([1e-300] * 30 + [1e300])
        self.assertFalse(extreme["available"])
        self.assertEqual(extreme["reason"], "NUMERIC_RANGE_UNAVAILABLE")
        self.assertIsNone(extreme["intervals"])
        json.dumps(extreme, allow_nan=False)

    def test_actual_prefix_fixture_detects_before_fix_lookahead(self):
        tape = [10, 11, 9, 12, 11, 13]
        # Before: normalize against a mean containing future bars.
        def biased(values):
            mean = sum(values) / len(values)
            return ["buy" if price < mean else "hold" for price in values]
        before = causality_check(biased(tape), biased(tape[:3]), 3)
        self.assertFalse(before["passed"])
        self.assertTrue(before["possible_lookahead"])
        self.assertEqual(before["first_mismatch_index"], 0)
        # After: each decision depends only on that bar and its past.
        def causal(values):
            return ["buy" if price < sum(values[:i + 1]) / (i + 1) else "hold"
                    for i, price in enumerate(values)]
        after = causality_check(causal(tape), causal(tape[:3]), 3)
        self.assertTrue(after["passed"])
        self.assertEqual(after["compared_count"], 3)

    def test_prefix_only_typed_bounded_outputs_and_immutability(self):
        full = [{"signal": "buy", "size": 1.0}, {"signal": "hold"}, object()]
        prefix = deepcopy(full[:2])
        frozen = deepcopy(prefix)
        self.assertTrue(causality_check(full, prefix, 2)["passed"])
        self.assertEqual(prefix, frozen)
        self.assertFalse(causality_check([True], [1], 1)["passed"])
        for args in (([1], [], 1), ([1], [1], 0), ([1], [1], True),
                     ([1] * 4097, [1], 1), ([float("nan")], [1.0], 1)):
            with self.subTest(cutoff=args[2]), self.assertRaises(ValueError):
                causality_check(*args)
        nested = 1
        for _ in range(10):
            nested = [nested]
        with self.assertRaises(ValueError):
            causality_check([nested], [nested], 1)


if __name__ == "__main__":
    unittest.main()
