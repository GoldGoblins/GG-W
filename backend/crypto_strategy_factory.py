"""Bounded, paper-only strategy discovery for the CRYPTO surface.

The social-media material that inspired this module talks about hundreds of
agents.  The useful part is the research loop, not an unbounded swarm.  This
module therefore evaluates a small, explicit catalogue of deterministic
hypotheses in at most two worker threads and returns an auditable
train/validation/test report.  It never places orders and it never enables a
wallet or a network connector.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import math
import time
from typing import Any
from backend import crypto_backtest


SCHEMA = "gg.crypto.strategy-factory.v1"
MAX_WORKERS = 2
FEE_BPS = crypto_backtest.FEE_BPS
SLIPPAGE_BPS = crypto_backtest.SLIPPAGE_BPS
MIN_BARS = 120


CANDIDATE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "MOMENTUM_20_60",
        "label": "MOMENTUM 20/60",
        "hypothesis": "A fast/slow trend separation may survive costs out of sample.",
        "family": "MOMENTUM",
        "warmup": 60,
        "parameters": {"fast": 20, "slow": 60, "buffer_bps": 10},
    },
    {
        "id": "MEAN_REVERSION_24",
        "label": "MEAN REVERSION 24",
        "hypothesis": "Large short-window deviations may revert before the next regime change.",
        "family": "MEAN_REVERSION",
        "warmup": 24,
        "parameters": {"lookback": 24, "entry_z": 1.5, "exit_z": 0.25},
    },
    {
        "id": "RANGE_BREAKOUT_20",
        "label": "RANGE BREAKOUT 20",
        "hypothesis": "A close outside a prior range may carry short-term continuation.",
        "family": "BREAKOUT",
        "warmup": 20,
        "parameters": {"lookback": 20, "buffer_bps": 10},
    },
    {
        "id": "VOLATILITY_EXPANSION",
        "label": "VOLATILITY EXPANSION",
        "hypothesis": "A positive volatility impulse may identify a tradable expansion phase.",
        "family": "VOLATILITY",
        "warmup": 32,
        "parameters": {"lookback": 32, "trigger_sigma": 1.2},
    },
    {
        "id": "VOL_REGIME_SIZE",
        "label": "VOL REGIME SIZE",
        "hypothesis": "Direction is noisy; only trade the existing momentum idea when the HMM vol state is LOW.",
        "family": "VOL_REGIME",
        "warmup": 60,
        "parameters": {"fast": 20, "slow": 60, "buffer_bps": 10},
    },
)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _sma(values: list[float], length: int) -> float:
    if len(values) < length or length <= 0:
        return 0.0
    return sum(values[-length:]) / float(length)


def _std(values: list[float], length: int) -> float:
    if len(values) < length or length <= 1:
        return 0.0
    sample = values[-length:]
    mean = sum(sample) / float(length)
    return math.sqrt(
        sum((value - mean) ** 2 for value in sample) / float(length)
    )


def _signal(candidate: dict[str, Any], prices: list[float], index: int) -> int:
    """Return target position using prices strictly before ``index``."""
    history = prices[:index]
    family = str(candidate.get("family") or "")
    params = candidate.get("parameters") or {}
    last = history[-1] if history else 0.0
    if last <= 0:
        return 0

    if family == "MOMENTUM":
        fast = _sma(history, int(params.get("fast") or 20))
        slow = _sma(history, int(params.get("slow") or 60))
        buffer_bps = float(params.get("buffer_bps") or 0.0) / 10_000.0
        if fast > slow * (1.0 + buffer_bps):
            return 1
        if fast < slow * (1.0 - buffer_bps):
            return 0
        return 0

    if family == "MEAN_REVERSION":
        lookback = int(params.get("lookback") or 24)
        mean = _sma(history, lookback)
        sigma = _std(history, lookback)
        if mean <= 0 or sigma <= 1e-12:
            return 0
        z_score = (last - mean) / sigma
        entry_z = float(params.get("entry_z") or 1.5)
        exit_z = float(params.get("exit_z") or 0.25)
        if z_score <= -entry_z:
            return 1
        if z_score >= -exit_z:
            return 0
        return 0

    if family == "BREAKOUT":
        lookback = int(params.get("lookback") or 20)
        if len(history) <= lookback:
            return 0
        window = history[-lookback - 1:-1]
        buffer_bps = float(params.get("buffer_bps") or 0.0) / 10_000.0
        if last > max(window) * (1.0 + buffer_bps):
            return 1
        if last < min(window) * (1.0 - buffer_bps):
            return 0
        return 0

    if family == "VOLATILITY":
        lookback = int(params.get("lookback") or 32)
        if len(history) <= lookback:
            return 0
        returns = [
            math.log(history[i] / history[i - 1])
            for i in range(max(1, len(history) - lookback), len(history))
            if history[i] > 0 and history[i - 1] > 0
        ]
        if len(returns) < 8:
            return 0
        mean = sum(returns) / len(returns)
        sigma = math.sqrt(
            sum((value - mean) ** 2 for value in returns) / len(returns)
        )
        current = math.log(last / history[-2]) if history[-2] > 0 else 0.0
        trigger = float(params.get("trigger_sigma") or 1.2)
        if sigma > 1e-12 and current > mean + trigger * sigma:
            return 1
        if sigma > 1e-12 and current < mean:
            return 0
        return 0

    if family == "VOL_REGIME":
        from backend import crypto_vol

        snap = crypto_vol.snapshot(history)
        if str((snap.get("hmm") or {}).get("last_state") or "") != "LOW":
            return 0
        fast = _sma(history, int(params.get("fast") or 20))
        slow = _sma(history, int(params.get("slow") or 60))
        buffer_bps = float(params.get("buffer_bps") or 0.0) / 10_000.0
        if fast > slow * (1.0 + buffer_bps):
            return 1
        return 0

    return 0


def _clean_frame(frame: Any) -> tuple[list[float], list[int]]:
    if not isinstance(frame, dict):
        return [], []
    raw_closes = frame.get("closes") or []
    raw_times = frame.get("times") or []
    closes: list[float] = []
    times: list[int] = []
    for index, raw in enumerate(raw_closes):
        price = _finite(raw, 0.0)
        if price <= 0:
            continue
        closes.append(price)
        if index < len(raw_times):
            try:
                times.append(int(raw_times[index]))
            except (TypeError, ValueError):
                times.append(0)
        else:
            times.append(0)
    return closes, times


def _trade_report(
    candidate: dict[str, Any],
    prices: list[float],
    start: int,
    end: int,
    bar_seconds: int = 3600,
) -> dict[str, Any]:
    warmup = int(candidate.get("warmup") or 0)
    first = max(warmup, int(start))
    last = min(len(prices), int(end))
    if last - first < 10:
        return {
            "state": "INSUFFICIENT_DATA",
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trades": 0,
            "wins": 0,
            "win_rate_pct": 0.0,
            "sharpe_proxy": 0.0,
        }

    friction = (FEE_BPS + SLIPPAGE_BPS) / 10_000.0
    cash = 1.0
    units = 0.0
    entry_price = 0.0
    equity_curve: list[float] = []
    trades: list[float] = []

    for index in range(first, last):
        price = prices[index]
        target = _signal(candidate, prices, index)
        if target == 1 and units <= 0:
            units = cash * (1.0 - friction) / price
            cash = 0.0
            entry_price = price
        elif target == 0 and units > 0:
            cash = units * price * (1.0 - friction)
            if entry_price > 0:
                trades.append((price / entry_price * (1.0 - friction)**2 - 1.0) * 100.0)
            units = 0.0
            entry_price = 0.0
        equity_curve.append(cash + units * price)

    if units > 0 and equity_curve:
        price = prices[last - 1]
        cash = units * price * (1.0 - friction)
        if entry_price > 0:
            trades.append((price / entry_price * (1.0 - friction)**2 - 1.0) * 100.0)
        equity_curve[-1] = cash

    if not equity_curve:
        return {
            "state": "INSUFFICIENT_DATA",
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "trades": 0,
            "wins": 0,
            "win_rate_pct": 0.0,
            "sharpe_proxy": 0.0,
        }

    peak = 1.0
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)

    returns = [
        (equity_curve[index] / equity_curve[index - 1]) - 1.0
        for index in range(1, len(equity_curve))
        if equity_curve[index - 1] > 0
    ]
    mean = sum(returns) / len(returns) if returns else 0.0
    sigma = (
        math.sqrt(sum((value - mean) ** 2 for value in returns) / len(returns))
        if returns
        else 0.0
    )
    sharpe_proxy = (mean / sigma) * math.sqrt(365.0 * 86400 / bar_seconds) if sigma > 1e-12 else 0.0
    wins = sum(1 for value in trades if value > 0)
    return {
        "state": "PASS",
        "return_pct": round((cash - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "trades": len(trades),
        "wins": wins,
        "win_rate_pct": round((wins / len(trades)) * 100.0, 2) if trades else 0.0,
        "avg_trade_pct": round(sum(trades) / len(trades), 4) if trades else 0.0,
        "sharpe_proxy": round(sharpe_proxy, 4),
        "bars": last - first,
    }


def _candidate_report(
    candidate: dict[str, Any],
    prices: list[float],
    split: dict[str, int],
    bar_seconds: int = 3600,
) -> dict[str, Any]:
    train = _trade_report(candidate, prices, 0, split["train_end"], bar_seconds)
    validation = _trade_report(
        candidate,
        prices,
        split["train_end"],
        split["validation_end"],
        bar_seconds,
    )
    test = _trade_report(candidate, prices, split["validation_end"], len(prices), bar_seconds)
    test_start = split["validation_end"]
    buy_hold = 0.0
    if test_start < len(prices) and prices[test_start] > 0:
        friction = (FEE_BPS + SLIPPAGE_BPS) / 10_000.0
        buy_hold = (prices[-1] / prices[test_start] * (1-friction)**2 - 1.0) * 100.0
    round_trip_pct = 2.0 * (FEE_BPS + SLIPPAGE_BPS) / 100.0
    avg_trade = float(test.get("avg_trade_pct") or 0.0)
    if len(prices) < MIN_BARS:
        verdict = "INSUFFICIENT_DATA"
        reason = f"Need at least {MIN_BARS} bars for three honest splits."
    elif validation["trades"] < 2 or test["trades"] < 3:
        verdict = "WATCH"
        reason = "Too few out-of-sample trades to support a decision."
    elif test["max_drawdown_pct"] > 35.0 or test["return_pct"] < -5.0:
        verdict = "REJECT"
        reason = "Out-of-sample drawdown or return breached the review gate."
    elif (
        test["return_pct"] > 0.0
        and validation["return_pct"] > -2.0
        and test["return_pct"] > buy_hold
        and avg_trade > 0.0
    ):
        verdict = "PASS"
        reason = (
            "Test beat buy-and-hold after fees, and the average trade cleared the round trip."
        )
    elif test["return_pct"] > 0.0 and validation["return_pct"] > -2.0:
        verdict = "WATCH"
        reason = "Positive test, but it did not beat buy-and-hold after fees."
    else:
        verdict = "WATCH"
        reason = "Mixed validation/test evidence; human review required."
    return {
        "id": str(candidate.get("id") or ""),
        "label": str(candidate.get("label") or ""),
        "family": str(candidate.get("family") or ""),
        "hypothesis": str(candidate.get("hypothesis") or ""),
        "parameters": dict(candidate.get("parameters") or {}),
        "verdict": verdict,
        "gate_reason": reason,
        "train": train,
        "validation": validation,
        "validation_folds": _validation_folds(candidate, prices, split, bar_seconds),
        "test": test,
        "buy_hold_test_pct": round(buy_hold, 4),
    }


def _choose_frame(frames: dict[str, Any]) -> tuple[str, list[float], list[int]]:
    preferred = ("1h", "4h", "8h", "1d", "15m", "5m", "1m")
    for interval in preferred:
        if interval in frames:
            closes, times = _clean_frame(frames[interval])
            if closes:
                return interval, closes, times
    for interval in sorted(frames):
        closes, times = _clean_frame(frames[interval])
        if closes:
            return interval, closes, times
    return "", [], []


def _validation_folds(candidate, prices, split, bar_seconds):
    """Two expanding-history folds, both strictly before the final holdout."""
    first, end = split["train_end"], split["validation_end"]
    middle = (first + end) // 2
    return [{"train_end": start, "from_index": start, "to_index": stop,
             **_trade_report(candidate, prices, start, stop, bar_seconds)}
            for start, stop in ((first, middle), (middle, end))]


def _validation_score(candidate, prices, split, bar_seconds):
    folds = _validation_folds(candidate, prices, split, bar_seconds)
    return sum(float(row.get("sharpe_proxy") or 0) for row in folds) / len(folds)


def _timestamp_label(value: int) -> str:
    if value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "state": "IDLE",
        "mode": "PAPER_ONLY",
        "scope": "BOUNDED_LOCAL_RESEARCH",
        "note": "No strategy factory run yet.",
        "candidates": [],
        "graveyard": [],
        "autoresearch": [],
        "orchestration": orchestration_snapshot("IDLE"),
    }


def orchestration_snapshot(state: str) -> dict[str, Any]:
    current = str(state or "IDLE").upper()
    phase_state = "PASS" if current == "DONE" else current
    return {
        "schema": "gg.crypto.research-board.v1",
        "mode": "BOUNDED_DETERMINISTIC_WORKERS",
        "max_parallel": MAX_WORKERS,
        "model_agents": False,
        "roles": [
            {"id": "RESEARCHER", "state": phase_state},
            {"id": "DATA_VALIDATOR", "state": phase_state},
            {"id": "IMPLEMENTER", "state": phase_state},
            {"id": "REVIEWER", "state": phase_state},
            {"id": "RISK", "state": phase_state},
        ],
        "gates": [
            "NO_LOOKAHEAD",
            "COSTS_AND_SLIPPAGE",
            "CHRONOLOGICAL_HOLDOUT",
            "PAPER_ONLY",
            "HUMAN_REVIEW_BEFORE_ACTION",
            "NEGATIVE_RESULTS_KEPT",
            "KEEP_OR_REVERT",
        ],
    }


def run_factory(frames: dict[str, Any]) -> dict[str, Any]:
    interval, prices, times = _choose_frame(frames)
    if not prices:
        return {
            **empty_snapshot(),
            "state": "ERROR",
            "note": "No usable OHLCV data was available.",
            "orchestration": orchestration_snapshot("ERROR"),
        }

    n = len(prices)
    bar_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "8h": 28800, "1d": 86400}.get(interval, 3600)
    train_end = max(1, int(n * 0.40))
    validation_end = max(train_end + 1, int(n * 0.80))
    split = {
        "train_end": min(train_end, n),
        "validation_end": min(validation_end, n),
    }
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="gg-strategy") as pool:
        futures = [
            pool.submit(_candidate_report, candidate, prices, split, bar_seconds)
            for candidate in CANDIDATE_CATALOG
        ]
        candidates = [future.result() for future in futures]

    graveyard = [
        {
            "id": row["id"],
            "verdict": row["verdict"],
            "gate_reason": row["gate_reason"],
            "test_return_pct": (row.get("test") or {}).get("return_pct"),
        }
        for row in candidates
        if row.get("verdict") in {"REJECT", "WATCH", "INSUFFICIENT_DATA"}
    ]

    base = dict(CANDIDATE_CATALOG[0])
    # Parameter choice never reads the final holdout. Only the frozen winner
    # is evaluated on that period after all validation decisions are made.
    best_sharpe = _validation_score(base, prices, split, bar_seconds)
    best_buffer = int((base.get("parameters") or {}).get("buffer_bps") or 10)
    autoresearch: list[dict[str, Any]] = [
        {
            "step": 0,
            "mutation": "BASE",
            "buffer_bps": best_buffer,
            "validation_sharpe": round(best_sharpe, 4),
            "decision": "KEEP",
        }
    ]
    for step, buffer in enumerate((5, 15, 25), start=1):
        mutated = {
            **base,
            "id": f"MOMENTUM_20_60_B{buffer}",
            "parameters": {**(base.get("parameters") or {}), "buffer_bps": buffer},
        }
        sharpe = _validation_score(mutated, prices, split, bar_seconds)
        keep = sharpe > best_sharpe
        if keep:
            best_sharpe = sharpe
            best_buffer = buffer
        autoresearch.append(
            {
                "step": step,
                "mutation": f"buffer_bps={buffer}",
                "buffer_bps": buffer,
                "validation_sharpe": round(sharpe, 4),
                "decision": "KEEP" if keep else "REVERT",
            }
        )

    return {
        "schema": SCHEMA,
        "state": "DONE",
        "mode": "PAPER_ONLY",
        "scope": "BOUNDED_LOCAL_RESEARCH",
        "note": "Deterministic candidates evaluated; no order path is connected.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "symbol": "SOLUSDT",
            "interval": interval,
            "bars": n,
            "from": _timestamp_label(times[0]) if times else "",
            "to": _timestamp_label(times[-1]) if times else "",
            "fee_bps": FEE_BPS,
            "slippage_bps": SLIPPAGE_BPS,
        },
        "split": {
            "train_pct": 40,
            "validation_pct": 40,
            "test_pct": 20,
            "train_end": split["train_end"],
            "validation_end": split["validation_end"],
        },
        "candidates": candidates,
        "graveyard": graveyard,
        "autoresearch": {
            "pattern": "KEEP_OR_REVERT",
            "best_buffer_bps": best_buffer,
            "best_validation_sharpe": round(best_sharpe, 4),
            "selection_period": "validation",
            "trial_count": len(candidates) + len(autoresearch) - 1,
            "selection_method": "Mean Sharpe of two expanding-history validation folds",
            "trial_registry": [row["id"] for row in CANDIDATE_CATALOG] + [f"MOMENTUM_20_60_B{x}" for x in (5, 15, 25)],
            "validation_folds": _validation_folds({**base, "parameters": {**base["parameters"], "buffer_bps": best_buffer}}, prices, split, bar_seconds),
            "interpretation": "Exploratory trials; final holdout is shown once per frozen choice, not an automatic winner or statistical proof.",
            "final_test": _trade_report(
                {**base, "parameters": {**base["parameters"], "buffer_bps": best_buffer}},
                prices, split["validation_end"], n, bar_seconds,
            ),
            "steps": autoresearch,
        },
        "orchestration": orchestration_snapshot("DONE"),
    }


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "family": str(row["family"]),
            "hypothesis": str(row["hypothesis"]),
        }
        for row in CANDIDATE_CATALOG
    ]


def generated_epoch() -> int:
    return int(time.time())
