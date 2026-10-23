"""Composed paper book: working GG pieces, one kill switch, no new brain.

Ingredients that already run in this desktop:

* GG swing law — SOL is home; calculated degen buy ≤38 / sell ≥70
* vol regime — GARCH(1,1) + HMM sizes the clip; high vol shrinks, it does not zero
* DESK Front Man — hard veto only: crowd spike, no volume, day cap, invalidation
* thin tape — smaller clip, not a skip
* HYBRID barriers — stop / take / trail / time on the tactical clip
* fee hold — a time exit inside the round-trip fee band stays open
* CORE_KEEP — half the SOL bag is not for the clip

This module never places venue orders and never arms mainnet.
"""

from __future__ import annotations

from typing import Any

from backend import crypto_desk
from backend import crypto_trader
from backend import crypto_vol
from backend import crypto_backtest
from backend.crypto_hybrid import HybridConfig, PaperPositionExecutor
from backend.crypto_indicators import rsi as rsi_series
from backend.crypto_trader import (
    FEE_BPS,
    MAX_TRADES_DAY,
    SOL_SCALE,
    START_SOL,
    _price_atoms,
    _trade_stats,
    _walk_primary,
)


SCHEMA = "gg.crypto.optimal-book.v1"
WARMUP = 80
CORE_KEEP = 0.50
CLIP_FRACTION = 0.35
DEGEN_BUY = 38.0
THIN_SIZE = 0.35
MAX_BARS = 4000
# Two DEX fees plus a small slip. A clock exit inside this band only pays the venue.
FEE_HOLD_BPS = 2 * FEE_BPS + 10
MAINNET = "NOT_ARMED"
HARD_VETO = frozenset({"CROWD_SPIKE", "NO_VOLUME", "TRADE_CAP"})


def live_gate(
    closes: list[float],
    volumes: list[float],
    *,
    in_position: bool,
    trades_today: int = 0,
    entry_price: float = 0.0,
) -> dict[str, Any]:
    """Front Man + vol size for the live tick. Does not call a model."""
    n = min(len(closes), len(volumes) if volumes else len(closes))
    if n < crypto_desk.WARMUP + 8:
        return {
            "allow_buy": False,
            "allow_sell": False,
            "size_scale": 0.0,
            "reasons": ["WARMUP"],
            "front_man": {"light": "RED", "reasons": ["WARMUP"], "in_code": True},
            "vol": {},
            "mode": "PAPER_ONLY",
            "mainnet": MAINNET,
        }
    index = n - 1
    padded_vol = list(volumes[:n]) if volumes else [0.0] * n
    if len(padded_vol) < n:
        padded_vol.extend([0.0] * (n - len(padded_vol)))
    seat_456 = crypto_desk._seat_456(closes[:n], padded_vol, index)
    seat_067 = crypto_desk._seat_067(closes[:n], padded_vol, index)
    seat_218 = crypto_desk._seat_218(closes[:n], index)
    seat_240 = crypto_desk._seat_240(closes[:n], index, entry_price if in_position else 0.0)
    vol_z = crypto_desk._zscore(padded_vol[: index + 1], 24)
    thin = any(value > 0 for value in padded_vol) and vol_z <= crypto_desk.THIN_VOLUME_Z
    man = crypto_desk.front_man(
        seat_456,
        seat_067,
        seat_218,
        seat_240,
        has_volume=any(value > 0 for value in padded_vol),
        trades_today=int(trades_today),
        in_position=bool(in_position),
        thin=bool(thin),
    )
    vol = crypto_vol.snapshot(closes[:n])
    scale = float(vol.get("size_scale") or 0.0)
    if scale <= 0:
        scale = 0.75
    if thin:
        scale *= THIN_SIZE
    rsi_last = None
    try:
        series = rsi_series(closes[:n], 14)
        rsi_last = series[-1] if series else None
    except (TypeError, ValueError):
        rsi_last = None
    buy_band = rsi_last is not None and rsi_last <= DEGEN_BUY
    sell_band = crypto_trader.in_sell_band(rsi_last)
    hard = set(man.get("reasons") or []) & HARD_VETO
    chased = (
        str(seat_067.get("vote") or "") == "SPIKE"
        and len(closes) > 1
        and closes[-1] > closes[-2]
    )
    if not chased:
        hard.discard("CROWD_SPIKE")
    setup = buy_band or str(seat_456.get("vote") or "") == "ATTRACTIVE"
    allow_buy = (
        not hard
        and setup
        and int(trades_today) < MAX_TRADES_DAY
    )
    allow_sell = bool(in_position) and (
        sell_band or "INVALIDATION" in list(man.get("reasons") or [])
    )
    return {
        "allow_buy": allow_buy,
        "allow_sell": allow_sell,
        "size_scale": round(scale, 4),
        "rsi": rsi_last,
        "reasons": list(man.get("reasons") or []),
        "front_man": man,
        "vol": vol,
        "mode": "PAPER_ONLY",
        "mainnet": MAINNET,
        "degen_buy": DEGEN_BUY,
        "thin": bool(thin),
    }


def _gate_at(
    closes: list[float],
    volumes: list[float],
    index: int,
    *,
    rsi_all: list[float | None],
    sigmas: list[float],
    states: list[str],
    uncond: list[float],
    in_position: bool,
    trades_today: int,
    entry_price: float = 0.0,
) -> dict[str, Any]:
    """O(window) gate using once-per-run vol/RSI series."""
    n = index + 1
    padded_vol = volumes[:n]
    seat_456 = crypto_desk._seat_456(closes[:n], padded_vol, index)
    seat_067 = crypto_desk._seat_067(closes[:n], padded_vol, index)
    seat_240 = crypto_desk._seat_240(closes[:n], index, entry_price if in_position else 0.0)
    vol_z = crypto_desk._zscore(padded_vol, 24)
    thin = any(value > 0 for value in padded_vol) and vol_z <= crypto_desk.THIN_VOLUME_Z
    ret_i = index - 1
    baseline = uncond[ret_i] if 0 <= ret_i < len(uncond) else 1e-6
    sigma = sigmas[ret_i] if 0 <= ret_i < len(sigmas) else baseline
    regime = states[ret_i] if 0 <= ret_i < len(states) else "UNKNOWN"
    scale = crypto_vol.size_scale(sigma, baseline, regime)
    if scale <= 0:
        scale = 0.75
    if thin:
        scale *= THIN_SIZE
    rsi_last = rsi_all[index] if index < len(rsi_all) else None
    buy_band = rsi_last is not None and rsi_last <= DEGEN_BUY
    sell_band = crypto_trader.in_sell_band(rsi_last)
    man = crypto_desk.front_man(
        seat_456,
        seat_067,
        {"vote": "SIZE" if scale > 0 else "WAIT"},
        seat_240,
        has_volume=any(value > 0 for value in padded_vol),
        trades_today=int(trades_today),
        in_position=bool(in_position),
        thin=bool(thin),
    )
    hard = set(man.get("reasons") or []) & HARD_VETO
    chased = (
        str(seat_067.get("vote") or "") == "SPIKE"
        and index > 0
        and closes[index] > closes[index - 1]
    )
    if not chased:
        hard.discard("CROWD_SPIKE")
    setup = buy_band or str(seat_456.get("vote") or "") == "ATTRACTIVE"
    allow_buy = not hard and setup and int(trades_today) < MAX_TRADES_DAY
    allow_sell = bool(in_position) and (
        sell_band or "INVALIDATION" in list(man.get("reasons") or [])
    )
    return {
        "allow_buy": allow_buy,
        "allow_sell": allow_sell,
        "size_scale": round(scale, 4),
        "reasons": list(man.get("reasons") or []),
        "front_man": man,
    }


def apply_live_votes(
    votes: dict[str, str],
    gate: dict[str, Any],
) -> dict[str, str]:
    """Strip buy/sell votes the Front Man would veto. Identity otherwise."""
    out = dict(votes)
    if gate.get("allow_sell") and not gate.get("allow_buy"):
        for key, value in list(out.items()):
            if value == "buy":
                out[key] = "none"
        if all(value == "none" for value in out.values()):
            out["1h"] = "sell"
        return out
    if not gate.get("allow_buy"):
        for key, value in list(out.items()):
            if value == "buy":
                out[key] = "none"
    if not gate.get("allow_sell"):
        for key, value in list(out.items()):
            if value == "sell":
                out[key] = "none"
    return out


def _precompute(closes: list[float]) -> tuple[list[float | None], list[float], list[str], list[float]]:
    rsi_all: list[float | None]
    try:
        rsi_all = list(rsi_series(closes, 14))
    except (TypeError, ValueError):
        rsi_all = [None] * len(closes)
    returns = crypto_vol.log_returns(closes)
    garch = crypto_vol.garch_1_1(returns)
    hmm = crypto_vol.hmm_two_state(returns)
    sigmas = [float(x) for x in (garch.get("sigma") or [])]
    states = [str(x) for x in (hmm.get("states") or [])]
    uncond = list(garch.get("baseline_sigma") or [])
    return rsi_all, sigmas, states, uncond


def run_backtest(frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Walk-forward compose. No lookahead. Paper only."""
    primary = "1h" if "1h" in frames else _walk_primary(frames)
    src = frames[primary]
    closes = [float(x) for x in (src.get("closes") or [])]
    highs = [float(x) for x in (src.get("highs") or closes)]
    lows = [float(x) for x in (src.get("lows") or closes)]
    volumes = [float(x) for x in (src.get("volumes") or [0.0] * len(closes))]
    n = min(len(closes), len(highs), len(lows), len(volumes))
    if n < WARMUP + 16:
        raise RuntimeError("CRYPTO_HISTORY")
    closes, highs, lows, volumes = closes[:n], highs[:n], lows[:n], volumes[:n]
    times = [int(x) for x in (src.get("times") or [])]
    if len(times) < n:
        times = [1_700_000_000 + i * 3600 for i in range(n)]
    else:
        times = times[:n]
    if n > MAX_BARS:
        closes = closes[-MAX_BARS:]
        highs = highs[-MAX_BARS:]
        lows = lows[-MAX_BARS:]
        volumes = volumes[-MAX_BARS:]
        times = times[-MAX_BARS:]
        n = MAX_BARS
    rsi_all, sigmas, states, uncond = _precompute(closes)

    begin = crypto_backtest.start_index(src)
    resume = crypto_backtest.restored("optimal")
    bar_sec = int(crypto_trader.BAR_SEC[primary])
    seed_px = _price_atoms(closes[begin])
    if seed_px <= 0:
        raise RuntimeError("CRYPTO_PRICE")
    start_sol = int(crypto_backtest.START_USD * 1_000_000) * SOL_SCALE // seed_px
    seeded_sol = start_sol * (10000 - crypto_backtest.EXECUTION_BPS) // 10000
    core_sol = int(seeded_sol * CORE_KEEP)
    float_sol = seeded_sol - core_sol
    float_cost_usd = (float_sol * seed_px // SOL_SCALE) * 10000 // (10000 - crypto_backtest.EXECUTION_BPS)
    cash_usd = 0
    cfg = HybridConfig(
        use_timesfm=False,
        cooldown_bars=4,
        max_trades_day=MAX_TRADES_DAY,
    )
    executor: PaperPositionExecutor | None = PaperPositionExecutor(begin, times[begin], closes[begin], cfg) if float_sol > 0 else None
    cooldown_until_i = 0
    lots: list[dict[str, Any]] = []
    fills_today = 0
    current_day = ""
    vetoes = 0
    barrier_counts = {
        "stop_loss": 0,
        "take_profit": 0,
        "trailing_stop": 0,
        "time_limit": 0,
        "invalidation": 0,
        "band_sell": 0,
    }
    fee_holds = 0
    accounting: list[dict[str, Any]] = []

    def _day(ts: int) -> str:
        return str(ts // 86400)

    if resume:
        if resume["config"] != cfg.as_dict():
            raise ValueError("CRYPTO_PAPER_PARAMETERS_CHANGED")
        core_sol = resume["core_sol"]
        float_sol = resume["float_sol"]
        float_cost_usd = resume["float_cost_usd"]
        cash_usd = resume["cash_usd"]
        fills_today = resume["fills_today"]
        current_day = resume["current_day"]
        executor = crypto_backtest.executor_from(resume.get("executor"), times, bar_sec, cfg)
        cooldown_until_i = (int(resume["cooldown_until_ts"]) - times[0]) // bar_sec
    start = n - 1 if resume else begin
    for index in range(start, n):
        accounting.append({"ts": times[index], "usd": (core_sol + float_sol) / SOL_SCALE * closes[index] + cash_usd / 1_000_000})
        day = _day(times[index])
        if day != current_day:
            current_day = day
            fills_today = 0
        in_pos = executor is not None
        gate = _gate_at(
            closes,
            volumes,
            index,
            rsi_all=rsi_all,
            sigmas=sigmas,
            states=states,
            uncond=uncond,
            in_position=in_pos,
            trades_today=fills_today,
            entry_price=float(executor.entry_px) if executor is not None else 0.0,
        )
        px = closes[index]
        px_atoms = _price_atoms(px)
        if px_atoms <= 0:
            continue
        if executor is not None:
            hit = executor.check(index, highs[index], lows[index], px, (src.get("opens") or [None] * n)[index])
            if hit and hit[0] == "time_limit":
                entry = max(1e-12, float(executor.entry_px))
                move_bps = (float(px) - entry) / entry * 10_000.0
                if 0.0 <= move_bps < FEE_HOLD_BPS:
                    hit = None
                    fee_holds += 1
            force_invalid = "INVALIDATION" in gate["reasons"]
            if hit or force_invalid or gate.get("allow_sell"):
                reason = (
                    "invalidation"
                    if force_invalid
                    else (hit[0] if hit else "band_sell")
                )
                exit_px = float(hit[1]) if hit else px
                exit_atoms = _price_atoms(exit_px) or px_atoms
                proceeds = float_sol * exit_atoms // SOL_SCALE
                fee = proceeds * crypto_backtest.EXECUTION_BPS // 10_000
                net = max(0, proceeds - fee)
                cash_usd += net
                lots.append(
                    {
                        "id": "opt-" + str(index),
                        "ts": times[index],
                        "side": "sell",
                        "price": exit_atoms,
                        "sol": float_sol,
                        "usd": net,
                        "profit_usd": net - float_cost_usd,
                        "venue": "optimal-paper",
                        "closed": True,
                    }
                )
                barrier_counts[reason] = barrier_counts.get(reason, 0) + 1
                float_sol = 0
                float_cost_usd = 0
                executor = None
                cooldown_until_i = index + max(0, cfg.cooldown_bars)
                fills_today += 1
                accounting[-1]["usd"] = core_sol / SOL_SCALE * px + cash_usd / 1_000_000
                continue
        if executor is None and gate.get("allow_buy") and fills_today < MAX_TRADES_DAY and index >= cooldown_until_i:
            if cash_usd > 0:
                scale = float(gate.get("size_scale") or 0.0)
                spend = int(cash_usd * min(1.0, max(0.15, scale * CLIP_FRACTION)))
                if spend <= 0:
                    vetoes += 1
                    continue
                fee = spend * crypto_backtest.EXECUTION_BPS // 10_000
                bought = (spend - fee) * SOL_SCALE // px_atoms
                if bought <= 0:
                    continue
                cash_usd -= spend
                float_sol += bought
                float_cost_usd += spend
            elif float_sol <= 0:
                vetoes += 1
                continue
            executor = PaperPositionExecutor(index, times[index], px, cfg)
            lots.append(
                {
                    "id": "opt-" + str(index),
                    "ts": times[index],
                    "side": "buy",
                    "price": px_atoms,
                    "sol": float_sol,
                    "usd": float_cost_usd,
                    "profit_usd": 0,
                    "venue": "optimal-paper",
                    "closed": True,
                }
            )
            fills_today += 1
            accounting[-1]["usd"] = (core_sol + float_sol) / SOL_SCALE * px + cash_usd / 1_000_000
        elif executor is None:
            vetoes += 1

    last_px = _price_atoms(closes[-1])
    accounting[-1]["usd"] = (core_sol + float_sol) / SOL_SCALE * closes[-1] + cash_usd / 1_000_000
    equity_sol = core_sol + float_sol + (
        cash_usd * SOL_SCALE // last_px if last_px else 0
    )
    stats = _trade_stats(
        lots,
        0,
        cash_usd,
        [1],
        sol_held=equity_sol,
        last_close=closes[-1],
        start_sol=start_sol,
    )
    report = {
        "schema": SCHEMA,
        "book": "optimal",
        "accounting": accounting,
        "mode": "PAPER_ONLY",
        "mainnet": MAINNET,
        "note": (
            "GG degen buy ≤38, vol-sized clips, Front Man only on spike/no-tape/cap, "
            "thin tape smaller not skip, hybrid barriers, fee-band hold, CORE_KEEP."
        ),
        "ingredients": [
            "crypto_trader.bands",
            "crypto_vol.size_scale",
            "crypto_desk.front_man",
            "crypto_hybrid.PaperPositionExecutor",
            "fee_hold",
            "CORE_KEEP",
        ],
        "fee_hold_bps": FEE_HOLD_BPS,
        "fee_holds": fee_holds,
        "parallel_agent_brain": "FORBIDDEN",
        "model_agents": False,
        "vetoes": vetoes,
        "barriers": barrier_counts,
        "fills": len(lots),
        "lots": lots[-40:],
        "pnl_sol": stats.get("pnl_sol"),
        "win_rate": stats.get("win_rate"),
        "equity_sol": stats.get("equity_sol") or equity_sol / SOL_SCALE,
    }

    crypto_backtest.checkpoint(report, "optimal", {"config": cfg.as_dict(),
        "executor": crypto_backtest.executor_state(executor),
        "cooldown_until_ts": times[0] + cooldown_until_i * bar_sec,
        "core_sol": core_sol,
        "float_sol": float_sol,
        "float_cost_usd": float_cost_usd,
        "cash_usd": cash_usd,
        "fills_today": fills_today,
        "current_day": current_day}, lots, core_sol + float_sol, cash_usd)
    return report
