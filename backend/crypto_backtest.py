"""Common costs, accounting metrics and baselines for the native paper books."""
from __future__ import annotations

import math
from contextvars import ContextVar
from typing import Any

from backend.crypto_data import BAR_SECONDS, iso, validate_frame

FEE_BPS = 30
SLIPPAGE_BPS = 5
EXECUTION_BPS = FEE_BPS + SLIPPAGE_BPS
START_USD = 200.0
WARMUP = 80
MAX_BARS = 4000
PERSIST = ContextVar("crypto_backtest_persist", default=True)
CONTINUATION = ContextVar("crypto_strategy_continuation", default=None)
STREAM = ContextVar("crypto_strategy_stream", default=False)


def start_index(src: dict[str, Any]) -> int:
    return min(len(src["closes"]) - 1, max(WARMUP, int(src.get("evaluation_start", WARMUP))))


def restored(book: str) -> dict[str, Any]:
    import copy
    value = CONTINUATION.get()
    if not value:
        return {}
    if value.get("book") != book:
        raise ValueError("CRYPTO_CONTINUATION_BOOK")
    return copy.deepcopy(value)


def executor_from(raw: dict[str, Any] | None, times: list[int], step: int, config: Any):
    if not raw:
        return None
    from backend.crypto_hybrid import PaperPositionExecutor
    index = (int(raw["entry_ts"]) - times[0]) // step
    return PaperPositionExecutor(index, int(raw["entry_ts"]), float(raw["entry_px"]), config, float(raw["peak_px"]))


def executor_state(executor: Any) -> dict[str, Any] | None:
    return {key: getattr(executor, key) for key in ("entry_ts", "entry_px", "peak_px")} if executor else None


def checkpoint(report: dict[str, Any], book: str, state: dict[str, Any], events: list[dict[str, Any]],
               tokens: int, quote: int) -> None:
    report["inventory_tokens"] = tokens / 1_000_000_000
    report["quote_balance"] = quote / 1_000_000
    if STREAM.get():
        report["continuation"] = {**state, "book": book}
        report["events"] = events
        report["inventory_tokens"] = tokens / 1_000_000_000
        report["quote_balance"] = quote / 1_000_000


def metrics(values: list[float], initial: float, bar_seconds: int) -> dict[str, float]:
    peak, drawdown = initial, 0.0
    previous = initial
    returns = []
    for value in values:
        if not math.isfinite(value) or value < 0:
            raise ValueError("CRYPTO_EQUITY_INVALID")
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak) if peak else drawdown
        returns.append(value / previous - 1 if previous else 0)
        previous = value
    mean = sum(returns) / max(1, len(returns))
    variance = sum((r - mean) ** 2 for r in returns) / max(1, len(returns))
    return {
        "return_pct": round((previous / initial - 1) * 100, 4),
        "max_drawdown_pct": round(drawdown * 100, 4),
        "sharpe_proxy": round(mean / math.sqrt(variance) * math.sqrt(365 * 86400 / bar_seconds), 4) if variance > 1e-16 else 0.0,
        "end_usd": round(previous, 8),
    }


def prepare(frames: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    primary = "1h" if "1h" in frames else next((tf for tf in BAR_SECONDS if tf in frames), "")
    if not primary:
        raise ValueError("CRYPTO_HISTORY")
    src = validate_frame(frames[primary], primary, min_bars=96)
    if src["gaps"]:
        raise ValueError("CRYPTO_DATA_GAPS")
    src = {**src, **{k: src[k][-MAX_BARS:] for k in ("highs", "lows", "closes", "volumes", "times", "opens") if k in src}}
    src = validate_frame(src, primary)
    src["evaluation_primary"] = True
    # Every comparison book sees exactly the same primary tape and clock.
    out = {primary: src}
    for tf, raw in frames.items():
        if tf == primary:
            continue
        row = validate_frame(raw, tf, min_bars=1)
        if row["symbol"] != src["symbol"]:
            raise ValueError("CRYPTO_DATA_PAIR_MIX")
        if row["gaps"]:
            raise ValueError("CRYPTO_DATA_GAPS")
        cutoff = src["times"][-1] + BAR_SECONDS[primary]
        indices = [i for i, t in enumerate(row["times"]) if t + BAR_SECONDS[tf] <= cutoff]
        if indices:
            out[tf] = {**row, "evaluation_primary": False, **{k: [row[k][i] for i in indices] for k in ("highs", "lows", "closes", "volumes", "times", "opens") if k in row}}
    return out


def benchmarks(prices: list[float], times: list[int], step: int) -> dict[str, Any]:
    friction = EXECUTION_BPS / 10000
    units = START_USD * (1 - friction) / prices[0]
    hold = [units * price for price in prices]
    cash, units, dca, contributions = START_USD, 0.0, [], 0
    first_day = times[0] // 86400
    total_days = times[-1] // 86400 - first_day + 1
    amount = START_USD / total_days
    day = None
    for price, stamp in zip(prices, times):
        if stamp // 86400 != day:
            day = stamp // 86400
            spend = min(cash, amount)
            units += spend * (1 - friction) / price
            cash -= spend
            contributions += 1
        dca.append(cash + units * price)
    return {"buy_and_hold": metrics(hold, START_USD, step), "simple_dca": {**metrics(dca, START_USD, step), "contributions": contributions}}


def finalize(report: dict[str, Any], frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = "1h" if "1h" in frames else next(iter(frames))
    src = frames[primary]
    step = BAR_SECONDS[primary]
    begin = start_index(src)
    stamps, prices = src["times"][begin:], src["closes"][begin:]
    if not prices:
        raise ValueError("CRYPTO_HISTORY")
    rows = report.pop("accounting", [])
    by_time = {int(row["ts"]): float(row["usd"]) for row in rows}
    if any(t not in by_time for t in stamps):
        raise ValueError("CRYPTO_ACCOUNTING_INCOMPLETE")
    values = [by_time[t] for t in stamps]
    summary = metrics(values, START_USD, step)
    end_sol = values[-1] / prices[-1]
    return {
        **report, "book": report["book"], "mode": "PAPER_ONLY", "quote_currency": "USDT" if src["symbol"].endswith("USDT") else "USD", "verdict": "DESCRIPTIVE",
        "primary": primary, "bars": len(src["closes"]),
        "range": iso(stamps[0]) + " → " + iso(stamps[-1] + step),
        "data": {k: src[k] for k in ("source", "symbol", "interval", "bar_count", "gaps", "closed_only", "volume_available", "from", "to")},
        "cost_model": {"fee_bps": FEE_BPS, "slippage_bps": SLIPPAGE_BPS, "per_leg_bps": EXECUTION_BPS,
                       "network_cost_usd": 0.0, "network_cost": "Excluded: off-chain paper run; chain fees are not estimated",
                       "assumption": "Fixed hypothetical execution friction, not a measured live venue quote"},
        "metrics": summary, "benchmarks": benchmarks(prices, stamps, step),
        "start_usd": str(START_USD), "end_usd": str(round(values[-1], 6)),
        "pnl_usd": str(round(values[-1] - START_USD, 6)), "return_pct": summary["return_pct"],
        "max_drawdown_pct": summary["max_drawdown_pct"],
        "sharpe_proxy": summary["sharpe_proxy"],
        "token_equivalent": round(end_sol, 9), "base_asset": src["symbol"].removesuffix("USDT"),
        "equity_sol": round(end_sol, 9),
        "pnl_sol": round(end_sol - START_USD / prices[0], 9),
        "return_sol_pct": round((end_sol / (START_USD / prices[0]) - 1) * 100, 4),
        "execution_assumption": "Closed-bar signals; close-price paper fills with 35 bps per leg; intrabar barriers use conservative stop-first ordering.",
        "validation": "DESCRIPTIVE_HISTORICAL · strategy parameters frozen before this run",
        "chart": {**(report.get("chart") or {}), "closes": src["closes"], "times": src["times"], "interval": primary,
                  "equity": [{"ts": t, "sol": value / price} for t, value, price in zip(stamps, values, prices)]},
    }
