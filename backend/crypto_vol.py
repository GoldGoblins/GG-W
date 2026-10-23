"""Paper volatility state: GARCH(1,1) plus a two-state HMM.

Price direction is treated as noisy.  Position size follows the vol regime.
This module never places orders and has no network or wallet path.
"""

from __future__ import annotations

import math
from typing import Any


SCHEMA = "gg.crypto.vol-regime.v1"
GARCH_ALPHA = 0.08
GARCH_BETA = 0.90
MIN_BARS = 48
SIZE_FLOOR = 0.15
SIZE_CAP = 1.50
HMM_STAY_LOW = 0.90
HMM_STAY_HIGH = 0.80


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    previous = 0.0
    for raw in closes:
        price = _finite(raw, 0.0)
        if price <= 0:
            continue
        if previous > 0:
            out.append(math.log(price / previous))
        previous = price
    return out


def garch_1_1(returns: list[float]) -> dict[str, Any]:
    """Causal variance-targeted GARCH with an expanding historical baseline.

    Every output uses only observations through that index. No whole-sample
    initialization or future variance estimate enters a historical forecast.
    """
    sample = [value for value in returns if math.isfinite(value)]
    mean = m2 = 0.0
    sigma2 = 1e-12
    series: list[float] = []
    baselines: list[float] = []
    omega = 0.0
    for count, value in enumerate(sample, 1):
        delta = value - mean
        mean += delta / count
        m2 += delta * (value - mean)
        var = max(m2 / count if count > 1 else value * value, 1e-12)
        if count == 1:
            sigma2 = var
        omega = var * (1.0 - GARCH_ALPHA - GARCH_BETA)
        sigma2 = max(omega + GARCH_ALPHA * value * value + GARCH_BETA * sigma2, 1e-12)
        series.append(math.sqrt(sigma2))
        baselines.append(math.sqrt(var))
    return {
        "ok": len(sample) >= 8,
        "sigma": series,
        "baseline_sigma": baselines,
        "last_sigma": series[-1] if series else 0.0,
        "unconditional": baselines[-1] if baselines else 0.0,
        "alpha": GARCH_ALPHA,
        "beta": GARCH_BETA,
        "omega": omega,
        "persistence": GARCH_ALPHA + GARCH_BETA,
        "method": "CAUSAL_EXPANDING_VARIANCE",
    }


def hmm_two_state(returns: list[float]) -> dict[str, Any]:
    """Online two-state volatility filter with adaptive exponential emissions.

    This is a causal filter, not a batch EM fit or Viterbi reconstruction.
    The probability is the latest filtered high-state probability; persistence
    describes observed state continuity, not prediction accuracy.
    """
    magnitudes = [abs(value) for value in returns if math.isfinite(value)]
    low_mean, high_mean = 0.001, 0.01
    p_high = 0.2
    states: list[str] = []
    probabilities: list[float] = []
    for value in magnitudes:
        prior = p_high * HMM_STAY_HIGH + (1 - p_high) * (1 - HMM_STAY_LOW)
        log_low = math.log(max(1e-12, 1 - prior)) - math.log(low_mean) - value / low_mean
        log_high = math.log(max(1e-12, prior)) - math.log(high_mean) - value / high_mean
        delta = max(-700.0, min(700.0, log_low - log_high))
        p_high = 1.0 / (1.0 + math.exp(delta))
        states.append("HIGH" if p_high >= 0.5 else "LOW")
        probabilities.append(p_high)
        low_mean = max(1e-8, low_mean + 0.05 * (1 - p_high) * (value - low_mean))
        high_mean = max(low_mean * 1.2, high_mean + 0.05 * p_high * (value - high_mean))
    same = sum(a == b for a, b in zip(states, states[1:]))
    return {
        "ok": len(magnitudes) >= 16,
        "states": states,
        "probabilities": probabilities,
        "last_state": states[-1] if states else "UNKNOWN",
        "p_high": p_high,
        "high_fraction": sum(s == "HIGH" for s in states) / max(1, len(states)),
        "low_mean": low_mean,
        "high_mean": high_mean,
        "state_persistence": round(same / max(1, len(states) - 1), 4),
        "method": "CAUSAL_TWO_STATE_FILTER",
    }


def size_scale(
    last_sigma: float,
    unconditional: float,
    regime: str,
) -> float:
    """Vol-aware size.  High-vol regimes shrink; low-vol may use full size."""
    baseline = max(1e-8, _finite(unconditional, 0.0))
    sigma = max(1e-8, _finite(last_sigma, baseline))
    scale = baseline / sigma
    if str(regime or "").upper() == "HIGH":
        scale *= 0.50
    elif str(regime or "").upper() == "LOW":
        scale *= 1.00
    else:
        scale *= 0.75
    return max(SIZE_FLOOR, min(SIZE_CAP, scale))


def snapshot(closes: list[float]) -> dict[str, Any]:
    returns = log_returns(closes)
    garch = garch_1_1(returns)
    hmm = hmm_two_state(returns)
    scale = 0.0
    if garch.get("ok"):
        scale = size_scale(
            float(garch.get("last_sigma") or 0.0),
            float(garch.get("unconditional") or 0.0),
            str(hmm.get("last_state") or "UNKNOWN"),
        )
    return {
        "schema": SCHEMA,
        "ok": bool(garch.get("ok") and hmm.get("ok") and len(returns) >= MIN_BARS),
        "bars": len(returns),
        "garch": {
            "last_sigma": round(float(garch.get("last_sigma") or 0.0), 8),
            "unconditional": round(float(garch.get("unconditional") or 0.0), 8),
            "alpha": GARCH_ALPHA,
            "beta": GARCH_BETA,
        },
        "hmm": {
            "last_state": str(hmm.get("last_state") or "UNKNOWN"),
            "p_high": round(float(hmm.get("p_high") or 0.0), 4),
            "state_persistence": float(hmm.get("state_persistence") or 0.0),
            "method": hmm["method"],
        },
        "size_scale": round(scale, 4),
        "note": "Size follows vol regime. Direction is not treated as the edge.",
        "mode": "PAPER_ONLY",
    }
