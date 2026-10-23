"""Behavior regressions for the five CRYPTO improvement areas. Offline only."""
from __future__ import annotations
import copy
import json
import math
import tempfile
import threading
import time
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from backend import (crypto_backtest as bt, crypto_bots, crypto_contract as contract,
    crypto_data, crypto_desk as desk, crypto_host as host, crypto_hybrid as hybrid,
    crypto_optimal, crypto_strategy_factory as factory, crypto_trader, crypto_tx as tx,
    crypto_vol, polymarket_research as poly)


def frame(n=240, step=3600):
    prices = [100 + 3 * math.sin(i / 7) + i * .03 for i in range(n)]
    return {"highs": [p+1 for p in prices], "lows": [p-1 for p in prices],
            "closes": prices, "volumes": [50.0] * n,
            "times": [1700000000 + i * step for i in range(n)],
            "source": "offline-fixture", "closed_only": True}


class Response:
    def __init__(self, rows, headers=None):
        self.rows, self.headers = rows, headers or {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, *args): return json.dumps(self.rows).encode()


class Reliability(unittest.TestCase):
    def test_finite_signal_and_mainnet_boundary(self):
        for value in (True, float("nan"), float("inf"), -.1, 0, 1001):
            with self.assertRaises(ValueError):
                contract.parse_signal(json.dumps({"side":"buy", "size_sol":value}))
        with patch.object(host, "load_network", return_value="mainnet"), patch.object(host.urllib.request, "urlopen") as network:
            for chain in ("mainnet", "testnet"):
                for method in ("sendTransaction", "requestAirdrop", "sendBundle", "futureWriteMethod"):
                    self.assertIn("error", host.rpc_call(method, [], chain))
            with self.assertRaisesRegex(RuntimeError, "MAINNET_OBSERVE_ONLY"):
                host._lab_rpc("sendTransaction", [])
            with patch.object(host, "status_payload", return_value={}):
                host.tick_trader()
            network.assert_not_called()
        with patch.object(crypto_bots, "selected", return_value="optimal"), patch.object(host, "load_network", return_value="testnet"), patch.object(host, "status_payload", return_value={}), patch.object(host.crypto_paper, "set_enabled") as enable:
            host.set_trader_armed(True)
            enable.assert_called_once_with("SOLUSDT", "optimal", True)

    def test_confirmation_and_ambiguous_send(self):
        calls = []
        state = {"confirmed": False, "failed": False, "expired": False, "ambiguous": False}
        def rpc(method, params):
            calls.append((method, params))
            if method == "getLatestBlockhash": return {"result":{"value":{"blockhash":"1"*32,"lastValidBlockHeight":10}}}
            if method == "sendTransaction": return None if state["ambiguous"] else {"result":"fixture-signature"}
            if method == "getBlockHeight": return {"result":11 if state["expired"] else 9}
            return {"result":{"value":[{"err":"failed" if state["failed"] else None, "confirmationStatus":"confirmed" if state["confirmed"] else "processed"}]}}
        with patch.object(tx, "load_test_pubkey", return_value="1"*32), patch.object(tx, "signed_transfer_bytes", return_value=b"\x01" + b"x"*64):
            state["confirmed"] = True
            self.assertEqual(tx.send_self_transfer(rpc, 1)["status"], "confirmed")
            self.assertFalse(next(params[1]["skipPreflight"] for method, params in calls if method == "sendTransaction"))
            state["confirmed"] = False
            for target in ("unconfirmed", "failed", "expired"):
                state["failed"], state["expired"] = target == "failed", target == "expired"
                with patch.object(tx, "confirm_signature", return_value=False), self.assertRaises(tx.ConfirmationError) as raised:
                    tx.send_self_transfer(rpc, 1)
                self.assertEqual(raised.exception.status, target)
                self.assertEqual(raised.exception.txid, "fixture-signature")
            state["ambiguous"] = True
            calls.clear()
            with self.assertRaises(tx.ConfirmationError): tx.send_self_transfer(rpc, 1)
            self.assertEqual(sum(method == "sendTransaction" for method, _ in calls), 1)

    def test_desk_cash_and_daily_limit(self):
        n = desk.WARMUP + 8
        f = frame(n)
        f["closes"] = [100.] * n
        with patch.object(desk, "_seat_218", return_value={"size_scale":.25}), patch.object(desk, "front_man", return_value={"light":"GREEN", "reasons":[]}), patch.object(desk, "_seat_240", return_value={}):
            result = desk.run_desk({"1h":f})
        friction = (desk.FEE_BPS + desk.SLIPPAGE_BPS) / 10000
        expected = .75 + .25 * (1-friction)**2
        self.assertAlmostEqual(result["equity_pct"], (expected-1)*100, places=4)
        seen = []
        def man(*args, **kw):
            seen.append(kw["trades_today"])
            return {"light":"RED", "reasons":["INVALIDATION"]} if kw["in_position"] else {"light":"GREEN", "reasons":[]}
        with patch.object(desk, "_seat_218", return_value={"size_scale":.25}), patch.object(desk, "front_man", side_effect=man):
            result = desk.run_desk({"1h":f})
        self.assertIn(1, seen)
        self.assertIn(2, seen)

    def test_breakout_and_prefix_invariance(self):
        candidate = next(row for row in factory.CANDIDATE_CATALOG if row["family"] == "BREAKOUT")
        prices = [100.] * 21 + [110.]
        self.assertEqual(factory._signal(candidate, prices, len(prices)), 1)
        prefix = [.001 * math.sin(i) for i in range(100)]
        suffix = [.2, -.3] * 40
        for fn, keys in ((crypto_vol.garch_1_1, ("sigma", "baseline_sigma")), (crypto_vol.hmm_two_state, ("states", "probabilities"))):
            a, b = fn(prefix), fn(prefix+suffix)
            for key in keys: self.assertEqual(a[key], b[key][:len(prefix)])
        f = frame(200)
        before = factory.run_factory({"1h":f})
        modified = copy.deepcopy(f)
        modified["closes"][160:] = [500.] * 40
        after = factory.run_factory({"1h":modified})
        self.assertEqual(before["autoresearch"]["steps"], after["autoresearch"]["steps"])
        self.assertEqual(before["autoresearch"]["best_buffer_bps"], after["autoresearch"]["best_buffer_bps"])
        self.assertEqual(before["autoresearch"]["trial_count"], len(before["autoresearch"]["trial_registry"]))
        self.assertEqual(len(before["autoresearch"]["validation_folds"]), 2)

    def test_data_integrity_and_freshness(self):
        f = frame()
        self.assertEqual(crypto_data.validate_frame(f, "1h")["gaps"], 0)
        for kind in ("synthetic", "volume", "open", "unordered"):
            bad = copy.deepcopy(f)
            if kind == "synthetic": bad["synthetic"] = True
            if kind == "volume": bad["volumes"] = []
            if kind == "open": bad["times"][-1] = int(time.time())
            if kind == "unordered": bad["times"][-1] = bad["times"][-2]
            with self.assertRaises(ValueError): crypto_data.validate_frame(bad, "1h")
        with self.assertRaisesRegex(RuntimeError, "NO_MARKET_DATA"): host._ohlcv_from_closes([100]*100)
        rows = [[(1700000000 + i * 3600) * 1000, 100.0] for i in range(10)]
        for price in ("invalid", float("nan"), float("inf"), -1, 0):
            bad = copy.deepcopy(rows)
            bad[4][1] = price
            for fetch in (host._coingecko_sol_chart, host._coingecko_kas_chart):
                with patch.object(host.urllib.request, "urlopen", return_value=Response({"prices":bad})):
                    with self.assertRaisesRegex(RuntimeError, "CRYPTO_CHART"): fetch()
        _, stamps = host._price_rows(rows, 4)
        self.assertEqual(host._source_chart_interval(stamps), "1h")
        for setter in (host._set_live_chart, host._set_kas_chart):
            with self.assertRaisesRegex(RuntimeError, "CRYPTO_CHART"):
                setter([100, float("nan")], [1, 2], "fixture")
        fetched = time.time()-3600
        with patch.dict(host._chart_cache, {"closes":[100,101],"times":[1,2],"fetched_at":fetched,"ts":0,"error":"","interval":"1h"}), patch.object(host, "fetch_klines", side_effect=RuntimeError()), patch.object(host, "_coingecko_sol_chart", side_effect=RuntimeError()):
            result = host.cached_sol_chart()
            self.assertTrue(result["stale"])
            self.assertEqual(result["fetched_at"], fetched)

    def test_closed_bars_and_cache_tail_repair(self):
        now = int(time.time()) // 3600 * 3600
        rows = [[(now-(80-i)*3600)*1000, "100", "102", "98", "100", "12"] for i in range(81)]
        with patch.object(host.urllib.request, "urlopen", return_value=Response(rows)):
            result = host.fetch_klines("1h", 81)
        self.assertEqual(len(result[2]), 80)
        f = frame(80)
        f["times"] = [now-(80-i)*3600 for i in range(80)]
        path = host._history_path("1h")
        path.write_text(json.dumps({**f,"interval":"1h","data_version":2}))
        tail = f["times"][-1]
        update = [[tail*1000,"100","120","90","111","2"], [now*1000,"100","120","90","119","2"]]
        with patch.object(host.urllib.request, "urlopen", return_value=Response(update)) as network:
            _, _, closes, _, stamps = host.fetch_klines_history("1h")
        self.assertEqual(closes[-1], 111)
        self.assertEqual(stamps[-1], tail)
        self.assertIn("startTime=" + str(tail*1000), network.call_args.args[0].full_url)

    def test_coarse_kas_source_is_not_four_hour(self):
        now = 1700000000
        daily = {"prices":[[(now+i*86400)*1000,.1+i*.001] for i in range(12)]}
        with patch.object(host.urllib.request, "urlopen", return_value=Response(daily)):
            _, stamps, actual = host._coingecko_kas_chart("4h")
        self.assertEqual(actual, "1d")
        self.assertTrue(all(b-a == 86400 for a,b in zip(stamps,stamps[1:])))

    def test_common_comparison_costs_metrics_identity(self):
        frames = {"1h":frame(240)}
        persisted = []
        def save(report):
            if bt.PERSIST.get(): persisted.append(report)
        with patch.object(crypto_bots, "selected", return_value="gg"), patch.object(crypto_trader, "save_backtest", side_effect=save):
            result = crypto_bots.compare_books(frames)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(len(result["comparison"]), 6)
        self.assertTrue(all(row["state"] == "DONE" for row in result["comparison"]), result["comparison"])
        self.assertEqual(len({row["holdout_range"] for row in result["comparison"]}), 1)
        for book in crypto_bots.BOOKS:
            report = crypto_bots.run_backtest(frames, book_id=book["id"], persist=False)
            self.assertEqual(report["book"], book["id"])
            self.assertEqual(report["start_usd"], "200.0")
            self.assertEqual(report["cost_model"]["per_leg_bps"], 35)
            self.assertEqual(report["benchmarks"], result["benchmarks"])
            self.assertGreater(report["return_pct"], -50, report["book"])
            self.assertLess(report["max_drawdown_pct"], 50, report["book"])
        self.assertAlmostEqual(bt.metrics([100,90,110],100,3600)["max_drawdown_pct"], 10)
        hourly, daily = bt.metrics([101,100,102],100,3600), bt.metrics([101,100,102],100,86400)
        self.assertAlmostEqual(hourly["sharpe_proxy"] / daily["sharpe_proxy"], math.sqrt(24), places=4)
        with patch.object(crypto_bots, "_native_backtest", side_effect=RuntimeError("fixture_failure")):
            with self.assertRaisesRegex(RuntimeError,"fixture_failure"):
                crypto_bots.compare_books(frames, book_id="dca")

    def test_usd_mark_includes_cash_and_flat_tape_only_loses_costs(self):
        state = {"sol":crypto_trader.SOL_SCALE//2,"banked_sol":0,
                 "usd":50*crypto_trader.USD_SCALE,"float_usd":100*crypto_trader.USD_SCALE,
                 "banked_usd":10*crypto_trader.USD_SCALE}
        self.assertEqual(crypto_trader._mark_usd(state,100),210)
        f=frame(240)
        f["closes"],f["highs"],f["lows"]=[100.]*240,[101.]*240,[99.]*240
        for book in crypto_bots.BOOKS:
            result=crypto_bots.run_backtest({"1h":f},book_id=book["id"],persist=False)
            self.assertLessEqual(result["return_pct"],0,book["id"])
            self.assertGreaterEqual(result["return_pct"],-1,book["id"])

    def test_slow_history_cannot_change_comparison_clock(self):
        frames={"1h":frame(240)}
        end=frames["1h"]["times"][-1]
        for interval, step in (("4h",14400),("1d",86400)):
            f=frame(400,step)
            f["times"]=[end-(400-i)*step for i in range(400)]
            frames[interval]=f
        for book in crypto_bots.BOOKS:
            result=crypto_bots.run_backtest(frames,book_id=book["id"],persist=False)
            self.assertEqual(result["primary"],"1h",book["id"])
            self.assertEqual(result["chart"]["times"],frames["1h"]["times"])

    def test_barriers_are_causal(self):
        executor = hybrid.PaperPositionExecutor(5,1,100,hybrid.HybridConfig(stop_loss_bps=500,take_profit_bps=500,trailing_delta_bps=200))
        self.assertIsNone(executor.check(5,120,80,100))
        hit = executor.check(6,120,94,100)
        self.assertEqual(hit[0], "stop_loss")

    def test_optimal_sale_profit_is_net_of_cost_basis(self):
        gate = crypto_optimal.live_gate([100-i*.1 for i in range(100)], [50]*100, in_position=True, entry_price=100)
        self.assertIn("INVALIDATION",gate["reasons"])
        f=frame(100)
        f["closes"]=[100.]*82+[90.]*18
        f["highs"]=[p+1 for p in f["closes"]]
        f["lows"]=[p-1 for p in f["closes"]]
        with patch.object(crypto_optimal,"_gate_at",return_value={"allow_buy":True,"allow_sell":False,"reasons":[],"size_scale":.5}):
            report=crypto_optimal.run_backtest({"1h":f})
        sells=[row for row in report["lots"] if row["side"]=="sell"]
        self.assertTrue(sells)
        self.assertLess(sells[0]["profit_usd"],0)
        self.assertGreater(sells[0]["sol"],1_000_000)
        self.assertLess(float(report["win_rate"]),100)

    def test_polymarket_outcomes_and_cross_hour_lookup(self):
        condition = "0x" + "ab"*32
        sql = poly.query_spec("TOUCH","2026-09-08","17","market",condition_id=condition)["sql"]
        self.assertIn("GROUP BY 1, 2", sql)
        self.assertIn("market = from_hex", sql)
        self.assertIn("GROUP BY 1, 2",poly.query_spec("SCAN","2026-09-08","17")["sql"])
        captured = []
        def execute(sql):
            captured.append(sql)
            return ["minute","asset","bid","ask"], [("17:00","0x01",.2,.3),("17:00","0x02",.7,.8)]
        result = poly.run_query("TOUCH","2026-09-08","17","market",executor=execute,
            resolver=lambda slug:{"condition_id":condition,"outcomes":{"0x01":"Yes","0x02":"No"}})
        self.assertTrue(result["ok"])
        self.assertEqual([r["outcome"] for r in result["rows"]], ["Yes","No"])
        self.assertIn("market = from_hex", captured[0])
        trades = poly._format_lines("TRADES",[{"at":"2026-09-08T17:00:00.123456","market":"a","asset":"b"}])
        self.assertIn(".123456",trades[-1])

    def test_polymarket_cancel_prevents_overlapping_workers(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def execute(sql):
            calls.append(sql); entered.set(); release.wait(2)
            return ["event_type","rows"], [("trade",1)]
        poly.reset()
        poly.start_query("SUMMARY","2026-09-08","17",executor=execute)
        self.assertTrue(entered.wait(1))
        self.assertEqual(poly.reset()["state"],"cancelling")
        self.assertEqual(poly.start_query("SUMMARY","2026-09-08","17",executor=execute)["state"],"cancelling")
        self.assertEqual(len(calls),1)
        release.set()
        for _ in range(100):
            if poly.snapshot()["state"] == "cancelled": break
            time.sleep(.01)
        self.assertEqual(poly.snapshot()["state"],"cancelled")

    def test_polymarket_source_size_budget(self):
        for size in (0, poly.MAX_SOURCE_BYTES+1):
            with patch.object(poly.urllib.request,"urlopen",return_value=Response({}, {"Content-Length":str(size)})):
                with self.assertRaises(ValueError): poly.source_metadata("2026-09-08","17")

    def test_polymarket_real_child_is_killed_on_cancel(self):
        real_popen = subprocess.Popen
        children = []
        def child(*args, **kwargs):
            proc = real_popen([sys.executable,"-B","-c","import sys,time; sys.stdin.read(); time.sleep(30)"], **kwargs)
            children.append(proc)
            return proc
        with patch.object(poly,"duckdb_available",return_value=True), patch.object(poly,"source_metadata",return_value={"bytes":1}), patch.object(poly.subprocess,"Popen",side_effect=child):
            poly.start_query("SUMMARY","2026-09-08","17")
            for _ in range(100):
                if children: break
                time.sleep(.01)
            self.assertEqual(len(children),1)
            poly.reset()
            for _ in range(100):
                if poly.snapshot()["state"] == "cancelled": break
                time.sleep(.01)
            self.assertEqual(poly.snapshot()["state"],"cancelled")
            self.assertIsNotNone(children[0].poll())

    def test_chart_and_tick_jobs_return_without_waiting(self):
        entered, release = threading.Event(), threading.Event()
        calls=[]
        def slow():
            calls.append(1); entered.set(); release.wait(2)
            return {}
        with patch.object(host,"tick_trader",side_effect=slow), patch.object(host,"status_payload",return_value={}):
            start=time.monotonic()
            host.start_paper_tick("trader")
            self.assertLess(time.monotonic()-start,.1)
            self.assertTrue(entered.wait(1))
            host.start_paper_tick("trader")
            self.assertEqual(len(calls),1)
            release.set()
            for _ in range(100):
                if host.paper_tick_status()["trader"]["state"] != "running": break
                time.sleep(.01)
        entered.clear();release.clear();calls.clear()
        with patch.object(host,"cached_sol_chart",side_effect=slow):
            start=time.monotonic()
            host.request_chart_refresh("SOL")
            self.assertLess(time.monotonic()-start,.1)
            self.assertTrue(entered.wait(1))
            release.set()
            for _ in range(100):
                with host._chart_refresh_lock:
                    if "SOL" not in host._chart_refresh_running: break
                time.sleep(.01)


if __name__ == "__main__":
    unittest.main(argv=[__file__], verbosity=2)
