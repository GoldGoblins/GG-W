"""werkkrew StochRSITEMA on GG klines.

Buy: stoch K and D cross up through the lower band, K>D, RSI above band.
Sell: close below TEMA, or ROI/stoploss from the published hyperopt block.
One bag in or out. Same start SOL as the house book. Paper only.
"""
from __future__ import annotations

from typing import Any

from backend import crypto_backtest

from backend.crypto_indicators import ema, rsi, stoch_kd
from backend.crypto_trader import (
    FEE_BPS,
    SOL_SCALE,
    START_SOL,
    START_USD,
    USD_SCALE,
    _advance_tape,
    _apply_fee,
    _backtest_chart,
    _close_tape,
    _fresh_tape,
    _note_fill,
    _price_atoms,
    _trade_stats,
    _utc_day,
    _walk_primary,
    default_state,
    format_units,
    save_backtest,
)

# Published hyperopt (PeetCrypto/freqtrade-stuff StochRSITEMA.py).
RSI_PERIOD = 15
RSI_BAND = 36.0
STOCH_BAND = 48.0
STOCH_K = 14
STOCH_SMOOTH = 3
TEMA_PERIOD = 5
STOPLOSS = -0.02205
SELL_PROFIT_OFFSET = 0.01
ROI = ((0, 0.19503), (13, 0.09149), (36, 0.02891), (64, 0.0))


def _tema(closes: list[float], period: int) -> list[float | None]:
    e1 = ema(closes, period)
    filled = [closes[i] if e1[i] is None else float(e1[i]) for i in range(len(closes))]
    e2 = ema(filled, period)
    filled2 = [filled[i] if e2[i] is None else float(e2[i]) for i in range(len(closes))]
    e3 = ema(filled2, period)
    out: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        a, b, c = e1[i], e2[i], e3[i]
        if a is None or b is None or c is None:
            continue
        out[i] = 3.0 * float(a) - 3.0 * float(b) + float(c)
    return out


def _crossed_up(prev: float | None, now: float | None, level: float) -> bool:
    if prev is None or now is None:
        return False
    return float(prev) <= level < float(now)


def _roi_need(hold_min: int) -> float:
    need = ROI[0][1]
    for minutes, frac in ROI:
        if hold_min >= minutes:
            need = frac
    return need


def run_backtest(frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = _walk_primary(frames)
    src = frames[primary]
    highs = list(src["highs"])
    lows = list(src["lows"])
    closes = list(src["closes"])
    volumes = list(src.get("volumes") or [1.0] * len(closes))
    times = [int(x) for x in (src.get("times") or [])]
    n = min(len(highs), len(lows), len(closes), len(times) or len(closes))
    if n < 96:
        raise RuntimeError("CRYPTO_HISTORY")
    highs, lows, closes, volumes = highs[:n], lows[:n], closes[:n], volumes[:n]
    if len(times) < n:
        times = list(range(n))
    else:
        times = times[:n]
    rsi_s = rsi(closes, RSI_PERIOD)
    k_s, d_s = stoch_kd(highs, lows, closes, STOCH_K, STOCH_SMOOTH, STOCH_SMOOTH)
    tema_s = _tema(closes, TEMA_PERIOD)
    begin = crypto_backtest.start_index(src)
    resume = crypto_backtest.restored("stoch_rsi")
    first_px = _price_atoms(closes[begin])
    start_sol = START_USD * SOL_SCALE // first_px if first_px else START_SOL
    state = default_state()
    state["armed"] = True
    state["seeded"] = True
    state["seed_style"] = "long"
    state["book"] = "stoch_rsi"
    state["sol"] = _apply_fee(start_sol)
    state["usd"] = 0
    state["start_sol"] = start_sol
    state["cost_px"] = first_px
    state["grid_px"] = first_px
    lots: list[dict[str, Any]] = []
    in_pos = True
    entry_px = first_px
    entry_ts = int(times[begin])
    entry_cost_usd = int(START_USD)
    tape = _fresh_tape()
    buys = 0
    sells = 0
    day_hist: list[int] = []
    prev_day = ""
    prev_count = 0
    if resume:
        state = resume["state"]
        start_sol = int(state["start_sol"])
        in_pos = resume["in_pos"]
        entry_px = resume["entry_px"]
        entry_ts = resume["entry_ts"]
        entry_cost_usd = resume["entry_cost_usd"]
        prev_day = resume["prev_day"]
        prev_count = resume["prev_count"]
    event_start = len(lots)
    start = n - 1 if resume else begin
    for i in range(start, n):
        ts = int(times[i])
        day_now = _utc_day(ts)
        if prev_day and day_now != prev_day:
            day_hist.append(prev_count)
            prev_count = 0
            state["trades_today"] = 0
        prev_day = day_now
        px = _price_atoms(closes[i])
        if px <= 0:
            continue
        _advance_tape(tape, ts, state, closes[i])
        now_k, prev_k = k_s[i], k_s[i - 1]
        now_d, prev_d = d_s[i], d_s[i - 1]
        now_r = rsi_s[i]
        now_t = tema_s[i]
        vol = float(volumes[i] if i < len(volumes) else 1.0)
        buy = (
            vol > 0
            and now_r is not None
            and float(now_r) > RSI_BAND
            and _crossed_up(prev_d, now_d, STOCH_BAND)
            and _crossed_up(prev_k, now_k, STOCH_BAND)
            and now_k is not None
            and now_d is not None
            and float(now_k) > float(now_d)
        )
        if (not in_pos) and buy:
            usd_in = int(state.get("usd") or 0) + int(state.get("float_usd") or 0)
            if usd_in >= USD_SCALE // 20:
                sol_got = _apply_fee(usd_in) * SOL_SCALE // px
                if sol_got > 0:
                    state["usd"] = 0
                    state["float_usd"] = 0
                    state["sol"] = int(state.get("sol") or 0) + sol_got
                    state["cost_px"] = px
                    in_pos = True
                    entry_px = px
                    entry_ts = ts
                    entry_cost_usd = usd_in
                    lots.append(
                        {
                            "id": "stoch-buy-" + str(ts),
                            "ts": ts,
                            "side": "buy",
                            "horizon": "spot",
                            "sol": sol_got,
                            "usd": usd_in,
                            "price": px,
                            "venue": "stoch_rsi",
                            "closed": True,
                        }
                    )
                    buys += 1
                    prev_count += 1
                    state["trades_today"] = prev_count
                    _note_fill(tape, lots[-1])
            continue
        if not in_pos:
            continue
        hold = int(state.get("sol") or 0)
        if hold <= 0 or entry_px <= 0:
            continue
        frac = (px - entry_px) / float(entry_px)
        net_proceeds = _apply_fee(hold * px // SOL_SCALE)
        net_frac = (net_proceeds - entry_cost_usd) / float(max(1, entry_cost_usd))
        hold_min = max(0, (ts - entry_ts) // 60)
        roi = net_frac >= _roi_need(hold_min)
        stop = frac <= STOPLOSS
        tema_hit = now_t is not None and closes[i] < float(now_t) and vol > 0
        want = stop or roi or tema_hit
        if tema_hit and (not stop) and (not roi) and net_frac < SELL_PROFIT_OFFSET:
            want = False
        if not want:
            continue
        usd_net = _apply_fee(hold * px // SOL_SCALE)
        if usd_net <= 0:
            continue
        cost = entry_cost_usd
        profit = usd_net - cost
        state["sol"] = 0
        state["float_usd"] = usd_net
        in_pos = False
        lots.append(
            {
                "id": "stoch-sell-" + str(ts),
                "ts": ts,
                "side": "sell",
                "horizon": "spot",
                "sol": hold,
                "usd": usd_net,
                "price": px,
                "profit_usd": profit,
                "venue": "stoch_rsi",
                "closed": True,
            }
        )
        sells += 1
        prev_count += 1
        state["trades_today"] = prev_count
        _note_fill(tape, lots[-1])
    if prev_day:
        day_hist.append(prev_count)
    last_px = closes[n - 1]
    last_ts = int(times[n - 1])
    _close_tape(tape, state, last_px, last_ts)
    banked = int(state.get("banked_sol") or 0)
    held = int(state.get("sol") or 0)
    usd = int(state.get("usd") or 0) + int(state.get("float_usd") or 0)
    stats = _trade_stats(
        lots,
        banked,
        usd,
        day_hist,
        sol_held=held,
        last_close=last_px,
        start_sol=start_sol,
    )
    report: dict[str, Any] = {
        "bars": n,
        "fills": buys + sells,
        "buys": buys,
        "sells": sells,
        "book": "stoch_rsi",
        "primary": primary,
        "banked_sol": format_units(banked, 9),
        "float_sol": format_units(held, 9),
        "tokens": format_units(banked + held, 9),
        "usd": format_units(usd, 6),
        "start_sol": format_units(start_sol, 9),
        "months": tape["months"],
        "weeks": tape["weeks"],
        "note": "werkkrew StochRSITEMA on the GG tape. Not a Freqtrade process.",
        "chart": _backtest_chart(
            frames, lots, closes, times, primary, equity=tape["equity"]
        ),
    }
    report.update(stats)
    report["accounting"] = tape.get("accounting", [])
    crypto_backtest.checkpoint(report, "stoch_rsi", {"state": state, "in_pos": in_pos, "entry_px": entry_px, "entry_ts": entry_ts, "entry_cost_usd": entry_cost_usd, "prev_day": prev_day, "prev_count": prev_count}, lots[event_start:], banked + held, usd)
    save_backtest(report)
    return report
