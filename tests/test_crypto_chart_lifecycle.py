"""Delayed public-feed fixtures exercise chart selection and worker recovery."""
from pathlib import Path
import copy
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import crypto_host as host, crypto_data


class ChartLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.cache = {"closes": [], "times": [], "ts": 0., "fetched_at": 0.,
                      "requested_interval": "15m", "interval": "15m", "price": "",
                      "source": "", "error": "", "usd_sek": 0.}
        self.stamps = [1_700_000_000 + i * 900 for i in range(80)]
        for change in (patch.dict(host._chart_cache, copy.deepcopy(self.cache), clear=True),
                       patch.dict(host._kas_chart_cache, copy.deepcopy(self.cache), clear=True),
                       patch.object(host, "_chart_refresh_running", set()),
                       patch.object(host, "_chart_refresh_pending", set()),
                       patch.object(host, "_chart_refresh_tokens", {}),
                       patch.dict(host._kline_times, {}, clear=True),
                       patch.object(host, "_load_chart_disk"), patch.object(host, "_load_kas_chart_disk"),
                       patch.object(host, "_save_chart_disk"), patch.object(host, "_save_kas_chart_disk"),
                       patch.object(host, "_usd_sek_rate", return_value=0.),
                       patch.object(host, "status_payload", return_value={}),
                       patch.object(socket.socket, "connect", side_effect=OSError("OFFLINE_TEST")),
                       patch.object(socket.socket, "connect_ex", side_effect=OSError("OFFLINE_TEST")),
                       patch.object(socket, "create_connection", side_effect=OSError("OFFLINE_TEST"))):
            change.start()
            self.addCleanup(change.stop)

    def wait(self, condition, seconds=2):
        until = time.monotonic() + seconds
        while not condition() and time.monotonic() < until:
            time.sleep(.002)
        self.assertTrue(condition(), "Offline chart worker did not finish")

    def test_sol_interval_switch_discards_old_result_and_fetches_requested_tape(self):
        entered, release = threading.Event(), threading.Event()
        calls, published = [], []
        def fetch(interval, *args, **kwargs):
            calls.append(interval)
            host._kline_times[interval] = self.stamps
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(2))
            price = 100. if interval == "15m" else 200.
            return [price + 2] * 80, [price - 2] * 80, [price] * 80, [1.] * 80
        with patch.object(host, "fetch_klines", side_effect=fetch), \
             patch.object(host, "_save_chart_disk", side_effect=lambda: published.append(host._chart_cache["interval"])):
            host.request_chart_refresh("SOL")
            self.assertTrue(entered.wait(1))
            try:
                host.set_chart_interval("1h")
            finally:
                release.set()
            self.wait(lambda: "SOL" not in host._chart_refresh_running)
        self.assertEqual(calls, ["15m", "1h"])
        self.assertTrue(published)
        self.assertTrue(all(interval == "1h" for interval in published))
        self.assertEqual(host._chart_cache["interval"], "1h")
        self.assertEqual(host._chart_cache["requested_interval"], "1h")
        self.assertEqual(host._chart_cache["closes"][-1], 200.)

    def test_kas_interval_switch_discards_old_result_and_preserves_fetch_time(self):
        entered, release = threading.Event(), threading.Event()
        calls, published = [], []
        fetched_at = time.time() - 5
        def fetch(pair, interval):
            self.assertEqual(pair, "KASUSDT")
            calls.append(interval)
            if len(calls) == 1:
                entered.set()
                self.assertTrue(release.wait(2))
            price = .1 if interval == "15m" else .2
            return {"closes": [price] * 80, "times": self.stamps,
                    "source": "gate-spot", "fetched_at": fetched_at}
        with patch.object(host.crypto_market, "recent", side_effect=fetch), \
             patch.object(host, "_save_kas_chart_disk", side_effect=lambda: published.append(host._kas_chart_cache["interval"])):
            host.request_chart_refresh("KAS")
            self.assertTrue(entered.wait(1))
            try:
                host.set_kas_chart_interval("1h")
            finally:
                release.set()
            self.wait(lambda: "KAS" not in host._chart_refresh_running)
        self.assertEqual(calls, ["15m", "1h"])
        self.assertTrue(all(interval == "1h" for interval in published))
        self.assertEqual(host._kas_chart_cache["closes"][-1], .2)
        snapshot = host.kas_chart_snapshot()
        self.assertEqual(snapshot["fetched_at"], fetched_at)
        self.assertEqual(snapshot["quote_currency"], "USDT")
        self.assertEqual(snapshot["requested_interval"], "1h")

    def test_sol_coarse_fallback_stays_explicit_and_does_not_hammer_provider(self):
        host._chart_cache["requested_interval"] = "1h"
        daily = [1_700_000_000 + i * 86400 for i in range(80)]
        with patch.object(host, "fetch_klines", side_effect=RuntimeError("OFFLINE_TEST")), \
             patch.object(host, "_coingecko_sol_chart", return_value=([100.] * 80, daily)) as provider:
            first = host.cached_sol_chart()
            second = host.cached_sol_chart()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(first["interval"], "1d")
        self.assertEqual(second["requested_interval"], "1h")
        self.assertFalse(second["interval_match"])
        self.assertTrue(second["stale"])

    def test_kas_coarse_fallback_stays_explicit_and_does_not_hammer_provider(self):
        host._kas_chart_cache["requested_interval"] = "1m"
        with patch.object(host.crypto_market, "recent", side_effect=RuntimeError("OFFLINE_TEST")), \
             patch.object(host, "_coingecko_kas_chart", return_value=([.1] * 80, self.stamps, "5m")) as provider:
            first = host.cached_kas_chart()
            second = host.cached_kas_chart()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(first["interval"], "5m")
        self.assertEqual(second["requested_interval"], "1m")
        self.assertFalse(second["interval_match"])
        self.assertTrue(second["stale"])

    def test_chart_thread_start_failure_releases_ownership_for_retry(self):
        for asset in ("SOL", "KAS"):
            with self.subTest(asset=asset), patch.object(threading.Thread, "start", side_effect=RuntimeError("OFFLINE_TEST")):
                try:
                    host.request_chart_refresh(asset)
                except RuntimeError:
                    pass
            self.assertNotIn(asset, host._chart_refresh_running)
            self.assertNotIn(asset, host._chart_refresh_pending)
            self.assertNotIn(asset, host._chart_refresh_tokens)

    def test_corrupt_disk_timestamps_and_prices_never_poison_status(self):
        valid = {"closes": [100., 101.], "times": [1_700_000_000, 1_700_000_900],
                 "fetched_at": time.time(), "source": "binance", "interval": "15m"}
        with tempfile.TemporaryDirectory(prefix="gg-chart-disk-") as directory:
            path = Path(directory) / "chart.json"
            for fetched in ("invalid-clock", float("nan"), float("inf"), -1, time.time() + 60):
                with self.subTest(fetched_type=type(fetched).__name__):
                    path.write_text(json.dumps(dict(valid, fetched_at=fetched)), encoding="utf-8")
                    restored = host._chart_disk_state(path, 5000)
                    self.assertTrue(restored is None or crypto_data.freshness(restored)["stale"])
            for price in (float("nan"), float("inf"), -1, True):
                with self.subTest(price_type=type(price).__name__):
                    path.write_text(json.dumps(dict(valid, closes=[100., price])), encoding="utf-8")
                    self.assertIsNone(host._chart_disk_state(path, 5000))
            path.write_text(json.dumps(dict(valid, times=[1_700_000_000, 1_700_000_000])), encoding="utf-8")
            restored = host._chart_disk_state(path, 5000)
            self.assertTrue(restored is None or crypto_data.freshness(restored)["stale"])
            path.write_bytes(b" " * (2 * 1024 * 1024 + 1))
            self.assertIsNone(host._chart_disk_state(path, 5000))

    def test_worker_launch_failure_releases_factory_desk_paper_and_backtest_jobs(self):
        for start, job in ((host.start_strategy_factory, host._strategy_factory_job),
                           (host.start_desk, host._desk_job),
                           (host.start_backtest_trader, host._backtest_job)):
            with self.subTest(job=start.__name__), \
                 patch.dict(job, {"state": "idle", "note": "", "started": 0., "result": {}}, clear=True), \
                 patch.object(host.crypto_bots, "selected", return_value="gg"), \
                 patch.object(host, "paper_pair", return_value="SOLUSDT"), \
                 patch.object(threading.Thread, "start", side_effect=RuntimeError("OFFLINE_TEST")):
                try:
                    start()
                except RuntimeError:
                    pass
                self.assertNotEqual(job["state"], "running")
        with patch.dict(host._paper_tick_jobs, {"trader": {"state": "idle", "note": ""}}, clear=True), \
             patch.object(threading.Thread, "start", side_effect=RuntimeError("OFFLINE_TEST")):
            try:
                host.start_paper_tick("trader")
            except RuntimeError:
                pass
            self.assertNotEqual(host._paper_tick_jobs["trader"]["state"], "running")

    def test_rpc_worker_launch_failure_releases_inflight_and_reports_unavailable(self):
        key = ("1" * 32, "testnet")
        with patch.dict(host._rpc_bundle, {}, clear=True), \
             patch.dict(host._rpc_errors, {}, clear=True), \
             patch.dict(host._rpc_retry_after, {}, clear=True), \
             patch.object(host, "_rpc_inflight", set()), \
             patch.object(threading.Thread, "start", side_effect=RuntimeError("OFFLINE_TEST")):
            try:
                host._bundle(*key)
            except RuntimeError:
                pass
            self.assertNotIn(key, host._rpc_inflight)
            self.assertTrue(host._rpc_errors.get(key))


if __name__ == "__main__":
    unittest.main(argv=[__file__], verbosity=2)
