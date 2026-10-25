#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_contract, crypto_flash_arb


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gg-arb-"))
    crypto_contract.STATE_DIR = tmp
    crypto_flash_arb.reset_pools()
    sized = crypto_flash_arb.optimal_borrow()
    if sized <= 0:
        raise AssertionError("seeded gap must have an optimal size")
    best = crypto_flash_arb.quote_flash_arb(sized)
    if not best.get("ok") or int(best["profit_usd"]) <= 0:
        raise AssertionError("optimal size must clear the tip")
    if int(best["tip_usd"]) * 2 + 1 < int(best["gross_usd"]):
        raise AssertionError("tip share should be at least half the gross when the floor is not binding")
    first = crypto_flash_arb.commit_flash_arb(10 * 1_000_000)
    if not first.get("ok") or not first.get("committed"):
        raise AssertionError("seeded arb must profit: " + json.dumps(first)[:400])
    if int(first["profit_usd"]) <= 0:
        raise AssertionError("profit")
    if int(first["tip_usd"]) <= 0 or int(first["profit_usd"]) >= int(first["gross_usd"]):
        raise AssertionError("tip must take a share and leave a smaller net")
    equal = {
        "A": {"sol": 1000 * 10**9, "usd": 100_000 * 10**6},
        "B": {"sol": 1000 * 10**9, "usd": 100_000 * 10**6},
        "fee_bps": 30,
        "flash_bps": 9,
    }
    crypto_flash_arb.save_pools(equal)
    dead = crypto_flash_arb.commit_flash_arb(10 * 1_000_000)
    if dead.get("ok") or dead.get("committed"):
        raise AssertionError("equal pools must revert")
    if dead.get("error") != "NO_PROFIT":
        raise AssertionError("error tag " + str(dead.get("error")))
    crypto_flash_arb.reset_pools()
    bought = crypto_flash_arb.swap_usd_for_sol(10 * 1_000_000)
    if int(bought.get("sol") or 0) <= 0:
        raise AssertionError("cpmm buy " + json.dumps(bought))
    sold = crypto_flash_arb.swap_sol_for_usd(int(bought["sol"]))
    if int(sold.get("usd") or 0) <= 0:
        raise AssertionError("cpmm sell " + json.dumps(sold))
    zero = crypto_flash_arb._default_pools()
    zero.update(fee_bps=0, flash_bps=0)
    uncharged = crypto_flash_arb.quote_flash_arb(10 * 1_000_000, zero)
    if uncharged["repay_usd"] != 10 * 1_000_000:
        raise AssertionError("explicit zero flash fee must remain zero")
    if uncharged["snapshot"]["fee_bps"] != 0 or uncharged["snapshot"]["flash_bps"] != 0:
        raise AssertionError("explicit zero fees were replaced by defaults")
    crypto_flash_arb.save_pools(zero)
    fresh_buy = crypto_flash_arb.swap_usd_for_sol(10 * 1_000_000)
    expected_sol = zero["A"]["sol"] * (10 * 1_000_000) // (zero["A"]["usd"] + 10 * 1_000_000)
    if fresh_buy["sol"] != expected_sol:
        raise AssertionError("zero-fee swap must use untaxed input")
    for bad in (True, 1.5, "100"):
        for action in (crypto_flash_arb.quote_flash_arb, crypto_flash_arb.swap_usd_for_sol,
                       crypto_flash_arb.swap_sol_for_usd):
            try:
                action(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("atomic size must reject noninteger values")
    malformed = json.loads(json.dumps(zero))
    malformed["fee_bps"] = True
    try:
        crypto_flash_arb.quote_flash_arb(10000, malformed)
    except ValueError:
        pass
    else:
        raise AssertionError("boolean fee rate must not be coerced to integer")
    print("CRYPTO_FLASH_ARB_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
