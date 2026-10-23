#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_bot_dca, crypto_bot_dca_swing, crypto_bots, crypto_contract, crypto_trader


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gg-bots-"))
    crypto_contract.STATE_DIR = tmp
    crypto_trader.reset_book()
    ids = [row["id"] for row in crypto_bots.catalog()]
    if ids != ["gg", "stoch_rsi", "dca", "dca_swing", "hybrid", "optimal"]:
        raise AssertionError("books " + str(ids))
    verdicts = {row["id"]: row.get("verdict") for row in crypto_bots.catalog()}
    if verdicts["stoch_rsi"] != "PARK" or verdicts["optimal"] != "KEEP":
        raise AssertionError("board " + str(verdicts))
    if verdicts["dca_swing"] != "WATCH":
        raise AssertionError("swing is a watch, not a keep")
    if crypto_bots.selected() != "gg":
        raise AssertionError("default book")
    if crypto_bots.set_book("stoch_rsi") != "stoch_rsi":
        raise AssertionError("set book")
    if crypto_bots.selected() != "stoch_rsi":
        raise AssertionError("selected after set")
    if crypto_bots.set_book("nope") != "gg":
        raise AssertionError("unknown book must fall back")
    crypto_bots.set_book("stoch_rsi")
    closes = [100.0] * 40 + [80.0] * 20 + [90.0] * 40 + [70.0] * 15 + [85.0] * 40
    n = len(closes)
    highs = [x + 1.0 for x in closes]
    lows = [x - 1.0 for x in closes]
    times = [1_700_000_000 + i * 3600 for i in range(n)]
    frames = {
        "1h": {
            "highs": highs,
            "lows": lows,
            "closes": closes,
            "volumes": [1.0] * n,
            "times": times,
        }
    }
    report = crypto_bots.run_backtest(frames)
    if str(report.get("book") or "") != "stoch_rsi":
        raise AssertionError("report book " + str(report.get("book")))
    if "pnl_sol" not in report:
        raise AssertionError("stoch rsi PnL missing")
    if "werkkrew" not in str(report.get("note") or ""):
        raise AssertionError("source must stay on the report")
    if "Freqtrade process" in str(report.get("note") or "") and "Not a" not in str(
        report.get("note") or ""
    ):
        raise AssertionError("must not claim a Freqtrade process")
    scored = crypto_trader._trade_stats(
        [
            {
                "id": "stoch-sell-1",
                "side": "sell",
                "profit_usd": 10,
                "sol": 1,
                "price": 1,
            }
        ],
        0,
        0,
        [1],
        sol_held=crypto_trader.START_SOL,
        last_close=100.0,
        start_sol=crypto_trader.START_SOL,
    )
    if float(scored.get("win_rate") or 0) < 99:
        raise AssertionError("stoch sell profit must count as a win " + str(scored))
    crypto_bots.set_book("dca")
    crash = [100.0 - i * 0.4 for i in range(120)]
    cn = len(crash)
    crash_frames = {
        "1h": {
            "highs": [x + 1.0 for x in crash],
            "lows": [x - 1.0 for x in crash],
            "closes": crash,
            "volumes": [1.0] * cn,
            "times": [1_710_000_000 + i * 3600 for i in range(cn)],
        }
    }
    dumped = crypto_bots.run_backtest(crash_frames)
    if str(dumped.get("book") or "") != "dca":
        raise AssertionError("dca book " + str(dumped.get("book")))
    end_sol = float(str(dumped.get("tokens") or dumped.get("float_sol") or "0"))
    start_sol = float(str(dumped.get("start_sol") or "0"))
    if start_sol > 0 and end_sol < start_sol * 0.95:
        raise AssertionError(
            "DCA must not sell principal into a crash "
            + str(start_sol)
            + " -> "
            + str(end_sol)
        )
    hold = 1 * crypto_trader.SOL_SCALE
    px_1 = 100 * crypto_trader.USD_SCALE
    px_110 = 110 * crypto_trader.USD_SCALE
    slice_10, take_10 = crypto_bot_dca._cycle_harvest_sol(hold, px_110, px_1)
    if take_10 != 8 * crypto_trader.USD_SCALE:
        raise AssertionError("1.00 to 1.10 must harvest 0.08 not the bag " + str(take_10))
    hold_bag = 56 * crypto_trader.SOL_SCALE
    px_ath = 200 * crypto_trader.USD_SCALE
    px_seed = 2 * crypto_trader.USD_SCALE
    slice_stale, _ = crypto_bot_dca._cycle_harvest_sol(hold_bag, px_ath, px_seed)
    if slice_stale * 2 > hold_bag:
        raise AssertionError("harvest vs 2020 seed is 80 percent of the bag " + str(slice_stale))
    left = hold - slice_10
    left_usd = left * px_110 // crypto_trader.SOL_SCALE
    keep_usd = 102 * crypto_trader.USD_SCALE
    if abs(left_usd - keep_usd) > crypto_trader.USD_SCALE // 2:
        raise AssertionError("principal plus 0.02 must stay " + str(left_usd))
    slice_0, _ = crypto_bot_dca._cycle_harvest_sol(hold, px_1, px_110)
    if slice_0 != 0:
        raise AssertionError("no harvest below the cycle high")
    if not crypto_bot_dca._fee_ok(8 * crypto_trader.USD_SCALE, px_110):
        raise AssertionError("0.08 harvest must clear the 10 percent fee cap")
    dust = crypto_trader.USD_SCALE // 5
    if crypto_bot_dca._fee_ok(dust, px_110):
        raise AssertionError("dust swap must not pay more than 10 percent in fees")
    sold = slice_10
    usd_net = crypto_trader._apply_fee(sold * px_110 // crypto_trader.SOL_SCALE)
    got_same = crypto_trader._apply_fee(usd_net) * crypto_trader.SOL_SCALE // px_110
    if got_same > sold:
        raise AssertionError("same price after fees must not count as more tokens")
    got_low = crypto_trader._apply_fee(usd_net) * crypto_trader.SOL_SCALE // px_1
    if got_low <= sold:
        raise AssertionError("buy at the 1.00 low must return more tokens than sold")
    src = (PROJECT / "backend" / "crypto_bot_dca.py").read_text(encoding="utf-8")
    if "sold_sol == 0" not in src:
        raise AssertionError("must not harvest again before buying back more tokens")
    hybrid_src = (PROJECT / "backend" / "crypto_bot_dca_swing.py").read_text(encoding="utf-8")
    if "sold_sol == 0" not in hybrid_src:
        raise AssertionError("hybrid must keep the one-harvest-then-buyback gate")
    if "_cycle_harvest_sol" not in hybrid_src:
        raise AssertionError("hybrid must reuse the DCA harvest clip")
    hot = {
        "rsi": 78.0,
        "rsi2": 92.0,
        "stoch_rsi": 88.0,
        "mfi": 81.0,
        "cci": 76.0,
        "williams": 84.0,
        "bb": 91.0,
        "uo": 74.0,
        "cmo": 72.0,
        "cmf": 71.0,
        "keltner": 80.0,
        "donchian": 86.0,
        "aroon": 70.0,
        "stc": 72.0,
        "ichimoku": 68.0,
        "supertrend": 80.0,
        "heikin": 72.0,
        "sar": 75.0,
        "ribbon": 80.0,
        "candle": 60.0,
        "stoch_stack": [82.0, 78.0, 74.0, 71.0],
        "stoch": 78.0,
        "stoch_k": 78.0,
        "stoch_d": 81.0,
        "adx": 28.0,
        "macd_hist": 0.4,
        "tema": 100.0,
        "close": 101.0,
    }
    if not crypto_bot_dca_swing.quorum(hot, True):
        raise AssertionError("overbought pack must quorum sell")
    if crypto_bot_dca_swing.quorum(hot, False):
        raise AssertionError("overbought pack must not quorum buy")
    if not crypto_bot_dca_swing.trend_ok(hot, True):
        raise AssertionError("uptrend pack must allow harvest")
    dumped = dict(hot)
    dumped.update(
        {
            "aroon": 18.0,
            "stc": 12.0,
            "ichimoku": 20.0,
            "supertrend": 20.0,
            "heikin": 22.0,
            "sar": 25.0,
            "ribbon": 15.0,
            "candle": 18.0,
        }
    )
    if crypto_bot_dca_swing.trend_ok(dumped, True):
        raise AssertionError("trend pack in a dump must block harvest")
    cold = {
        "rsi": 18.0,
        "rsi2": 8.0,
        "stoch_rsi": 12.0,
        "mfi": 19.0,
        "cci": 22.0,
        "williams": 14.0,
        "bb": 9.0,
        "uo": 24.0,
        "cmo": 21.0,
        "cmf": 16.0,
        "keltner": 20.0,
        "donchian": 11.0,
        "stoch_stack": [22.0, 18.0, 16.0, 14.0],
        "stoch": 18.0,
        "stoch_k": 18.0,
        "stoch_d": 15.0,
        "adx": 12.0,
        "macd_hist": -0.4,
        "tema": 100.0,
        "close": 98.0,
    }
    if not crypto_bot_dca_swing.quorum(cold, False):
        raise AssertionError("oversold pack must quorum buy")
    prev_hot = dict(hot)
    prev_hot["stoch_stack"] = [79.0, 80.0, 76.0, 73.0]
    prev_hot["stoch_k"] = 80.0
    prev_hot["stoch_d"] = 79.0
    prev_hot["macd_hist"] = 0.8
    prev_hot["close"] = 102.0
    prev_hot["tema"] = 100.0
    if not crypto_bot_dca_swing.timing(hot, prev_hot, True):
        raise AssertionError("cluster roll-over must print a harvest timing")
    prev_cross = {
        "stoch_k": 24.0,
        "stoch_d": 24.0,
        "rsi": 22.0,
        "stoch_stack": [24.0, 24.0, 22.0, 20.0],
        "tema": 100.0,
        "close": 99.0,
        "macd_hist": -0.5,
    }
    now_cross = dict(cold)
    now_cross["stoch_k"] = 27.0
    now_cross["stoch_d"] = 26.0
    now_cross["stoch_stack"] = [27.0, 26.0, 22.0, 20.0]
    if not crypto_bot_dca_swing.timing(now_cross, prev_cross, False):
        raise AssertionError("stoch K/D cross up through 25 must print a buy timing")
    crypto_bots.set_book("dca_swing")
    hybrid = crypto_bots.run_backtest(crash_frames)
    if str(hybrid.get("book") or "") != "dca_swing":
        raise AssertionError("hybrid book " + str(hybrid.get("book")))
    end_hy = float(str(hybrid.get("tokens") or hybrid.get("float_sol") or "0"))
    start_hy = float(str(hybrid.get("start_sol") or "0"))
    if start_hy > 0 and end_hy < start_hy * 0.95:
        raise AssertionError(
            "DCA+SWING must not sell principal into a crash "
            + str(start_hy)
            + " -> "
            + str(end_hy)
        )
    note = str(hybrid.get("note") or "")
    if "80%" not in note or "osc" not in note.lower():
        raise AssertionError("hybrid note must name harvest and osc " + note)
    print("CRYPTO_BOTS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
