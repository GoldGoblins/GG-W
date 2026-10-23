"""Hold SOL. Harvest 80% of THIS cycle's profit at a high. Buy it back at the next low.

1.00 → 1.10: take 0.08, leave 1.02 in the bag (principal + 20% of the gain).
Paper only. MAINNET not used.
"""
from __future__ import annotations

from typing import Any

from backend import crypto_backtest

from backend.crypto_indicators import bb_percent, cci_osc, mfi, rsi, stoch_kd, williams_osc
from backend.crypto_trader import (
    FEE_BPS,
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
    _other_agree,
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


# 80% of the cycle gain is sold. 20% of the gain stays in the bag with principal.
HARVEST_BPS = 8000
OFF_PEAK_BPS = 200
# Paper stand-in for base + priority. Skip the swap if fees > 10% of notional.
NETWORK_FEE_LAMPORTS = 1_000_000
MAX_FEE_BPS = 1000


def _swap_fee_usd(notional_usd: int, px: int) -> int:
    if notional_usd <= 0 or px <= 0:
        return 0
    dex = notional_usd * FEE_BPS // 10_000
    net = NETWORK_FEE_LAMPORTS * px // SOL_SCALE
    return dex + net


def _fee_ok(notional_usd: int, px: int) -> bool:
    """Network+swap fee must stay ≤ 10% of the clip."""
    if notional_usd <= 0 or px <= 0:
        return False
    fee = _swap_fee_usd(notional_usd, px)
    return fee * 10_000 <= notional_usd * MAX_FEE_BPS


def _cycle_harvest_sol(hold: int, px: int, cycle_px: int) -> tuple[int, int]:
    """SOL to sell = 80% of this swing's gain. Swing is capped at 1.00→1.10."""
    if hold <= 0 or px <= 0 or cycle_px <= 0 or px <= cycle_px:
        return 0, 0
    if px * 10_000 < cycle_px * (10_000 + MIN_COVER_BPS):
        return 0, 0
    hi = px
    cap = cycle_px + cycle_px // 10
    if hi > cap:
        hi = cap
    profit = hold * (hi - cycle_px) // SOL_SCALE
    take = profit * HARVEST_BPS // 10_000
    slice_sol = take * SOL_SCALE // px
    slice_sol = min(slice_sol, hold - MIN_SOL_LOT)
    if slice_sol < MIN_SOL_LOT or take < USD_SCALE // 20:
        return 0, 0
    notional = slice_sol * px // SOL_SCALE
    if not _fee_ok(notional, px):
        return 0, 0
    return slice_sol, take


def _osc_at(
    i: int,
    rsi_s: list[float | None],
    stacks: list[list[float | None]],
    extra: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    stack = [series[i] if i < len(series) else None for series in stacks]
    stoch = stack[1] if len(stack) > 1 else (stack[0] if stack else None)
    row = {
        "rsi": rsi_s[i] if i < len(rsi_s) else None,
        "stoch": stoch,
        "stoch_stack": stack,
    }
    for key, series in (extra or {}).items():
        row[key] = series[i] if i < len(series) else None
    return row


def run_backtest(frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = _walk_primary(frames)
    src = frames[primary]
    highs = list(src["highs"])
    lows = list(src["lows"])
    closes = list(src["closes"])
    times = [int(x) for x in (src.get("times") or [])]
    n = min(len(highs), len(lows), len(closes), len(times) or len(closes))
    if n < 96:
        raise RuntimeError("CRYPTO_HISTORY")
    highs, lows, closes = highs[:n], lows[:n], closes[:n]
    times = times[:n] if len(times) >= n else list(range(n))
    vols = list(src.get("volumes") or [1.0] * n)
    if len(vols) < n:
        vols.extend([1.0] * (n - len(vols)))
    vols = vols[:n]
    rsi_s = rsi(closes, 14)
    stacks: list[list[float | None]] = []
    for k_len, k_sm, d_sm, _vol in STOCH_STACK:
        sk, _sd = stoch_kd(highs, lows, closes, k_len, k_sm, d_sm)
        stacks.append(sk)
    indicator_extra = {
        "mfi": mfi(highs, lows, closes, vols, 14),
        "cci": cci_osc(highs, lows, closes, 20),
        "bb": bb_percent(closes, 14, 2.0),
        "williams": williams_osc(highs, lows, closes, 14),
    }
    begin = crypto_backtest.start_index(src)
    resume = crypto_backtest.restored("dca")
    first_px = _price_atoms(closes[begin])
    start_sol = START_USD * SOL_SCALE // first_px if first_px else START_SOL
    state = default_state()
    state["armed"] = True
    state["seeded"] = True
    state["seed_style"] = "long"
    state["book"] = "dca"
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
    # 1.00 is the last low, not 2020 seed. No harvest until a low is marked.
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
        osc = _osc_at(i, rsi_s, stacks, indicator_extra)
        prev = _osc_at(i - 1, rsi_s, stacks, indicator_extra)
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
            and _stoch_cluster(osc, True)[1]
            and _stoch_turn(osc, prev, True)
            and _other_agree(osc, True) >= 2
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
                            "id": "dca-sell-" + str(ts),
                            "ts": ts,
                            "side": "sell",
                            "horizon": "spot",
                            "sol": slice_sol,
                            "usd": usd_net,
                            "price": px,
                            "profit_usd": take,
                            "venue": "dca",
                            "closed": True,
                        }
                    )
                    sells += 1
                    prev_count += 1
                    state["trades_today"] = prev_count
                    sell_armed = True
                    _note_fill(tape, lots[-1])
                continue
        in_buy = (
            _stoch_cluster(osc, False)[1]
            and _other_agree(osc, False) >= 2
        )
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
                "id": "dca-buy-" + str(ts),
                "ts": ts,
                "side": "buy",
                "horizon": "spot",
                "sol": sol_got,
                "usd": powder,
                "price": px,
                "extra_sol": extra,
                "venue": "dca",
                "closed": True,
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
        "book": "dca",
        "primary": primary,
        "banked_sol": format_units(banked, 9),
        "float_sol": format_units(held, 9),
        "tokens": format_units(banked + held, 9),
        "usd": format_units(usd, 6),
        "start_sol": format_units(start_sol, 9),
        "months": tape["months"],
        "weeks": tape["weeks"],
        "note": "Sell high, buy back more SOL or wait. 80% of cycle profit. Fees ≤ 10% of clip.",
        "chart": _backtest_chart(
            frames, lots, closes, times, primary, equity=tape["equity"]
        ),
    }
    report.update(stats)
    report["accounting"] = tape.get("accounting", [])
    crypto_backtest.checkpoint(report, "dca", {"state": state, "sell_armed": sell_armed, "buy_armed": buy_armed, "cycle_px": cycle_px, "peak_px": peak_px, "sold_sol": sold_sol, "prev_day": prev_day, "prev_count": prev_count, "recent_lots": lots[-8:]}, lots[event_start:], banked + held, usd)
    save_backtest(report)
    return report
