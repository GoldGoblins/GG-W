"""Bounded offline paper fills using explicit decoded market snapshots.

No live execution, wallet, clock reads or RPC. A fill consumes only the
snapshot available at its timestamp. Balances and cost basis use atoms;
equity marks are executable liquidation estimates, not future candle closes.
Persistence belongs to the caller's existing atomic state writer.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.crypto_pump_quotes import U64_MAX, _integer, quote

MAX_FILLS = 2000
MAX_POSITIONS = 128
MAX_EVENTS = 2000
MAX_SNAPSHOT_AGE_MS = 60_000
WSOL = "So11111111111111111111111111111111111111112"


def new_state(cash_atoms: int, *, quote_mint: str = WSOL, timestamp_ms: int = 0) -> dict:
    if not isinstance(quote_mint, str) or not 1 <= len(quote_mint) <= 64:
        raise ValueError("PUMP_PAPER_QUOTE_MINT")
    return {"version": 1, "mode": "PAPER", "quote_mint": quote_mint,
            "initial_cash_atoms": str(_integer(cash_atoms, "cash")),
            "cash_atoms": str(_integer(cash_atoms, "cash")),
            "realized_pnl_atoms": "0", "slippage_cost_atoms": "0",
            "last_timestamp_ms": _integer(timestamp_ms, "timestamp"),
            "positions": {}, "fills": []}


def validate_state(state: dict) -> dict:
    if (not isinstance(state, dict) or type(state.get("version")) is not int
            or state.get("version") != 1 or state.get("mode") != "PAPER"):
        raise ValueError("PUMP_PAPER_STATE")
    result = deepcopy(state)
    if not isinstance(result.get("quote_mint"), str) or not 1 <= len(result["quote_mint"]) <= 64:
        raise ValueError("PUMP_PAPER_QUOTE_MINT")
    for key in ("initial_cash_atoms", "cash_atoms", "slippage_cost_atoms"):
        _integer(result.get(key), key)
    _integer(result.get("realized_pnl_atoms"), "realized_pnl", -U64_MAX, U64_MAX)
    result["last_timestamp_ms"] = _integer(result.get("last_timestamp_ms"), "timestamp")
    positions, fills = result.get("positions"), result.get("fills")
    if not isinstance(positions, dict) or len(positions) > MAX_POSITIONS:
        raise ValueError("PUMP_PAPER_POSITIONS")
    if not isinstance(fills, list) or len(fills) > MAX_FILLS:
        raise ValueError("PUMP_PAPER_FILLS")
    for key, position in positions.items():
        if not isinstance(key, str) or not key or len(key) > 128 or not isinstance(position, dict):
            raise ValueError("PUMP_PAPER_POSITION")
        for field in ("base_atoms", "cost_atoms"):
            _integer(position.get(field), field)
        if not isinstance(position.get("base_mint"), str):
            raise ValueError("PUMP_PAPER_BASE_MINT")
    previous = -1
    for fill in fills:
        if not isinstance(fill, dict):
            raise ValueError("PUMP_PAPER_FILL")
        timestamp = _integer(fill.get("timestamp_ms"), "timestamp")
        if timestamp < previous or timestamp > result["last_timestamp_ms"]:
            raise ValueError("PUMP_PAPER_FILL_ORDER")
        previous = timestamp
        if fill.get("side") not in ("buy_exact_in", "buy_exact_out", "sell_exact_in", "sell_exact_out"):
            raise ValueError("PUMP_PAPER_FILL_SIDE")
        for field in ("debit_atoms", "received_atoms"):
            _integer(fill.get(field), field, 1)
    return result


def _market_at(market: dict, timestamp_ms: int, quote_mint: str) -> str:
    if not isinstance(market, dict):
        raise ValueError("PUMP_PAPER_MARKET")
    identity = market.get("market_id", market.get("address"))
    if not isinstance(identity, str) or not 1 <= len(identity) <= 128:
        raise ValueError("PUMP_PAPER_MARKET_ID")
    observed = _integer(market.get("timestamp_ms"), "snapshot_timestamp")
    if observed > timestamp_ms:
        raise ValueError("PUMP_PAPER_FUTURE_SNAPSHOT")
    if timestamp_ms - observed > MAX_SNAPSHOT_AGE_MS:
        raise ValueError("PUMP_PAPER_STALE_SNAPSHOT")
    if market.get("quote_mint", WSOL) != quote_mint:
        raise ValueError("PUMP_PAPER_QUOTE_MISMATCH")
    if not isinstance(market.get("base_mint"), str) or not 1 <= len(market["base_mint"]) <= 64:
        raise ValueError("PUMP_PAPER_BASE_MINT")
    return identity


def execute(state: dict, market: dict, side: str, amount_atoms: int,
            slippage_bps: int = 100, *, timestamp_ms: int,
            expected_quote: dict | None = None) -> dict:
    """Return a new state and fill; failure leaves every input unchanged.

    expected_quote, when supplied, provides the original wallet slippage
    bounds. The fill is re-quoted at the supplied current snapshot. No candle
    high/low, later bar, or assumed zero-price asset can fund this account.
    """
    result = validate_state(state)
    timestamp = _integer(timestamp_ms, "timestamp")
    if timestamp < result["last_timestamp_ms"]:
        raise ValueError("PUMP_PAPER_TIME_REVERSED")
    identity = _market_at(market, timestamp, result["quote_mint"])
    if len(result["fills"]) >= MAX_FILLS:
        raise ValueError("PUMP_PAPER_FILL_LIMIT")
    actual = quote(market, side, amount_atoms, slippage_bps)
    debit, received = int(actual["debit_atoms"]), int(actual["received_atoms"])
    buy = actual["side"].startswith("buy")
    position = result["positions"].get(identity, {
        "base_atoms": "0", "cost_atoms": "0", "base_mint": market["base_mint"]})
    if position["base_mint"] != market["base_mint"]:
        raise ValueError("PUMP_PAPER_TARGET_CHANGED")
    amount, cost = int(position["base_atoms"]), int(position["cost_atoms"])
    cash = int(result["cash_atoms"])
    slippage_cost = 0
    if expected_quote is not None:
        if not isinstance(expected_quote, dict) or expected_quote.get("side") != actual["side"]:
            raise ValueError("PUMP_PAPER_EXPECTED_QUOTE")
        if expected_quote.get("amount_atoms") != str(amount_atoms):
            raise ValueError("PUMP_PAPER_EXPECTED_QUOTE")
        minimum = _integer(expected_quote.get("min_received_atoms"), "min_received", 1)
        maximum = _integer(expected_quote.get("max_debit_atoms"), "max_debit", 1)
        if debit > maximum or received < minimum:
            raise ValueError("PUMP_PAPER_SLIPPAGE_EXCEEDED")
        prior_debit = _integer(expected_quote.get("debit_atoms"), "prior_debit", 1)
        prior_received = _integer(expected_quote.get("received_atoms"), "prior_received", 1)
        # Quote-denominated adverse execution cost; do not mix base and quote atoms.
        slippage_cost = (max(0, debit - prior_debit) if buy and actual["side"].endswith("exact_out")
                         else max(0, (prior_received - received) * prior_debit // prior_received) if buy
                         else max(0, (debit - prior_debit) * prior_received // prior_debit)
                         if actual["side"].endswith("exact_out")
                         else max(0, prior_received - received))
    realized = 0
    if buy:
        if debit > cash:
            raise ValueError("PUMP_PAPER_INSUFFICIENT_CASH")
        if identity not in result["positions"] and len(result["positions"]) >= MAX_POSITIONS:
            raise ValueError("PUMP_PAPER_POSITION_LIMIT")
        cash -= debit
        amount = _integer(amount + received, "position")
        cost = _integer(cost + debit, "cost")
    else:
        if debit > amount:
            raise ValueError("PUMP_PAPER_INSUFFICIENT_POSITION")
        removed_cost = cost if debit == amount else cost * debit // amount
        amount -= debit
        cost -= removed_cost
        cash = _integer(cash + received, "cash")
        realized = received - removed_cost
    result["cash_atoms"] = str(cash)
    result["realized_pnl_atoms"] = str(_integer(
        int(result["realized_pnl_atoms"]) + realized, "realized_pnl", -U64_MAX, U64_MAX))
    result["slippage_cost_atoms"] = str(_integer(
        int(result["slippage_cost_atoms"]) + slippage_cost, "slippage_cost"))
    if amount:
        result["positions"][identity] = {"base_atoms": str(amount), "cost_atoms": str(cost),
                                          "base_mint": market["base_mint"]}
    else:
        result["positions"].pop(identity, None)
    result["last_timestamp_ms"] = timestamp
    fill = {"number": len(result["fills"]) + 1, "timestamp_ms": timestamp,
            "snapshot_timestamp_ms": market["timestamp_ms"], "market_id": identity,
            "base_mint": market["base_mint"], "side": actual["side"],
            "debit_atoms": str(debit), "received_atoms": str(received),
            "fee_breakdown": actual["fee_breakdown"], "realized_pnl_atoms": str(realized),
            "slippage_cost_atoms": str(slippage_cost), "price_impact_bps": actual["price_impact_bps"],
            "limits": actual["limits"]}
    result["fills"].append(fill)
    return {"state": result, "fill": fill, "quote": actual,
            "post_market": actual["post_market"]}


def snapshot(state: dict, marks: dict[str, dict] | None = None, *, timestamp_ms: int | None = None) -> dict:
    """Liquidation equity; unavailable marks remain unknown, never zero."""
    state = validate_state(state)
    timestamp = state["last_timestamp_ms"] if timestamp_ms is None else _integer(timestamp_ms, "timestamp")
    if timestamp < state["last_timestamp_ms"]:
        raise ValueError("PUMP_PAPER_TIME_REVERSED")
    marks = {} if marks is None else marks
    if not isinstance(marks, dict) or len(marks) > MAX_POSITIONS:
        raise ValueError("PUMP_PAPER_MARKS")
    equity = int(state["cash_atoms"])
    marked, missing = {}, []
    for identity, position in state["positions"].items():
        try:
            market = marks[identity]
            if _market_at(market, timestamp, state["quote_mint"]) != identity:
                raise ValueError("PUMP_PAPER_TARGET_CHANGED")
            if market["base_mint"] != position["base_mint"]:
                raise ValueError("PUMP_PAPER_TARGET_CHANGED")
            value = int(quote(market, "sell", int(position["base_atoms"]), 0)["received_atoms"])
            marked[identity] = str(value)
            equity += value
        except (KeyError, ValueError):
            missing.append(identity)
    return {"mode": "PAPER", "cash_atoms": state["cash_atoms"],
            "equity_atoms": None if missing else str(equity),
            "pnl_atoms": None if missing else str(equity - int(state["initial_cash_atoms"])),
            "realized_pnl_atoms": state["realized_pnl_atoms"],
            "slippage_cost_atoms": state["slippage_cost_atoms"],
            "position_values_atoms": marked, "unpriced_positions": missing,
            "positions": state["positions"], "fill_count": len(state["fills"]),
            "timestamp_ms": timestamp, "limits": ["offline single-market fills", "network fees, rent and MEV excluded"]}


def replay(initial_state: dict, events: list[dict]) -> dict:
    """Replay an ordered, bounded recorded tape; no generated future bars."""
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("PUMP_PAPER_EVENT_LIMIT")
    state = validate_state(initial_state)
    marks = {}
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("PUMP_PAPER_EVENT")
        if event.get("type", "trade") == "mark":
            timestamp = _integer(event.get("timestamp_ms"), "timestamp")
            if timestamp < state["last_timestamp_ms"]:
                raise ValueError("PUMP_PAPER_TIME_REVERSED")
            identity = _market_at(event.get("market"), timestamp, state["quote_mint"])
            marks[identity] = deepcopy(event["market"])
            state["last_timestamp_ms"] = timestamp
        elif event.get("type", "trade") == "trade":
            execution = execute(state, event.get("market"), event.get("side"),
                                event.get("amount_atoms"), event.get("slippage_bps", 100),
                                timestamp_ms=event.get("timestamp_ms"),
                                expected_quote=event.get("expected_quote"))
            state = execution["state"]
            marks[execution["fill"]["market_id"]] = execution["post_market"]
        else:
            raise ValueError("PUMP_PAPER_EVENT_TYPE")
    return {"state": state, "summary": snapshot(state, marks)}
