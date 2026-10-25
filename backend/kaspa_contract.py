"""Kaspa desk laws. Paper or local testnet. Mainnet is observe-only."""

from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.crypto_contract import write_state_json, read_state_json

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path(str(STATE_ROOT / 'kaspa'))
NETWORK_DEFAULT = "paper"
RPC_ALLOWLIST = {
    "paper": "",
    "testnet": "http://127.0.0.1:16210",
    "mainnet": "https://api.kaspa.org",
}
SOMPI_PER_KAS = 100_000_000
HUMAN_ERROR = {
    "MAINNET_NOT_ARMED": "Mainnet is observe-only. Paper and testnet still run.",
    "MAINNET_OBSERVE_ONLY": "Mainnet is observe-only. Paper and testnet still run.",
    "KASPA_NETWORK": "Unknown Kaspa network.",
    "KASPA_AMOUNT": "Amount must be a positive integer.",
    "KASPA_COUNT": "Counter cannot go below zero.",
    "KASPA_SILVERC": "silverc is not installed.",
}


def ensure_state_dir() -> Path:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return STATE_DIR


def human_error(code: str) -> str:
    return HUMAN_ERROR.get(code, code)


def format_kas(sompi: int | None) -> str:
    if sompi is None:
        return "—"
    try:
        n = int(sompi)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if n < 0 else ""
    n = abs(n)
    whole, frac = divmod(n, SOMPI_PER_KAS)
    return sign + str(whole) + "." + f"{frac:08d}"


def load_json(name: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    path = ensure_state_dir() / name
    try:
        payload = read_state_json(path, max_bytes=1024 * 1024)
    except FileNotFoundError:
        return dict(default or {})
    except (OSError, ValueError):
        raise ValueError('KASPA_STATE_CORRUPT') from None
    return payload


def save_json(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = ensure_state_dir() / name
    write_state_json(path, payload)
    return payload


def load_network() -> str:
    chain = str(load_json("network.json").get("network") or NETWORK_DEFAULT)
    if chain not in RPC_ALLOWLIST:
        return NETWORK_DEFAULT
    return chain


def save_network(network: str) -> str:
    chain = str(network or "").strip().lower()
    if chain not in RPC_ALLOWLIST:
        raise ValueError("KASPA_NETWORK")
    save_json("network.json", {"network": chain})
    return chain
