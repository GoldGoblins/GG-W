"""Explicit market-data contracts shared by research and paper execution."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

BAR_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "8h": 28800, "1d": 86400}
HISTORY_VERSION = 2


def iso(stamp: int | float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def validate_frame(frame: dict[str, Any], interval: str, *, min_bars: int = 80, require_closed: bool = True, now: float | None = None) -> dict[str, Any]:
    """Reject invented/incomplete OHLCV; retain gaps as explicit evidence."""
    step = BAR_SECONDS.get(interval)
    if not isinstance(frame, dict) or not step or frame.get("synthetic"):
        raise ValueError("CRYPTO_DATA_SYNTHETIC_OR_INTERVAL")
    if isinstance(min_bars, bool) or not isinstance(min_bars, int) or min_bars < 1:
        raise ValueError("CRYPTO_DATA_INCOMPLETE")
    keys = ("highs", "lows", "closes", "volumes", "times")
    if any(not isinstance(frame.get(key), (list, tuple)) for key in keys):
        raise ValueError("CRYPTO_DATA_INCOMPLETE")
    values = {key: list(frame[key]) for key in keys}
    n = len(values["closes"])
    if n < min_bars or any(len(values[key]) != n for key in keys):
        raise ValueError("CRYPTO_DATA_INCOMPLETE")
    for key in keys[:4]:
        try:
            if any(isinstance(value, bool) for value in values[key]):
                raise ValueError("CRYPTO_DATA_INVALID")
            values[key] = [float(value) for value in values[key]]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("CRYPTO_DATA_INVALID") from exc
    for i in range(n):
        high, low, close, volume = (values[key][i] for key in keys[:4])
        if not all(math.isfinite(x) for x in (high, low, close, volume)) or not 0 < low <= close <= high or volume < 0:
            raise ValueError("CRYPTO_DATA_INVALID")
    if "opens" in frame:
        raw_opens = frame["opens"]
        if not isinstance(raw_opens, (list, tuple)) or len(raw_opens) != n or any(isinstance(v, bool) for v in raw_opens):
            raise ValueError("CRYPTO_DATA_OPEN_PRICE")
        try:
            opens = [float(v) for v in raw_opens]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("CRYPTO_DATA_OPEN_PRICE") from exc
        if any(not math.isfinite(v) or not values["lows"][i] <= v <= values["highs"][i] for i, v in enumerate(opens)):
            raise ValueError("CRYPTO_DATA_OPEN_PRICE")
        values["opens"] = opens
    try:
        if any(isinstance(value, bool) or not math.isfinite(float(value)) or float(value) != int(value) for value in values["times"]):
            raise ValueError("CRYPTO_DATA_TIMESTAMPS")
        times = [int(x) for x in values["times"]]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CRYPTO_DATA_TIMESTAMPS") from exc
    if any(t <= 0 for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("CRYPTO_DATA_TIMESTAMPS")
    clock = time.time() if now is None else now
    if times[-1] > clock or (require_closed and (frame.get("closed_only") is False or times[-1] + step > clock)):
        raise ValueError("CRYPTO_DATA_OPEN_CANDLE")
    gaps = sum(b - a != step for a, b in zip(times, times[1:]))
    return {
        **frame, **values, "times": times, "interval": interval,
        "source": str(frame.get("source") or "offline-fixture"),
        "symbol": str(frame.get("symbol") or "SOLUSDT"),
        "bar_count": n, "from": iso(times[0]), "to": iso(times[-1] + step),
        "gaps": gaps, "volume_available": any(float(x) > 0 for x in values["volumes"]),
        "closed_only": bool(require_closed), "synthetic": False,
    }


def freshness(cache: dict[str, Any], ttl: float = 60.0) -> dict[str, Any]:
    try:
        raw_fetched = cache.get("fetched_at")
        fetched = float(raw_fetched or 0)
        valid = not isinstance(raw_fetched, bool) and math.isfinite(fetched) and fetched > 0
    except (TypeError, ValueError, OverflowError):
        fetched, valid = 0.0, False
    clock = time.time()
    clock_skew = valid and fetched > clock
    age = clock - fetched if valid and not clock_skew else None
    try:
        lifetime = float(ttl)
        valid_ttl = not isinstance(ttl, bool) and math.isfinite(lifetime) and lifetime >= 0
    except (TypeError, ValueError, OverflowError):
        lifetime, valid_ttl = 0.0, False
    requested = str(cache.get("requested_interval") or cache.get("interval") or "")
    actual = str(cache.get("interval") or "")
    interval_match = not requested or requested == actual
    return {
        "fetched_at": fetched if valid else None, "age_seconds": round(age, 1) if age is not None else None,
        "stale": age is None or not valid_ttl or bool(cache.get("error")) or age > lifetime or not interval_match,
        "error": str(cache.get("error") or ""),
        "requested_interval": requested,
        "actual_interval": actual,
        "interval_match": interval_match,
        "clock_skew": bool(clock_skew),
    }
