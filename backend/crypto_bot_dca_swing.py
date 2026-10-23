"""DCA bag + swing timing. Many 0–100 osc vote; the bag never dumps principal.

Hold SOL. Harvest 80% of THIS cycle's profit at a high. Buy the powder back
at the next low only if it returns more tokens. Timing is a quorum of
mean-reversion osc plus stoch K/D, TEMA, MACD — not all-in/all-out.
Paper only. MAINNET not used.
"""
from __future__ import annotations

from typing import Any

from backend import crypto_backtest

from backend.crypto_bot_dca import OFF_PEAK_BPS, _cycle_harvest_sol, _fee_ok
from backend.crypto_bot_stoch_rsi import TEMA_PERIOD, _crossed_up, _tema
from backend.crypto_indicators import (
    aroon_osc,
    bb_percent,
    candle_osc,
    cci_osc,
    cmf_osc,
    cmo_osc,
    donchian_percent,
    ema_ribbon_osc,
    heikin_osc,
    ichimoku_osc,
    keltner_percent,
    macd,
    mfi,
    rsi,
    sar_osc,
    schaff_trend,
    stoch_kd,
    stoch_rsi,
    supertrend_osc,
    ultimate_osc,
    williams_osc,
)
from backend.crypto_strategy004 import adx
from backend.crypto_trader import (
    BAND_BUY,
    BAND_SELL,
    MIN_COVER_BPS,
    MIN_SOL_LOT,
    SOL_SCALE,
    START_SOL,
    START_USD,
    STOCH_STACK,
    USD_SCALE,
    _advance_tape,
    _apply_fee,
    _backtest_chart,
    _close_tape,
    _fresh_tape,
    _in_zone_val,
    _note_fill,
    _price_atoms,
    _stoch_cluster,
    _stoch_turn,
    _trade_stats,
    _utc_day,
    _walk_primary,
    default_state,
    format_units,
    save_backtest,
)

# Mean-reversion pack. Each is 0–100. Buy ≤25, sell ≥70.
VOTE_KEYS = (
    "rsi",
    "rsi2",
    "stoch_rsi",
    "mfi",
    "cci",
    "williams",
    "bb",
    "uo",
    "cmo",
    "cmf",
    "keltner",
    "donchian",
)
# Trend pack. Against-zone majority blocks the print (no harvest into a dump).
TREND_KEYS = (
    "aroon",
    "stc",
    "ichimoku",
    "supertrend",
    "heikin",
    "sar",
    "ribbon",
    "candle",
)
VOTE_NEED = 5
# Chop. Harvesting 80 bps of noise pays the fee cap.
ADX_MIN = 18.0


def _crossed_down(prev: float | None, now: float | None, level: float) -> bool:
    if prev is None or now is None:
        return False
    return float(prev) >= level > float(now)


def _at(series: list[Any], i: int) -> Any:
    if i < 0 or i >= len(series):
        return None
    return series[i]


def _bundle(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> dict[str, Any]:
    stacks: list[list[float | None]] = []
    stack_d: list[list[float | None]] = []
    for k_len, k_sm, d_sm, _vol in STOCH_STACK:
        sk, sd = stoch_kd(highs, lows, closes, k_len, k_sm, d_sm)
        stacks.append(sk)
        stack_d.append(sd)
    _line, _sig, hist = macd(closes)
    return {
        "rsi": rsi(closes, 14),
        "rsi2": rsi(closes, 2),
        "stacks": stacks,
        "stack_d": stack_d,
        "stoch_rsi": stoch_rsi(closes, 14, 14),
        "mfi": mfi(highs, lows, closes, volumes, 14),
        "cci": cci_osc(highs, lows, closes, 20),
        "williams": williams_osc(highs, lows, closes, 14),
        "bb": bb_percent(closes, 14, 2.0),
        "uo": ultimate_osc(highs, lows, closes),
        "cmo": cmo_osc(closes, 14),
        "cmf": cmf_osc(highs, lows, closes, volumes, 20),
        "keltner": keltner_percent(highs, lows, closes),
        "donchian": donchian_percent(highs, lows, closes),
        "aroon": aroon_osc(highs, lows, 25),
        "stc": schaff_trend(closes),
        "ichimoku": ichimoku_osc(highs, lows, closes),
        "supertrend": supertrend_osc(highs, lows, closes),
        "heikin": heikin_osc(highs, lows, closes),
        "sar": sar_osc(highs, lows, closes),
        "ribbon": ema_ribbon_osc(closes),
        "candle": candle_osc(highs, lows, closes),
        "macd_hist": hist,
        "tema": _tema(closes, TEMA_PERIOD),
        "adx": adx(highs, lows, closes, 14),
        "close": closes,
    }


def _osc_at(bundle: dict[str, Any], i: int) -> dict[str, Any]:
    stacks = bundle["stacks"]
    stack = [_at(series, i) for series in stacks]
    d_stack = bundle["stack_d"]
    stoch_k = stack[1] if len(stack) > 1 else (stack[0] if stack else None)
    stoch_d = _at(d_stack[1], i) if len(d_stack) > 1 else None
    out: dict[str, Any] = {
        "rsi": _at(bundle["rsi"], i),
        "stoch": stoch_k,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "stoch_stack": stack,
        "macd_hist": _at(bundle["macd_hist"], i),
        "tema": _at(bundle["tema"], i),
        "adx": _at(bundle["adx"], i),
        "close": _at(bundle["close"], i),
    }
    for key in VOTE_KEYS + TREND_KEYS:
        if key == "rsi":
            continue
        out[key] = _at(bundle[key], i)
    return out


def _zone_hits(osc: dict[str, Any], keys: tuple[str, ...], sell: bool) -> tuple[int, int]:
    hits = 0
    present = 0
    for key in keys:
        value = osc.get(key)
        if value is None:
            continue
        present += 1
        if _in_zone_val(value, sell):
            hits += 1
    return hits, present


def quorum(osc: dict[str, Any], sell: bool, need: int = VOTE_NEED) -> bool:
    """Enough mean-reversion osc in the 25/70 band. Missing prints do not vote."""
    hits, present = _zone_hits(osc, VOTE_KEYS, sell)
    if present <= 0:
        return False
    want = min(need, max(3, present // 2))
    return hits >= want and hits > (present - hits)


def trend_ok(osc: dict[str, Any], sell: bool) -> bool:
    """Block harvest into a dump / buy into a blow-off when the trend pack disagrees."""
    hits, present = _zone_hits(osc, TREND_KEYS, not sell)
    if present < 3:
        return True
    return hits * 2 <= present


def _kd_cross(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    k, d = osc.get("stoch_k"), osc.get("stoch_d")
    pk, pd = prev.get("stoch_k"), prev.get("stoch_d")
    if k is None or d is None:
        return False
    if sell:
        return (
            _crossed_down(pd, d, BAND_SELL)
            and _crossed_down(pk, k, BAND_SELL)
            and float(k) < float(d)
        )
    return (
        _crossed_up(pd, d, BAND_BUY)
        and _crossed_up(pk, k, BAND_BUY)
        and float(k) > float(d)
    )


def _tema_flip(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    now_t, prev_t = osc.get("tema"), prev.get("tema")
    close, prev_close = osc.get("close"), prev.get("close")
    if now_t is None or prev_t is None or close is None or prev_close is None:
        return False
    if sell:
        return float(prev_close) >= float(prev_t) and float(close) < float(now_t)
    return float(prev_close) <= float(prev_t) and float(close) > float(now_t)


def _macd_turn(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    now_h, prev_h = osc.get("macd_hist"), prev.get("macd_hist")
    if now_h is None or prev_h is None:
        return False
    if sell:
        return float(now_h) < float(prev_h)
    return float(now_h) > float(prev_h)


def timing(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    """DCA stoch pile-up turning, or swing K/D cross, or TEMA flip with RSI in band."""
    cluster_turn = _stoch_cluster(osc, sell)[1] and _stoch_turn(osc, prev, sell)
    if cluster_turn:
        return True
    if _kd_cross(osc, prev, sell):
        return True
    if _tema_flip(osc, prev, sell) and _in_zone_val(osc.get("rsi"), sell):
        return True
    if _macd_turn(osc, prev, sell) and _stoch_cluster(osc, sell)[1]:
        return True
    return False


def _adx_ok(osc: dict[str, Any], sell: bool) -> bool:
    if not sell:
        return True
    value = osc.get("adx")
    if value is None:
        return True
    return float(value) >= ADX_MIN


def want_print(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    return (
        timing(osc, prev, sell)
        and quorum(osc, sell)
        and trend_ok(osc, sell)
        and _adx_ok(osc, sell)
    )


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
    highs, lows, closes = highs[:n], lows[:n], closes[:n]
    if len(volumes) < n:
        volumes = (volumes + [1.0] * n)[:n]
    else:
        volumes = volumes[:n]
    times = times[:n] if len(times) >= n else list(range(n))
    bundle = _bundle(highs, lows, closes, volumes)
    begin = crypto_backtest.start_index(src)
    resume = crypto_backtest.restored("dca_swing")
    first_px = _price_atoms(closes[begin])
    start_sol = START_USD * SOL_SCALE // first_px if first_px else START_SOL
    state = default_state()
    state["armed"] = True
    state["seeded"] = True
    state["seed_style"] = "long"
    state["book"] = "dca_swing"
    state["sol"] = _apply_fee(start_sol)
    state["usd"] = 0
    state["float_usd"] = 0
    state["start_sol"] = start_sol
    state["cost_px"] = first_px
    lots: list[dict[str, Any]] = []
    tape = _fresh_tape()
    buys = 0
    sells = 0
    day_hist: list[int] = []
    prev_day = ""
    prev_count = 0
    sell_armed = False
    buy_armed = False
    cycle_px = 0
    peak_px = 0
    sold_sol = 0
    if resume:
        state = resume["state"]
        start_sol = int(state["start_sol"])
        sell_armed = resume["sell_armed"]
        buy_armed = resume["buy_armed"]
        cycle_px = resume["cycle_px"]
        peak_px = resume["peak_px"]
        sold_sol = resume["sold_sol"]
        prev_day = resume["prev_day"]
        prev_count = resume["prev_count"]
        lots = list(resume.get("recent_lots") or [])
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
        osc = _osc_at(bundle, i)
        prev = _osc_at(bundle, i - 1)
        rsi_now = osc.get("rsi")
        if rsi_now is not None and float(rsi_now) < 50.0:
            sell_armed = False
        if rsi_now is not None and float(rsi_now) > 50.0:
            buy_armed = False
        hold = int(state.get("sol") or 0)
        cost_px = int(state.get("cost_px") or 0)
        if px > peak_px:
            peak_px = px
        near_high = peak_px <= 0 or px * 10_000 >= peak_px * (10_000 - OFF_PEAK_BPS)
        harvest = (
            (not sell_armed)
            and sold_sol == 0
            and hold > MIN_SOL_LOT
            and cycle_px > 0
            and near_high
            and want_print(osc, prev, True)
        )
        if harvest:
            slice_sol, take = _cycle_harvest_sol(hold, px, cycle_px)
            if slice_sol > 0:
                usd_net = _apply_fee(slice_sol * px // SOL_SCALE)
                if usd_net > 0:
                    state["sol"] = hold - slice_sol
                    state["float_usd"] = int(state.get("float_usd") or 0) + usd_net
                    cycle_px = px
                    sold_sol += slice_sol
                    lots.append(
                        {
                            "id": "dca-swing-sell-" + str(ts),
                            "ts": ts,
                            "side": "sell",
                            "horizon": "spot",
                            "sol": slice_sol,
                            "usd": usd_net,
                            "price": px,
                            "profit_usd": take,
                            "venue": "dca_swing",
                            "closed": True,
                            "votes": _zone_hits(osc, VOTE_KEYS, True)[0],
                        }
                    )
                    sells += 1
                    prev_count += 1
                    state["trades_today"] = prev_count
                    sell_armed = True
                    _note_fill(tape, lots[-1])
                continue
        in_buy = (not buy_armed) and want_print(osc, prev, False)
        if not in_buy:
            continue
        if cycle_px == 0 or px < cycle_px:
            cycle_px = px
            peak_px = px
        powder = int(state.get("float_usd") or 0)
        if powder < USD_SCALE // 20:
            continue
        last_sell = 0
        if lots:
            for row in reversed(lots):
                if row.get("side") == "sell":
                    last_sell = int(row.get("price") or 0)
                    break
        if last_sell and px * 10_000 > last_sell * (10_000 - MIN_COVER_BPS):
            continue
        if not _fee_ok(powder, px):
            continue
        sol_got = _apply_fee(powder) * SOL_SCALE // px
        if sol_got <= 0:
            continue
        if sold_sol > 0 and sol_got <= sold_sol:
            continue
        prev_sol = int(state.get("sol") or 0)
        state["float_usd"] = 0
        state["sol"] = prev_sol + sol_got
        new_sol = prev_sol + sol_got
        extra = sol_got - sold_sol if sold_sol > 0 else 0
        sold_sol = 0
        if new_sol > 0:
            state["cost_px"] = (prev_sol * cost_px + powder * SOL_SCALE) // new_sol
            cycle_px = px
            peak_px = px
        lots.append(
            {
                "id": "dca-swing-buy-" + str(ts),
                "ts": ts,
                "side": "buy",
                "horizon": "spot",
                "sol": sol_got,
                "usd": powder,
                "price": px,
                "extra_sol": extra,
                "venue": "dca_swing",
                "closed": True,
                "votes": _zone_hits(osc, VOTE_KEYS, False)[0],
            }
        )
        buys += 1
        prev_count += 1
        state["trades_today"] = prev_count
        buy_armed = True
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
        "book": "dca_swing",
        "primary": primary,
        "banked_sol": format_units(banked, 9),
        "float_sol": format_units(held, 9),
        "tokens": format_units(banked + held, 9),
        "usd": format_units(usd, 6),
        "start_sol": format_units(start_sol, 9),
        "months": tape["months"],
        "weeks": tape["weeks"],
        "note": (
            "DCA harvest 80% of cycle profit. Swing timing: stoch K/D, TEMA, MACD "
            "+ 12 mean-reversion osc + 8 trend osc. Buy back more SOL or wait."
        ),
        "chart": _backtest_chart(
            frames, lots, closes, times, primary, equity=tape["equity"]
        ),
    }
    report.update(stats)
    report["accounting"] = tape.get("accounting", [])
    crypto_backtest.checkpoint(report, "dca_swing", {"state": state, "sell_armed": sell_armed, "buy_armed": buy_armed, "cycle_px": cycle_px, "peak_px": peak_px, "sold_sol": sold_sol, "prev_day": prev_day, "prev_count": prev_count, "recent_lots": lots[-8:]}, lots[event_start:], banked + held, usd)
    save_backtest(report)
    return report
