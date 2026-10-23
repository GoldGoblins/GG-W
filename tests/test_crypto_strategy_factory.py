#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_strategy_factory as factory


def main() -> int:
    prices = []
    for index in range(300):
        cycle = (index % 40) - 20
        prices.append(100.0 + (index * 0.08) + (cycle * 0.35))
    frames = {
        "1h": {
            "closes": prices,
            "times": [1_700_000_000 + index * 3600 for index in range(len(prices))],
        }
    }
    report = factory.run_factory(frames)
    assert report["schema"] == factory.SCHEMA
    assert report["state"] == "DONE"
    assert report["mode"] == "PAPER_ONLY"
    assert report["source"]["interval"] == "1h"
    assert report["source"]["bars"] == len(prices)
    assert len(report["candidates"]) == 5
    assert report["autoresearch"]["pattern"] == "KEEP_OR_REVERT"
    assert len(report["autoresearch"]["steps"]) == 4
    assert isinstance(report["graveyard"], list)
    ids = {row["id"] for row in report["candidates"]}
    assert "VOL_REGIME_SIZE" in ids
    assert report["orchestration"]["max_parallel"] == 2
    assert report["orchestration"]["model_agents"] is False
    for candidate in report["candidates"]:
        assert candidate["verdict"] in {"PASS", "WATCH", "REJECT", "INSUFFICIENT_DATA"}
        for key in ("train", "validation", "test"):
            assert "return_pct" in candidate[key]
            assert "max_drawdown_pct" in candidate[key]

    short = factory.run_factory({"1h": {"closes": prices[:50]}})
    assert short["state"] == "DONE"
    assert all(
        row["verdict"] == "INSUFFICIENT_DATA"
        for row in short["candidates"]
    )

    empty = factory.run_factory({})
    assert empty["state"] == "ERROR"
    assert empty["orchestration"]["mode"] == "BOUNDED_DETERMINISTIC_WORKERS"
    print("test_crypto_strategy_factory: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
