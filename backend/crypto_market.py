"""Public spot OHLCV: Binance SOL/USDT and Gate KAS/USDT. No account access."""
from __future__ import annotations

import json
import re
import math
import os
import tempfile
import threading
import time
import urllib.request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
from typing import Any
from pathlib import Path
from collections import OrderedDict

from backend import crypto_data
from backend.crypto_contract import ensure_state_dir
from backend.platform_files import atomic_replace

PAIRS = {"SOLUSDT": ("binance", "api.binance.com"), "KASUSDT": ("gate", "api.gateio.ws")}
TIMEFRAMES = ("15m", "1h", "4h", "1d")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_HISTORY_PAGES = 40
_RECENT_LOCKS = {(pair, interval): threading.Lock() for pair in PAIRS for interval in crypto_data.BAR_SECONDS}
_recent_memory: OrderedDict[str, tuple[tuple[int, int, int], int, dict[str, Any]]] = OrderedDict()
_recent_memory_lock = threading.Lock()
_pair_registry_lock = threading.Lock()


def register_public_pair(pair: str) -> None:
    """Caller has checked the public Binance symbol; finite registry, no orders."""
    if not isinstance(pair, str) or not re.fullmatch(r'[A-Z0-9]{1,20}USDT', pair):
        raise ValueError('CRYPTO_MARKET_SYMBOL')
    with _pair_registry_lock:
        if pair in PAIRS:
            return
        if len(PAIRS) >= 128:
            raise ValueError('CRYPTO_MARKET_PAIR_LIMIT')
        for interval in crypto_data.BAR_SECONDS:
            _RECENT_LOCKS[(pair, interval)] = threading.Lock()
        PAIRS[pair] = ('binance', 'api.binance.com')


def _identity(pair: str, interval: str) -> None:
    if pair not in PAIRS or interval not in crypto_data.BAR_SECONDS:
        raise ValueError("CRYPTO_MARKET_PAIR_OR_INTERVAL")


def _integer(value: Any) -> int:
    try:
        integer = int(value)
        if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) != integer:
            raise ValueError("CRYPTO_MARKET_TIMESTAMP")
        return integer
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CRYPTO_MARKET_TIMESTAMP") from exc


def parse(rows: Any, pair: str, interval: str, *, now: float | None = None) -> dict[str, Any]:
    _identity(pair, interval)
    provider = PAIRS[pair][0]
    clock = time.time() if now is None else now
    step = crypto_data.BAR_SECONDS[interval]
    points = {}
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError("CRYPTO_MARKET_RESPONSE")
    for row in rows:
        if not isinstance(row, list) or len(row) < (7 if provider == "binance" else 6):
            raise ValueError("CRYPTO_MARKET_ROW")
        if any(isinstance(value, bool) for value in row[:7]):
            raise ValueError("CRYPTO_MARKET_OHLCV")
        if provider == "binance":
            milliseconds = _integer(row[0])
            if milliseconds % 1000:
                raise ValueError("CRYPTO_MARKET_TIMESTAMP")
            ts = milliseconds // 1000
            opening, high, low, close, volume = map(float, row[1:6])
        else:
            ts = _integer(row[0])
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
        point = (opening, high, low, close, volume)
        if ts in points and points[ts] != point:
            raise ValueError("CRYPTO_MARKET_DUPLICATE")
        points[ts] = point
    stamps = sorted(points)
    raw = {"times": stamps, "source": provider + "-spot", "symbol": pair,
           "base_currency": pair.removesuffix("USDT"), "quote_currency": "USDT", "closed_only": True}
    for column, key in enumerate(("opens", "highs", "lows", "closes", "volumes")):
        raw[key] = [points[ts][column] for ts in stamps]
    return crypto_data.validate_frame(raw, interval, min_bars=1, now=clock)


def _request_once(pair: str, interval: str, *, start: int | None = None, end: int | None = None, limit: int = 400) -> dict[str, Any]:
    _identity(pair, interval)
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
    _identity(pair, interval)
    return ensure_state_dir() / ("market-" + pair.lower() + "-" + interval + ".json")


def _save(frame: dict[str, Any], pair: str, interval: str) -> dict[str, Any]:
    path = _cache_path(pair, interval)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".new")
    temporary = Path(name)
    saved = {**frame, "data_version": crypto_data.HISTORY_VERSION, "fetched_at": time.time()}
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(saved, stream, allow_nan=False)
        atomic_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return saved


def _signature(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    if stat.st_size > MAX_CACHE_BYTES:
        raise ValueError("CRYPTO_MARKET_CACHE_TOO_LARGE")
    return stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns


def _copy_frame(frame: dict[str, Any]) -> dict[str, Any]:
    return {key: list(value) if isinstance(value, list) else value for key, value in frame.items()}


def _recent_frame(frame: dict[str, Any], pair: str, interval: str, last_closed: int) -> dict[str, Any]:
    checked = crypto_data.validate_frame(frame, interval, min_bars=96)
    if checked["gaps"] or checked["source"] != PAIRS[pair][0] + "-spot" or checked["symbol"] != pair:
        raise ValueError("CRYPTO_CACHE_INTEGRITY")
    if checked["times"][-1] != last_closed:
        raise ValueError("CRYPTO_MARKET_STALE")
    checked.update(base_currency=pair.removesuffix("USDT"), quote_currency="USDT")
    # Slice metadata together with the actual tape, rather than returning a
    # 400-bar tape labelled with a multi-year history's count and date range.
    trimmed = {**checked, **{key: checked[key][-400:] for key in ("opens", "highs", "lows", "closes", "volumes", "times") if key in checked}}
    return crypto_data.validate_frame(trimmed, interval, min_bars=96)


def _remember_recent(path: Path, last_closed: int, frame: dict[str, Any]) -> None:
    key = str(path)
    with _recent_memory_lock:
        _recent_memory[key] = (_signature(path), last_closed, _copy_frame(frame))
        _recent_memory.move_to_end(key)
        while len(_recent_memory) > len(_RECENT_LOCKS):
            _recent_memory.popitem(last=False)


def recent(pair: str, interval: str) -> dict[str, Any]:
    path = _cache_path(pair, interval)
    # Paper workers may request the same pair together. One bounded download
    # supplies them; all callers get an independent copy of the validated tape.
    with _RECENT_LOCKS[pair, interval]:
        step = crypto_data.BAR_SECONDS[interval]
        last_closed = int(time.time() // step) * step - step
        key = str(path)
        try:
            signature = _signature(path)
            with _recent_memory_lock:
                hit = _recent_memory.get(key)
                if hit is not None and hit[:2] == (signature, last_closed):
                    _recent_memory.move_to_end(key)
                    return _copy_frame(hit[2])
            with path.open("rb") as stream:
                body = stream.read(MAX_CACHE_BYTES + 1)
            if len(body) > MAX_CACHE_BYTES:
                raise ValueError("CRYPTO_MARKET_CACHE_TOO_LARGE")
            cached = json.loads(body)
            if not isinstance(cached, dict) or cached.get("data_version") != crypto_data.HISTORY_VERSION:
                raise ValueError("CRYPTO_CACHE_VERSION")
            checked = _recent_frame(cached, pair, interval, last_closed)
        except (OSError, ValueError, KeyError, TypeError):
            checked = _recent_frame(_request(pair, interval), pair, interval, last_closed)
            checked = _save(checked, pair, interval)
        _remember_recent(path, last_closed, checked)
        return _copy_frame(checked)


def history(pair: str, interval: str, start: int, *, max_pages: int = 40) -> dict[str, Any]:
    """Bounded explicit research download; never substitutes coarse or invented bars."""
    _identity(pair, interval)
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= MAX_HISTORY_PAGES:
        raise ValueError("CRYPTO_HISTORY_PAGE_BUDGET")
    step = crypto_data.BAR_SECONDS[interval]
    end = int(time.time() // step) * step
    cursor = _integer(start) // step * step
    if cursor <= 0 or cursor >= end:
        raise ValueError("CRYPTO_HISTORY_RANGE")
    if end - cursor > max_pages * 1000 * step:
        raise ValueError("CRYPTO_HISTORY_PAGE_BUDGET")
    records = {}
    for _ in range(max_pages):
        if cursor >= end:
            break
        until = min(end - 1, cursor + 1000 * step - 1)
        frame = _request(pair, interval, start=cursor, end=until, limit=1000)
        frame = crypto_data.validate_frame(frame, interval, min_bars=1)
        if frame["symbol"] != pair or frame["source"] != PAIRS[pair][0] + "-spot" or any(not cursor <= ts <= until for ts in frame["times"]):
            raise ValueError("CRYPTO_HISTORY_RESPONSE_RANGE")
        for index, ts in enumerate(frame["times"]):
            records[ts] = {key: frame[key][index] for key in ("opens", "highs", "lows", "closes", "volumes")}
        cursor = until + 1
    if cursor < end:
        raise ValueError("CRYPTO_HISTORY_PAGE_BUDGET")
    stamps = sorted(records)
    result = {"times": stamps, "symbol": pair, "source": PAIRS[pair][0] + "-spot",
              "base_currency": pair.removesuffix("USDT"), "quote_currency": "USDT", "closed_only": True}
    for key in ("opens", "highs", "lows", "closes", "volumes"):
        result[key] = [records[ts][key] for ts in stamps]
    checked = crypto_data.validate_frame(result, interval, min_bars=96)
    if checked["gaps"]:
        raise ValueError("CRYPTO_DATA_GAPS")
    return _save(checked, pair, interval)


def recent_frames(pair: str) -> dict[str, dict[str, Any]]:
    return {tf: recent(pair, tf) for tf in TIMEFRAMES}
