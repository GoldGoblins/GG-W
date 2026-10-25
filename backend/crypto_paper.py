"""Persistent closed-bar paper accounts for all strategies. No signer or orders.

State, cursor and events commit together. Strategy checkpoints survive a rolling
data window; old candles are not replayed as new trades after an app restart.
"""
from __future__ import annotations

import json
from backend.platform_support import file_locks as fcntl
from backend.platform_files import sync_directory
from contextlib import contextmanager
import math
import os
import threading
import time
from typing import Any

from backend import crypto_backtest, crypto_bots, crypto_data
from backend.crypto_contract import ensure_state_dir, write_state_json, read_state_json

PAIRS = {"SOLUSDT", "KASUSDT"}
SCHEMA = 1
START_QUOTE = 200.0
MAX_CATCHUP = 24
MAX_DRAWDOWN = .20
MAX_DAY_LOSS = .05
_lock = threading.RLock()


@contextmanager
def _transaction():
    # Also serialize a separate bounded paper worker against the desktop.
    with _lock:
        with (ensure_state_dir() / ".paper.lock").open("a") as stream:
            os.chmod(stream.name, 0o600)
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _path(pair: str):
    if pair not in PAIRS:
        raise ValueError("CRYPTO_PAPER_PAIR")
    return ensure_state_dir() / ("paper-" + pair.lower() + ".json")


def _load(pair: str) -> dict[str, Any]:
    path = _path(pair)
    try:
        value = read_state_json(path)
    except FileNotFoundError:
        return {"schema": SCHEMA, "pair": pair, "primary": "1h", "accounts": {}, "events": []}
    except (OSError, ValueError):
        raise ValueError('CRYPTO_PAPER_STATE_CORRUPT') from None
    if value.get("schema") != SCHEMA or value.get("pair") != pair:
        raise ValueError("CRYPTO_PAPER_STATE_VERSION")
    if (not isinstance(value.get('accounts'), dict) or not isinstance(value.get('events'), list)
            or not all(isinstance(account, dict) for account in value['accounts'].values())):
        raise ValueError('CRYPTO_PAPER_STATE_CORRUPT')
    return value


def _save(value: dict[str, Any]) -> None:
    path = _path(value["pair"])
    write_state_json(path, value)


def _new_account() -> dict[str, Any]:
    return {"enabled": False, "status": "IDLE", "checkpoint": None,
            "processed_ts": None, "tokens": 0.0, "quote": START_QUOTE,
            "equity_quote": START_QUOTE, "peak_quote": START_QUOTE,
            "day_start_quote": START_QUOTE, "day": None, "fills": 0}


def set_enabled(pair: str, book: str, enabled: bool) -> dict[str, Any]:
    if book not in {row["id"] for row in crypto_bots.BOOKS}:
        raise ValueError("CRYPTO_BOOK")
    with _transaction():
        state = _load(pair)
        account = state["accounts"].setdefault(book, _new_account())
        if account["status"] in ("RISK_HALT", "GAP", "ERROR"):
            if enabled:
                raise ValueError("CRYPTO_PAPER_RESET_REQUIRED")
            account["enabled"] = False
            _save(state)
            return snapshot(pair)
        if enabled and not account["enabled"] and account["checkpoint"]:
            account["resume_latest"] = True
        account.update(enabled=bool(enabled), status="WAITING_FOR_CLOSED_BAR" if enabled else "PAUSED")
        _save(state)
        return snapshot(pair)


def set_all(pair: str, enabled: bool) -> dict[str, Any]:
    with _transaction():
        state = _load(pair)
        for book in crypto_bots.BOOKS:
            account = state["accounts"].setdefault(book["id"], _new_account())
            if account["status"] in ("RISK_HALT", "GAP", "ERROR"):
                account["enabled"] = False
                continue
            if enabled and not account["enabled"] and account["checkpoint"]:
                account["resume_latest"] = True
            account.update(enabled=bool(enabled), status="WAITING_FOR_CLOSED_BAR" if enabled else "PAUSED")
        _save(state)
        return snapshot(pair)


def reset(pair: str, book: str) -> None:
    if book not in {row["id"] for row in crypto_bots.BOOKS}:
        raise ValueError("CRYPTO_BOOK")
    with _transaction():
        state = _load(pair)
        old = state["accounts"].get(book)
        if old:
            state.setdefault("previous_runs", []).append({"book": book, "finished_at": int(time.time()),
                **{key: old.get(key) for key in ("equity_quote", "tokens", "quote", "fills", "status")}})
            state["previous_runs"] = state["previous_runs"][-48:]
        state["accounts"][book] = _new_account()
        _save(state)


def active_pairs() -> list[str]:
    result = []
    for pair in sorted(PAIRS):
        try:
            if any(account.get("enabled") for account in _load(pair)["accounts"].values()):
                result.append(pair)
        except (ValueError, OSError, KeyError):
            continue
    return result


def due(pair: str, now: float | None = None) -> bool:
    state = _load(pair)
    step = crypto_data.BAR_SECONDS[state["primary"]]
    expected = int((time.time() if now is None else now) // step) * step - step
    return any(account.get("enabled") and (account.get("processed_ts") is None or account["processed_ts"] != expected) for account in state["accounts"].values())


def data_error(pair: str, reason: str) -> None:
    with _transaction():
        state = _load(pair)
        for account in state["accounts"].values():
            if account.get("enabled"):
                account.update(status="DATA_ERROR", error=reason[:160])
        _save(state)


def snapshot(pair: str) -> dict[str, Any]:
    state = _load(pair)
    rows = []
    for book in crypto_bots.BOOKS:
        account = state["accounts"].get(book["id"], _new_account())
        row = {key: account.get(key) for key in ("enabled", "status", "processed_ts", "tokens", "quote", "equity_quote", "fills", "error", "halt_reason", "recovery_bars")}
        price = float(state.get("price") or 0)
        marked = account["tokens"] * price + account["quote"] if price > 0 else account["equity_quote"]
        row.update(book=book["id"], name=book["name"], equity_quote=marked, pnl_quote=round(marked - START_QUOTE, 6))
        row["token_equivalent"] = marked / price if price > 0 else None
        seed_price = account.get("initial_price")
        row["pnl_token_equivalent"] = row["token_equivalent"] - START_QUOTE / seed_price if seed_price and row["token_equivalent"] is not None else None
        row["buy_hold_quote"] = START_QUOTE * (1 - crypto_backtest.EXECUTION_BPS / 10000) * price / seed_price if seed_price else None
        rows.append(row)
    return {"mode": "PAPER_ONLY", "base_asset": pair.removesuffix("USDT"), "quote_asset": "USDT",
            "primary": state["primary"], "source": state.get("source"), "price": state.get("price"),
            "updated_at": state.get("updated_at"), "accounts": rows, "events": state["events"][-24:],
            "risk": {"max_drawdown_pct": MAX_DRAWDOWN * 100, "max_day_loss_pct": MAX_DAY_LOSS * 100},
            "cost_model": {"per_leg_bps": crypto_backtest.EXECUTION_BPS, "network_cost": "not estimated; hypothetical paper execution"}}


def advance(pair: str, frames: dict[str, dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
    """Process up to 24 missing closed bars per account, isolated on failure."""
    prepared = crypto_backtest.prepare(frames)
    primary = "1h" if "1h" in prepared else next(iter(prepared))
    src = prepared[primary]
    if src["symbol"] != pair:
        raise ValueError("CRYPTO_PAPER_DATA_PAIR")
    step = crypto_data.BAR_SECONDS[primary]
    clock = time.time() if now is None else now
    latest_close = src["times"][-1] + step
    if not 0 <= clock - latest_close <= step * 2:
        raise ValueError("CRYPTO_PAPER_STALE_DATA")
    with _transaction():
        state = _load(pair)
        if state["accounts"] and state["primary"] != primary:
            raise ValueError("CRYPTO_PAPER_CLOCK_CHANGED")
        state.update(primary=primary, source=src["source"], price=src["closes"][-1], updated_at=clock)
        for book, account in state["accounts"].items():
            if not account["enabled"]:
                if account["checkpoint"]:
                    account["equity_quote"] = account["tokens"] * state["price"] + account["quote"]
                continue
            try:
                cursor = account["processed_ts"]
                if cursor is not None and cursor > src["times"][-1]:
                    raise ValueError("CRYPTO_PAPER_CURSOR_AHEAD_OF_DATA")
                resume_latest = bool(account.pop("resume_latest", False))
                indices = [len(src["times"]) - 1] if cursor is None or (resume_latest and cursor < src["times"][-1]) else [i for i, ts in enumerate(src["times"]) if ts > cursor][:MAX_CATCHUP]
                if indices and cursor is not None and not resume_latest and src["times"][indices[0]] != cursor + step:
                    account.update(enabled=False, status="GAP", error="CRYPTO_PAPER_HISTORY_GAP")
                    continue
                for index in indices:
                    ts, price = src["times"][index], src["closes"][index]
                    marked = account["tokens"] * price + account["quote"]
                    day = (ts + step) // 86400
                    if account["day"] != day:
                        account.update(day=day, day_start_quote=account["equity_quote"])
                    peak = max(account["peak_quote"], marked)
                    account.update(equity_quote=marked, peak_quote=peak)
                    if marked < peak * (1 - MAX_DRAWDOWN) or marked < account["day_start_quote"] * (1 - MAX_DAY_LOSS):
                        # Close the simulated exposure; merely pausing would keep
                        # losing money in a falling market. Resume requires reset.
                        sold = account["tokens"]
                        proceeds = sold * price * (1 - crypto_backtest.EXECUTION_BPS / 10000)
                        if sold > 0:
                            state["events"].append({"ts": ts, "side": "sell", "sol": round(sold * 1e9),
                                "usd": round(proceeds * 1e6), "price": round(price * 1e6),
                                "book": book, "pair": pair, "mode": "PAPER_ONLY", "venue": "risk-liquidation-paper"})
                            account["fills"] += 1
                        account.update(tokens=0.0, quote=account["quote"] + proceeds,
                                       equity_quote=account["quote"] + proceeds, processed_ts=ts)
                        account.update(enabled=False, status="RISK_HALT", halt_reason="PORTFOLIO_DRAWDOWN_OR_DAILY_LOSS")
                        break
                    if index < 95:
                        raise ValueError("CRYPTO_PAPER_WARMUP_GAP")
                    prefix = {primary: {**src, **{key: src[key][:index + 1] for key in ("highs", "lows", "closes", "volumes", "times", "opens") if key in src}}}
                    for tf, raw in prepared.items():
                        if tf != primary:
                            prefix[tf] = raw
                    result = crypto_bots.run_step(prefix, book_id=book, continuation=account["checkpoint"])
                    tokens, quote = result["inventory_tokens"], result["quote_balance"]
                    if not all(math.isfinite(v) and v >= 0 for v in (tokens, quote)):
                        raise ValueError("CRYPTO_PAPER_NEGATIVE_OR_INVALID_BALANCE")
                    for event in result["events"]:
                        state["events"].append({**event, "book": book, "pair": pair, "mode": "PAPER_ONLY", "recovery_replay": ts + step < latest_close})
                    account.update(checkpoint=result["continuation"], tokens=tokens, quote=quote,
                                   processed_ts=ts, equity_quote=tokens * price + quote, status="RUNNING",
                                   fills=account["fills"] + len(result["events"]))
                    account.pop("error", None)
                    if ts + step < latest_close:
                        account["recovery_bars"] = account.get("recovery_bars", 0) + 1
                    account.setdefault("initial_price", price)
                    state["events"] = state["events"][-512:]
            except Exception as exc:
                account.update(enabled=False, status="ERROR", error=type(exc).__name__ + ": " + str(exc)[:160])
        _save(state)
        return snapshot(pair)
