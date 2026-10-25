"""Bounded hypothetical Pump cost stress, using GG's offline integer quotes.

These six reserve/fee perturbations are independent scenarios, not forecasts,
simulated market histories, transaction builders, or execution guarantees.
No RPC, wallet, model, external runtime, or persistent state is accessed.
"""
from __future__ import annotations

from copy import deepcopy
import re

from backend import crypto_pump_quotes as quotes

MAX_SCENARIOS = 6
MODE = "HYPOTHETICAL COST STRESS"
_RATE_KEYS = ("lp_fee_bps", "protocol_fee_bps", "creator_fee_bps")
_LIMITS = (
    "Hypothetical reserve and fee changes; no forecast or probability is assigned.",
    "Every row is compared with the original quote's wallet debit and minimum received bounds.",
    "Liquidity rows retain 75% or 50% of observed depth. Price rows change quote/base reserve ratios.",
    "Curve available real quote is never increased. Integer rounding or insufficient real reserves can make a scenario unsupported.",
    "The fee row freezes baseline effective exchange rates, then adds 25 bps to the protocol rate; transfer fees remain unchanged.",
    "Network fees, account rent, MEV and inclusion are outside these swap estimates.",
)


def _integer(value, *, positive=False, maximum=quotes.U64_MAX):
    if isinstance(value, str) and 0 < len(value) <= 40 and value.isascii() and value.isdecimal():
        value = int(value)
    if type(value) is not int or not (1 if positive else 0) <= value <= maximum:
        raise ValueError("PUMP_STRESS_INVALID_INPUT")
    return value


def _error(exc):
    message = str(exc)
    return message if re.fullmatch(r"PUMP_[A-Z0-9_]{1,80}", message) else "PUMP_STRESS_INVALID_INPUT"


def _units(value, decimals, symbol):
    whole, fraction = divmod(value, 10**decimals)
    tail = f"{fraction:0{decimals}d}".rstrip("0") if decimals else ""
    return str(whole) + ("." + tail if tail else "") + " " + symbol


def _signed_scale(value, numerator, denominator):
    magnitude = abs(value) * numerator // denominator
    return -magnitude if value < 0 else magnitude


def _scale_quote_reserves(market, numerator, denominator):
    """Scale effective liquidity while keeping retained fee buckets coherent.

    AMM virtual quote can contain a signed offset minus retained fees. Scale
    the offset and each bucket separately, then derive raw reserves from the
    target effective reserve. This avoids counting retained fees as liquidity
    or rounding a negative offset through a floating point value.
    """
    if market["kind"] == "curve":
        market["quote_reserves_atoms"] = market["quote_reserves_atoms"] * numerator // denominator
        # Quote-side price stress never creates spendable curve inventory.
        market["real_quote_reserves_atoms"] = min(
            market["real_quote_reserves_atoms"],
            market["real_quote_reserves_atoms"] * numerator // denominator)
        return
    retained = market["protocol_fees_atoms"] + market["creator_fees_atoms"]
    offset = market["virtual_quote_reserves_atoms"] + retained
    effective = market["quote_reserves_atoms"] + market["virtual_quote_reserves_atoms"]
    for key in ("protocol_fees_atoms", "creator_fees_atoms"):
        market[key] = market[key] * numerator // denominator
    next_retained = market["protocol_fees_atoms"] + market["creator_fees_atoms"]
    market["virtual_quote_reserves_atoms"] = _signed_scale(offset, numerator, denominator) - next_retained
    market["quote_reserves_atoms"] = effective * numerator // denominator - market["virtual_quote_reserves_atoms"]


def _scenario(market, kind, parameter, baseline_rates):
    result = deepcopy(market)
    if kind == "liquidity":
        result["base_reserves_atoms"] = result["base_reserves_atoms"] * parameter // 100
        if result["kind"] == "curve":
            result["real_base_reserves_atoms"] = result["real_base_reserves_atoms"] * parameter // 100
        _scale_quote_reserves(result, parameter, 100)
    elif kind == "price":
        _scale_quote_reserves(result, parameter, quotes.BPS)
    elif kind == "fee":
        # Freeze the already-selected canonical tier and creator override.
        # Leaving FeeConfig present would override these flat values again.
        result.pop("fee_config", None)
        result.update({key: baseline_rates[key] for key in _RATE_KEYS})
        result["protocol_fee_bps"] += parameter
        result["creator_fee_configurable"] = False
        result["configured_creator_fee_bps"] = 0
    return result


def _unsupported(label, exc):
    return {"label": label, "supported": False, "debit_display": "—", "received_display": "—",
            "within_slippage": False, "error": _error(exc)}


def analyze(market: dict, proposal: dict) -> dict:
    """Return at most six local scenarios against the original wallet bounds.

    The proposal is an existing ``crypto_pump_quotes.quote`` result. Atomic
    integers may arrive as strings; no input is mutated. A stale/mismatched or
    invalid baseline yields one unsupported row instead of invented estimates.
    """
    report = {"mode": MODE, "rows": [], "limits": list(_LIMITS)}
    try:
        if not isinstance(proposal, dict):
            raise ValueError("PUMP_STRESS_INVALID_INPUT")
        side = proposal.get("side")
        amount = _integer(proposal.get("amount_atoms"), positive=True)
        slippage = _integer(proposal.get("slippage_bps"), maximum=quotes.BPS - 1)
        min_received = _integer(proposal.get("min_received_atoms"), positive=True)
        max_debit = _integer(proposal.get("max_debit_atoms"), positive=True)
        normalized = quotes.validate_market(market)
        baseline = quotes.quote(normalized, side, amount, slippage)
        # Evidence must refer to this snapshot, not a previous market's quote.
        for key in ("debit_atoms", "received_atoms"):
            if key in proposal and _integer(proposal[key], positive=True) != int(baseline[key]):
                raise ValueError("PUMP_STRESS_QUOTE_MISMATCH")
        if "fee_rates" in proposal and proposal["fee_rates"] != baseline["fee_rates"]:
            raise ValueError("PUMP_STRESS_QUOTE_MISMATCH")
    except (ValueError, TypeError, KeyError) as exc:
        report["rows"] = [_unsupported("Original quote", exc)]
        return report

    buy = baseline["side"].startswith("buy")
    symbol = normalized.get("quote_symbol", "QUOTE")
    symbol = symbol if isinstance(symbol, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,16}", symbol) else "QUOTE"
    input_decimals, output_decimals = (normalized["quote_decimals"], normalized["base_decimals"]) if buy else (normalized["base_decimals"], normalized["quote_decimals"])
    input_symbol, output_symbol = (symbol, "TOKEN") if buy else ("TOKEN", symbol)
    cases = [
        ("Original quote", "base", 0),
        ("Depth remaining 75%", "liquidity", 75),
        ("Depth remaining 50%", "liquidity", 50),
        ("Adverse price " + ("+10%" if buy else "-10%"), "price", 11000 if buy else 9000),
        ("Adverse price " + ("+25%" if buy else "-25%"), "price", 12500 if buy else 7500),
        ("Protocol fee +25 bps", "fee", 25),
    ]
    for label, kind, parameter in cases[:MAX_SCENARIOS]:
        try:
            stressed = baseline if kind == "base" else quotes.quote(
                _scenario(normalized, kind, parameter, baseline["fee_rates"]), side, amount, slippage)
            debit, received = int(stressed["debit_atoms"]), int(stressed["received_atoms"])
            report["rows"].append({"label": label, "supported": True,
                "debit_display": _units(debit, input_decimals, input_symbol),
                "received_display": _units(received, output_decimals, output_symbol),
                "debit_atoms": str(debit), "received_atoms": str(received),
                "within_slippage": debit <= max_debit and received >= min_received,
                "error": ""})
        except (ValueError, TypeError, KeyError) as exc:
            report["rows"].append(_unsupported(label, exc))
    return report
