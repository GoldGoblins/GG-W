from __future__ import annotations

from backend.application_paths import STATE_ROOT

import json
import math
import re
import time
from pathlib import Path
from typing import Any

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


def save_network(network: str) -> str:
    chain = str(network or "").strip().lower()
    if chain in ("paper", "devnet", "localnet"):
        chain = "testnet"
    if chain not in RPC_ALLOWLIST:
        raise ValueError("CRYPTO_NETWORK_INVALID")
    path = ensure_state_dir() / "network.json"
    path.write_text(json.dumps({"network": chain}) + "\n", encoding="utf-8")
    path.chmod(0o600)
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
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
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
    path.write_text(
        json.dumps({"accounts": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


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


def clear_wallet() -> dict[str, Any]:
    path = wallet_path()
    try:
        path.unlink()
    except OSError:
        pass
    return load_wallet()


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
    path = ledger_path()
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


ERROR_HINTS = {
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
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return load_proven()
