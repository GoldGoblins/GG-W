#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_contract, crypto_trader


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gg-trader-"))
    crypto_contract.STATE_DIR = tmp
    crypto_trader.reset_book()
    crypto_trader.set_armed(True)
    sig_buy = {"super": "buy"}
    sig_sell = {"super": "sell"}
    t0 = 1_700_000_000
    book = crypto_trader.tick(100.0, sig_buy, "range", 0.02, now=t0)
    if book["trades_today"] != 1:
        raise AssertionError("buy not counted")
    if book["sol"] in ("0.000000000", "—"):
        raise AssertionError("no sol after buy " + book["sol"])
    if book["banked_sol"] not in ("0.000000000", "0"):
        raise AssertionError("start 2 SOL must all be float " + book["banked_sol"])
    vault_after_seed = book["banked_sol"]
    book = crypto_trader.tick(110.0, sig_sell, "range", 0.02, now=t0 + 8 * 60)
    if int(book["trades_today"]) != 2:
        raise AssertionError("sell not counted " + str(book))
    if book["banked_sol"] in ("0.000000000", "0", "—"):
        raise AssertionError("20 percent profit not banked " + book["banked_sol"])
    if book["banked_sol"] == vault_after_seed:
        raise AssertionError("profit was not vaulted")
    blocked = crypto_trader.tick(90.0, sig_buy, "trend_down", 0.02, now=t0 + 16 * 60)
    if blocked["last"].get("action") == "buy":
        raise AssertionError("buy in trend_down")

    crypto_trader.reset_book()
    crypto_trader.set_armed(True)
    first = crypto_trader.tick(100.0, sig_buy, "range", 0.02, now=t0)
    vault = first["banked_sol"]
    lost = crypto_trader.tick(80.0, sig_sell, "range", 0.02, now=t0 + 8 * 60)
    if lost["banked_sol"] != vault:
        raise AssertionError(
            "vault moved on loss " + vault + " -> " + lost["banked_sol"]
        )
    if int(lost.get("max_day") or 0) != 34:
        raise AssertionError("max day " + str(lost.get("max_day")))

    closes = [100.0] * 120 + [125.0] * 80
    highs = [item + 1.0 for item in closes]
    lows = [item - 1.0 for item in closes]
    sigs = ["none"] * 200
    sigs[90] = "buy"
    sigs[150] = "sell"
    report = crypto_trader.run_backtest(highs, lows, closes, signals=sigs)
    if not report.get("banked_never_fell"):
        raise AssertionError("backtest vault fell")
    if not report.get("banked_grew"):
        raise AssertionError("backtest vault empty " + str(report))
    if int(report.get("sells") or 0) < 1:
        raise AssertionError("backtest no sell " + str(report))
    chart = report.get("chart") or {}
    if len(chart.get("closes") or []) < 2:
        raise AssertionError("backtest chart missing")
    if len(chart.get("times") or []) != len(chart.get("closes") or []):
        raise AssertionError("backtest chart times")
    if not chart.get("marks"):
        raise AssertionError("backtest marks missing")

    sigs2 = ["none"] * 80 + ["buy"] * 40
    packed = crypto_trader.run_backtest(highs, lows, closes, signals=sigs2)
    if int(packed.get("fills") or 0) > 34:
        raise AssertionError("day cap broken " + str(packed.get("fills")))
    series = crypto_trader.signal_series(highs, lows, closes)
    if "buy" not in series and "sell" not in series:
        raise AssertionError("variant signals empty")
    if crypto_trader.mtf_super({"1m": "buy", "5m": "buy", "15m": "none", "1h": "none"}) != "buy":
        raise AssertionError("mtf buy")
    if crypto_trader.mtf_super({"1m": "buy", "5m": "buy", "15m": "none", "1h": "sell"}) != "none":
        raise AssertionError("1h veto")
    crypto_trader.reset_book()
    crypto_trader.set_armed(True)
    mid = {"1h": {"rsi": 40.0, "buy_n": 1, "sell_n": 0, "close": 100.0}}
    no = crypto_trader.tick(
        100.0, {"super": "buy"}, "range", 0.02, now=t0 + 100, tf_osc=mid
    )
    if no["last"].get("action") == "buy":
        raise AssertionError("rsi 40 must not buy")
    aplus = {
        "1d": {"rsi": 52.0},
        "8h": {"rsi": 48.0},
        "4h": {"rsi": 44.0},
        "1h": {"rsi": 22.0},
        "15m": {"rsi": 20.0},
        "5m": {"rsi": 40.0},
        "1m": {"rsi": 40.0},
    }
    aplus_flow = {
        "1d": "trend_up",
        "8h": "trend_up",
        "4h": "trend_up",
        "1h": "range",
        "15m": "range",
        "5m": "range",
        "1m": "range",
    }
    yes = crypto_trader.tick(
        100.0,
        {"super": "none"},
        "trend_up",
        0.02,
        now=t0 + 200,
        tf_osc=aplus,
        tf_flow=aplus_flow,
    )
    if yes["last"].get("action") != "buy":
        raise AssertionError("1d/4h bull + 1h/15m dip should buy " + str(yes["last"]))
    against = crypto_trader.confluence_vote(
        {"1d": {"rsi": 30.0}, "1h": {"rsi": 22.0}, "15m": {"rsi": 18.0}},
        tf_super={"1h": "buy", "15m": "buy"},
        tf_flow={"1d": "trend_down", "4h": "trend_down", "1h": "range"},
    )
    if against.get("side") == "sell":
        raise AssertionError("do not sell the crash " + str(against))
    if against.get("side") == "buy" or against.get("dca"):
        raise AssertionError("do not buy a 1d+4h waterfall " + str(against))
    hi = {
        "1d": {"rsi": 60.0},
        "8h": {"rsi": 62.0},
        "4h": {"rsi": 58.0},
        "1h": {"rsi": 74.0},
        "15m": {"rsi": 78.0},
    }
    hi_flow = {
        "1d": "trend_up",
        "8h": "trend_up",
        "4h": "trend_up",
        "1h": "range",
        "15m": "range",
    }
    out = crypto_trader.tick(
        110.0,
        {"super": "none"},
        "trend_up",
        0.02,
        now=t0 + 400,
        tf_osc=hi,
        tf_flow=hi_flow,
    )
    if out.get("sol") in ("0.000000000", "0", "—"):
        raise AssertionError("dip-buy in 1d bull must keep a bag " + str(out))
    if out["last"].get("note", "").find("bag ") >= 0:
        raise AssertionError("1h rip must not be a cycle dump " + str(out["last"]))
    if crypto_trader.TIMEFRAMES != ("1m", "5m", "15m", "1h", "4h", "8h", "1d"):
        raise AssertionError("seven timeframes")
    if crypto_trader.MACRO_TFS[0] != "1d":
        raise AssertionError("macro starts at 1d")
    if int(crypto_trader.MAX_OPEN_LOTS) < 16:
        raise AssertionError("need many concurrent swings")
    flat_state = crypto_trader.default_state()
    flat_state["armed"] = True
    flat_state["usd"] = 50 * crypto_trader.USD_SCALE
    flat_state["banked_usd"] = 10 * crypto_trader.USD_SCALE
    flat_state["sol"] = 1 * crypto_trader.SOL_SCALE
    flat_opens = [
        {
            "id": "lot-x",
            "side": "sell",
            "sol": 1 * crypto_trader.SOL_SCALE // 10,
            "usd": 10 * crypto_trader.USD_SCALE,
            "closed": False,
        }
    ]
    flat_lots: list = list(flat_opens)
    usd_before = int(flat_state.get("usd") or 0)
    crypto_trader.flatten_book(
        flat_state, flat_lots, flat_opens, 120.0, t0 + 900, reason="end"
    )
    if flat_opens:
        raise AssertionError("flatten must not keep phantom swings")
    if int(flat_state.get("usd") or 0) != usd_before:
        raise AssertionError("flatten must not buy just because the clock moved")
    dca = crypto_trader.confluence_vote(
        {
            "1d": {"rsi": 22.0},
            "4h": {"rsi": 24.0},
            "1h": {"rsi": 18.0},
            "15m": {"rsi": 16.0},
        },
        tf_super={"1h": "buy", "15m": "buy"},
        tf_flow={"1d": "trend_down", "4h": "range", "8h": "trend_down"},
    )
    if not dca.get("dca") or dca.get("side") != "buy":
        raise AssertionError("bear bottom should DCA buy " + str(dca))
    hold_bag = crypto_trader.confluence_vote(
        {
            "1d": {"rsi": 55.0},
            "4h": {"rsi": 74.0},
            "1h": {"rsi": 76.0},
            "15m": {"rsi": 72.0},
        },
        tf_super={"1h": "sell", "15m": "sell", "4h": "sell"},
        tf_flow={"1d": "trend_up", "4h": "trend_up", "8h": "trend_up"},
    )
    if hold_bag.get("bag_sell"):
        raise AssertionError("1h/4h rip in a 1d bull must not dump the bag " + str(hold_bag))
    stacked = crypto_trader.confluence_vote(
        {
            "1d": {"rsi": 82.0},
            "8h": {"rsi": 80.0},
            "4h": {"rsi": 74.0},
            "1h": {"rsi": 76.0},
            "15m": {"rsi": 72.0},
        },
        tf_super={"1d": "sell", "8h": "sell", "4h": "sell", "1h": "sell"},
        tf_flow={"1d": "trend_up", "8h": "trend_up", "4h": "trend_up", "1h": "range"},
    )
    if not stacked.get("bag_sell"):
        raise AssertionError("1d+8h+4h+1h sell is a cycle top " + str(stacked))
    early = crypto_trader.confluence_vote(
        {
            "1d": {"rsi": 72.0},
            "8h": {"rsi": 80.0},
            "4h": {"rsi": 74.0},
            "1h": {"rsi": 76.0},
            "15m": {"rsi": 72.0},
        },
        tf_super={"1d": "sell", "8h": "sell", "4h": "sell", "1h": "sell"},
        tf_flow={"1d": "trend_up", "8h": "trend_up", "4h": "trend_up", "1h": "range"},
    )
    if early.get("bag_sell"):
        raise AssertionError("1d RSI 70 is not cycle euphoria " + str(early))
    if int(crypto_trader.BAG_SLICE_BPS) != 10000:
        raise AssertionError("cycle top must sell the bag")
    if int(crypto_trader.DCA_BPS) != 10000:
        raise AssertionError("DCA must spend the powder")
    if int(crypto_trader.BAG_OB_NEED) < 40:
        raise AssertionError("do not dump on the first RSI70 week")
    if crypto_trader.EXECUTE_CYCLE_BAG:
        raise AssertionError("do not sit a year in cash after a cycle vote")
    if tuple(row["id"] for row in crypto_trader.SWINGS) != ("day", "week", "month"):
        raise AssertionError("need day/week/month swings")
    if crypto_trader._index_closed_at_or_before([1000], 1000 + 86399, 86400) is not None:
        raise AssertionError("1d close must not be visible before the day ends")
    if crypto_trader._index_closed_at_or_before([1000], 1000 + 86400, 86400) != 0:
        raise AssertionError("1d close is visible only after the candle closes")
    if crypto_trader._at_year_low({"day_lows": [10.0] * 10}, {"1d": {"close": 8.0}}):
        raise AssertionError("warmup must not fake a 365d low")
    if crypto_trader._timing_oversold({"4h": {"rsi": 32.0}, "1d": {"rsi": 55.0}}):
        raise AssertionError("4h 32 is not the 25 buy band")
    if not crypto_trader._timing_oversold({"4h": {"rsi": 24.0}, "1d": {"rsi": 55.0}}):
        raise AssertionError("4h 24 is the 25 buy band")
    if crypto_trader._tf_hook(
        {"rsi": 22.0, "stoch": 50.0}, {"rsi": 18.0, "stoch": 50.0}, False
    ):
        raise AssertionError("rsi without stoch in zone is not the guess")
    if not crypto_trader._tf_hook(
        {"rsi": 40.0, "stoch": 22.0}, {"rsi": 40.0, "stoch": 18.0}, False
    ):
        raise AssertionError("stoch turning in the buy band is the guess")
    if crypto_trader._zone_turn(20.0, 18.0, False):
        raise AssertionError("falling in the buy band is not a buy")
    if not crypto_trader._zone_turn(18.0, 22.0, False):
        raise AssertionError("turning up under 25 is the buy")
    if crypto_trader._zone_turn(72.0, 78.0, True):
        raise AssertionError("rising in the sell band is not a sell")
    if not crypto_trader._zone_turn(78.0, 72.0, True):
        raise AssertionError("turning down over 70 is the sell")
    src = (PROJECT / "backend" / "crypto_trader.py").read_text(encoding="utf-8")
    if 'int(state.get("sol") or 0) <= 0' not in src or "_powder_usd(state) <= 0" not in src:
        raise AssertionError("price grid must not skip bars while the bag is held")
    day_cfg = next(row for row in crypto_trader.SWINGS if row["id"] == "day")
    fee_floor = 2 * int(crypto_trader.FEE_BPS) + 20
    if int(day_cfg["cover_bps"]) < fee_floor or int(day_cfg["min_move_bps"]) < fee_floor:
        raise AssertionError("day grid must still clear roundtrip fees")
    if int(day_cfg["min_move_bps"]) > 200 or int(day_cfg["cover_bps"]) > 200:
        raise AssertionError("day grid is 1-2 percent levels, not a 3 percent wait")
    if int(crypto_trader.GRID_STEP_BPS) < 2 * int(crypto_trader.FEE_BPS) + 20:
        raise AssertionError("range fee floor must clear roundtrip")
    if int(crypto_trader.GRID_STEP_BPS) > 150:
        raise AssertionError("range fee floor too wide")
    if "GRID_TREND_STEP_BPS" in src:
        raise AssertionError("no hardcoded 3 percent ladder — hold while momentum is up")
    if int(crypto_trader.DAY_HOLD_SEC) < 86400:
        raise AssertionError("momentum hold must last at least a day")
    if int((crypto_trader.HORIZONS.get("day") or {}).get("max_open") or 0) < 8:
        raise AssertionError("day book needs many concurrent grid levels")
    if int(crypto_trader.DAY_HOLD_SEC) > 3 * 86400:
        raise AssertionError("day lots must not sit idle for months")
    if int(day_cfg.get("park_sec") or 0) != 0:
        raise AssertionError("do not park and hope — the day ledger is now")
    if int(crypto_trader.ENTRY_GAP_SEC) > 3600:
        raise AssertionError("entry gap is not a day wait")
    if 'notes.append("wait year low")' in src:
        raise AssertionError("must not wait for a year low")
    if crypto_trader.osc_buy_depth(30.0) != 0 or crypto_trader.osc_buy_depth(24.0) != 1:
        raise AssertionError("25 is the buy zone edge")
    if crypto_trader.osc_buy_depth(5.0) != 5 or crypto_trader.osc_buy_depth(10.0) != 4:
        raise AssertionError("extra buy tiers 20/15/10/5")
    if crypto_trader.osc_sell_depth(69.0) != 0 or crypto_trader.osc_sell_depth(70.0) != 1:
        raise AssertionError("70 is the sell zone edge")
    if crypto_trader.osc_sell_depth(90.0) != 3:
        raise AssertionError("extra sell tiers 80/90")
    if crypto_trader.BUY_TIERS != (25.0, 20.0, 15.0, 10.0, 5.0):
        raise AssertionError("same 0-100 buy tiers for rsi and stoch")
    stoch_buy = crypto_trader._tf_wants_buy(
        "1h",
        {"1h": {"rsi": 40.0, "stoch": 18.0}},
        {},
    )
    if not stoch_buy:
        raise AssertionError("stoch uses the same 25 buy zone")
    stacked_top = crypto_trader.stack_zone(
        {
            "1d": {"rsi": 55.0},
            "4h": {"rsi": 74.0, "stoch": 81.0},
            "1h": {"rsi": 76.0},
            "15m": {"stoch": 72.0},
        },
        sell=True,
    )
    if int(stacked_top.get("n") or 0) < 3 or int(stacked_top.get("depth") or 0) < 2:
        raise AssertionError("multi-tf 70/80 is closer to THE top " + str(stacked_top))
    day_needs_tape = crypto_trader.swing_vote(
        "day",
        {
            "1d": {"rsi": 55.0},
            "1h": {"rsi": 74.0},
            "15m": {"rsi": 72.0},
            "5m": {"rsi": 40.0},
            "1m": {"rsi": 42.0},
        },
        tf_flow={"1d": "trend_up", "4h": "trend_up", "1h": "range"},
    )
    if day_needs_tape.get("side") != "sell":
        raise AssertionError("day book is a 3-5 percent price tape, not RSI70 " + str(day_needs_tape))
    day_tape = crypto_trader.swing_vote(
        "day",
        {
            "1d": {"rsi": 55.0},
            "1h": {"rsi": 74.0},
            "15m": {"rsi": 72.0},
            "5m": {"rsi": 71.0},
        },
        tf_flow={"1d": "trend_up", "4h": "trend_up", "1h": "range"},
    )
    if day_tape.get("side") != "sell":
        raise AssertionError("15m structure + 5m flow is the day rip " + str(day_tape))
    week_rip = crypto_trader.swing_vote(
        "week",
        {"1d": {"rsi": 55.0}, "4h": {"rsi": 74.0}, "1h": {"rsi": 76.0}, "15m": {"rsi": 72.0}},
        tf_flow={"1d": "trend_up", "4h": "trend_up", "1h": "range"},
    )
    if week_rip.get("side") != "sell":
        raise AssertionError("week rip should slice float " + str(week_rip))
    month_early = crypto_trader.swing_vote(
        "month",
        {"1d": {"rsi": 55.0}, "8h": {"rsi": 71.0}, "4h": {"rsi": 70.0}, "1h": {"rsi": 50.0}},
        tf_flow={"1d": "trend_up", "8h": "trend_up", "4h": "trend_up", "1h": "range"},
    )
    if month_early.get("side") != "sell":
        raise AssertionError("month 8h/4h rip inside a 1d bull should slice " + str(month_early))
    if crypto_trader.swing_vote(
        "month",
        {"1d": {"rsi": 72.0}, "8h": {"rsi": 71.0}, "4h": {"rsi": 70.0}, "1h": {"rsi": 50.0}},
        tf_flow={"1d": "trend_up", "8h": "trend_up", "4h": "trend_up", "1h": "range"},
    ).get("side") == "sell":
        raise AssertionError("1d overbought is the cycle top, not a month slice")
    if int(crypto_trader.FLOAT_KEEP_BPS) < 1000:
        raise AssertionError("perpetual day float too small")
    day_bear = crypto_trader.swing_vote(
        "day",
        {
            "1d": {"rsi": 30.0},
            "1h": {"rsi": 74.0},
            "15m": {"rsi": 72.0},
            "5m": {"rsi": 71.0},
        },
        tf_flow={"1d": "trend_down", "4h": "range", "1h": "range"},
    )
    if day_bear.get("side") != "sell":
        raise AssertionError("day book must stay on in a 1d bear " + str(day_bear))
    day_crash = crypto_trader.swing_vote(
        "day",
        {
            "1d": {"rsi": 30.0},
            "1h": {"rsi": 74.0},
            "15m": {"rsi": 72.0},
            "5m": {"rsi": 71.0},
        },
        tf_flow={"1d": "trend_down", "4h": "trend_down", "1h": "range"},
    )
    if day_crash.get("side") != "sell":
        raise AssertionError("day grid stays on in the 1d+4h waterfall " + str(day_crash))
    crash_week = crypto_trader.swing_vote(
        "week",
        {"1d": {"rsi": 30.0}, "4h": {"rsi": 74.0}, "1h": {"rsi": 76.0}},
        tf_flow={"1d": "trend_down", "4h": "trend_down", "1h": "range"},
    )
    if crash_week.get("side") != "none":
        raise AssertionError("do not swing-sell the waterfall " + str(crash_week))
    week_bar = {
        "1d": {"rsi": 55.0},
        "8h": {"rsi": 52.0},
        "4h": {"rsi": 74.0},
        "1h": {"rsi": 76.0},
        "15m": {"rsi": 72.0},
    }
    sliced = crypto_trader.tick(
        128.0,
        {"super": "none"},
        "trend_up",
        0.02,
        now=t0 + 400 + 4 * 86400,
        tf_osc=week_bar,
        tf_flow=aplus_flow,
    )
    if sliced.get("sol") in ("0.000000000", "0", "—"):
        raise AssertionError("nested slice dumped the bag " + str(sliced))
    if sliced.get("sol") in ("0.000000000", "0", "—"):
        raise AssertionError("nested slice dumped the bag " + str(sliced))
    t0 = 1_598_000_000
    tiny_c = [20.0 + (i % 30) * 0.2 for i in range(160)]
    tiny_h = [x + 0.4 for x in tiny_c]
    tiny_l = [x - 0.4 for x in tiny_c]
    tiny_v = [10.0] * 160
    tiny_t = [t0 + i * 300 for i in range(160)]
    flow_bt = crypto_trader.run_flow_backtest(
        {
            "5m": {
                "highs": tiny_h,
                "lows": tiny_l,
                "closes": tiny_c,
                "volumes": tiny_v,
                "times": tiny_t,
            }
        },
        persist=False,
    )
    if int(flow_bt.get("bars") or 0) != 160:
        raise AssertionError("flow backtest bars " + str(flow_bt.get("bars")))
    if not str(flow_bt.get("pnl_sol") or "").strip():
        raise AssertionError("PnL must be SOL " + str(flow_bt.get("pnl_sol")))
    if "pnl_usd" in flow_bt:
        raise AssertionError("headline PnL still USD")
    if not (flow_bt.get("weeks") or []):
        raise AssertionError("weekly tape missing")
    day_n = 500
    day_c = [20.0 + (i % 40) * 0.4 for i in range(day_n)]
    day_h = [x + 0.8 for x in day_c]
    day_l = [x - 0.8 for x in day_c]
    day_v = [12.0] * day_n
    day_t = [t0 + i * 86400 for i in range(day_n)]
    min_n = 100
    min_c = [day_c[-1] + (i % 5) * 0.1 for i in range(min_n)]
    min_t = [day_t[-1] - (min_n - 1 - i) * 60 for i in range(min_n)]
    span_bt = crypto_trader.run_flow_backtest(
        {
            "1m": {
                "highs": [x + 0.2 for x in min_c],
                "lows": [x - 0.2 for x in min_c],
                "closes": min_c,
                "volumes": [1.0] * min_n,
                "times": min_t,
            },
            "1d": {
                "highs": day_h,
                "lows": day_l,
                "closes": day_c,
                "volumes": day_v,
                "times": day_t,
            },
        },
        persist=False,
    )
    if span_bt.get("primary") != "1d":
        raise AssertionError("short 1m must not skip the 1d years " + str(span_bt.get("primary")))
    long = 40 * 86400
    stamps = [t0 + i * (long // 9) for i in range(10)]
    clock = crypto_trader._walk_primary(
        {
            "1m": {"closes": [1.0] * 10, "times": stamps},
            "5m": {"closes": [1.0] * 10, "times": stamps},
            "1h": {"closes": [1.0] * 10, "times": stamps},
            "1d": {"closes": [1.0] * 10, "times": stamps},
        }
    )
    if clock != "1h":
        raise AssertionError("long backtest clock must be 1h not " + str(clock))
    if int(span_bt.get("bars") or 0) != day_n:
        raise AssertionError("walked short 1m " + str(span_bt.get("bars")))
    weeks = span_bt.get("weeks") or []
    if len(weeks) < 40:
        raise AssertionError("weekly tape skipped weeks " + str(len(weeks)))
    months = span_bt.get("months") or []
    if len(months) < 12:
        raise AssertionError("months skipped " + str([m.get("month") for m in months]))
    years = span_bt.get("years") or []
    if len(years) < 2:
        raise AssertionError("year roll missing " + str(years))
    marks = ((span_bt.get("chart") or {}).get("marks") or [])
    fills = int(span_bt.get("fills") or 0)
    if fills > 80 and len(marks) > max(120, fills // 2):
        raise AssertionError("chart still dumps every day fill " + str(len(marks)))
    if not ((span_bt.get("chart") or {}).get("equity") or []):
        raise AssertionError("SOL equity overlay missing")
    if "pnl_sol" not in report:
        raise AssertionError("bar backtest PnL not SOL")
    crypto_trader.save_backtest({"n": 1, "chart": {"closes": [1.0, 2.0]}})
    crypto_trader.save_backtest({"n": 2, "chart": {"closes": [3.0, 4.0]}})
    if int((crypto_trader.load_backtest() or {}).get("n") or 0) != 2:
        raise AssertionError("latest backtest not kept")
    if int((crypto_trader.load_backtest_prev() or {}).get("n") or 0) != 1:
        raise AssertionError("previous backtest not rotated")
    scored = crypto_trader._trade_stats(
        [
            {"side": "sell", "horizon": "day", "parked": True, "sol": 1, "usd": 1, "price": 1},
            {"side": "buy", "extra_sol": 10, "horizon": "day"},
        ],
        0,
        0,
        [1],
        sol_held=crypto_trader.START_SOL,
        last_close=100.0,
        start_sol=crypto_trader.START_SOL,
    )
    if float(scored.get("win_rate") or 0) >= 99:
        raise AssertionError("parked float must count against win rate " + str(scored))
    cash = crypto_trader._trade_stats(
        [],
        0,
        200 * crypto_trader.USD_SCALE,
        [1],
        sol_held=0,
        last_close=1.0,
        start_sol=crypto_trader.START_SOL,
    )
    try:
        cash_pnl = float(str(cash.get("pnl_sol") or "0"))
    except (TypeError, ValueError):
        cash_pnl = 0.0
    if cash_pnl > 0:
        raise AssertionError("USD powder counted as SOL pnl " + str(cash))
    stuck = crypto_trader.default_state()
    stuck["armed"] = True
    stuck["seeded"] = True
    stuck["seed_style"] = "long"
    stuck["sol"] = 40 * crypto_trader.SOL_SCALE
    stuck["usd"] = 0
    stuck["float_usd"] = 80 * crypto_trader.USD_SCALE
    stuck["peak_tokens"] = 80 * crypto_trader.SOL_SCALE
    stuck["start_sol"] = 80 * crypto_trader.SOL_SCALE
    stuck["grid_px"] = 100 * crypto_trader.USD_SCALE
    stuck["osc_prev"] = {
        tf: {"rsi": 18.0, "stoch": 18.0} for tf in crypto_trader.TIMEFRAMES
    }
    stuck_lots: list = []
    crypto_trader.apply_horizons(
        stuck,
        stuck_lots,
        90.0,
        {
            "1d": {"rsi": 22.0, "stoch": 22.0, "close": 90.0},
            "4h": {"rsi": 22.0, "stoch": 22.0},
            "1h": {"rsi": 22.0, "stoch": 22.0},
            "15m": {"rsi": 22.0, "stoch": 22.0},
        },
        "range",
        2_000_000_000,
        tf_flow={"1d": "range", "4h": "range", "1h": "range"},
        open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in stuck_lots):
        raise AssertionError("ATH peak must not freeze the current 15 percent float")
    stuck_up = crypto_trader.default_state()
    stuck_up["armed"] = True
    stuck_up["seeded"] = True
    stuck_up["seed_style"] = "long"
    stuck_up["sol"] = 40 * crypto_trader.SOL_SCALE
    stuck_up["usd"] = 80 * crypto_trader.USD_SCALE
    stuck_up["peak_tokens"] = 80 * crypto_trader.SOL_SCALE
    stuck_up["grid_px"] = 100 * crypto_trader.USD_SCALE
    stuck_up["osc_prev"] = {
        tf: {"rsi": 50.0, "stoch": 50.0} for tf in crypto_trader.TIMEFRAMES
    }
    up_lots: list = []
    crypto_trader.apply_horizons(
        stuck_up,
        up_lots,
        101.2,
        {
            "1d": {"rsi": 50.0, "stoch": 50.0, "close": 101.2},
            "4h": {"rsi": 50.0, "stoch": 50.0},
            "1h": {"rsi": 50.0, "stoch": 50.0},
            "15m": {"rsi": 50.0, "stoch": 50.0},
        },
        "range",
        2_000_000_100,
        tf_flow={"1d": "range", "4h": "range", "1h": "range"},
        open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-sell") for row in up_lots):
        raise AssertionError("stuck bag must not grind-sell the core")
    src = (PROJECT / "backend" / "crypto_trader.py").read_text(encoding="utf-8")
    if "def _replay_float_15m" not in src:
        raise AssertionError("1h clock must still print 15m float turns")
    if "for j, t_open in enumerate(times15)" in src:
        raise AssertionError("15m replay must not scan the whole tape every hour")
    pocket = crypto_trader.default_state()
    pocket["armed"] = True
    pocket["seeded"] = True
    pocket["seed_style"] = "long"
    pocket["cash_cycle"] = True
    pocket["sol"] = 12 * crypto_trader.SOL_SCALE
    pocket["peak_tokens"] = 80 * crypto_trader.SOL_SCALE
    pocket["grid_px"] = 100 * crypto_trader.USD_SCALE
    pocket["osc_prev"] = {
        tf: {"rsi": 80.0, "stoch": 80.0} for tf in crypto_trader.TIMEFRAMES
    }
    pocket_lots: list = []
    crypto_trader.apply_horizons(
        pocket,
        pocket_lots,
        101.2,
        {
            "1d": {"rsi": 72.0, "stoch": 72.0, "close": 101.2},
            "4h": {"rsi": 72.0, "stoch": 72.0},
            "1h": {"rsi": 72.0, "stoch": 72.0},
            "15m": {"rsi": 72.0, "stoch": 72.0},
        },
        "range",
        2_000_000_200,
        tf_flow={"1d": "range", "4h": "range", "1h": "range"},
        open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-sell") for row in pocket_lots):
        raise AssertionError("cash-cycle 15 percent pocket must still trim")
    idle = crypto_trader._idle_gaps(
        [
            {"month": "2024-01", "fills": 0},
            {"month": "2024-02", "fills": 0},
            {"month": "2024-03", "fills": 3},
        ]
    )
    if not idle or int(idle[0].get("months") or 0) != 2:
        raise AssertionError("idle month gaps " + str(idle))
    def _book() -> dict:
        st = crypto_trader.default_state()
        st["armed"] = True
        st["seeded"] = True
        st["seed_style"] = "long"
        st["sol"] = 60 * crypto_trader.SOL_SCALE
        st["usd"] = 0
        st["peak_tokens"] = 60 * crypto_trader.SOL_SCALE
        st["start_sol"] = 60 * crypto_trader.SOL_SCALE
        st["grid_px"] = 100 * crypto_trader.USD_SCALE
        st["cost_px"] = 100 * crypto_trader.USD_SCALE
        return st

    def _osc(rsi_1d: float, close: float = 100.0) -> dict:
        return {
            "1d": {"rsi": rsi_1d, "close": close, "stoch": rsi_1d},
            "4h": {"rsi": rsi_1d, "stoch": rsi_1d},
            "1h": {"rsi": 50.0, "stoch": 50.0},
            "15m": {"rsi": 50.0, "stoch": 50.0},
            "5m": {"rsi": 50.0, "stoch": 50.0},
        }

    def _prev(rsi: float) -> dict:
        row = {"rsi": rsi, "stoch": rsi}
        return {tf: dict(row) for tf in crypto_trader.TIMEFRAMES}

    range_flow = {"1d": "range", "4h": "range", "1h": "range"}
    bull_flow = {"1d": "trend_up", "4h": "trend_up", "1h": "range"}
    bear_flow = {"1d": "trend_down", "4h": "trend_down", "1h": "range"}
    mid = _osc(50.0)
    hot = _osc(75.0, 110.0)
    cold = _osc(20.0, 90.0)
    g = _book()
    g["osc_prev"] = _prev(80.0)
    g_lots: list = []
    crypto_trader.apply_horizons(
        g, g_lots, 101.2, mid, "range", 1_700_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-") for row in g_lots):
        raise AssertionError("range mid-band must not scalp 1 percent " + str(g.get("last")))
    g["osc_prev"] = _prev(80.0)
    crypto_trader.apply_horizons(
        g, g_lots, 110.0, hot, "range", 1_700_000_000 + 60,
        tf_flow=range_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-sell") for row in g_lots):
        raise AssertionError("sell band turning down may trim " + str(g.get("last")))
    n_trim = sum(1 for row in g_lots if str(row.get("id") or "").startswith("grid-sell"))
    crypto_trader.apply_horizons(
        g, g_lots, 109.0, hot, "range", 1_700_000_000 + 120,
        tf_flow=range_flow, open_rows=[],
    )
    n_soon = sum(1 for row in g_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_soon != n_trim:
        raise AssertionError("do not refill inside the same 15m candle")
    crypto_trader.apply_horizons(
        g, g_lots, 115.0, _osc(78.0, 115.0), "range", 1_700_000_000 + 960,
        tf_flow=range_flow, open_rows=[],
    )
    n_up = sum(1 for row in g_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_up != n_trim:
        raise AssertionError("still running up in the sell band is not another dump")
    crypto_trader.apply_horizons(
        g, g_lots, 105.0, _osc(45.0, 105.0), "range", 1_700_000_000 + 1860,
        tf_flow=range_flow, open_rows=[],
    )
    g["osc_prev"] = _prev(80.0)
    crypto_trader.apply_horizons(
        g, g_lots, 111.0, _osc(74.0, 111.0), "range", 1_700_000_000 + 2760,
        tf_flow=range_flow, open_rows=[],
    )
    n_re = sum(1 for row in g_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_re <= n_trim:
        raise AssertionError("a new visit to the sell band may slice again")
    g2 = _book()
    g2["float_usd"] = 50 * crypto_trader.USD_SCALE
    g2["osc_prev"] = _prev(18.0)
    g2_lots: list = []
    crypto_trader.apply_horizons(
        g2, g2_lots, 90.0, cold, "range", 1_710_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in g2_lots):
        raise AssertionError("range turning up under 25 may buy")
    g3 = _book()
    g3["grid_px"] = 200 * crypto_trader.USD_SCALE
    g3["float_usd"] = 50 * crypto_trader.USD_SCALE
    g3_lots: list = []
    crypto_trader.apply_horizons(
        g3, g3_lots, 100.0, cold, "trend_down", 2_000_000_000,
        tf_flow=bear_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-") for row in g3_lots):
        raise AssertionError("bear must not trade the float " + str(g3.get("last")))
    gb = _book()
    gb_lots: list = []
    crypto_trader.apply_horizons(
        gb, gb_lots, 101.2, mid, "trend_up", 1_900_000_000,
        tf_flow=bull_flow, open_rows=[],
    )
    crypto_trader.apply_horizons(
        gb, gb_lots, 200.0, mid, "trend_up", 1_900_000_000 + 86400,
        tf_flow=bull_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-sell") for row in gb_lots):
        raise AssertionError("bull must hold a 100 percent run while 1d is up")
    crypto_trader.apply_horizons(
        gb, gb_lots, 210.0, hot, "trend_up", 1_900_000_000 + 2 * 86400,
        tf_flow=bull_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-sell") for row in gb_lots):
        raise AssertionError("entering the sell band while still rising is not a sell")
    crypto_trader.apply_horizons(
        gb, gb_lots, 208.0, _osc(72.0, 208.0), "trend_up",
        1_900_000_000 + 3 * 86400,
        tf_flow=bull_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-sell") for row in gb_lots):
        raise AssertionError("bull sell-band rolling over may trim")
    gh = _book()
    gh["float_usd"] = 50 * crypto_trader.USD_SCALE
    gh["osc_prev"] = _prev(18.0)
    gh_lots: list = []
    crypto_trader.apply_horizons(
        gh, gh_lots, 90.0, cold, "trend_up", 2_100_000_000,
        tf_flow=bull_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in gh_lots):
        raise AssertionError("bull still buys an oversold dip")
    n_sell_before = sum(1 for row in gh_lots if str(row.get("id") or "").startswith("grid-sell"))
    crypto_trader.apply_horizons(
        gh, gh_lots, 200.0, mid, "trend_up", 2_100_000_000 + 60,
        tf_flow=bull_flow, open_rows=[],
    )
    n_sell_after = sum(1 for row in gh_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_sell_after != n_sell_before:
        raise AssertionError("bull run after a dip buy must stay held")
    gd = _book()
    gd["float_usd"] = 50 * crypto_trader.USD_SCALE
    gd["osc_prev"] = _prev(50.0)
    gd["osc_prev"]["4h"] = {"rsi": 18.0, "stoch": 18.0}
    gd_lots: list = []
    pull = {
        "1d": {"rsi": 55.0, "close": 90.0, "stoch": 55.0},
        "4h": {"rsi": 24.0, "stoch": 24.0},
        "1h": {"rsi": 40.0, "stoch": 40.0},
        "15m": {"rsi": 50.0, "stoch": 50.0},
        "5m": {"rsi": 50.0, "stoch": 50.0},
    }
    crypto_trader.apply_horizons(
        gd, gd_lots, 90.0, pull, "trend_up", 2_300_000_000,
        tf_flow=bull_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in gd_lots):
        raise AssertionError("bull 4h pullback should add tokens")
    rj = _book()
    rj["float_usd"] = 50 * crypto_trader.USD_SCALE
    rj["swing_high"] = {
        "week": 200 * crypto_trader.USD_SCALE,
        "month": 200 * crypto_trader.USD_SCALE,
        "day": 200 * crypto_trader.USD_SCALE,
    }
    rj_lots: list = []
    crypto_trader.apply_horizons(
        rj, rj_lots, 100.0, mid, "range", 2_200_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if any("rejoin" in str(row.get("id") or "") for row in rj_lots):
        raise AssertionError("stale swing_high must not dump float_usd as a rejoin")
    gc = _book()
    gc["cash_cycle"] = True
    gc["bag_armed"] = False
    gc["usd"] = 1000 * crypto_trader.USD_SCALE
    gc["float_usd"] = 50 * crypto_trader.USD_SCALE
    gc["osc_prev"] = _prev(80.0)
    usd_cycle = int(gc["usd"])
    gc_lots: list = []
    crypto_trader.apply_horizons(
        gc, gc_lots, 110.0, hot, "range", 2_400_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if int(gc["usd"]) != usd_cycle:
        raise AssertionError("cash_cycle powder stays in usd until DCA")
    if not any(str(row.get("id") or "").startswith("grid-sell") for row in gc_lots):
        raise AssertionError("15 percent float still trades during cash_cycle")
    gl = _book()
    gl["float_usd"] = 50 * crypto_trader.USD_SCALE
    gl["osc_prev"] = _prev(18.0)
    gl_lots: list = []
    crypto_trader.apply_horizons(
        gl, gl_lots, 90.0, cold, "trend_up", 2_500_000_000,
        tf_flow=bull_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in gl_lots):
        raise AssertionError("setup dip buy")
    n_sell0 = sum(1 for row in gl_lots if str(row.get("id") or "").startswith("grid-sell"))
    dump = {
        "1d": {"rsi": 75.0, "close": 80.0, "stoch": 75.0},
        "4h": {"rsi": 75.0, "stoch": 75.0},
        "1h": {"rsi": 70.0, "stoch": 70.0},
        "15m": {"rsi": 50.0, "stoch": 50.0},
        "5m": {"rsi": 50.0, "stoch": 50.0},
    }
    gl["osc_prev"] = _prev(80.0)
    crypto_trader.apply_horizons(
        gl, gl_lots, 80.0, dump, "trend_down",
        2_500_000_000 + int(crypto_trader.DAY_HOLD_SEC) + 60,
        tf_flow=bear_flow, open_rows=[],
    )
    n_sell1 = sum(1 for row in gl_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_sell1 != n_sell0:
        raise AssertionError("must not dump a dip buy at a loss two days later")
    ga = _book()
    ga["float_usd"] = 50 * crypto_trader.USD_SCALE
    ga["grid_last_sell_px"] = 100 * crypto_trader.USD_SCALE
    ga["osc_prev"] = _prev(50.0)
    ga["osc_prev"]["4h"] = {"rsi": 18.0, "stoch": 18.0}
    ga_lots: list = []
    crypto_trader.apply_horizons(
        ga, ga_lots, 110.0, pull, "trend_up", 2_600_000_000,
        tf_flow=bull_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-buy") for row in ga_lots):
        raise AssertionError("must not buy above the last float sell")
    stale = _book()
    stale["float_usd"] = 50 * crypto_trader.USD_SCALE
    stale["grid_last_sell_px"] = 20 * crypto_trader.USD_SCALE
    stale["osc_prev"] = _prev(18.0)
    stale_lots: list = []
    crypto_trader.apply_horizons(
        stale, stale_lots, 90.0, cold, "trend_up", 2_650_000_000,
        tf_flow=bull_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in stale_lots):
        raise AssertionError("stale last_sell must not lock a new market")
    gw = _book()
    gw["float_usd"] = 50 * crypto_trader.USD_SCALE
    gw_lots: list = []
    weak = {
        "1d": {"rsi": 35.0, "close": 90.0},
        "4h": {"rsi": 32.0},
        "1h": {"rsi": 40.0},
        "15m": {"rsi": 50.0},
        "5m": {"rsi": 50.0},
    }
    crypto_trader.apply_horizons(
        gw, gw_lots, 90.0, weak, "range", 2_700_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-buy") for row in gw_lots):
        raise AssertionError("4h 32 is not in the 25 buy band")

    def _stack_row(rsi: float, stack: list[float], extras: bool = False) -> dict:
        row = {
            "rsi": rsi,
            "stoch": stack[1] if len(stack) > 1 else rsi,
            "stoch_stack": list(stack),
        }
        if extras:
            row.update({"mfi": rsi, "cci": rsi, "bb": rsi, "williams": rsi})
        return row

    mid_stack = [50.0, 50.0, 50.0, 50.0]
    spread_stack = [8.0, 22.0, 48.0, 81.0]
    pile_prev = [16.0, 17.0, 18.0, 19.0]
    pile_now = [18.0, 19.0, 20.0, 21.0]
    gspread = _book()
    gspread["float_usd"] = 50 * crypto_trader.USD_SCALE
    gspread["osc_prev"] = {
        tf: _stack_row(18.0, spread_stack) for tf in crypto_trader.TIMEFRAMES
    }
    spread_now = {
        tf: _stack_row(20.0, spread_stack, extras=True)
        for tf in ("1d", "4h", "1h", "15m", "5m")
    }
    spread_now["1d"]["close"] = 90.0
    spread_lots: list = []
    crypto_trader.apply_horizons(
        gspread, spread_lots, 90.0, spread_now, "range", 2_720_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-") for row in spread_lots):
        raise AssertionError("spread 4-stoch is not a supersignal " + str(gspread.get("last")))
    gsuper = _book()
    gsuper["float_usd"] = 50 * crypto_trader.USD_SCALE
    gsuper["osc_prev"] = {
        tf: _stack_row(50.0, mid_stack) for tf in crypto_trader.TIMEFRAMES
    }
    gsuper["osc_prev"]["15m"] = _stack_row(16.0, pile_prev)
    super_now = {
        "1d": dict(_stack_row(50.0, mid_stack), close=90.0),
        "8h": _stack_row(50.0, mid_stack),
        "4h": _stack_row(50.0, mid_stack),
        "1h": _stack_row(22.0, pile_now, extras=True),
        "15m": _stack_row(20.0, pile_now, extras=True),
        "5m": _stack_row(50.0, mid_stack),
        "1m": _stack_row(50.0, mid_stack),
    }
    super_lots: list = []
    crypto_trader.apply_horizons(
        gsuper, super_lots, 90.0, super_now, "range", 2_730_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if not any(str(row.get("id") or "").startswith("grid-buy") for row in super_lots):
        raise AssertionError("4-stoch pile-up plus oscillators must buy " + str(gsuper.get("last")))
    gthin = _book()
    gthin["float_usd"] = 50 * crypto_trader.USD_SCALE
    gthin["osc_prev"] = {
        tf: _stack_row(50.0, mid_stack) for tf in crypto_trader.TIMEFRAMES
    }
    gthin["osc_prev"]["15m"] = _stack_row(16.0, pile_prev)
    thin_now = {
        "1d": dict(_stack_row(50.0, mid_stack), close=90.0),
        "8h": _stack_row(50.0, mid_stack),
        "4h": _stack_row(50.0, mid_stack),
        "1h": _stack_row(50.0, mid_stack),
        "15m": _stack_row(20.0, pile_now),
        "5m": _stack_row(50.0, mid_stack),
        "1m": _stack_row(50.0, mid_stack),
    }
    thin_lots: list = []
    crypto_trader.apply_horizons(
        gthin, thin_lots, 90.0, thin_now, "range", 2_740_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-buy") for row in thin_lots):
        raise AssertionError("15m pile-up without other osc must not print")
    gladd = _book()
    gladd["osc_prev"] = {
        tf: _stack_row(50.0, mid_stack) for tf in crypto_trader.TIMEFRAMES
    }
    gladd["osc_prev"]["15m"] = _stack_row(82.0, [82.0, 81.0, 80.0, 79.0])
    sell_now = {
        "1d": dict(_stack_row(50.0, mid_stack), close=110.0),
        "8h": _stack_row(50.0, mid_stack),
        "4h": _stack_row(50.0, mid_stack),
        "1h": _stack_row(78.0, [80.0, 79.0, 78.0, 77.0], extras=True),
        "15m": _stack_row(78.0, [80.0, 79.0, 78.0, 77.0], extras=True),
        "5m": _stack_row(50.0, mid_stack),
        "1m": _stack_row(50.0, mid_stack),
    }
    ladd_lots: list = []
    t_ladd = 2_750_000_000
    crypto_trader.apply_horizons(
        gladd, ladd_lots, 110.0, sell_now, "range", t_ladd,
        tf_flow=range_flow, open_rows=[],
    )
    n_top = sum(1 for row in ladd_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_top != 1:
        raise AssertionError("first alignment around the top is one clip " + str(n_top))
    run_up = {
        "1d": dict(_stack_row(50.0, mid_stack), close=111.5),
        "8h": _stack_row(50.0, mid_stack),
        "4h": _stack_row(50.0, mid_stack),
        "1h": _stack_row(80.0, [81.0, 80.0, 79.0, 78.0], extras=True),
        "15m": _stack_row(80.0, [81.0, 80.0, 79.0, 78.0], extras=True),
        "5m": _stack_row(50.0, mid_stack),
        "1m": _stack_row(50.0, mid_stack),
    }
    crypto_trader.apply_horizons(
        gladd, ladd_lots, 111.5, run_up, "range", t_ladd + 900,
        tf_flow=range_flow, open_rows=[],
    )
    n_run = sum(1 for row in ladd_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_run != n_top:
        raise AssertionError("still running into the top is not another clip")
    roll = {
        "1d": dict(_stack_row(50.0, mid_stack), close=105.5),
        "8h": _stack_row(50.0, mid_stack),
        "4h": _stack_row(50.0, mid_stack),
        "1h": _stack_row(76.0, [79.0, 78.0, 77.0, 76.0], extras=True),
        "15m": _stack_row(76.0, [79.0, 78.0, 77.0, 76.0], extras=True),
        "5m": _stack_row(50.0, mid_stack),
        "1m": _stack_row(50.0, mid_stack),
    }
    crypto_trader.apply_horizons(
        gladd, ladd_lots, 105.5, roll, "range", t_ladd + 1800,
        tf_flow=range_flow, open_rows=[],
    )
    n_around = sum(1 for row in ladd_lots if str(row.get("id") or "").startswith("grid-sell"))
    if n_around != 2:
        raise AssertionError("rolling around the top must add a second clip " + str(n_around))
    gbot = _book()
    gbot["float_usd"] = 200 * crypto_trader.USD_SCALE
    gbot["osc_prev"] = {
        tf: _stack_row(50.0, mid_stack) for tf in crypto_trader.TIMEFRAMES
    }
    gbot["osc_prev"]["15m"] = _stack_row(16.0, pile_prev)
    bot_lots: list = []
    t_bot = 2_760_000_000
    crypto_trader.apply_horizons(
        gbot, bot_lots, 90.0, super_now, "range", t_bot,
        tf_flow=range_flow, open_rows=[],
    )
    n_bot = sum(1 for row in bot_lots if str(row.get("id") or "").startswith("grid-buy"))
    if n_bot != 1:
        raise AssertionError("first alignment around the bottom is one clip " + str(n_bot))
    lift = {
        "1d": dict(_stack_row(50.0, mid_stack), close=93.7),
        "8h": _stack_row(50.0, mid_stack),
        "4h": _stack_row(50.0, mid_stack),
        "1h": _stack_row(21.0, [19.0, 20.0, 21.0, 22.0], extras=True),
        "15m": _stack_row(21.0, [19.0, 20.0, 21.0, 22.0], extras=True),
        "5m": _stack_row(50.0, mid_stack),
        "1m": _stack_row(50.0, mid_stack),
    }
    crypto_trader.apply_horizons(
        gbot, bot_lots, 93.7, lift, "range", t_bot + 900,
        tf_flow=range_flow, open_rows=[],
    )
    n_lift = sum(1 for row in bot_lots if str(row.get("id") or "").startswith("grid-buy"))
    if n_lift != 2:
        raise AssertionError("bouncing around the bottom must add a second clip " + str(n_lift))
    gp = _book()
    gp["osc_prev"] = _prev(80.0)
    gp_lots: list = []
    crypto_trader.apply_horizons(
        gp, gp_lots, 105.0, _osc(75.0, 105.0), "range", 2_770_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    sold = next((row for row in gp_lots if str(row.get("id") or "").startswith("grid-sell")), None)
    if sold is None:
        raise AssertionError("5 percent lift must sell high")
    usd_net = int(sold.get("usd") or 0)
    profit = int(sold.get("profit_usd") or 0)
    if profit <= 0:
        raise AssertionError("105 vs cost 100 must be profit " + str(sold))
    bank = int(gp.get("banked_usd") or 0)
    rolled = int(gp.get("float_usd") or 0)
    if bank + rolled != usd_net:
        raise AssertionError("profit split leaked " + str(bank) + "+" + str(rolled) + " != " + str(usd_net))
    want_bank = profit * crypto_trader.PROFIT_BANK_BPS // 10_000
    if bank != want_bank:
        raise AssertionError("bank must be 20 percent of the 0.05 not the 1.00 " + str(bank) + " vs " + str(want_bank))
    cost = usd_net - profit
    if rolled <= cost:
        raise AssertionError("the 1.04 must stay in the trade " + str(rolled) + " vs cost " + str(cost))
    glose = _book()
    glose["osc_prev"] = _prev(80.0)
    lose_lots: list = []
    crypto_trader.apply_horizons(
        glose, lose_lots, 95.0, _osc(75.0, 95.0), "range", 2_780_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if int(glose.get("banked_usd") or 0) != 0:
        raise AssertionError("a losing clip must not bank principal")
    g1 = _book()
    g1["osc_prev"] = _prev(50.0)
    g1["osc_prev"]["1m"] = {"rsi": 80.0, "stoch": 80.0}
    g1_lots: list = []
    only_1m = {
        "1d": {"rsi": 50.0, "stoch": 50.0, "close": 110.0},
        "4h": {"rsi": 50.0, "stoch": 50.0},
        "1h": {"rsi": 50.0, "stoch": 50.0},
        "15m": {"rsi": 50.0, "stoch": 50.0},
        "5m": {"rsi": 50.0, "stoch": 50.0},
        "1m": {"rsi": 74.0, "stoch": 74.0},
    }
    crypto_trader.apply_horizons(
        g1, g1_lots, 110.0, only_1m, "range", 2_800_000_000,
        tf_flow=range_flow, open_rows=[],
    )
    if any(str(row.get("id") or "").startswith("grid-") for row in g1_lots):
        raise AssertionError("1m must not print unless 15m is in the same zone")
    gn = _book()
    gn["cash_cycle"] = True
    gn["bag_armed"] = False
    gn["sol"] = crypto_trader.MIN_SOL_LOT * 2
    gn["peak_tokens"] = 60 * crypto_trader.SOL_SCALE
    gn["osc_prev"] = _prev(80.0)
    gn_lots: list = []
    for i in range(8):
        gn["osc_prev"] = _prev(80.0)
        gn["zone_armed"] = {}
        crypto_trader.apply_horizons(
            gn, gn_lots, 110.0, hot, "range", 2_900_000_000 + i * 3600,
            tf_flow=range_flow, open_rows=[],
        )
    if int(gn["sol"]) < 0:
        raise AssertionError("float must not go negative SOL " + str(gn["sol"]))
    if "ts + 7 * 86400" in src:
        raise AssertionError("do not fit a 7-day lock to one backtest")
    flow_chart = flow_bt.get("chart") or {}
    if len(flow_chart.get("closes") or []) < 8:
        raise AssertionError("flow chart missing")
    if len(flow_chart.get("times") or []) != len(flow_chart.get("closes") or []):
        raise AssertionError("flow chart times")

    lab_src = (PROJECT / "backend" / "crypto_lab.py").read_text(encoding="utf-8")
    if "execute_contracts" not in (PROJECT / "backend" / "crypto_trader.py").read_text(
        encoding="utf-8"
    ):
        raise AssertionError("lab CPMM fills not wired")
    if "taskset" in lab_src:
        raise AssertionError("validator still pinned to a core slice")
    if 'RAYON_NUM_THREADS"] = "2"' in lab_src:
        raise AssertionError("validator still two rayon threads")
    print("CRYPTO_TRADER_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
