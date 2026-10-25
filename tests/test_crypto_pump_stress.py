"""Independent offline scenarios: real quote arithmetic, no network or state."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_pump_quotes as quotes
from backend import crypto_pump_stress as stress


def amm(**changes):
    result = dict(kind="amm", base_reserves_atoms=1_000_000_000,
        quote_reserves_atoms=2_000_000_000, base_decimals=6, quote_decimals=9,
        quote_symbol="SOL", lp_fee_bps=30, protocol_fee_bps=20, creator_fee_bps=10)
    result.update(changes)
    return result


def curve(**changes):
    result = amm(kind="curve", lp_fee_bps=0, real_base_reserves_atoms=700_000_000,
                 real_quote_reserves_atoms=1_000_000_000)
    result.update(changes)
    return result


class PumpStressTests(unittest.TestCase):
    def test_six_deterministic_rows_use_original_slippage_bounds(self):
        for side, amount in (("buy", 100_000_000), ("buy_exact_out", 50_000_000),
                             ("sell", 50_000_000), ("sell_exact_out", 50_000_000)):
            market = amm()
            proposal = quotes.quote(market, side, amount, 100)
            market_before, quote_before = deepcopy(market), deepcopy(proposal)
            report = stress.analyze(market, proposal)
            self.assertEqual(report, stress.analyze(market, proposal))
            self.assertEqual(market, market_before)
            self.assertEqual(proposal, quote_before)
            self.assertEqual(report["mode"], "HYPOTHETICAL COST STRESS")
            self.assertEqual(len(report["rows"]), 6)
            self.assertTrue(report["rows"][0]["within_slippage"])
            self.assertEqual(report["rows"][0]["debit_atoms"], proposal["debit_atoms"])
            adverse = report["rows"][3]
            self.assertTrue(adverse["supported"], adverse)
            self.assertFalse(adverse["within_slippage"], adverse)
            # A scenario's newly recalculated bound must never replace the old one.
            for row in report["rows"]:
                if row["supported"]:
                    expected = int(row["received_atoms"]) >= int(proposal["min_received_atoms"]) and int(row["debit_atoms"]) <= int(proposal["max_debit_atoms"])
                    self.assertEqual(row["within_slippage"], expected)
            json.dumps(report, allow_nan=False)

    def test_depth_scales_signed_offsets_and_retained_fee_buckets(self):
        market = amm(trade_v2=True, protocol_fees_atoms=2_000_003,
            creator_fees_atoms=1_000_007, virtual_quote_reserves_atoms=-3_000_010,
            base_transfer_fee={"bps": 100, "max_fee": 500},
            quote_transfer_fee={"bps": 50, "max_fee": 300})
        proposal = quotes.quote(market, "sell", 100_000_000)
        captured = []
        original = quotes.quote

        def record(m, *args):
            captured.append(deepcopy(m))
            return original(m, *args)

        with patch.object(stress.quotes, "quote", side_effect=record):
            result = stress.analyze(market, proposal)
        self.assertEqual(len(captured), 6)
        for changed in captured:
            checked = quotes.validate_market(changed)
            self.assertEqual(checked["virtual_quote_reserves_atoms"],
                             -checked["protocol_fees_atoms"] - checked["creator_fees_atoms"])
            self.assertEqual(changed["base_transfer_fee"], market["base_transfer_fee"])
            self.assertEqual(changed["quote_transfer_fee"], market["quote_transfer_fee"])
        thinned = captured[2]
        self.assertEqual(thinned["base_reserves_atoms"], market["base_reserves_atoms"] // 2)
        self.assertEqual(thinned["quote_reserves_atoms"] + thinned["virtual_quote_reserves_atoms"],
                         (market["quote_reserves_atoms"] + market["virtual_quote_reserves_atoms"]) // 2)
        self.assertTrue(all(row["supported"] for row in result["rows"]))

    def test_fee_scenario_freezes_effective_tier_and_creator_override_once(self):
        def rates(lp, protocol, creator):
            return dict(lp_fee_bps=lp, protocol_fee_bps=protocol, creator_fee_bps=creator)

        market = amm(fee_config={"flat_fees": rates(50, 70, 90),
            "fee_tiers": [{"market_cap_lamports_threshold": 0, "fees": rates(30, 20, 10)}]},
            is_pump_pool=True, mint_supply_atoms=10_000_000,
            creator_fee_configurable=True, configured_creator_fee_bps=7)
        proposal = quotes.quote(market, "buy", 10_000_000)
        self.assertEqual(proposal["fee_rates"], rates(30, 20, 7))
        expected_market = deepcopy(market)
        expected_market.pop("fee_config")
        expected_market.update(rates(30, 45, 7), creator_fee_configurable=False)
        expected = quotes.quote(expected_market, "buy", 10_000_000)
        report = stress.analyze(market, proposal)
        fee_row = report["rows"][-1]
        self.assertEqual(fee_row["received_atoms"], expected["received_atoms"])
        self.assertEqual(fee_row["debit_atoms"], expected["debit_atoms"])
        for creator_present in (True, False):
            zero = amm(lp_fee_bps=0, protocol_fee_bps=0, creator_fee_bps=0, creator_present=creator_present)
            self.assertTrue(all(row["supported"] for row in stress.analyze(zero, quotes.quote(zero, "buy", 100000))["rows"]))

    def test_curves_keep_real_inventory_conservative_and_show_failures(self):
        market = curve()
        captured = []
        original = quotes.quote

        def record(m, *args):
            captured.append(deepcopy(m))
            return original(m, *args)

        proposal = quotes.quote(market, "buy_exact_out", 600_000_000, 100)
        with patch.object(stress.quotes, "quote", side_effect=record):
            result = stress.analyze(market, proposal)
        for m in captured:
            self.assertLessEqual(m["real_base_reserves_atoms"], m["base_reserves_atoms"])
            self.assertLessEqual(m["real_quote_reserves_atoms"], market["real_quote_reserves_atoms"])
            self.assertEqual(m.get("virtual_quote_reserves_atoms", 0), 0)
        self.assertFalse(result["rows"][1]["supported"])
        self.assertEqual(result["rows"][1]["error"], "PUMP_UNSUPPORTED_MIGRATION_CROSSING")
        self.assertEqual(result["rows"][1]["debit_display"], "—")

    def test_invalid_inputs_and_unattainable_fee_scenario_report_reasons(self):
        market = amm()
        valid = quotes.quote(market, "buy", 10_000_000)
        for broken_market, proposal in (({}, valid), ({**market, "virtual_quote_reserves_atoms": -3_000_000_000}, valid),
                (market, {}), (market, None), (market, {**valid, "amount_atoms": "0"}),
                (market, {**valid, "amount_atoms": True}), (market, {**valid, "slippage_bps": 10000}),
                (market, {**valid, "received_atoms": "1"}), (market, {**valid, "max_debit_atoms": "NaN"})):
            report = stress.analyze(broken_market, proposal)
            self.assertEqual(len(report["rows"]), 1)
            self.assertFalse(report["rows"][0]["supported"])
            self.assertTrue(report["rows"][0]["error"].startswith("PUMP_"))
        expensive = amm(lp_fee_bps=0, creator_fee_bps=0, protocol_fee_bps=9990)
        proposal = quotes.quote(expensive, "buy", 10_000_000)
        report = stress.analyze(expensive, proposal)
        self.assertFalse(report["rows"][-1]["supported"])
        self.assertIn("PROTOCOL", report["rows"][-1]["error"])

    def test_large_atomic_strings_and_bounded_work(self):
        market = amm(base_reserves_atoms=10**18, quote_reserves_atoms=8 * 10**18,
                     base_decimals=18, quote_decimals=18)
        proposal = quotes.quote(market, "buy", 10**17)
        started = time.perf_counter()
        with patch.object(stress.quotes, "quote", wraps=quotes.quote) as count:
            report = stress.analyze(market, proposal)
        self.assertLessEqual(count.call_count, stress.MAX_SCENARIOS)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(report["rows"][0]["debit_atoms"], proposal["debit_atoms"])
        self.assertEqual(report["rows"][0]["debit_display"], "0.1 SOL")
        self.assertLess(len(json.dumps(report)), 12000)


if __name__ == "__main__":
    unittest.main()
