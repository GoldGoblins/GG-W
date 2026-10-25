"""Pinned Pump instruction facts and unsigned simulation-only transactions."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from backend import crypto_pump_accounts as a
from backend import crypto_pump_quotes as q

_FACTS = Path(__file__).resolve().parents[1] / "config/crypto-pump-instructions.json"
# These selected public interface facts are reviewed with the implementation.
# A replaced discriminator/account/argument definition must not become code.
_FACTS_DIGEST = "a540352acaa187ba85bb914b5fc96d3658b027db18ade501201376a1a304a09c"


def compact_u16(value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError("PUMP_SIMULATION_COMPACT")
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def _facts() -> dict:
    with _FACTS.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != _FACTS_DIGEST:
        raise ValueError("PUMP_INTERFACE_INTEGRITY")
    facts = json.loads(raw)
    if (facts.get("schema") != "gg.crypto.pump-interface-facts.v1"
            or facts.get("interface_facts_only") is not True
            or facts.get("commit") != a.PROTOCOL_COMMIT):
        raise ValueError("PUMP_INTERFACE_VERSION")
    return facts


def _pda(program, *seeds):
    return a.find_program_address(list(seeds), program)[0]


def _compile(payer: str, blockhash: str, instructions: list) -> tuple[bytes, list[str]]:
    """Compile legacy messages with one zero signature; never sign or send."""
    a.pubkey_bytes(payer)
    a.pubkey_bytes(blockhash)
    if not isinstance(instructions, list) or not 1 <= len(instructions) <= 16:
        raise ValueError("PUMP_SIMULATION_INSTRUCTION_LIMIT")
    permissions = {payer: [True, True]}
    for program, metas, data in instructions:
        a.pubkey_bytes(program)
        if not isinstance(metas, list) or len(metas) > 64 or not isinstance(data, bytes) or len(data) > 1232:
            raise ValueError("PUMP_SIMULATION_INSTRUCTION")
        permissions.setdefault(program, [False, False])
        for key, writable, signer in metas:
            a.pubkey_bytes(key)
            if type(writable) is not bool or type(signer) is not bool:
                raise ValueError("PUMP_SIMULATION_PERMISSIONS")
            current = permissions.setdefault(key, [False, False])
            current[0] |= signer
            current[1] |= writable
    if any(key != payer and flags[0] for key, flags in permissions.items()):
        raise ValueError("PUMP_SIMULATION_SIGNERS")
    if any(any(permissions[program]) for program, _, _ in instructions):
        raise ValueError("PUMP_SIMULATION_PROGRAM_PERMISSIONS")
    ordered = [payer] + [key for key in permissions if key != payer and permissions[key][1]] + [key for key in permissions if key != payer and not permissions[key][1]]
    if len(ordered) > 64:
        raise ValueError("PUMP_SIMULATION_ACCOUNT_LIMIT")
    lookup = {key: index for index, key in enumerate(ordered)}
    readonly = sum(not permissions[key][1] for key in ordered if key != payer)
    message = bytes([1, 0, readonly]) + compact_u16(len(ordered))
    message += b"".join(a.pubkey_bytes(key) for key in ordered) + a.pubkey_bytes(blockhash)
    message += compact_u16(len(instructions))
    for program, metas, data in instructions:
        indices = bytes(lookup[key] for key, _, _ in metas)
        message += bytes([lookup[program]]) + compact_u16(len(indices)) + indices + compact_u16(len(data)) + data
    transaction = b"\x01" + b"\0" * 64 + message
    if len(transaction) > 1232:
        raise ValueError("PUMP_SIMULATION_TRANSACTION_SIZE")
    return transaction, ordered


def _ata_create(payer: str, owner: str, mint: str, token_program: str) -> tuple:
    return (a.ASSOCIATED_TOKEN_PROGRAM,
            [(payer, True, True), (a.derive_ata(owner, mint, token_program), True, False),
             (owner, False, False), (mint, False, False), (a.ZERO_KEY, False, False),
             (token_program, False, False)], b"\x01")


def _before_token(raw: dict | None, mint: str, payer: str, program: str) -> dict | None:
    if raw is None:
        return None
    try:
        account = a.decode_token_account(raw, expected_mint=mint,
                    expected_owner=payer, expected_program=program)
    except a.AccountDecodeError:
        raise ValueError("PUMP_SIMULATION_USER_TOKEN_INVALID") from None
    if account.get("quote_supported") is not True:
        raise ValueError("PUMP_SIMULATION_USER_TOKEN_UNSUPPORTED")
    return account


def build_unsigned(context: dict, market: dict, quote: dict, payer: str, blockhash: str) -> dict:
    """Prepare simulation bytes; no keys, signing, network or broadcast code.

    AMM context.raw_before must contain payer/base ATA/WSOL ATA RPC snapshots.
    WSOL preparation creates its ATA and wraps only the missing cap balance.
    It never closes an account. Native rent and transaction fees are separate
    from the swap quote and are measured by the caller's RPC simulation.
    """
    a.pubkey_bytes(payer)
    a.pubkey_bytes(blockhash)
    if not isinstance(context, dict) or not isinstance(quote, dict):
        raise ValueError("PUMP_SIMULATION_CONTEXT")
    market = q.validate_market(market)
    if market.get("quote_mint") != a.WSOL_MINT or context.get("unsupported"):
        raise ValueError("PUMP_SIMULATION_ROUTE_UNSUPPORTED")
    # Do not trust UI/JSON amounts, flags or wallet caps as instruction data.
    recalculated = q.quote(market, quote.get("side"),
            q._integer(quote.get("amount_atoms"), "amount", 1), quote.get("slippage_bps"))
    for key in ("kind", "side", "mode", "ok", "amount_atoms", "debit_atoms", "received_atoms",
                "min_received_atoms", "max_debit_atoms", "fee_breakdown", "quote_semantics"):
        if quote.get(key) != recalculated[key]:
            raise ValueError("PUMP_SIMULATION_QUOTE_CHANGED")
    kind, program = market["kind"], context["program"]
    base_fee = q.transfer_fee_at(market.get("base_transfer_fee"), market.get("epoch"))
    if kind == "amm" and base_fee["bps"] and base_fee["max_fee"]:
        # The pinned public AMM helpers establish quote-mint transfer fee
        # semantics, not base-mint TransferFeeConfig accounting/checks.
        # A local wallet estimate must not pretend to be a verified wire bound.
        raise ValueError("PUMP_SIMULATION_BASE_TRANSFER_FEE_UNVERIFIED")
    if program != (a.PUMP_PROGRAM if kind == "curve" else a.PUMP_AMM_PROGRAM):
        raise ValueError("PUMP_SIMULATION_PROGRAM")
    if kind == "amm" and not market.get("trade_v2"):
        raise ValueError("PUMP_SIMULATION_AMM_VERSION")
    token_program = context["token"]["token_program"]
    quote_program = context["quote_token"]["token_program"]
    if (token_program not in (a.TOKEN_PROGRAM, a.TOKEN_2022_PROGRAM)
            or quote_program != a.TOKEN_PROGRAM):
        raise ValueError("PUMP_SIMULATION_TOKEN_PROGRAM")
    if (context["token"].get("quote_supported") is not True
            or context["quote_token"].get("quote_supported") is not True):
        raise ValueError("PUMP_SIMULATION_TOKEN_UNSUPPORTED")
    if context["global_address"] != a.derive_global(kind) or context["fee_address"] != a.derive_fee_config(program):
        raise ValueError("PUMP_SIMULATION_PDA")
    decoded = context["decoded"]
    expected_market = (a.derive_curve(market["base_mint"]) if kind == "curve" else
        a.derive_pool(market["base_mint"], market["quote_mint"],
                      creator=decoded.get("creator"), index=decoded.get("index")))
    if context["market_address"] != expected_market or market.get("address", expected_market) != expected_market:
        raise ValueError("PUMP_SIMULATION_MARKET_TARGET")
    for field, mint, token in (("base_vault", market["base_mint"], token_program),
                               ("quote_vault", market["quote_mint"], quote_program)):
        if context[field] != a.derive_ata(expected_market, mint, token):
            raise ValueError("PUMP_SIMULATION_VAULT_TARGET")
    buy = quote["side"].startswith("buy")
    # Curve exact-input estimates are budget-fitted exact-base buys. The
    # serialized instruction must match that meaning, not an exact-in helper.
    instruction = ("buy_v2" if kind == "curve" or quote["side"] == "buy_exact_out" else "buy_exact_quote_in_v2") if buy else "sell_v2"
    facts = _facts()
    if facts.get("commit") != a.PROTOCOL_COMMIT or facts["programs"][kind]["address"] != program:
        raise ValueError("PUMP_INTERFACE_VERSION")
    specification = facts["programs"][kind]["instructions"][instruction]
    if bytes(specification["discriminator"]) != hashlib.sha256(("global:" + instruction).encode()).digest()[:8]:
        raise ValueError("PUMP_INTERFACE_DISCRIMINATOR")
    global_state, decoded = context["global"], context["decoded"]
    buybacks = [key for key in global_state.get("buyback_fee_recipients", []) if key != a.ZERO_KEY]
    if not buybacks:
        raise ValueError("PUMP_BUYBACK_RECIPIENT_MISSING")
    base_ata = a.derive_ata(payer, market["base_mint"], token_program)
    quote_ata = a.derive_ata(payer, market["quote_mint"], quote_program)
    creator = decoded.get("creator" if kind == "curve" else "coin_creator", a.ZERO_KEY)
    creator_vault = _pda(a.PUMP_PROGRAM, b"creator-vault", a.pubkey_bytes(creator))
    accumulator = _pda(program, b"user_volume_accumulator", a.pubkey_bytes(payer))
    recipient = global_state.get("fee_recipient", a.ZERO_KEY)
    if kind == "curve" and recipient == a.ZERO_KEY:
        recipient = next((key for key in global_state.get("fee_recipients", []) if key != a.ZERO_KEY), None)
        if recipient is None:
            raise ValueError("PUMP_FEE_RECIPIENT_MISSING")
    addresses = {
        "global": context["global_address"], "global_config": context["global_address"],
        "pool": context["market_address"], "bonding_curve": context["market_address"],
        "base_mint": market["base_mint"], "quote_mint": market["quote_mint"],
        "base_token_program": token_program, "quote_token_program": quote_program,
        "user": payer, "associated_base_user": base_ata, "user_base_token_account": base_ata,
        "associated_quote_user": quote_ata, "user_quote_token_account": quote_ata,
        "associated_base_bonding_curve": context["base_vault"], "pool_base_token_account": context["base_vault"],
        "associated_quote_bonding_curve": context["quote_vault"], "pool_quote_token_account": context["quote_vault"],
        "fee_recipient": recipient,
        "associated_quote_fee_recipient": a.derive_ata(recipient, market["quote_mint"], quote_program),
        "buyback_fee_recipient": buybacks[0] if kind == "curve" else a.derive_ata(buybacks[0], market["quote_mint"], quote_program),
        "associated_quote_buyback_fee_recipient": a.derive_ata(buybacks[0], market["quote_mint"], quote_program),
        "creator_vault": creator_vault,
        "associated_creator_vault": a.derive_ata(creator_vault, market["quote_mint"], quote_program),
        "sharing_config": _pda(a.PUMP_FEES_PROGRAM, b"sharing-config", a.pubkey_bytes(market["base_mint"])),
        "global_volume_accumulator": _pda(program, b"global_volume_accumulator"),
        "user_volume_accumulator": accumulator,
        "associated_user_volume_accumulator": a.derive_ata(accumulator, market["quote_mint"], quote_program),
        "fee_config": context["fee_address"], "event_authority": _pda(program, b"__event_authority"),
    }
    metas = []
    for entry in specification["accounts"]:
        key = entry.get("address") or (program if entry["name"] == "program" else addresses.get(entry["name"]))
        if key is None:
            raise ValueError("PUMP_SIMULATION_ACCOUNT_MAPPING")
        metas.append((key, entry.get("writable", False), entry.get("signer", False)))
    if instruction == "buy_v2":
        first = int(quote["received_atoms"]) + int(quote["fee_breakdown"]["base_transfer_atoms"])
        second = int(quote["max_debit_atoms"])
    elif buy:
        first, second = int(quote["amount_atoms"]), int(quote["min_received_atoms"])
    else:
        first, second = int(quote["debit_atoms"]), int(quote["min_received_atoms"])
    if not 0 < first < 2**64 or not 0 < second < 2**64:
        raise ValueError("PUMP_SIMULATION_AMOUNT")
    data = bytes(specification["discriminator"]) + first.to_bytes(8, "little") + second.to_bytes(8, "little")
    if kind == "curve" and buy:
        data += b"\x00"  # OptionBool(false), never a migration/partial fill.
    instructions = []
    before = context.get("raw_before")
    if kind == "amm" and not isinstance(before, dict):
        raise ValueError("PUMP_SIMULATION_USER_SNAPSHOT_REQUIRED")
    existing_quote = None
    if before is not None:
        if not isinstance(before, dict) or any(key not in before for key in (payer, base_ata, quote_ata)):
            raise ValueError("PUMP_SIMULATION_USER_SNAPSHOT_REQUIRED")
        payer_raw = before[payer]
        if (not isinstance(payer_raw, dict) or payer_raw.get("owner") != a.ZERO_KEY
                or payer_raw.get("executable") is not False):
            raise ValueError("PUMP_SIMULATION_PAYER")
        q._integer(payer_raw.get("lamports"), "payer_lamports")
        existing_base = _before_token(before[base_ata], market["base_mint"], payer, token_program)
        existing_quote = _before_token(before[quote_ata], a.WSOL_MINT, payer, quote_program)
        if existing_quote is not None:
            reserve = existing_quote["native_reserve"]
            if reserve is None:
                raise ValueError("PUMP_SIMULATION_WSOL_NATIVE")
            lamports = q._integer(before[quote_ata].get("lamports"), "wsol_lamports")
            if lamports < reserve + existing_quote["amount"]:
                raise ValueError("PUMP_SIMULATION_WSOL_BALANCE")
        if not buy and (existing_base is None or existing_base["amount"] < first):
            raise ValueError("PUMP_SIMULATION_USER_BASE_BALANCE")
    if buy:
        instructions.append(_ata_create(payer, payer, market["base_mint"], token_program))
    wrap = 0
    if kind == "amm":
        instructions.append(_ata_create(payer, payer, a.WSOL_MINT, quote_program))
        if buy:
            available = 0
            if existing_quote is not None:
                available = q._integer(before[quote_ata]["lamports"], "wsol_lamports") - existing_quote["native_reserve"]
            wrap = max(0, int(quote["max_debit_atoms"]) - available)
            if wrap > q._integer(before[payer].get("lamports"), "payer_lamports"):
                raise ValueError("PUMP_SIMULATION_NATIVE_BALANCE")
            if wrap:
                instructions.append((a.ZERO_KEY, [(payer, True, True), (quote_ata, True, False)],
                                     (2).to_bytes(4, "little") + wrap.to_bytes(8, "little")))
            instructions.append((quote_program, [(quote_ata, True, False)], b"\x11"))
    instructions.append((program, metas, data))
    transaction, keys = _compile(payer, blockhash, instructions)
    return {"transaction": base64.b64encode(transaction).decode("ascii"),
            "message": base64.b64encode(transaction[65:]).decode("ascii"),
            "accounts": keys, "observed_accounts": list(dict.fromkeys([payer, base_ata, quote_ata])),
            "instruction": instruction, "signatures": "ZERO_SIMULATION_ONLY",
            "preparation_wrap_lamports": str(wrap), "quote_account": quote_ata,
            "native_quote": kind == "curve", "transaction_bytes": len(transaction),
            "limits": ["unsigned simulation only", "quote excludes transaction fees and account rent",
                       "AMM proceeds remain WSOL; existing accounts are never closed"]}
