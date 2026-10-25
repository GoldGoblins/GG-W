from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.crypto_pump_paper import execute, new_state, replay, snapshot, validate_state
from backend.crypto_pump_quotes import quote


def market(**changes):
    result = dict(kind="amm", market_id="recorded-pool", base_mint="recorded-mint",
                  timestamp_ms=1000, base_reserves_atoms=1_000_000,
                  quote_reserves_atoms=2_000_000, base_decimals=6, quote_decimals=9,
                  protocol_fee_bps=20, creator_fee_bps=0, lp_fee_bps=30)
    result.update(changes)
    return result


class PumpPaperTests(unittest.TestCase):
    def test_roundtrip_cash_positions_fees_and_realized_cost_basis(self):
        initial = new_state(100_000)
        frozen = deepcopy(initial)
        bought = execute(initial, market(), "buy_exact_out", 10_000, timestamp_ms=1000)
        self.assertEqual(initial, frozen)
        self.assertEqual(bought["state"]["cash_atoms"], "79695")
        self.assertEqual(bought["state"]["positions"]["recorded-pool"]["base_atoms"], "10000")
        sold = execute(bought["state"], bought["post_market"], "sell", 10_000, timestamp_ms=1000)
        self.assertEqual(sold["state"]["positions"], {})
        self.assertLess(int(sold["state"]["cash_atoms"]), 100_000)
        self.assertEqual(int(sold["state"]["realized_pnl_atoms"]),
                         int(sold["state"]["cash_atoms"]) - 100_000)
        self.assertEqual(snapshot(sold["state"])["equity_atoms"], sold["state"]["cash_atoms"])
        self.assertEqual(len(sold["state"]["fills"]), 2)

    def test_partial_sell_cost_basis_and_cash_balance(self):
        bought = execute(new_state(100_000), market(), "buy_exact_out", 10_000, timestamp_ms=1000)
        sold = execute(bought["state"], bought["post_market"], "sell", 5000, timestamp_ms=1000)
        pos = sold["state"]["positions"]["recorded-pool"]
        self.assertEqual(pos["base_atoms"], "5000")
        self.assertEqual(pos["cost_atoms"], "10153")
        self.assertEqual(int(sold["fill"]["realized_pnl_atoms"]),
                         int(sold["fill"]["received_atoms"]) - 10152)

    def test_unknown_liquidation_marks_never_become_zero(self):
        bought = execute(new_state(100_000), market(), "buy", 20_000, timestamp_ms=1000)
        unknown = snapshot(bought["state"])
        self.assertIsNone(unknown["equity_atoms"])
        self.assertEqual(unknown["unpriced_positions"], ["recorded-pool"])
        known = snapshot(bought["state"], {"recorded-pool": bought["post_market"]})
        self.assertIsNotNone(known["equity_atoms"])
        self.assertLess(int(known["equity_atoms"]), 100_000)
        future = snapshot(bought["state"], {"recorded-pool": market(timestamp_ms=2000)})
        self.assertIsNone(future["equity_atoms"])
        virtual_only = {**bought["post_market"], "quote_reserves_atoms": "1",
                        "virtual_quote_reserves_atoms": "2000000"}
        self.assertIsNone(snapshot(bought["state"], {"recorded-pool": virtual_only})["equity_atoms"])

    def test_slippage_requote_and_no_mutation_on_failure(self):
        initial = new_state(100_000)
        expected = quote(market(), "buy_exact_out", 10000, 100)
        slight = market(quote_reserves_atoms=2_010_000)
        fill = execute(initial, slight, "buy_exact_out", 10000, timestamp_ms=1000,
                       expected_quote=expected)
        self.assertGreater(int(fill["fill"]["slippage_cost_atoms"]), 0)
        frozen = deepcopy(initial)
        with self.assertRaisesRegex(ValueError, "SLIPPAGE"):
            execute(initial, market(quote_reserves_atoms=3_000_000), "buy_exact_out", 10000,
                    timestamp_ms=1000, expected_quote=expected)
        self.assertEqual(initial, frozen)
        with self.assertRaisesRegex(ValueError, "CASH"):
            execute(new_state(1), market(), "buy_exact_out", 10000, timestamp_ms=1000)
        with self.assertRaisesRegex(ValueError, "POSITION"):
            execute(initial, market(), "sell", 10000, timestamp_ms=1000)

    def test_replay_uses_only_ordered_recorded_snapshots(self):
        bought = execute(new_state(100000), market(), "buy_exact_out", 10000, timestamp_ms=1000)
        tape = [dict(timestamp_ms=1000, market=market(), side="buy_exact_out", amount_atoms=10000),
                dict(timestamp_ms=1001, market=bought["post_market"], side="sell", amount_atoms=10000)]
        replayed = replay(new_state(100000), tape)
        self.assertEqual(replayed["summary"]["fill_count"], 2)
        self.assertEqual(replayed["summary"]["positions"], {})
        self.assertLess(int(replayed["summary"]["equity_atoms"]), 100000)
        with self.assertRaisesRegex(ValueError, "FUTURE"):
            replay(new_state(100000), [{**tape[0], "timestamp_ms": 999}])
        with self.assertRaisesRegex(ValueError, "REVERSED"):
            replay(new_state(100000), [tape[0], {**tape[1], "timestamp_ms": 999}])
        with self.assertRaisesRegex(ValueError, "STALE"):
            execute(new_state(100000), market(), "buy", 1000, timestamp_ms=62000)
        with self.assertRaisesRegex(ValueError, "EVENT_LIMIT"):
            replay(new_state(100000), [{}] * 2001)

    def test_corrupt_state_and_changed_targets_fail_closed(self):
        state = new_state(100000)
        for changes in ({"cash_atoms": True}, {"cash_atoms": "NaN"},
                        {"mode": "LIVE"}, {"fills": [{}]}, {"positions": []}):
            with self.assertRaises(ValueError):
                validate_state({**state, **changes})
        with self.assertRaisesRegex(ValueError, "QUOTE_MISMATCH"):
            execute(state, market(quote_mint="different"), "buy", 1000, timestamp_ms=1000)
        bought = execute(state, market(), "buy", 1000, timestamp_ms=1000)
        with self.assertRaisesRegex(ValueError, "TARGET_CHANGED"):
            execute(bought["state"], market(base_mint="different"), "buy", 1000, timestamp_ms=1000)


if __name__ == "__main__":
    unittest.main()
