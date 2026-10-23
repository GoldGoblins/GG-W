"""Read-only portfolio presentation. Missing prices never become zero prices."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def change_24h(chart: dict[str, Any]) -> float | None:
    """Compare candle endpoints exactly 24 hours apart; gaps are not a 24h return."""
    closes, times = chart.get("closes") or [], chart.get("times") or []
    if not closes or len(closes) != len(times):
        return None
    end, last = number(times[-1]), number(closes[-1])
    if end is None or last is None or last <= 0:
        return None
    target = end - 86400
    for timestamp, close in zip(reversed(times), reversed(closes)):
        if number(timestamp) == target:
            start = number(close)
            return float((last / start - 1) * 100) if start is not None and start > 0 else None
    return None


def summarize(holdings: list[dict[str, Any]], chart: dict[str, Any], *,
              native_symbol: str = "SOL", usd_sek: Any = None) -> dict[str, Any]:
    """Aggregate accounts by mint, preserving exact quantities and price coverage.

    Only the native asset receives this chart's price. Additional tokens require
    their own numeric price_usd and price_source, never a peg or ticker guess.
    """
    closes = chart.get("closes") or []
    native_price = number(chart.get("price"))
    if native_price is None or native_price <= 0:
        native_price = number(closes[-1]) if closes else None
    source = str(chart.get("source") or "")
    native_change = change_24h(chart) if source and native_price is not None and native_price > 0 else None
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for index, holding in enumerate(holdings):
        mint = str(holding.get("mint") or "")
        # Unknown identifiers remain distinct; equal tickers do not imply equal assets.
        key = (mint or f"unknown-{index}", str(holding.get("program") or ""))
        quantity = number(holding.get("display"))
        if quantity is not None and quantity < 0:
            quantity = None
        is_native = mint == "native" and holding.get("symbol") == native_symbol
        price = native_price if is_native else number(holding.get("price_usd"))
        price_source = source if is_native else str(holding.get("price_source") or "")
        if price is None or price <= 0 or not price_source:
            price = None
        change = native_change if is_native else number(holding.get("change_24h_pct"))
        symbol = str(holding.get("symbol") or (mint[:4] + "…" + mint[-4:] if mint else "TOKEN"))
        row = groups.get(key)
        if row is None:
            row = {"symbol": symbol, "name": str(holding.get("name") or
                   ({"SOL": "Solana", "KAS": "Kaspa"}.get(native_symbol, native_symbol) if is_native else symbol)),
                   "mint": mint, "quantity": quantity, "price": price,
                   "price_source": price_source, "change_24h_pct": change,
                   "stale": bool(chart.get("stale", True)) if is_native else bool(holding.get("price_stale", True))}
            groups[key] = row
        else:
            row["quantity"] = row["quantity"] + quantity if row["quantity"] is not None and quantity is not None else None
            # Conflicting account metadata cannot supply a trustworthy combined value.
            if row["price"] != price or row["price_source"] != price_source:
                row["price"] = None
            if row["change_24h_pct"] != change:
                row["change_24h_pct"] = None
            row["stale"] = row["stale"] or (bool(chart.get("stale", True)) if is_native else bool(holding.get("price_stale", True)))
    rows, total, missing, unknown_balance, valued, stale_count = [], Decimal(0), 0, 0, 0, 0
    for row in groups.values():
        quantity, price = row.pop("quantity"), row.pop("price")
        value = quantity * price if quantity is not None and price is not None else None
        missing += int(price is None)
        unknown_balance += int(quantity is None)
        if value is not None:
            valued += 1
            total += value
            stale_count += int(row["stale"])
        row.update({"quantity_text": format(quantity, "f") if quantity is not None else "—",
                    "price_usd": float(price) if price is not None else None,
                    "value_usd": float(value) if value is not None else None,
                    "change_24h_pct": float(row["change_24h_pct"]) if row["change_24h_pct"] is not None else None})
        rows.append(row)
    rows.sort(key=lambda row: (row["value_usd"] is None, -(row["value_usd"] or 0), row["symbol"]))
    priced = len(rows) - missing
    fx = number(usd_sek)
    return {"assets": rows, "value_usd": float(total) if valued else None,
            "value_sek": float(total * fx) if valued and fx is not None and fx > 0 else None,
            "priced_count": priced, "unpriced_count": missing, "stale_count": stale_count,
            "valued_count": valued, "unknown_balance_count": unknown_balance,
            "complete": valued == len(rows) and bool(rows), "change_24h_pct": native_change,
            "price_usd": float(native_price) if native_price is not None and native_price > 0 and source else None,
            "source": source, "stale": bool(chart.get("stale", True))}
