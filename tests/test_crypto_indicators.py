#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend.crypto_indicators import (
    aroon_osc,
    bb_percent,
    candle_osc,
    cci_osc,
    cmf_osc,
    cmo_osc,
    heikin_osc,
    ichimoku_osc,
    keltner_percent,
    mfi,
    rsi,
    schaff_trend,
    sma,
    stoch_kd,
    supertrend_osc,
    ultimate_osc,
    williams_osc,
)
from backend.crypto_strategy004 import evaluate


def main() -> int:
    if sma([1, 2, 3, 4], 2)[-1] != 3.5:
        raise AssertionError("sma")
    series = [float(i) for i in range(1, 120)]
    r = rsi(series, 14)
    if r[-1] is None or r[-1] < 70:
        raise AssertionError("rsi uptrend " + str(r[-1]))
    highs = [x + 1 for x in series]
    lows = [max(0.1, x - 1) for x in series]
    vols = [100.0] * len(series)
    report = evaluate(highs, lows, series, vols)
    if report.get("strategy") != "Strategy004":
        raise AssertionError("strategy tag")
    if report["super"] not in ("buy", "sell", "none"):
        raise AssertionError("super " + str(report["super"]))
    k, d = stoch_kd(highs, lows, series, 9, 3, 3)
    if k[-1] is None or d[-1] is None:
        raise AssertionError("stoch 9 3 3")
    k60, d60 = stoch_kd(highs, lows, series, 60, 10, 10)
    if len(k60) != len(series) or k60[-1] is None:
        raise AssertionError("stoch 60 10 10")
    w = williams_osc(highs, lows, series, 14)
    if w[-1] is None or not (0 <= w[-1] <= 100):
        raise AssertionError("williams")
    cci = cci_osc(highs, lows, series, 20)
    if cci[-1] is None or not (0 <= cci[-1] <= 100):
        raise AssertionError("cci osc")
    pct = bb_percent(series, 14, 2.0)
    if pct[-1] is None:
        raise AssertionError("bb percent")
    flow = mfi(highs, lows, series, vols, 14)
    if flow[-1] is None or not (0 <= flow[-1] <= 100):
        raise AssertionError("mfi")
    for name, values in (
        ("uo", ultimate_osc(highs, lows, series)),
        ("cmo", cmo_osc(series, 14)),
        ("cmf", cmf_osc(highs, lows, series, vols, 20)),
        ("aroon", aroon_osc(highs, lows, 25)),
        ("stc", schaff_trend(series)),
        ("keltner", keltner_percent(highs, lows, series)),
        ("ichi", ichimoku_osc(highs, lows, series)),
        ("st", supertrend_osc(highs, lows, series)),
        ("ha", heikin_osc(highs, lows, series)),
        ("candle", candle_osc(highs, lows, series)),
    ):
        if values[-1] is None or not (0 <= values[-1] <= 100):
            raise AssertionError(name + " " + str(values[-1]))
    print("CRYPTO_INDICATORS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
