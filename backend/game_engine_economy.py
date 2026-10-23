"""Bounded vendor economy for the GAME ENGINE.

Gold is a small authoritative wallet ledger.  Vendor stock is deliberately
not duplicated here: it is read from the NPC's materialized item instances.
That makes a successful purchase or sale one canonical item transition plus
one atomic currency transition, with no presentation-only stock.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Iterable


SCHEMA = "gg.game-engine.economy.v1"
VERSION = 1
MAX_VENDORS = 8
MAX_PRICING_ROWS = 48
MAX_OFFERS_PER_VENDOR = 16
MAX_CURRENCY = 2_000_000_000
MAX_TRANSACTION_HISTORY = 16
STARTER_PLAYER_GOLD = 250
STARTER_VENDOR_GOLD = 500
INTERACTION_RADIUS_M = 3.75
MAX_DEMAND = 10
MIN_BUY_MULTIPLIER = 0.75
MAX_BUY_MULTIPLIER = 1.75
MIN_SELL_MULTIPLIER = 0.50
MAX_SELL_MULTIPLIER = 1.50
MIN_RESTOCK_INTERVAL_S = 4.0
MAX_RESTOCK_INTERVAL_S = 300.0
MAX_STOCK_LIMIT = 32
MAX_RESTOCK_ITEMS = 4
MAX_PREFERENCES = 24
MAX_DECISION_DEFINITIONS = 4
MAX_DECISION_REASON = 48
NEED_GATE_KEYS = ("hunger", "thirst", "fatigue")
DEFAULT_NEED_THRESHOLDS = {
    "hunger": 0.92,
    "thirst": 0.92,
    "fatigue": 0.95,
}
TRADEABLE_KINDS = frozenset(
    {
        "MATERIAL",
        "CONSUMABLE",
        "TRASH",
        "WEAPON",
        "ARMOR",
        "ACCESSORY",
        "INSERTABLE",
        "RUNE",
        "GEM",
        "CRAFTING_MATERIAL",
        "ITEM",
    }
)
BLOCKED_TAGS = frozenset({"QUEST", "SOULBOUND", "NO_TRADE", "BOUND"})


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, default: str = "", limit: int = 96) -> str:
    return str(value or default).strip()[:limit]


def _bounded_currency(value: Any, default: int = 0) -> int:
    return max(0, min(MAX_CURRENCY, _safe_int(value, default)))


def bounded_currency(value: Any, default: int = 0) -> int:
    """Expose the same currency cap to the runtime transaction layer."""
    return _bounded_currency(value, default)


def _bounded_demand(value: Any) -> int:
    return max(-MAX_DEMAND, min(MAX_DEMAND, _safe_int(value)))


def _bounded_ratio(value: Any, default: float = 0.0) -> float:
    return round(max(0.0, min(1.0, _safe_float(value, default))), 4)


def _normalize_needs(raw: Any) -> dict[str, float]:
    """Keep the vendor-facing copy of identity needs small and numeric."""
    if not isinstance(raw, dict):
        return {}
    return {
        key: _bounded_ratio(raw.get(key))
        for key in ("hunger", "thirst", "fatigue", "curiosity")
        if key in raw
    }


def _normalize_need_thresholds(raw: Any) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    return {
        key: _bounded_ratio(source.get(key), default)
        for key, default in DEFAULT_NEED_THRESHOLDS.items()
    }


def _normalize_preference_row(raw: Any) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "priority": _bounded_ratio(row.get("priority")),
        "target_stock": max(
            0,
            min(MAX_STOCK_LIMIT, _safe_int(row.get("target_stock"))),
        ),
        # Negative values are player discounts; positive values are premiums.
        "buy_bias": round(max(-0.25, min(0.50, _safe_float(row.get("buy_bias")))), 3),
        "sell_premium": round(
            max(0.0, min(0.50, _safe_float(row.get("sell_premium")))),
            3,
        ),
    }


def _normalize_preferences(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    preferences: dict[str, dict[str, Any]] = {}
    for definition_id, value in list(raw.items())[:MAX_PREFERENCES]:
        wanted = _text(definition_id, limit=96)
        if not wanted or not isinstance(value, dict):
            continue
        preferences[wanted] = _normalize_preference_row(value)
    return preferences


def _normalize_string_list(raw: Any, limit: int = MAX_DECISION_DEFINITIONS) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    result: list[str] = []
    for value in raw[:limit]:
        wanted = _text(value, limit=96)
        if wanted and wanted not in result:
            result.append(wanted)
    return result


def _normalize_decision(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    action = _text(raw.get("action"), limit=16).upper()
    if action not in {"HOLD", "RESTOCK"}:
        return {}
    preferred = raw.get("preferred_definition_ids")
    if preferred is None:
        preferred = raw.get("candidates")
    result = {
        "action": action,
        "reason": _text(raw.get("reason"), "UNSPECIFIED", MAX_DECISION_REASON).upper(),
        "focus_definition_id": _text(raw.get("focus_definition_id"), limit=96),
        "preferred_definition_ids": _normalize_string_list(preferred),
        "rolled_definition_ids": _normalize_string_list(
            raw.get("rolled_definition_ids")
        ),
        "selected_definition_id": _text(
            raw.get("selected_definition_id"),
            limit=96,
        ),
        "selected_seed": max(0, min(0xFFFFFFFF, _safe_int(raw.get("selected_seed")))),
        "needs": _normalize_needs(raw.get("needs")),
        "time_s": round(max(0.0, _safe_float(raw.get("time_s"))), 3),
    }
    return result


def _normalize_market_row(raw: Any) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    action = _text(row.get("last_action"), limit=16).upper()
    if action not in {"BUY", "SELL", "RESTOCK"}:
        action = ""
    return {
        "demand": _bounded_demand(row.get("demand")),
        "transactions": max(0, _safe_int(row.get("transactions"))),
        "last_action": action,
        "last_time_s": round(max(0.0, _safe_float(row.get("last_time_s"))), 3),
    }


def _normalize_market(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(definition_id)[:96]: _normalize_market_row(value)
        for definition_id, value in list(raw.items())[:MAX_PRICING_ROWS]
        if str(definition_id).strip()
    }


def _normalize_restock(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not any(
        raw.get(key)
        for key in ("ok", "status", "definition_id", "table_id", "time_s")
    ):
        return {}
    return {
        "ok": bool(raw.get("ok")),
        "status": _text(raw.get("status"), "UNKNOWN", 32).upper(),
        "definition_id": _text(raw.get("definition_id"), limit=96),
        "quantity": max(0, _safe_int(raw.get("quantity"))),
        "table_id": _text(raw.get("table_id"), limit=96),
        "seed": max(0, _safe_int(raw.get("seed"))),
        "time_s": round(max(0.0, _safe_float(raw.get("time_s"))), 3),
    }


def starter_vendors() -> dict[str, dict[str, Any]]:
    """Return the first authored vendor table.

    Mira is already a living NPC.  Her two visible stock rows are therefore
    backed by the NPC identity inventory and materialized POCKET instances;
    the rest of the pricing table controls what she is willing to buy when a
    player brings it to her.
    """
    return {
        "vendor.mira": {
            "id": "vendor.mira",
            "name": "Mira's Shore Stall",
            "npc_id": "npc-wanderer-01",
            "starting_gold": STARTER_VENDOR_GOLD,
            "gold_floor": 0,
            "pricing": {
                "item.old_boot": {"buy": 3, "sell": 1},
                "item.sea_salt": {"buy": 6, "sell": 2},
                "item.sun_herb": {"buy": 12, "sell": 4},
                "item.field_ration": {"buy": 18, "sell": 7},
                "item.moon_shard": {"buy": 65, "sell": 22},
                "item.iron_saber": {"buy": 90, "sell": 36},
                "item.tideguard_jacket": {"buy": 180, "sell": 72},
                "item.sunken_crown": {"buy": 400, "sell": 160},
            },
            "restock_table_id": "loot.goblin_pocket",
            "restock_interval_s": 12.0,
            "stock_limit": 6,
            "restock_max_items": 1,
            # These are authored preferences, not a second stock database.
            # They bias real quotes and choose among real loot-table rolls.
            "need_thresholds": {
                "hunger": 0.92,
                "thirst": 0.92,
                "fatigue": 0.95,
            },
            "preferences": {
                "item.sea_salt": {
                    "priority": 0.90,
                    "target_stock": 2,
                    "sell_premium": 0.18,
                    "buy_bias": -0.04,
                },
                "item.sun_herb": {
                    "priority": 0.72,
                    "target_stock": 2,
                    "sell_premium": 0.08,
                    "buy_bias": -0.02,
                },
                "item.field_ration": {
                    "priority": 0.66,
                    "target_stock": 2,
                    "sell_premium": 0.10,
                    "buy_bias": -0.03,
                },
                "item.moon_shard": {
                    "priority": 0.55,
                    "target_stock": 1,
                    "sell_premium": 0.05,
                    "buy_bias": 0.03,
                },
                "item.old_boot": {
                    "priority": 0.20,
                    "target_stock": 1,
                    "sell_premium": 0.00,
                    "buy_bias": 0.00,
                },
            },
            "policy": "PHYSICAL_STOCK_GOLD_ATOMIC",
        },
    }


def _normalize_pricing(raw: Any) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    pricing: dict[str, dict[str, int]] = {}
    for definition_id, value in list(raw.items())[:MAX_PRICING_ROWS]:
        if not isinstance(value, dict):
            continue
        wanted = _text(definition_id, limit=96)
        if not wanted:
            continue
        pricing[wanted] = {
            "buy": _bounded_currency(value.get("buy")),
            "sell": _bounded_currency(value.get("sell")),
        }
    return pricing


def normalize_vendor(raw: Any, fallback_id: str = "") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    vendor_id = _text(raw.get("id"), fallback_id, 64)
    npc_id = _text(raw.get("npc_id"), limit=64)
    if not vendor_id or not npc_id:
        return None
    return {
        "id": vendor_id,
        "name": _text(raw.get("name"), vendor_id, 96),
        "npc_id": npc_id,
        "starting_gold": _bounded_currency(
            raw.get("starting_gold"), STARTER_VENDOR_GOLD
        ),
        "gold_floor": _bounded_currency(raw.get("gold_floor"), 0),
        "pricing": _normalize_pricing(raw.get("pricing")),
        "restock_table_id": _text(
            raw.get("restock_table_id"),
            "loot.goblin_pocket",
            96,
        ),
        "restock_interval_s": round(
            max(
                MIN_RESTOCK_INTERVAL_S,
                min(
                    MAX_RESTOCK_INTERVAL_S,
                    _safe_float(raw.get("restock_interval_s"), 12.0),
                ),
            ),
            3,
        ),
        "stock_limit": max(
            0,
            min(MAX_STOCK_LIMIT, _safe_int(raw.get("stock_limit"), 6)),
        ),
        "restock_max_items": max(
            1,
            min(MAX_RESTOCK_ITEMS, _safe_int(raw.get("restock_max_items"), 1)),
        ),
        "policy": _text(
            raw.get("policy"),
            "PHYSICAL_STOCK_GOLD_ATOMIC",
            64,
        ).upper(),
        "need_thresholds": _normalize_need_thresholds(raw.get("need_thresholds")),
        "preferences": _normalize_preferences(raw.get("preferences")),
    }


def catalog_from_content(content: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Merge bounded authored vendors over the deterministic starter table."""
    defaults = starter_vendors()
    source = content.get("vendors") if isinstance(content, dict) else None
    if isinstance(source, dict):
        for key, value in list(source.items())[:MAX_VENDORS]:
            if not isinstance(value, dict):
                continue
            candidate = copy.deepcopy(value)
            candidate.setdefault("id", str(key))
            normalized = normalize_vendor(candidate, str(key))
            if normalized is not None:
                defaults[normalized["id"]] = normalized
    elif isinstance(source, list):
        for value in source[:MAX_VENDORS]:
            normalized = normalize_vendor(value)
            if normalized is not None:
                defaults[normalized["id"]] = normalized
    return dict(list(defaults.items())[:MAX_VENDORS])


def catalog_summary(vendors: Any) -> dict[str, Any]:
    rows = vendors if isinstance(vendors, dict) else {}
    pricing_rows = 0
    for row in rows.values():
        if isinstance(row, dict) and isinstance(row.get("pricing"), dict):
            pricing_rows += len(row["pricing"])
    preference_rows = 0
    for row in rows.values():
        if isinstance(row, dict) and isinstance(row.get("preferences"), dict):
            preference_rows += len(row["preferences"])
    return {
        "vendors": min(MAX_VENDORS, len(rows)),
        "pricing_rows": min(MAX_VENDORS * MAX_PRICING_ROWS, pricing_rows),
        "preference_rows": min(MAX_VENDORS * MAX_PREFERENCES, preference_rows),
        "currency": "GOLD",
        "policy": "PHYSICAL_NPC_STOCK_GOLD_ATOMIC",
    }


def _copper_fields(row: dict[str, Any]) -> dict[str, int]:
    copper = max(0, min(9999, _safe_int(row.get('copper'))))
    return {'copper': copper} if copper else {}


def _normalize_wallet(raw: Any) -> dict[str, int]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "gold": _bounded_currency(row.get("gold"), STARTER_PLAYER_GOLD),
        **_copper_fields(row),
        "earned": _bounded_currency(row.get("earned")),
        "spent": _bounded_currency(row.get("spent")),
        "revision": max(0, _safe_int(row.get("revision"))),
    }


def _normalize_vendor_account(
    raw: Any,
    vendor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    vendor_row = vendor if isinstance(vendor, dict) else {}
    return {
        "gold": _bounded_currency(
            row.get("gold"),
            _bounded_currency(vendor_row.get("starting_gold"), STARTER_VENDOR_GOLD),
        ),
        **_copper_fields(row),
        "transactions": max(0, _safe_int(row.get("transactions"))),
        "revision": max(0, _safe_int(row.get("revision"))),
        "market": _normalize_market(row.get("market")),
        "restock_count": max(0, _safe_int(row.get("restock_count"))),
        "restock_attempts": max(0, _safe_int(row.get("restock_attempts"))),
        "decision_count": max(0, _safe_int(row.get("decision_count"))),
        "hold_count": max(0, _safe_int(row.get("hold_count"))),
        "last_restock_s": round(
            max(0.0, _safe_float(row.get("last_restock_s"))),
            3,
        ),
        "last_restock": _normalize_restock(row.get("last_restock")),
        "last_decision": _normalize_decision(row.get("last_decision")),
    }


def new_state(vendors: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    catalog = vendors if isinstance(vendors, dict) else starter_vendors()
    accounts: dict[str, dict[str, Any]] = {}
    for vendor_id, vendor in list(catalog.items())[:MAX_VENDORS]:
        if not isinstance(vendor, dict):
            continue
        accounts[str(vendor_id)] = {
            "gold": _bounded_currency(vendor.get("starting_gold"), STARTER_VENDOR_GOLD),
            "transactions": 0,
            "revision": 0,
            "market": {},
            "restock_count": 0,
            "restock_attempts": 0,
            "decision_count": 0,
            "hold_count": 0,
            "last_restock_s": 0.0,
            "last_restock": {},
            "last_decision": {},
        }
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "wallet": _normalize_wallet({"gold": STARTER_PLAYER_GOLD}),
        "vendors": accounts,
        "last": {},
        "history": [],
        "buybacks": {},
    }


def _normalize_transaction(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not any(
        raw.get(key)
        for key in (
            "action",
            "vendor_id",
            "npc_id",
            "instance_id",
            "definition_id",
            "error",
        )
    ):
        return {}
    action = _text(raw.get("action"), limit=16).upper()
    if action not in {"BUY", "SELL"}:
        action = "TRANSACTION"
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "ok": bool(raw.get("ok", True)),
        "action": action,
        "vendor_id": _text(raw.get("vendor_id"), limit=64),
        "vendor_name": _text(raw.get("vendor_name"), limit=96),
        "npc_id": _text(raw.get("npc_id"), limit=64),
        "instance_id": _text(raw.get("instance_id"), limit=64),
        "definition_id": _text(raw.get("definition_id"), limit=96),
        "quantity": max(0, _safe_int(raw.get("quantity"))),
        "unit_price": _bounded_currency(raw.get("unit_price")),
        "total_price": _bounded_currency(raw.get("total_price")),
        "currency": _text(raw.get("currency"), "GOLD", 16).upper(),
        "distance_m": round(max(0.0, min(1000.0, _safe_float(raw.get("distance_m")))), 3),
        "atomic": bool(raw.get("atomic", True)),
    }
    for key in ("player_gold_after", "vendor_gold_after", "vendor_revision"):
        if key in raw:
            result[key] = _bounded_currency(raw.get(key)) if key.endswith("after") else max(0, _safe_int(raw.get(key)))
    if "base_unit_price" in raw:
        result["base_unit_price"] = _bounded_currency(raw.get("base_unit_price"))
    if "demand" in raw:
        result["demand"] = _bounded_demand(raw.get("demand"))
    if "stock" in raw:
        result["stock"] = max(0, _safe_int(raw.get("stock")))
    if "buy_multiplier" in raw:
        result["buy_multiplier"] = round(
            max(0.0, min(4.0, _safe_float(raw.get("buy_multiplier")))),
            3,
        )
    if "sell_multiplier" in raw:
        result["sell_multiplier"] = round(
            max(0.0, min(4.0, _safe_float(raw.get("sell_multiplier")))),
            3,
        )
    if "preference_priority" in raw:
        result["preference_priority"] = _bounded_ratio(
            raw.get("preference_priority")
        )
    if "target_stock" in raw:
        result["target_stock"] = max(0, _safe_int(raw.get("target_stock")))
    if "preference_gap" in raw:
        result["preference_gap"] = max(0, _safe_int(raw.get("preference_gap")))
    if raw.get("error"):
        result["error"] = _text(raw.get("error"), "VENDOR_TRANSACTION_FAILED", 96)
    if isinstance(raw.get("item"), dict):
        result["item"] = copy.deepcopy(raw["item"])
    if isinstance(raw.get("details"), dict):
        result["details"] = copy.deepcopy(raw["details"])
    if isinstance(raw.get("npc_gear_upgrade"), dict):
        result["npc_gear_upgrade"] = copy.deepcopy(raw["npc_gear_upgrade"])
    if isinstance(raw.get("npc_power"), dict):
        result["npc_power"] = copy.deepcopy(raw["npc_power"])
    return result


def normalize_transaction(raw: Any) -> dict[str, Any]:
    return _normalize_transaction(raw)


def restore_state(raw: Any, vendors: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    base = new_state(vendors)
    if not isinstance(raw, dict):
        return base
    base["wallet"] = _normalize_wallet(raw.get("wallet"))
    buybacks=raw.get("buybacks")
    if isinstance(buybacks,dict):
        for vendor_id,rows in list(buybacks.items())[:MAX_VENDORS]:
            if vendor_id not in base['vendors'] or not isinstance(rows,list):continue
            kept=[];seen=set()
            for row in rows[-12:]:
                if not isinstance(row,dict):continue
                instance=_text(row.get('instance_id'),limit=64);price=_bounded_currency(row.get('price'))
                if not instance or instance in seen or price<=0:continue
                seen.add(instance);kept.append({'instance_id':instance,'price':price})
            base['buybacks'][vendor_id]=kept
    source_accounts = raw.get("vendors")
    if isinstance(source_accounts, dict):
        for vendor_id, account in list(source_accounts.items())[:MAX_VENDORS]:
            if str(vendor_id) not in base["vendors"] or not isinstance(account, dict):
                continue
            vendor = (vendors or {}).get(str(vendor_id), {})
            base["vendors"][str(vendor_id)] = _normalize_vendor_account(
                account,
                vendor if isinstance(vendor, dict) else None,
            )
    last = _normalize_transaction(raw.get("last"))
    base["last"] = last
    history = raw.get("history")
    if isinstance(history, list):
        base["history"] = [
            _normalize_transaction(row)
            for row in history[-MAX_TRANSACTION_HISTORY:]
            if isinstance(row, dict)
        ]
    return base


def vendor_for(
    vendors: dict[str, dict[str, Any]],
    identifier: Any,
) -> tuple[str, dict[str, Any]] | None:
    wanted = _text(identifier, limit=96)
    if not wanted:
        return None
    for vendor_id, vendor in vendors.items():
        if not isinstance(vendor, dict):
            continue
        if wanted in {str(vendor_id), str(vendor.get("id", "")), str(vendor.get("npc_id", ""))}:
            return str(vendor_id), vendor
    return None


def pricing_row(vendor: dict[str, Any], definition_id: Any) -> dict[str, int] | None:
    pricing = vendor.get("pricing", {}) if isinstance(vendor, dict) else {}
    row = pricing.get(str(definition_id)) if isinstance(pricing, dict) else None
    if not isinstance(row, dict):
        return None
    return {
        "buy": _bounded_currency(row.get("buy")),
        "sell": _bounded_currency(row.get("sell")),
    }


def preference_for(vendor: dict[str, Any], definition_id: Any) -> dict[str, Any]:
    """Return one bounded authored preference, with a neutral default."""
    preferences = vendor.get("preferences", {}) if isinstance(vendor, dict) else {}
    raw = preferences.get(str(definition_id)) if isinstance(preferences, dict) else None
    return _normalize_preference_row(raw)


def market_row(account: dict[str, Any] | None, definition_id: Any) -> dict[str, Any]:
    market = account.get("market", {}) if isinstance(account, dict) else {}
    raw = market.get(str(definition_id)) if isinstance(market, dict) else None
    return _normalize_market_row(raw)


def _price_from_multiplier(base: Any, multiplier: float) -> int:
    base_price = _bounded_currency(base)
    if base_price <= 0:
        return 0
    # Explicit half-up rounding keeps the price deterministic across runtimes.
    return max(
        1,
        min(MAX_CURRENCY, int(float(base_price) * multiplier + 0.5)),
    )


def dynamic_prices(
    vendor: dict[str, Any],
    account: dict[str, Any] | None,
    definition_id: Any,
    stock_count: Any = 0,
) -> dict[str, Any] | None:
    """Price one definition from bounded demand and real physical stock.

    The catalog remains the authored base price.  Only the account's bounded
    market memory and the number of matching POCKET instances affect the
    current quote, so a renderer cannot invent a price or stock shortage.
    """
    base = pricing_row(vendor, definition_id)
    if base is None:
        return None
    stock = max(0, min(MAX_STOCK_LIMIT, _safe_int(stock_count)))
    demand = market_row(account, definition_id)["demand"]
    preference = preference_for(vendor, definition_id)
    preference_priority = float(preference["priority"])
    preference_gap = max(
        0,
        min(
            MAX_STOCK_LIMIT,
            int(preference["target_stock"]) - stock,
        ),
    )
    scarcity = max(0, min(4, 2 - stock)) * 0.08
    demand_factor = demand * 0.04
    buy_multiplier = max(
        MIN_BUY_MULTIPLIER,
        min(
            MAX_BUY_MULTIPLIER,
            1.0
            + demand_factor
            + scarcity
            + float(preference["buy_bias"]) * preference_priority,
        ),
    )
    sell_multiplier = max(
        MIN_SELL_MULTIPLIER,
        min(
            MAX_SELL_MULTIPLIER,
            1.0
            + demand_factor
            + float(preference["sell_premium"]) * preference_priority
            + min(4, preference_gap) * 0.02,
        ),
    )
    return {
        "buy": _price_from_multiplier(base["buy"], buy_multiplier),
        "sell": _price_from_multiplier(base["sell"], sell_multiplier),
        "base_buy": base["buy"],
        "base_sell": base["sell"],
        "demand": demand,
        "stock": stock,
        "buy_multiplier": round(buy_multiplier, 3),
        "sell_multiplier": round(sell_multiplier, 3),
        "preference_priority": preference["priority"],
        "target_stock": preference["target_stock"],
        "preference_gap": preference_gap,
        "buy_bias": preference["buy_bias"],
        "sell_premium": preference["sell_premium"],
    }


def record_market_transaction(
    account: dict[str, Any],
    definition_id: Any,
    action: Any,
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    """Record one bounded demand signal without touching item ownership."""
    if not isinstance(account, dict):
        return {}
    wanted = _text(definition_id, limit=96)
    normalized_action = _text(action, limit=16).upper()
    deltas = {"BUY": 1, "SELL": -1, "RESTOCK": -1}
    if not wanted or normalized_action not in deltas:
        return {}
    market = account.setdefault("market", {})
    if not isinstance(market, dict):
        market = {}
        account["market"] = market
    if wanted not in market and len(market) >= MAX_PRICING_ROWS:
        return {}
    row = market_row(account, wanted)
    row["demand"] = _bounded_demand(row["demand"] + deltas[normalized_action])
    row["transactions"] = min(MAX_CURRENCY, row["transactions"] + 1)
    row["last_action"] = normalized_action
    row["last_time_s"] = round(max(0.0, _safe_float(sim_time)), 3)
    market[wanted] = row
    return copy.deepcopy(row)


def _stable_seed(vendor_id: Any, table_id: Any, ordinal: Any) -> int:
    """Return a portable seed; Python's process-randomized hash is forbidden."""
    state = 2166136261
    for char in f"{_text(vendor_id, limit=64)}:{_text(table_id, limit=96)}:{_safe_int(ordinal)}":
        state ^= ord(char)
        state = (state * 16777619) & 0xFFFFFFFF
    return state or 1


def restock_plan(
    vendor: dict[str, Any],
    account: dict[str, Any] | None,
    current_stock: Any,
    sim_time: Any,
) -> dict[str, Any]:
    """Determine whether a vendor may roll one deterministic stock addition."""
    vendor_row = vendor if isinstance(vendor, dict) else {}
    account_row = account if isinstance(account, dict) else {}
    stock = max(0, min(MAX_STOCK_LIMIT, _safe_int(current_stock)))
    limit = max(0, min(MAX_STOCK_LIMIT, _safe_int(vendor_row.get("stock_limit"), 6)))
    interval = max(
        MIN_RESTOCK_INTERVAL_S,
        min(
            MAX_RESTOCK_INTERVAL_S,
            _safe_float(vendor_row.get("restock_interval_s"), 12.0),
        ),
    )
    table_id = _text(vendor_row.get("restock_table_id"), limit=96)
    safe_time = max(0.0, _safe_float(sim_time))
    last_time = _safe_float(account_row.get("last_restock_s"))
    details = {
        "table_id": table_id,
        "stock": stock,
        "stock_limit": limit,
        "interval_s": round(interval, 3),
        "max_items": max(
            0,
            min(
                MAX_RESTOCK_ITEMS,
                _safe_int(vendor_row.get("restock_max_items"), 1),
                limit - stock,
            ),
        ),
    }
    if stock >= limit:
        return {"due": False, "reason": "STOCK_FULL", **details}
    if not table_id:
        return {"due": False, "reason": "RESTOCK_TABLE_MISSING", **details}
    if safe_time + 0.000001 < last_time + interval:
        return {"due": False, "reason": "RESTOCK_COOLDOWN", **details}
    max_items = int(details["max_items"])
    if max_items <= 0:
        return {"due": False, "reason": "RESTOCK_LIMIT_ZERO", **details}
    attempts = max(0, _safe_int(account_row.get("restock_attempts")))
    return {
        "due": True,
        "reason": "DUE",
        "seed": _stable_seed(vendor_row.get("id"), table_id, attempts),
        **details,
    }


def vendor_restock_decision(
    vendor: dict[str, Any],
    account: dict[str, Any] | None,
    needs: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    stock_by_definition: dict[str, Any] | None,
) -> dict[str, Any]:
    """Make one bounded vendor decision from identity needs and real stock.

    This is intentionally pure: it chooses an intent, but it never creates
    stock.  The host must still roll the authored loot table and commit a
    physical item instance before the decision has an in-world effect.
    """
    del account  # Kept in the contract so future account policy stays explicit.
    vendor_row = vendor if isinstance(vendor, dict) else {}
    plan_row = plan if isinstance(plan, dict) else {}
    need_values = _normalize_needs(needs)
    base = {
        "needs": need_values,
        "preferred_definition_ids": [],
        "focus_definition_id": "",
        "time_s": 0.0,
    }
    if not plan_row.get("due"):
        return {
            "action": "HOLD",
            "reason": _text(plan_row.get("reason"), "NOT_DUE", MAX_DECISION_REASON).upper(),
            **base,
        }

    thresholds = _normalize_need_thresholds(vendor_row.get("need_thresholds"))
    urgent_key = ""
    urgent_ratio = -1.0
    for key in NEED_GATE_KEYS:
        value = _bounded_ratio(need_values.get(key))
        threshold = max(0.0001, float(thresholds[key]))
        ratio = value / threshold
        if value >= threshold and ratio > urgent_ratio:
            urgent_key = key
            urgent_ratio = ratio
    if urgent_key:
        return {
            "action": "HOLD",
            "reason": f"NEEDS_{urgent_key.upper()}",
            **base,
        }

    stock = stock_by_definition if isinstance(stock_by_definition, dict) else {}
    preferences = (
        vendor_row.get("preferences", {})
        if isinstance(vendor_row.get("preferences", {}), dict)
        else {}
    )
    preference_rows: list[tuple[float, str, int]] = []
    for definition_id in sorted(preferences):
        wanted = _text(definition_id, limit=96)
        if not wanted:
            continue
        preference = preference_for(vendor_row, wanted)
        current = max(0, _safe_int(stock.get(wanted)))
        gap = max(0, min(MAX_STOCK_LIMIT, int(preference["target_stock"]) - current))
        if gap <= 0 or float(preference["priority"]) <= 0.0:
            continue
        preference_rows.append(
            (
                float(preference["priority"]) * gap,
                wanted,
                gap,
            )
        )
    preference_rows.sort(key=lambda row: (-row[0], row[1]))
    preferred_ids = [row[1] for row in preference_rows[:MAX_DECISION_DEFINITIONS]]
    return {
        "action": "RESTOCK",
        "reason": "PREFERENCE_GAP" if preferred_ids else "TABLE_ROLL",
        "focus_definition_id": preferred_ids[0] if preferred_ids else "",
        "preferred_definition_ids": preferred_ids,
        "needs": need_values,
        "time_s": 0.0,
    }


def record_vendor_decision(
    account: dict[str, Any],
    sim_time: Any,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Persist one intent; HOLD also advances the restock clock once."""
    if not isinstance(account, dict):
        return {}
    safe_time = round(max(0.0, _safe_float(sim_time)), 3)
    raw = copy.deepcopy(decision) if isinstance(decision, dict) else {}
    raw["time_s"] = safe_time
    normalized = _normalize_decision(raw)
    if not normalized:
        return {}
    account["decision_count"] = max(0, _safe_int(account.get("decision_count"))) + 1
    if normalized["action"] == "HOLD":
        account["hold_count"] = max(0, _safe_int(account.get("hold_count"))) + 1
        # A need-driven hold is a real deferral, not a repeated 2 Hz no-op.
        account["last_restock_s"] = safe_time
    account["last_decision"] = normalized
    account["revision"] = max(0, _safe_int(account.get("revision"))) + 1
    return copy.deepcopy(normalized)


def choose_restock_candidate(
    vendor: dict[str, Any],
    candidates: Iterable[dict[str, Any]],
    stock_by_definition: dict[str, Any] | None = None,
    current_stock: Any = 0,
) -> dict[str, Any] | None:
    """Choose one valid loot-table roll according to authored preferences.

    Every candidate must already be a real roll from the configured table.
    Preference scoring only selects among those rolls; it cannot manufacture an
    item that the table did not produce.
    """
    del current_stock  # Kept for callers that track both total and per-item stock.
    stock = stock_by_definition if isinstance(stock_by_definition, dict) else {}
    rows = [row for row in candidates if isinstance(row, dict)]
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for ordinal, candidate in enumerate(rows[:MAX_DECISION_DEFINITIONS]):
        definition_id = _text(candidate.get("definition_id"), limit=96)
        if not definition_id:
            continue
        preference = preference_for(vendor, definition_id)
        current = max(0, _safe_int(stock.get(definition_id)))
        gap = max(
            0,
            min(MAX_STOCK_LIMIT, int(preference["target_stock"]) - current),
        )
        score = (
            float(preference["priority"]) * 100.0
            + min(4, gap) * 20.0
            + float(preference["sell_premium"]) * 10.0
        )
        if best is None or score > best_score:
            best = copy.deepcopy(candidate)
            best_score = score
    return best


def record_restock_attempt(
    account: dict[str, Any],
    sim_time: Any,
    *,
    success: bool,
    status: Any,
    table_id: Any = "",
    seed: Any = 0,
    definition_id: Any = "",
    quantity: Any = 0,
) -> dict[str, Any]:
    """Persist a restock decision, including failed bounded attempts."""
    if not isinstance(account, dict):
        return {}
    safe_time = round(max(0.0, _safe_float(sim_time)), 3)
    normalized_status = _text(status, "UNKNOWN", 32).upper()
    result = {
        "ok": bool(success),
        "status": normalized_status,
        "definition_id": _text(definition_id, limit=96),
        "quantity": max(0, _safe_int(quantity)),
        "table_id": _text(table_id, limit=96),
        "seed": max(0, _safe_int(seed)),
        "time_s": safe_time,
    }
    account["restock_attempts"] = max(0, _safe_int(account.get("restock_attempts"))) + 1
    if success:
        account["restock_count"] = max(0, _safe_int(account.get("restock_count"))) + 1
        if result["definition_id"]:
            record_market_transaction(
                account,
                result["definition_id"],
                "RESTOCK",
                safe_time,
            )
    account["last_restock_s"] = safe_time
    account["last_restock"] = result
    account["revision"] = max(0, _safe_int(account.get("revision"))) + 1
    return copy.deepcopy(result)


def is_tradeable_definition(definition: Any) -> bool:
    if not isinstance(definition, dict):
        return False
    if str(definition.get("kind", "ITEM")).upper() not in TRADEABLE_KINDS:
        return False
    tags = {str(tag).upper() for tag in definition.get("tags", []) if tag}
    return not tags.intersection(BLOCKED_TAGS)


def _offer(
    action: str,
    instance: dict[str, Any],
    unit_price: int,
    item_viewer: Callable[[dict[str, Any]], dict[str, Any]] | None,
    quote: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quantity = max(1, _safe_int(instance.get("quantity"), 1))
    item = item_viewer(instance) if callable(item_viewer) else {
        "instance_id": str(instance.get("instance_id", "")),
        "definition_id": str(instance.get("definition_id", "")),
        "name": str(instance.get("name", "Unknown Item")),
        "quantity": quantity,
    }
    result = {
        "action": str(action).upper(),
        "instance_id": str(instance.get("instance_id", "")),
        "definition_id": str(instance.get("definition_id", "")),
        "quantity": quantity,
        "unit_price": _bounded_currency(unit_price),
        "total_price": _bounded_currency(unit_price * quantity),
        "currency": "GOLD",
        "item": copy.deepcopy(item),
    }
    if isinstance(quote, dict):
        result.update(
            {
                "base_unit_price": _bounded_currency(
                    quote.get("base_buy" if str(action).upper() == "BUY" else "base_sell")
                ),
                "demand": _bounded_demand(quote.get("demand")),
                "stock": max(0, _safe_int(quote.get("stock"))),
                "buy_multiplier": round(
                    max(0.0, min(4.0, _safe_float(quote.get("buy_multiplier")))),
                    3,
                ),
                "sell_multiplier": round(
                    max(0.0, min(4.0, _safe_float(quote.get("sell_multiplier")))),
                    3,
                ),
                "preference_priority": _bounded_ratio(
                    quote.get("preference_priority")
                ),
                "target_stock": max(0, _safe_int(quote.get("target_stock"))),
                "preference_gap": max(0, _safe_int(quote.get("preference_gap"))),
            }
        )
    return result


def build_view(
    state: dict[str, Any],
    vendors: dict[str, dict[str, Any]],
    instances: Iterable[dict[str, Any]],
    *,
    item_viewer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    definition_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    presence: dict[str, dict[str, Any]] | None = None,
    vendor_needs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build bounded real offers from the current item-instance registry."""
    source = [row for row in instances if isinstance(row, dict)]
    wallet = _normalize_wallet(state.get("wallet")) if isinstance(state, dict) else _normalize_wallet({})
    accounts = state.get("vendors", {}) if isinstance(state, dict) else {}
    presence_rows = presence if isinstance(presence, dict) else {}
    needs_rows = vendor_needs if isinstance(vendor_needs, dict) else {}
    vendor_rows: list[dict[str, Any]] = []
    for vendor_id in sorted(vendors)[:MAX_VENDORS]:
        vendor = vendors.get(vendor_id)
        if not isinstance(vendor, dict):
            continue
        npc_id = str(vendor.get("npc_id", ""))
        account = _normalize_vendor_account(
            accounts.get(vendor_id, {}) if isinstance(accounts, dict) else {},
            vendor,
        )
        pricing = vendor.get("pricing", {})
        if not isinstance(pricing, dict):
            pricing = {}
        stock_by_definition: dict[str, int] = {}
        stock_count = 0
        for instance in source:
            definition_id = str(instance.get("definition_id", ""))
            if (
                str(instance.get("owner_id", "")) != npc_id
                or str(instance.get("location", "")) != "POCKET"
                or pricing_row(vendor, definition_id) is None
            ):
                continue
            definition = (
                definition_lookup(definition_id)
                if callable(definition_lookup)
                else None
            )
            if not is_tradeable_definition(definition):
                continue
            stock_by_definition[definition_id] = (
                stock_by_definition.get(definition_id, 0) + 1
            )
            stock_count += 1
        buy_offers: list[dict[str, Any]] = []
        sell_offers: list[dict[str, Any]] = []
        for instance in sorted(source, key=lambda row: str(row.get("instance_id", ""))):
            definition_id = str(instance.get("definition_id", ""))
            price = dynamic_prices(
                vendor,
                account,
                definition_id,
                stock_by_definition.get(definition_id, 0),
            )
            if price is None:
                continue
            definition = definition_lookup(definition_id) if callable(definition_lookup) else None
            if not is_tradeable_definition(definition):
                continue
            owner_id = str(instance.get("owner_id", ""))
            location = str(instance.get("location", ""))
            if (
                owner_id == npc_id
                and location == "POCKET"
                and price["buy"] > 0
                and len(buy_offers) < MAX_OFFERS_PER_VENDOR
            ):
                buy_offers.append(
                    _offer("BUY", instance, price["buy"], item_viewer, price)
                )
            if (
                owner_id == "player"
                and location == "INVENTORY"
                and price["sell"] > 0
                and len(sell_offers) < MAX_OFFERS_PER_VENDOR
            ):
                sell_offers.append(
                    _offer("SELL", instance, price["sell"], item_viewer, price)
                )
        presence_row = presence_rows.get(vendor_id, {})
        if not isinstance(presence_row, dict):
            presence_row = {}
        pricing_view: list[dict[str, Any]] = []
        for definition_id, row in list(pricing.items())[:MAX_PRICING_ROWS]:
            if not isinstance(row, dict):
                continue
            quote = dynamic_prices(
                vendor,
                account,
                definition_id,
                stock_by_definition.get(str(definition_id), 0),
            )
            if quote is None:
                continue
            pricing_view.append(
                {
                    "definition_id": str(definition_id),
                    "buy_price": quote["buy"],
                    "sell_price": quote["sell"],
                    "base_buy_price": quote["base_buy"],
                    "base_sell_price": quote["base_sell"],
                    "demand": quote["demand"],
                    "stock": quote["stock"],
                    "buy_multiplier": quote["buy_multiplier"],
                    "sell_multiplier": quote["sell_multiplier"],
                    "preference_priority": quote["preference_priority"],
                    "target_stock": quote["target_stock"],
                    "preference_gap": quote["preference_gap"],
                    "currency": "GOLD",
                }
            )
        preference_view = [
            {
                "definition_id": str(definition_id),
                **_normalize_preference_row(value),
            }
            for definition_id, value in sorted(
                (vendor.get("preferences", {}) or {}).items()
                if isinstance(vendor.get("preferences", {}), dict)
                else []
            )[:MAX_PREFERENCES]
            if isinstance(value, dict)
        ]
        current_needs = _normalize_needs(needs_rows.get(vendor_id))
        need_thresholds = _normalize_need_thresholds(vendor.get("need_thresholds"))
        vendor_rows.append(
            {
                "id": str(vendor_id),
                "name": str(vendor.get("name", vendor_id)),
                "npc_id": npc_id,
                "gold": account["gold"],
                "transactions": account["transactions"],
                "revision": account["revision"],
                "stock_count": stock_count,
                "presence": copy.deepcopy(presence_row),
                "needs": current_needs,
                "need_thresholds": need_thresholds,
                "preferences": preference_view,
                "decision": copy.deepcopy(account["last_decision"]),
                "decision_count": account["decision_count"],
                "hold_count": account["hold_count"],
                "pricing": pricing_view,
                "market": copy.deepcopy(account["market"]),
                "restock": {
                    "table_id": str(vendor.get("restock_table_id", "")),
                    "interval_s": round(
                        max(
                            MIN_RESTOCK_INTERVAL_S,
                            min(
                                MAX_RESTOCK_INTERVAL_S,
                                _safe_float(vendor.get("restock_interval_s"), 12.0),
                            ),
                        ),
                        3,
                    ),
                    "stock_limit": max(
                        0,
                        min(
                            MAX_STOCK_LIMIT,
                            _safe_int(vendor.get("stock_limit"), 6),
                        ),
                    ),
                    "max_items": max(
                        1,
                        min(
                            MAX_RESTOCK_ITEMS,
                            _safe_int(vendor.get("restock_max_items"), 1),
                        ),
                    ),
                    "stock_count": stock_count,
                    "successful": account["restock_count"],
                    "attempts": account["restock_attempts"],
                    "decision_count": account["decision_count"],
                    "holds": account["hold_count"],
                    "last": copy.deepcopy(account["last_restock"]),
                },
                "offers": {
                    "buy": buy_offers,
                    "sell": sell_offers,
                },
                "policy": str(vendor.get("policy", "PHYSICAL_STOCK_GOLD_ATOMIC")),
            }
        )
    last = _normalize_transaction(state.get("last")) if isinstance(state, dict) else {}
    history = state.get("history", []) if isinstance(state, dict) else []
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "currency": "GOLD",
        "catalog": catalog_summary(vendors),
        "wallet": wallet,
        "vendors": vendor_rows,
        "last": last,
        "history_count": len(history) if isinstance(history, list) else 0,
        "policy": "AUTHORITATIVE_WALLET_PHYSICAL_STOCK_ATOMIC",
        "limits": {
            "max_vendors": MAX_VENDORS,
            "max_offers_per_vendor": MAX_OFFERS_PER_VENDOR,
            "max_currency": MAX_CURRENCY,
        },
    }
