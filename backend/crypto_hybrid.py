"""Hybrid paper book for the existing CRYPTO surface.

This is deliberately a local paper/backtest adapter, not a Hummingbot process.
It keeps the useful separation from Hummingbot's V2 design:

* the current GG multi-timeframe vote produces the market intent;
* TimesFM supplies a bounded forecast and uncertainty gate;
* a small position executor owns the triple-barrier exit rules.

The TimesFM dependency is optional at runtime.  If the downloaded CPU runtime
is unavailable, the same walk-forward path uses a deterministic log-drift
fallback and reports that fact.  No network, wallet, connector, or mainnet
operation belongs in this module.
"""
from __future__ import annotations

import dataclasses
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from backend import crypto_trader, crypto_backtest
from backend.crypto_indicators import rsi, stoch_kd
from backend.crypto_trader import (
    BAR_SEC,
    MAX_TRADES_DAY,
    SOL_SCALE,
    START_SOL,
    START_USD,
    STOCH_STACK,
    USD_SCALE,
    _backtest_chart,
    _day_book,
    _price_atoms,
    _trade_stats,
    _walk_primary,
    confluence_vote,
    format_units,
    regime_series,
    save_backtest,
    signal_series,
)


ForecastProvider = Callable[[list[float], int], dict[str, Any]]
SignalProvider = Callable[[int, float], dict[str, Any]]


@dataclasses.dataclass(frozen=True)
class HybridConfig:
    """Paper risk and forecast settings.

    Values are intentionally conservative and explicit so the same settings
    can later be reviewed before any separate testnet adapter is considered.
    """

    context_bars: int = 256
    forecast_horizon: int = 12
    forecast_stride: int = 24
    max_forecast_calls: int = 128
    max_forecast_age_bars: int = 48
    entry_edge_bps: int = 300
    exit_edge_bps: int = 40
    min_forecast_q10_edge_bps: int = 100
    max_forecast_band_bps: int = 1200
    stop_loss_bps: int = 800
    take_profit_bps: int = 1200
    time_limit_bars: int = 48
    trailing_activation_bps: int = 600
    trailing_delta_bps: int = 300
    max_trades_day: int = 12
    cooldown_bars: int = 24
    min_quote_usd: int = 5 * USD_SCALE
    position_bps: int = 2500
    initial_position_bps: int = 0
    core_position_bps: int = 0
    block_trend_down: bool = True
    use_timesfm: bool = True

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _positive_prices(values: list[float]) -> list[float]:
    return [max(1e-12, _finite(value, 1.0)) for value in values if _finite(value) > 0]


def naive_forecast(closes: list[float], horizon: int = 12) -> dict[str, Any]:
    """Deterministic fallback with a volatility band, in price space."""
    prices = _positive_prices(closes)
    if not prices:
        return {"model": "naive", "point": 0.0, "q10": 0.0, "q90": 0.0}
    steps = max(1, int(horizon))
    logs = [math.log(value) for value in prices]
    returns = [logs[i] - logs[i - 1] for i in range(1, len(logs))]
    sample = returns[-48:] or [0.0]
    drift = sum(sample) / len(sample)
    variance = sum((value - drift) ** 2 for value in sample) / len(sample)
    sigma = math.sqrt(max(0.0, variance))
    last = logs[-1]
    point = math.exp(last + drift * steps)
    spread = 1.2816 * sigma * math.sqrt(steps)
    return {
        "model": "naive",
        "point": point,
        "q10": math.exp(last + drift * steps - spread),
        "q90": math.exp(last + drift * steps + spread),
    }


def _normalise_forecast(raw: Any, fallback_last: float) -> dict[str, Any]:
    """Accept an injected provider or TimesFM output and return price values."""
    if not isinstance(raw, dict):
        return naive_forecast([fallback_last], 1)
    point = _finite(raw.get("point"), 0.0)
    q10 = _finite(raw.get("q10"), point)
    q90 = _finite(raw.get("q90"), point)
    if point <= 0:
        point = max(1e-12, fallback_last)
    if q10 <= 0:
        q10 = point
    if q90 <= 0:
        q90 = point
    return {
        "model": str(raw.get("model") or "provider"),
        "point": point,
        "q10": min(q10, q90),
        "q90": max(q10, q90),
    }


def _add_timesfm_paths() -> None:
    """Use installed packages or explicitly configured source paths."""
    for key in ("GG_TIMESFM_SITEPACKAGES", "GG_TIMESFM_SOURCE"):
        candidate = os.environ.get(key, "")
        if candidate and Path(candidate).is_dir() and candidate not in sys.path:
            sys.path.insert(0, candidate)


def _timesfm_provider(config: HybridConfig) -> tuple[Any, str, str]:
    """Load TimesFM 3 from the local cache only; never fetch from the app."""
    global _TIMESFM_PROVIDER, _TIMESFM_INIT_ERROR
    if not config.use_timesfm:
        return None, "disabled", "GG_TIMESFM_OFF"
    if os.environ.get("GG_TIMESFM_ALLOW_NONCOMMERCIAL_RESEARCH") != "1":
        return None, "naive-fallback", "TIMESFM3_NONCOMMERCIAL_RESEARCH_OPT_IN_REQUIRED"
    if _TIMESFM_PROVIDER is not None:
        return _TIMESFM_PROVIDER, "timesfm3", _TIMESFM_INIT_ERROR
    if _TIMESFM_INIT_ERROR:
        return None, "naive-fallback", _TIMESFM_INIT_ERROR
    try:
        _add_timesfm_paths()
        import numpy as np
        from timesfm3 import ModelConfig, TimesFM3Evaluator

        cache_dir = os.environ.get("GG_TIMESFM_CACHE", str(Path.home() / ".cache/goldgoblins/timesfm"))
        model_config = ModelConfig(
            checkpoint_path="google/timesfm-3.0-pytorch",
            per_core_batch_size=1,
            device="cpu",
            cache_dir=cache_dir,
            local_files_only=True,
        )
        model = TimesFM3Evaluator(model_config)

        def provider(history: list[float], horizon: int) -> dict[str, Any]:
            prices = _positive_prices(history)
            if len(prices) < 8:
                return naive_forecast(prices, horizon)
            context = np.asarray([math.log(value) for value in prices], dtype=np.float32)
            result = list(
                model.predict_batch(
                    [context],
                    horizon=max(1, int(horizon)),
                    return_quantiles=True,
                    use_symmetric_averaging=False,
                )
            )[0]
            point_values = np.asarray(result.forecast).reshape(-1)
            if point_values.size == 0:
                raise ValueError("TIMESFM_EMPTY")
            point_log = float(point_values[-1])
            quantiles = np.asarray(result.quantiles) if result.quantiles is not None else None
            if quantiles is not None and quantiles.size:
                row = quantiles.reshape((-1, quantiles.shape[-1]))[-1]
                q10_log = float(row[0])
                q90_log = float(row[-1])
            else:
                q10_log = point_log
                q90_log = point_log
            return {
                "model": "timesfm3",
                "point": math.exp(point_log),
                "q10": math.exp(q10_log),
                "q90": math.exp(q90_log),
            }

        _TIMESFM_PROVIDER = provider
        return provider, "timesfm3", ""
    except Exception as exc:  # optional runtime: paper path must remain usable
        _TIMESFM_INIT_ERROR = str(exc)[:240] or "TIMESFM_UNAVAILABLE"
        return None, "naive-fallback", _TIMESFM_INIT_ERROR


class _ForecastEngine:
    def __init__(self, config: HybridConfig, injected: ForecastProvider | None = None):
        self.config = config
        self.provider: Any = injected
        self.model = "injected" if injected is not None else ""
        self.error = ""
        self.calls = 0
        self.actual_calls = 0
        self.fallback_calls = 0
        if injected is None:
            self.provider, self.model, self.error = _timesfm_provider(config)

    def forecast(self, history: list[float]) -> dict[str, Any]:
        self.calls += 1
        last = _positive_prices(history)[-1] if _positive_prices(history) else 0.0
        if self.provider is not None:
            try:
                result = _normalise_forecast(
                    self.provider(history, self.config.forecast_horizon), last
                )
                self.actual_calls += 1
                return result
            except Exception as exc:  # switch once to deterministic safe fallback
                if not self.error:
                    self.error = str(exc)[:240] or "TIMESFM_FORECAST_FAILED"
                self.provider = None
                self.model = "naive-fallback"
        self.fallback_calls += 1
        return naive_forecast(history, self.config.forecast_horizon)


@dataclasses.dataclass
class PaperPositionExecutor:
    """Minimal long-only triple-barrier executor used by the backtester."""

    entry_i: int
    entry_ts: int
    entry_px: float
    config: HybridConfig
    peak_px: float = 0.0

    def __post_init__(self) -> None:
        if self.peak_px <= 0:
            self.peak_px = float(self.entry_px)

    def check(
        self, i: int, high: float, low: float, close: float, open_price: float | None = None
    ) -> tuple[str, float] | None:
        if i <= self.entry_i:
            return None
        entry = max(1e-12, float(self.entry_px))
        stop = entry * (1.0 - self.config.stop_loss_bps / 10_000.0)
        take = entry * (1.0 + self.config.take_profit_bps / 10_000.0)
        if low <= stop:
            gap = open_price if open_price is not None and low <= open_price <= high else close
            return "stop_loss", min(stop, gap) if high < stop or (open_price is not None and gap < stop) else stop
        if high >= take:
            return "take_profit", take
        activation = entry * (1.0 + self.config.trailing_activation_bps / 10_000.0)
        if self.peak_px >= activation:
            trail = self.peak_px * (1.0 - self.config.trailing_delta_bps / 10_000.0)
            if low <= trail:
                gap = open_price if open_price is not None and low <= open_price <= high else close
                return "trailing_stop", min(trail, gap) if high < trail or (open_price is not None and gap < trail) else trail
        if high >= activation:
            self.peak_px = max(self.peak_px, float(high))
        if i - self.entry_i >= self.config.time_limit_bars:
            return "time_limit", max(1e-12, float(close))
        return None


def _prepare_mtf(frames: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tf_rsi: dict[str, list[float | None]] = {}
    tf_stoch: dict[str, list[float | None]] = {}
    tf_stack: dict[str, list[list[float | None]]] = {}
    tf_times: dict[str, list[int]] = {}
    tf_sig: dict[str, list[str]] = {}
    tf_reg: dict[str, list[str]] = {}
    for name, raw in frames.items():
        closes = [float(x) for x in (raw.get("closes") or [])]
        highs = [float(x) for x in (raw.get("highs") or [])]
        lows = [float(x) for x in (raw.get("lows") or [])]
        n = min(len(highs), len(lows), len(closes))
        if n < 2:
            continue
        highs, lows, closes = highs[:n], lows[:n], closes[:n]
        volumes = [float(x) for x in (raw.get("volumes") or [])][:n]
        if len(volumes) < n:
            volumes.extend([1.0] * (n - len(volumes)))
        tf_rsi[name] = rsi(closes, 14)
        k14, _d14 = stoch_kd(highs, lows, closes, 14, 3, 3)
        tf_stoch[name] = k14
        stack: list[list[float | None]] = []
        for k_len, k_sm, d_sm, _use_vol in STOCH_STACK:
            kk, _dd = stoch_kd(highs, lows, closes, k_len, k_sm, d_sm)
            stack.append(kk)
        tf_stack[name] = stack
        tf_times[name] = [int(x) for x in (raw.get("times") or [])]
        tf_sig[name] = signal_series(highs, lows, closes, volumes)
        tf_reg[name] = regime_series(highs, lows, closes)
    return {
        "rsi": tf_rsi,
        "stoch": tf_stoch,
        "stack": tf_stack,
        "times": tf_times,
        "sig": tf_sig,
        "reg": tf_reg,
    }


def _local_vote(
    frames: dict[str, dict[str, Any]],
    prepared: dict[str, Any],
    primary: str,
    i: int,
    ts: int,
    close: float,
) -> dict[str, Any]:
    now = int(ts) + int(BAR_SEC.get(primary) or 3600)
    tf_osc, tf_super, tf_flow = crypto_trader._snapshot_tfs(
        frames,
        prepared["rsi"],
        prepared["stoch"],
        prepared["stack"],
        prepared["times"],
        prepared["sig"],
        prepared["reg"],
        now,
        primary,
        i,
        close,
    )
    return confluence_vote(tf_osc, tf_super, tf_flow)


def _forecast_indices(start: int, n: int, config: HybridConfig) -> set[int]:
    if n <= start:
        return set()
    stride = max(1, int(config.forecast_stride))
    max_calls = max(1, int(config.max_forecast_calls))
    # Extending history cannot move forecasts that were made in the past.
    return set(range(start, min(n, start + stride * max_calls), stride))


def _combined_signal(
    vote: dict[str, Any], forecast: dict[str, Any], price: float, config: HybridConfig
) -> dict[str, Any]:
    local = str(vote.get("side") or "none")
    flow = str(vote.get("flow") or "range")
    invalid = bool(vote.get("invalid"))
    px = max(1e-12, float(price))
    point = _finite(forecast.get("point"), px)
    q10 = _finite(forecast.get("q10"), point)
    q90 = _finite(forecast.get("q90"), point)
    edge_bps = (point / px - 1.0) * 10_000.0
    q10_edge_bps = (q10 / px - 1.0) * 10_000.0
    band_bps = max(0.0, q90 - q10) / px * 10_000.0
    uncertain = band_bps > config.max_forecast_band_bps
    try:
        forecast_age = int(forecast.get("_age_bars") or 0)
    except (TypeError, ValueError):
        forecast_age = 0
    forecast_fresh = forecast_age <= max(0, int(config.max_forecast_age_bars))
    blocked = bool(config.block_trend_down) and (flow == "trend_down" or invalid)
    forecast_buy = (
        edge_bps >= config.entry_edge_bps
        and q10_edge_bps >= config.min_forecast_q10_edge_bps
        and not uncertain
        and forecast_fresh
        and not blocked
    )
    forecast_sell = edge_bps <= -config.exit_edge_bps and forecast_fresh
    side = "none"
    if local == "buy" and forecast_buy:
        side = "buy"
    elif forecast_sell and (local in ("sell", "none")):
        side = "sell"
    return {
        "side": side,
        "local": local,
        "edge_bps": round(edge_bps, 1),
        "q10_edge_bps": round(q10_edge_bps, 1),
        "band_bps": round(band_bps, 1),
        "flow": flow,
        "forecast_age_bars": forecast_age,
        "forecast_fresh": forecast_fresh,
        "blocked": blocked,
        "reason": "local+forecast" if side != "none" else "gate",
    }


def run_backtest(
    frames: dict[str, dict[str, Any]],
    config: HybridConfig | None = None,
    persist: bool = True,
    forecast_provider: ForecastProvider | None = None,
    signal_provider: SignalProvider | None = None,
) -> dict[str, Any]:
    """Run the hybrid book without looking past the current candle."""
    cfg = config or HybridConfig()
    primary = _walk_primary(frames)
    src = frames[primary]
    highs = [float(x) for x in (src.get("highs") or [])]
    lows = [float(x) for x in (src.get("lows") or [])]
    closes = [float(x) for x in (src.get("closes") or [])]
    n = min(len(highs), len(lows), len(closes))
    if n < 80:
        raise RuntimeError("CRYPTO_HISTORY")
    highs, lows, closes = highs[:n], lows[:n], closes[:n]
    times = [int(x) for x in (src.get("times") or [])]
    if len(times) < n:
        bar_sec = int(BAR_SEC.get(primary) or 3600)
        times = [1_700_000_000 + i * bar_sec for i in range(n)]
    else:
        times = times[:n]

    begin = crypto_backtest.start_index(src)
    resume = crypto_backtest.restored("hybrid")
    bar_sec = int(BAR_SEC[primary])
    prepared = _prepare_mtf(frames)
    engine = _ForecastEngine(cfg, forecast_provider)
    forecast_at = _forecast_indices(80, n, cfg)
    latest_forecast = naive_forecast(closes[:begin + 1], cfg.forecast_horizon)
    last_forecast_i = begin - 1
    seed_i = begin
    seed_px = _price_atoms(closes[seed_i])
    if seed_px <= 0:
        raise RuntimeError("CRYPTO_PRICE")
    start_usd = int(START_USD)
    start_sol = start_usd * SOL_SCALE // seed_px or START_SOL
    core_bps = max(0, min(10_000, int(cfg.core_position_bps)))
    tactical_bps = max(0, min(10_000 - core_bps, int(cfg.initial_position_bps)))
    core_spend_usd = start_usd * core_bps // 10_000
    initial_tactical_spend_usd = start_usd * tactical_bps // 10_000
    initial_spend_usd = core_spend_usd + initial_tactical_spend_usd
    core_net_usd = core_spend_usd * (
        10_000 - crypto_backtest.EXECUTION_BPS
    ) // 10_000
    tactical_net_usd = initial_tactical_spend_usd * (
        10_000 - crypto_backtest.EXECUTION_BPS
    ) // 10_000
    core_sol = core_net_usd * SOL_SCALE // seed_px
    position_sol = tactical_net_usd * SOL_SCALE // seed_px
    cash_usd = start_usd - initial_spend_usd
    cost_usd = initial_tactical_spend_usd
    executor: PaperPositionExecutor | None = (
        PaperPositionExecutor(seed_i, times[seed_i], closes[seed_i], cfg)
        if position_sol > 0
        else None
    )
    lots: list[dict[str, Any]] = []
    equity: list[dict[str, Any]] = []
    accounting: list[dict[str, Any]] = []
    buys = 0
    sells = 0
    signal_buys = 0
    signal_sells = 0
    max_day = 0
    fills_today = 0
    day_hist: list[int] = []
    current_day = ""
    barrier_counts: dict[str, int] = {
        "stop_loss": 0,
        "take_profit": 0,
        "trailing_stop": 0,
        "time_limit": 0,
        "signal_flip": 0,
    }
    equity_step = max(1, n // 400)
    realized_pnl_usd = 0
    peak_equity_usd = start_usd
    min_equity_usd = start_usd
    max_drawdown_usd = 0
    max_position_usd = 0
    max_position_sol = 0
    max_forecast_age = 0
    cooldown_until_i = 0

    def record_mark(i: int, ts: int) -> None:
        nonlocal peak_equity_usd, min_equity_usd, max_drawdown_usd
        nonlocal max_position_usd, max_position_sol, max_forecast_age
        price_atoms = _price_atoms(closes[i])
        total_position_sol = core_sol + position_sol
        position_usd = total_position_sol * price_atoms // SOL_SCALE
        mark_usd = cash_usd + position_usd
        accounting.append({"ts": ts, "usd": mark_usd / USD_SCALE})
        peak_equity_usd = max(peak_equity_usd, mark_usd)
        min_equity_usd = min(min_equity_usd, mark_usd)
        max_drawdown_usd = max(max_drawdown_usd, peak_equity_usd - mark_usd)
        max_position_usd = max(max_position_usd, position_usd)
        max_position_sol = max(max_position_sol, total_position_sol)
        max_forecast_age = max(max_forecast_age, max(0, i - last_forecast_i))
        if i % equity_step == 0 or i == n - 1:
            total_sol = total_position_sol + cash_usd * SOL_SCALE // max(1, price_atoms)
            equity.append(
                {
                    "ts": ts,
                    "sol": total_sol / SOL_SCALE,
                    "usd": mark_usd / USD_SCALE,
                }
            )

    if resume:
        if resume["config"] != cfg.as_dict():
            raise ValueError("CRYPTO_PAPER_PARAMETERS_CHANGED")
        core_sol = resume["core_sol"]
        position_sol = resume["position_sol"]
        cash_usd = resume["cash_usd"]
        cost_usd = resume["cost_usd"]
        fills_today = resume["fills_today"]
        current_day = resume["current_day"]
        latest_forecast = resume["latest_forecast"]
        executor = crypto_backtest.executor_from(resume.get("executor"), times, bar_sec, cfg)
        cooldown_until_i = (int(resume["cooldown_until_ts"]) - times[0]) // bar_sec
        last_forecast_i = (int(resume["last_forecast_ts"]) - times[0]) // bar_sec
    start = n - 1 if resume else begin
    anchor_ts = int(resume.get("anchor_ts", times[begin]))
    for i in range(start, n):
        ts = int(times[i])
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        if current_day and day != current_day:
            day_hist.append(fills_today)
            fills_today = 0
        current_day = day
        forecast_due = i in forecast_at
        if crypto_backtest.STREAM.get():
            forecast_due = not resume or ((ts - anchor_ts) // bar_sec) % max(1, cfg.forecast_stride) == 0
        if forecast_due:
            left = max(0, i + 1 - max(8, cfg.context_bars))
            latest_forecast = engine.forecast(closes[left : i + 1])
            latest_forecast = dict(latest_forecast)
            latest_forecast["_age_bars"] = 0
            last_forecast_i = i
        else:
            latest_forecast = dict(latest_forecast)
            latest_forecast["_age_bars"] = max(0, i - last_forecast_i)
        vote = (
            signal_provider(i, closes[i])
            if signal_provider is not None
            else _local_vote(frames, prepared, primary, i, ts, closes[i])
        ) or {}
        signal = _combined_signal(vote, latest_forecast, closes[i], cfg)
        if signal["side"] == "buy":
            signal_buys += 1
        elif signal["side"] == "sell":
            signal_sells += 1

        if position_sol > 0 and executor is not None:
            barrier = executor.check(i, highs[i], lows[i], closes[i], (src.get("opens") or [None] * n)[i])
            if barrier is not None:
                reason, exit_px = barrier
            elif signal["side"] == "sell":
                reason, exit_px = "signal_flip", closes[i]
            else:
                reason, exit_px = "", 0.0
            if reason:
                exit_atoms = _price_atoms(exit_px)
                usd_net = (position_sol * exit_atoms // SOL_SCALE) * (
                    10_000 - crypto_backtest.EXECUTION_BPS
                ) // 10_000
                profit_usd = usd_net - cost_usd
                realized_pnl_usd += profit_usd
                lots.append(
                    {
                        "id": "hybrid-sell-" + str(ts),
                        "ts": ts,
                        "side": "sell",
                        "horizon": "hybrid",
                        "sol": position_sol,
                        "usd": usd_net,
                        "price": exit_atoms,
                        "profit_usd": profit_usd,
                        "profit_sol": profit_usd * SOL_SCALE // max(1, exit_atoms),
                        "venue": "hybrid-paper",
                        "barrier": reason,
                        "closes": True,
                        "closed": True,
                    }
                )
                barrier_counts[reason] = barrier_counts.get(reason, 0) + 1
                position_sol = 0
                cash_usd += usd_net
                cost_usd = 0
                executor = None
                sells += 1
                fills_today += 1
                max_day = max(max_day, fills_today)
                if profit_usd < 0:
                    cooldown_until_i = i + max(0, int(cfg.cooldown_bars))
                record_mark(i, ts)
                continue

        if (
            position_sol <= 0
            and signal["side"] == "buy"
            and cash_usd >= max(1, int(cfg.min_quote_usd))
            and i >= cooldown_until_i
            and fills_today < min(MAX_TRADES_DAY, max(1, cfg.max_trades_day))
        ):
            entry_atoms = _price_atoms(closes[i])
            equity_before = cash_usd + (
                core_sol + position_sol
            ) * entry_atoms // SOL_SCALE
            target_spend = equity_before * max(
                0, min(10_000, int(cfg.position_bps))
            ) // 10_000
            spend = min(cash_usd, target_spend)
            if spend < max(1, int(cfg.min_quote_usd)):
                spend = 0
            sol_got = (
                spend * (10_000 - crypto_backtest.EXECUTION_BPS) // 10_000
            ) * SOL_SCALE // max(1, entry_atoms)
            if sol_got > 0:
                spent = spend
                position_sol += sol_got
                cash_usd -= spent
                cost_usd = spent
                executor = PaperPositionExecutor(i, ts, closes[i], cfg)
                lots.append(
                    {
                        "id": "hybrid-buy-" + str(ts),
                        "ts": ts,
                        "side": "buy",
                        "horizon": "hybrid",
                        "sol": sol_got,
                        "usd": spent,
                        "price": entry_atoms,
                        "venue": "hybrid-paper",
                        "signal": signal.get("reason"),
                        "closed": True,
                    }
                )
                buys += 1
                fills_today += 1
                max_day = max(max_day, fills_today)

        record_mark(i, ts)

    if current_day:
        day_hist.append(fills_today)
    last_px = closes[-1]
    last_atoms = _price_atoms(last_px)
    cash_sol = cash_usd * SOL_SCALE // max(1, last_atoms)
    end_sol = core_sol + position_sol + cash_sol
    end_equity_usd = cash_usd + (core_sol + position_sol) * last_atoms // SOL_SCALE
    hold_end_usd = start_sol * last_atoms // SOL_SCALE
    stats = _trade_stats(
        lots,
        0,
        cash_usd,
        day_hist,
        sol_held=end_sol,
        last_close=last_px,
        start_sol=start_sol,
    )
    report: dict[str, Any] = {
        "accounting": accounting,
        "bars": n,
        "from": 80,
        "fills": buys + sells,
        "buys": buys,
        "sells": sells,
        "signals_buy": signal_buys,
        "signals_sell": signal_sells,
        "max_open": 1,
        "max_day_fills": max_day,
        "days": len(day_hist),
        "avg_fills_day": round(sum(day_hist) / len(day_hist), 2) if day_hist else 0.0,
        "days_in_band": sum(
            1
            for count in day_hist
            if int(cfg.max_trades_day) >= count >= 1
        ),
        "banked_sol": format_units(0, 9),
        "float_sol": format_units(core_sol + position_sol, 9),
        "core_sol": format_units(core_sol, 9),
        "tactical_sol": format_units(position_sol, 9),
        "cash_sol": format_units(cash_sol, 9),
        "tokens": format_units(end_sol, 9),
        "usd": format_units(cash_usd, 6),
        "banked_never_fell": True,
        "banked_grew": False,
        "lots": lots[-24:],
        "seeded": True,
        "book": "hybrid",
        "mode": "PAPER",
        "network": "testnet",
        "primary": primary,
        "range": "+".join(name for name in crypto_trader.TIMEFRAMES if name in frames),
        "note": (
            "Paper only: GG MTF confluence + TimesFM forecast gate + "
            "Hummingbot-style triple barrier. No connector, wallet, or mainnet."
        ),
        "params": cfg.as_dict(),
        "triple_barrier": {
            "stop_loss_bps": cfg.stop_loss_bps,
            "take_profit_bps": cfg.take_profit_bps,
            "time_limit_bars": cfg.time_limit_bars,
            "trailing_activation_bps": cfg.trailing_activation_bps,
            "trailing_delta_bps": cfg.trailing_delta_bps,
        },
        "barriers": barrier_counts,
        "forecast_model": engine.model or "naive-fallback",
        "timesfm_calls": engine.calls,
        "timesfm_actual_calls": engine.actual_calls,
        "timesfm_fallback_calls": engine.fallback_calls,
        "timesfm_error": engine.error,
        "timesfm_license": "TimesFM 3 requires explicit noncommercial research opt-in; local models only, no automatic download.",
        "start_sol": format_units(start_sol, 9),
        "day_book": _day_book(lots),
        "chart": _backtest_chart(
            frames, lots, closes, times, primary, equity=equity
        ),
    }
    report.update(stats)
    sell_lots = [row for row in lots if row.get("side") == "sell"]

    def quote_trade_view(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "side": row.get("side"),
            "profit": format_units(int(row.get("profit_usd") or 0), 6),
            "currency": "USD",
            "sol": format_units(row.get("sol"), 9),
            "ts": row.get("ts"),
        }

    quote_best = max(
        sell_lots, key=lambda row: int(row.get("profit_usd") or 0), default=None
    )
    quote_worst = min(
        sell_lots, key=lambda row: int(row.get("profit_usd") or 0), default=None
    )
    quote_return = (end_equity_usd / start_usd - 1.0) * 100.0 if start_usd else 0.0
    if quote_return >= 50.0 and float(stats.get("win_rate") or 0.0) >= 55.0:
        quote_verdict = "GOOD"
    elif quote_return > 0.0 and float(stats.get("win_rate") or 0.0) >= 50.0:
        quote_verdict = "MIXED"
    else:
        quote_verdict = "WEAK"
    report.update(
        {
            "verdict": quote_verdict,
            "quote_currency": "USD",
            "start_usd": format_units(start_usd, 6),
            "end_usd": format_units(end_equity_usd, 6),
            "pnl_usd": format_units(end_equity_usd - start_usd, 6),
            "realized_pnl_usd": format_units(realized_pnl_usd, 6),
            "return_pct": round(quote_return, 2),
            "min_equity_usd": format_units(min_equity_usd, 6),
            "max_drawdown_usd": format_units(max_drawdown_usd, 6),
            "max_drawdown_pct": round(
                max_drawdown_usd * 100.0 / max(1, peak_equity_usd), 2
            ),
            "max_position_usd": format_units(max_position_usd, 6),
            "max_position_pct": round(
                max_position_usd * 100.0 / max(1, peak_equity_usd), 2
            ),
            "max_position_sol": format_units(max_position_sol, 9),
            "initial_position_usd": format_units(initial_spend_usd, 6),
            "core_position_usd": format_units(core_spend_usd, 6),
            "initial_tactical_position_usd": format_units(
                initial_tactical_spend_usd, 6
            ),
            "benchmark_hold_end_usd": format_units(hold_end_usd, 6),
            "benchmark_hold_pnl_usd": format_units(hold_end_usd - start_usd, 6),
            "max_forecast_age_bars": max_forecast_age,
            "best_trade": quote_trade_view(quote_best),
            "worst_trade": quote_trade_view(quote_worst),
            "avg_pnl_usd": format_units(
                realized_pnl_usd // max(1, len(sell_lots)), 6
            ),
        }
    )
    if persist:
        save_backtest(report)
    crypto_backtest.checkpoint(report, "hybrid", {"config": cfg.as_dict(), "anchor_ts": anchor_ts,
        "executor": crypto_backtest.executor_state(executor),
        "cooldown_until_ts": times[0] + cooldown_until_i * bar_sec,
        "last_forecast_ts": times[0] + last_forecast_i * bar_sec,
        "core_sol": core_sol,
        "position_sol": position_sol,
        "cash_usd": cash_usd,
        "cost_usd": cost_usd,
        "fills_today": fills_today,
        "current_day": current_day,
        "latest_forecast": latest_forecast}, lots, core_sol + position_sol, cash_usd)
    return report
