#!/usr/bin/env python3
from __future__ import annotations

import math
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_vol


def _clustered_prices(n: int = 240) -> list[float]:
    price = 100.0
    out = [price]
    for index in range(1, n):
        if (index // 40) % 2 == 0:
            shock = 0.002 * math.sin(index / 7.0)
        else:
            shock = 0.03 * math.sin(index / 3.0)
        price = max(1.0, price * (1.0 + shock))
        out.append(price)
    return out


def main() -> int:
    quiet = [100.0 + (index * 0.01) for index in range(80)]
    assert crypto_vol.snapshot(quiet[:10])["ok"] is False

    prices = _clustered_prices()
    snap = crypto_vol.snapshot(prices)
    assert snap["schema"] == crypto_vol.SCHEMA
    assert snap["mode"] == "PAPER_ONLY"
    assert snap["ok"] is True
    assert snap["hmm"]["last_state"] in {"LOW", "HIGH"}
    assert snap["garch"]["last_sigma"] > 0
    high = crypto_vol.size_scale(0.04, 0.01, "HIGH")
    low = crypto_vol.size_scale(0.005, 0.01, "LOW")
    assert high < low
    assert crypto_vol.SIZE_FLOOR <= high <= crypto_vol.SIZE_CAP
    print("test_crypto_vol: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
