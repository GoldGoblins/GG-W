"""Public spot OHLCV: Binance SOL/USDT and Gate KAS/USDT. No account access."""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
import urllib.request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
from typing import Any
from pathlib import Path

from backend import crypto_data
from backend.crypto_contract import ensure_state_dir

PAIRS = {"SOLUSDT": ("binance", "api.binance.com"), "KASUSDT": ("gate", "api.gateio.ws")}
TIMEFRAMES = ("15m", "1h", "4h", "1d")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def parse(rows: Any, pair: str, interval: str, *, now: float | None = None) -> dict[str, Any]:
    provider = PAIRS[pair][0]
    clock = time.time() if now is None else now
    step = crypto_data.BAR_SECONDS[interval]
    points = {}
    if not isinstance(rows, list):
        raise ValueError("CRYPTO_MARKET_RESPONSE")
    for row in rows:
        if not isinstance(row, list) or len(row) < (7 if provider == "binance" else 6):
            raise ValueError("CRYPTO_MARKET_ROW")
        if provider == "binance":
            ts = int(row[0]) // 1000
            opening, high, low, close, volume = map(float, row[1:6])
        else:
            ts = int(row[0])
            close, high, low, opening = map(float, row[2:6])
            if len(row) < 7:
                raise ValueError("CRYPTO_MARKET_BASE_VOLUME_MISSING")
            volume = float(row[6])
            if len(row) > 7 and str(row[7]).lower() == "false":
                continue
        if ts + step > clock:
            continue
        if not all(math.isfinite(x) for x in (opening, high, low, close, volume)) or not low <= opening <= high:
            raise ValueError("CRYPTO_MARKET_OHLCV")
        points[ts] = (opening, high, low, close, volume)
    stamps = sorted(points)
    raw = {"times": stamps, "source": provider + "-spot", "symbol": pair, "closed_only": True}
    for column, key in enumerate(("opens", "highs", "lows", "closes", "volumes")):
        raw[key] = [points[ts][column] for ts in stamps]
    return crypto_data.validate_frame(raw, interval, min_bars=1)


def _request_once(pair: str, interval: str, *, start: int | None = None, end: int | None = None, limit: int = 400) -> dict[str, Any]:
    provider, host = PAIRS[pair]
    if interval not in crypto_data.BAR_SECONDS:
        raise ValueError("CRYPTO_KLINE_INTERVAL")
    if provider == "binance":
        query = {"symbol": pair, "interval": interval, "limit": min(1000, limit)}
        if start is not None:
            query.update(startTime=start * 1000, endTime=end * 1000)
        url = "https://api.binance.com/api/v3/klines?" + urlencode(query)
    else:
        query = {"currency_pair": "KAS_USDT", "interval": interval}
        if start is None:
            query["limit"] = min(1000, limit)
        else:
            query.update({"from": start, "to": end})
        url = "https://api.gateio.ws/api/v4/spot/candlesticks?" + urlencode(query)
    request = urllib.request.Request(url, headers={"User-Agent": "gg-ai-desktop-market/1"}, method="GET")
    with urllib.request.urlopen(request, timeout=8.0) as response:
        actual = response.geturl() if hasattr(response, "geturl") else url
        if urlparse(actual).hostname != host:
            raise ValueError("CRYPTO_MARKET_REDIRECT")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("CRYPTO_MARKET_RESPONSE_TOO_LARGE")
    return parse(json.loads(body), pair, interval)



def _request(pair: str, interval: str, **kwargs) -> dict[str, Any]:
    # Idempotent public GETs only. Retry one transient transport/server failure.
    for attempt in range(2):
        try:
            return _request_once(pair, interval, **kwargs)
        except HTTPError as exc:
            if exc.code < 500 or attempt:
                raise
        except (TimeoutError, URLError, OSError):
            if attempt:
                raise
    raise RuntimeError("CRYPTO_MARKET_REQUEST_FAILED")


def _cache_path(pair: str, interval: str):
    if pair not in PAIRS or interval not in crypto_data.BAR_SECONDS:
        raise ValueError("CRYPTO_MARKET_PAIR_OR_INTERVAL")
    return ensure_state_dir() / ("market-" + pair.lower() + "-" + interval + ".json")


def _save(frame: dict[str, Any], pair: str, interval: str) -> None:
    path = _cache_path(pair, interval)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".new")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump({**frame, "data_version": crypto_data.HISTORY_VERSION, "fetched_at": time.time()}, stream, allow_nan=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def recent(pair: str, interval: str) -> dict[str, Any]:
    path = _cache_path(pair, interval)
    try:
        cached = json.loads(path.read_text())
        if cached.get("data_version") != crypto_data.HISTORY_VERSION:
            raise ValueError("CRYPTO_CACHE_VERSION")
        checked = crypto_data.validate_frame(cached, interval, min_bars=96)
        if checked["gaps"] or checked["source"] != PAIRS[pair][0] + "-spot":
            raise ValueError("CRYPTO_CACHE_INTEGRITY")
        if checked["symbol"] == pair and checked["times"][-1] == int(time.time() // crypto_data.BAR_SECONDS[interval]) * crypto_data.BAR_SECONDS[interval] - crypto_data.BAR_SECONDS[interval]:
            return {**checked, **{key: checked[key][-400:] for key in ("opens", "highs", "lows", "closes", "volumes", "times") if key in checked}}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    frame = _request(pair, interval)
    frame = crypto_data.validate_frame(frame, interval, min_bars=96)
    if frame["gaps"]:
        raise ValueError("CRYPTO_DATA_GAPS")
    _save(frame, pair, interval)
    return frame


def history(pair: str, interval: str, start: int, *, max_pages: int = 40) -> dict[str, Any]:
    """Bounded explicit research download; never substitutes coarse or invented bars."""
    step = crypto_data.BAR_SECONDS[interval]
    end = int(time.time() // step) * step
    cursor = int(start // step) * step
    records = {}
    for _ in range(max_pages):
        if cursor >= end:
            break
        until = min(end - 1, cursor + 1000 * step - 1)
        frame = _request(pair, interval, start=cursor, end=until, limit=1000)
        for index, ts in enumerate(frame["times"]):
            records[ts] = {key: frame[key][index] for key in ("opens", "highs", "lows", "closes", "volumes")}
        cursor = until + 1
    if cursor < end:
        raise ValueError("CRYPTO_HISTORY_PAGE_BUDGET")
    stamps = sorted(records)
    result = {"times": stamps, "symbol": pair, "source": PAIRS[pair][0] + "-spot", "closed_only": True}
    for key in ("opens", "highs", "lows", "closes", "volumes"):
        result[key] = [records[ts][key] for ts in stamps]
    checked = crypto_data.validate_frame(result, interval, min_bars=96)
    if checked["gaps"]:
        raise ValueError("CRYPTO_DATA_GAPS")
    _save(checked, pair, interval)
    return checked


def recent_frames(pair: str) -> dict[str, dict[str, Any]]:
    return {tf: recent(pair, tf) for tf in TIMEFRAMES}
