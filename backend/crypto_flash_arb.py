"""Paper atomic arb on two constant-product pools, with a Jito-style tip.

Borrow quote → swap the cheap pool → swap the rich pool → repay + fee.
Size is searched, not guessed. A competitive bundle gives about half the
gross to the tip (the public 2026 band starts at 50% and runs to 70%).
The minimum tip is 1000 lamports plus a base signature fee. If the tip
eats the edge, the snapshot is dropped. Pools live in local state only.
Not a live searcher, not a sandwich, not mainnet.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.crypto_contract import ensure_state_dir, format_units

SOL_DECIMALS = 9
USD_DECIMALS = 6
SOL_SCALE = 10**SOL_DECIMALS
USD_SCALE = 10**USD_DECIMALS
SWAP_FEE_BPS = 30
FLASH_FEE_BPS = 9
# Half the gross. Below this, a competitive Jito auction does not land.
TIP_SHARE_BPS = 5000
MIN_TIP_LAMPORTS = 1000
BASE_FEE_LAMPORTS = 5000
POOLS_NAME = "arb-pools.json"


def pools_path() -> Path:
    return ensure_state_dir() / POOLS_NAME


def _default_pools() -> dict[str, Any]:
    return {
        "A": {
            "sol": 1000 * SOL_SCALE,
            "usd": 100_000 * USD_SCALE,
        },
        "B": {
            "sol": 1000 * SOL_SCALE,
            "usd": 102_000 * USD_SCALE,
        },
        "fee_bps": SWAP_FEE_BPS,
        "flash_bps": FLASH_FEE_BPS,
    }


def load_pools() -> dict[str, Any]:
    path = pools_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = _default_pools()
        save_pools(payload)
        return payload
    if not isinstance(payload, dict) or "A" not in payload or "B" not in payload:
        payload = _default_pools()
        save_pools(payload)
    return payload


def save_pools(payload: dict[str, Any]) -> None:
    path = pools_path()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def reset_pools() -> dict[str, Any]:
    payload = _default_pools()
    save_pools(payload)
    return payload


def price_usd_per_sol(pool: dict[str, Any]) -> str:
    sol = int(pool["sol"])
    usd = int(pool["usd"])
    if sol == 0:
        return "—"
    q = (usd * SOL_SCALE) // sol
    whole, frac = divmod(q, USD_SCALE)
    return str(whole) + "." + f"{frac:06d}"


def _swap_usd_for_sol(pool: dict[str, Any], usd_in: int, fee_bps: int) -> int:
    if usd_in <= 0:
        raise ValueError("CRYPTO_ARB_SIZE")
    x = int(pool["sol"])
    y = int(pool["usd"])
    taxed = usd_in * (10_000 - fee_bps) // 10_000
    if taxed <= 0:
        raise ValueError("CRYPTO_ARB_FEE")
    sol_out = x * taxed // (y + taxed)
    if sol_out <= 0 or sol_out >= x:
        raise ValueError("CRYPTO_ARB_SWAP")
    pool["usd"] = y + usd_in
    pool["sol"] = x - sol_out
    return sol_out


def _swap_sol_for_usd(pool: dict[str, Any], sol_in: int, fee_bps: int) -> int:
    if sol_in <= 0:
        raise ValueError("CRYPTO_ARB_SIZE")
    x = int(pool["sol"])
    y = int(pool["usd"])
    taxed = sol_in * (10_000 - fee_bps) // 10_000
    if taxed <= 0:
        raise ValueError("CRYPTO_ARB_FEE")
    usd_out = y * taxed // (x + taxed)
    if usd_out <= 0 or usd_out >= y:
        raise ValueError("CRYPTO_ARB_SWAP")
    pool["sol"] = x + sol_in
    pool["usd"] = y - usd_out
    return usd_out


def _pool_px(pool: dict[str, Any]) -> int:
    sol = int(pool["sol"])
    if sol <= 0:
        return 0
    return int(pool["usd"]) * SOL_SCALE // sol


def _tip_usd(gross_usd: int, usd_per_sol: int) -> int:
    """Tip in USD atoms. Share of gross, never below the lamport floor."""
    if gross_usd <= 0 or usd_per_sol <= 0:
        return 0
    share = gross_usd * TIP_SHARE_BPS // 10_000
    floor = (MIN_TIP_LAMPORTS + BASE_FEE_LAMPORTS) * usd_per_sol // SOL_SCALE
    return max(share, floor)


def quote_flash_arb(usd_borrow: int, pools: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = json.loads(json.dumps(pools or load_pools()))
    fee_bps = int(snapshot.get("fee_bps") or SWAP_FEE_BPS)
    flash_bps = int(snapshot.get("flash_bps") or FLASH_FEE_BPS)
    a = dict(snapshot["A"])
    b = dict(snapshot["B"])
    price_a = _pool_px(a)
    price_b = _pool_px(b)
    mid_px = (price_a + price_b) // 2
    cheap, rich = ("A", "B") if price_a <= price_b else ("B", "A")
    buy_pool = a if cheap == "A" else b
    sell_pool = b if rich == "B" else a
    sol_bought = _swap_usd_for_sol(buy_pool, usd_borrow, fee_bps)
    usd_out = _swap_sol_for_usd(sell_pool, sol_bought, fee_bps)
    repay = usd_borrow + (usd_borrow * flash_bps + 9999) // 10_000
    gross = usd_out - repay
    tip = _tip_usd(gross, mid_px)
    net = gross - tip
    if gross <= 0:
        error = "NO_PROFIT"
    elif net <= 0:
        error = "TIP_EATS_EDGE"
    else:
        error = ""
    return {
        "borrow_usd": usd_borrow,
        "repay_usd": repay,
        "sol_bought": sol_bought,
        "usd_out": usd_out,
        "gross_usd": gross,
        "tip_usd": tip,
        "tip_share_bps": TIP_SHARE_BPS,
        "profit_usd": net,
        "buy_pool": cheap,
        "sell_pool": rich,
        "price_a": price_usd_per_sol(snapshot["A"]),
        "price_b": price_usd_per_sol(snapshot["B"]),
        "ok": net > 0,
        "error": error,
        "snapshot": {
            "A": a,
            "B": b,
            "fee_bps": fee_bps,
            "flash_bps": flash_bps,
        },
    }


def optimal_borrow(pools: dict[str, Any] | None = None) -> int:
    """Largest net after the tip, searching a geometric size ladder."""
    snapshot = json.loads(json.dumps(pools or load_pools()))
    thin = min(int(snapshot["A"]["usd"]), int(snapshot["B"]["usd"]))
    cap = max(USD_SCALE, thin // 20)
    best = 0
    best_net = 0
    steps = 16
    for step in range(steps):
        if steps == 1:
            borrow = cap
        else:
            growth = (cap / float(USD_SCALE)) ** (step / float(steps - 1))
            borrow = int(USD_SCALE * growth)
        borrow = max(USD_SCALE, min(cap, borrow))
        try:
            quoted = quote_flash_arb(borrow, snapshot)
        except ValueError:
            continue
        net = int(quoted.get("profit_usd") or 0)
        if quoted.get("ok") and net > best_net:
            best_net = net
            best = borrow
    return best


def swap_usd_for_sol(usd_in: int) -> dict[str, Any]:
    amount = int(usd_in)
    if amount <= 0:
        raise ValueError("CRYPTO_ARB_SIZE")
    pools = load_pools()
    fee = int(pools.get("fee_bps") or SWAP_FEE_BPS)
    snapshot = json.loads(json.dumps(pools))
    buy = dict(snapshot["A"])
    sol_out = _swap_usd_for_sol(buy, amount, fee)
    snapshot["A"] = buy
    save_pools(snapshot)
    return {
        "usd": amount,
        "sol": sol_out,
        "venue": "cpmm-A",
        "price": price_usd_per_sol(buy),
    }


def swap_sol_for_usd(sol_in: int) -> dict[str, Any]:
    amount = int(sol_in)
    if amount <= 0:
        raise ValueError("CRYPTO_ARB_SIZE")
    pools = load_pools()
    fee = int(pools.get("fee_bps") or SWAP_FEE_BPS)
    snapshot = json.loads(json.dumps(pools))
    sell = dict(snapshot["A"])
    usd_out = _swap_sol_for_usd(sell, amount, fee)
    snapshot["A"] = sell
    save_pools(snapshot)
    return {
        "sol": amount,
        "usd": usd_out,
        "venue": "cpmm-A",
        "price": price_usd_per_sol(sell),
    }


def commit_flash_arb(usd_borrow: int) -> dict[str, Any]:
    current = load_pools()
    quoted = quote_flash_arb(usd_borrow, current)
    if not quoted["ok"]:
        quoted["error"] = str(quoted.get("error") or "NO_PROFIT")
        quoted["committed"] = False
        return quoted
    save_pools(quoted["snapshot"])
    quoted["committed"] = True
    quoted["price_a_after"] = price_usd_per_sol(quoted["snapshot"]["A"])
    quoted["price_b_after"] = price_usd_per_sol(quoted["snapshot"]["B"])
    return quoted


def pool_status() -> dict[str, Any]:
    pools = load_pools()
    borrow = optimal_borrow(pools)
    quote: dict[str, Any] = {}
    if borrow > 0:
        try:
            quote = quote_flash_arb(borrow, pools)
        except ValueError:
            quote = {}
    return {
        "price_a": price_usd_per_sol(pools["A"]),
        "price_b": price_usd_per_sol(pools["B"]),
        "sol_a": pools["A"]["sol"],
        "sol_b": pools["B"]["sol"],
        "usd_a": pools["A"]["usd"],
        "usd_b": pools["B"]["usd"],
        "fee_bps": pools.get("fee_bps", SWAP_FEE_BPS),
        "flash_bps": pools.get("flash_bps", FLASH_FEE_BPS),
        "tip_share_bps": TIP_SHARE_BPS,
        "optimal_ok": bool(quote.get("ok")),
        "optimal_usd": format_units(borrow, USD_DECIMALS) if borrow else "—",
        "optimal_tip": format_units(quote.get("tip_usd"), USD_DECIMALS) if quote else "—",
        "optimal_net": format_units(quote.get("profit_usd"), USD_DECIMALS) if quote else "—",
        "optimal_drop": str(quote.get("error") or ""),
        "buy_pool": quote.get("buy_pool") or "",
        "sell_pool": quote.get("sell_pool") or "",
    }
