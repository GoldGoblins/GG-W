from __future__ import annotations

from backend.application_paths import STATE_ROOT

import json
import math
import re
import os
import threading
import time
import uuid
from functools import wraps
from pathlib import Path
from typing import Any

from backend.platform_files import atomic_replace, secure_open, set_private_mode, sync_directory

STATE_DIR = Path(str(STATE_ROOT / 'crypto'))
LEDGER_NAME = "ledger.jsonl"
WALLET_NAME = "wallet.json"
ACCOUNTS_NAME = "accounts.json"
NETWORK_DEFAULT = "testnet"
PUBLIC_DEVNET = "https://api.devnet.solana.com"
RPC_ALLOWLIST = {
    "testnet": "http://127.0.0.1:8899",
    "mainnet": "https://api.mainnet-beta.solana.com",
}
_PUBKEY = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_SIDES = ("buy", "sell")
_state_lock = threading.RLock()
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_LEDGER_READ_BYTES = 1024 * 1024


def _serialized(action):
    @wraps(action)
    def run(*args, **kwargs):
        with _state_lock:
            return action(*args, **kwargs)
    return run


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Prepare a complete private record before changing the active state."""
    data = (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".new")
    try:
        descriptor = secure_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        set_private_mode(temporary, 0o600)
        atomic_replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_state_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish a complete private crypto state/cache record."""
    _write_json(path, payload)


def read_state_json(path: Path, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    """Read one bounded complete state record; callers handle a missing file."""
    with path.open('rb') as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('CRYPTO_STATE_TOO_LARGE')
    def nonfinite(_value):
        raise ValueError('CRYPTO_STATE_CORRUPT')
    try:
        value = json.loads(raw.decode('utf-8'), parse_constant=nonfinite)
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError('CRYPTO_STATE_CORRUPT') from None
    if not isinstance(value, dict):
        raise ValueError('CRYPTO_STATE_CORRUPT')
    return value


def ensure_state_dir() -> Path:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return STATE_DIR


def wallet_path() -> Path:
    return ensure_state_dir() / WALLET_NAME


def ledger_path() -> Path:
    return ensure_state_dir() / LEDGER_NAME


def validate_pubkey(value: str) -> str:
    key = str(value or "").strip()
    if not _PUBKEY.fullmatch(key):
        raise ValueError("CRYPTO_PUBKEY_INVALID")
    number = 0
    for character in key:
        number = number * 58 + _B58_ALPHABET.index(character)
    padding = len(key) - len(key.lstrip("1"))
    if padding + (number.bit_length() + 7) // 8 != 32:
        raise ValueError("CRYPTO_PUBKEY_INVALID")
    return key


def parse_signal(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(str(raw or ""))
        except json.JSONDecodeError as exc:
            raise ValueError("CRYPTO_SIGNAL_JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("CRYPTO_SIGNAL_JSON")
    side = str(payload.get("side") or "").strip().lower()
    if side not in _SIDES:
        raise ValueError("CRYPTO_SIGNAL_SIDE")
    if isinstance(payload.get("size_sol"), bool):
        raise ValueError("CRYPTO_SIGNAL_SIZE")
    try:
        size = float(payload.get("size_sol"))
    except (TypeError, ValueError) as exc:
        raise ValueError("CRYPTO_SIGNAL_SIZE") from exc
    if not math.isfinite(size) or size <= 0 or size > 1000:
        raise ValueError("CRYPTO_SIGNAL_SIZE")
    symbol = str(payload.get("symbol") or "SOL").strip()[:24] or "SOL"
    source = str(payload.get("source") or "manual").strip()[:40] or "manual"
    return {
        "side": side,
        "size_sol": size,
        "symbol": symbol,
        "source": source,
        "network": NETWORK_DEFAULT,
        "mode": "TESTNET",
    }


SOL_DECIMALS = 9


def format_units(amount: int | str | None, decimals: int) -> str:
    if amount is None:
        return "—"
    try:
        n = int(amount)
        places = int(decimals)
    except (TypeError, ValueError):
        return "—"
    if places < 0 or places > 18:
        return "—"
    sign = "-" if n < 0 else ""
    n = abs(n)
    if places == 0:
        return sign + str(n)
    scale = 10 ** places
    whole, frac = divmod(n, scale)
    return sign + str(whole) + "." + f"{frac:0{places}d}"


def format_sol(lamports: int | None) -> str:
    return format_units(lamports, SOL_DECIMALS)


def short_pubkey(value: str) -> str:
    key = str(value or "")
    if len(key) < 8:
        return key or "DISCONNECTED"
    return key[:4] + "…" + key[-4:]


def load_network() -> str:
    path = ensure_state_dir() / "network.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        chain = str(payload.get("network") or NETWORK_DEFAULT)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return NETWORK_DEFAULT
    if chain in ("paper", "devnet", "localnet"):
        chain = "testnet"
    if chain not in RPC_ALLOWLIST:
        return NETWORK_DEFAULT
    return chain


@_serialized
def save_network(network: str) -> str:
    chain = str(network or "").strip().lower()
    if chain in ("paper", "devnet", "localnet"):
        chain = "testnet"
    if chain not in RPC_ALLOWLIST:
        raise ValueError("CRYPTO_NETWORK_INVALID")
    path = ensure_state_dir() / "network.json"
    _write_json(path, {"network": chain})
    return chain


def load_wallet() -> dict[str, Any]:
    path = wallet_path()
    if not path.is_file():
        return {
            "connected": False,
            "pubkey": "",
            "label": "WALLET · DISCONNECTED",
            "network": NETWORK_DEFAULT,
            "mode": "TESTNET",
            "balance_lamports": None,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    pubkey = str(payload.get("pubkey") or "")
    connected = bool(pubkey)
    return {
        "connected": connected,
        "pubkey": pubkey,
        "label": (
            "WALLET · " + short_pubkey(pubkey)
            if connected
            else "WALLET · DISCONNECTED"
        ),
        "network": str(payload.get("network") or NETWORK_DEFAULT),
        "mode": "TESTNET" if (payload.get("network") or NETWORK_DEFAULT) != "mainnet" else "LIVE",
        "balance_lamports": payload.get("balance_lamports"),
    }


@_serialized
def save_wallet(
    pubkey: str,
    balance_lamports: int | None = None,
    network: str | None = None,
) -> dict[str, Any]:
    key = validate_pubkey(pubkey)
    current = load_wallet()
    chain = str(network or current.get("network") or load_network() or NETWORK_DEFAULT)
    if chain in ("paper", "devnet", "localnet"):
        chain = "testnet"
    if chain not in RPC_ALLOWLIST:
        chain = NETWORK_DEFAULT
    payload = {
        "pubkey": key,
        "network": chain,
        "mode": "TESTNET" if chain != "mainnet" else "LIVE",
        "balance_lamports": balance_lamports,
    }
    path = wallet_path()
    _write_json(path, payload)
    remember_account(key)
    return load_wallet()


def _accounts_path() -> Path:
    return ensure_state_dir() / ACCOUNTS_NAME


def load_accounts() -> list[dict[str, Any]]:
    path = _accounts_path()
    rows: list[dict[str, Any]] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = {}
    raw = payload.get("accounts") if isinstance(payload, dict) else payload
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("pubkey") or "")
            if not key:
                continue
            rows.append({"pubkey": key})
    active = str(load_wallet().get("pubkey") or "")
    if active and not any(row["pubkey"] == active for row in rows):
        rows.insert(0, {"pubkey": active})
    return rows


@_serialized
def remember_account(pubkey: str) -> None:
    try:
        key = validate_pubkey(pubkey)
    except ValueError:
        return
    rows = load_accounts()
    if any(row["pubkey"] == key for row in rows):
        return
    rows.append({"pubkey": key})
    path = _accounts_path()
    _write_json(path, {"accounts": rows})


def account_catalog() -> list[dict[str, Any]]:
    active = str(load_wallet().get("pubkey") or "")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in load_accounts():
        key = str(row.get("pubkey") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "pubkey": key,
                "short": short_pubkey(key),
                "active": key == active,
            }
        )
    return out


@_serialized
def clear_wallet() -> dict[str, Any]:
    path = wallet_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return load_wallet()


@_serialized
def append_ledger(row: dict[str, Any]) -> dict[str, Any]:
    ensure_state_dir()
    path = ledger_path()
    line = json.dumps(row, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return row


def read_ledger(limit: int = 20) -> list[dict[str, Any]]:
    return read_journal_tail(ledger_path(), limit)


def read_journal_tail(path: Path, limit: int = 20) -> list[dict[str, Any]]:
    """Bound work by bytes and rows even when a journal keeps growing."""
    if not path.is_file():
        return []
    count = max(1, min(2000, int(limit)))
    try:
        with path.open("rb") as stream:
            size = stream.seek(0, os.SEEK_END)
            start = max(0, size - _LEDGER_READ_BYTES)
            stream.seek(start)
            tail = stream.read(_LEDGER_READ_BYTES)
        if start:
            # The first fragment may start inside a UTF-8 code point or JSON row.
            _, separator, tail = tail.partition(b"\n")
            if not separator:
                return []
        lines = tail.splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-count:]:
        try:
            item = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeError):
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


ERROR_HINTS = {
    "CRYPTO_SIGNER_MISMATCH": "The selected account does not match the loaded signer. No transaction was sent.",
    "CRYPTO_KEYPAIR_JSON": "The keypair is invalid or inconsistent. Existing key material was preserved.",
    "CRYPTO_OPENSSL_MISSING": "OpenSSL is unavailable. Install Git for Windows or configure GG_OPENSSL_BINARY.",
    "CRYPTO_OPENSSL_TIMEOUT": "The signing helper timed out. No transaction was sent.",
    "CRYPTO_OPENSSL_FAILED": "The signing helper failed. No transaction was sent.",
    "CRYPTO_TRADER_STATE_CORRUPT": "Saved trader state is unreadable and has been preserved for review.",
    "CRYPTO_ARB_STATE_CORRUPT": "Saved paper pool state is unreadable and has been preserved for review.",
    "CRYPTO_PAPER_STATE_CORRUPT": "Saved paper accounts are unreadable and have been preserved for review.",
    "CRYPTO_BACKTEST_STATE_CORRUPT": "The saved backtest is unreadable and has been preserved for review.",
    "CRYPTO_LAB_FOREIGN_RPC": "Another RPC service is using the lab endpoint. GG will not take it over.",
    "CRYPTO_LAB_LEDGER_REQUIRES_REVIEW": "The existing lab ledger requires review and has been preserved.",
    "CRYPTO_LAB_FROZEN_REQUIRES_REVIEW": "The validator is frozen. Its ledger was preserved; review it before resetting.",
    "CRYPTO_VALIDATOR_UNSUPPORTED_PLATFORM": "The configured validator is not a native executable for this platform.",
    "CRYPTO_TX_UNCONFIRMED": "Transaction submitted; confirmation timed out. It is not a fill.",
    "CRYPTO_TX_FAILED": "The chain reported a failed transaction.",
    "CRYPTO_TX_EXPIRED": "The transaction blockhash expired before confirmation.",
    "LAB_OFF": "Start LAB first. Local validator is off.",
    "LAB_STARTING": "Lab is still starting. Wait for LAB ON.",
    "RPC_UNREACHABLE": "Lab RPC is down. Turn LAB ON.",
    "NEED_FEE_SOL": "Too little SOL for fees. AIRDROP first.",
    "NO_SIGNER": "CREATE TEST WALLET first.",
    "MAINNET_NOT_ARMED": "Mainnet is observe-only. Sends stay on testnet/lab.",
    "MAINNET_OBSERVE_ONLY": "Mainnet is observe-only. Sends stay on testnet/lab.",
    "NO_PROFIT": "Arb reverted. Pools unchanged.",
    "TIP_EATS_EDGE": "Gross edge is smaller than the Jito tip. Bundle dropped.",
    "NO_MARKET_DATA": "Market feed quiet. EVAL needs a SOL chart.",
    "AIRDROP_FAIL": "Lab airdrop failed. Retry after LAB ON.",
    "CRYPTO_BLOCKHASH": "Lab did not give a blockhash. Retry.",
    "CRYPTO_NO_SIGNER": "CREATE TEST WALLET first.",
    "CRYPTO_RPC": "Lab RPC rejected the transaction.",
    "CRYPTO_VALIDATOR_MISSING": "solana-test-validator is not installed.",
    "CRYPTO_KLINE": "Market feed quiet. EVAL needs a SOL chart.",
    "CRYPTO_CANDLES": "Not enough candles yet. Refresh the SOL chart.",
}
PROVEN_STEPS = ("lab", "airdrop", "buy", "bot", "arb")
PROVEN_NAME = "testnet-proven.json"
_DEAD_TX = frozenset({"", "NONE", "UNSENT", "REVERT", "POOLS_ONLY", "RESET"})


def human_error(code: str | None) -> str:
    raw = str(code or "").strip()
    if not raw:
        return ""
    key = raw.split(":", 1)[-1].strip() if raw.startswith("CRYPTO_") is False else raw
    if raw in ERROR_HINTS:
        return ERROR_HINTS[raw]
    if key in ERROR_HINTS:
        return ERROR_HINTS[key]
    low = raw.lower()
    if "insufficient" in low:
        return ERROR_HINTS["NEED_FEE_SOL"]
    if "blockhash" in low:
        return ERROR_HINTS["CRYPTO_BLOCKHASH"]
    if "-32603" in raw or "internal error" in low:
        return "Lab RPC internal error. Is LAB ON?"
    if "429" in raw or "airdrop" in low and ("limit" in low or "dry" in low):
        return "Use the local lab airdrop, not a public faucet."
    if len(raw) > 80:
        return raw[:72] + "…"
    return raw


def short_error(code: str | None) -> str:
    raw = str(code or "").strip()
    if not raw:
        return ""
    if raw in ERROR_HINTS:
        return raw
    low = raw.lower()
    if "insufficient" in low:
        return "NEED_FEE_SOL"
    if "blockhash" in low:
        return "CRYPTO_BLOCKHASH"
    if "-32603" in raw or "internal error" in low:
        return "AIRDROP_FAIL"
    if raw.startswith("HTTP ") or "urlerror" in low or "unreachable" in low:
        return "RPC_UNREACHABLE"
    token = raw.split(":", 1)[0].strip()
    if token in ERROR_HINTS:
        return token
    if len(raw) > 32:
        return raw[:32]
    return raw


def decorate_ledger_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    err = out.get("error")
    if err:
        out["error"] = short_error(str(err))
        if not out.get("hint"):
            out["hint"] = human_error(str(err))
    elif not out.get("hint"):
        tx = str(out.get("txid") or "")
        if out.get("status") == "confirmed":
            out["hint"] = "Confirmed localnet diagnostic self-transfer."
        elif tx not in _DEAD_TX:
            out["hint"] = "Submitted transaction; confirmation not recorded."
        else:
            out["hint"] = "Simulated portfolio operation."
    hint = str(out.get("hint") or "")
    if "Swap path next" in hint:
        out["hint"] = "Localnet self-transfer diagnostic; no token swap."
    if "Balance not yet visible" in hint:
        out["hint"] = "Lab airdrop submitted."
    return out


def proven_path() -> Path:
    return ensure_state_dir() / PROVEN_NAME


def load_proven() -> dict[str, Any]:
    path = proven_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    out: dict[str, Any] = {step: bool(payload.get(step)) for step in PROVEN_STEPS}
    out["ready"] = all(out[step] for step in PROVEN_STEPS)
    done = sum(1 for step in PROVEN_STEPS if out[step])
    out["done"] = done
    out["total"] = len(PROVEN_STEPS)
    out["label"] = str(done) + "/" + str(len(PROVEN_STEPS))
    if payload.get("ts"):
        out["ts"] = payload.get("ts")
    return out


@_serialized
def mark_proven(step: str, txid: str | None = None) -> dict[str, Any]:
    name = str(step or "").strip().lower()
    if name not in PROVEN_STEPS:
        raise ValueError("CRYPTO_PROVEN_STEP")
    path = proven_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload[name] = True
    payload[name + "_ts"] = int(time.time())
    if txid:
        payload[name + "_txid"] = str(txid)[:88]
    payload["ready"] = all(bool(payload.get(item)) for item in PROVEN_STEPS)
    payload["ts"] = int(time.time())
    _write_json(path, payload)
    return load_proven()
