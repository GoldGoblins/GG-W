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


def validate_frame(frame: dict[str, Any], interval: str, *, min_bars: int = 80, require_closed: bool = True) -> dict[str, Any]:
    """Reject invented/incomplete OHLCV; retain gaps as explicit evidence."""
    step = BAR_SECONDS.get(interval)
    if not step or frame.get("synthetic"):
        raise ValueError("CRYPTO_DATA_SYNTHETIC_OR_INTERVAL")
    keys = ("highs", "lows", "closes", "volumes", "times")
    values = {key: list(frame.get(key) or []) for key in keys}
    n = len(values["closes"])
    if n < min_bars or any(len(values[key]) != n for key in keys):
        raise ValueError("CRYPTO_DATA_INCOMPLETE")
    for i in range(n):
        high, low, close, volume = (float(values[key][i]) for key in keys[:4])
        if not all(math.isfinite(x) for x in (high, low, close, volume)) or not 0 < low <= close <= high or volume < 0:
            raise ValueError("CRYPTO_DATA_INVALID")
    if "opens" in frame:
        opens = list(frame["opens"])
        if len(opens) != n or any(not math.isfinite(float(v)) or not float(values["lows"][i]) <= float(v) <= float(values["highs"][i]) for i, v in enumerate(opens)):
            raise ValueError("CRYPTO_DATA_OPEN_PRICE")
        values["opens"] = [float(v) for v in opens]
    times = [int(x) for x in values["times"]]
    if any(t <= 0 for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("CRYPTO_DATA_TIMESTAMPS")
    if times[-1] > time.time() or (require_closed and (frame.get("closed_only") is False or times[-1] + step > time.time())):
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
    fetched = float(cache.get("fetched_at") or 0)
    age = max(0.0, time.time() - fetched) if fetched else None
    return {
        "fetched_at": fetched or None, "age_seconds": round(age, 1) if age is not None else None,
        "stale": not fetched or bool(cache.get("error")) or age > ttl,
        "error": str(cache.get("error") or ""),
        "requested_interval": str(cache.get("requested_interval") or cache.get("interval") or ""),
        "actual_interval": str(cache.get("interval") or ""),
        "interval_match": not cache.get("requested_interval") or cache.get("requested_interval") == cache.get("interval"),
    }
