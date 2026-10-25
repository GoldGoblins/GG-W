"""Offline integer quotes for single Pump curves and PumpSwap pools.

Independent implementation of the published arithmetic in official SDKs
@pump-fun/pump-sdk 4.3.1 (bondingCurve.ts/fees.ts) and
@pump-fun/pump-swap-sdk 2.2.0 (buy.ts/sell.ts/fees.ts/transferFee.ts).
Sources: https://unpkg.com/@pump-fun/pump-sdk@4.3.1/src/bondingCurve.ts
https://unpkg.com/@pump-fun/pump-swap-sdk@2.2.0/src/sdk/buy.ts
https://github.com/pump-fun/pump-public-docs/blob/main/docs/NEGATIVE_VIRTUAL_QUOTE_RESERVES.md

These are local estimates, never transaction builders or execution promises.
Mayhem, cashback, curve v3, synthetic migration and routes are refused. AMM
v1 and v2 use the same price but different fee-retention bookkeeping. No RPC,
wallet access, binary SDK dependency or floating-point money arithmetic.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from typing import Any

U64_MAX = (1 << 64) - 1
I128_MIN, I128_MAX = -(1 << 127), (1 << 127) - 1
BPS = 10_000
SOL_MINTS = frozenset(("11111111111111111111111111111111",
    "So11111111111111111111111111111111111111112",
    "9pan9bMn5HatX4EJdBwg9VgCa7Uz5HL8N1m5D3NdXejP"))
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = U64_MAX) -> int:
    # Decimal strings are the transport representation, never floats or bools.
    if isinstance(value, str) and len(value) <= 40:
        digits = value[1:] if value.startswith("-") else value
        if digits and digits.isascii() and digits.isdecimal():
            value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("PUMP_INVALID_" + name.upper())
    return value


def _flag(market: dict, key: str, default: bool = False) -> bool:
    value = market.get(key, default)
    if type(value) is not bool:
        raise ValueError("PUMP_INVALID_" + key.upper())
    return value


def _ceil(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def transfer_fee_at(config: dict | None, epoch: int | None = None) -> dict:
    """Select the Token-2022 schedule in force; the newer epoch is inclusive."""
    if config is None:
        return {"bps": 0, "max_fee": 0}
    if not isinstance(config, dict):
        raise ValueError("PUMP_TRANSFER_FEE")
    if "older" in config or "newer" in config:
        current = _integer(epoch, "epoch")
        older, newer = config.get("older"), config.get("newer")
        if not isinstance(older, dict) or not isinstance(newer, dict):
            raise ValueError("PUMP_TRANSFER_FEE_SCHEDULE")
        old_epoch = _integer(older.get("epoch"), "epoch")
        new_epoch = _integer(newer.get("epoch"), "epoch")
        if new_epoch < old_epoch:
            raise ValueError("PUMP_TRANSFER_FEE_SCHEDULE")
        # Validate both, so an invalid future schedule is not silently cached.
        transfer_fee_at({k: older.get(k) for k in ("bps", "max_fee")})
        transfer_fee_at({k: newer.get(k) for k in ("bps", "max_fee")})
        config = newer if current >= new_epoch else older
    return {"bps": _integer(config.get("bps"), "transfer_bps", maximum=BPS),
            "max_fee": _integer(config.get("max_fee"), "transfer_max_fee")}


def transfer_fee(amount: int, config: dict | None) -> int:
    amount = _integer(amount, "amount")
    fee = transfer_fee_at(config)
    return min(_ceil(amount * fee["bps"], BPS), fee["max_fee"])


def net_of_transfer_fee(amount: int, config: dict | None) -> int:
    return amount - transfer_fee(amount, config)


def gross_for_transfer_fee(net: int, config: dict | None) -> int:
    """SPL pre-fee amount, checked for u64 overflow (100% is capped)."""
    net = _integer(net, "amount")
    fee = transfer_fee_at(config)
    bps, cap = fee["bps"], fee["max_fee"]
    if not net or not bps:
        return net
    gross = (net + cap if bps == BPS else
             min(net + cap, _ceil(net * BPS, BPS - bps)))
    return _integer(gross, "gross_amount")


def _rates(record: dict) -> dict[str, int]:
    if not isinstance(record, dict):
        raise ValueError("PUMP_FEE_CONFIG")
    result = {key: _integer(record.get(key), key, maximum=BPS - 1)
              for key in ("lp_fee_bps", "protocol_fee_bps", "creator_fee_bps")}
    if sum(result.values()) >= BPS:
        raise ValueError("PUMP_FEE_TOTAL")
    return result


def fee_rates(market: dict, base: int, effective_quote: int) -> dict:
    """Select canonical SOL/stable/exotic schedules or noncanonical flat fees."""
    config = market.get("fee_config")
    if config is None:
        result = _rates(market)
    else:
        if not isinstance(config, dict):
            raise ValueError("PUMP_FEE_CONFIG")
        if market["kind"] == "amm" and "is_pump_pool" not in market:
            raise ValueError("PUMP_CANONICAL_CLASSIFICATION_REQUIRED")
        canonical = market["kind"] == "curve" or _flag(market, "is_pump_pool")
        flat = _rates(config.get("flat_fees"))
        if not canonical:
            result = flat
        else:
            mint = market.get("quote_mint", "So11111111111111111111111111111111111111112")
            if mint not in SOL_MINTS and mint != USDC_MINT:
                exotic = _rates(config.get("exotic_flat_fees", {
                    "lp_fee_bps": 0, "protocol_fee_bps": 0, "creator_fee_bps": 0}))
                result = exotic if any(exotic.values()) else flat
            else:
                tiers = config.get("stable_fee_tiers") if mint == USDC_MINT else None
                tiers = tiers or config.get("fee_tiers")
                if not isinstance(tiers, list) or not 1 <= len(tiers) <= 128:
                    raise ValueError("PUMP_FEE_TIERS")
                # Ordinary curves use Pump's fixed one-billion-token supply for
                # charged fee market cap; AMM uses the actual base mint supply.
                supply = (10**15 if market["kind"] == "curve" else
                          _integer(market.get("mint_supply_atoms"), "mint_supply", 1))
                cap = effective_quote * supply // base
                previous = -1
                selected = None
                for tier in tiers:
                    if not isinstance(tier, dict):
                        raise ValueError("PUMP_FEE_TIERS")
                    threshold = _integer(tier.get("market_cap_lamports_threshold"),
                                         "fee_threshold", maximum=(1 << 128) - 1)
                    rates = _rates(tier.get("fees"))
                    if threshold <= previous:
                        raise ValueError("PUMP_FEE_TIERS_ORDER")
                    previous = threshold
                    if selected is None or cap >= threshold:
                        selected = rates
                result = selected
    if config is not None and market["kind"] == "curve":
        # FeeConfig's Fees record is shared with AMM schedules. Pump curves
        # consume only protocol and creator fields; they never charge LP fees.
        result = {**result, "lp_fee_bps": 0}
    if _flag(market, "creator_fee_configurable"):
        configured = _integer(market.get("configured_creator_fee_bps", 0),
                              "configured_creator_fee_bps", maximum=BPS - 1)
        # AMM override only applies with FeeConfig; curve applies with either.
        if configured and (config is not None or market["kind"] == "curve"):
            result = {**result, "creator_fee_bps": configured}
    if not _flag(market, "creator_present", True):
        result = {**result, "creator_fee_bps": 0}
    result = _rates(result)
    if market["kind"] == "curve" and result["lp_fee_bps"]:
        raise ValueError("PUMP_CURVE_LP_FEE")
    return result


def validate_market(market: dict) -> dict:
    """Validate a caller-provided, decoded snapshot, without inventing depth."""
    if not isinstance(market, dict) or market.get("kind") not in ("curve", "amm"):
        raise ValueError("PUMP_MARKET_KIND")
    market = deepcopy(market)
    for key in ("mayhem", "is_mayhem_mode", "cashback", "is_cashback_coin",
                "synthetic_migration", "multi_hop"):
        if _flag(market, key):
            raise ValueError("PUMP_UNSUPPORTED_" + key.upper())
    version = _integer(market.get("instruction_version", 2 if market["kind"] == "curve" else 1),
                       "instruction_version", 1, 3)
    if market["kind"] == "curve" and version >= 3:
        raise ValueError("PUMP_UNSUPPORTED_CURVE_V3")
    if _flag(market, "complete"):
        raise ValueError("PUMP_CURVE_COMPLETE")
    for key in ("base_reserves_atoms", "quote_reserves_atoms"):
        market[key] = _integer(market.get(key), key, 1)
    for key in ("base_decimals", "quote_decimals"):
        market[key] = _integer(market.get(key), key, maximum=18)
    virtual = _integer(market.get("virtual_quote_reserves_atoms", 0),
                       "virtual_quote_reserves_atoms", I128_MIN, I128_MAX)
    if market["kind"] == "curve" and virtual:
        raise ValueError("PUMP_CURVE_DOUBLE_VIRTUAL_RESERVES")
    market["virtual_quote_reserves_atoms"] = virtual
    effective = _integer(market["quote_reserves_atoms"] + virtual, "effective_quote", 1)
    for key in ("protocol_fees_atoms", "creator_fees_atoms"):
        market[key] = _integer(market.get(key, 0), key)
    if market["kind"] == "curve":
        market["real_base_reserves_atoms"] = _integer(
            market.get("real_base_reserves_atoms"), "real_base_reserves_atoms")
        if market["real_base_reserves_atoms"] > market["base_reserves_atoms"]:
            raise ValueError("PUMP_REAL_BASE_RESERVES")
        market["real_quote_reserves_atoms"] = _integer(
            market.get("real_quote_reserves_atoms"), "real_quote_reserves_atoms")
    elif market["protocol_fees_atoms"] + market["creator_fees_atoms"] > market["quote_reserves_atoms"]:
        raise ValueError("PUMP_FEE_BUCKET_RESERVES")
    market["trade_v2"] = _flag(market, "trade_v2")
    market["buyback_bps"] = _integer(market.get("buyback_bps", 0), "buyback_bps", maximum=BPS)
    for key in ("base_transfer_fee", "quote_transfer_fee"):
        active = transfer_fee_at(market.get(key), market.get("epoch"))
        if not isinstance(market.get(key), dict) or "older" not in market[key]:
            market[key] = active
    fee_rates(market, market["base_reserves_atoms"], effective)
    return market


def _decimal(numerator: int, denominator: int) -> str:
    with localcontext() as context:
        context.prec = 50
        return format(Decimal(numerator) / Decimal(denominator), "f")


def quote(market: dict, side: str, amount_atoms: int, slippage_bps: int = 100) -> dict:
    """Quote gross exact input or net exact output with explicit wallet bounds.

    buy/buy_exact_in: quote wallet budget. buy_exact_out: net base desired.
    sell/sell_exact_in: gross base wallet debit. sell_exact_out: net quote
    desired (minimal base input found by bounded monotonic integer search).
    All atomic result amounts are strings safe for JavaScript beyond 2**53.
    """
    if type(amount_atoms) is not int or not 0 < amount_atoms <= U64_MAX:
        raise ValueError("PUMP_INVALID_AMOUNT")
    if type(slippage_bps) is not int or not 0 <= slippage_bps < BPS:
        raise ValueError("PUMP_INVALID_SLIPPAGE")
    aliases = {"buy": "buy_exact_in", "sell": "sell_exact_in"}
    side = aliases.get(side, side) if isinstance(side, str) else None
    if side not in ("buy_exact_in", "buy_exact_out", "sell_exact_in", "sell_exact_out"):
        raise ValueError("PUMP_SIDE")
    m = validate_market(market)
    base, raw_quote = m["base_reserves_atoms"], m["quote_reserves_atoms"]
    effective_quote = raw_quote + m["virtual_quote_reserves_atoms"]
    rates = fee_rates(m, base, effective_quote)
    base_fee = transfer_fee_at(m["base_transfer_fee"], m.get("epoch"))
    quote_fee = transfer_fee_at(m["quote_transfer_fee"], m.get("epoch"))
    buy, exact_out = side.startswith("buy"), side.endswith("exact_out")
    v2 = m["kind"] == "amm" and m["trade_v2"]

    def fees(value: int) -> tuple[int, int, int]:
        return tuple(_ceil(value * rates[key], BPS) for key in
                     ("lp_fee_bps", "protocol_fee_bps", "creator_fee_bps"))

    def buy_debit(net_quote: int, split: tuple[int, int, int]) -> int:
        lp, protocol, creator = split
        buyback = protocol * m["buyback_bps"] // BPS if v2 else 0
        vault = net_quote + lp + ((protocol + creator - buyback) if v2 else 0)
        return gross_for_transfer_fee(vault, quote_fee) + (buyback if v2 else protocol + creator)

    if buy:
        if exact_out:
            gross_base = gross_for_transfer_fee(amount_atoms, base_fee)
            if gross_base >= base:
                raise ValueError("PUMP_INSUFFICIENT_BASE")
            numerator, denominator = effective_quote * gross_base, base - gross_base
            net_quote = (numerator // denominator + 1 if m["kind"] == "curve"
                         else _ceil(numerator, denominator))
            split = fees(net_quote)
            debit = buy_debit(net_quote, split)
        else:
            spendable = net_of_transfer_fee(amount_atoms, quote_fee)
            if m["kind"] == "curve":
                # Pump SDK legacy/v2 estimate uses (budget - 1) BEFORE fee division.
                pricing_quote = max(0, spendable - 1) * BPS // (BPS + sum(rates.values()))
                gross_base = base * pricing_quote // (effective_quote + pricing_quote)
                if gross_base <= 0 or gross_base >= base:
                    raise ValueError("PUMP_DUST")
                # Get the actual exact-base instruction's debit, not the unused budget.
                net_quote = effective_quote * gross_base // (base - gross_base) + 1
                split = fees(net_quote)
                debit = buy_debit(net_quote, split)
                # Independently rounded fee legs can exceed the SDK estimate by atoms.
                # Fit a valid exact-base buy to the supplied wallet budget.
                if debit > amount_atoms:
                    low, high = 0, gross_base
                    while low < high:
                        middle = (low + high + 1) // 2
                        cost = effective_quote * middle // (base - middle) + 1
                        if buy_debit(cost, fees(cost)) <= amount_atoms:
                            low = middle
                        else:
                            high = middle - 1
                    gross_base = low
                    net_quote = effective_quote * gross_base // (base - gross_base) + 1
                    split = fees(net_quote)
                    debit = buy_debit(net_quote, split)
            else:
                net_quote = spendable * BPS // (BPS + sum(rates.values()))
                split = fees(net_quote)
                net_quote -= max(0, net_quote + sum(split) - spendable)
                if net_quote > 0:
                    net_quote -= max(0, buy_debit(net_quote, split) - amount_atoms)
                pricing_quote = net_quote - 1
                if pricing_quote <= 0:
                    raise ValueError("PUMP_DUST")
                gross_base = base * pricing_quote // (effective_quote + pricing_quote)
                debit = buy_debit(net_quote, split)
        if gross_base <= 0 or debit > (amount_atoms if not exact_out else U64_MAX):
            raise ValueError("PUMP_DUST_OR_BUDGET")
        if m["kind"] == "curve" and gross_base > m["real_base_reserves_atoms"]:
            raise ValueError("PUMP_UNSUPPORTED_MIGRATION_CROSSING")
        base_tax = transfer_fee(gross_base, base_fee)
        received = gross_base - base_tax
        lp, protocol, creator = split
        buyback = protocol * m["buyback_bps"] // BPS if v2 else 0
        vault_net = net_quote + lp + (protocol + creator - buyback if v2 else 0)
        # Only the vault gross-up is an additional wallet cost. Withholding
        # from external fee recipients is already inside their gross fee;
        # adding it here would count the same wallet atoms twice.
        quote_tax = gross_for_transfer_fee(vault_net, quote_fee) - vault_net
        base_delta, quote_delta = -gross_base, vault_net
        quote_quantity = debit
    else:
        real_quote = (m["real_quote_reserves_atoms"] if m["kind"] == "curve" else
                      raw_quote - m["protocol_fees_atoms"] - m["creator_fees_atoms"])

        def sell_for(gross: int) -> tuple[int, int, tuple[int, int, int], int]:
            net_base = net_of_transfer_fee(gross, base_fee)
            output = effective_quote * net_base // (base + net_base)
            split = fees(output)
            user_gross = output - sum(split)
            received = net_of_transfer_fee(max(0, user_gross), quote_fee)
            return received, output, split, net_base

        if exact_out:
            # Independently ceiled fee legs make wallet output locally
            # nonmonotonic. Do not binary-search net output! Start from its
            # smooth upper bound and test successively attainable raw outputs.
            target_gross = gross_for_transfer_fee(amount_atoms, quote_fee)
            required_raw = _ceil(target_gross * BPS, BPS - sum(rates.values()))
            for _ in range(3 * BPS + 4):
                if required_raw >= effective_quote:
                    raise ValueError("PUMP_INSUFFICIENT_QUOTE")
                required_base = _ceil(required_raw * base, effective_quote - required_raw)
                debit = gross_for_transfer_fee(required_base, base_fee)
                _integer(base + net_of_transfer_fee(debit, base_fee), "post_base", 1)
                candidate_received, attained_raw, _, _ = sell_for(debit)
                if candidate_received >= amount_atoms:
                    break
                required_raw = max(required_raw + 1, attained_raw + 1)
            else:
                raise ValueError("PUMP_EXACT_OUT_LIMIT")
        else:
            debit = amount_atoms
        received, net_quote, split, net_base = sell_for(debit)
        lp, protocol, creator = split
        if net_quote - lp > real_quote:
            raise ValueError("PUMP_INSUFFICIENT_REAL_QUOTE")
        if net_quote <= sum(split) or received <= 0:
            raise ValueError("PUMP_DUST")
        buyback = protocol * m["buyback_bps"] // BPS if v2 else 0
        base_tax = debit - net_base
        user_gross = net_quote - sum(split)
        quote_tax = transfer_fee(user_gross, quote_fee)
        base_delta = net_base
        quote_delta = -(net_quote - lp) + ((protocol + creator - buyback) if v2 else 0)
        quote_quantity = received

    if received <= 0:
        raise ValueError("PUMP_DUST")
    max_debit = _ceil(debit * (BPS + slippage_bps), BPS) if exact_out else debit
    min_received = amount_atoms if exact_out else received * (BPS - slippage_bps) // BPS
    if min_received <= 0:
        raise ValueError("PUMP_DUST_SLIPPAGE")
    for value in (debit, received, max_debit, min_received, net_quote):
        _integer(value, "quote_result")
    post = deepcopy(m)
    post["base_reserves_atoms"] = _integer(base + base_delta, "post_base", 1)
    post["quote_reserves_atoms"] = _integer(raw_quote + quote_delta, "post_quote", 1)
    if v2:
        retained = protocol + creator - buyback
        post["protocol_fees_atoms"] += protocol - buyback
        post["creator_fees_atoms"] += creator
        post["virtual_quote_reserves_atoms"] -= retained
    if m["kind"] == "curve":
        post["real_base_reserves_atoms"] += base_delta
        post["real_quote_reserves_atoms"] += quote_delta
        post["complete"] = post["real_base_reserves_atoms"] == 0
    for key, value in post.items():
        if key.endswith("_atoms"):
            _integer(value, key, I128_MIN if key == "virtual_quote_reserves_atoms" else 0,
                     I128_MAX if key == "virtual_quote_reserves_atoms" else U64_MAX)
    _integer(post["quote_reserves_atoms"] + post["virtual_quote_reserves_atoms"],
             "post_effective_quote", 1)
    base_quantity = received if buy else debit
    # Adverse all-in price impact, in bps, includes exchange and transfer fees.
    actual_n, actual_d = quote_quantity, base_quantity
    adverse_n = actual_n * base - effective_quote * actual_d
    if not buy:
        adverse_n = -adverse_n
    impact = _decimal(adverse_n * BPS, effective_quote * actual_d)
    spot = _decimal(effective_quote * 10**m["base_decimals"],
                    base * 10**m["quote_decimals"])
    return {"ok": True, "mode": "PAPER", "kind": m["kind"], "side": side,
            "amount_atoms": str(amount_atoms), "debit_atoms": str(debit),
            "received_atoms": str(received), "net_received_atoms": str(received),
            "min_received_atoms": str(min_received), "max_debit_atoms": str(max_debit),
            "unspent_atoms": str(max(0, amount_atoms - debit) if buy and not exact_out else 0),
            "internal_quote_atoms": str(net_quote), "slippage_bps": slippage_bps,
            "price_impact_bps": impact, "spot_price_quote": spot,
            "fee_rates": rates, "fee_breakdown": {
                "lp_atoms": str(lp), "protocol_atoms": str(protocol),
                "creator_atoms": str(creator), "buyback_atoms": str(buyback),
                "base_transfer_atoms": str(base_tax), "quote_transfer_atoms": str(quote_tax)},
            "post_market": _transport_market(post),
            "limits": ["local estimate; no inclusion guarantee", "no network fee, rent or MEV included"]
                      + (["AMM base transfer-fee math is a local estimate; network parity unverified"]
                         if m["kind"] == "amm" and base_fee["bps"] and base_fee["max_fee"] else []),
            "quote_semantics": ("curve_exact_base_budget_fit" if buy and not exact_out and m["kind"] == "curve"
                                else "single_instruction")}


def _transport_market(market: dict) -> dict:
    for key in list(market):
        if key.endswith("_atoms") and type(market[key]) is int:
            market[key] = str(market[key])
    return market
