"""Reliability audits run only after the factory freezes its final choice."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_strategy_factory as factory
from backend import crypto_research_quality as quality


def prices(count=300):
    return [100.0 + index * 0.08 + ((index % 40) - 20) * 0.35 for index in range(count)]


def frames(values):
    return {"1h": {"closes": values, "times": [1_700_000_000 + i * 3600 for i in range(len(values))]}}


class FactoryQualityTests(unittest.TestCase):
    def test_capture_preserves_metrics_and_includes_initial_and_both_costs(self):
        candidate = {"warmup": 0, "family": "MOMENTUM", "parameters": {}}
        with patch.object(factory, "_signal", return_value=1):
            prior = factory._trade_report(candidate, [100.0] * 40, 0, 40)
            captured = factory._trade_report(candidate, [100.0] * 40, 0, 40, capture_equity=True)
        equity = captured.pop("_equity_curve")
        self.assertEqual(prior, captured)
        self.assertEqual(prior["return_pct"], -0.6988)
        self.assertEqual(prior["max_drawdown_pct"], 0.6988)
        self.assertEqual(prior["trades"], 1)
        friction = (factory.FEE_BPS + factory.SLIPPAGE_BPS) / 10000
        self.assertEqual(len(equity), 41)
        self.assertEqual(equity[0], 1.0)
        self.assertAlmostEqual(equity[1], 1 - friction)
        self.assertAlmostEqual(equity[-1], (1 - friction)**2)
        diagnostic = quality.report(equity)
        self.assertEqual(diagnostic["sample_count"], 40)
        self.assertAlmostEqual(diagnostic["observed"]["total_return"], (1 - friction)**2 - 1)
        self.assertAlmostEqual(diagnostic["observed"]["max_drawdown"], 1 - (1 - friction)**2)

    def test_one_bootstrap_for_final_winner_with_no_private_curve_in_ui(self):
        source = frames(prices())
        frozen = deepcopy(source)
        original = factory._trade_report
        with patch.object(factory, "CANDIDATE_CATALOG", factory.CANDIDATE_CATALOG[:2]), \
             patch.object(factory, "_trade_report", wraps=original) as trades, \
             patch.object(factory.crypto_research_quality, "report", wraps=quality.report) as audit:
            result = factory.run_factory(source)
        self.assertEqual(source, frozen)
        self.assertEqual(audit.call_count, 1)
        capture_calls = [call for call in trades.call_args_list if call.kwargs.get("capture_equity")]
        self.assertEqual(len(capture_calls), 1)
        captured = audit.call_args.args[0]
        self.assertEqual(captured[0], 1.0)
        final = result["autoresearch"]["final_test"]
        self.assertEqual(len(captured), final["bars"] + 1)
        self.assertEqual(result["research_quality"]["bootstrap"]["sample_count"], final["bars"])
        self.assertEqual(audit.call_args.kwargs, {"seed": 0, "replicas": 128})
        self.assertAlmostEqual(result["research_quality"]["bootstrap"]["observed"]["total_return"] * 100,
                               final["return_pct"], places=3)
        frozen_winner = {**factory.CANDIDATE_CATALOG[0], "parameters": {
            **factory.CANDIDATE_CATALOG[0]["parameters"],
            "buffer_bps": result["autoresearch"]["best_buffer_bps"]}}
        expected_final = original(frozen_winner, source["1h"]["closes"],
                                  result["split"]["validation_end"], len(source["1h"]["closes"]))
        self.assertEqual(final, expected_final)
        self.assertNotIn("_equity_curve", json.dumps(result, allow_nan=False))
        self.assertTrue(result["research_quality"]["causality"]["passed"])

    def test_final_holdout_changes_never_select_parameters_or_trials(self):
        first = prices()
        changed = first[:240] + [price * (0.4 + (i % 7) * 0.025) for i, price in enumerate(first[240:])]
        with patch.object(factory, "CANDIDATE_CATALOG", factory.CANDIDATE_CATALOG[:2]):
            a = factory.run_factory(frames(first))
            b = factory.run_factory(frames(changed))
        for key in ("best_buffer_bps", "best_validation_sharpe", "steps", "validation_folds",
                    "trial_registry", "trial_count", "selection_period", "selection_method"):
            self.assertEqual(a["autoresearch"][key], b["autoresearch"][key], key)
        for earlier, later in zip(a["candidates"], b["candidates"]):
            self.assertEqual(earlier["train"], later["train"])
            self.assertEqual(earlier["validation"], later["validation"])
        self.assertNotEqual(a["autoresearch"]["final_test"], b["autoresearch"]["final_test"])

    def test_failed_quality_has_no_selection_effect(self):
        source = frames(prices())
        with patch.object(factory, "CANDIDATE_CATALOG", factory.CANDIDATE_CATALOG[:1]):
            normal = factory.run_factory(source)
            with patch.object(factory, "_winner_research_quality", return_value={
                    "bootstrap": {"available": False}, "causality": {"passed": False}, "limits": []}):
                failed = factory.run_factory(source)
        self.assertEqual(normal["autoresearch"], failed["autoresearch"])
        self.assertEqual(normal["candidates"], failed["candidates"])

    def test_executable_future_read_detected_on_actual_prefix_inputs(self):
        candidate = deepcopy(factory.CANDIDATE_CATALOG[0])
        source = [100 + index * 0.1 for index in range(300)]
        seen_lengths = []
        def future_read(_candidate, tape, index):
            seen_lengths.append(len(tape))
            return int(tape[-1] > 125)
        with patch.object(factory, "_signal", side_effect=future_read):
            result = factory._winner_research_quality(candidate, source, [1.0] * 61)
        causality = result["causality"]
        self.assertFalse(causality["passed"])
        self.assertEqual(causality["reason"], "PREFIX_OUTPUT_CHANGED")
        self.assertEqual(len(causality["checks"]), 3)
        self.assertLessEqual(causality["max_prefix_bars"], 256)
        self.assertLessEqual(causality["signal_evaluations"], 1024)
        self.assertEqual(set(seen_lengths), {300, 85, 170, 256})
        self.assertTrue(any(check["mismatch_count"] for check in causality["checks"]))
        self.assertIn("bounded", " ".join(result["limits"]))

    def test_next_bar_read_that_breaks_prefix_execution_cannot_pass(self):
        candidate = deepcopy(factory.CANDIDATE_CATALOG[0])
        def next_bar(_candidate, tape, index):
            return int(tape[index + 1] > tape[index])
        with patch.object(factory, "_signal", side_effect=next_bar):
            result = factory._winner_research_quality(candidate, prices(), [1.0] * 61)
        check = result["causality"]
        self.assertFalse(check["passed"])
        self.assertFalse(check["available"])
        self.assertEqual(check["reason"], "PREFIX_EXECUTION_FAILED")
        self.assertEqual(check["signal_evaluations"], 256 + 85)
        self.assertFalse(check["checks"][0]["passed"])

    def test_oversized_equity_and_short_history_are_explicitly_unavailable(self):
        candidate = deepcopy(factory.CANDIDATE_CATALOG[0])
        result = factory._winner_research_quality(candidate, prices(), [1.0] * 4097)
        self.assertFalse(result["bootstrap"]["available"])
        self.assertEqual(result["bootstrap"]["reason"], "CRYPTO_RESEARCH_EQUITY_LIMIT")
        self.assertEqual(result["bootstrap"]["equity_count"], 4097)
        self.assertEqual(result["bootstrap"]["sample_count"], 4096)
        short = factory._winner_research_quality(candidate, [100.0], [1.0])
        self.assertFalse(short["bootstrap"]["available"])
        self.assertFalse(short["causality"]["available"])
        self.assertIsNone(short["causality"]["passed"])
        with patch.object(factory, "CANDIDATE_CATALOG", factory.CANDIDATE_CATALOG[:1]):
            output = factory.run_factory(frames(prices(50)))
        self.assertEqual(output["state"], "DONE")
        self.assertEqual(output["research_quality"]["bootstrap"]["reason"], "INSUFFICIENT_RETURNS")


if __name__ == "__main__":
    unittest.main()
