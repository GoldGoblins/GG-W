#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_bots, crypto_optimal


def _frames() -> dict[str, dict[str, list]]:
    closes: list[float] = []
    volumes: list[float] = []
    price = 100.0
    for index in range(220):
        if 90 <= index < 120:
            volumes.append(220.0)
            price *= 0.972
        elif index % 18 == 0:
            volumes.append(400.0)
            price *= 0.992
        elif index % 18 == 1:
            volumes.append(80.0)
            price *= 1.014
        else:
            volumes.append(90.0)
            price *= 1.0003
        closes.append(price)
    highs = [value + 0.4 for value in closes]
    lows = [value - 0.4 for value in closes]
    times = [1_700_000_000 + i * 3600 for i in range(len(closes))]
    return {
        "1h": {
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": volumes,
            "times": times,
        }
    }


def main() -> int:
    gate = crypto_optimal.live_gate([100.0] * 10, [1.0] * 10, in_position=False)
    assert gate["allow_buy"] is False
    assert gate["mainnet"] == "NOT_ARMED"
    assert gate["front_man"]["in_code"] is True

    votes = {"1h": "buy", "5m": "sell"}
    blocked = crypto_optimal.apply_live_votes(votes, {"allow_buy": False, "allow_sell": False})
    assert blocked["1h"] == "none"
    assert blocked["5m"] == "none"

    report = crypto_optimal.run_backtest(_frames())
    assert report["schema"] == crypto_optimal.SCHEMA
    assert report["book"] == "optimal"
    assert report["mode"] == "PAPER_ONLY"
    assert report["mainnet"] == "NOT_ARMED"
    assert report["parallel_agent_brain"] == "FORBIDDEN"
    assert report["model_agents"] is False
    assert "crypto_desk.front_man" in report["ingredients"]
    assert "fee_hold" in report["ingredients"]
    assert int(report["fee_hold_bps"]) == 2 * 30 + 10
    assert "pnl_sol" in report
    assert int(report.get("fills") or 0) >= 1

    crypto_bots.set_book("optimal")
    assert crypto_bots.selected() == "optimal"
    via_bots = crypto_bots.run_backtest(_frames())
    assert via_bots.get("book") == "optimal"
    import time as _time

    t0 = _time.perf_counter()
    crypto_optimal.run_backtest(_frames())
    elapsed = _time.perf_counter() - t0
    if elapsed > 2.0:
        raise AssertionError("optimal backtest too slow: " + str(elapsed))
    crypto_bots.set_book("gg")

    qml = (PROJECT / "qml/components/CryptoSurface.qml").read_text(encoding="utf-8")
    if "cryptoSetBook" not in qml:
        raise AssertionError("book chips missing")
    print("test_crypto_optimal: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
