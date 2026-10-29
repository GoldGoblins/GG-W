"""Portfolio amounts, quote coverage and 24-hour labels, without network/state."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.crypto_portfolio import change_24h, summarize


class PortfolioTest(unittest.TestCase):
    def setUp(self):
        self.chart = {"price": 100, "source": "fixture", "stale": False,
                      "closes": [100 + i for i in range(25)],
                      "times": [1700000000 + i * 3600 for i in range(25)]}
        self.sol = {"symbol": "SOL", "mint": "native", "display": "2.000000001"}

    def test_value_partial_coverage_and_fx(self):
        data = summarize([self.sol, {"symbol": "OTHER", "mint": "unpriced", "display": "8"}], self.chart, usd_sek=10)
        self.assertAlmostEqual(data["value_usd"], 200.0000001)
        self.assertAlmostEqual(data["value_sek"], 2000.000001)
        self.assertEqual(data["priced_count"], 1)
        self.assertEqual(data["unpriced_count"], 1)
        self.assertFalse(data["complete"])
        self.assertIsNone(data["assets"][1]["value_usd"])

    def test_no_prices_and_zero_balance_are_distinct(self):
        self.assertIsNone(summarize([self.sol], {})["value_usd"])
        self.assertIsNone(summarize([], self.chart)["value_usd"])
        result = summarize([dict(self.sol, display="0")], self.chart)
        self.assertEqual(result["value_usd"], 0)
        self.assertTrue(result["complete"])
        self.assertIsNone(result["value_sek"])

    def test_native_ticker_cannot_price_an_unrelated_mint(self):
        spoof = dict(self.sol, mint="fake-sol-mint")
        self.assertIsNone(summarize([spoof], self.chart)["assets"][0]["price_usd"])

    def test_token_requires_its_own_quote_source_no_stablecoin_peg(self):
        token = {"symbol": "USDC", "mint": "usd", "display": "100", "price_usd": 0.92}
        self.assertIsNone(summarize([token], self.chart)["value_usd"])
        token.update(price_source="fixture", price_stale=False)
        self.assertEqual(summarize([token], self.chart)["value_usd"], 92)

    def test_merge_accounts_by_mint_not_ticker(self):
        tokens = [{"symbol": "DUP", "mint": mint, "display": qty, "price_usd": 2, "price_source": "fixture", "price_stale": False}
                  for mint, qty in [("a", "1.000000001"), ("a", "2.000000002"), ("b", "8")]]
        data = summarize(tokens, self.chart)
        self.assertEqual(len(data["assets"]), 2)
        self.assertEqual(data["assets"][1]["quantity_text"], "3.000000003")
        self.assertAlmostEqual(data["value_usd"], 22.000000006)
        tokens[1]["price_usd"] = 3
        self.assertEqual(summarize(tokens, self.chart)["unpriced_count"], 1)

    def test_dust_and_full_precision_quantity(self):
        data = summarize([{"symbol":"DUST", "mint":"dust", "display":"0.000000000000000123", "price_usd":0.00000004, "price_source":"fixture"}], self.chart)
        self.assertEqual(data["assets"][0]["quantity_text"], "0.000000000000000123")
        self.assertGreater(data["value_usd"], 0)

    def test_invalid_balances_or_quotes_are_not_zero(self):
        for value in ["—", None, "NaN", "Infinity", "-1"]:
            with self.subTest(value=value):
                data = summarize([dict(self.sol, display=value)], self.chart)
                self.assertIsNone(data["value_usd"])
                self.assertEqual(data["unknown_balance_count"],1)
                self.assertEqual(data["priced_count"],1)
                self.assertEqual(data["valued_count"],0)
        for value in ["NaN", "Infinity", "-1", "0"]:
            chart = dict(self.chart, price=value, closes=[])
            self.assertIsNone(summarize([self.sol], chart)["value_usd"])

    def test_24h_requires_matching_timestamps(self):
        self.assertEqual(change_24h(self.chart), 24)
        self.assertIsNone(change_24h(dict(self.chart, times=[])))
        self.assertIsNone(change_24h(dict(self.chart, times=self.chart["times"][1:], closes=self.chart["closes"][1:])))
        daily = {"times":[1,86401], "closes":[100,80]}
        self.assertEqual(change_24h(daily), -20)
        self.assertIsNone(summarize([self.sol],dict(self.chart,source=""))["change_24h_pct"])

    def test_stale_quotes_remain_marked(self):
        data = summarize([self.sol], dict(self.chart, stale=True))
        self.assertEqual(data["stale_count"], 1)
        self.assertTrue(data["assets"][0]["stale"])
        self.assertEqual(data["change_24h_pct"], 24)

    def test_kas_is_a_separate_valuation_no_input_mutation(self):
        holdings = [{"symbol":"KAS", "mint":"native", "display":"12"}]
        before = copy.deepcopy(holdings)
        data = summarize(holdings, {"price":0.1,"source":"fixture"}, native_symbol="KAS")
        self.assertEqual(data["value_usd"], 1.2)
        self.assertEqual(holdings, before)
        self.assertEqual(data["assets"][0]["name"], "Kaspa")

    def test_host_delivers_separate_portfolios_and_keeps_asset_selection(self):
        from backend import crypto_host as host
        with patch.multiple(host,
                load_wallet=lambda: {"pubkey":"offline-public-fixture", "balance_lamports":2_000_000_000},
                _bundle=lambda *args, **kwargs: (None,[{"symbol":"OTHER","mint":"unpriced","display":"8"}]),
                chart_snapshot=lambda: self.chart,
                quote_for_wallet=lambda wallet: {"usd":"$200.00","usd_sek":10},
                kas_chart_snapshot=lambda: {"price":0.1,"source":"fixture"},
                portfolio_asset=lambda: "KAS",
                read_ledger=lambda *args: []), \
             patch.object(host.kaspa_covenant,"snapshot",return_value={"value_kas":"4", "network":"paper"}), \
             patch.object(host.crypto_trader,"read_lots",return_value=[]):
            result=host.status_payload()["portfolio"]
        self.assertEqual(result["asset"],"KAS")
        self.assertEqual(result["sol"]["value_usd"],200)
        self.assertEqual(result["sol"]["unpriced_count"],1)
        self.assertEqual(result["kas"]["value_usd"],0.4)


if __name__ == "__main__":
    unittest.main(argv=["test_crypto_portfolio"])
