"""SOL-native swing book: grow token count. USD is quote, not home.

Here and now. Super = all 4 stoch piled in 25/70 plus other osc.
More agreement unlocks a faster clock. 34/day is the ledger.
Park is zero. MAINNET not used.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.crypto_contract import ensure_state_dir, format_units
from backend import crypto_backtest
from backend.crypto_indicators import (
    aroon_osc,
    bb_percent,
    bollinger,
    candle_osc,
    cci_osc,
    cmf_osc,
    cmo_osc,
    donchian_percent,
    ema,
    ema_ribbon_osc,
    heikin_osc,
    ichimoku_osc,
    keltner_percent,
    last,
    macd,
    mfi,
    rsi,
    sar_osc,
    schaff_trend,
    sma,
    stoch_kd,
    stoch_rsi,
    supertrend_osc,
    ultimate_osc,
    williams_osc,
)
from backend.crypto_strategy004 import adx, evaluate as evaluate_004

SOL_SCALE = 10**9
USD_SCALE = 10**6
START_SOL = 2 * SOL_SCALE
START_USD = 200 * USD_SCALE
FEE_BPS = 30
# Roundtrip fees are 60 bps. Infinite grid step must clear that.
MIN_COVER_BPS = 80
# Cover is this swing. A 20% move means the last fill is dead.
STALE_BPS = 2000
GRID_STEP_BPS = 100
# One trade is a 5% clip. 20% of THAT clip's profit vaults. 80% stays in the trade.
GRID_SLICE_BPS = 500
MIN_NET_BPS = MIN_COVER_BPS - 2 * FEE_BPS
PROFIT_BANK_BPS = 2000
PROFIT_ROLL_BPS = 8000
FLOAT_BPS = 10000
# 15% stays in the day book forever. Cycle bag_sell cannot take it.
FLOAT_KEEP_BPS = 1500
VAULT_BPS = 0
MAX_TRADES_DAY = 34
MIN_TRADES_DAY = 4
MAX_OPEN_LOTS = 24
LOT_BPS = 1500
DCA_BPS = 10000
BAG_SLICE_BPS = 10000
BAG_OB_NEED = 80
# Vote exists. The book does not go to cash and wait.
EXECUTE_CYCLE_BAG = False
DCA_RSI = 32.0
YEAR_LOW_BARS = 365
YEAR_LOW_BPS = 12500
ENTRY_GAP_SEC = 15 * 60
MIN_SOL_LOT = SOL_SCALE // 50
STOP_BPS = 800
MAX_UNCOVERED = 20
DAY_HOLD_SEC = 2 * 86400
MAX_BAG_RISK_BPS = 3000
# Half the bag stays SOL. The float sells high and buys low.
CORE_KEEP_BPS = 5000
PEAK_DD_BPS = 1500
STATE_NAME = "trader.json"
LOTS_NAME = "trader-lots.jsonl"
BACKTEST_NAME = "backtest.json"
BACKTEST_PREV_NAME = "backtest-prev.json"
PARAMS_NAME = "signal-params.json"


def default_signal_params() -> dict[str, Any]:
    return {
        "rsi_buy": 38.0,
        "rsi_sell": 58.0,
        "stoch_buy": 20.0,
        "stoch_sell": 80.0,
        "macd_buy": True,
        "bb_buy": True,
        "stoch_need": 2,
        "tf_need": 2,
        "allow_trend_down_exits": True,
    }


# Four stochs on the same TF: fast → slow. Last one is volume-confirmed.
# (%K length, %K smoothing, %D smoothing, volume_gate)
STOCH_STACK = (
    (9, 3, 3, False),
    (14, 3, 3, False),
    (40, 4, 4, False),
    (60, 10, 10, True),
)
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "8h", "1d")
# 1m/5m print the 15m turn. Fills sit on 15m and slower — 34/day is a cap, not a refill queue.
FILL_TFS = ("15m", "1h", "4h", "8h", "1d")
BAND_BUY = 25.0
BAND_SELL = 70.0
# All 4 stochs piled in the same spot is the opportunity. Extra osc unlock faster clocks.
# Span is oscillator points — slow 60 lags, so this is "about the same place".
STOCH_CLUSTER_SPAN = 15.0
QUAL_KEYS = ("rsi", "mfi", "cci", "bb", "williams")
TF_OTHER_NEED = {
    "15m": 3,
    "1h": 2,
    "4h": 1,
    "8h": 1,
    "1d": 1,
}
# Several clips around the extreme. Interval is a real swing, not 80 bps noise.
LADDER_N = 3
LADDER_BUY_BPS = 400
LADDER_SELL_BPS = 400
TF_PARENT = {"15m": "1h", "1h": "4h"}
# Buy deploys the 1.04 around the low. 25% × 4 clips spends the powder.
BUY_CLIP_BPS = 2500
# Same 0-100 scale for RSI and stoch. Deeper = more interesting, dollar still rules.
BUY_TIERS = (25.0, 20.0, 15.0, 10.0, 5.0)
SELL_TIERS = (70.0, 80.0, 90.0)
# All TFs are data for one vote. Macro = direction, timing = pullback.
MACRO_TFS = ("1d", "8h", "4h")
MACRO_WEIGHTS = (8, 4, 4)
TIMING_TFS = ("1h", "15m", "5m", "1m")
TIMING_WEIGHTS = (4, 3, 2, 1)
TIMING_NEED = 2
HORIZON_WEIGHTS = (32, 16, 8, 4, 2, 1, 1)
SWINGS = (
    {
        "id": "day",
        "sell": ("1h", "15m"),
        "realtime": ("5m", "1m"),
        "sell_need": 1,
        "slice_bps": 150,
        "min_move_bps": 150,
        "cover_bps": 120,
        "gap_sec": 0,
        "park_sec": 0,
        "park_run_bps": 1800,
    },
    {
        "id": "week",
        "sell": ("4h", "1h"),
        "sell_need": 1,
        "slice_bps": 500,
        "min_move_bps": 400,
        "cover_bps": 400,
        "gap_sec": 0,
        "park_sec": 0,
        "park_run_bps": 1800,
    },
    {
        "id": "month",
        "sell": ("8h", "4h"),
        "sell_need": 2,
        "slice_bps": 700,
        "min_move_bps": 1600,
        "cover_bps": 800,
        "gap_sec": 0,
        "park_sec": 0,
        "park_run_bps": 1800,
    },
)
HORIZONS = {
    "spot": {
        "tfs": TIMEFRAMES,
        "max_open": MAX_OPEN_LOTS,
        "bps": LOT_BPS,
    },
    "day": {"tfs": ("1h", "15m", "5m", "1m"), "max_open": 16, "bps": 150},
    "week": {"tfs": ("4h", "1h"), "max_open": 2, "bps": 500},
    "month": {"tfs": ("8h", "4h"), "max_open": 1, "bps": 700},
}
FLOW_SIGN = {"trend_up": 1.0, "range": 0.0, "trend_down": -1.0}
BAR_SEC = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "8h": 28800,
    "1d": 86400,
}


def in_buy_band(value: float | None) -> bool:
    return value is not None and value <= BAND_BUY


def _same_market_px(ref: int, price: int) -> bool:
    if ref <= 0 or price <= 0:
        return False
    return abs(price - ref) * 10_000 < ref * STALE_BPS


def in_sell_band(value: float | None) -> bool:
    return value is not None and value >= BAND_SELL


def osc_buy_depth(value: float | None) -> int:
    """0 if not oversold. 1 at 25, 2 at 20, … 5 at 5."""
    if value is None:
        return 0
    v = float(value)
    depth = 0
    for tier in BUY_TIERS:
        if v <= tier:
            depth += 1
        else:
            break
    return depth


def osc_sell_depth(value: float | None) -> int:
    """0 if not overbought. 1 at 70, 2 at 80, 3 at 90."""
    if value is None:
        return 0
    v = float(value)
    depth = 0
    for tier in SELL_TIERS:
        if v >= tier:
            depth += 1
        else:
            break
    return depth


def _osc_pair_depth(osc: dict[str, Any], sell: bool) -> int:
    rsi_v = osc.get("rsi")
    stoch_v = osc.get("stoch")
    if sell:
        return max(
            osc_sell_depth(None if rsi_v is None else float(rsi_v)),
            osc_sell_depth(None if stoch_v is None else float(stoch_v)),
        )
    return max(
        osc_buy_depth(None if rsi_v is None else float(rsi_v)),
        osc_buy_depth(None if stoch_v is None else float(stoch_v)),
    )


def stack_zone(
    tf_osc: dict[str, dict[str, Any]],
    sell: bool = True,
) -> dict[str, Any]:
    """How many TFs are in the 25/70 zone, and how deep. Dollar still executes."""
    n = 0
    depth = 0
    hit: list[str] = []
    for tf in TIMEFRAMES:
        osc = tf_osc.get(tf) or {}
        d = _osc_pair_depth(osc, sell)
        if d <= 0:
            continue
        n += 1
        if d > depth:
            depth = d
        hit.append(tf)
    return {"n": n, "depth": depth, "tfs": hit}


def _cover_need(cfg: dict[str, Any] | None = None) -> int:
    """Gross dip so a cover still nets a bit after 30 bps each way."""
    floor = 2 * FEE_BPS + 20
    if cfg and cfg.get("cover_bps"):
        return max(int(cfg["cover_bps"]), floor)
    return max(MIN_COVER_BPS, floor)


def _tf_available(
    tf: str,
    tf_osc: dict[str, Any],
    tf_super: dict[str, str] | None,
    tf_flow: dict[str, str] | None,
) -> bool:
    if tf in tf_osc:
        return True
    if tf_super and tf in tf_super:
        return True
    if tf_flow and tf in tf_flow:
        return True
    return False


def _present_tfs(
    tfs: tuple[str, ...],
    weights: tuple[int, ...],
    tf_osc: dict[str, Any],
    tf_super: dict[str, str] | None,
    tf_flow: dict[str, str] | None,
) -> list[tuple[str, int]]:
    present: list[tuple[str, int]] = []
    for tf, weight in zip(tfs, weights):
        if _tf_available(tf, tf_osc, tf_super, tf_flow):
            present.append((tf, int(weight)))
    return present


def _zone_turn(prev: float | None, now: float | None, sell: bool) -> bool:
    """In the 25/70 band AND turning. In-band while still running is not the print."""
    if now is None:
        return False
    if sell:
        if not in_sell_band(now) or prev is None:
            return False
        return float(now) < float(prev)
    if not in_buy_band(now) or prev is None:
        return False
    return float(now) > float(prev)


def _in_zone_val(value: object, sell: bool) -> bool:
    try:
        if value is None:
            return False
        v = float(value)
    except (TypeError, ValueError):
        return False
    return in_sell_band(v) if sell else in_buy_band(v)


def _stoch_vals(osc: dict[str, Any]) -> list[float]:
    """Four K readings when the stack is present, else the single stoch."""
    out: list[float] = []
    stack = osc.get("stoch_stack")
    if isinstance(stack, list) and stack:
        for item in stack:
            try:
                if item is not None:
                    out.append(float(item))
            except (TypeError, ValueError):
                continue
        return out
    for k_len, _k_sm, _d_sm, _vol in STOCH_STACK:
        try:
            raw = osc.get("stoch" + str(k_len) + "k")
            if raw is not None:
                out.append(float(raw))
        except (TypeError, ValueError):
            continue
    if out:
        return out
    try:
        raw = osc.get("stoch")
        if raw is not None:
            out.append(float(raw))
    except (TypeError, ValueError):
        return out
    return out


def _stoch_cluster(osc: dict[str, Any], sell: bool) -> tuple[int, bool]:
    """(n in the 25/70 band, all 4 piled on the same spot in that band)."""
    vals = _stoch_vals(osc)
    in_z = sum(1 for item in vals if _in_zone_val(item, sell))
    if len(vals) < 4:
        return in_z, False
    span = max(vals) - min(vals)
    mean = sum(vals) / 4.0
    clustered = span <= STOCH_CLUSTER_SPAN and _in_zone_val(mean, sell)
    return in_z, clustered


def _stoch_mean(osc: dict[str, Any]) -> float | None:
    vals = _stoch_vals(osc)
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def _other_agree(osc: dict[str, Any], sell: bool) -> int:
    return sum(1 for key in QUAL_KEYS if _in_zone_val(osc.get(key), sell))


def _tf_unlocked(tf: str, osc: dict[str, Any], sell: bool) -> bool:
    """More agreeing osc → faster clock. Spread 4-stoch is not a fill."""
    vals = _stoch_vals(osc)
    if len(vals) < 4:
        return True
    _n, clustered = _stoch_cluster(osc, sell)
    if not clustered:
        return False
    need = int(TF_OTHER_NEED.get(tf, 3))
    return _other_agree(osc, sell) >= need


def _stoch_turn(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    now_vals = _stoch_vals(osc)
    prev_vals = _stoch_vals(prev)
    if len(now_vals) >= 4:
        if len(prev_vals) < 4:
            return False
        _n, clustered = _stoch_cluster(osc, sell)
        if not clustered:
            return False
        return _zone_turn(
            sum(prev_vals) / float(len(prev_vals)),
            sum(now_vals) / 4.0,
            sell,
        )
    now_stack = osc.get("stoch_stack")
    prev_stack = prev.get("stoch_stack")
    if isinstance(now_stack, list) and isinstance(prev_stack, list):
        for a, b in zip(now_stack, prev_stack):
            if _zone_turn(b, a, sell):
                return True
    return _zone_turn(prev.get("stoch"), osc.get("stoch"), sell)


def _tf_hook(osc: dict[str, Any], prev: dict[str, Any], sell: bool) -> bool:
    """Stoch pile-up is the guess. RSI alone is not a fill."""
    if _stoch_turn(osc, prev, sell):
        return True
    if len(_stoch_vals(osc)) >= 4:
        return False
    if _zone_turn(prev.get("rsi"), osc.get("rsi"), sell) and _in_zone_val(
        osc.get("stoch"), sell
    ):
        return True
    return False


def _guess_agree(osc: dict[str, Any], sell: bool) -> int:
    """How many 0–100 osc share the guess. Cap 5 so one bar cannot dump the bag."""
    n = _other_agree(osc, sell)
    stoch_n, clustered = _stoch_cluster(osc, sell)
    if clustered:
        n += min(4, max(1, stoch_n))
    elif _in_zone_val(osc.get("stoch"), sell):
        n += 1
    if n <= 0:
        n = int(osc.get("sell_n") or 0) if sell else int(osc.get("buy_n") or 0)
    return min(5, n)


def _count_hooks(
    tf_osc: dict[str, dict[str, Any]],
    osc_prev: dict[str, Any],
    sell: bool,
    tfs: tuple[str, ...],
) -> int:
    n = 0
    for tf in tfs:
        if _tf_hook(tf_osc.get(tf) or {}, osc_prev.get(tf) or {}, sell):
            n += 1
    return n


def _tf_in_zone(osc: dict[str, Any], sell: bool) -> bool:
    vals = [osc.get("rsi"), osc.get("stoch")]
    vals.extend(osc.get("stoch_stack") or [])
    if sell:
        return any(in_sell_band(v) for v in vals)
    return any(in_buy_band(v) for v in vals)


def _tf_left_mid(osc: dict[str, Any], sell: bool) -> bool:
    """Re-arm only after RSI crosses 50, not on a 69/71 flicker."""
    rsi_v = osc.get("rsi")
    if rsi_v is None:
        return False
    if sell:
        return float(rsi_v) < 50.0
    return float(rsi_v) > 50.0


def _fresh_hooks(
    tf_osc: dict[str, dict[str, Any]],
    osc_prev: dict[str, Any],
    sell: bool,
    tfs: tuple[str, ...],
    armed: dict[str, Any],
) -> list[str]:
    """One print per decision TF per visit. 1m/5m confirm 15m; they do not fill."""
    key = "sell" if sell else "buy"
    fresh: list[str] = []
    fast_ok = True
    if "15m" in tfs:
        fast_ok = _tf_hook(
            tf_osc.get("1m") or {}, osc_prev.get("1m") or {}, sell
        ) or _tf_hook(tf_osc.get("5m") or {}, osc_prev.get("5m") or {}, sell)
        if not (tf_osc.get("1m") or tf_osc.get("5m")):
            fast_ok = True
    for tf in tfs:
        if tf in ("1m", "5m"):
            continue
        osc = tf_osc.get(tf) or {}
        if _tf_left_mid(osc, sell) and armed.get(tf) == key:
            armed[tf] = None
        if not _tf_in_zone(osc, sell):
            continue
        if not _tf_unlocked(tf, osc, sell):
            continue
        parent = TF_PARENT.get(tf)
        if parent and parent in tf_osc:
            if not _tf_in_zone(tf_osc.get(parent) or {}, sell):
                continue
        if tf == "15m" and not fast_ok and len(_stoch_vals(osc)) < 4:
            continue
        if _tf_hook(osc, osc_prev.get(tf) or {}, sell) and armed.get(tf) != key:
            fresh.append(tf)
    return fresh


def _tf_wants_buy(
    tf: str,
    tf_osc: dict[str, dict[str, Any]],
    tf_super: dict[str, str],
    osc_prev: dict[str, Any] | None = None,
) -> bool:
    osc = tf_osc.get(tf) or {}
    prev = (osc_prev or {}).get(tf) if osc_prev else None
    if isinstance(prev, dict) and (
        prev.get("rsi") is not None
        or prev.get("stoch") is not None
        or prev.get("stoch_stack")
    ):
        return _tf_hook(osc, prev, False)
    rsi_v = osc.get("rsi")
    stoch_v = osc.get("stoch")
    if osc_buy_depth(None if rsi_v is None else float(rsi_v)):
        return True
    if osc_buy_depth(None if stoch_v is None else float(stoch_v)):
        return True
    if str(tf_super.get(tf) or "none") == "buy":
        return True
    return int(osc.get("buy_n") or 0) >= 6


def _tf_wants_sell(
    tf: str,
    tf_osc: dict[str, dict[str, Any]],
    tf_super: dict[str, str],
    osc_prev: dict[str, Any] | None = None,
) -> bool:
    osc = tf_osc.get(tf) or {}
    prev = (osc_prev or {}).get(tf) if osc_prev else None
    if isinstance(prev, dict) and (
        prev.get("rsi") is not None
        or prev.get("stoch") is not None
        or prev.get("stoch_stack")
    ):
        return _tf_hook(osc, prev, True)
    rsi_v = osc.get("rsi")
    stoch_v = osc.get("stoch")
    if osc_sell_depth(None if rsi_v is None else float(rsi_v)):
        return True
    if osc_sell_depth(None if stoch_v is None else float(stoch_v)):
        return True
    if str(tf_super.get(tf) or "none") == "sell":
        return True
    return int(osc.get("sell_n") or 0) >= 6


def confluence_vote(
    tf_osc: dict[str, dict[str, Any]],
    tf_super: dict[str, str] | None = None,
    tf_flow: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One buy/sell from all TFs. Macro is 1d/8h/4h; 1h…1m time the pullback."""
    super_map = tf_super or {}
    flow_map = tf_flow or {}
    empty = {
        "side": "none",
        "flow": "range",
        "flow_score": 0.0,
        "buy": 0.0,
        "sell": 0.0,
        "rsi": None,
        "tf": "1h",
        "need": TIMING_NEED,
        "timing_n": 0,
        "invalid": False,
        "dca": False,
    }
    macro_present = _present_tfs(MACRO_TFS, MACRO_WEIGHTS, tf_osc, super_map, flow_map)
    if not macro_present:
        for tf in reversed(TIMEFRAMES):
            if _tf_available(tf, tf_osc, super_map, flow_map):
                macro_present = [(tf, 8)]
                break
    if not macro_present:
        return empty
    flow_acc = 0.0
    flow_w = 0.0
    for tf, weight in macro_present:
        flow_w += weight
        flow_acc += weight * FLOW_SIGN.get(str(flow_map.get(tf) or "range"), 0.0)
    flow_score = flow_acc / flow_w if flow_w else 0.0
    if flow_score > 0.15:
        flow_name = "trend_up"
    elif flow_score < -0.15:
        flow_name = "trend_down"
    else:
        flow_name = "range"
    flow_1d = str(flow_map.get("1d") or "")
    flow_4h = str(flow_map.get("4h") or "")
    invalid = flow_1d == "trend_down" or flow_4h == "trend_down"
    timing_buy_n = 0
    timing_sell_n = 0
    buy_acc = 0.0
    sell_acc = 0.0
    rsi_acc = 0.0
    rsi_w = 0.0
    for tf, weight in zip(TIMING_TFS, TIMING_WEIGHTS):
        if not _tf_available(tf, tf_osc, super_map, flow_map):
            continue
        osc = tf_osc.get(tf) or {}
        rsi_v = osc.get("rsi")
        if rsi_v is not None:
            rsi_acc += weight * float(rsi_v)
            rsi_w += weight
        if _tf_wants_buy(tf, tf_osc, super_map):
            timing_buy_n += 1
            buy_acc += weight
        if _tf_wants_sell(tf, tf_osc, super_map):
            timing_sell_n += 1
            sell_acc += weight
    hour_sell = _tf_wants_sell("1h", tf_osc, super_map) if "1h" in tf_osc or "1h" in super_map else False
    four_sell = _tf_wants_sell("4h", tf_osc, super_map)
    eight_sell = _tf_wants_sell("8h", tf_osc, super_map)
    rsi_1d = (tf_osc.get("1d") or {}).get("rsi")
    deep_1d = rsi_1d is not None and float(rsi_1d) <= DCA_RSI
    dca = (
        deep_1d
        and flow_1d != "trend_up"
        and flow_4h != "trend_down"
    )
    bull = (
        flow_name == "trend_up"
        and flow_1d != "trend_down"
        and flow_4h != "trend_down"
    )
    going_down = flow_1d == "trend_down" or flow_4h == "trend_down"
    side = "none"
    if dca or (
        timing_buy_n >= TIMING_NEED
        and buy_acc > sell_acc
        and not hour_sell
        and bull
    ):
        side = "buy"
    elif (
        timing_sell_n >= TIMING_NEED
        and sell_acc > buy_acc
        and hour_sell
        and not going_down
    ):
        side = "sell"
    return {
        "side": side,
        "flow": flow_name,
        "flow_score": round(flow_score, 3),
        "buy": round(buy_acc, 2),
        "sell": round(sell_acc, 2),
        "rsi": None if rsi_w <= 0 else round(rsi_acc / rsi_w, 2),
        "tf": macro_present[0][0],
        "need": TIMING_NEED,
        "timing_n": timing_buy_n if side == "buy" else timing_sell_n,
        "invalid": invalid,
        "dca": dca,
        "bag_sell": (
            rsi_1d is not None
            and float(rsi_1d) >= 80.0
            and eight_sell
            and four_sell
            and hour_sell
            and flow_1d != "trend_down"
        ),
    }


def _swing_cfg(horizon: str) -> dict[str, Any] | None:
    for row in SWINGS:
        if row["id"] == horizon:
            return row
    return None


def swing_vote(
    horizon: str,
    tf_osc: dict[str, dict[str, Any]],
    tf_super: dict[str, str] | None = None,
    tf_flow: dict[str, str] | None = None,
    osc_prev: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Peak-low vote at day/week/month. Does not dump the cycle bag."""
    cfg = _swing_cfg(horizon)
    empty = {"side": "none", "horizon": horizon, "waterfall": False}
    if cfg is None:
        return empty
    super_map = tf_super or {}
    flow_map = tf_flow or {}
    flow_1d = str(flow_map.get("1d") or "")
    flow_4h = str(flow_map.get("4h") or "")
    waterfall = flow_1d == "trend_down" and flow_4h == "trend_down"
    if cfg["id"] == "day":
        return {
            "side": "sell",
            "horizon": "day",
            "waterfall": waterfall,
            "sell_n": 0,
            "price_book": True,
        }
    sell_n = 0
    for tf in cfg["sell"]:
        if _tf_available(tf, tf_osc, super_map, flow_map) and _tf_wants_sell(
            tf, tf_osc, super_map, osc_prev
        ):
            sell_n += 1
    sell_ok = sell_n >= int(cfg.get("sell_need") or len(cfg["sell"]))
    rt_tfs = tuple(cfg.get("realtime") or ())
    rt_avail = [
        tf
        for tf in rt_tfs
        if _tf_available(tf, tf_osc, super_map, flow_map)
    ]
    if rt_avail:
        rt_ok = any(
            _tf_wants_sell(tf, tf_osc, super_map, osc_prev) for tf in rt_avail
        )
        sell_ok = sell_ok and rt_ok
    side = "none"
    if sell_ok and not waterfall:
        rsi_1d = (tf_osc.get("1d") or {}).get("rsi")
        cycle_ob = rsi_1d is not None and float(rsi_1d) >= BAND_SELL
        if flow_1d == "trend_down":
            side = "none"
        elif cycle_ob and cfg["id"] == "month":
            side = "none"
        else:
            side = "sell"
    return {
        "side": side,
        "horizon": cfg["id"],
        "waterfall": waterfall,
        "sell_n": sell_n,
    }


def horizon_vote(
    horizon: str,
    tf_osc: dict[str, dict[str, Any]],
    tf_super: dict[str, str] | None = None,
    tf_flow: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Cycle uses confluence. Day/week/month use nested peak-low votes."""
    if horizon in ("day", "week", "month"):
        return swing_vote(horizon, tf_osc, tf_super, tf_flow)
    return confluence_vote(tf_osc, tf_super, tf_flow)


def _state_path() -> Path:
    return ensure_state_dir() / STATE_NAME


def _lots_path() -> Path:
    return ensure_state_dir() / LOTS_NAME


def _book_id() -> str:
    return str(load_state().get("book") or "gg")


def _backtest_path() -> Path:
    bid = _book_id()
    if bid in ("", "gg"):
        return ensure_state_dir() / BACKTEST_NAME
    return ensure_state_dir() / ("backtest-" + bid + ".json")


def _backtest_prev_path() -> Path:
    bid = _book_id()
    if bid in ("", "gg"):
        return ensure_state_dir() / BACKTEST_PREV_NAME
    return ensure_state_dir() / ("backtest-" + bid + "-prev.json")


def default_state() -> dict[str, Any]:
    return {
        "armed": False,
        "usd": START_USD,
        "sol": 0,
        "banked_sol": 0,
        "banked_usd": 0,
        "seeded": False,
        "day": "",
        "trades_today": 0,
        "last_ts": 0,
        "gap_ts": {},
        "peak_tokens": 0,
        "bag_armed": True,
        "cash_cycle": False,
        "ob_days": 0,
        "ob_1d_close": None,
        "day_lows": [],
        "swing_low": {},
        "swing_high": {},
        "swing_anchor": {},
        "float_usd": 0,
        "grid_px": 0,
        "grid_hold_sell_ts": 0,
        "grid_hold_buy_ts": 0,
        "grid_last_buy_px": 0,
        "grid_last_sell_px": 0,
        "float_fill_ts": 0,
        "tf_buy_px": {},
        "tf_sell_px": {},
        "float_trimmed": False,
        "zone_armed": {},
        "ladder": {},
        "book": "gg",
        "cost_px": 0,
        "cycle_sold_sol": 0,
        "cycle_sold_usd": 0,
        "dump_low": None,
        "osc_bounce": False,
        "osc_prev": {},
        "regime": "range",
        "last": {},
    }


def load_state() -> dict[str, Any]:
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = default_state()
        save_state(payload)
        return payload
    if not isinstance(payload, dict):
        payload = default_state()
    base = default_state()
    base.update(payload)
    return base


def save_state(payload: dict[str, Any]) -> dict[str, Any]:
    path = _state_path()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return load_state()


def append_lot(row: dict[str, Any]) -> None:
    path = _lots_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def read_lots(limit: int = 24) -> list[dict[str, Any]]:
    path = _lots_path()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, int(limit)) :]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _utc_day(ts: int | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else None))


def _price_atoms(close: float) -> int:
    return max(1, int(round(float(close) * USD_SCALE)))


def _apply_fee(amount: int) -> int:
    return amount * (10_000 - crypto_backtest.EXECUTION_BPS) // 10_000


def _quarter_id(ts: int) -> int:
    st = time.gmtime(int(ts))
    return int(st.tm_year) * 4 + (int(st.tm_mon) - 1) // 3


def flatten_book(
    state: dict[str, Any],
    lots: list[dict[str, Any]],
    opens: list[dict[str, Any]],
    close: float,
    ts: int,
    reason: str = "rotate",
) -> list[dict[str, Any]]:
    """Never a market order. Calendar must not buy or sell."""
    del lots, close, ts, reason
    for lot in list(opens):
        lot["closed"] = True
        lot["covered"] = True
        opens.remove(lot)
    state["gap_ts"] = {}
    return []


def regime_series(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[str]:
    n = min(len(highs), len(lows), len(closes))
    out = ["range"] * n
    if n < 40:
        return out
    a = adx(highs, lows, closes, 14)
    e5 = ema(closes, 5)
    e20 = ema(closes, 20)
    for i in range(n):
        av = a[i] if i < len(a) else None
        f = e5[i] if i < len(e5) else None
        s = e20[i] if i < len(e20) else None
        if av is None or f is None or s is None:
            continue
        if av > 25 and f > s:
            out[i] = "trend_up"
        elif av > 25 and f < s:
            out[i] = "trend_down"
        else:
            out[i] = "range"
    return out


def atr_series(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float]:
    n = min(len(highs), len(lows), len(closes))
    out = [0.01] * n
    if n < period + 1:
        return out
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    acc = sum(tr[1 : period + 1])
    px = closes[period] or 1.0
    out[period] = max(0.001, (acc / period) / px)
    for i in range(period + 1, n):
        acc += tr[i] - tr[i - period]
        px = closes[i] or 1.0
        out[i] = max(0.001, (acc / period) / px)
    return out


def regime_from_4h(highs: list[float], lows: list[float], closes: list[float]) -> str:
    if len(closes) < 40:
        return "range"
    a = last(adx(highs, lows, closes, 14))
    e5 = last(ema(closes, 5))
    e20 = last(ema(closes, 20))
    if a is None or e5 is None or e20 is None:
        return "range"
    if a > 25 and e5 > e20:
        return "trend_up"
    if a > 25 and e5 < e20:
        return "trend_down"
    return "range"


def atr_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 0.01
    trs: list[float] = []
    for i in range(1, len(closes)):
        trs.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    window = trs[-period:]
    atr = sum(window) / len(window)
    px = closes[-1] if closes[-1] else 1.0
    return max(0.001, atr / px)


def _params_path() -> Path:
    return ensure_state_dir() / PARAMS_NAME


def load_signal_params() -> dict[str, Any]:
    base = default_signal_params()
    try:
        payload = json.loads(_params_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return base
    if not isinstance(payload, dict):
        return base
    base.update(payload)
    return base


def save_signal_params(payload: dict[str, Any]) -> dict[str, Any]:
    merged = default_signal_params()
    merged.update(payload)
    path = _params_path()
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return merged


def trader_super(sig: dict[str, Any]) -> str:
    side = str(sig.get("super") or "none").strip().lower()
    if side in ("buy", "sell"):
        return side
    notes = sig.get("notes") or []
    blob = " ".join(str(item) for item in notes).lower()
    if "oversold" in blob:
        return "buy"
    if "overbought" in blob or "exit_long" in blob:
        return "sell"
    return "none"


def signal_series(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float] | None = None,
    params: dict[str, Any] | None = None,
) -> list[str]:
    """4x stoch stack (9/3/3, 14/3/3, 40/4/4, 60/10/10+vol) + RSI14 + MACD 12/26/9 + BB 14/2/0."""
    if isinstance(volumes, dict) and params is None:
        params = volumes
        volumes = None
    cfg = default_signal_params()
    if params:
        cfg.update(params)
    n = min(len(highs), len(lows), len(closes))
    out = ["none"] * n
    if n < 70:
        return out
    h = highs[:n]
    low = lows[:n]
    c = closes[:n]
    vols = list(volumes[:n]) if volumes is not None else [1.0] * n
    r = rsi(c, 14)
    _line, _sig, hist = macd(c)
    upper, _mid, lower = bollinger(c, 14, 2.0, 0)
    stacks: list[tuple[list[float | None], list[float | None], bool]] = []
    for k_len, k_sm, d_sm, use_vol in STOCH_STACK:
        kk, dd = stoch_kd(h, low, c, k_len, k_sm, d_sm)
        stacks.append((kk, dd, use_vol))
    vol_sma = sma(vols, 60)
    rsi_buy = float(cfg.get("rsi_buy") or 38)
    rsi_sell = float(cfg.get("rsi_sell") or 58)
    stoch_buy = float(cfg.get("stoch_buy") or 20)
    stoch_sell = float(cfg.get("stoch_sell") or 80)
    need = int(cfg.get("stoch_need") or 2)
    use_macd = bool(cfg.get("macd_buy"))
    use_bb = bool(cfg.get("bb_buy"))
    for i in range(70, n):
        oversold = 0
        overbought = 0
        for kk, dd, use_vol in stacks:
            kv = kk[i] if i < len(kk) else None
            dv = dd[i] if i < len(dd) else None
            if kv is None or dv is None:
                continue
            if use_vol:
                vs = vol_sma[i] if i < len(vol_sma) else None
                if vs is None or vols[i] < vs:
                    continue
            if kv <= stoch_buy and dv <= stoch_buy + 8:
                oversold += 1
            if kv >= stoch_sell and dv >= stoch_sell - 8:
                overbought += 1
        buy_votes = oversold
        sell_votes = overbought
        rv = r[i] if i < len(r) else None
        if rv is not None and rv <= rsi_buy:
            buy_votes += 1
        if rv is not None and rv >= rsi_sell:
            sell_votes += 1
        if (
            use_macd
            and i > 0
            and hist[i] is not None
            and hist[i - 1] is not None
            and hist[i - 1] <= 0 < hist[i]
        ):
            buy_votes += 1
        if (
            use_macd
            and i > 0
            and hist[i] is not None
            and hist[i - 1] is not None
            and hist[i - 1] >= 0 > hist[i]
        ):
            sell_votes += 1
        if use_bb and lower[i] is not None and c[i] <= float(lower[i]):
            buy_votes += 1
        if use_bb and upper[i] is not None and c[i] >= float(upper[i]):
            sell_votes += 1
        if buy_votes >= need and buy_votes > sell_votes:
            out[i] = "buy"
        elif sell_votes >= need and sell_votes > buy_votes:
            out[i] = "sell"
    return out


def mtf_super(votes: dict[str, str], tf_need: int = 2) -> str:
    buys = sum(1 for side in votes.values() if side == "buy")
    sells = sum(1 for side in votes.values() if side == "sell")
    hour = str(votes.get("1h") or "none")
    need = max(1, int(tf_need))
    if buys >= need and buys > sells and hour != "sell":
        return "buy"
    if sells >= need and sells > buys and hour != "buy":
        return "sell"
    return "none"


def cooldown_sec(atr_fraction: float) -> int:
    if atr_fraction >= 0.02:
        return 8 * 60
    if atr_fraction >= 0.012:
        return 15 * 60
    if atr_fraction >= 0.007:
        return 25 * 60
    return 40 * 60


def lot_usd(state: dict[str, Any], price: int) -> int:
    usd = int(state["usd"])
    if usd <= 0:
        return 0
    chunk = usd // 8
    floor = 1 * USD_SCALE
    cap = 20 * USD_SCALE
    size = max(floor, min(cap, chunk))
    return min(size, usd)


def set_armed(armed: bool) -> dict[str, Any]:
    state = load_state()
    state["armed"] = bool(armed)
    return save_state(state)


def reset_book() -> dict[str, Any]:
    book = str(load_state().get("book") or "gg")
    state = default_state()
    state["book"] = book
    save_state(state)
    path = _lots_path()
    try:
        path.unlink()
    except OSError:
        pass
    return state


_bt_mem: dict[str, tuple[int, dict[str, Any]]] = {}


def _slim_chart(chart: dict[str, Any]) -> dict[str, Any]:
    marks = list(chart.get("marks") or [])
    if len(marks) > 400:
        marks = marks[-400:]
    equity = list(chart.get("equity") or [])
    if len(equity) > 400:
        step = max(1, (len(equity) + 399) // 400)
        equity = equity[::step]
    return {
        "closes": list(chart.get("closes") or []),
        "times": list(chart.get("times") or []),
        "interval": str(chart.get("interval") or ""),
        "marks": marks,
        "equity": equity,
    }


def _slim_backtest(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.pop("lots", None)
    weeks = out.get("weeks")
    if isinstance(weeks, list) and len(weeks) > 16:
        active = [row for row in weeks if int((row or {}).get("fills") or 0) > 0]
        keep = active[-12:]
        if weeks:
            last = weeks[-1]
            if keep[-1:] != [last]:
                keep.append(last)
        out["weeks"] = keep
    months = out.get("months")
    if isinstance(months, list) and len(months) > 24:
        out["months"] = months[-24:]
    chart = out.get("chart")
    if isinstance(chart, dict):
        out["chart"] = _slim_chart(chart)
    # day_book stays — 34 rows, the live ledger
    return out


def _load_backtest_file(path: Path) -> dict[str, Any]:
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    hit = _bt_mem.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError):
        return {}
    if not isinstance(payload, dict):
        payload = {}
    slim = _slim_backtest(payload)
    _bt_mem[key] = (mtime, slim)
    return slim


def load_backtest() -> dict[str, Any]:
    return _load_backtest_file(_backtest_path())


def load_backtest_prev() -> dict[str, Any]:
    return _load_backtest_file(_backtest_prev_path())


def save_backtest(payload: dict[str, Any]) -> dict[str, Any]:
    if not crypto_backtest.PERSIST.get():
        return payload
    if isinstance(payload, dict) and not payload.get("ran_at"):
        payload["ran_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _backtest_path()
    prev = _backtest_prev_path()
    if path.is_file():
        try:
            old = path.read_text(encoding="utf-8")
            prev.write_text(old, encoding="utf-8")
            prev.chmod(0o600)
        except OSError:
            pass
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    _bt_mem.pop(str(path), None)
    _bt_mem.pop(str(prev), None)
    return payload


def _fill_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "side": row.get("side"),
        "horizon": row.get("horizon") or "day",
        "sol": format_units(row.get("sol"), 9),
        "pnl_sol": format_units(_lot_profit_sol(row), 9),
        "ts": row.get("ts"),
    }


def _day_book(lots: list[dict[str, Any]], day: str = "") -> dict[str, Any]:
    by_day: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in lots:
        if str(row.get("id") or "") == "lot-seed" or str(row.get("venue") or "") == "seed":
            continue
        if str(row.get("side") or "") not in ("buy", "sell"):
            continue
        try:
            ts = int(row.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        stamp = time.strftime("%Y-%m-%d", time.gmtime(ts))
        if stamp not in by_day:
            by_day[stamp] = []
            order.append(stamp)
        by_day[stamp].append(_fill_view(row))
    last = str(day or (order[-1] if order else ""))
    rows = by_day.get(last) or []
    return {
        "day": last,
        "fills": rows[-MAX_TRADES_DAY:],
        "n": min(len(rows), MAX_TRADES_DAY),
    }


def snapshot() -> dict[str, Any]:
    state = load_state()
    sol = int(state.get("sol") or 0)
    banked = int(state.get("banked_sol") or 0)
    usd = int(state.get("usd") or 0) + int(state.get("float_usd") or 0)
    lots = read_lots(128)
    today = _utc_day(int(state.get("last_ts") or 0) or None)
    return {
        "armed": bool(state.get("armed")),
        "regime": str(state.get("regime") or "range"),
        "trades_today": int(state.get("trades_today") or 0),
        "min_day": MIN_TRADES_DAY,
        "max_day": MAX_TRADES_DAY,
        "open_lots": len(_open_lots_from(lots)),
        "max_open": MAX_OPEN_LOTS,
        "bands": {"buy": BAND_BUY, "sell": BAND_SELL},
        "horizons": (state.get("last") or {}).get("horizons")
        if isinstance(state.get("last"), dict)
        else {},
        "osc": (state.get("last") or {}).get("osc")
        if isinstance(state.get("last"), dict)
        else {},
        "float_bps": FLOAT_BPS,
        "bank_bps": PROFIT_BANK_BPS,
        "usd": format_units(usd, 6),
        "sol": format_units(sol, 9),
        "banked_sol": format_units(banked, 9),
        "banked_usd": format_units(int(state.get("banked_usd") or 0), 6),
        "tokens": format_units(sol + banked, 9),
        "seeded": bool(state.get("seeded")),
        "book": str(state.get("book") or "gg"),
        "last": state.get("last") if isinstance(state.get("last"), dict) else {},
        "mtf": (state.get("last") or {}).get("mtf")
        if isinstance(state.get("last"), dict)
        else {},
        "flow": (state.get("last") or {}).get("flow")
        if isinstance(state.get("last"), dict)
        else {},
        "macro": (state.get("last") or {}).get("macro")
        if isinstance(state.get("last"), dict)
        else "",
        "vote": (state.get("last") or {}).get("vote")
        if isinstance(state.get("last"), dict)
        else "",
        "lots": lots,
        "day_book": _day_book(lots, today),
        "backtest": load_backtest(),
        "backtest_prev": load_backtest_prev(),
        "contracts": {
            "vault": "20% of trade profit. 80% stays in the trade and buys more tokens",
            "cpmm": "lab constant-product pools",
            "mainnet": "NOT_ARMED",
        },
    }


def _open_lots_from(lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_rows: list[dict[str, Any]] = []
    window = lots[-512:] if len(lots) > 512 else lots
    for row in window:
        if row.get("side") == "buy" and not row.get("closed"):
            open_rows.append(row)
        if (
            row.get("side") == "sell"
            and not row.get("closed")
            and not row.get("covered")
            and not row.get("closes")
        ):
            open_rows.append(row)
        if row.get("side") == "sell" and row.get("closes"):
            cid = row.get("closes")
            for item in open_rows:
                if item.get("id") == cid:
                    item["closed"] = True
            open_rows = [x for x in open_rows if x.get("id") != cid]
    return open_rows


def _seed_vault(
    state: dict[str, Any],
    price: int,
    lots: list[dict[str, Any]] | None = None,
    opens: list[dict[str, Any]] | None = None,
) -> None:
    if state.get("seeded"):
        return
    state["banked_sol"] = 0
    state["seeded"] = True
    if price <= 0:
        state["start_sol"] = START_SOL
        return
    start_sol = START_USD * SOL_SCALE // price
    state["start_sol"] = start_sol
    if lots is None or str(state.get("seed_style") or "") != "long":
        state["usd"] = START_USD
        state["sol"] = 0
        state["banked_usd"] = int(state.get("banked_usd") or 0)
        state["swing_anchor"] = {row["id"]: price for row in SWINGS}
        state["swing_high"] = {row["id"]: price for row in SWINGS}
        state["grid_px"] = price
        state["cost_px"] = price
        return
    state["usd"] = 0
    state["sol"] = _apply_fee(start_sol)
    state["banked_usd"] = 0
    state["banked_sol"] = 0
    state["cost_px"] = price
    state["cycle_sold_sol"] = 0
    state["cycle_sold_usd"] = 0
    state["swing_low"] = {row["id"]: price for row in SWINGS}
    state["swing_anchor"] = {row["id"]: price for row in SWINGS}
    state["swing_high"] = {row["id"]: price for row in SWINGS}
    state["grid_px"] = price


def _cpmm_buy(usd_in: int, price: int) -> tuple[int, str]:
    """Compatibility wrapper: market paper fills never route through the lab pool."""
    if price <= 0:
        raise ValueError("CRYPTO_PRICE")
    return _apply_fee(int(usd_in)) * SOL_SCALE // price, "paper"


def _cpmm_sell(sol_in: int, price: int) -> tuple[int, str]:
    if price <= 0:
        raise ValueError("CRYPTO_PRICE")
    return _apply_fee(int(sol_in) * price // SOL_SCALE), "paper"


def apply_tick(
    state: dict[str, Any],
    lots: list[dict[str, Any]],
    close: float,
    sig: dict[str, Any],
    regime: str,
    atr_fraction: float,
    now: int,
    execute_contracts: bool = False,
) -> dict[str, Any]:
    ts = int(now)
    day = _utc_day(ts)
    if state.get("day") != day:
        state["day"] = day
        state["trades_today"] = 0
    state["regime"] = regime
    price = _price_atoms(close)
    _seed_vault(state, price)
    action = "hold"
    note = "no super · " + regime
    cooldown = cooldown_sec(atr_fraction)
    if not state.get("armed"):
        note = "disarmed"
    elif int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
        note = "day cap"
    elif ts - int(state.get("last_ts") or 0) < cooldown:
        note = "cooldown " + str(cooldown) + "s"
    else:
        super_sig = trader_super(sig)
        opens = _open_lots_from(lots)
        if (
            super_sig == "buy"
            and regime != "trend_down"
            and len(opens) < MAX_OPEN_LOTS
        ):
            usd_in = lot_usd(state, price)
            if usd_in > 0:
                if execute_contracts:
                    sol_got, venue = _cpmm_buy(usd_in, price)
                else:
                    sol_got, venue = _apply_fee(usd_in) * SOL_SCALE // price, "paper"
                if sol_got > 0:
                    state["usd"] = int(state["usd"]) - usd_in
                    state["sol"] = int(state["sol"]) + sol_got
                    lot_id = "lot-" + str(ts)
                    row = {
                        "id": lot_id,
                        "ts": ts,
                        "side": "buy",
                        "sol": sol_got,
                        "usd": usd_in,
                        "price": price,
                        "regime": regime,
                        "venue": venue,
                        "closed": False,
                    }
                    lots.append(row)
                    state["trades_today"] = int(state["trades_today"]) + 1
                    state["last_ts"] = ts
                    action = "buy"
                    note = "buy " + format_units(sol_got, 9)
        elif super_sig == "sell" and int(state.get("sol") or 0) > 0:
            opens = _open_lots_from(lots)
            lot = opens[0] if opens else None
            sol_sell = int(lot["sol"]) if lot else int(state["sol"])
            sol_sell = min(sol_sell, int(state["sol"]))
            if execute_contracts:
                usd_net, venue = _cpmm_sell(sol_sell, price)
            else:
                usd_net, venue = _apply_fee(sol_sell * price // SOL_SCALE), "paper"
            cost = int(lot["usd"]) if lot else usd_net
            profit = usd_net - cost
            state["sol"] = int(state["sol"]) - sol_sell
            if lot is not None:
                lot["closed"] = True
            if profit > 0:
                bank_usd = profit * PROFIT_BANK_BPS // 10_000
                roll_usd = profit - bank_usd
                bank_sol = bank_usd * SOL_SCALE // price
                state["banked_sol"] = int(state["banked_sol"]) + bank_sol
                state["usd"] = int(state["usd"]) + cost + roll_usd
            else:
                state["usd"] = int(state["usd"]) + usd_net
            row = {
                "id": "sell-" + str(ts),
                "ts": ts,
                "side": "sell",
                "sol": sol_sell,
                "usd": usd_net,
                "price": price,
                "profit_usd": profit,
                "regime": regime,
                "closes": (lot or {}).get("id"),
                "bank_bps": PROFIT_BANK_BPS if profit > 0 else 0,
                "venue": venue,
            }
            lots.append(row)
            state["trades_today"] = int(state["trades_today"]) + 1
            state["last_ts"] = ts
            action = "sell"
            note = "sell profit " + format_units(profit, 6)
    state["last"] = {
        "action": action,
        "note": note,
        "regime": regime,
        "atr_pct": atr_fraction,
        "super": sig.get("super"),
        "close": close,
        "cooldown": cooldown,
        "mtf": sig.get("mtf") if isinstance(sig.get("mtf"), dict) else {},
    }
    return state["last"]


def osc_last(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float] | None = None,
) -> dict[str, Any]:
    """All 0–100 oscillators on one TF. Buy band ≤25, sell band ≥70."""
    n = min(len(highs), len(lows), len(closes))
    if n < 30:
        return {"rsi": None, "buy_n": 0, "sell_n": 0, "close": closes[-1] if closes else 0.0}
    h, lo, c = highs[:n], lows[:n], closes[:n]
    vols = list(volumes[:n]) if volumes is not None else [1.0] * n
    readings: list[tuple[str, float | None]] = []
    readings.append(("rsi", last(rsi(c, 14))))
    stack_k: list[float | None] = []
    for k_len, k_sm, d_sm, _vol in STOCH_STACK:
        kk, dd = stoch_kd(h, lo, c, k_len, k_sm, d_sm)
        k_last = last(kk)
        stack_k.append(k_last)
        readings.append(("stoch" + str(k_len) + "k", k_last))
        readings.append(("stoch" + str(k_len) + "d", last(dd)))
    readings.append(("stoch_rsi", last(stoch_rsi(c, 14, 14))))
    readings.append(("mfi", last(mfi(h, lo, c, vols, 14))))
    readings.append(("cci", last(cci_osc(h, lo, c, 20))))
    readings.append(("williams", last(williams_osc(h, lo, c, 14))))
    readings.append(("bb", last(bb_percent(c, 14, 2.0))))
    readings.append(("rsi2", last(rsi(c, 2))))
    readings.append(("uo", last(ultimate_osc(h, lo, c))))
    readings.append(("cmo", last(cmo_osc(c, 14))))
    readings.append(("cmf", last(cmf_osc(h, lo, c, vols, 20))))
    readings.append(("aroon", last(aroon_osc(h, lo, 25))))
    readings.append(("stc", last(schaff_trend(c))))
    readings.append(("keltner", last(keltner_percent(h, lo, c))))
    readings.append(("donchian", last(donchian_percent(h, lo, c))))
    readings.append(("ichimoku", last(ichimoku_osc(h, lo, c))))
    readings.append(("supertrend", last(supertrend_osc(h, lo, c))))
    readings.append(("heikin", last(heikin_osc(h, lo, c))))
    readings.append(("sar", last(sar_osc(h, lo, c))))
    readings.append(("ribbon", last(ema_ribbon_osc(c))))
    readings.append(("candle", last(candle_osc(h, lo, c))))
    buy_n = 0
    sell_n = 0
    out: dict[str, Any] = {"close": c[-1]}
    for name, value in readings:
        out[name] = None if value is None else round(float(value), 2)
        if in_buy_band(value):
            buy_n += 1
        if in_sell_band(value):
            sell_n += 1
    out["buy_n"] = buy_n
    out["sell_n"] = sell_n
    out["rsi"] = out.get("rsi")
    out["stoch_stack"] = [
        None if item is None else round(float(item), 2) for item in stack_k
    ]
    stoch14 = stack_k[1] if len(stack_k) > 1 else None
    out["stoch"] = None if stoch14 is None else round(float(stoch14), 2)
    _line, _sig, hist = macd(c)
    out["macd_hist"] = last(hist)
    out["ema20"] = last(ema(c, 20))
    out["ema50"] = last(ema(c, 50))
    return out


def _mark_cycle_day(state: dict[str, Any], tf_osc: dict[str, dict[str, Any]]) -> None:
    """Count 1d overbought days. Once per 1d close."""
    osc_1d = tf_osc.get("1d") or {}
    close_1d = osc_1d.get("close")
    if close_1d is None:
        return
    close_1d = float(close_1d)
    if state.get("ob_1d_close") == close_1d:
        return
    state["ob_1d_close"] = close_1d
    rsi_1d = osc_1d.get("rsi")
    if rsi_1d is not None and float(rsi_1d) >= BAND_SELL:
        state["ob_days"] = int(state.get("ob_days") or 0) + 1
    lows = state.get("day_lows")
    if not isinstance(lows, list):
        lows = []
    lows.append(close_1d)
    state["day_lows"] = lows[-YEAR_LOW_BARS:]


def _touch_swing_low(state: dict[str, Any], price: int) -> None:
    lows = state.get("swing_low")
    if not isinstance(lows, dict):
        lows = {}
    for row in SWINGS:
        hid = str(row["id"])
        prev = lows.get(hid)
        if prev is None or int(prev) <= 0 or price < int(prev):
            lows[hid] = price
    state["swing_low"] = lows


def _touch_swing_high(state: dict[str, Any], price: int) -> None:
    highs = state.get("swing_high")
    if not isinstance(highs, dict):
        highs = {}
    for row in SWINGS:
        hid = str(row["id"])
        prev = highs.get(hid)
        if prev is None or int(prev) <= 0 or price > int(prev):
            highs[hid] = price
    state["swing_high"] = highs


def _powder_usd(state: dict[str, Any]) -> int:
    return int(state.get("usd") or 0) + int(state.get("float_usd") or 0)


def _claim_tokens(state: dict[str, Any], covers: list[dict[str, Any]]) -> int:
    """Tradable bag for core-keep. Vault is already off the table."""
    risk = sum(int(row.get("sol") or 0) for row in covers)
    return int(state.get("sol") or 0) + risk


def _paper_fill(
    usd_in: int,
    sol_in: int,
    price: int,
    execute_contracts: bool,
    buy: bool,
) -> tuple[int, str]:
    # execute_contracts is retained for compatibility; this is a simulation.
    # The ARB tab's local CPMM is not a quote for the observed market price.
    return _cpmm_buy(usd_in, price) if buy else _cpmm_sell(sol_in, price)


def _grid_regime(tf_flow: dict[str, str] | None) -> str:
    """Bull holds the float; bear holds powder; range is osc in/out."""
    flow = tf_flow or {}
    flow_1d = str(flow.get("1d") or "")
    flow_4h = str(flow.get("4h") or "")
    if flow_1d == "trend_down" or flow_4h == "trend_down":
        return "bear"
    if flow_1d == "trend_up":
        return "bull"
    return "range"


def _timing_oversold(tf_osc: dict[str, dict[str, Any]] | None) -> bool:
    """Same 25-band as live. 1d/4h/1h only — 1m is not a buy zone of its own."""
    osc = tf_osc or {}
    for tf in ("1d", "4h", "1h"):
        if in_buy_band((osc.get(tf) or {}).get("rsi")):
            return True
    return False


def _timing_pullback(tf_osc: dict[str, dict[str, Any]] | None) -> bool:
    """Week covers a 4h/1h dip. 40 is a pullback, 25 is the turn."""
    if _timing_oversold(tf_osc):
        return True
    osc = tf_osc or {}
    for tf in ("4h", "1h"):
        rsi_v = (osc.get(tf) or {}).get("rsi")
        if rsi_v is not None and float(rsi_v) <= 40.0:
            return True
    return False


def _ladder_bump(
    state: dict[str, Any],
    side: str,
    tf: str,
    price: int,
    bag0: int = 0,
    keep: int = 0,
    usd0: int = 0,
) -> None:
    row = state.get("ladder")
    if not isinstance(row, dict) or str(row.get("side") or "") != side:
        state["ladder"] = {
            "side": side,
            "tf": tf,
            "n": 1,
            "px": int(price),
            "bag0": int(bag0),
            "keep": int(keep),
            "usd0": int(usd0),
        }
        return
    row["n"] = int(row.get("n") or 0) + 1
    row["px"] = int(price)
    row["tf"] = tf


def _bank_profit_usd(state: dict[str, Any], profit: int, usd_net: int) -> int:
    """1.00 → 1.05: bank 20% of the 0.05. The 1.04 stays in the trade.
    Never bank principal. A loss leaves the remainder in float.
    """
    bank = 0
    if profit > 0:
        bank = profit * PROFIT_BANK_BPS // 10_000
        bank = min(bank, max(0, usd_net))
    state["banked_usd"] = int(state.get("banked_usd") or 0) + bank
    state["float_usd"] = int(state.get("float_usd") or 0) + (usd_net - bank)
    return bank


def _touch_cost_px(state: dict[str, Any], prev_sol: int, usd_in: int, sol_got: int) -> None:
    prev_cost = int(state.get("cost_px") or 0)
    new_sol = prev_sol + sol_got
    if new_sol <= 0:
        return
    state["cost_px"] = (prev_sol * prev_cost + usd_in * SOL_SCALE) // new_sol


def _ladder_step(
    state: dict[str, Any],
    tf_osc: dict[str, dict[str, Any]],
    osc_prev: dict[str, Any],
    price: int,
) -> tuple[str, str]:
    """Next clip around the same extreme. Running into the high/low is not a clip."""
    row = state.get("ladder")
    if not isinstance(row, dict):
        return "", ""
    side = str(row.get("side") or "")
    tf = str(row.get("tf") or "")
    n = int(row.get("n") or 0)
    px0 = int(row.get("px") or 0)
    if side not in ("buy", "sell") or not tf or n >= LADDER_N or px0 <= 0:
        return "", ""
    osc = tf_osc.get(tf) or {}
    prev = osc_prev.get(tf) or {}
    sell = side == "sell"
    if _tf_left_mid(osc, sell):
        state["ladder"] = {}
        return "", ""
    if not _stoch_cluster(osc, sell)[1]:
        return "", ""
    now_m = _stoch_mean(osc)
    prev_m = _stoch_mean(prev)
    if now_m is None or prev_m is None:
        return "", ""
    if sell and now_m > prev_m:
        return "", ""
    if (not sell) and now_m < prev_m:
        return "", ""
    need = LADDER_SELL_BPS if sell else LADDER_BUY_BPS
    if abs(price - px0) * 10_000 < px0 * need:
        return "", ""
    return side, tf


def _apply_float_grid(
    state: dict[str, Any],
    lots: list[dict[str, Any]],
    price: int,
    ts: int,
    execute_contracts: bool,
    notes: list[str],
    tf_flow: dict[str, str] | None = None,
    tf_osc: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Buy low, sell high. Bank 20% of trade profit. The rest compounds.
    Several clips around the top/bottom. Not one exact tick.
    """
    if int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
        return ""
    if price <= 0:
        return ""
    last = int(state.get("grid_px") or 0)
    if last <= 0:
        state["grid_px"] = price
        return ""
    action = ""
    bag = int(state.get("sol") or 0)
    peak = int(state.get("peak_tokens") or 0)
    if peak < bag:
        peak = bag
        state["peak_tokens"] = bag
    lad = state.get("ladder")
    if not isinstance(lad, dict):
        lad = {}
    keep0 = int(lad.get("keep") or 0)
    bag0 = int(lad.get("bag0") or 0)
    usd0 = int(lad.get("usd0") or 0)
    seeded = int(state.get("start_sol") or START_SOL)
    core = keep0 if keep0 > 0 else max(MIN_SOL_LOT, seeded * CORE_KEEP_BPS // 10_000)
    regime = _grid_regime(tf_flow)
    osc_prev = state.get("osc_prev")
    if not isinstance(osc_prev, dict):
        osc_prev = {}
    waterfall = regime == "bear"
    if waterfall:
        state["ladder"] = {}
    armed = state.get("zone_armed")
    if not isinstance(armed, dict):
        armed = {}
        state["zone_armed"] = armed
    last_fill_ts = int(state.get("float_fill_ts") or 0)
    if last_fill_ts and ts - last_fill_ts < BAR_SEC["15m"]:
        return ""
    if waterfall:
        return ""
    sell_fresh = _fresh_hooks(tf_osc or {}, osc_prev, True, FILL_TFS, armed)
    buy_fresh = _fresh_hooks(tf_osc or {}, osc_prev, False, FILL_TFS, armed)
    sell_tf = next((tf for tf in MACRO_TFS if tf in sell_fresh), None)
    if sell_tf is None and regime != "bull":
        sell_tf = next((tf for tf in TIMEFRAMES if tf in sell_fresh), None)
    buy_tf = next((tf for tf in TIMING_TFS if tf in buy_fresh), None)
    if buy_tf is None:
        buy_tf = next((tf for tf in TIMEFRAMES if tf in buy_fresh), None)
    continued = False
    if not sell_tf and not buy_tf:
        side, tf = _ladder_step(state, tf_osc or {}, osc_prev, price)
        if side == "sell" and (regime != "bull" or tf in MACRO_TFS):
            sell_tf = tf
            continued = True
        elif side == "buy":
            buy_tf = tf
            continued = True
    hooks = 1
    buy_map = state.get("tf_buy_px")
    if not isinstance(buy_map, dict):
        buy_map = {}
        state["tf_buy_px"] = buy_map
    sell_map = state.get("tf_sell_px")
    if not isinstance(sell_map, dict):
        sell_map = {}
        state["tf_sell_px"] = sell_map
    clip_meta = {"bag0": 0, "keep": 0, "usd0": 0}

    def do_buy() -> bool:
        last_sell = max(
            int(sell_map.get(str(buy_tf)) or 0),
            int(state.get("grid_last_sell_px") or 0),
        )
        if (
            last_sell
            and _same_market_px(last_sell, price)
            and price * 10_000 > last_sell * (10_000 - MIN_COVER_BPS)
        ):
            return False
        fu = int(state.get("float_usd") or 0)
        bag_now = int(state.get("sol") or 0)
        clip_meta["usd0"] = fu
        clip_meta["bag0"] = bag_now
        base_usd = usd0 if (continued and usd0 > 0) else fu
        usd_in = max(USD_SCALE // 20, base_usd * BUY_CLIP_BPS // 10_000)
        extra_usd = 0
        if fu < usd_in and state.get("cash_cycle"):
            pocket = int(state.get("peak_tokens") or 0) * FLOAT_KEEP_BPS // 10_000
            if bag_now < pocket:
                extra_usd = min(int(state.get("usd") or 0), usd_in - fu)
        usd_in = min(fu + extra_usd, usd_in)
        if usd_in < USD_SCALE // 20:
            return False
        sol_got, venue = _paper_fill(usd_in, 0, price, execute_contracts, True)
        if sol_got <= 0:
            return False
        take = min(fu, usd_in)
        state["float_usd"] = fu - take
        state["usd"] = int(state.get("usd") or 0) - (usd_in - take)
        sold_usd = int(state.get("cycle_sold_usd") or 0)
        sold_sol = int(state.get("cycle_sold_sol") or 0)
        extra = 0
        if sold_usd > 0:
            matched = min(usd_in, sold_usd)
            ref_sol = sold_sol * matched // sold_usd
            got = sol_got * matched // usd_in if usd_in else sol_got
            extra = got - ref_sol
            state["cycle_sold_usd"] = sold_usd - matched
            state["cycle_sold_sol"] = max(0, sold_sol - ref_sol)
        _touch_cost_px(state, bag_now, usd_in, sol_got)
        state["sol"] = bag_now + sol_got
        lots.append(
            {
                "id": "grid-buy-" + str(ts) + "-" + str(len(lots)),
                "ts": ts,
                "side": "buy",
                "horizon": "day",
                "sol": sol_got,
                "usd": usd_in,
                "price": price,
                "extra_sol": extra,
                "venue": venue,
                "closed": True,
            }
        )
        state["trades_today"] = int(state.get("trades_today") or 0) + 1
        state["last_ts"] = ts
        state["grid_px"] = price
        state["grid_last_buy_px"] = price
        buy_map[str(buy_tf)] = price
        state["float_fill_ts"] = ts
        state["float_trimmed"] = False
        notes.append("dip buy")
        return True

    def do_trim() -> bool:
        last_buy = max(
            int(buy_map.get(str(sell_tf)) or 0),
            int(state.get("grid_last_buy_px") or 0),
        )
        hold = int(state.get("sol") or 0)
        if hold <= MIN_SOL_LOT:
            return False
        cost_px = int(state.get("cost_px") or 0)
        if cost_px > 0 and price * 10_000 < cost_px * (10_000 + MIN_COVER_BPS):
            return False
        keep = core if core else max(MIN_SOL_LOT, seeded * CORE_KEEP_BPS // 10_000)
        clip_meta["bag0"] = seeded
        clip_meta["keep"] = keep
        slice_sol = max(MIN_SOL_LOT, seeded * GRID_SLICE_BPS // 10_000)
        slice_sol = min(slice_sol, hold - keep)
        if slice_sol < MIN_SOL_LOT or hold - slice_sol < 0:
            return False
        usd_net, venue = _paper_fill(0, slice_sol, price, execute_contracts, False)
        if usd_net <= 0:
            return False
        cost = slice_sol * cost_px // SOL_SCALE if cost_px > 0 else 0
        profit = usd_net - cost if cost > 0 else 0
        state["sol"] = hold - slice_sol
        _bank_profit_usd(state, profit, usd_net)
        state["cycle_sold_sol"] = int(state.get("cycle_sold_sol") or 0) + slice_sol
        state["cycle_sold_usd"] = int(state.get("cycle_sold_usd") or 0) + usd_net
        state["grid_last_sell_sol"] = slice_sol
        state["grid_last_sell_px"] = price
        sell_map[str(sell_tf)] = price
        lots.append(
            {
                "id": "grid-sell-" + str(ts) + "-" + str(len(lots)),
                "ts": ts,
                "side": "sell",
                "horizon": "day",
                "sol": slice_sol,
                "usd": usd_net,
                "price": price,
                "profit_usd": profit,
                "bank_bps": PROFIT_BANK_BPS if profit > 0 else 0,
                "venue": venue,
                "covered": True,
                "closed": True,
            }
        )
        state["trades_today"] = int(state.get("trades_today") or 0) + 1
        state["last_ts"] = ts
        state["grid_px"] = price
        state["float_fill_ts"] = ts
        state["float_trimmed"] = True
        notes.append("trim float")
        return True

    if sell_tf:
        hooks = _guess_agree((tf_osc or {}).get(str(sell_tf)) or {}, True)
    elif buy_tf:
        hooks = _guess_agree((tf_osc or {}).get(str(buy_tf)) or {}, False)
    if not continued and hooks < 2:
        return ""
    if continued:
        hooks = 1
    else:
        hooks = min(2, max(1, hooks))
    if sell_tf:
        if do_trim():
            armed[sell_tf] = "sell"
            osc = (tf_osc or {}).get(str(sell_tf)) or {}
            if _stoch_cluster(osc, True)[1]:
                _ladder_bump(
                    state,
                    "sell",
                    str(sell_tf),
                    price,
                    bag0=int(clip_meta["bag0"]),
                    keep=int(clip_meta["keep"]),
                )
            notes[-1] = "trim around top" if continued else notes[-1]
            action = "sell"
    elif buy_tf and not waterfall:
        if do_buy():
            armed[buy_tf] = "buy"
            osc = (tf_osc or {}).get(str(buy_tf)) or {}
            if _stoch_cluster(osc, False)[1]:
                _ladder_bump(
                    state,
                    "buy",
                    str(buy_tf),
                    price,
                    bag0=int(clip_meta["bag0"]),
                    usd0=int(clip_meta["usd0"]),
                )
            notes[-1] = "buy around bottom" if continued else notes[-1]
            action = "buy"
    return action


def _apply_nested_swings(
    state: dict[str, Any],
    lots: list[dict[str, Any]],
    opens: list[dict[str, Any]],
    covers: list[dict[str, Any]],
    price: int,
    ts: int,
    tf_osc: dict[str, dict[str, Any]],
    tf_super: dict[str, str] | None,
    tf_flow: dict[str, str] | None,
    execute_contracts: bool,
    notes: list[str],
) -> str:
    """Week/month rips plus a momentum float (hold the bull, osc-trim the 15%)."""
    if int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
        return ""
    action = _apply_float_grid(
        state, lots, price, ts, execute_contracts, notes,
        tf_flow=tf_flow, tf_osc=tf_osc,
    )
    gaps = state.get("gap_ts")
    if not isinstance(gaps, dict):
        gaps = {}
        state["gap_ts"] = gaps
    lows = state.get("swing_low")
    if not isinstance(lows, dict):
        lows = {}
        state["swing_low"] = lows
    flow_1d = str((tf_flow or {}).get("1d") or "")
    flow_4h = str((tf_flow or {}).get("4h") or "")
    waterfall = flow_1d == "trend_down" and flow_4h == "trend_down"

    def bump(kind: str, hid: str) -> None:
        state["trades_today"] = int(state.get("trades_today") or 0) + 1
        state["last_ts"] = ts
        gaps[hid] = ts
        notes.append(kind + " " + hid)

    anchors = state.get("swing_anchor")
    if not isinstance(anchors, dict):
        anchors = {}
        state["swing_anchor"] = anchors

    def take_cover(cover: dict[str, Any], hid: str, kind: str) -> bool:
        if hid == "week":
            if not _timing_pullback(tf_osc):
                return False
        elif not _timing_oversold(tf_osc):
            return False
        usd_in = min(int(state.get("float_usd") or 0), int(cover.get("usd") or 0))
        if usd_in < USD_SCALE // 20:
            return False
        sol_got, venue = _paper_fill(usd_in, 0, price, execute_contracts, True)
        if sol_got <= 0:
            return False
        state["float_usd"] = int(state.get("float_usd") or 0) - usd_in
        state["sol"] = int(state["sol"]) + sol_got
        extra = sol_got - int(cover.get("sol") or 0)
        cover["covered"] = True
        cover["closed"] = True
        if cover in opens:
            opens.remove(cover)
        if cover in covers:
            covers.remove(cover)
        _touch_cost_px(
            state,
            int(state["sol"]) - sol_got,
            usd_in,
            sol_got,
        )
        lots.append(
            {
                "id": kind + "-" + hid + "-" + str(ts),
                "ts": ts,
                "side": "buy",
                "horizon": hid,
                "sol": sol_got,
                "usd": usd_in,
                "price": price,
                "extra_sol": extra,
                "rejoin": kind == "rejoin",
                "venue": venue,
                "closed": True,
            }
        )
        lows[hid] = price
        anchors[hid] = price
        bump(kind, hid)
        return True

    for cover in list(covers):
        if int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
            break
        hid = str(cover.get("horizon") or "")
        if hid == "day":
            continue
        cfg = _swing_cfg(hid)
        if cfg is None:
            continue
        sold_px = int(cover.get("price") or 0)
        if sold_px <= 0:
            continue
        peak = max(int(cover.get("peak") or sold_px), price)
        cover["peak"] = peak
        need = _cover_need(cfg)
        hit = price * 10_000 <= sold_px * (10_000 - need)
        if hid == "day" and peak > sold_px:
            hit = hit or price * 10_000 <= peak * (10_000 - need)
        if hid == "day" and ts - int(cover.get("ts") or 0) >= DAY_HOLD_SEC:
            hit = True
        if not hit:
            continue
        if hid != "day":
            rt = tuple(cfg.get("realtime") or ())
            if rt and any(
                _tf_available(tf, tf_osc, tf_super or {}, tf_flow or {})
                and _tf_wants_sell(tf, tf_osc, tf_super or {})
                for tf in rt
            ):
                continue
        if take_cover(cover, hid, "cover"):
            action = "buy"
    if not waterfall:
        for cfg in SWINGS:
            if int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
                break
            hid = str(cfg["id"])
            if hid == "day":
                continue
            cover = next(
                (row for row in covers if str(row.get("horizon") or "") == hid),
                None,
            )
            if cover is None:
                continue
            opened = int(cover.get("ts") or 0)
            wait = int(cfg.get("park_sec") or cfg["gap_sec"])
            if opened and ts - opened < wait:
                continue
            sold_px = int(cover.get("price") or 0)
            need = _cover_need(cfg)
            if sold_px and price * 10_000 <= sold_px * (10_000 - need):
                if take_cover(cover, hid, "cover"):
                    action = "buy"
                continue
            run = int(cfg.get("park_run_bps") or 800)
            if sold_px and price * 10_000 > sold_px * (10_000 + run):
                cover["covered"] = True
                cover["closed"] = True
                cover["parked"] = True
                if cover in opens:
                    opens.remove(cover)
                if cover in covers:
                    covers.remove(cover)
                lows[hid] = price
                anchors[hid] = price
                gaps[hid] = ts
                notes.append("park " + hid)
    if int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
        return action
    for cfg in SWINGS:
        if int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
            break
        if len(covers) >= MAX_UNCOVERED or len(opens) >= MAX_OPEN_LOTS:
            break
        hid = str(cfg["id"])
        if hid == "day":
            continue
        if waterfall or flow_1d == "trend_down":
            continue
        rsi_1d = (tf_osc.get("1d") or {}).get("rsi")
        if flow_1d == "trend_up" and not in_sell_band(rsi_1d):
            continue
        if ts < int(state.get("grid_hold_sell_ts") or 0):
            continue
        open_h = sum(1 for row in covers if str(row.get("horizon") or "") == hid)
        max_h = int((HORIZONS.get(hid) or {}).get("max_open") or 1)
        if open_h >= max_h:
            continue
        vote = swing_vote(
            hid, tf_osc, tf_super, tf_flow, osc_prev=state.get("osc_prev")
        )
        if vote.get("side") != "sell":
            continue
        prev = int(gaps.get(hid) or 0)
        if int(cfg["gap_sec"]) and prev and ts - prev < int(cfg["gap_sec"]):
            continue
        floor = int(anchors.get(hid) or 0)
        if floor <= 0:
            anchors[hid] = price
            continue
        if hid == "day" and open_h == 0 and floor > 0:
            drift = abs(price - floor) * 10_000
            if drift >= floor * 800:
                anchors[hid] = price
                continue
        if price * 10_000 < floor * (10_000 + int(cfg["min_move_bps"])):
            continue
        bag = int(state.get("sol") or 0)
        risk = sum(int(row.get("sol") or 0) for row in covers)
        total = bag + risk
        if total <= 0 or risk * 10_000 >= total * MAX_BAG_RISK_BPS:
            break
        zone = stack_zone(tf_osc, sell=True)
        conv = 10_000
        if int(zone["n"]) >= 3:
            conv += 500
        if int(zone["depth"]) >= 2:
            conv += 400
        slice_sol = bag * int(cfg["slice_bps"]) * conv // 10_000 // 10_000
        slice_sol = max(MIN_SOL_LOT, min(slice_sol, bag))
        remain = bag - slice_sol
        core = max(MIN_SOL_LOT, bag * CORE_KEEP_BPS // 10_000)
        if remain < core:
            continue
        if slice_sol < MIN_SOL_LOT:
            continue
        usd_net, venue = _paper_fill(0, slice_sol, price, execute_contracts, False)
        if usd_net <= 0:
            continue
        state["sol"] = int(state["sol"]) - slice_sol
        state["float_usd"] = int(state.get("float_usd") or 0) + usd_net
        row = {
            "id": "swing-" + hid + "-" + str(ts),
            "ts": ts,
            "side": "sell",
            "horizon": hid,
            "sol": slice_sol,
            "usd": usd_net,
            "price": price,
            "venue": venue,
            "covered": False,
            "closed": False,
        }
        lots.append(row)
        opens.append(row)
        covers.append(row)
        anchors[hid] = price
        bump("swing", hid)
        action = "sell"
    return action


def _at_year_low(state: dict[str, Any], tf_osc: dict[str, dict[str, Any]]) -> bool:
    close_1d = (tf_osc.get("1d") or {}).get("close")
    if close_1d is None:
        return False
    close_1d = float(close_1d)
    lows = state.get("day_lows")
    if not isinstance(lows, list) or len(lows) < 90:
        return False
    floor = min(float(x) for x in lows)
    if floor <= 0 or close_1d <= 0:
        return False
    return close_1d * 10_000 <= floor * YEAR_LOW_BPS


def apply_horizons(
    state: dict[str, Any],
    lots: list[dict[str, Any]],
    close: float,
    tf_osc: dict[str, dict[str, Any]],
    regime: str,
    now: int,
    execute_contracts: bool = False,
    tf_super: dict[str, str] | None = None,
    tf_flow: dict[str, str] | None = None,
    open_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """SOL home. Long = hold SOL. USDT = powder to buy more tokens cheaper."""
    ts = int(now)
    day = _utc_day(ts)
    new_day = state.get("day") != day
    if new_day:
        state["day"] = day
        state["trades_today"] = 0
    state["regime"] = regime
    price = _price_atoms(close)
    if open_rows is None:
        opens = _open_lots_from(lots)
    else:
        opens = open_rows
    state["last_ts"] = state.get("last_ts") or ts
    _seed_vault(state, price, lots=lots, opens=opens)
    action = "hold"
    notes: list[str] = []
    vote = confluence_vote(tf_osc, tf_super, tf_flow)
    if not state.get("armed"):
        notes.append("disarmed")
    elif int(state.get("trades_today") or 0) >= MAX_TRADES_DAY:
        notes.append("day cap")
    else:
        longs = [row for row in opens if row.get("side") == "buy" and not row.get("closed")]
        covers = [
            row
            for row in opens
            if row.get("side") == "sell" and not row.get("covered") and not row.get("closed")
        ]
        if new_day:
            anchors = state.get("swing_anchor")
            if not isinstance(anchors, dict):
                anchors = {}
                state["swing_anchor"] = anchors
            if not any(str(row.get("horizon") or "") == "day" for row in covers):
                anchors["day"] = price
        claim = _claim_tokens(state, covers)
        peak = int(state.get("peak_tokens") or 0)
        if claim > peak:
            state["peak_tokens"] = claim
            peak = claim
        # Nominal token inventory excludes quote cash; it is not portfolio
        # drawdown. The shared forward runner enforces mark-to-market risk.
        state["token_inventory_drawdown"] = peak > 0 and claim * 10_000 < peak * (10_000 - PEAK_DD_BPS)
        _touch_swing_low(state, price)
        _touch_swing_high(state, price)
        oversold = False
        for tf in ("4h", "1h", "15m"):
            if _osc_pair_depth(tf_osc.get(tf) or {}, False) > 0:
                oversold = True
                break
        if oversold:
            prev_dump = state.get("dump_low")
            state["dump_low"] = (
                price if prev_dump is None else min(int(prev_dump), price)
            )
            state["osc_bounce"] = False
        elif state.get("dump_low") is not None:
            if price <= int(state["dump_low"]):
                state["osc_bounce"] = True
            else:
                state["dump_low"] = None
                state["osc_bounce"] = False
        prev_open = int((state.get("gap_ts") or {}).get("spot") or 0)
        gap_ok = (not ENTRY_GAP_SEC) or (ts - prev_open >= ENTRY_GAP_SEC)
        _mark_cycle_day(state, tf_osc)
        rsi_1d = (tf_osc.get("1d") or {}).get("rsi")
        if (
            rsi_1d is not None
            and float(rsi_1d) <= 40.0
            and not state.get("cash_cycle")
        ):
            state["bag_armed"] = True
        if vote.get("dca"):
            extra = int(state.get("banked_usd") or 0)
            if extra > 0:
                state["usd"] = int(state.get("usd") or 0) + extra
                state["banked_usd"] = 0
                notes.append("dca bank")
        sold = False
        if (
            EXECUTE_CYCLE_BAG
            and vote.get("bag_sell")
            and state.get("bag_armed")
            and not state.get("cash_cycle")
            and int(state.get("ob_days") or 0) >= BAG_OB_NEED
            and not any(
                str(row.get("horizon") or "spot") == "spot" for row in covers
            )
            and int(state.get("sol") or 0) >= MIN_SOL_LOT
            and len(opens) < MAX_OPEN_LOTS
        ):
            keep = int(state["sol"]) * FLOAT_KEEP_BPS // 10_000
            if keep < MIN_SOL_LOT:
                keep = 0
            slice_sol = int(state["sol"]) - keep
            slice_sol = max(MIN_SOL_LOT, min(slice_sol, int(state["sol"]) - keep))
            if execute_contracts:
                usd_net, venue = _cpmm_sell(slice_sol, price)
            else:
                usd_net, venue = _apply_fee(slice_sol * price // SOL_SCALE), "paper"
            if usd_net > 0:
                state["sol"] = int(state["sol"]) - slice_sol
                state["usd"] = int(state["usd"]) + usd_net
                row = {
                    "id": "raise-" + str(ts),
                    "ts": ts,
                    "side": "sell",
                    "horizon": "spot",
                    "sol": slice_sol,
                    "usd": usd_net,
                    "price": price,
                    "venue": venue,
                    "covered": False,
                    "closed": False,
                }
                lots.append(row)
                opens.append(row)
                state["bag_armed"] = False
                state["cash_cycle"] = True
                sold = True
                notes.append("bag " + str(vote.get("flow")) + " rsi " + str(vote.get("rsi")))
        elif vote.get("side") == "sell" and longs and str(vote.get("flow") or "") != "trend_up":
            lot = longs[0]
            sol_sell = min(int(lot.get("sol") or 0), int(state.get("sol") or 0))
            if sol_sell > 0:
                if execute_contracts:
                    usd_net, venue = _cpmm_sell(sol_sell, price)
                else:
                    usd_net, venue = _apply_fee(sol_sell * price // SOL_SCALE), "paper"
                cost = int(lot.get("usd") or usd_net)
                profit = usd_net - cost
                if profit > 0:
                    state["sol"] = int(state["sol"]) - sol_sell
                    lot["closed"] = True
                    if lot in opens:
                        opens.remove(lot)
                    bank_usd = profit * PROFIT_BANK_BPS // 10_000
                    roll_usd = profit - bank_usd
                    state["banked_usd"] = int(state.get("banked_usd") or 0) + bank_usd
                    state["usd"] = int(state["usd"]) + cost + roll_usd
                    lots.append(
                        {
                            "id": "sell-spot-" + str(ts),
                            "ts": ts,
                            "side": "sell",
                            "horizon": "spot",
                            "sol": sol_sell,
                            "usd": usd_net,
                            "price": price,
                            "profit_usd": profit,
                            "closes": lot.get("id"),
                            "venue": venue,
                            "bank_bps": PROFIT_BANK_BPS,
                        }
                    )
                    sold = True
                else:
                    state["usd"] = int(state.get("usd") or 0)
        if sold:
            state["trades_today"] = int(state["trades_today"]) + 1
            state["last_ts"] = ts
            gaps = state.get("gap_ts")
            if not isinstance(gaps, dict):
                gaps = {}
                state["gap_ts"] = gaps
            gaps["spot"] = ts
            action = "sell"
            notes.append("sell " + str(vote.get("flow")) + " rsi " + str(vote.get("rsi")))
        allow_buy = bool(vote.get("dca")) or not state.get("cash_cycle")
        if (
            vote.get("side") == "buy"
            and allow_buy
            and int(state.get("trades_today") or 0) < MAX_TRADES_DAY
            and (covers or gap_ok)
        ):
            dca_now = bool(vote.get("dca"))
            nested_wait = any(
                str(row.get("horizon") or "spot") != "spot" for row in covers
            )
            if dca_now:
                usd_in = int(state.get("usd") or 0)
                cover = covers[0] if covers else None
            elif nested_wait or str(state.get("seed_style") or "") == "long":
                usd_in = 0
                cover = None
            elif state.get("osc_bounce") and not dca_now:
                usd_in = 0
                cover = None
                notes.append("osc bounce, dollar still down")
            else:
                bps = LOT_BPS
                usd_in = int(state.get("usd") or 0) * bps // 10_000
                usd_in = min(usd_in, int(state.get("usd") or 0))
                cover = covers[0] if covers else None
                if cover is not None:
                    sold_px = int(cover.get("price") or 0)
                    if sold_px and price > sold_px:
                        cover = None
                        usd_in = 0
                    else:
                        usd_in = min(usd_in, int(cover.get("usd") or usd_in))
            if usd_in >= USD_SCALE // 20:
                if execute_contracts:
                    sol_got, venue = _cpmm_buy(usd_in, price)
                else:
                    sol_got, venue = _apply_fee(usd_in) * SOL_SCALE // price, "paper"
                if sol_got > 0:
                    prev_sol = int(state.get("sol") or 0)
                    state["usd"] = int(state["usd"]) - usd_in
                    extra = 0
                    if cover is not None:
                        if dca_now:
                            sold_sol = sum(int(row.get("sol") or 0) for row in list(covers))
                            extra = sol_got - sold_sol
                            for row in list(covers):
                                row["covered"] = True
                                row["closed"] = True
                                if row in opens:
                                    opens.remove(row)
                        else:
                            extra = sol_got - int(cover.get("sol") or 0)
                            cover["covered"] = True
                            cover["closed"] = True
                            if cover in opens:
                                opens.remove(cover)
                    _touch_cost_px(state, prev_sol, usd_in, sol_got)
                    state["sol"] = prev_sol + sol_got
                    if cover is None and str(vote.get("flow") or "") != "trend_up":
                        opens.append(
                            {
                                "id": "lot-spot-" + str(ts),
                                "ts": ts,
                                "side": "buy",
                                "horizon": "spot",
                                "sol": sol_got,
                                "usd": usd_in,
                                "price": price,
                                "venue": venue,
                                "closed": False,
                            }
                        )
                    lots.append(
                        {
                            "id": "buy-spot-" + str(ts),
                            "ts": ts,
                            "side": "buy",
                            "horizon": "spot",
                            "sol": sol_got,
                            "usd": usd_in,
                            "price": price,
                            "extra_sol": extra,
                            "dca": bool(vote.get("dca")),
                            "venue": venue,
                            "closed": cover is not None,
                        }
                    )
                    state["trades_today"] = int(state["trades_today"]) + 1
                    state["last_ts"] = ts
                    gaps = state.get("gap_ts")
                    if not isinstance(gaps, dict):
                        gaps = {}
                        state["gap_ts"] = gaps
                    gaps["spot"] = ts
                    action = "buy"
                    notes.append(
                        ("dca " if vote.get("dca") else "buy ")
                        + str(vote.get("flow"))
                        + " rsi "
                        + str(vote.get("rsi"))
                    )
                    if dca_now:
                        state["cash_cycle"] = False
                        state["bag_armed"] = True
                        state["ob_days"] = 0
                        state["peak_tokens"] = int(state.get("sol") or 0)
                        state["float_trimmed"] = True
                        state["grid_px"] = price
                        state["grid_last_buy_px"] = price
        nested = _apply_nested_swings(
            state,
            lots,
            opens,
            covers,
            price,
            ts,
            tf_osc,
            tf_super,
            tf_flow,
            execute_contracts,
            notes,
        )
        if nested:
            action = nested
    mtf = {
        tf: str((tf_super or {}).get(tf) or (
            "buy"
            if in_buy_band((tf_osc.get(tf) or {}).get("rsi"))
            else (
                "sell"
                if in_sell_band((tf_osc.get(tf) or {}).get("rsi"))
                else "none"
            )
        ))
        for tf in TIMEFRAMES
    }
    note = " · ".join(notes) if notes else (
        "wait confluence " + str(vote.get("flow")) + " · " + str(BAND_BUY) + "/" + str(int(BAND_SELL))
    )
    state["last"] = {
        "action": action,
        "note": note,
        "regime": vote.get("flow") or regime,
        "macro": vote.get("flow"),
        "vote": vote.get("side"),
        "super": action if action in ("buy", "sell") else "none",
        "close": close,
        "mtf": mtf,
        "flow": dict(tf_flow or {}),
        "osc": {tf: (tf_osc.get(tf) or {}).get("rsi") for tf in TIMEFRAMES},
        "horizons": {
            name: sum(
                1
                for row in opens
                if str(row.get("horizon") or "spot") == name
            )
            for name in HORIZONS
        },
        "votes": {
            "spot": vote.get("side"),
            "month": swing_vote(
                "month", tf_osc, tf_super, tf_flow, osc_prev=state.get("osc_prev")
            ).get("side"),
            "week": swing_vote(
                "week", tf_osc, tf_super, tf_flow, osc_prev=state.get("osc_prev")
            ).get("side"),
            "day": swing_vote(
                "day", tf_osc, tf_super, tf_flow, osc_prev=state.get("osc_prev")
            ).get("side"),
        },
    }
    state["osc_prev"] = {
        tf: {
            "rsi": (tf_osc.get(tf) or {}).get("rsi"),
            "stoch": (tf_osc.get(tf) or {}).get("stoch"),
            "stoch_stack": list((tf_osc.get(tf) or {}).get("stoch_stack") or []),
        }
        for tf in tf_osc
    }
    return state["last"]


def tick(
    close: float,
    sig: dict[str, Any],
    regime: str,
    atr_fraction: float,
    now: int | None = None,
    execute_contracts: bool = False,
    tf_osc: dict[str, dict[str, Any]] | None = None,
    tf_super: dict[str, str] | None = None,
    tf_flow: dict[str, str] | None = None,
) -> dict[str, Any]:
    state = load_state()
    lots = read_lots(2000)
    before = len(lots)
    ts = int(now if now is not None else time.time())
    if tf_osc:
        apply_horizons(
            state,
            lots,
            close,
            tf_osc,
            regime,
            ts,
            execute_contracts=execute_contracts,
            tf_super=tf_super,
            tf_flow=tf_flow,
        )
    else:
        apply_tick(
            state,
            lots,
            close,
            sig,
            regime,
            atr_fraction,
            ts,
            execute_contracts=execute_contracts,
        )
    for row in lots[before:]:
        append_lot(row)
    save_state(state)
    return snapshot()


def resample_ohlc(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    factor: int = 48,
) -> tuple[list[float], list[float], list[float]]:
    rh: list[float] = []
    rl: list[float] = []
    rc: list[float] = []
    step = max(2, int(factor))
    i = 0
    n = min(len(highs), len(lows), len(closes))
    while i + step <= n:
        rh.append(max(highs[i : i + step]))
        rl.append(min(lows[i : i + step]))
        rc.append(closes[i + step - 1])
        i += step
    return rh, rl, rc


def _iso_week(ts: int) -> str:
    return time.strftime("%G-W%V", time.gmtime(int(ts)))


def _lot_px(row: dict[str, Any]) -> float:
    try:
        px = float(row.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0
    if px > 10000:
        px = px / float(USD_SCALE)
    return px


def _lot_profit_sol(row: dict[str, Any]) -> int:
    extra = int(row.get("extra_sol") or 0)
    sol = int(row.get("sol") or 0)
    if extra and extra != sol:
        return extra
    stored = int(row.get("profit_sol") or 0)
    if stored:
        return stored
    profit_usd = int(row.get("profit_usd") or 0)
    px = int(row.get("price") or 0)
    if profit_usd and px:
        return profit_usd * SOL_SCALE // px
    return 0


def _equity_atoms(state: dict[str, Any], last_close: float) -> int:
    """Actual SOL tokens. USD powder stays quote, even at a crash."""
    del last_close
    return int(state.get("banked_sol") or 0) + int(state.get("sol") or 0)


def _mark_usd(state: dict[str, Any], price: float) -> float:
    """Portfolio equity includes both token holdings and every cash bucket."""
    cash = _powder_usd(state) + int(state.get("banked_usd") or 0)
    return _equity_atoms(state, price) / SOL_SCALE * price + cash / USD_SCALE


def _new_bucket() -> dict[str, Any]:
    return {
        "fills": 0,
        "buys": 0,
        "sells": 0,
        "wins": 0,
        "start_eq": 0,
        "last_buy": 0.0,
        "last_sell": 0.0,
    }


def _fresh_tape() -> dict[str, Any]:
    return {
        "months": [],
        "weeks": [],
        "equity": [],
        "prev_month": "",
        "prev_week": "",
        "month": _new_bucket(),
        "week": _new_bucket(),
    }


def _flush_bucket(
    kind: str,
    key: str,
    bucket: dict[str, Any],
    state: dict[str, Any],
    last_close: float,
) -> dict[str, Any]:
    eq = _equity_atoms(state, last_close)
    pnl = eq - int(bucket.get("start_eq") or 0)
    banked = int(state.get("banked_sol") or 0)
    held = int(state.get("sol") or 0)
    row = {
        kind: key,
        "vault": format_units(banked, 9),
        "float": format_units(held, 9),
        "tokens": format_units(eq, 9),
        "usd": format_units(_powder_usd(state), 6),
        "fills": int(bucket.get("fills") or 0),
        "buys": int(bucket.get("buys") or 0),
        "sells": int(bucket.get("sells") or 0),
        "wins": int(bucket.get("wins") or 0),
        "pnl_sol": format_units(pnl, 9),
    }
    if bucket.get("last_buy"):
        row["last_buy"] = round(float(bucket["last_buy"]), 4)
    if bucket.get("last_sell"):
        row["last_sell"] = round(float(bucket["last_sell"]), 4)
    return row


def _advance_tape(
    tape: dict[str, Any],
    ts: int,
    state: dict[str, Any],
    last_close: float,
) -> None:
    mark_usd = _mark_usd(state, last_close)
    tape["mark_state"] = state
    tape["mark_close"] = last_close
    rows = tape.setdefault("accounting", [])
    row = {"ts": int(ts), "usd": mark_usd}
    if rows and rows[-1]["ts"] == int(ts):
        rows[-1] = row
    else:
        rows.append(row)
    if not state.get("seeded"):
        return
    month_now = time.strftime("%Y-%m", time.gmtime(int(ts)))
    week_now = _iso_week(ts)
    eq = _equity_atoms(state, last_close)
    sol = round(eq / SOL_SCALE, 4) if eq else 0.0
    if tape["prev_month"] and month_now != tape["prev_month"]:
        tape["months"].append(
            _flush_bucket("month", tape["prev_month"], tape["month"], state, last_close)
        )
        tape["month"] = _new_bucket()
        tape["month"]["start_eq"] = eq
    if not tape["prev_month"]:
        tape["month"]["start_eq"] = eq
    tape["prev_month"] = month_now
    if tape["prev_week"] and week_now != tape["prev_week"]:
        tape["weeks"].append(
            _flush_bucket("week", tape["prev_week"], tape["week"], state, last_close)
        )
        tape["equity"].append({"ts": int(ts), "sol": sol})
        tape["week"] = _new_bucket()
        tape["week"]["start_eq"] = eq
    if not tape["prev_week"]:
        tape["week"]["start_eq"] = eq
        tape["equity"].append({"ts": int(ts), "sol": sol})
    tape["prev_week"] = week_now


def _note_fill(tape: dict[str, Any], row: dict[str, Any]) -> None:
    if tape.get("accounting") and tape.get("mark_state") is not None:
        price = float(tape["mark_close"])
        tape["accounting"][-1]["usd"] = _mark_usd(tape["mark_state"], price)
    if str(row.get("id") or "") == "lot-seed" or str(row.get("venue") or "") == "seed":
        return
    side = str(row.get("side") or "")
    if side not in ("buy", "sell"):
        return
    px = _lot_px(row)
    for key in ("month", "week"):
        bucket = tape[key]
        bucket["fills"] = int(bucket.get("fills") or 0) + 1
        if side == "buy":
            bucket["buys"] = int(bucket.get("buys") or 0) + 1
            if px:
                bucket["last_buy"] = px
            if int(row.get("extra_sol") or 0) > 0:
                bucket["wins"] = int(bucket.get("wins") or 0) + 1
        else:
            bucket["sells"] = int(bucket.get("sells") or 0) + 1
            if px:
                bucket["last_sell"] = px
            if _lot_profit_sol(row) > 0:
                bucket["wins"] = int(bucket.get("wins") or 0) + 1


def _close_tape(
    tape: dict[str, Any],
    state: dict[str, Any],
    last_close: float,
    ts: int,
) -> None:
    _advance_tape(tape, ts, state, last_close)
    eq = _equity_atoms(state, last_close)
    sol = round(eq / SOL_SCALE, 4) if eq else 0.0
    if tape["prev_week"]:
        tape["weeks"].append(
            _flush_bucket("week", tape["prev_week"], tape["week"], state, last_close)
        )
        tape["equity"].append({"ts": int(ts), "sol": sol})
    if tape["prev_month"]:
        tape["months"].append(
            _flush_bucket("month", tape["prev_month"], tape["month"], state, last_close)
        )


def _idle_gaps(months: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    run: list[str] = []
    for row in months:
        key = str(row.get("month") or "")
        if int(row.get("fills") or 0) == 0 and key:
            run.append(key)
            continue
        if len(run) >= 2:
            gaps.append({"from": run[0], "to": run[-1], "months": len(run)})
        run = []
    if len(run) >= 2:
        gaps.append({"from": run[0], "to": run[-1], "months": len(run)})
    return gaps


def _years_from_weeks(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    years: list[dict[str, Any]] = []
    prev = ""
    fills = 0
    buys = 0
    sells = 0
    pnl = 0
    tokens = ""
    vault = ""
    for row in weeks:
        year = str(row.get("week") or "")[:4]
        if prev and year != prev:
            years.append(
                {
                    "year": prev,
                    "fills": fills,
                    "buys": buys,
                    "sells": sells,
                    "pnl_sol": format_units(pnl, 9),
                    "tokens": tokens,
                    "vault": vault,
                }
            )
            fills = 0
            buys = 0
            sells = 0
            pnl = 0
        prev = year
        fills += int(row.get("fills") or 0)
        buys += int(row.get("buys") or 0)
        sells += int(row.get("sells") or 0)
        try:
            pnl += int(round(float(str(row.get("pnl_sol") or "0")) * SOL_SCALE))
        except (TypeError, ValueError):
            pass
        tokens = str(row.get("tokens") or tokens)
        vault = str(row.get("vault") or vault)
    if prev:
        years.append(
            {
                "year": prev,
                "fills": fills,
                "buys": buys,
                "sells": sells,
                "pnl_sol": format_units(pnl, 9),
                "tokens": tokens,
                "vault": vault,
            }
        )
    return years


def _frame_span(data: dict[str, Any]) -> int:
    times = [int(x) for x in (data.get("times") or [])]
    if len(times) < 8:
        return 0
    return int(times[-1]) - int(times[0])


def _walk_primary(frames: dict[str, dict[str, Any]]) -> str:
    """1h clock on long history. 1m as clock melts the desktop."""
    for name, data in frames.items():
        if data.get("evaluation_primary"):
            return name
    spans: dict[str, int] = {}
    for name, data in frames.items():
        span = _frame_span(data)
        if span > 0 and list((data or {}).get("closes") or []):
            spans[name] = span
    if not spans:
        raise RuntimeError("CRYPTO_MTF")
    longest = max(spans.values())
    need = longest * 80 // 100
    order = TIMEFRAMES
    if longest >= 30 * 86400:
        order = ("1h", "4h", "8h", "1d")
    for name in order:
        if spans.get(name, 0) >= need:
            return name
    return max(spans, key=lambda item: spans[item])


def _lot_mark(row: dict[str, Any]) -> dict[str, Any] | None:
    side = str(row.get("side") or "")
    if side not in ("buy", "sell"):
        return None
    if str(row.get("id") or "") == "lot-seed" or str(row.get("venue") or "") == "seed":
        return None
    try:
        ts = int(row.get("ts") or 0)
        px = float(row.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0 or px <= 0:
        return None
    if px > 10000:
        px = px / float(USD_SCALE)
    return {"ts": ts, "side": side, "px": round(px, 4)}


def _weekly_chart_marks(lots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most one buy and one sell per ISO week. Prefer week/month/spot over day grid."""
    rank = {"month": 3, "week": 2, "spot": 2, "day": 1}
    best: dict[tuple[str, str], tuple[tuple[int, int], dict[str, Any]]] = {}
    for row in lots:
        mark = _lot_mark(row)
        if not mark:
            continue
        week = _iso_week(int(mark["ts"]))
        side = str(mark["side"])
        hz = str(row.get("horizon") or "day")
        score = (int(rank.get(hz, 0)), int(row.get("sol") or 0))
        key = (week, side)
        prev = best.get(key)
        if prev is None or score > prev[0]:
            best[key] = (score, mark)
    return [item[1] for item in best.values()]


def _backtest_chart(
    frames: dict[str, dict[str, Any]] | None,
    lots: list[dict[str, Any]],
    closes: list[float] | None = None,
    times: list[int] | None = None,
    interval: str = "",
    cap: int = 400,
    equity: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    src_c = [float(item) for item in (closes or [])]
    src_t = [int(item) for item in (times or [])]
    tf = str(interval or "")
    if frames:
        for name in ("1d", "8h", "4h", "1h", "15m", "5m", "1m"):
            data = frames.get(name) or {}
            rows = list(data.get("closes") or [])
            stamps = [int(item) for item in (data.get("times") or [])]
            if len(rows) < 8:
                continue
            src_c = [float(item) for item in rows]
            src_t = stamps
            tf = name
            break
    n = len(src_c)
    if n < 2:
        return {}
    if src_t and len(src_t) != n:
        src_t = []
    if n > cap:
        step = max(1, (n + cap - 1) // cap)
        idxs = list(range(0, n, step))
        if idxs[-1] != n - 1:
            idxs.append(n - 1)
        src_c = [round(src_c[i], 4) for i in idxs]
        src_t = [src_t[i] for i in idxs] if src_t else []
    else:
        src_c = [round(item, 4) for item in src_c]
    eq_out: list[dict[str, Any]] = []
    for row in equity or []:
        try:
            ts = int(row.get("ts") or 0)
            val = float(row.get("sol") or 0)
        except (TypeError, ValueError):
            continue
        if ts > 0 and val > 0:
            eq_out.append({"time": ts, "value": round(val, 4)})
    return {
        "closes": src_c,
        "times": src_t,
        "interval": tf or "bt",
        "marks": _weekly_chart_marks(lots),
        "equity": eq_out,
    }


def run_backtest(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float] | None = None,
    signals: list[str] | None = None,
    now0: int = 1_700_000_000,
    bar_sec: int = 300,
    resample_factor: int = 48,
    params: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    n = min(len(highs), len(lows), len(closes))
    vols = volumes if volumes is not None else [1.0] * n
    state = default_state()
    state["armed"] = True
    lots: list[dict[str, Any]] = []
    prev_banked = 0
    never_fell = True
    buys = 0
    sells = 0
    sig_buy = 0
    sig_sell = 0
    max_open = 0
    max_day = 0
    day_hist: list[int] = []
    prev_day = ""
    prev_count = 0
    tape = _fresh_tape()
    start = 80 if n > 80 else 1
    factor = max(2, int(resample_factor))
    rh, rl, rc = resample_ohlc(highs[:n], lows[:n], closes[:n], factor)
    reg4 = regime_series(rh, rl, rc)
    atrs = atr_series(highs[:n], lows[:n], closes[:n])
    pre_signals: list[str] | None = None
    if signals is None and params is None:
        pre_signals = None
    for i in range(start, n):
        sl = slice(max(0, i - 79), i + 1)
        if signals is not None:
            side = str(signals[i] if i < len(signals) else "none")
            sig = {"super": side}
        elif params is not None:
            sig = {"super": "none"}
        else:
            try:
                sig = evaluate_004(highs[sl], lows[sl], closes[sl], vols[sl])
            except (ValueError, TypeError):
                sig = {"super": "none"}
        side = trader_super(sig)
        sig = dict(sig)
        sig["super"] = side
        if side == "buy":
            sig_buy += 1
        elif side == "sell":
            sig_sell += 1
        idx4 = min(len(reg4) - 1, i // factor) if reg4 else -1
        regime = reg4[idx4] if idx4 >= 0 else "range"
        atr = atrs[i] if i < len(atrs) else 0.01
        last_row = apply_tick(
            state,
            lots,
            closes[i],
            sig,
            regime,
            atr,
            now0 + i * bar_sec,
        )
        day_now = str(state.get("day") or "")
        count_now = int(state.get("trades_today") or 0)
        if prev_day and day_now != prev_day:
            day_hist.append(prev_count)
        prev_day = day_now
        prev_count = count_now
        banked = int(state.get("banked_sol") or 0)
        if banked < prev_banked:
            never_fell = False
        prev_banked = banked
        ts_now = now0 + i * bar_sec
        _advance_tape(tape, ts_now, state, closes[i])
        if last_row.get("action") == "buy":
            buys += 1
            if lots:
                _note_fill(tape, lots[-1])
        elif last_row.get("action") == "sell":
            sells += 1
            if lots:
                _note_fill(tape, lots[-1])
        max_open = max(max_open, len(_open_lots_from(lots)))
        max_day = max(max_day, int(state.get("trades_today") or 0))
    if prev_day:
        day_hist.append(prev_count)
    last_ts = now0 + (n - 1) * bar_sec if n else now0
    last_px = closes[n - 1] if n else 0.0
    _close_tape(tape, state, last_px, last_ts)
    in_band = sum(1 for item in day_hist if MIN_TRADES_DAY <= item <= MAX_TRADES_DAY)
    avg_day = (sum(day_hist) / len(day_hist)) if day_hist else 0.0
    banked = int(state.get("banked_sol") or 0)
    float_sol = int(state.get("sol") or 0)
    report = {
        "bars": n,
        "from": start,
        "signals_buy": sig_buy,
        "signals_sell": sig_sell,
        "fills": buys + sells,
        "buys": buys,
        "sells": sells,
        "max_open": max_open,
        "max_day_fills": max_day,
        "days": len(day_hist),
        "avg_fills_day": round(avg_day, 2),
        "days_in_band": in_band,
        "banked_sol": format_units(banked, 9),
        "float_sol": format_units(float_sol, 9),
        "tokens": format_units(banked + float_sol, 9),
        "usd": format_units(int(state.get("usd") or 0), 6),
        "banked_never_fell": never_fell,
        "banked_grew": banked > 0,
        "lots": lots[-24:],
        "seeded": bool(state.get("seeded")),
        "note": "Cycle bag at 1d euphoria. Day/week/month only cover 3%+ dips after fees.",
        "params": params or {},
        "start_sol": format_units(int(state.get("start_sol") or START_SOL), 9),
        "months": tape["months"],
        "weeks": tape["weeks"],
        "years": _years_from_weeks(tape["weeks"]),
        "gaps": _idle_gaps(tape["months"]),
        "day_book": _day_book(lots),
    }
    report.update(
        _trade_stats(
            lots,
            banked,
            _powder_usd(state),
            day_hist,
            sol_held=float_sol,
            last_close=last_px,
            start_sol=int(state.get("start_sol") or START_SOL),
        )
    )
    report["chart"] = _backtest_chart(
        None,
        lots,
        closes=list(closes[:n]),
        times=[int(now0) + i * int(bar_sec) for i in range(n)],
        interval="bt",
        equity=tape["equity"],
    )
    if persist:
        save_backtest(report)
    return report


def _trade_stats(
    lots: list[dict[str, Any]],
    banked: int,
    usd: int,
    day_hist: list[int],
    sol_held: int = 0,
    last_close: float = 0.0,
    start_sol: int | None = None,
) -> dict[str, Any]:
    sells = [row for row in lots if row.get("side") == "sell"]
    scored_flags: list[bool] = []
    for row in lots:
        if row.get("id") == "lot-seed" or row.get("venue") == "seed":
            continue
        if row.get("side") == "buy" and "extra_sol" in row and not row.get("rejoin"):
            scored_flags.append(int(row.get("extra_sol") or 0) > 0)
        elif row.get("side") == "sell" and row.get("closes"):
            scored_flags.append(int(row.get("profit_usd") or 0) > 0)
        elif row.get("side") == "sell" and row.get("parked"):
            scored_flags.append(False)
        elif (
            row.get("side") == "sell"
            and str(row.get("id") or "").startswith("grid-")
        ):
            scored_flags.append(int(row.get("profit_usd") or 0) > 0)
        elif row.get("side") == "sell" and "profit_usd" in row:
            scored_flags.append(int(row.get("profit_usd") or 0) > 0)
    wins = [1 for ok in scored_flags if ok]
    losses = [1 for ok in scored_flags if not ok]
    scored = scored_flags
    live = [
        row
        for row in lots
        if str(row.get("id") or "") != "lot-seed"
        and str(row.get("venue") or "") != "seed"
        and str(row.get("side") or "") in ("buy", "sell")
    ]
    best = max(live, key=_lot_profit_sol, default=None)
    worst = min(live, key=_lot_profit_sol, default=None)
    win_rate = (100.0 * len(wins) / len(scored)) if scored else 0.0
    days_cap = sum(1 for item in day_hist if item >= MAX_TRADES_DAY)
    vault_sol = banked / SOL_SCALE if banked else 0.0
    seeded = int(start_sol) if start_sol else START_SOL
    start = seeded / SOL_SCALE
    equity = int(banked) + int(sol_held)
    token_end = equity / SOL_SCALE if equity else (banked / SOL_SCALE)
    pnl_sol = equity - seeded
    avg_pnl = (pnl_sol / len(sells)) if sells else 0
    verdict = "WEAK"
    if token_end >= start * 1.5 and win_rate >= 55.0 and len(sells) >= 10:
        verdict = "GOOD"
    elif token_end > start and win_rate >= 70.0 and len(sells) >= 15:
        verdict = "GOOD"
    elif token_end > start and win_rate >= 50 and len(sells) >= 80:
        verdict = "GOOD" if token_end >= start * 2 else "MIXED"
    elif token_end > start and len(sells) >= 20:
        verdict = "MIXED"
    def _lot_view(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "side": row.get("side"),
            "profit": format_units(_lot_profit_sol(row), 9),
            "sol": format_units(row.get("sol"), 9),
            "ts": row.get("ts"),
        }
    return {
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "pnl_sol": format_units(pnl_sol, 9),
        "avg_pnl": format_units(int(avg_pnl), 9),
        "best_trade": _lot_view(best),
        "worst_trade": _lot_view(worst),
        "days_hit_cap": days_cap,
        "verdict": verdict,
        "vault_sol": round(vault_sol, 4),
        "start_sol": format_units(seeded, 9),
        "end_sol": format_units(equity, 9),
        "equity_sol": format_units(equity, 9),
        "growth": round(token_end / start, 2) if start else 0.0,
    }


def _index_at_or_before(times: list[int], ts: int) -> int | None:
    lo = 0
    hi = len(times) - 1
    found: int | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if times[mid] <= ts:
            found = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return found


def _index_closed_at_or_before(
    times: list[int], ts: int, bar_sec: int
) -> int | None:
    """Last candle that has already closed. `times` are open times."""
    return _index_at_or_before(times, int(ts) - int(bar_sec))


def run_mtf_backtest(
    frames: dict[str, dict[str, Any]],
    params: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Walk the fastest available TF; vote with 4x-stoch stack on each TF."""
    order = ("5m", "15m", "1h", "1m")
    primary = next((name for name in order if name in frames and frames[name].get("closes")), "")
    if not primary:
        raise RuntimeError("CRYPTO_MTF")
    cfg = load_signal_params()
    if params:
        cfg.update(params)
    src = frames[primary]
    highs = list(src["highs"])
    lows = list(src["lows"])
    closes = list(src["closes"])
    volumes = list(src.get("volumes") or [])
    times = [int(x) for x in (src.get("times") or [])]
    n = min(len(highs), len(lows), len(closes), len(times) or len(closes))
    tf_sigs: dict[str, list[str]] = {}
    tf_times: dict[str, list[int]] = {}
    for name, data in frames.items():
        tf_sigs[name] = signal_series(
            list(data["highs"]),
            list(data["lows"]),
            list(data["closes"]),
            list(data.get("volumes") or []),
            params=cfg,
        )
        tf_times[name] = [int(x) for x in (data.get("times") or [])]
    combined: list[str] = ["none"] * n
    for i in range(n):
        ts = times[i] if i < len(times) else 0
        votes: dict[str, str] = {}
        now = int(ts) + int(BAR_SEC.get(primary) or 0)
        for name, series in tf_sigs.items():
            bar_sec = int(BAR_SEC.get(name) or BAR_SEC.get(primary) or 0)
            idx = (
                _index_closed_at_or_before(tf_times[name], now, bar_sec)
                if tf_times.get(name)
                else None
            )
            if idx is None and name == primary:
                idx = i
            if idx is None or idx >= len(series):
                votes[name] = "none"
            else:
                votes[name] = series[idx]
        combined[i] = mtf_super(votes, int(cfg.get("tf_need") or 2))
    bar_sec = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}.get(primary, 3600)
    factor = {"1m": 60, "5m": 12, "15m": 4, "1h": 4}.get(primary, 4)
    now0 = times[0] if times else 1_598_000_000
    report = run_backtest(
        highs,
        lows,
        closes,
        volumes,
        signals=combined,
        now0=int(now0),
        bar_sec=bar_sec,
        resample_factor=factor,
        params=cfg,
        persist=persist,
    )
    report["range"] = "+".join(tf for tf in TIMEFRAMES if tf in frames)
    report["primary"] = primary
    report["max_day"] = MAX_TRADES_DAY
    if persist:
        save_backtest(report)
    return report


def _rsi_last_series(closes: list[float]) -> list[float | None]:
    return rsi(closes, 14)


def _snapshot_tfs(
    frames: dict[str, dict[str, Any]],
    tf_rsi: dict[str, list[float | None]],
    tf_stoch: dict[str, list[float | None]],
    tf_stoch_stack: dict[str, list[list[float | None]]],
    tf_times: dict[str, list[int]],
    tf_sig: dict[str, list[str]],
    tf_reg: dict[str, list[str]],
    now: int,
    primary: str,
    primary_i: int,
    fallback_close: float,
    tf_qual: dict[str, dict[str, list[float | None]]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str]]:
    tf_osc: dict[str, dict[str, Any]] = {}
    tf_super: dict[str, str] = {}
    tf_flow: dict[str, str] = {}
    for name in frames:
        bar_sec = int(BAR_SEC.get(name) or BAR_SEC.get(primary) or 0)
        idx = (
            _index_closed_at_or_before(tf_times[name], now, bar_sec)
            if tf_times.get(name)
            else None
        )
        if idx is None and name == primary:
            idx = primary_i
        if idx is None:
            continue
        rsi_v = None
        series_r = tf_rsi.get(name) or []
        if idx < len(series_r):
            rsi_v = series_r[idx]
        stoch_v = None
        series_k = tf_stoch.get(name) or []
        if idx < len(series_k):
            stoch_v = series_k[idx]
        stack_now: list[float | None] = []
        for series in tf_stoch_stack.get(name) or []:
            stack_now.append(series[idx] if idx < len(series) else None)
        src = frames.get(name) or {}
        src_c = src.get("closes") or []
        src_l = src.get("lows") or []
        tf_osc[name] = {
            "rsi": rsi_v,
            "stoch": stoch_v,
            "stoch_stack": stack_now,
            "buy_n": 0,
            "sell_n": 0,
            "close": float(src_c[idx]) if idx < len(src_c) else fallback_close,
            "low": float(src_l[idx]) if idx < len(src_l) else fallback_close,
        }
        extra = (tf_qual or {}).get(name) or {}
        for key, series in extra.items():
            tf_osc[name][key] = series[idx] if idx < len(series) else None
        sigs = tf_sig.get(name) or []
        tf_super[name] = sigs[idx] if idx < len(sigs) else "none"
        regs = tf_reg.get(name) or []
        tf_flow[name] = regs[idx] if idx < len(regs) else "range"
        row = tf_osc[name]
        row["buy_n"] = _other_agree(row, False) + (
            1 if _in_zone_val(row.get("stoch"), False) else 0
        )
        row["sell_n"] = _other_agree(row, True) + (
            1 if _in_zone_val(row.get("stoch"), True) else 0
        )
    return tf_osc, tf_super, tf_flow


def _replay_float_15m(
    state: dict[str, Any],
    lots: list[dict[str, Any]],
    frames: dict[str, dict[str, Any]],
    tf_rsi: dict[str, list[float | None]],
    tf_stoch: dict[str, list[float | None]],
    tf_stoch_stack: dict[str, list[list[float | None]]],
    tf_times: dict[str, list[int]],
    t_from: int,
    t_to: int,
    primary: str,
    base_osc: dict[str, dict[str, Any]],
    base_flow: dict[str, str],
    tf_qual: dict[str, dict[str, list[float | None]]] | None = None,
    tf_sig: dict[str, list[str]] | None = None,
    tf_reg: dict[str, list[str]] | None = None,
) -> None:
    """Only the 15m bars in this 1h window, and only on a 4-stoch pile-up."""
    if primary in ("1m", "5m", "15m"):
        return
    times15 = tf_times.get("15m") or []
    closes15 = list((frames.get("15m") or {}).get("closes") or [])
    rsi15 = tf_rsi.get("15m") or []
    stoch15 = tf_stoch.get("15m") or []
    if len(times15) < 8 or len(closes15) < 8:
        return
    bar = int(BAR_SEC["15m"])
    start = _index_at_or_before(times15, int(t_from) - bar)
    if start is None:
        start = 0
    notes: list[str] = []
    stack_series = tf_stoch_stack.get("15m") or []
    for j in range(start, len(times15)):
        t_close = int(times15[j]) + bar
        if t_close <= t_from:
            continue
        if t_close >= t_to:
            break
        prev_r = rsi15[j - 1] if j > 0 and j - 1 < len(rsi15) else None
        now_r = rsi15[j] if j < len(rsi15) else None
        prev_s = stoch15[j - 1] if j > 0 and j - 1 < len(stoch15) else None
        now_s = stoch15[j] if j < len(stoch15) else None
        stack_now: list[float | None] = []
        stack_prev: list[float | None] = []
        for series in stack_series:
            stack_now.append(series[j] if j < len(series) else None)
            stack_prev.append(series[j - 1] if j > 0 and j - 1 < len(series) else None)
        probe = {
            "rsi": now_r,
            "stoch": now_s,
            "stoch_stack": stack_now,
        }
        if len(_stoch_vals(probe)) >= 4:
            if not _stoch_cluster(probe, False)[1] and not _stoch_cluster(probe, True)[1]:
                continue
        elif not (
            _zone_turn(prev_r, now_r, False)
            or _zone_turn(prev_s, now_s, False)
            or _zone_turn(prev_r, now_r, True)
            or _zone_turn(prev_s, now_s, True)
        ):
            continue
        px = float(closes15[j]) if j < len(closes15) else 0.0
        if px <= 0:
            continue
        extra = (tf_qual or {}).get("15m") or {}
        for key, series in extra.items():
            probe[key] = series[j] if j < len(series) else None
        prev_map = state.get("osc_prev")
        if not isinstance(prev_map, dict):
            prev_map = {}
            state["osc_prev"] = prev_map
        prev_map["15m"] = {
            "rsi": prev_r,
            "stoch": prev_s,
            "stoch_stack": stack_prev,
        }
        # Sample every TF at this 15m close, before the enclosing hour closes.
        tf_osc, _unused, causal_flow = _snapshot_tfs(
            frames, tf_rsi, tf_stoch, tf_stoch_stack, tf_times,
            tf_sig or {}, tf_reg or {}, t_close, "15m", j, px, tf_qual,
        )
        tf_osc["15m"] = {
            "rsi": now_r,
            "stoch": now_s,
            "stoch_stack": stack_now,
            "buy_n": _other_agree(probe, False),
            "sell_n": _other_agree(probe, True),
            "close": px,
            "low": px,
        }
        for key in QUAL_KEYS:
            if key != "rsi" and key in probe:
                tf_osc["15m"][key] = probe[key]
        _apply_float_grid(
            state,
            lots,
            _price_atoms(px),
            t_close,
            False,
            notes,
            tf_flow=causal_flow,
            tf_osc=tf_osc,
        )
        prev_map["15m"] = {
            "rsi": now_r,
            "stoch": now_s,
            "stoch_stack": stack_now,
        }


def run_flow_backtest(
    frames: dict[str, dict[str, Any]],
    persist: bool = True,
) -> dict[str, Any]:
    """Walk the fastest TF that still covers the long chart."""
    primary = _walk_primary(frames)
    src = frames[primary]
    highs = list(src["highs"])
    lows = list(src["lows"])
    closes = list(src["closes"])
    volumes = list(src.get("volumes") or [])
    times = [int(x) for x in (src.get("times") or [])]
    n = min(len(highs), len(lows), len(closes), len(times) or len(closes))
    tf_rsi: dict[str, list[float | None]] = {}
    tf_stoch: dict[str, list[float | None]] = {}
    tf_stoch_stack: dict[str, list[list[float | None]]] = {}
    tf_sig: dict[str, list[str]] = {}
    tf_reg: dict[str, list[str]] = {}
    tf_times: dict[str, list[int]] = {}
    tf_qual: dict[str, dict[str, list[float | None]]] = {}
    for name, data in frames.items():
        h = list(data["highs"])
        lo = list(data["lows"])
        c = list(data["closes"])
        v = list(data.get("volumes") or [])
        tf_rsi[name] = _rsi_last_series(c)
        kk, _dd = stoch_kd(h, lo, c, 14, 3, 3)
        tf_stoch[name] = kk
        tf_stoch_stack[name] = []
        for k_len, k_sm, d_sm, _vol in STOCH_STACK:
            sk, _sd = stoch_kd(h, lo, c, k_len, k_sm, d_sm)
            tf_stoch_stack[name].append(sk)
        tf_times[name] = [int(x) for x in (data.get("times") or [])]
        if name not in ("1m", "5m"):
            tf_qual[name] = {
                "mfi": mfi(h, lo, c, v or [1.0] * len(c), 14),
                "cci": cci_osc(h, lo, c, 20),
                "bb": bb_percent(c, 14, 2.0),
                "williams": williams_osc(h, lo, c, 14),
            }
        if name in ("1m", "5m"):
            # Fast TFs print the slower candle. RSI/stoch only — ADX on 1m is noise.
            sigs: list[str] = []
            for val in tf_rsi[name]:
                if in_buy_band(val):
                    sigs.append("buy")
                elif in_sell_band(val):
                    sigs.append("sell")
                else:
                    sigs.append("none")
            tf_sig[name] = sigs
            tf_reg[name] = ["range"] * len(c)
        else:
            tf_sig[name] = signal_series(h, lo, c, v)
            tf_reg[name] = regime_series(h, lo, c)
    resume = crypto_backtest.restored("gg")
    state = default_state()
    state["armed"] = True
    state["seed_style"] = "long"
    lots: list[dict[str, Any]] = []
    opens: list[dict[str, Any]] = []
    prev_banked = 0
    never_fell = True
    buys = 0
    sells = 0
    max_open = 0
    max_day = 0
    day_hist: list[int] = []
    prev_day = ""
    prev_count = 0
    tape = _fresh_tape()
    by_horizon = {name: 0 for name in HORIZONS}
    if resume:
        state = resume["state"]
        lots = list(resume.get("recent_lots") or [])
        opens = _open_lots_from(lots)
    event_start = len(lots)
    start = n - 1 if resume else crypto_backtest.start_index(src)
    now0 = times[0] if times else 1_598_000_000
    pri_super = tf_sig.get(primary) or []
    pri_rsi = tf_rsi.get(primary) or []
    rotates = 0
    for i in range(start, n):
        ts = times[i] if i < len(times) else now0
        now = int(ts) + int(BAR_SEC.get(primary) or 0)
        day_now = time.strftime("%Y-%m-%d", time.gmtime(now))
        if prev_day and day_now != prev_day:
            day_hist.append(prev_count)
            prev_count = 0
            state["day"] = day_now
            state["trades_today"] = 0
        prev_day = day_now
        _advance_tape(tape, int(ts), state, closes[i])
        ps = pri_super[i] if i < len(pri_super) else "none"
        pr = pri_rsi[i] if i < len(pri_rsi) else None
        slow_bar = (int(ts) % 300) == 0
        if (
            primary in ("1m", "5m")
            and not opens
            and int(state.get("sol") or 0) <= 0
            and _powder_usd(state) <= 0
            and int(state.get("banked_usd") or 0) <= 0
            and ps == "none"
            and not in_buy_band(pr)
            and not in_sell_band(pr)
            and not slow_bar
        ):
            continue
        tf_osc, tf_super, tf_flow = _snapshot_tfs(
            frames,
            tf_rsi,
            tf_stoch,
            tf_stoch_stack,
            tf_times,
            tf_sig,
            tf_reg,
            now,
            primary,
            i,
            closes[i],
            tf_qual,
        )
        macro = str(tf_flow.get("1h") or tf_flow.get(primary) or "range")
        before = len(lots)
        prev_now = int(times[i - 1]) + int(BAR_SEC.get(primary) or 0) if i > 0 else int(ts)
        # Shared evaluation/forward accounts decide on their declared clock.
        # Do not backdate new fills to 15m prices after that hour has finished.
        if not src.get("evaluation_primary"):
            _replay_float_15m(
                state,
                lots,
                frames,
                tf_rsi,
                tf_stoch,
                tf_stoch_stack,
                tf_times,
                prev_now,
                now,
                primary,
                tf_osc,
                tf_flow,
                tf_qual,
                tf_sig,
                tf_reg,
            )
        apply_horizons(
            state,
            lots,
            closes[i],
            tf_osc,
            macro,
            now,
            tf_super=tf_super,
            tf_flow=tf_flow,
            open_rows=opens,
        )
        _advance_tape(tape, int(ts), state, closes[i])
        prev_count = int(state.get("trades_today") or 0)
        banked = int(state.get("banked_sol") or 0)
        if banked < prev_banked:
            never_fell = False
        prev_banked = banked
        for row in lots[before:]:
            if row.get("id") == "lot-seed" or row.get("venue") == "seed":
                continue
            hz = str(row.get("horizon") or "")
            if hz in by_horizon:
                by_horizon[hz] += 1
            _note_fill(tape, row)
            if row.get("side") == "buy":
                buys += 1
            elif row.get("side") == "sell":
                sells += 1
        max_open = max(max_open, len(opens))
        max_day = max(max_day, int(state.get("trades_today") or 0))
    if prev_day:
        day_hist.append(prev_count)
    last_px = closes[n - 1] if n else 0.0
    last_ts = times[n - 1] if times else now0
    _close_tape(tape, state, last_px, int(last_ts))
    in_band = sum(1 for item in day_hist if MIN_TRADES_DAY <= item <= MAX_TRADES_DAY)
    avg_day = (sum(day_hist) / len(day_hist)) if day_hist else 0.0
    banked = int(state.get("banked_sol") or 0)
    float_sol = int(state.get("sol") or 0)
    report = {
        "bars": n,
        "from": start,
        "fills": buys + sells,
        "buys": buys,
        "sells": sells,
        "max_open": max_open,
        "max_day_fills": max_day,
        "days": len(day_hist),
        "avg_fills_day": round(avg_day, 2),
        "days_in_band": in_band,
        "banked_sol": format_units(banked, 9),
        "float_sol": format_units(float_sol, 9),
        "tokens": format_units(banked + float_sol, 9),
        "usd": format_units(_powder_usd(state), 6),
        "banked_never_fell": never_fell,
        "banked_grew": banked > 0,
        "lots": lots[-24:],
        "seeded": bool(state.get("seeded")),
        "note": "Cycle bag at 1d euphoria. Day/week/month only cover 3%+ dips after fees.",
        "start_sol": format_units(int(state.get("start_sol") or START_SOL), 9),
        "months": tape["months"],
        "weeks": tape["weeks"],
        "years": _years_from_weeks(tape["weeks"]),
        "gaps": _idle_gaps(tape["months"]),
        "day_book": _day_book(lots),
        "range": "+".join(tf for tf in TIMEFRAMES if tf in frames),
        "primary": primary,
        "max_day": MAX_TRADES_DAY,
        "horizon_fills": by_horizon,
        "rotates": rotates,
        "weights": {name: list(HORIZONS[name]["tfs"]) for name in HORIZONS},
    }
    stats = _trade_stats(
        lots,
        banked,
        _powder_usd(state),
        day_hist,
        sol_held=float_sol,
        last_close=last_px,
        start_sol=int(state.get("start_sol") or START_SOL),
    )
    report.update(stats)
    report["accounting"] = tape.get("accounting", [])
    report["inventory_tokens"] = (banked + float_sol) / SOL_SCALE
    report["quote_balance"] = _powder_usd(state) / USD_SCALE
    if crypto_backtest.STREAM.get():
        keep = [row for row in lots if not row.get("closed")]
        keep_ids = {row.get("id") for row in keep}
        keep += [row for row in lots[-48:] if row.get("id") not in keep_ids]
        crypto_backtest.checkpoint(report, "gg", {"state": state, "recent_lots": keep}, lots[event_start:], banked + float_sol, _powder_usd(state))
    if stats.get("equity_sol"):
        report["tokens"] = stats["equity_sol"]
    report["chart"] = _backtest_chart(frames, lots, equity=tape["equity"])
    if persist:
        save_backtest(report)
    return report


def _token_float(report: dict[str, Any]) -> float:
    try:
        return float(str(report.get("tokens") or "0"))
    except (TypeError, ValueError):
        return 0.0


def sweep_signal_params(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    now0: int,
    bar_sec: int,
    resample_factor: int,
) -> dict[str, Any]:
    grid: list[dict[str, Any]] = []
    for rsi_buy in (32.0, 38.0, 45.0):
        for rsi_sell in (58.0, 68.0):
            for stoch_buy in (22.0, 32.0):
                for bb_buy in (True, False):
                    grid.append(
                        {
                            "rsi_buy": rsi_buy,
                            "rsi_sell": rsi_sell,
                            "stoch_buy": stoch_buy,
                            "stoch_sell": 70.0,
                            "macd_buy": True,
                            "bb_buy": bb_buy,
                        }
                    )
    best: dict[str, Any] | None = None
    best_score = -1e18
    ranked: list[dict[str, Any]] = []
    for cfg in grid:
        sigs = signal_series(highs, lows, closes, params=cfg)
        report = run_backtest(
            highs,
            lows,
            closes,
            signals=sigs,
            now0=now0,
            bar_sec=bar_sec,
            resample_factor=resample_factor,
            params=cfg,
            persist=False,
        )
        score = -1e18
        if report.get("banked_never_fell") and report.get("banked_grew"):
            try:
                usd_left = float(str(report.get("usd") or "0"))
            except (TypeError, ValueError):
                usd_left = 0.0
            score = (
                float(report.get("fills") or 0) * 3.0
                + _token_float(report) * 200.0
                + float(report.get("days_in_band") or 0) * 12.0
                + usd_left * 40.0
            )
            if usd_left < 1:
                score *= 0.35
        ranked.append(
            {
                "params": cfg,
                "fills": report.get("fills"),
                "tokens": report.get("tokens"),
                "avg_fills_day": report.get("avg_fills_day"),
                "days_in_band": report.get("days_in_band"),
                "score": score,
            }
        )
        if score > best_score:
            best_score = score
            best = {"report": report, "params": cfg, "score": score}
    if best is None:
        raise RuntimeError("CRYPTO_SWEEP")
    save_signal_params(best["params"])
    out = dict(best["report"])
    out["winner"] = best["params"]
    out["score"] = best["score"]
    out["tried"] = len(grid)
    ranked.sort(key=lambda row: float(row.get("score") or -1e18), reverse=True)
    out["ranked"] = ranked[:8]
    save_backtest(out)
    return out
