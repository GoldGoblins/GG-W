"""Offline market refresh, cache coherence and untrusted-data regressions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_contract as contract, crypto_data as data, crypto_market as market

NOW = 1_700_002_800 + 5_000 * 3600


def frame(n=400, *, now=NOW):
    return {"times": [now - (n-i)*3600 for i in range(n)],
            "opens": [100.] * n, "highs": [102.] * n,
            "lows": [98.] * n, "closes": [101.] * n, "volumes": [50.] * n,
            "source": "binance-spot", "symbol": "SOLUSDT", "closed_only": True}


class MarketRefreshTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="gg-market-refresh-")
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        for change in (patch.object(contract, "STATE_DIR", self.state),
                       patch.object(market.time, "time", return_value=NOW),
                       patch.object(socket.socket, "connect", side_effect=OSError("OFFLINE_TEST")),
                       patch.object(socket.socket, "connect_ex", side_effect=OSError("OFFLINE_TEST")),
                       patch.object(socket, "create_connection", side_effect=OSError("OFFLINE_TEST"))):
            change.start()
            self.addCleanup(change.stop)
        with market._recent_memory_lock:
            market._recent_memory.clear()

    def test_recent_tape_metadata_and_fetch_provenance_match_trimmed_data(self):
        saved = market._save(frame(800), "SOLUSDT", "1h")
        with patch.object(market, "_request", side_effect=AssertionError("Unexpected download")):
            result = market.recent("SOLUSDT", "1h")
        self.assertEqual(len(result["times"]), 400)
        self.assertEqual(result["bar_count"], 400)
        self.assertEqual(result["from"], data.iso(result["times"][0]))
        self.assertEqual(result["to"], data.iso(result["times"][-1] + 3600))
        self.assertEqual(result["fetched_at"], saved["fetched_at"])
        self.assertEqual(result["quote_currency"], "USDT")
        self.assertEqual(result["base_currency"], "SOL")

    def test_cached_hits_do_not_reparse_disk_and_return_independent_tapes(self):
        market._save(frame(), "SOLUSDT", "1h")
        original = market.recent("SOLUSDT", "1h")
        original["closes"][0] = -1
        with patch.object(Path, "open", side_effect=AssertionError("Cache reread")), \
             patch.object(market, "_request", side_effect=AssertionError("Cache download")):
            result = market.recent("SOLUSDT", "1h")
        self.assertEqual(result["closes"][0], 101.)

    def test_concurrent_paper_workers_share_one_download(self):
        entered, release = threading.Event(), threading.Event()
        def fetch(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return frame()
        with patch.object(market, "_request", side_effect=fetch) as request, ThreadPoolExecutor(max_workers=5) as pool:
            tasks = [pool.submit(market.recent, "SOLUSDT", "1h") for _ in range(5)]
            self.assertTrue(entered.wait(1))
            release.set()
            results = [task.result(timeout=3) for task in tasks]
        self.assertEqual(request.call_count, 1)
        self.assertTrue(all(result["fetched_at"] == NOW for result in results))
        results[0]["closes"][0] = -1
        self.assertTrue(all(result["closes"][0] == 101 for result in results[1:]))

    def test_new_closed_candle_invalidates_memory_and_disk_hits(self):
        market._save(frame(), "SOLUSDT", "1h")
        market.recent("SOLUSDT", "1h")
        with patch.object(market.time, "time", return_value=NOW + 3600), \
             patch.object(market, "_request", return_value=frame(now=NOW + 3600)) as request:
            result = market.recent("SOLUSDT", "1h")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["times"][-1], NOW)
        self.assertEqual(result["fetched_at"], NOW + 3600)

    def test_external_cache_replacement_is_observed(self):
        market._save(frame(), "SOLUSDT", "1h")
        market.recent("SOLUSDT", "1h")
        changed = frame(399)
        changed["closes"][-1] = 100
        market._save(changed, "SOLUSDT", "1h")
        with patch.object(market, "_request", side_effect=AssertionError("Unexpected download")):
            result = market.recent("SOLUSDT", "1h")
        self.assertEqual(result["closes"][-1], 100)
        self.assertEqual(result["bar_count"], 399)

    def test_stale_feed_never_relabels_or_replaces_previous_evidence(self):
        stale = frame(now=NOW - 3600)
        market._save(stale, "SOLUSDT", "1h")
        path = market._cache_path("SOLUSDT", "1h")
        previous = path.read_bytes()
        with patch.object(market, "_request", return_value=stale), self.assertRaisesRegex(ValueError, "STALE"):
            market.recent("SOLUSDT", "1h")
        self.assertEqual(path.read_bytes(), previous)

    def test_wrong_provider_pair_and_malformed_cache_do_not_become_trusted(self):
        path = market._cache_path("SOLUSDT", "1h")
        for payload in ([], {**frame(), "data_version": data.HISTORY_VERSION, "symbol": "KASUSDT"}):
            with self.subTest(payload_type=type(payload).__name__):
                path.write_text(json.dumps(payload), encoding="utf-8")
                with patch.object(market, "_request", return_value=frame()) as request:
                    result = market.recent("SOLUSDT", "1h")
                self.assertEqual(request.call_count, 1)
                self.assertEqual(result["symbol"], "SOLUSDT")
        bad = dict(frame(), source="other-provider")
        path.unlink()
        with patch.object(market, "_request", return_value=bad), self.assertRaisesRegex(ValueError, "INTEGRITY"):
            market.recent("SOLUSDT", "1h")

    def test_history_rejects_impossible_budget_before_download(self):
        with patch.object(market, "_request", side_effect=AssertionError("Wasted history download")):
            with self.assertRaisesRegex(ValueError, "PAGE_BUDGET"):
                market.history("SOLUSDT", "1h", NOW - 40_001 * 3600)
            for budget in (0, True, 41, 1.5):
                with self.assertRaisesRegex(ValueError, "PAGE_BUDGET"):
                    market.history("SOLUSDT", "1h", NOW - 120 * 3600, max_pages=budget)

    def test_history_rejects_wrong_window_and_retains_previous_cache(self):
        market._save(frame(), "SOLUSDT", "1h")
        path = market._cache_path("SOLUSDT", "1h")
        previous = path.read_bytes()
        outside = frame(121)
        with patch.object(market, "_request", return_value=outside), self.assertRaisesRegex(ValueError, "RESPONSE_RANGE"):
            market.history("SOLUSDT", "1h", NOW - 120 * 3600)
        self.assertEqual(path.read_bytes(), previous)

    def test_valid_history_records_actual_fetch_time(self):
        with patch.object(market, "_request", return_value=frame(120)):
            result = market.history("SOLUSDT", "1h", NOW - 120 * 3600)
        self.assertEqual(result["bar_count"], 120)
        self.assertEqual(result["fetched_at"], NOW)
        self.assertEqual(result["quote_currency"], "USDT")
        self.assertEqual(result["base_currency"], "SOL")
        self.assertEqual(json.loads(market._cache_path("SOLUSDT", "1h").read_bytes())["fetched_at"], NOW)

    def test_parser_rejects_conflicting_duplicate_candles_and_bad_timestamp(self):
        row = [(NOW - 3600) * 1000, "100", "102", "98", "101", "50", NOW * 1000 - 1]
        conflicting = row[:]
        conflicting[4] = "100"
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            market.parse([row, conflicting], "SOLUSDT", "1h")
        for timestamp in (True, row[0] + 1, float("nan"), str(row[0]) + ".5"):
            bad = [timestamp, *row[1:]]
            with self.subTest(timestamp_type=type(timestamp).__name__), self.assertRaises(ValueError):
                market.parse([bad], "SOLUSDT", "1h")

    def test_gate_candles_preserve_quote_and_base_currency_without_peg_assumption(self):
        row = [str(NOW - 3600), "9000", "100", "102", "98", "101", "90", "true"]
        result = market.parse([row], "KASUSDT", "1h")
        self.assertEqual(result["quote_currency"], "USDT")
        self.assertEqual(result["base_currency"], "KAS")

    def test_frame_normalizes_numeric_strings_without_mutating_input(self):
        raw = frame(96)
        for key in ("opens", "highs", "lows", "closes", "volumes", "times"):
            raw[key] = [str(value) for value in raw[key]]
        original = copy.deepcopy(raw)
        result = data.validate_frame(raw, "1h")
        self.assertIsInstance(result["closes"][0], float)
        self.assertIsInstance(result["times"][0], int)
        self.assertEqual(result["highs"][0] - result["lows"][0], 4)
        self.assertEqual(raw, original)

    def test_frame_rejects_boolean_prices_fractional_times_and_empty_tape(self):
        for field, value in (("closes", True), ("opens", False), ("volumes", True),
                             ("times", True), ("times", NOW - 3600 + .5), ("times", float("inf"))):
            raw = frame(96)
            raw[field][-1] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                data.validate_frame(raw, "1h")
        with self.assertRaises(ValueError):
            data.validate_frame({key: [] for key in ("highs", "lows", "closes", "volumes", "times")}, "1h", min_bars=0)

    def test_freshness_marks_malformed_future_and_wrong_interval_stale(self):
        for fetched in (None, "bad", [], True, -1, float("nan"), float("inf"), NOW + 1):
            with self.subTest(fetched_type=type(fetched).__name__):
                meta = data.freshness({"fetched_at": fetched, "interval": "1h"})
                self.assertTrue(meta["stale"])
                self.assertIsNone(meta["age_seconds"])
                json.dumps(meta, allow_nan=False)
        matched = data.freshness({"fetched_at": NOW - 10, "interval": "1h"})
        self.assertFalse(matched["stale"])
        self.assertEqual(matched["age_seconds"], 10)
        wrong = data.freshness({"fetched_at": NOW, "interval": "1d", "requested_interval": "4h"})
        self.assertTrue(wrong["stale"])
        self.assertFalse(wrong["interval_match"])
        for ttl in (float("nan"), "invalid", -1, True):
            self.assertTrue(data.freshness({"fetched_at": NOW}, ttl)["stale"])

    def test_memory_cache_bound_and_hot_snapshot_latency(self):
        for index in range(len(market._RECENT_LOCKS) + 2):
            with patch.object(contract, "STATE_DIR", self.state / str(index)):
                market._save(frame(), "SOLUSDT", "1h")
                market.recent("SOLUSDT", "1h")
        self.assertLessEqual(len(market._recent_memory), len(market._RECENT_LOCKS))
        market._save(frame(), "SOLUSDT", "1h")
        market.recent("SOLUSDT", "1h")
        started = time.perf_counter()
        for _ in range(100):
            market.recent("SOLUSDT", "1h")
        # A broad regression threshold, not a claim about application frame rate.
        self.assertLess(time.perf_counter() - started, .5)


if __name__ == "__main__":
    unittest.main(argv=[__file__], verbosity=2)
