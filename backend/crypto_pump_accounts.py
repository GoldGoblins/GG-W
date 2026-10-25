"""Bounded, read-only Solana account decoding; no RPC, wallet or signing code.

Pump field order/discriminators/seeds are protocol facts from official
pump-fun/pump-public-docs, pinned at PROTOCOL_COMMIT. The implementation is
original Python, not a bundled SDK. Missing *whole* appended fields default to
zero as the official docs specify; partial fields and unknown trailing data
are rejected. A decoded account alone is not a verified market: callers must
also bind its requested address, mint, vault, owner, slot and token program.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any, Iterable

PROTOCOL_COMMIT = "639b87fb45c3adeffa6f7c4a1bf0cb85e392bf22"
TOKEN_PROTOCOL_COMMIT = "3f85f9cf0764a15869d4c11411cfe022eaa1d6ee"
PROTOCOL_SOURCE = "https://github.com/pump-fun/pump-public-docs/tree/" + PROTOCOL_COMMIT
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_FEES_PROGRAM = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
ZERO_KEY = "11111111111111111111111111111111"
MAX_ACCOUNT_BYTES = 16384
MAX_FEE_TIERS = 128
U64_MAX = (1 << 64) - 1
# Public SDK 2.2.0/src/sdk/offlinePumpAmm.ts publishes these allocation
# versions. Allocation bytes are not interchangeable with serialized fields.
POOL_SERIALIZED_BYTES = 287
POOL_EXTENDED_BYTES = 300
FEE_CONFIG_PRE_STABLE_BYTES = 2512
FEE_CONFIG_POST_STABLE_BYTES = 4073
FEE_CONFIG_CURRENT_BYTES = 4097
_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_DISCRIMINATORS = {
    "BondingCurve": bytes([23, 183, 248, 55, 96, 216, 172, 96]),
    "Pool": bytes([241, 154, 109, 4, 17, 177, 109, 188]),
    "Global": bytes([167, 232, 232, 177, 200, 108, 114, 127]),
    "GlobalConfig": bytes([149, 8, 156, 202, 160, 252, 176, 217]),
    "FeeConfig": bytes([143, 52, 146, 187, 219, 123, 76, 155]),
}


class AccountDecodeError(ValueError):
    """The account cannot safely be interpreted by this protocol version."""


def b58encode(raw: bytes) -> str:
    value = int.from_bytes(raw, "big")
    result = ""
    while value:
        value, digit = divmod(value, 58)
        result = _ALPHABET[digit] + result
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + result


def pubkey_bytes(key: str) -> bytes:
    if not isinstance(key, str) or not 32 <= len(key) <= 44:
        raise AccountDecodeError("invalid public key length")
    value = 0
    for character in key:
        digit = _ALPHABET.find(character)
        if digit < 0:
            raise AccountDecodeError("invalid base58 public key")
        value = value * 58 + digit
    zeroes = len(key) - len(key.lstrip("1"))
    raw = b"\0" * zeroes + value.to_bytes((value.bit_length() + 7) // 8, "big")
    if len(raw) != 32 or b58encode(raw) != key:
        raise AccountDecodeError("public key must encode exactly 32 bytes")
    return raw


def _on_ed25519_curve(raw: bytes) -> bool:
    # Compressed Edwards-y decompression: small-order points also count as
    # on-curve. Signature-verification APIs reject some of those and therefore
    # are not substitutes for Solana's PDA off-curve test.
    prime = (1 << 255) - 19
    y = (int.from_bytes(raw, "little") & ((1 << 255) - 1)) % prime
    y2 = y * y % prime
    d = -121665 * pow(121666, prime - 2, prime) % prime
    denominator = (d * y2 + 1) % prime
    if denominator == 0:
        return False
    x2 = (y2 - 1) * pow(denominator, prime - 2, prime) % prime
    return x2 == 0 or pow(x2, (prime - 1) // 2, prime) == 1


def find_program_address(seeds: Iterable[bytes], program: str) -> tuple[str, int]:
    parts = []
    for seed in seeds:
        if len(parts) == 15 or not isinstance(seed, bytes) or len(seed) > 32:
            raise AccountDecodeError("PDA needs at most 15 byte seeds of at most 32 bytes")
        parts.append(seed)
    program_bytes = pubkey_bytes(program)
    for bump in range(255, -1, -1):
        digest = hashlib.sha256(b"".join(parts) + bytes([bump]) + program_bytes + b"ProgramDerivedAddress").digest()
        if not _on_ed25519_curve(digest):
            return b58encode(digest), bump
    raise AccountDecodeError("PDA bump unavailable")


def derive_curve(mint: str) -> str:
    return find_program_address([b"bonding-curve", pubkey_bytes(mint)], PUMP_PROGRAM)[0]


def derive_pool_authority(mint: str) -> str:
    return find_program_address([b"pool-authority", pubkey_bytes(mint)], PUMP_PROGRAM)[0]


def derive_pool(mint: str, quote_mint: str = WSOL_MINT, *, creator: str | None = None, index: int = 0) -> str:
    if type(index) is not int or not 0 <= index <= 65535:
        raise AccountDecodeError("pool index must fit u16")
    authority = creator if creator is not None else derive_pool_authority(mint)
    return find_program_address([b"pool", index.to_bytes(2, "little"), pubkey_bytes(authority),
                                 pubkey_bytes(mint), pubkey_bytes(quote_mint)], PUMP_AMM_PROGRAM)[0]


def derive_ata(owner: str, mint: str, token_program: str = TOKEN_PROGRAM) -> str:
    if token_program not in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
        raise AccountDecodeError("unsupported token program")
    return find_program_address([pubkey_bytes(owner), pubkey_bytes(token_program), pubkey_bytes(mint)], ASSOCIATED_TOKEN_PROGRAM)[0]


def derive_global(kind: str = "pump") -> str:
    if kind in ("pump", "curve", PUMP_PROGRAM):
        return find_program_address([b"global"], PUMP_PROGRAM)[0]
    if kind in ("amm", "pumpswap", PUMP_AMM_PROGRAM):
        return find_program_address([b"global_config"], PUMP_AMM_PROGRAM)[0]
    raise AccountDecodeError("unknown global kind")


def derive_fee_config(program: str = PUMP_PROGRAM) -> str:
    if program not in (PUMP_PROGRAM, PUMP_AMM_PROGRAM):
        raise AccountDecodeError("unknown fee config program")
    return find_program_address([b"fee_config", pubkey_bytes(program)], PUMP_FEES_PROGRAM)[0]


def _account(account: dict[str, Any], owners: tuple[str, ...], maximum: int = MAX_ACCOUNT_BYTES) -> tuple[bytes, str]:
    if not isinstance(account, dict):
        raise AccountDecodeError("missing RPC account")
    owner = account.get("owner")
    if owner not in owners:
        raise AccountDecodeError("unexpected account owner")
    if account.get("executable") is not False:
        raise AccountDecodeError("account must be explicitly non-executable")
    encoded = account.get("data")
    if not isinstance(encoded, (list, tuple)) or len(encoded) != 2 or encoded[1] != "base64" or not isinstance(encoded[0], str):
        raise AccountDecodeError("expected base64 RPC account data")
    if len(encoded[0]) > ((maximum + 2) // 3) * 4:
        raise AccountDecodeError("account exceeds decoder bound")
    try:
        raw = base64.b64decode(encoded[0], validate=True)
    except (ValueError, binascii.Error):
        raise AccountDecodeError("invalid base64 account data") from None
    if len(raw) > maximum:
        raise AccountDecodeError("account exceeds decoder bound")
    return raw, owner


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise AccountDecodeError("truncated account field")
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def integer(self, size: int, *, signed: bool = False) -> int:
        return int.from_bytes(self.take(size), "little", signed=signed)

    def boolean(self) -> bool:
        value = self.integer(1)
        if value not in (0, 1):
            raise AccountDecodeError("invalid boolean")
        return bool(value)

    def key(self) -> str:
        return b58encode(self.take(32))

    def coption(self, size: int) -> bytes | None:
        tag = self.integer(4)
        value = self.take(size)
        if tag not in (0, 1):
            raise AccountDecodeError("invalid COption tag")
        return value if tag else None


def _read_fields(reader: _Reader, fields: list[tuple[str, str]], *, appended: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, field_type in fields:
        if appended and reader.pos == len(reader.data):
            result[name] = ZERO_KEY if field_type == "key" else False if field_type == "bool" else [] if field_type.startswith("keys") else 0
        elif field_type == "bool":
            result[name] = reader.boolean()
        elif field_type == "key":
            result[name] = reader.key()
        elif field_type.startswith("keys"):
            result[name] = [reader.key() for _ in range(int(field_type[4:]))]
        else:
            result[name] = reader.integer(int(field_type[1:]) // 8, signed=field_type.startswith("i"))
    if reader.pos != len(reader.data):
        raise AccountDecodeError("unknown trailing account layout")
    return result


def _anchor(account: dict[str, Any], owner: str, kind: str) -> _Reader:
    raw, _ = _account(account, (owner,))
    reader = _Reader(raw)
    if reader.take(8) != _DISCRIMINATORS[kind]:
        raise AccountDecodeError("unexpected " + kind + " discriminator")
    return reader


_CURVE_FIELDS = [
    ("virtual_token_reserves", "u64"), ("virtual_quote_reserves", "u64"),
    ("real_token_reserves", "u64"), ("real_quote_reserves", "u64"),
    ("token_total_supply", "u64"), ("complete", "bool"),
    ("creator", "key"), ("is_mayhem_mode", "bool"), ("is_cashback_coin", "bool"),
    ("quote_mint", "key"), ("creator_fee_bps", "u64"), ("can_edit_creator_fee", "bool"),
    ("is_holder_reward", "bool"), ("creator_fee", "u64"), ("protocol_fees", "u64"),
    ("depth", "u8"), ("initial_virtual_quote_reserves", "u64"),
    ("post_complete_base_out", "u64"), ("post_complete_quote_in", "u64"),
]
_POOL_FIELDS = [
    ("pool_bump", "u8"), ("index", "u16"), ("creator", "key"), ("base_mint", "key"),
    ("quote_mint", "key"), ("lp_mint", "key"), ("pool_base_token_account", "key"),
    ("pool_quote_token_account", "key"), ("lp_supply", "u64"), ("coin_creator", "key"),
    ("is_mayhem_mode", "bool"), ("is_cashback_coin", "bool"), ("virtual_quote_reserves", "i128"),
    ("creator_fee_bps", "u64"), ("can_edit_creator_fee", "bool"), ("is_holder_reward", "bool"),
    ("protocol_fees", "u64"), ("creator_fees", "u64"),
]


def decode_curve(account: dict[str, Any]) -> dict[str, Any]:
    reader = _anchor(account, PUMP_PROGRAM, "BondingCurve")
    if len(reader.data) < 49:
        raise AccountDecodeError("truncated bonding curve")
    result = _read_fields(reader, _CURVE_FIELDS, appended=True)
    result.update(kind="bonding_curve", layout_bytes=len(reader.data), warnings=[])
    result["quote_mint_raw"] = result["quote_mint"]
    if result["quote_mint"] == ZERO_KEY:
        result["quote_mint"] = WSOL_MINT
    result["virtual_sol_reserves"] = result["virtual_quote_reserves"]
    result["real_sol_reserves"] = result["real_quote_reserves"]
    if result["depth"]:
        result["warnings"].append("quote_chain_curve_requires_v3")
    if result["is_mayhem_mode"]:
        result["warnings"].append("mayhem_mode")
    if result["can_edit_creator_fee"] or result["creator_fee_bps"] > 10000:
        result["warnings"].append("unsupported_creator_fee_configuration")
    return result


def decode_pool(account: dict[str, Any]) -> dict[str, Any]:
    reader = _anchor(account, PUMP_AMM_PROGRAM, "Pool")
    allocation_bytes = len(reader.data)
    if allocation_bytes == POOL_EXTENDED_BYTES:
        # The documented extend_account allocation is 300, while the pinned
        # Pool schema ends at 287. Only this known allocation and a zero tail
        # are accepted. No arbitrary stripping or future field guessing.
        if any(reader.data[POOL_SERIALIZED_BYTES:]):
            raise AccountDecodeError("nonzero unknown extended pool fields")
        reader.data = reader.data[:POOL_SERIALIZED_BYTES]
    if len(reader.data) < 211:
        raise AccountDecodeError("truncated pool")
    result = _read_fields(reader, _POOL_FIELDS, appended=True)
    result.update(kind="pumpswap_pool", layout_bytes=allocation_bytes,
                  serialized_bytes=len(reader.data), warnings=[])
    result["reserved_quote_fees"] = result["protocol_fees"] + result["creator_fees"]
    result["boost_quote_reserves"] = result["virtual_quote_reserves"] + result["reserved_quote_fees"]
    result["is_pump_pool"] = result["creator"] == derive_pool_authority(result["base_mint"])
    if result["is_mayhem_mode"]:
        result["warnings"].append("mayhem_mode")
    if result["can_edit_creator_fee"] or result["creator_fee_bps"] > 10000:
        result["warnings"].append("unsupported_creator_fee_configuration")
    return result


def effective_pool_quote_reserves(pool: dict[str, Any], quote_amount: int) -> int:
    virtual = pool.get("virtual_quote_reserves")
    if type(quote_amount) is not int or not 0 <= quote_amount <= U64_MAX or type(virtual) is not int or not -(1 << 127) <= virtual < 1 << 127:
        raise AccountDecodeError("invalid quote reserve integer")
    effective = quote_amount + virtual
    if not 0 <= effective <= U64_MAX:
        raise AccountDecodeError("effective quote reserve outside u64")
    # Retained protocol/creator fees are ALREADY deducted in signed virtual.
    return effective


_GLOBAL_FIELDS = [
    ("initialized", "bool"), ("authority", "key"), ("fee_recipient", "key"),
    ("initial_virtual_token_reserves", "u64"), ("initial_virtual_sol_reserves", "u64"),
    ("initial_real_token_reserves", "u64"), ("token_total_supply", "u64"),
    ("fee_basis_points", "u64"), ("withdraw_authority", "key"), ("enable_migrate", "bool"),
    ("pool_migration_fee", "u64"), ("creator_fee_basis_points", "u64"), ("fee_recipients", "keys7"),
    ("set_creator_authority", "key"), ("admin_set_creator_authority", "key"),
    ("create_v2_enabled", "bool"), ("whitelist_pda", "key"), ("reserved_fee_recipient", "key"),
    ("mayhem_mode_enabled", "bool"), ("reserved_fee_recipients", "keys7"),
    ("is_cashback_enabled", "bool"), ("buyback_fee_recipients", "keys8"), ("buyback_basis_points", "u64"),
    ("initial_virtual_quote_reserves", "u64"), ("whitelisted_quote_mints", "keys1"),
    ("creator_fee_configurable", "bool"), ("max_configurable_creator_fee_bps", "u64"),
    ("holder_reward_claim_authority", "key"), ("is_holder_reward_enabled", "bool"), ("max_curve_depth", "u8"),
]
_AMM_GLOBAL_FIELDS = [
    ("admin", "key"), ("lp_fee_basis_points", "u64"), ("protocol_fee_basis_points", "u64"),
    ("disable_flags", "u8"), ("protocol_fee_recipients", "keys8"),
    ("coin_creator_fee_basis_points", "u64"), ("admin_set_coin_creator_authority", "key"),
    ("whitelist_pda", "key"), ("reserved_fee_recipient", "key"), ("mayhem_mode_enabled", "bool"),
    ("reserved_fee_recipients", "keys7"), ("is_cashback_enabled", "bool"),
    ("buyback_fee_recipients", "keys8"), ("buyback_basis_points", "u64"), ("boost_authority", "key"),
    ("boost_enabled", "bool"), ("creator_fee_configurable", "bool"), ("max_configurable_creator_fee_bps", "u64"),
]


def decode_global(account: dict[str, Any], *, kind: str = "pump") -> dict[str, Any]:
    if kind in ("pump", "curve", PUMP_PROGRAM):
        reader = _anchor(account, PUMP_PROGRAM, "Global")
        fields, minimum = _GLOBAL_FIELDS, 113
    elif kind in ("amm", "pumpswap", PUMP_AMM_PROGRAM):
        reader = _anchor(account, PUMP_AMM_PROGRAM, "GlobalConfig")
        fields, minimum = _AMM_GLOBAL_FIELDS, 313
    else:
        raise AccountDecodeError("unknown global kind")
    if len(reader.data) < minimum:
        raise AccountDecodeError("truncated global configuration")
    result = _read_fields(reader, fields, appended=True)
    for name, value in result.items():
        if (name.endswith("basis_points") or name.endswith("fee_bps")) and value > 10000:
            raise AccountDecodeError("invalid global fee basis points")
    result.update(kind="pump_global" if fields is _GLOBAL_FIELDS else "pumpswap_global", layout_bytes=len(reader.data), warnings=[])
    return result


def _fees(reader: _Reader) -> dict[str, int]:
    result = {name: reader.integer(8) for name in ("lp_fee_bps", "protocol_fee_bps", "creator_fee_bps")}
    if sum(result.values()) > 10000:
        raise AccountDecodeError("invalid total fee basis points")
    return result


def _tiers(reader: _Reader) -> list[dict[str, Any]]:
    count = reader.integer(4)
    if count > MAX_FEE_TIERS:
        raise AccountDecodeError("fee tier count exceeds bound")
    result = []
    previous = -1
    for _ in range(count):
        threshold = reader.integer(16)
        if threshold <= previous:
            raise AccountDecodeError("fee thresholds must strictly increase")
        previous = threshold
        result.append({"market_cap_lamports_threshold": threshold, "fees": _fees(reader)})
    return result


def decode_fee_config(account: dict[str, Any]) -> dict[str, Any]:
    reader = _anchor(account, PUMP_FEES_PROGRAM, "FeeConfig")
    allocation_bytes = len(reader.data)
    if allocation_bytes not in (FEE_CONFIG_PRE_STABLE_BYTES, FEE_CONFIG_POST_STABLE_BYTES, FEE_CONFIG_CURRENT_BYTES):
        raise AccountDecodeError("unsupported fee config allocation version")
    result = {"kind": "pump_fee_config", "bump": reader.integer(1), "admin": reader.key(), "flat_fees": _fees(reader)}
    result["fee_tiers"] = _tiers(reader)
    # The program gates newer fields by ACCOUNT ALLOCATION LENGTH, not by
    # remaining bytes after a dynamic vector. Unused allocation can retain
    # old nonzero tier bytes after an admin shrinks the vectors. Such bytes
    # are explicitly ignored by the official versioned reader; interpreting
    # them as a stable vector or an exotic fee would invent a fee schedule.
    result["stable_fee_tiers"] = _tiers(reader) if allocation_bytes >= FEE_CONFIG_POST_STABLE_BYTES else []
    result["exotic_flat_fees"] = _fees(reader) if allocation_bytes >= FEE_CONFIG_CURRENT_BYTES else {
        "lp_fee_bps": 0, "protocol_fee_bps": 0, "creator_fee_bps": 0}
    result.update(layout_bytes=allocation_bytes, serialized_bytes=reader.pos,
                  allocation_tail_bytes=allocation_bytes-reader.pos, warnings=[])
    return result


def _extensions(raw: bytes, base_length: int, account_type: int) -> dict[int, bytes]:
    if len(raw) == base_length:
        return {}
    if len(raw) < 166 or len(raw) == 355:
        raise AccountDecodeError("unsupported Token-2022 account length")
    if any(raw[base_length:165]) or raw[165] != account_type:
        raise AccountDecodeError("invalid Token-2022 padding or account type")
    result: dict[int, bytes] = {}
    reader = _Reader(raw[166:])
    while reader.pos < len(reader.data):
        remaining = reader.data[reader.pos:]
        if not any(remaining):
            break  # Unallocated TLV tail must be entirely zero.
        kind = reader.integer(2)
        length = reader.integer(2)
        if kind == 0 or kind in result:
            raise AccountDecodeError("invalid or duplicate token extension")
        result[kind] = reader.take(length)
        if len(result) > 64:
            raise AccountDecodeError("token extension count exceeds bound")
    return result


def _extension_size(value: bytes, expected: int) -> None:
    if len(value) != expected:
        raise AccountDecodeError("invalid token extension length")


def _optional_key(value: bytes) -> str | None:
    return b58encode(value) if any(value) else None


def _transfer_fee(value: bytes) -> dict[str, int]:
    reader = _Reader(value)
    result = {"epoch": reader.integer(8), "maximum_fee": reader.integer(8), "transfer_fee_basis_points": reader.integer(2)}
    if result["transfer_fee_basis_points"] > 10000:
        raise AccountDecodeError("invalid transfer fee basis points")
    return result


def decode_mint(account: dict[str, Any], *, epoch: int = 0) -> dict[str, Any]:
    if type(epoch) is not int or not 0 <= epoch <= U64_MAX:
        raise AccountDecodeError("invalid epoch")
    raw, owner = _account(account, (TOKEN_PROGRAM, TOKEN_2022_PROGRAM))
    if len(raw) < 82 or owner == TOKEN_PROGRAM and len(raw) != 82:
        raise AccountDecodeError("invalid SPL mint length")
    reader = _Reader(raw[:82])
    mint_authority = reader.coption(32)
    supply = reader.integer(8)
    decimals = reader.integer(1)
    initialized = reader.boolean()
    freeze_authority = reader.coption(32)
    if not initialized:
        raise AccountDecodeError("uninitialized mint")
    extensions = _extensions(raw, 82, 1) if owner == TOKEN_2022_PROGRAM else {}
    result: dict[str, Any] = {
        "kind": "mint", "token_program": owner, "supply": supply, "decimals": decimals,
        "initialized": initialized, "mint_authority": b58encode(mint_authority) if mint_authority is not None else None,
        "freeze_authority": b58encode(freeze_authority) if freeze_authority is not None else None,
        "extension_types": list(extensions), "transfer_fee": None, "transfer_fee_config": None,
        "transfer_hook": None, "permanent_delegate": None, "non_transferable": False,
        "unsupported_extensions": [], "warnings": [], "quote_supported": True,
    }
    if mint_authority is not None:
        result["warnings"].append("mint_authority_present")
    if freeze_authority is not None:
        result["warnings"].append("freeze_authority_present")
    for kind, value in extensions.items():
        if kind == 1:
            _extension_size(value, 108)
            older, newer = _transfer_fee(value[72:90]), _transfer_fee(value[90:108])
            config = {"transfer_fee_config_authority": _optional_key(value[:32]),
                      "withdraw_withheld_authority": _optional_key(value[32:64]),
                      "withheld_amount": int.from_bytes(value[64:72], "little"),
                      "older_transfer_fee": older, "newer_transfer_fee": newer}
            result["transfer_fee_config"] = config
            result["transfer_fee"] = dict(newer if epoch >= newer["epoch"] else older)
            if config["transfer_fee_config_authority"]:
                result["warnings"].append("transfer_fee_authority_present")
        elif kind == 3:
            _extension_size(value, 32)
            result["mint_close_authority"] = _optional_key(value)
            if any(value):
                result["warnings"].append("mint_close_authority_present")
        elif kind == 6:
            _extension_size(value, 1)
            if value[0] not in (1, 2):
                raise AccountDecodeError("invalid default token state")
            result["default_account_state"] = value[0]
            if value[0] == 2:
                result["warnings"].append("default_accounts_frozen")
                result["quote_supported"] = False
        elif kind == 9:
            _extension_size(value, 0)
            result["non_transferable"] = True
            result["warnings"].append("non_transferable")
            result["quote_supported"] = False
        elif kind == 12:
            _extension_size(value, 32)
            result["permanent_delegate"] = _optional_key(value)
            if any(value):
                result["warnings"].append("permanent_delegate_present")
        elif kind == 14:
            _extension_size(value, 64)
            result["transfer_hook"] = {"authority": _optional_key(value[:32]), "program_id": _optional_key(value[32:])}
            if any(value):
                result["warnings"].append("transfer_hook_requires_review")
                result["quote_supported"] = False
        elif kind in (18, 20, 22):  # Metadata/group pointer, no transfer semantics.
            _extension_size(value, 64)
        elif kind == 19:
            # Variable Borsh token metadata is not needed for quotes, but all
            # declared strings/vector entries must fit and consume the payload.
            meta = _Reader(value)
            meta.take(64)
            for _ in range(3):
                meta.take(meta.integer(4))
            count = meta.integer(4)
            if count > 256:
                raise AccountDecodeError("metadata entry count exceeds bound")
            for _ in range(count * 2):
                meta.take(meta.integer(4))
            if meta.pos != len(value):
                raise AccountDecodeError("unknown token metadata layout")
        else:
            result["unsupported_extensions"].append(kind)
            result["warnings"].append("unsupported_mint_extension_" + str(kind))
            result["quote_supported"] = False
    return result


def decode_token_account(account: dict[str, Any], *, expected_mint: str | None = None,
                         expected_owner: str | None = None, expected_program: str | None = None) -> dict[str, Any]:
    raw, program = _account(account, (TOKEN_PROGRAM, TOKEN_2022_PROGRAM))
    if expected_program is not None and expected_program != program:
        raise AccountDecodeError("token program mismatch")
    if len(raw) < 165 or program == TOKEN_PROGRAM and len(raw) != 165:
        raise AccountDecodeError("invalid SPL token account length")
    reader = _Reader(raw[:165])
    mint, owner, amount = reader.key(), reader.key(), reader.integer(8)
    delegate = reader.coption(32)
    state = reader.integer(1)
    native = reader.coption(8)
    delegated_amount = reader.integer(8)
    close_authority = reader.coption(32)
    if state not in (1, 2):
        raise AccountDecodeError("uninitialized or invalid token account state")
    if expected_mint is not None:
        pubkey_bytes(expected_mint)
        if mint != expected_mint:
            raise AccountDecodeError("token mint mismatch")
    if expected_owner is not None:
        pubkey_bytes(expected_owner)
        if owner != expected_owner:
            raise AccountDecodeError("token authority mismatch")
    extensions = _extensions(raw, 165, 2) if program == TOKEN_2022_PROGRAM else {}
    warnings = ["token_account_frozen"] if state == 2 else []
    result = {"kind": "token_account", "token_program": program, "mint": mint, "owner": owner,
              "amount": amount, "state": state, "frozen": state == 2, "delegate": b58encode(delegate) if delegate is not None else None,
              "delegated_amount": delegated_amount, "native_reserve": int.from_bytes(native, "little") if native is not None else None,
              "close_authority": b58encode(close_authority) if close_authority is not None else None,
              "extension_types": list(extensions), "withheld_amount": 0, "warnings": warnings,
              "quote_supported": state == 1, "unsupported_extensions": []}
    for kind, value in extensions.items():
        if kind == 2:
            _extension_size(value, 8)
            result["withheld_amount"] = int.from_bytes(value, "little")
        elif kind in (7, 13):
            _extension_size(value, 0)
            if kind == 13:
                warnings.append("non_transferable_account")
                result["quote_supported"] = False
        elif kind in (8, 11, 15):
            _extension_size(value, 1)
            if value[0] not in (0, 1):
                raise AccountDecodeError("invalid token extension boolean")
            if value[0]:
                warnings.append({8: "memo_required", 11: "cpi_guard_enabled", 15: "transfer_in_progress"}[kind])
                result["quote_supported"] = False
        else:
            result["unsupported_extensions"].append(kind)
            warnings.append("unsupported_account_extension_" + str(kind))
            result["quote_supported"] = False
    return result
