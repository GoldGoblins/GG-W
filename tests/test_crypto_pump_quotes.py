"""Offline known answers and safety invariants; no SDK execution or RPC."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.crypto_pump_quotes import (U64_MAX, USDC_MINT, fee_rates,
    gross_for_transfer_fee, net_of_transfer_fee, quote, transfer_fee, transfer_fee_at,
    validate_market)


def amm(**changes):
    return dict(kind="amm", base_reserves_atoms=1_000_000,
                quote_reserves_atoms=2_000_000, base_decimals=6, quote_decimals=9,
                protocol_fee_bps=20, creator_fee_bps=0, lp_fee_bps=30, **changes)


def curve(**changes):
    result = amm()
    result.update(kind="curve", lp_fee_bps=0, real_base_reserves_atoms=700_000,
                  real_quote_reserves_atoms=1_000_000)
    result.update(changes)
    return result


class PumpQuotesTests(unittest.TestCase):
    def test_official_amm_buy_and_sell_known_answers(self):
        # Published SDK 2.2.0 buy.spec.ts/sell.spec.ts examples:
        # https://unpkg.com/@pump-fun/pump-swap-sdk@2.2.0/src/__tests__/buy.spec.ts
        bought = quote(amm(), "buy_exact_out", 10_000, 100)
        self.assertEqual(bought["debit_atoms"], "20305")
        self.assertEqual(bought["internal_quote_atoms"], "20203")
        self.assertEqual(bought["fee_breakdown"]["lp_atoms"], "61")
        self.assertEqual(bought["fee_breakdown"]["protocol_atoms"], "41")
        # Our wallet cap uses a conservative integer ceil; SDK UI floors it.
        self.assertEqual(bought["max_debit_atoms"], "20509")
        sold = quote(amm(), "sell", 50_000, 100)
        self.assertEqual(sold["received_atoms"], "94761")
        self.assertEqual(sold["min_received_atoms"], "93813")
        self.assertEqual(sold["internal_quote_atoms"], "95238")

    def test_curve_floor_plus_one_differs_from_amm_true_ceil(self):
        # Exactly divisible Q*out/(B-out) = 2_000_000.
        pool = amm()
        pool.update(lp_fee_bps=0, protocol_fee_bps=0)
        a = quote(pool, "buy_exact_out", 500_000, 0)
        b = quote(curve(protocol_fee_bps=0), "buy_exact_out", 500_000, 0)
        self.assertEqual(a["debit_atoms"], "2000000")
        self.assertEqual(b["debit_atoms"], "2000001")

    def test_exact_in_minus_one_and_individual_fee_ceils(self):
        market = amm()
        market.update(lp_fee_bps=1, protocol_fee_bps=1, creator_fee_bps=1)
        result = quote(market, "buy", 100, 0)
        # Fee-fit 99 + three ceiled atoms >100, so swap receives97;
        # CP uses96, not97. 1_000_000*96//2_000_096 =47.
        self.assertEqual(result["received_atoms"], "47")
        self.assertEqual(result["internal_quote_atoms"], "97")
        self.assertEqual(result["debit_atoms"], "100")
        self.assertEqual([result["fee_breakdown"][k] for k in
                          ("lp_atoms", "protocol_atoms", "creator_atoms")], ["1"] * 3)

    def test_transfer_fee_official_known_answers(self):
        # Official transferFee.spec.ts oracle; SPL receiver withholding.
        fee = {"bps": 100, "max_fee": U64_MAX}
        self.assertEqual([transfer_fee(n, fee) for n in (10_000, 10_001, 1, 0)],
                         [100, 101, 1, 0])
        self.assertEqual(gross_for_transfer_fee(9900, fee), 10_000)
        self.assertEqual(gross_for_transfer_fee(100_000, {"bps": 100, "max_fee": 50}), 100_050)
        self.assertEqual(gross_for_transfer_fee(3, {"bps": 10_000, "max_fee": 7}), 10)
        for bps in (0, 1, 100, 3333, 9999, 10_000):
            for cap in (0, 1, 50, 1_000_000):
                fee = {"bps": bps, "max_fee": cap}
                for net in (1, 2, 99, 100, 4950, 4951, 123457):
                    gross = gross_for_transfer_fee(net, fee)
                    self.assertGreaterEqual(net_of_transfer_fee(gross, fee), net)
                    self.assertLess(net_of_transfer_fee(gross - 1, fee), net)
        with self.assertRaises(ValueError):
            gross_for_transfer_fee(U64_MAX, {"bps": 1, "max_fee": 1})

    def test_epoch_boundary_and_schedules_require_epoch(self):
        schedule = {"older": {"epoch": 1, "bps": 10, "max_fee": 20},
                    "newer": {"epoch": 100, "bps": 100, "max_fee": 50}}
        self.assertEqual(transfer_fee_at(schedule, 99)["bps"], 10)
        self.assertEqual(transfer_fee_at(schedule, 100)["bps"], 100)
        with self.assertRaises(ValueError):
            transfer_fee_at(schedule)
        schedule["newer"]["bps"] = True
        with self.assertRaises(ValueError):
            transfer_fee_at(schedule, 99)
        schedule["newer"]["bps"] = 100
        before = quote(amm(base_transfer_fee=schedule, epoch=99), "buy", 10000)
        carried = before["post_market"]
        self.assertIn("newer", carried["base_transfer_fee"])
        carried["epoch"] = 100
        self.assertEqual(transfer_fee_at(carried["base_transfer_fee"], carried["epoch"])["bps"], 100)

    def test_net_wallet_bounds_and_vault_only_grossup(self):
        market = amm(base_transfer_fee={"bps": 100, "max_fee": 50},
                     quote_transfer_fee={"bps": 100, "max_fee": U64_MAX})
        market.update(creator_fee_bps=30)
        result = quote(market, "buy_exact_out", 10_000, 0)
        self.assertEqual(result["received_atoms"], "10000")
        self.assertEqual(result["fee_breakdown"]["base_transfer_atoms"], "50")
        raw = int(result["internal_quote_atoms"])
        f = result["fee_breakdown"]
        expected = gross_for_transfer_fee(raw + int(f["lp_atoms"]), market["quote_transfer_fee"])
        expected += int(f["protocol_atoms"]) + int(f["creator_atoms"])
        self.assertEqual(int(result["debit_atoms"]), expected)
        self.assertEqual(int(result["debit_atoms"]), raw + int(f["lp_atoms"])
                         + int(f["protocol_atoms"]) + int(f["creator_atoms"])
                         + int(f["quote_transfer_atoms"]))
        sold = quote(market, "sell", 50_000, 100)
        self.assertEqual(int(sold["min_received_atoms"]), int(sold["received_atoms"]) * 99 // 100)
        exact = quote(market, "sell_exact_out", 10_000, 0)
        self.assertGreaterEqual(int(exact["received_atoms"]), 10_000)
        self.assertEqual(exact["min_received_atoms"], "10000")
        previous = quote(market, "sell", int(exact["debit_atoms"]) - 1, 0)
        self.assertLess(int(previous["received_atoms"]), 10_000)

    def test_signed_virtual_and_fee_sweep_invariance(self):
        with_fees = amm(virtual_quote_reserves_atoms=-3000,
                        protocol_fees_atoms=2000, creator_fees_atoms=1000)
        swept = amm()
        swept["quote_reserves_atoms"] -= 3000
        for side, amount in (("buy", 10_000), ("buy_exact_out", 10_000), ("sell", 10_000)):
            a, b = quote(with_fees, side, amount), quote(swept, side, amount)
            for key in ("debit_atoms", "received_atoms", "price_impact_bps"):
                self.assertEqual(a[key], b[key])
        market = amm(virtual_quote_reserves_atoms=10_000_000)
        market["quote_reserves_atoms"] = 1
        with self.assertRaisesRegex(ValueError, "REAL_QUOTE"):
            quote(market, "sell", 1000)

    def test_v2_retained_fees_do_not_change_effective_liquidity(self):
        v1 = amm()
        v1.update(creator_fee_bps=30)
        v2 = {**v1, "trade_v2": True, "buyback_bps": 2000}
        for side in ("buy", "sell"):
            first, second = quote(v1, side, 10_000), quote(v2, side, 10_000)
            self.assertEqual(first["debit_atoms"], second["debit_atoms"])
            self.assertEqual(first["received_atoms"], second["received_atoms"])
            a, b = first["post_market"], second["post_market"]
            self.assertEqual(int(a["quote_reserves_atoms"]),
                             int(b["quote_reserves_atoms"]) + int(b["virtual_quote_reserves_atoms"]))
            self.assertLess(int(b["virtual_quote_reserves_atoms"]), 0)

    def test_dynamic_schedule_canonical_stable_exotic_and_override(self):
        def rates(lp, protocol, creator):
            return dict(lp_fee_bps=lp, protocol_fee_bps=protocol, creator_fee_bps=creator)
        config = {"flat_fees": rates(25, 5, 0),
                  "fee_tiers": [{"market_cap_lamports_threshold": 0, "fees": rates(30, 20, 10)},
                                {"market_cap_lamports_threshold": 20_000_000, "fees": rates(20, 10, 5)}],
                  "stable_fee_tiers": [{"market_cap_lamports_threshold": 0, "fees": rates(100, 50, 20)}],
                  "exotic_flat_fees": rates(200, 100, 0)}
        market = amm(fee_config=config, is_pump_pool=True, mint_supply_atoms=10_000_000)
        self.assertEqual(quote(market, "buy", 10000)["fee_rates"], rates(20, 10, 5))
        market["quote_mint"] = USDC_MINT
        self.assertEqual(quote(market, "buy", 10000)["fee_rates"], rates(100, 50, 20))
        market["quote_mint"] = "other"
        self.assertEqual(quote(market, "buy", 10000)["fee_rates"], rates(200, 100, 0))
        market.update(is_pump_pool=False, creator_fee_configurable=True,
                      configured_creator_fee_bps=7)
        self.assertEqual(quote(market, "buy", 10000)["fee_rates"], rates(25, 5, 7))
        market["configured_creator_fee_bps"] = 0
        self.assertEqual(quote(market, "buy", 10000)["fee_rates"], rates(25, 5, 0))
        del market["is_pump_pool"]
        with self.assertRaisesRegex(ValueError, "CLASSIFICATION"):
            quote(market, "buy", 10000)
        curve_market = curve(fee_config=config)
        result = quote(curve_market, "buy", 10000)
        self.assertEqual(result["fee_rates"]["lp_fee_bps"], 0)

    def test_fee_sweep_exact_in_budget_and_nonnegative_post_state(self):
        for protocol in (0, 1, 20, 100, 3000):
            for creator in (0, 1, 30, 2000):
                for lp in (0, 1, 30):
                    market = amm()
                    market.update(protocol_fee_bps=protocol, creator_fee_bps=creator, lp_fee_bps=lp)
                    for budget in (100, 1000, 10000):
                        result = quote(market, "buy", budget, 0)
                        self.assertLessEqual(int(result["debit_atoms"]), budget)
                        self.assertGreater(int(result["received_atoms"]), 0)
                        self.assertTrue(Decimal(result["price_impact_bps"]).is_finite())
                        validate_market(result["post_market"])
        for budget in (10, 100, 1000, 10000):
            market = curve(protocol_fee_bps=1, creator_fee_bps=1)
            result = quote(market, "buy", budget, 0)
            self.assertLessEqual(int(result["debit_atoms"]), budget)

    def test_exact_out_matches_bruteforce_at_rounding_discontinuities(self):
        market = amm()
        market.update(base_reserves_atoms=100, quote_reserves_atoms=30_000,
                      lp_fee_bps=100, protocol_fee_bps=100, creator_fee_bps=100)
        # Check every input below each returned debit. Fee ceil boundaries can
        # reduce net output locally; inverse quotes still find first valid input.
        for target in (1, 287, 288, 3000, 9699, 9700, 9701, 15000):
            inverse = quote(market, "sell_exact_out", target, 0)
            debit = int(inverse["debit_atoms"])
            self.assertGreaterEqual(int(inverse["received_atoms"]), target)
            for amount in range(1, debit):
                try:
                    previous = quote(market, "sell", amount, 0)
                except ValueError:
                    continue
                self.assertLess(int(previous["received_atoms"]), target)

    def test_invalid_unsupported_overflow_and_no_input_mutation(self):
        original = amm()
        frozen = deepcopy(original)
        quote(original, "buy", 10_000)
        self.assertEqual(original, frozen)
        for amount in (True, 1.5, "100", 0, -1, U64_MAX + 1):
            with self.assertRaises(ValueError):
                quote(original, "buy", amount)
        for slip in (True, -1, 10000, 1.5):
            with self.assertRaises(ValueError):
                quote(original, "buy", 100, slip)
        for changes in ({"lp_fee_bps": True}, {"base_reserves_atoms": 0},
                        {"virtual_quote_reserves_atoms": -2_000_001},
                        {"virtual_quote_reserves_atoms": U64_MAX},
                        {"quote_reserves_atoms": U64_MAX, "virtual_quote_reserves_atoms": 1},
                        {"is_mayhem_mode": True}, {"cashback": True}, {"multi_hop": True}):
            with self.assertRaises(ValueError):
                quote({**original, **changes}, "buy", 100)
        with self.assertRaisesRegex(ValueError, "MIGRATION"):
            quote(curve(real_base_reserves_atoms=10), "buy_exact_out", 11)
        with self.assertRaisesRegex(ValueError, "CURVE_V3"):
            quote(curve(instruction_version=3), "buy", 100)
        with self.assertRaisesRegex(ValueError, "REAL_QUOTE"):
            quote(curve(real_quote_reserves_atoms=0), "sell", 100)
        self.assertEqual(quote({**original, "protocol_fee_bps": 0, "lp_fee_bps": 0},
                               "buy_exact_out", 10000)["fee_breakdown"]["protocol_atoms"], "0")


if __name__ == "__main__":
    unittest.main()
