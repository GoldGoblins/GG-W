"""Read-only Polymarket market research for the Crypto surface.

The desktop deliberately keeps this adapter separate from the Solana wallet
and trading code.  It does not contact the network at import time or while
the Crypto status rail is refreshing.  A user action starts one bounded
DuckDB query against one Pendulumflow V3 hourly Parquet file.

DuckDB is optional because the application should still start when the
analytical dependency is not installed.  In that case the UI exposes the
validated URL and SQL preview and explains how to enable the query runner.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlencode
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence


ARCHIVE_BASE = "https://archive.pendulumflow.com/v3"
ARCHIVE_HOST = "archive.pendulumflow.com"
REPO_URL = "https://github.com/warproxxx/poly_data"
SOURCE_LABEL = "PENDULUMFLOW V3 · REMOTE PARQUET · READ ONLY"
PRESETS = ("SUMMARY", "TRADES", "TOUCH", "SCAN")
MAX_ROWS = 240
MAX_SLUG_LENGTH = 160
QUERY_TIMEOUT_SECONDS = 30
MEMORY_LIMIT = "512MiB"
MAX_SOURCE_BYTES = 2 * 1024**3
_process_lock = threading.RLock()
_active_process: subprocess.Popen | None = None
_cancel = threading.Event()
_worker_running = False

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HOUR_RE = re.compile(r"^\d{1,2}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,159}$")

QueryExecutor = Callable[[str], tuple[Sequence[str], Sequence[Sequence[Any]]]]


class DuckDBUnavailable(RuntimeError):
    """Raised when the optional local analytical runner is absent."""


def _utc_defaults() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return now.date().isoformat(), f"{now.hour:02d}"


def _normalise_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not _DATE_RE.fullmatch(raw):
        raise ValueError("POLYMARKET_DATE")
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("POLYMARKET_DATE") from exc
    if parsed.isoformat() != raw:
        raise ValueError("POLYMARKET_DATE")
    return raw


def _normalise_hour(value: Any) -> str:
    raw = str(value or "").strip()
    if not _HOUR_RE.fullmatch(raw):
        raise ValueError("POLYMARKET_HOUR")
    hour = int(raw)
    if hour < 0 or hour > 23:
        raise ValueError("POLYMARKET_HOUR")
    return f"{hour:02d}"


def _normalise_slug(value: Any, *, required: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise ValueError("POLYMARKET_SLUG_REQUIRED")
        return ""
    if len(raw) > MAX_SLUG_LENGTH or not _SLUG_RE.fullmatch(raw):
        raise ValueError("POLYMARKET_SLUG")
    return raw


def normalise_query(
    preset: Any,
    query_date: Any,
    hour: Any,
    slug: Any = "",
) -> dict[str, Any]:
    mode = str(preset or "").strip().upper()
    if mode not in PRESETS:
        raise ValueError("POLYMARKET_PRESET")
    day = _normalise_date(query_date)
    utc_hour = _normalise_hour(hour)
    market_slug = _normalise_slug(slug, required=mode == "TOUCH")
    return {
        "preset": mode,
        "date": day,
        "hour": utc_hour,
        "slug": market_slug,
    }


def archive_url(query_date: Any, hour: Any) -> str:
    day = _normalise_date(query_date)
    utc_hour = _normalise_hour(hour)
    return f"{ARCHIVE_BASE}/{day}/{utc_hour}/{day}T{utc_hour}.parquet"


def _sql_literal(value: str) -> str:
    """Quote an already validated value for a DuckDB SQL string literal."""

    return "'" + value.replace("'", "''") + "'"


def query_spec(
    preset: Any,
    query_date: Any,
    hour: Any,
    slug: Any = "",
    *, condition_id: str = "",
) -> dict[str, Any]:
    """Return the fixed, auditable query for a selected archive hour."""

    query = normalise_query(preset, query_date, hour, slug)
    url = archive_url(query["date"], query["hour"])
    source = _sql_literal(url)
    mode = query["preset"]
    if mode == "SUMMARY":
        sql = f"""
SELECT event_type, count(*) AS rows
FROM read_parquet({source})
GROUP BY 1
ORDER BY rows DESC
LIMIT 16
""".strip()
    elif mode == "TRADES":
        sql = f"""
SELECT timestamp_received AS at,
       round(price, 4) AS price,
       round(size, 2) AS size,
       side,
       '0x' || lower(hex(market)) AS market,
       '0x' || lower(hex(asset_id)) AS asset
FROM read_parquet({source})
WHERE event_type = 'last_trade_price'
ORDER BY size DESC
LIMIT 20
""".strip()
    elif mode == "SCAN":
        sql = f"""
SELECT '0x' || lower(hex(market)) AS market,
       '0x' || lower(hex(asset_id)) AS asset,
       round(avg(best_ask - best_bid), 4) AS spread,
       round(avg(best_bid), 4) AS bid,
       round(avg(best_ask), 4) AS ask,
       count(*) AS quotes
FROM read_parquet({source})
WHERE event_type = 'best_bid_ask'
GROUP BY 1, 2
HAVING spread IS NOT NULL
ORDER BY spread DESC
LIMIT 20
""".strip()
    else:
        market_slug = _sql_literal(query["slug"])
        if condition_id and not re.fullmatch(r"0x[0-9a-fA-F]{64}", condition_id):
            raise ValueError("POLYMARKET_CONDITION_ID")
        target_filter = "market = from_hex(" + _sql_literal(condition_id[2:]) + ")" if condition_id else "market = (SELECT market FROM target)"
        target_cte = "" if condition_id else f"""WITH target AS (
    SELECT market
    FROM read_parquet({source})
    WHERE event_type = 'new_market'
      AND slug = {market_slug}
    LIMIT 1
)
"""
        sql = f"""{target_cte}
SELECT strftime(date_trunc('minute', timestamp_received), '%H:%M') AS minute,
       '0x' || lower(hex(asset_id)) AS asset,
       round(avg(best_bid), 4) AS bid,
       round(avg(best_ask), 4) AS ask
FROM read_parquet({source})
WHERE event_type = 'best_bid_ask'
  AND {target_filter}
GROUP BY 1, 2
ORDER BY 1, 2
LIMIT 240
""".strip()
    return {
        **query,
        "url": url,
        "sql": sql,
        "source": SOURCE_LABEL,
        "budget": {"memory": MEMORY_LIMIT, "threads": 2, "timeout_seconds": QUERY_TIMEOUT_SECONDS, "max_source_bytes": MAX_SOURCE_BYTES},
    }


def _public_json(url: str) -> Any:
    # Fixed URLs constructed internally, never user-supplied hosts or paths.
    request = urllib.request.Request(url, headers={"User-Agent": "gg-ai-desktop-crypto/2"})
    with urllib.request.urlopen(request, timeout=8) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError("POLYMARKET_METADATA_SIZE")
    return json.loads(raw)


def resolve_market(slug: str) -> dict[str, Any]:
    slug = _normalise_slug(slug, required=True)
    rows = _public_json("https://gamma-api.polymarket.com/markets?" + urlencode({"slug": slug, "limit": 2}))
    for row in rows if isinstance(rows, list) else []:
        if row.get("slug") != slug:
            continue
        condition = str(row.get("conditionId") or "")
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", condition):
            continue
        def array(value):
            return json.loads(value) if isinstance(value, str) else (value or [])
        tokens, outcomes = array(row.get("clobTokenIds")), array(row.get("outcomes"))
        labels = {"0x" + int(token).to_bytes(32, "big").hex(): str(outcome) for token, outcome in zip(tokens, outcomes)}
        return {"condition_id": condition, "outcomes": labels, "slug": slug}
    raise ValueError("POLYMARKET_MARKET_NOT_FOUND")


def source_metadata(query_date: str, hour: str) -> dict[str, Any]:
    """Check the selected object before DuckDB can scan it, without downloading it."""
    url = archive_url(query_date, hour)
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=8) as response:
        size = int(response.headers.get("Content-Length") or 0)
        tag = response.headers.get("ETag") or ""
    if size <= 0:
        raise ValueError("POLYMARKET_SOURCE_SIZE_UNKNOWN")
    if size > MAX_SOURCE_BYTES:
        raise ValueError("POLYMARKET_SOURCE_BUDGET")
    return {"url": url, "bytes": size, "etag": tag, "checked_at": datetime.now(timezone.utc).isoformat(),
            "coverage": "One archive hour; completeness of the feed is not verified."}


def duckdb_available() -> bool:
    try:
        return importlib.util.find_spec("duckdb") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _duckdb_in_process(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    if not duckdb_available():
        raise DuckDBUnavailable("DUCKDB_NOT_INSTALLED")
    import duckdb

    connection = duckdb.connect(database=":memory:", config={"memory_limit": MEMORY_LIMIT, "threads": 2,
        "autoinstall_known_extensions": False, "autoload_known_extensions": False})
    try:
        # Loading a previously installed extension is explicit; never install
        # software as a side effect of a read-only archive query.
        connection.execute("LOAD httpfs")
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute("SET http_timeout = 10")
        connection.execute("SET http_retries = 1")
        connection.execute("SET max_temp_directory_size = '0B'")
        cursor = connection.execute(sql)
        columns = [str(item[0]) for item in (cursor.description or ())]
        rows = [tuple(row) for row in cursor.fetchmany(MAX_ROWS)]
        return columns, rows
    finally:
        connection.close()


def _duckdb_execute(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    """An interruptible child bounds wall time and isolates optional DuckDB."""
    global _active_process
    if not duckdb_available():
        raise DuckDBUnavailable()
    with _process_lock:
        if _cancel.is_set() or _active_process is not None:
            raise RuntimeError("POLYMARKET_CANCELLED_OR_BUSY")
        process = subprocess.Popen([sys.executable, "-B", "-m", "backend.polymarket_research", "--worker"],
                                   cwd=str(Path(__file__).resolve().parents[1]),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True)
        _active_process = process
    try:
        try:
            output, _ = process.communicate(sql, timeout=QUERY_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("POLYMARKET_QUERY_TIMEOUT")
        if process.returncode or _cancel.is_set():
            raise RuntimeError("POLYMARKET_QUERY_CANCELLED")
        payload = json.loads(output)
        if payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload["columns"], payload["rows"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        with _process_lock:
            _active_process = None


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date_type)):
        return value.isoformat()
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _row_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    names = [str(item) for item in columns]
    result: list[dict[str, Any]] = []
    for row in rows[:MAX_ROWS]:
        if isinstance(row, dict):
            result.append({str(key): _json_value(value) for key, value in row.items()})
            continue
        values = list(row)
        result.append(
            {
                name: _json_value(values[index]) if index < len(values) else None
                for index, name in enumerate(names)
            }
        )
    return result


def _display_market(value: Any) -> str:
    text = str(value or "")
    if len(text) > 22:
        return text[:10] + "…" + text[-8:]
    return text


def _format_lines(preset: str, rows: Sequence[dict[str, Any]]) -> list[str]:
    if preset == "SUMMARY":
        lines = ["EVENT TYPE                 ROWS"]
        for row in rows:
            lines.append(
                f"{str(row.get('event_type') or '')[:25]:<25} "
                f"{str(row.get('rows') or 0):>8}"
            )
        return lines
    if preset == "TRADES":
        lines = ["AT (UTC, full precision)       PRICE      SIZE       SIDE  MARKET / OUTCOME ASSET"]
        for row in rows:
            lines.append(
                f"{str(row.get('at') or ''):<28}  "
                f"{str(row.get('price') or '')[:10]:>10}  "
                f"{str(row.get('size') or '')[:10]:>10}  "
                f"{str(row.get('side') or '')[:4]:<4}  "
                f"{_display_market(row.get('market'))} / {_display_market(row.get('asset'))}"
            )
        return lines
    if preset == "SCAN":
        lines = ["MARKET / OUTCOME ASSET                    SPREAD      BID        ASK   QUOTES"]
        for row in rows:
            lines.append(
                f"{_display_market(row.get('market')):<18}  "
                f"{str(row.get('spread') or '')[:8]:>8}  "
                f"{str(row.get('bid') or '')[:8]:>8}  "
                f"{str(row.get('ask') or '')[:8]:>8}  "
                f"{str(row.get('quotes') or 0):>6}"
                f"  ASSET {_display_market(row.get('asset'))}"
            )
        return lines
    lines = ["MINUTE    BID        ASK        OUTCOME / ASSET"]
    for row in rows:
        lines.append(
            f"{str(row.get('minute') or '')[:8]:<8}  "
            f"{str(row.get('bid') or '')[:10]:>10}  "
            f"{str(row.get('ask') or '')[:10]:>10}  "
            f"{row.get('outcome') or _display_market(row.get('asset'))}"
        )
    return lines


def _error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split())
    known = {
        "POLYMARKET_SOURCE_BUDGET": "The selected archive file exceeds the 2 GiB source budget. Choose another UTC hour.",
        "POLYMARKET_SOURCE_SIZE_UNKNOWN": "The archive did not report its file size. The query stopped before scanning.",
        "POLYMARKET_QUERY_TIMEOUT": "The query exceeded its 30-second SQL time budget and was stopped.",
        "POLYMARKET_MARKET_NOT_FOUND": "No market matched this slug. Verify the market's slug.",
    }
    if message in known:
        return known[message]
    if len(message) > 240:
        message = message[:237] + "..."
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def run_query(
    preset: Any,
    query_date: Any,
    hour: Any,
    slug: Any = "",
    *,
    executor: QueryExecutor | None = None,
    resolver: Callable[[str], dict[str, Any]] | None = None,
    metadata_reader: Callable[[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one fixed query, or return a precise local setup error."""

    started = time.monotonic()
    try:
        spec = query_spec(preset, query_date, hour, slug)
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "hint": "Choose a valid UTC date, hour and market slug.",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    try:
        metadata = {"coverage": "Injected offline executor; archive coverage is not verified."}
        market = {}
        if not executor and not duckdb_available():
            raise DuckDBUnavailable()
        if not executor or metadata_reader:
            metadata = (metadata_reader or source_metadata)(spec["date"], spec["hour"])
        if spec["preset"] == "TOUCH" and (not executor or resolver):
            market = (resolver or resolve_market)(spec["slug"])
            spec = query_spec(preset, query_date, hour, slug, condition_id=market["condition_id"])
        if not executor and _cancel.is_set():
            raise RuntimeError("POLYMARKET_QUERY_CANCELLED")
        columns, raw_rows = executor(spec["sql"]) if executor else _duckdb_execute(spec["sql"])
        rows = _row_dicts(columns, raw_rows)
        for row in rows:
            row["outcome"] = (market.get("outcomes") or {}).get(str(row.get("asset") or ""), "")
        return {
            "ok": True,
            "error": "",
            "hint": "",
            "columns": [str(item) for item in columns],
            "rows": rows,
            "lines": _format_lines(spec["preset"], rows),
            "row_count": len(rows),
            "duration_ms": int((time.monotonic() - started) * 1000),
            "sql": spec["sql"],
            "url": spec["url"],
            "budget": spec["budget"],
            "source_metadata": metadata,
            "market": market,
            "limit_note": "Ranked/limited sample; empty results do not establish absence of activity.",
        }
    except DuckDBUnavailable:
        return {
            "ok": False,
            "error": "DUCKDB_NOT_INSTALLED",
            "hint": "Install the optional Python package duckdb to run archive queries locally.",
            "columns": [],
            "rows": [],
            "lines": [],
            "row_count": 0,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "sql": spec["sql"],
            "url": spec["url"],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "POLYMARKET_QUERY",
            "hint": _error_message(exc),
            "columns": [],
            "rows": [],
            "lines": [],
            "row_count": 0,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "sql": spec["sql"],
            "url": spec["url"],
        }


def _initial_state() -> dict[str, Any]:
    day, hour = _utc_defaults()
    return {
        "state": "idle",
        "preset": "SUMMARY",
        "date": day,
        "hour": hour,
        "slug": "",
        "source": SOURCE_LABEL,
        "url": "",
        "sql": "",
        "result": None,
        "error": "",
        "note": "Select one UTC archive hour. No query runs until RUN QUERY is pressed.",
    }


_lock = threading.RLock()
_state = _initial_state()
_generation = 0


def _snapshot_locked() -> dict[str, Any]:
    result = _state.get("result")
    if isinstance(result, dict):
        result = dict(result)
        result["rows"] = list(result.get("rows") or [])[:MAX_ROWS]
        result["lines"] = list(result.get("lines") or [])[:MAX_ROWS + 1]
    return {
        "state": str(_state.get("state") or "idle"),
        "preset": str(_state.get("preset") or "SUMMARY"),
        "date": str(_state.get("date") or ""),
        "hour": str(_state.get("hour") or ""),
        "slug": str(_state.get("slug") or ""),
        "source": SOURCE_LABEL,
        "url": str(_state.get("url") or ""),
        "sql": str(_state.get("sql") or ""),
        "result": result,
        "error": str(_state.get("error") or ""),
        "note": str(_state.get("note") or ""),
        "duckdb": duckdb_available(),
        "budget": {"memory": MEMORY_LIMIT, "threads": 2, "timeout_seconds": QUERY_TIMEOUT_SECONDS, "max_source_bytes": MAX_SOURCE_BYTES},
        "poly_data": {
            "repo": REPO_URL,
            "state": "OPTIONAL · NOT STARTED",
            "note": (
                "poly_data sync needs its own Envio HYPERSYNC_API and is never "
                "started by this read-only panel."
            ),
        },
    }


def snapshot() -> dict[str, Any]:
    with _lock:
        return _snapshot_locked()


def _run_async(
    token: int,
    spec: dict[str, Any],
    executor: QueryExecutor | None,
) -> None:
    global _worker_running
    result = run_query(
        spec["preset"],
        spec["date"],
        spec["hour"],
        spec["slug"],
        executor=executor,
    )
    with _lock:
        _worker_running = False
        if _cancel.is_set():
            _state["state"] = "cancelled"
            _state["note"] = "Query cancelled. The worker has stopped."
            return
        if token != _generation:
            return
        _state["result"] = result
        _state["sql"] = result.get("sql", spec["sql"])
        _state["state"] = "done" if result.get("ok") else "error"
        _state["error"] = str(result.get("error") or "")
        _state["note"] = (
            "Query complete. Results are observational only."
            if result.get("ok")
            else str(result.get("hint") or "Query could not run.")
        )


def start_query(
    preset: Any,
    query_date: Any,
    hour: Any,
    slug: Any = "",
    *,
    executor: QueryExecutor | None = None,
) -> dict[str, Any]:
    """Start a single bounded query after validating all user inputs."""

    global _generation, _state, _worker_running
    with _lock:
        if _worker_running:
            return _snapshot_locked()
    try:
        spec = query_spec(preset, query_date, hour, slug)
    except ValueError as exc:
        with _lock:
            _generation += 1
            _state = _initial_state()
            _state.update(
                {
                    "state": "error",
                    "preset": str(preset or "").strip().upper(),
                    "date": str(query_date or "").strip(),
                    "hour": str(hour or "").strip(),
                    "slug": str(slug or "").strip(),
                    "error": str(exc),
                    "note": "Choose a valid UTC date, hour and market slug.",
                }
            )
            return _snapshot_locked()
    with _lock:
        if _worker_running:
            return _snapshot_locked()
        _cancel.clear()
        _worker_running = True
        _generation += 1
        token = _generation
        _state = _initial_state()
        _state.update(
            {
                "state": "running",
                **spec,
                "result": None,
                "error": "",
                "note": "Reading only the selected UTC archive hour…",
            }
        )
        thread = threading.Thread(
            target=_run_async,
            args=(token, spec, executor),
            name="gg-polymarket-query",
            daemon=True,
        )
        thread.start()
        return _snapshot_locked()


def reset() -> dict[str, Any]:
    global _generation, _state
    with _lock:
        _generation += 1
        _cancel.set()
        _state = _initial_state()
        if _worker_running:
            _state["state"] = "cancelling"
            _state["note"] = "Stopping the query worker…"
        with _process_lock:
            if _active_process is not None and _active_process.poll() is None:
                _active_process.kill()
        return _snapshot_locked()


def reset_for_tests() -> None:
    reset()


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    try:
        columns, rows = _duckdb_in_process(sys.stdin.read(65537))
        payload = {"columns": columns, "rows": _json_value(rows)}
    except Exception as exc:
        payload = {"error": _error_message(exc)}
    sys.stdout.write(json.dumps(payload, allow_nan=False))
