#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_hybrid


def main() -> int:
    config = crypto_hybrid.HybridConfig(
        forecast_stride=1,
        max_forecast_calls=200,
        take_profit_bps=100,
        stop_loss_bps=800,
        time_limit_bars=80,
        cooldown_bars=0,
        initial_position_bps=2500,
        use_timesfm=False,
    )
    closes = [100.0] * 90 + [100.0] * 10 + [96.0] + [98.0] * 49
    highs = [value + 0.2 for value in closes]
    lows = [value - 0.2 for value in closes]
    times = [1_700_000_000 + i * 3600 for i in range(len(closes))]
    frames = {
        "1h": {
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": [1.0] * len(closes),
            "times": times,
        }
    }

    def forecast(history: list[float], _horizon: int) -> dict[str, float | str]:
        last = history[-1]
        if last >= 99.0:
            return {"model": "fake-timesfm", "point": 98.0, "q10": 98.0, "q90": 98.0}
        return {
            "model": "fake-timesfm",
            "point": last * 1.05,
            "q10": last * 1.04,
            "q90": last * 1.06,
        }

    def signal(i: int, _price: float) -> dict[str, str]:
        if i == 90:
            return {"side": "sell", "flow": "range"}
        if i >= 100:
            return {"side": "buy", "flow": "range"}
        return {"side": "none", "flow": "range"}

    report = crypto_hybrid.run_backtest(
        frames,
        config=config,
        persist=False,
        forecast_provider=forecast,
        signal_provider=signal,
    )
    if report.get("book") != "hybrid":
        raise AssertionError("hybrid book missing")
    if report.get("mode") != "PAPER" or report.get("network") != "testnet":
        raise AssertionError("hybrid must stay in paper/testnet mode")
    if int(report.get("buys") or 0) < 1 or int(report.get("sells") or 0) < 2:
        raise AssertionError("paper executor did not close and re-enter")
    if int((report.get("barriers") or {}).get("take_profit") or 0) < 1:
        raise AssertionError("take-profit barrier did not fire")
    if int(report.get("max_open") or 0) != 1:
        raise AssertionError("hybrid executor must stay single-position")
    if report.get("forecast_model") != "injected":
        raise AssertionError("forecast provider provenance missing")
    if "triple barrier" not in str(report.get("note") or ""):
        raise AssertionError("paper safety note missing")
    if report.get("quote_currency") != "USD" or "pnl_usd" not in report:
        raise AssertionError("quote equity accounting missing")
    if float(report.get("max_position_pct") or 0.0) > 100.0:
        raise AssertionError("position exposure accounting invalid")

    barrier = crypto_hybrid.PaperPositionExecutor(
        0,
        1_700_000_000,
        100.0,
        crypto_hybrid.HybridConfig(stop_loss_bps=500, take_profit_bps=500),
    )
    hit = barrier.check(1, 100.1, 94.0, 96.0)
    if not hit or hit[0] != "stop_loss":
        raise AssertionError("stop-loss must win a same-bar conflict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
