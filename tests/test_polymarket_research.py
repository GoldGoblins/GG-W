#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import polymarket_research as research


def main() -> int:
    valid_url = (
        "https://archive.pendulumflow.com/v3/2026-09-08/17/"
        "2026-09-08T17.parquet"
    )
    if research.archive_url("2026-09-08", "17") != valid_url:
        raise AssertionError("archive URL contract changed")
    if research.normalise_query("trades", "2026-09-08", "7")["hour"] != "07":
        raise AssertionError("hour normalization missing")

    for bad in (
        ("SUMMARY", "2026-02-30", "01", ""),
        ("SUMMARY", "2026-09-08", "24", ""),
        ("UNKNOWN", "2026-09-08", "01", ""),
        ("TOUCH", "2026-09-08", "01", ""),
        ("TOUCH", "2026-09-08", "01", "market;drop"),
    ):
        try:
            research.query_spec(*bad)
        except ValueError:
            continue
        raise AssertionError("invalid query input was accepted: " + repr(bad))

    seen_sql: list[str] = []

    def fake_executor(sql: str):
        seen_sql.append(sql)
        if "last_trade_price" in sql:
            return (
                ["at", "price", "size", "side", "market"],
                [("17:02:03", 0.42, 125.5, "BUY", b"\x01\x02")],
            )
        if "avg(best_ask - best_bid)" in sql:
            return (
                ["market", "spread", "bid", "ask", "quotes"],
                [("0x0102", 0.08, 0.41, 0.49, 12)],
            )
        if "best_bid_ask" in sql:
            return (["minute", "bid", "ask"], [("17:02", 0.41, 0.44)])
        return (
            ["event_type", "rows"],
            [("last_trade_price", 4), ("best_bid_ask", 2)],
        )

    summary = research.run_query(
        "SUMMARY", "2026-09-08", "17", executor=fake_executor
    )
    if not summary.get("ok") or summary.get("row_count") != 2:
        raise AssertionError("summary query fixture failed")
    if "EVENT TYPE" not in "\n".join(summary.get("lines") or []):
        raise AssertionError("summary formatter missing")

    trades = research.run_query(
        "TRADES", "2026-09-08", "17", executor=fake_executor
    )
    if not trades.get("ok") or "0x0102" not in "\n".join(trades.get("lines") or []):
        raise AssertionError("trade formatter or byte market missing")

    touch = research.run_query(
        "TOUCH",
        "2026-09-08",
        "17",
        "election-2026",
        executor=fake_executor,
    )
    if not touch.get("ok") or "MINUTE" not in "\n".join(touch.get("lines") or []):
        raise AssertionError("touch query fixture failed")
    scan = research.run_query(
        "SCAN", "2026-09-08", "17", executor=fake_executor
    )
    if not scan.get("ok") or "SPREAD" not in "\n".join(scan.get("lines") or []):
        raise AssertionError("scan query fixture failed")
    if len(seen_sql) != 4 or any(valid_url not in sql for sql in seen_sql):
        raise AssertionError("query did not stay on the selected archive file")
    if any("DROP" in sql.upper() for sql in seen_sql):
        raise AssertionError("arbitrary SQL entered the fixed query path")

    research.reset_for_tests()

    def slow_executor(sql: str):
        time.sleep(0.05)
        return fake_executor(sql)

    initial = research.start_query(
        "SUMMARY", "2026-09-08", "17", executor=slow_executor
    )
    if initial.get("state") not in ("running", "done"):
        raise AssertionError("async query did not start")
    deadline = time.monotonic() + 2.0
    final = research.snapshot()
    while time.monotonic() < deadline and final.get("state") == "running":
        time.sleep(0.01)
        final = research.snapshot()
    if final.get("state") != "done":
        raise AssertionError("async query did not finish: " + repr(final))
    if not ((final.get("result") or {}).get("ok")):
        raise AssertionError("async query result missing")

    qml = (PROJECT / "qml/components/CryptoSurface.qml").read_text(
        encoding="utf-8"
    )
    for marker in (
        '"POLY"',
        'text: "POLYMARKET RESEARCH"',
        'text: "PENDULUMFLOW V3  ·  REMOTE PARQUET  ·  READ ONLY"',
        "cryptoPolymarketQuery",
        "cryptoPolymarketStatus",
        "cryptoPolymarketReset",
        'text: "SQL PREVIEW\\n"',
        "poly_data",
        'text: "SCAN"',
    ):
        if marker not in qml:
            raise AssertionError("Crypto QML marker missing: " + marker)

    host = (PROJECT / "backend/crypto_host.py").read_text(encoding="utf-8")
    bridge = (PROJECT / "backend/chat_surface_host.py").read_text(
        encoding="utf-8"
    )
    for marker in (
        '"polymarket": polymarket_research.snapshot()',
        "def start_polymarket_query",
        "def poll_polymarket_query",
        "def reset_polymarket_query",
    ):
        if marker not in host:
            raise AssertionError("crypto host marker missing: " + marker)
    for marker in (
        "def cryptoPolymarketQuery",
        "def cryptoPolymarketStatus",
        "def cryptoPolymarketReset",
    ):
        if marker not in bridge:
            raise AssertionError("Qt bridge marker missing: " + marker)

    research.reset_for_tests()
    print("POLYMARKET_RESEARCH_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

