from __future__ import annotations

from typing import Any


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    n = int(period)
    if n <= 0:
        raise ValueError("CRYPTO_PERIOD")
    acc = 0.0
    for i, value in enumerate(values):
        acc += value
        if i >= n:
            acc -= values[i - n]
        if i + 1 < n:
            out.append(None)
        else:
            out.append(acc / n)
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    n = int(period)
    if n <= 0:
        raise ValueError("CRYPTO_PERIOD")
    out: list[float | None] = [None] * len(values)
    if len(values) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    n = int(period)
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / n
    avg_loss = losses / n
    if avg_loss == 0:
        out[n] = 100.0
    else:
        out[n] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(n + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return out


def stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
    k_smooth: int = 3,
) -> list[float | None]:
    k, _d = stoch_kd(highs, lows, closes, period, k_smooth, k_smooth)
    return k


def stoch_kd(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    k_length: int,
    k_smooth: int,
    d_smooth: int,
) -> tuple[list[float | None], list[float | None]]:
    """%K length, %K smoothing, %D smoothing (TradingView Stochastic)."""
    n = int(k_length)
    raw: list[float | None] = []
    size = min(len(highs), len(lows), len(closes))
    for i in range(size):
        if i + 1 < n:
            raw.append(None)
            continue
        window_h = highs[i + 1 - n : i + 1]
        window_l = lows[i + 1 - n : i + 1]
        hi = max(window_h)
        lo = min(window_l)
        close = closes[i]
        if hi == lo:
            raw.append(50.0)
        else:
            raw.append(100.0 * (close - lo) / (hi - lo))
    filled = [0.0 if x is None else x for x in raw]
    k_sma = sma(filled, max(1, int(k_smooth)))
    k: list[float | None] = []
    for i, value in enumerate(k_sma):
        if raw[i] is None or value is None:
            k.append(None)
        else:
            k.append(value)
    d_src = [0.0 if x is None else x for x in k]
    d_sma = sma(d_src, max(1, int(d_smooth)))
    d: list[float | None] = []
    for i, value in enumerate(d_sma):
        if k[i] is None or value is None:
            d.append(None)
        else:
            d.append(value)
    return k, d


def stoch_rsi(closes: list[float], rsi_period: int = 14, stoch_period: int = 14) -> list[float | None]:
    series = rsi(closes, rsi_period)
    numeric = [x if x is not None else 50.0 for x in series]
    dummy = numeric[:]
    return stochastic(dummy, dummy, numeric, stoch_period, 3)


def macd(closes: list[float]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    line: list[float | None] = []
    for a, b in zip(fast, slow):
        if a is None or b is None:
            line.append(None)
        else:
            line.append(a - b)
    numeric = [0.0 if x is None else x for x in line]
    signal = ema(numeric, 9)
    hist: list[float | None] = []
    for a, b in zip(line, signal):
        if a is None or b is None:
            hist.append(None)
        else:
            hist.append(a - b)
    return line, signal, hist


def bollinger(
    closes: list[float], period: int = 14, width: float = 2.0, offset: int = 0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    mid = sma(closes, period)
    upper: list[float | None] = []
    lower: list[float | None] = []
    n = int(period)
    for i, mean in enumerate(mid):
        if mean is None:
            upper.append(None)
            lower.append(None)
            continue
        window = closes[i + 1 - n : i + 1]
        var = sum((x - mean) ** 2 for x in window) / n
        std = var ** 0.5
        upper.append(mean + width * std)
        lower.append(mean - width * std)
    shift = int(offset)
    if shift == 0:
        return upper, mid, lower
    def _shift(series: list[float | None]) -> list[float | None]:
        if shift > 0:
            return [None] * shift + series[:-shift]
        return series[-shift:] + [None] * (-shift)
    return _shift(upper), _shift(list(mid)), _shift(lower)


def bb_percent(
    closes: list[float], period: int = 14, width: float = 2.0
) -> list[float | None]:
    upper, _mid, lower = bollinger(closes, period, width, 0)
    out: list[float | None] = []
    for close, up, lo in zip(closes, upper, lower):
        if up is None or lo is None or up == lo:
            out.append(None)
        else:
            pct = 100.0 * (close - lo) / (up - lo)
            out.append(max(0.0, min(100.0, pct)))
    return out


def williams_osc(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    """Williams %R mapped to 0–100 (100 = overbought, same band as RSI)."""
    n = int(period)
    out: list[float | None] = [None] * len(closes)
    size = min(len(highs), len(lows), len(closes))
    for i in range(n - 1, size):
        hi = max(highs[i + 1 - n : i + 1])
        lo = min(lows[i + 1 - n : i + 1])
        if hi == lo:
            out[i] = 50.0
        else:
            out[i] = 100.0 * (closes[i] - lo) / (hi - lo)
    return out


def cci_osc(
    highs: list[float], lows: list[float], closes: list[float], period: int = 20
) -> list[float | None]:
    """CCI mapped onto 0–100. CCI −100 ≈ 25, +100 ≈ 75."""
    n = int(period)
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    out: list[float | None] = [None] * len(tp)
    for i in range(n - 1, len(tp)):
        window = tp[i + 1 - n : i + 1]
        mean = sum(window) / n
        dev = sum(abs(x - mean) for x in window) / n
        if dev == 0:
            cci = 0.0
        else:
            cci = (tp[i] - mean) / (0.015 * dev)
        out[i] = max(0.0, min(100.0, 50.0 + cci / 4.0))
    return out


def mfi(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    period: int = 14,
) -> list[float | None]:
    """Money Flow Index, 0–100."""
    n = int(period)
    size = min(len(highs), len(lows), len(closes), len(volumes))
    out: list[float | None] = [None] * size
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(size)]
    pos = [0.0] * size
    neg = [0.0] * size
    for i in range(1, size):
        flow = tp[i] * volumes[i]
        if tp[i] > tp[i - 1]:
            pos[i] = flow
        elif tp[i] < tp[i - 1]:
            neg[i] = flow
    for i in range(n, size):
        p = sum(pos[i + 1 - n : i + 1])
        q = sum(neg[i + 1 - n : i + 1])
        if q == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - (100.0 / (1.0 + p / q))
    return out


def _clamp100(value: float) -> float:
    return max(0.0, min(100.0, value))


def _true_range(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[float]:
    n = min(len(highs), len(lows), len(closes))
    tr = [0.0] * n
    if n == 0:
        return tr
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    return tr


def _synth_opens(closes: list[float], opens: list[float] | None) -> list[float]:
    if opens is not None and len(opens) >= len(closes):
        return list(opens[: len(closes)])
    if not closes:
        return []
    return [closes[0]] + list(closes[:-1])


def ultimate_osc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    short: int = 7,
    mid: int = 14,
    long: int = 28,
) -> list[float | None]:
    """Larry Williams Ultimate Oscillator, 0–100."""
    n = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * n
    if n < long + 1:
        return out
    bp = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        prev = closes[i - 1]
        floor = min(lows[i], prev)
        ceil = max(highs[i], prev)
        bp[i] = closes[i] - floor
        tr[i] = max(0.0, ceil - floor)
    for i in range(long, n):
        def _avg(span: int) -> float:
            b = sum(bp[i - span + 1 : i + 1])
            t = sum(tr[i - span + 1 : i + 1])
            return 0.0 if t == 0 else b / t

        out[i] = _clamp100(
            100.0 * (4.0 * _avg(short) + 2.0 * _avg(mid) + _avg(long)) / 7.0
        )
    return out


def cmo_osc(closes: list[float], period: int = 14) -> list[float | None]:
    """Chande Momentum mapped from −100..100 onto 0–100."""
    n = int(period)
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    for i in range(n, len(closes)):
        up = 0.0
        down = 0.0
        for j in range(i - n + 1, i + 1):
            delta = closes[j] - closes[j - 1]
            if delta > 0:
                up += delta
            else:
                down -= delta
        denom = up + down
        cmo = 0.0 if denom == 0 else 100.0 * (up - down) / denom
        out[i] = _clamp100((cmo + 100.0) / 2.0)
    return out


def cmf_osc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
    period: int = 20,
) -> list[float | None]:
    """Chaikin Money Flow mapped from −1..1 onto 0–100."""
    n = int(period)
    size = min(len(highs), len(lows), len(closes), len(volumes))
    out: list[float | None] = [None] * size
    mfv = [0.0] * size
    for i in range(size):
        span = highs[i] - lows[i]
        if span == 0:
            mfv[i] = 0.0
        else:
            mfv[i] = (((closes[i] - lows[i]) - (highs[i] - closes[i])) / span) * volumes[i]
    for i in range(n - 1, size):
        vol = sum(volumes[i + 1 - n : i + 1])
        if vol == 0:
            out[i] = 50.0
        else:
            out[i] = _clamp100(50.0 * (1.0 + sum(mfv[i + 1 - n : i + 1]) / vol))
    return out


def aroon_osc(
    highs: list[float], lows: list[float], period: int = 25
) -> list[float | None]:
    """Aroon oscillator mapped to 0–100 (50 = balanced, 100 = strong up)."""
    n = int(period)
    size = min(len(highs), len(lows))
    out: list[float | None] = [None] * size
    for i in range(n, size):
        window_h = highs[i - n + 1 : i + 1]
        window_l = lows[i - n + 1 : i + 1]
        since_hi = n - 1 - max(range(n), key=lambda k: window_h[k])
        since_lo = n - 1 - min(range(n), key=lambda k: window_l[k])
        up = 100.0 * (n - since_hi) / n
        down = 100.0 * (n - since_lo) / n
        out[i] = _clamp100(50.0 + (up - down) / 2.0)
    return out


def keltner_percent(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 20,
    width: float = 1.5,
) -> list[float | None]:
    mid = ema(closes, period)
    tr = _true_range(highs, lows, closes)
    atr = ema(tr, period)
    out: list[float | None] = [None] * len(closes)
    for i, mean in enumerate(mid):
        a = atr[i] if i < len(atr) else None
        if mean is None or a is None:
            continue
        up = mean + width * a
        lo = mean - width * a
        if up == lo:
            out[i] = 50.0
        else:
            out[i] = _clamp100(100.0 * (closes[i] - lo) / (up - lo))
    return out


def donchian_percent(
    highs: list[float], lows: list[float], closes: list[float], period: int = 20
) -> list[float | None]:
    n = int(period)
    size = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * size
    for i in range(n - 1, size):
        hi = max(highs[i + 1 - n : i + 1])
        lo = min(lows[i + 1 - n : i + 1])
        if hi == lo:
            out[i] = 50.0
        else:
            out[i] = _clamp100(100.0 * (closes[i] - lo) / (hi - lo))
    return out


def schaff_trend(closes: list[float], cycle: int = 10) -> list[float | None]:
    """Schaff Trend Cycle on MACD, 0–100."""
    line, _sig, _hist = macd(closes)
    numeric = [0.0 if x is None else x for x in line]
    n = int(cycle)
    size = len(closes)
    out: list[float | None] = [None] * size
    if size < 40 or n <= 1:
        return out
    stoch1: list[float] = [50.0] * size
    for i in range(n - 1, size):
        window = numeric[i + 1 - n : i + 1]
        lo = min(window)
        hi = max(window)
        stoch1[i] = 50.0 if hi == lo else 100.0 * (numeric[i] - lo) / (hi - lo)
    pf = ema(stoch1, n)
    filled = [50.0 if x is None else x for x in pf]
    stoch2: list[float] = [50.0] * size
    for i in range(n - 1, size):
        window = filled[i + 1 - n : i + 1]
        lo = min(window)
        hi = max(window)
        stoch2[i] = 50.0 if hi == lo else 100.0 * (filled[i] - lo) / (hi - lo)
    stc = ema(stoch2, n)
    for i, value in enumerate(stc):
        if i < 35 or value is None:
            continue
        out[i] = _clamp100(value)
    return out


def ichimoku_osc(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[float | None]:
    """Close vs cloud/tenkan/kijun as 0–100. >50 = above structure."""
    size = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * size

    def _mid(left: int, right: int, period: int) -> float | None:
        if right - period + 1 < left:
            return None
        return (
            max(highs[right - period + 1 : right + 1])
            + min(lows[right - period + 1 : right + 1])
        ) / 2.0

    for i in range(51, size):
        tenkan = _mid(0, i, 9)
        kijun = _mid(0, i, 26)
        span_b = _mid(0, i, 52)
        if tenkan is None or kijun is None or span_b is None:
            continue
        span_a = (tenkan + kijun) / 2.0
        cloud_hi = max(span_a, span_b)
        cloud_lo = min(span_a, span_b)
        score = 50.0
        if closes[i] > cloud_hi:
            score += 20.0
        elif closes[i] < cloud_lo:
            score -= 20.0
        if tenkan > kijun:
            score += 15.0
        elif tenkan < kijun:
            score -= 15.0
        if closes[i] > tenkan:
            score += 10.0
        elif closes[i] < tenkan:
            score -= 10.0
        out[i] = _clamp100(score)
    return out


def supertrend_osc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 10,
    mult: float = 3.0,
) -> list[float | None]:
    """Supertrend as 0–100: 80 in uptrend, 20 in downtrend."""
    n = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * n
    if n < period + 2:
        return out
    tr = _true_range(highs, lows, closes)
    atr = ema(tr, period)
    upper = 0.0
    lower = 0.0
    trend = 1
    for i in range(period, n):
        a = atr[i]
        if a is None:
            continue
        mid = (highs[i] + lows[i]) / 2.0
        bu = mid + mult * a
        bl = mid - mult * a
        if i == period:
            upper, lower, trend = bu, bl, 1 if closes[i] >= mid else -1
        else:
            upper = bu if bu < upper or closes[i - 1] > upper else upper
            lower = bl if bl > lower or closes[i - 1] < lower else lower
            if trend == 1 and closes[i] < lower:
                trend = -1
            elif trend == -1 and closes[i] > upper:
                trend = 1
        out[i] = 80.0 if trend == 1 else 20.0
    return out


def heikin_osc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    opens: list[float] | None = None,
) -> list[float | None]:
    """Heikin-Ashi body mapped to 0–100 (close>open → bull)."""
    o = _synth_opens(closes, opens)
    n = min(len(highs), len(lows), len(closes), len(o))
    out: list[float | None] = [None] * n
    if n == 0:
        return out
    ha_open = o[0]
    ha_close = (o[0] + highs[0] + lows[0] + closes[0]) / 4.0
    out[0] = 60.0 if ha_close >= ha_open else 40.0
    for i in range(1, n):
        ha_open = (ha_open + ha_close) / 2.0
        ha_close = (o[i] + highs[i] + lows[i] + closes[i]) / 4.0
        if ha_close == ha_open:
            out[i] = 50.0
        elif ha_close > ha_open:
            out[i] = _clamp100(60.0 + min(20.0, 200.0 * (ha_close - ha_open) / max(1e-9, highs[i] - lows[i])))
        else:
            out[i] = _clamp100(40.0 - min(20.0, 200.0 * (ha_open - ha_close) / max(1e-9, highs[i] - lows[i])))
    return out


def sar_osc(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[float | None]:
    """Parabolic SAR: 75 if price above SAR, 25 if below."""
    n = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * n
    if n < 5:
        return out
    bull = True
    af = 0.02
    sar = lows[0]
    ep = highs[0]
    out[0] = 75.0
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            sar = min(sar, lows[i - 1], lows[i - 2] if i >= 2 else lows[i - 1])
            if lows[i] < sar:
                bull = False
                sar = ep
                ep = lows[i]
                af = 0.02
            else:
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(0.2, af + 0.02)
        else:
            sar = max(sar, highs[i - 1], highs[i - 2] if i >= 2 else highs[i - 1])
            if highs[i] > sar:
                bull = True
                sar = ep
                ep = highs[i]
                af = 0.02
            else:
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(0.2, af + 0.02)
        out[i] = 75.0 if closes[i] >= sar else 25.0
    return out


def ema_ribbon_osc(closes: list[float]) -> list[float | None]:
    """EMA 9/21/55/200 stack as 0–100. 100 = full bull alignment."""
    e9 = ema(closes, 9)
    e21 = ema(closes, 21)
    e55 = ema(closes, 55)
    e200 = ema(closes, 200) if len(closes) >= 200 else ema(closes, min(50, max(10, len(closes) // 4 or 10)))
    out: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        vals = [e9[i], e21[i], e55[i], e200[i] if i < len(e200) else None]
        if any(v is None for v in vals):
            continue
        score = 50.0
        if vals[0] > vals[1]:
            score += 15.0
        else:
            score -= 15.0
        if vals[1] > vals[2]:
            score += 15.0
        else:
            score -= 15.0
        if vals[2] > vals[3]:
            score += 15.0
        else:
            score -= 15.0
        if closes[i] > vals[0]:
            score += 5.0
        else:
            score -= 5.0
        out[i] = _clamp100(score)
    return out


def candle_osc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    opens: list[float] | None = None,
) -> list[float | None]:
    """Candlestick bias as 0–100. 25 = bear reversal, 75 = bull reversal."""
    o = _synth_opens(closes, opens)
    n = min(len(highs), len(lows), len(closes), len(o))
    out: list[float | None] = [None] * n
    if n == 0:
        return out

    def _body(i: int) -> float:
        return abs(closes[i] - o[i])

    def _range(i: int) -> float:
        return max(1e-12, highs[i] - lows[i])

    def _bull(i: int) -> bool:
        return closes[i] > o[i]

    def _bear(i: int) -> bool:
        return closes[i] < o[i]

    for i in range(n):
        rng = _range(i)
        body = _body(i)
        upper = highs[i] - max(closes[i], o[i])
        lower = min(closes[i], o[i]) - lows[i]
        score = 50.0
        if body <= 0.1 * rng:
            score = 50.0
        if lower >= 2.0 * body and upper <= 0.4 * body and _bull(i):
            score = 78.0
        if upper >= 2.0 * body and lower <= 0.4 * body and _bear(i):
            score = 22.0
        if i >= 1:
            prev_body = _body(i - 1)
            if (
                _bear(i - 1)
                and _bull(i)
                and o[i] <= closes[i - 1]
                and closes[i] >= o[i - 1]
                and body > prev_body
            ):
                score = 82.0
            if (
                _bull(i - 1)
                and _bear(i)
                and o[i] >= closes[i - 1]
                and closes[i] <= o[i - 1]
                and body > prev_body
            ):
                score = 18.0
            if _bear(i - 1) and _bull(i) and closes[i] > (o[i - 1] + closes[i - 1]) / 2.0 and o[i] < lows[i - 1]:
                score = max(score, 76.0)
            if _bull(i - 1) and _bear(i) and closes[i] < (o[i - 1] + closes[i - 1]) / 2.0 and o[i] > highs[i - 1]:
                score = min(score, 24.0)
        if i >= 2:
            if (
                _bear(i - 2)
                and _body(i - 1) <= 0.35 * _range(i - 1)
                and _bull(i)
                and closes[i] > o[i - 2]
            ):
                score = 85.0
            if (
                _bull(i - 2)
                and _body(i - 1) <= 0.35 * _range(i - 1)
                and _bear(i)
                and closes[i] < o[i - 2]
            ):
                score = 15.0
        if i >= 2 and all(_bull(j) and _body(j) > 0.45 * _range(j) for j in (i - 2, i - 1, i)):
            if closes[i] > closes[i - 1] > closes[i - 2]:
                score = max(score, 80.0)
        if i >= 2 and all(_bear(j) and _body(j) > 0.45 * _range(j) for j in (i - 2, i - 1, i)):
            if closes[i] < closes[i - 1] < closes[i - 2]:
                score = min(score, 20.0)
        out[i] = _clamp100(score)
    return out


def last(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def last2(values: list[float | None]) -> tuple[float | None, float | None]:
    found: list[float] = []
    for value in reversed(values):
        if value is not None:
            found.append(value)
        if len(found) == 2:
            break
    if len(found) == 0:
        return None, None
    if len(found) == 1:
        return found[0], None
    return found[0], found[1]


def evaluate(highs: list[float], lows: list[float], closes: list[float]) -> dict[str, Any]:
    if len(closes) < 60 or len(highs) != len(closes) or len(lows) != len(closes):
        raise ValueError("CRYPTO_CANDLES")
    rsi14 = last(rsi(closes, 14))
    stochs = {}
    oversold = 0
    overbought = 0
    for period in (5, 14, 21, 55):
        k = last(stochastic(highs, lows, closes, period, 3))
        stochs["stoch_" + str(period)] = k
        if k is not None and k <= 20:
            oversold += 1
        if k is not None and k >= 80:
            overbought += 1
    srsi = last(stoch_rsi(closes))
    macd_line, macd_sig, macd_hist = macd(closes)
    hist_now, hist_prev = last2(macd_hist)
    upper, mid, lower = bollinger(closes)
    close = closes[-1]
    band_u = last(upper)
    band_l = last(lower)
    buy_votes = 0
    sell_votes = 0
    notes: list[str] = []
    if rsi14 is not None and rsi14 <= 30:
        buy_votes += 1
        notes.append("RSI oversold")
    if rsi14 is not None and rsi14 >= 70:
        sell_votes += 1
        notes.append("RSI overbought")
    if oversold >= 3:
        buy_votes += 1
        notes.append("3/4 stoch oversold")
    if overbought >= 3:
        sell_votes += 1
        notes.append("3/4 stoch overbought")
    if srsi is not None and srsi <= 20:
        buy_votes += 1
        notes.append("StochRSI oversold")
    if srsi is not None and srsi >= 80:
        sell_votes += 1
        notes.append("StochRSI overbought")
    if hist_now is not None and hist_prev is not None and hist_prev <= 0 < hist_now:
        buy_votes += 1
        notes.append("MACD hist up")
    if hist_now is not None and hist_prev is not None and hist_prev >= 0 > hist_now:
        sell_votes += 1
        notes.append("MACD hist down")
    if band_l is not None and close <= band_l:
        buy_votes += 1
        notes.append("close <= lower BB")
    if band_u is not None and close >= band_u:
        sell_votes += 1
        notes.append("close >= upper BB")
    side = "none"
    if buy_votes >= 4 and buy_votes > sell_votes:
        side = "buy"
    elif sell_votes >= 4 and sell_votes > buy_votes:
        side = "sell"
    return {
        "close": close,
        "rsi14": rsi14,
        "stoch": stochs,
        "stoch_rsi": srsi,
        "macd_hist": hist_now,
        "bb_upper": band_u,
        "bb_lower": band_l,
        "buy_votes": buy_votes,
        "sell_votes": sell_votes,
        "notes": notes,
        "super": side,
        "source": "ohlcv",
    }
