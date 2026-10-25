#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_contract, crypto_host, crypto_keys


def _off(wait_s: float = 0.0) -> tuple[bool, str]:
    return False, "LAB_OFF"


def _on(wait_s: float = 0.0) -> tuple[bool, str]:
    return True, ""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gg-crypto-host-"))
    crypto_contract.STATE_DIR = tmp
    host_src = (PROJECT / "backend" / "crypto_host.py").read_text(encoding="utf-8")
    lab_src = (PROJECT / "backend" / "crypto_lab.py").read_text(encoding="utf-8")
    if host_src.count("def tick_trader") != 1:
        raise AssertionError("duplicate tick_trader")
    if "def _refresh_bundle" not in host_src:
        raise AssertionError("RPC refresh must leave the UI thread")
    rail = crypto_host.status_payload(rail=True)
    if "chart" in rail or "trader" in rail or "backtest_job" in rail:
        raise AssertionError("rail status still carries the tape")
    if "legend" not in rail or "signer" not in rail:
        raise AssertionError("rail status missing wallet chips")
    if host_src.count("def set_trader_armed") != 1:
        raise AssertionError("duplicate set_trader_armed")
    if "Public RPC airdrop is dry" in host_src:
        raise AssertionError("public faucet hint still in airdrop")
    if "lab-airdrop" not in host_src:
        raise AssertionError("lab airdrop source missing")
    if "LAB_AIRDROP_LAMPORTS = 100 * 1_000_000_000" not in host_src:
        raise AssertionError("lab airdrop default is not 100 SOL")
    if '"100000"' not in lab_src:
        raise AssertionError("lab ledger size too small")
    if "wait_ready" not in lab_src or "is_frozen" not in lab_src:
        raise AssertionError("lab freeze recovery missing")
    if "taskset" in lab_src:
        raise AssertionError("lab validator still pinned")
    if "CPUQuota=" not in lab_src:
        raise AssertionError("lab CPU quota missing")
    if "def backtest_trader" not in host_src:
        raise AssertionError("trader backtest missing")
    if '"1m": 3400' not in host_src or '"5m": 720' not in host_src:
        raise AssertionError("1m/5m history page cap too small")
    if '"8h": 20' not in host_src or '"1d": 10' not in host_src:
        raise AssertionError("8h/1d history page cap missing")
    if "crypto_bots.compare_books" not in host_src:
        raise AssertionError("six-book comparison not wired")
    if "crypto_bots" not in host_src or "def set_trader_book" not in host_src:
        raise AssertionError("book switch missing")
    if crypto_contract.human_error("LAB_OFF") != crypto_contract.ERROR_HINTS["LAB_OFF"]:
        raise AssertionError("human LAB_OFF")
    if (
        crypto_contract.short_error(
            "Attempt to debit an account but found insufficient funds"
        )
        != "NEED_FEE_SOL"
    ):
        raise AssertionError("short insufficient")
    if "observe-only" not in crypto_contract.human_error("MAINNET_OBSERVE_ONLY").lower():
        raise AssertionError("mainnet hint")
    if crypto_contract.human_error("MAINNET_NOT_ARMED") != crypto_contract.human_error(
        "MAINNET_OBSERVE_ONLY"
    ):
        raise AssertionError("old MAINNET_NOT_ARMED must alias observe-only")

    proven = crypto_contract.mark_proven("lab")
    if not proven["lab"] or proven["ready"]:
        raise AssertionError("partial proven")
    crypto_contract.mark_proven("airdrop")
    crypto_contract.mark_proven("buy")
    crypto_contract.mark_proven("bot")
    ready = crypto_contract.mark_proven("arb")
    if not ready["ready"] or ready["done"] != 5:
        raise AssertionError("proven ready " + json.dumps(ready))

    crypto_host.fetch_tokens = lambda *a, **k: []
    crypto_host._bundle = lambda *a, **k: (0, [])
    orig_fetch = crypto_host.fetch_balance
    crypto_host.fetch_balance = lambda *a, **k: 0

    crypto_host._lab_gate = _off
    wallet = crypto_host.airdrop_testnet()
    row = wallet.get("airdrop") or {}
    if row.get("error") != "LAB_OFF":
        raise AssertionError("airdrop lab off " + json.dumps(row))
    if "Start LAB first" not in str(row.get("hint") or ""):
        raise AssertionError("airdrop hint " + str(row.get("hint")))

    key = crypto_keys.ensure_test_wallet()
    crypto_contract.save_network("mainnet")
    crypto_contract.save_wallet(key, 0, "mainnet")
    fired = crypto_host.ingest_paper_signal(
        '{"side":"buy","size_sol":0.01,"symbol":"SOL","source":"manual"}'
    )
    if fired.get("error") != "MAINNET_OBSERVE_ONLY":
        raise AssertionError("mainnet send? " + json.dumps(fired))

    crypto_contract.save_network("testnet")
    crypto_contract.save_wallet(key, 0, "testnet")
    crypto_host._lab_gate = _off
    fired = crypto_host.ingest_paper_signal(
        '{"side":"buy","size_sol":0.01,"symbol":"SOL","source":"manual"}'
    )
    if fired.get("error") != "LAB_OFF":
        raise AssertionError("buy lab off " + json.dumps(fired))

    crypto_host._lab_gate = _on
    crypto_host.fetch_balance = lambda *a, **k: None
    fired = crypto_host.ingest_paper_signal(
        '{"side":"buy","size_sol":0.01,"symbol":"SOL","source":"manual"}'
    )
    if fired.get("error") != "RPC_UNREACHABLE":
        raise AssertionError("rpc none " + json.dumps(fired))

    crypto_host.fetch_balance = lambda *a, **k: 0
    fired = crypto_host.ingest_paper_signal(
        '{"side":"buy","size_sol":0.01,"symbol":"SOL","source":"manual"}'
    )
    if fired.get("error") != "NEED_FEE_SOL":
        raise AssertionError("zero sol " + json.dumps(fired))

    crypto_host.fetch_balance = orig_fetch
    crypto_host._chart_cache["closes"] = []
    crypto_host._chart_cache["times"] = []
    crypto_host._chart_cache["ts"] = 0.0

    def boom_ohlcv():
        raise RuntimeError("CRYPTO_KLINE")

    orig_fetch_sol = crypto_host.fetch_sol_ohlcv
    crypto_host.fetch_sol_ohlcv = boom_ohlcv
    report = crypto_host.evaluate_signals()
    if report.get("super") != "none":
        raise AssertionError("eval junk super")
    if report.get("error") != "NO_MARKET_DATA":
        raise AssertionError("eval error " + json.dumps(report))
    if "HTTP" in json.dumps(report) or "Traceback" in json.dumps(report):
        raise AssertionError("eval dumped rpc junk")
    crypto_host.fetch_sol_ohlcv = orig_fetch_sol

    closes = [100.0 + (i * 0.1) for i in range(80)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    vols = [1.0] * 80
    report = crypto_host.evaluate_signals((highs, lows, closes, vols))
    if report.get("error"):
        raise AssertionError("eval fixture error " + json.dumps(report))
    if report.get("super") not in ("buy", "sell", "none"):
        raise AssertionError("eval super " + str(report.get("super")))

    if "_ingest_spark" not in host_src or "_set_live_chart" not in host_src:
        raise AssertionError("live spark ingest missing")
    if 'fetch_klines("15m", 80' not in host_src:
        raise AssertionError("15m live chart missing")
    if "_kline_times" not in host_src:
        raise AssertionError("kline open times missing")
    qml = (PROJECT / "qml" / "components" / "CryptoSurface.qml").read_text(encoding="utf-8")
    if "fromZero: false" not in qml or "tradeMarks" not in qml:
        raise AssertionError("portfolio spark is not live-marked")
    if "botTab" not in qml or "botTape" not in qml:
        raise AssertionError("bot tape views missing")
    if "BACKTEST 1" not in qml or "BACKTEST 2" not in qml:
        raise AssertionError("last two backtests not switchable")
    # Actual portfolio rendering and interaction are exercised by
    # test_crypto_ui_refresh.py; the unused WebEngine placeholder was removed.
    if "start_backtest_trader" not in host_src or "threading.Thread" not in host_src:
        raise AssertionError("backtest still blocks the UI thread")
    if "_UI_BACKTEST_TF" not in host_src or "backtestRunning" not in qml:
        raise AssertionError("async UI backtest missing")
    if "sorted(frames.keys())" in host_src:
        raise AssertionError("backtest TF label still lexicographic")
    if "_UI_BACKTEST_TF = crypto_market.TIMEFRAMES" not in host_src:
        raise AssertionError("UI backtest must use actual market timeframes")
    if "crypto_market.history(pair, tf, start)" not in host_src:
        raise AssertionError("common hourly comparison data missing")
    if "pnl_sol" not in qml or "bt.pnl_usd" not in qml:
        raise AssertionError("backtest PnL currency fields missing")
    if "bt.weeks" not in qml:
        raise AssertionError("weekly buy/sell tape missing")
    # The former equity binding belonged to an always-hidden 0x0 WebEngine.
    # Active Canvas and optional equity-series behavior have executable UI tests.
    if "cryptoSetBook" not in qml or "trader.books" not in qml:
        raise AssertionError("book switch not on the CRYPTO surface")
    hole = (PROJECT / "qml" / "crypto-hole" / "index.html").read_text(encoding="utf-8")
    if "lightweight-charts.min.js" not in hole or "setTape" not in hole:
        raise AssertionError("crypto tape hole missing")
    if "startPlay" in hole or "tapePlay" in hole:
        raise AssertionError("fake backtest replay still in the tape")
    if "REPLAY" in qml or "tapePaused" in qml:
        raise AssertionError("fake backtest replay controls still in QML")
    if "priceScaleId: \"left\"" not in hole and "priceScaleId: 'left'" not in hole:
        raise AssertionError("SOL equity scale missing")
    chart_qml = (PROJECT / "qml" / "components" / "CryptoChart.qml").read_text(encoding="utf-8")
    if "QtWebEngine" not in chart_qml or "crypto-hole/index.html" not in chart_qml:
        raise AssertionError("CryptoChart does not load the vendored tape")
    spark = (PROJECT / "qml" / "components" / "TmogSpark.qml").read_text(encoding="utf-8")
    if "property var marks" not in spark or "fromZero" not in spark:
        raise AssertionError("spark marks/fromZero missing")

    now = 1_700_000_000
    live_closes = [100.0 + (i * 0.2) for i in range(80)]
    live_times = [now - (80 - i) * 900 for i in range(80)]
    crypto_host._kline_times["15m"] = list(live_times)
    highs = [c + 1 for c in live_closes]
    lows = [c - 1 for c in live_closes]
    vols = [1.0] * 80
    crypto_host._ingest_spark(
        {"15m": (highs, lows, live_closes, vols)},
        live=188.25,
    )
    snap = crypto_host.chart_snapshot()
    if snap.get("closes")[-1] != 188.25:
        raise AssertionError("live pin " + str(snap.get("closes")[-1]))
    if snap.get("times") != live_times:
        raise AssertionError("spark times")
    if snap.get("interval") != "15m":
        raise AssertionError("spark interval " + str(snap.get("interval")))
    crypto_host._chart_cache["closes"] = []
    crypto_host._chart_cache["times"] = []
    crypto_host._load_chart_disk()
    snap = crypto_host.chart_snapshot()
    if snap.get("closes")[-1] != 188.25:
        raise AssertionError("disk live pin")
    if len(snap.get("times") or []) != 80:
        raise AssertionError("disk times")

    crypto_host._backtest_job["state"] = "idle"
    crypto_host._backtest_job["note"] = ""
    fired = {"n": 0}

    def fake_bt(tfs=None, **kwargs):
        fired["n"] += 1
        time.sleep(0.05)
        return {"fills": 1, "chart": {"closes": [1.0, 2.0], "times": [1, 2]}}

    orig_bt = crypto_host.backtest_trader
    crypto_host.backtest_trader = fake_bt
    try:
        t0 = time.time()
        payload = crypto_host.start_backtest_trader()
        if time.time() - t0 > 0.5:
            raise AssertionError("start_backtest blocked")
        if (payload.get("backtest_job") or {}).get("state") != "running":
            raise AssertionError("job not running " + json.dumps(payload.get("backtest_job")))
        deadline = time.time() + 2
        while time.time() < deadline and crypto_host.backtest_job().get("state") == "running":
            time.sleep(0.02)
        if crypto_host.backtest_job().get("state") != "done":
            raise AssertionError("job " + json.dumps(crypto_host.backtest_job()))
        if fired["n"] != 1:
            raise AssertionError("walk count " + str(fired["n"]))
    finally:
        crypto_host.backtest_trader = orig_bt
        crypto_host._backtest_job["state"] = "idle"

    crypto_contract.save_network("mainnet")
    payload = crypto_host.run_flash_arb()
    last = payload.get("arb_last") or {}
    if last.get("error") != "MAINNET_OBSERVE_ONLY":
        raise AssertionError("arb mainnet " + json.dumps(last))

    print("CRYPTO_HOST_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
