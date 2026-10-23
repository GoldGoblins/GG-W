"""Port of freqtrade-strategies Strategy004 (Gerald Lonlas).

Source: https://github.com/freqtrade/freqtrade-strategies
File: user_data/strategies/Strategy004.py
License of upstream: GPL-3.0 (freqtrade). Rules only — no freqtrade runtime.

Buy (all of):
  (ADX>50 OR slowADX>26) AND CCI<-100
  AND prev fast stoch K,D < 20 AND prev slow stoch K,D < 30
  AND fast K crosses above D AND volume SMA12 > 0.75
Sell (all of):
  slowADX<25 AND (fastK>70 OR fastD>70)
  AND prev K < prev D AND close > EMA5

Local extra (not in 004): 4-stoch overlay + RSI/MACD/BB notes for the rail.
"""
from __future__ import annotations

from typing import Any

from backend.crypto_indicators import ema, last, last2, macd, rsi, stochastic


def _wilder(values: list[float], period: int) -> list[float | None]:
    n = int(period)
    out: list[float | None] = [None] * len(values)
    if len(values) < n or n <= 0:
        return out
    total = sum(values[:n])
    out[n - 1] = total
    for i in range(n, len(values)):
        total = total - (total / n) + values[i]
        out[i] = total
    return out


def adx(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    n = int(period)
    size = len(closes)
    tr: list[float] = [0.0] * size
    plus_dm: list[float] = [0.0] * size
    minus_dm: list[float] = [0.0] * size
    for i in range(1, size):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = _wilder(tr, n)
    sm_plus = _wilder(plus_dm, n)
    sm_minus = _wilder(minus_dm, n)
    dx: list[float] = [0.0] * size
    for i in range(size):
        a = atr[i]
        if a is None or a == 0:
            continue
        pdi = 100.0 * (sm_plus[i] or 0.0) / a
        mdi = 100.0 * (sm_minus[i] or 0.0) / a
        denom = pdi + mdi
        dx[i] = 0.0 if denom == 0 else 100.0 * abs(pdi - mdi) / denom
    smoothed = _wilder(dx, n)
    out: list[float | None] = [None] * size
    for i, value in enumerate(smoothed):
        if value is None:
            continue
        out[i] = value / n
    return out


def cci(
    highs: list[float], lows: list[float], closes: list[float], period: int = 20
) -> list[float | None]:
    n = int(period)
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    out: list[float | None] = [None] * len(tp)
    for i in range(n - 1, len(tp)):
        window = tp[i + 1 - n : i + 1]
        mean = sum(window) / n
        dev = sum(abs(x - mean) for x in window) / n
        if dev == 0:
            out[i] = 0.0
        else:
            out[i] = (tp[i] - mean) / (0.015 * dev)
    return out


def _sma_last(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def evaluate(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float] | None = None,
) -> dict[str, Any]:
    if len(closes) < 80:
        raise ValueError("CRYPTO_CANDLES")
    vols = volumes if volumes is not None else [1.0] * len(closes)
    adx14 = adx(highs, lows, closes, 14)
    adx35 = adx(highs, lows, closes, 35)
    cci20 = cci(highs, lows, closes, 20)
    from backend.crypto_indicators import sma

    def raw_k(period: int) -> list[float | None]:
        n = int(period)
        out: list[float | None] = []
        for i, close in enumerate(closes):
            if i + 1 < n:
                out.append(None)
                continue
            hi = max(highs[i + 1 - n : i + 1])
            lo = min(lows[i + 1 - n : i + 1])
            if hi == lo:
                out.append(50.0)
            else:
                out.append(100.0 * (close - lo) / (hi - lo))
        return out

    fastk = raw_k(5)
    fastd = sma([0.0 if x is None else x for x in fastk], 3)
    slowk = raw_k(50)
    slowd = sma([0.0 if x is None else x for x in slowk], 3)
    ema5 = ema(closes, 5)
    mean_vol = _sma_last(vols, 12)
    rsi14 = last(rsi(closes, 14))
    _, _, hist = macd(closes)
    hist_now, hist_prev = last2(hist)

    def at(series: list[float | None], offset: int) -> float | None:
        idx = len(series) - 1 - offset
        if idx < 0:
            return None
        return series[idx]

    fk = at(fastk, 0)
    fd = at(fastd, 0)
    fkp = at(fastk, 1)
    fdp = at(fastd, 1)
    skp = at(slowk, 1)
    sdp = at(slowd, 1)
    a14 = at(adx14, 0)
    a35 = at(adx35, 0)
    cci_now = at(cci20, 0)
    e5 = at(ema5, 0)
    close = closes[-1]
    notes: list[str] = []
    buy = False
    sell = False
    if (
        a14 is not None
        and a35 is not None
        and cci_now is not None
        and fkp is not None
        and fdp is not None
        and skp is not None
        and sdp is not None
        and fk is not None
        and fd is not None
        and mean_vol is not None
    ):
        trend = a14 > 50 or a35 > 26
        if (
            trend
            and cci_now < -100
            and fkp < 20
            and fdp < 20
            and skp < 30
            and sdp < 30
            and fkp < fdp
            and fk > fd
            and mean_vol > 0.75
            and close > 0.000001
        ):
            buy = True
            notes.append("Strategy004 enter_long")
        if (
            a35 < 25
            and (fk > 70 or fd > 70)
            and fkp < fdp
            and e5 is not None
            and close > e5
        ):
            sell = True
            notes.append("Strategy004 exit_long")
    extra = []
    stoch_os = 0
    for period in (5, 14, 21, 55):
        k = last(stochastic(highs, lows, closes, period, 3))
        if k is not None and k <= 20:
            stoch_os += 1
    if stoch_os >= 3:
        extra.append("4x-stoch overlay oversold")
    if rsi14 is not None and rsi14 <= 30:
        extra.append("RSI overlay oversold")
    if hist_now is not None and hist_prev is not None and hist_prev <= 0 < hist_now:
        extra.append("MACD overlay up")
    notes.extend(extra)
    side = "none"
    if buy and not sell:
        side = "buy"
    elif sell and not buy:
        side = "sell"
    return {
        "strategy": "Strategy004",
        "source": "freqtrade-strategies",
        "close": close,
        "adx": a14,
        "slowadx": a35,
        "cci": cci_now,
        "fastk": fk,
        "fastd": fd,
        "rsi14": rsi14,
        "macd_hist": hist_now,
        "mean_volume": mean_vol,
        "buy_votes": 1 if buy else 0,
        "sell_votes": 1 if sell else 0,
        "notes": notes,
        "super": side,
    }
