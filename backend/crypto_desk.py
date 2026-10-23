"""Paper trading desk: specialist seats plus a code-level Front Man.

Inspired by public multi-seat desk writeups (numbered specialists, one
veto that ends the conversation).  Seats are deterministic indicator
roles, not model agents.  The Front Man kill switch lives in this file
as hard returns — never as prompt text.  No wallet, no live venue.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend import crypto_vol, crypto_backtest


SCHEMA = "gg.crypto.desk.v1"
WARMUP = 40
MAX_TRADES = 8
FEE_BPS = crypto_backtest.FEE_BPS
SLIPPAGE_BPS = crypto_backtest.SLIPPAGE_BPS
VOL_LEAD_Z = 1.25
PRICE_QUIET_BPS = 25.0
CROWD_MOVE_BPS = 80.0
THIN_VOLUME_Z = -0.50


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _zscore(values: list[float], lookback: int) -> float:
    if len(values) < lookback or lookback <= 1:
        return 0.0
    window = values[-lookback:]
    mean = sum(window) / float(lookback)
    var = sum((item - mean) ** 2 for item in window) / float(lookback)
    sigma = math.sqrt(max(var, 1e-12))
    return (window[-1] - mean) / sigma


def _bps(now: float, then: float) -> float:
    if then <= 0:
        return 0.0
    return ((now / then) - 1.0) * 10_000.0


def _clean(frames: dict[str, Any]) -> tuple[list[float], list[float]]:
    preferred = ("1h", "15m", "5m", "1m")
    frame = None
    for key in preferred:
        if key in frames and isinstance(frames[key], dict):
            frame = frames[key]
            break
    if frame is None:
        for value in frames.values():
            if isinstance(value, dict) and value.get("closes"):
                frame = value
                break
    if not isinstance(frame, dict):
        return [], []
    closes: list[float] = []
    volumes: list[float] = []
    raw_vol = list(frame.get("volumes") or [])
    for index, raw in enumerate(frame.get("closes") or []):
        price = _finite(raw, 0.0)
        if price <= 0:
            continue
        closes.append(price)
        if index < len(raw_vol):
            volumes.append(max(0.0, _finite(raw_vol[index], 0.0)))
        else:
            volumes.append(0.0)
    return closes, volumes


def _seat_456(closes: list[float], volumes: list[float], index: int) -> dict[str, Any]:
    """Volume moves before price."""
    hist_c = closes[: index + 1]
    hist_v = volumes[: index + 1]
    vol_z = _zscore(hist_v, 24)
    move = abs(_bps(hist_c[-1], hist_c[-2])) if len(hist_c) > 1 else 0.0
    flag = vol_z >= VOL_LEAD_Z and move <= PRICE_QUIET_BPS
    return {
        "id": "456",
        "job": "VOLUME_LEADS_PRICE",
        "vote": "ATTRACTIVE" if flag else "WAIT",
        "vol_z": round(vol_z, 3),
        "move_bps": round(move, 2),
    }


def _seat_067(closes: list[float], volumes: list[float], index: int) -> dict[str, Any]:
    """Crowd already paid for the spike — do not chase."""
    hist_c = closes[: index + 1]
    hist_v = volumes[: index + 1]
    vol_z = _zscore(hist_v, 24)
    move = abs(_bps(hist_c[-1], hist_c[-2])) if len(hist_c) > 1 else 0.0
    flag = vol_z >= VOL_LEAD_Z and move >= CROWD_MOVE_BPS
    return {
        "id": "067",
        "job": "CROWD_PAID_SPIKE",
        "vote": "SPIKE" if flag else "CLEAR",
        "vol_z": round(vol_z, 3),
        "move_bps": round(move, 2),
    }


def _seat_218(closes: list[float], index: int) -> dict[str, Any]:
    """Money math: vol-aware size only."""
    snap = crypto_vol.snapshot(closes[: index + 1])
    scale = float(snap.get("size_scale") or 0.0)
    regime = str((snap.get("hmm") or {}).get("last_state") or "UNKNOWN")
    return {
        "id": "218",
        "job": "SIZE",
        "vote": "SIZE" if scale >= 0.25 and snap.get("ok") else "FLAT",
        "size_scale": round(scale, 4),
        "regime": regime,
    }


def _seat_240(closes: list[float], index: int, entry: float) -> dict[str, Any]:
    """Invalidation level.  Once crossed, the trade is over."""
    hist = closes[: index + 1]
    if len(hist) < 16 or entry <= 0:
        return {
            "id": "240",
            "job": "INVALIDATION",
            "vote": "FLAT",
            "level": 0.0,
            "hit": False,
        }
    window = hist[-16:]
    sigma = 0.0
    logs = [
        math.log(window[i] / window[i - 1])
        for i in range(1, len(window))
        if window[i] > 0 and window[i - 1] > 0
    ]
    if logs:
        mean = sum(logs) / len(logs)
        sigma = math.sqrt(sum((item - mean) ** 2 for item in logs) / len(logs))
    level = entry * math.exp(-1.5 * sigma * math.sqrt(16.0))
    hit = hist[-1] < level
    return {
        "id": "240",
        "job": "INVALIDATION",
        "vote": "STOP" if hit else "HOLD",
        "level": round(level, 6),
        "hit": hit,
    }


def front_man(
    seat_456: dict[str, Any],
    seat_067: dict[str, Any],
    seat_218: dict[str, Any],
    seat_240: dict[str, Any],
    *,
    has_volume: bool,
    trades_today: int,
    in_position: bool,
    thin: bool,
) -> dict[str, Any]:
    """Hard veto.  This function is the kill switch."""
    reasons: list[str] = []
    if not has_volume:
        reasons.append("NO_VOLUME")
    if thin:
        reasons.append("THIN_LIQUIDITY")
    if str(seat_067.get("vote") or "") == "SPIKE":
        reasons.append("CROWD_SPIKE")
    if trades_today >= MAX_TRADES:
        reasons.append("TRADE_CAP")
    if in_position and bool(seat_240.get("hit")):
        reasons.append("INVALIDATION")
    if not in_position and str(seat_218.get("vote") or "") != "SIZE":
        reasons.append("NO_SIZE")
    light = "RED" if reasons else "GREEN"
    if light == "GREEN" and not in_position:
        if str(seat_456.get("vote") or "") != "ATTRACTIVE":
            light = "RED"
            reasons.append("NO_SETUP")
    return {
        "id": "FRONT_MAN",
        "job": "KILL_SWITCH",
        "light": light,
        "reasons": reasons,
        "in_code": True,
    }


def empty_snapshot() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "state": "IDLE",
        "mode": "PAPER_ONLY",
        "mainnet": "NOT_ARMED",
        "note": "No desk run yet.",
        "seats": [],
        "front_man": {"id": "FRONT_MAN", "light": "RED", "reasons": ["IDLE"]},
        "fills": [],
        "equity_pct": 0.0,
        "trades": 0,
    }


def run_desk(frames: dict[str, Any]) -> dict[str, Any]:
    closes, volumes = _clean(frames)
    if len(closes) < WARMUP + 8:
        return {
            **empty_snapshot(),
            "state": "ERROR",
            "note": "Need more bars before the desk can sit.",
        }
    has_volume = any(value > 0 for value in volumes)
    friction = (FEE_BPS + SLIPPAGE_BPS) / 10_000.0
    cash = 1.0
    units = 0.0
    entry = 0.0
    fills: list[dict[str, Any]] = []
    last_board: dict[str, Any] = {}
    red_count = 0
    frame = next((frames[key] for key in ("1h", "15m", "5m", "1m") if key in frames), next(iter(frames.values()), {}))
    times = list(frame.get("times") or [])
    day = None
    trades_today = 0

    for index in range(WARMUP, len(closes)):
        stamp = int(times[index]) if index < len(times) else index * 3600
        current_day = stamp // 86400
        if current_day != day:
            day, trades_today = current_day, 0
        seat_456 = _seat_456(closes, volumes, index)
        seat_067 = _seat_067(closes, volumes, index)
        seat_218 = _seat_218(closes, index)
        seat_240 = _seat_240(closes, index, entry)
        vol_z = _zscore(volumes[: index + 1], 24)
        thin = has_volume and vol_z <= THIN_VOLUME_Z
        in_position = units > 0
        man = front_man(
            seat_456,
            seat_067,
            seat_218,
            seat_240,
            has_volume=has_volume,
            trades_today=trades_today,
            in_position=in_position,
            thin=thin,
        )
        price = closes[index]
        last_board = {
            "seats": [seat_456, seat_067, seat_218, seat_240],
            "front_man": man,
            "001": {
                "id": "001",
                "job": "REPORTER",
                "vote": "BOARD",
                "light": man["light"],
            },
        }
        if man["light"] == "RED":
            red_count += 1
            if in_position and "INVALIDATION" in man["reasons"]:
                cash += units * price * (1.0 - friction)
                fills.append(
                    {
                        "side": "SELL",
                        "reason": "INVALIDATION",
                        "price": round(price, 6),
                    }
                )
                units = 0.0
                entry = 0.0
            continue
        if not in_position:
            scale = float(seat_218.get("size_scale") or 0.0)
            spend = cash * min(1.0, max(0.0, scale))
            if spend <= 0:
                continue
            units = spend * (1.0 - friction) / price
            cash -= spend
            trades_today += 1
            entry = price
            fills.append(
                {
                    "side": "BUY",
                    "reason": "456_SETUP",
                    "price": round(price, 6),
                    "size_scale": round(scale, 4),
                }
            )

    if units > 0:
        price = closes[-1]
        cash += units * price * (1.0 - friction)
        fills.append({"side": "SELL", "reason": "EOD_MARK", "price": round(price, 6)})
        units = 0.0

    board = last_board or {"seats": [], "front_man": {"light": "RED"}}
    reporter = board.get("001") or {
        "id": "001",
        "job": "REPORTER",
        "vote": "BOARD",
    }
    return {
        "schema": SCHEMA,
        "state": "DONE",
        "mode": "PAPER_ONLY",
        "mainnet": "NOT_ARMED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Specialists vote independently. Front Man veto is code. "
            "001 only reports. No live path."
        ),
        "bars": len(closes),
        "has_volume": has_volume,
        "seats": list(board.get("seats") or []) + [reporter],
        "front_man": board.get("front_man") or {"light": "RED"},
        "fills": fills[-16:],
        "trades": len([row for row in fills if row.get("side") == "BUY"]),
        "equity_pct": round((cash - 1.0) * 100.0, 4),
        "red_lights": red_count,
        "vol": crypto_vol.snapshot(closes),
        "orchestration": {
            "model_agents": False,
            "kill_switch": "CODE",
            "max_trades": MAX_TRADES,
            "cross_talk_during_inference": False,
        },
    }
