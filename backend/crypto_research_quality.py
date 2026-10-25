"""Bounded, descriptive reliability diagnostics for historical research.

Original implementation of circular block resampling and prefix invariance.
No strategy code, external packages, file/network access, forecasts or trade
recommendations. A bootstrap diagnostic does not repair selection bias, and
one successful prefix comparison cannot establish absence of future leakage.
"""
from __future__ import annotations

import math
import random
from typing import Any, Iterator

MAX_EQUITY = 4096
MAX_REPLICAS = 256
MIN_RETURNS = 30
INTERVAL_LEVEL = 0.95
_MAX_SIGNAL_NODES = 65536
_LIMITS = [
    "Historical resampling uncertainty only; not a forecast or a probability of profit.",
    "Within-block return order is retained; joins break some dependence and stationarity is assumed.",
    "Results depend on block size, sample length, regimes, costs and the original strategy selection.",
    "No out-of-sample, walk-forward or leakage test is implied by this bootstrap.",
]


def _checked_integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("CRYPTO_RESEARCH_" + name)
    return value


def _block_length(sample_count: int) -> int:
    # Transparent, deterministic heuristic: ceil(cube root of return count).
    result = 2
    while result**3 < sample_count:
        result += 1
    return result


def _resampled_returns(returns: list[float], rng: random.Random,
                       block_size: int) -> Iterator[float]:
    """One circular moving-block path, streamed without a retained matrix."""
    size = len(returns)
    remaining = size
    while remaining:
        start = rng.randrange(size)
        take = min(block_size, remaining)
        for offset in range(take):
            yield returns[(start + offset) % size]
        remaining -= take


def _path_metrics(returns) -> tuple[float, float]:
    # Log wealth prevents path underflow and keeps drawdown scale invariant.
    # Total-return overflow becomes explicit unavailable data, never clipping.
    wealth, peak, drawdown = 0.0, 0.0, 0.0
    for change in returns:
        wealth += change
        peak = max(peak, wealth)
        drawdown = max(drawdown, -math.expm1(wealth - peak))
    total = math.expm1(wealth)
    if not math.isfinite(total) or not math.isfinite(drawdown):
        raise OverflowError("unrepresentable resampled path")
    return total, drawdown


def _percentile(sorted_values: list[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def _summary(values: list[float]) -> dict:
    values = sorted(values)
    return {"lower": _percentile(values, 0.025), "median": _percentile(values, 0.5),
            "upper": _percentile(values, 0.975), "minimum": values[0], "maximum": values[-1]}


def report(equity: list, *, seed: int = 0, replicas: int = 128,
           block_size: int | None = None) -> dict:
    """Describe empirical uncertainty using contiguous circular return blocks.

    Input is one consistently denominated equity value per ordered bar, with
    no deposits/withdrawals. The caller must supply the actual initial equity
    if the first return should include opening costs. None marks missing data;
    it is never removed or bridged. At least thirty contiguous returns are
    required. Interval values are fractions (0.1 is 10%), not predictions or
    calibrated confidence claims about an unknown population parameter.
    """
    if not isinstance(equity, list) or len(equity) > MAX_EQUITY:
        raise ValueError("CRYPTO_RESEARCH_EQUITY_LIMIT")
    seed = _checked_integer(seed, "SEED", -(1 << 63), (1 << 64) - 1)
    replicas = _checked_integer(replicas, "REPLICAS", 1, MAX_REPLICAS)
    if block_size is not None:
        block_size = _checked_integer(block_size, "BLOCK_SIZE", 2, MAX_EQUITY - 1)
    values = []
    missing = 0
    for value in equity:
        if value is None:
            missing += 1
            values.append(None)
            continue
        if type(value) not in (int, float):
            raise ValueError("CRYPTO_RESEARCH_EQUITY_INVALID")
        try:
            numeric = float(value)
        except (OverflowError, ValueError):
            raise ValueError("CRYPTO_RESEARCH_EQUITY_INVALID") from None
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError("CRYPTO_RESEARCH_EQUITY_INVALID")
        values.append(numeric)
    count = sum(first is not None and second is not None
                for first, second in zip(values, values[1:]))
    result = {"available": False, "reason": "", "method": "circular_block_bootstrap",
              "sample_count": count, "equity_count": len(values), "missing_count": missing,
              "minimum_sample_count": MIN_RETURNS, "seed": seed, "replicas": replicas,
              "block_size": block_size, "interval_level": INTERVAL_LEVEL,
              "interval_kind": "empirical_resample_percentiles",
              "metric_units": "fraction", "observed": None, "intervals": None,
              "limits": list(_LIMITS)}
    if missing:
        return {**result, "reason": "MISSING_EQUITY"}
    if count < MIN_RETURNS:
        return {**result, "reason": "INSUFFICIENT_RETURNS"}
    chosen = _block_length(count) if block_size is None else block_size
    if chosen > count:
        raise ValueError("CRYPTO_RESEARCH_BLOCK_SIZE")
    result["block_size"] = chosen
    result["blocks_per_replica"] = (count + chosen - 1) // chosen
    log_returns = [math.log(values[i]) - math.log(values[i - 1]) for i in range(1, len(values))]
    rng = random.Random(seed)
    totals, drawdowns = [], []
    try:
        total, drawdown = _path_metrics(log_returns)
        observed = {"total_return": total, "max_drawdown": drawdown}
        result["observed"] = observed
        for _ in range(replicas):
            total, drawdown = _path_metrics(_resampled_returns(log_returns, rng, chosen))
            totals.append(total)
            drawdowns.append(drawdown)
    except OverflowError:
        return {**result, "reason": "NUMERIC_RANGE_UNAVAILABLE", "completed_replicas": len(totals)}
    result.update(available=True, reason="", completed_replicas=replicas,
                  intervals={"total_return": _summary(totals), "max_drawdown": _summary(drawdowns)})
    if replicas < 40:
        result["limits"].append("Few replicas: percentile endpoints are especially coarse.")
    if chosen == count:
        result["limits"].append("A full-length circular block fixes total return; its interval is degenerate.")
    return result


def _signal_signature(value: Any, budget: list[int], depth: int = 0):
    """Bounded typed equality for JSON-like signal outputs; reject NaN/bools-as-ints."""
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        raise ValueError("CRYPTO_CAUSALITY_SIGNAL_LIMIT")
    kind = type(value)
    if value is None:
        return ("null",)
    if kind is bool:
        return ("bool", value)
    if kind is int and abs(value) < (1 << 128):
        return ("int", value)
    if kind is float and math.isfinite(value):
        return ("float", value)
    if kind is str and len(value) <= 512:
        return ("str", value)
    if kind is list and len(value) <= 128:
        return ("list", tuple(_signal_signature(v, budget, depth + 1) for v in value))
    if kind is dict and len(value) <= 32:
        if any(type(key) is not str or len(key) > 128 for key in value):
            raise ValueError("CRYPTO_CAUSALITY_SIGNAL_INVALID")
        return ("dict", tuple((key, _signal_signature(value[key], budget, depth + 1))
                              for key in sorted(value)))
    raise ValueError("CRYPTO_CAUSALITY_SIGNAL_INVALID")


def causality_check(full_signals: list, prefix_signals: list, cutoff: int) -> dict:
    """Compare [0:cutoff], where cutoff is the actual prefix tape length.

    The caller must independently rerun its executable strategy on the real
    prefix input. Slicing previously generated full-tape signals is not that
    experiment. Future full-tape outputs are neither compared nor inspected.
    A mismatch rejects prefix invariance; leakage or nondeterminism may cause
    it. Passing one prefix does not prove an absence of lookahead bias.
    """
    cutoff = _checked_integer(cutoff, "CUTOFF", 1, MAX_EQUITY)
    if (not isinstance(full_signals, list) or not isinstance(prefix_signals, list)
            or len(full_signals) > MAX_EQUITY or len(prefix_signals) > MAX_EQUITY
            or len(full_signals) < cutoff or len(prefix_signals) != cutoff):
        raise ValueError("CRYPTO_CAUSALITY_PREFIX_LENGTH")
    mismatches, first_indices = 0, []
    budget = [_MAX_SIGNAL_NODES]
    for index in range(cutoff):
        full = _signal_signature(full_signals[index], budget)
        prefix = _signal_signature(prefix_signals[index], budget)
        if full != prefix:
            mismatches += 1
            if len(first_indices) < 16:
                first_indices.append(index)
    return {"available": True, "passed": mismatches == 0,
            "prefix_invariant": mismatches == 0, "possible_lookahead": mismatches > 0,
            "reason": "PREFIX_OUTPUT_CHANGED" if mismatches else "",
            "cutoff": cutoff, "compared_count": cutoff, "mismatch_count": mismatches,
            "first_mismatch_index": first_indices[0] if first_indices else None,
            "mismatch_indices": first_indices,
            "limits": ["Caller must independently execute the strategy on real prefix inputs.",
                       "Mismatch can indicate leakage or nondeterminism; passing one prefix is not proof of causality.",
                       "This comparison does not establish walk-forward or out-of-sample performance."]}
