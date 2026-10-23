"""Paper Kaspa covenant desk: Counter state in a successor UTXO.

This is the Solana-lab analog for Kaspa. It does not copy the account model.
Covenant steps always run as paper. Mainnet is observe-only.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from backend import kaspa_contract as C


SCHEMA = "gg.kaspa-covenant.v1"
ACTION_AUTHORITY = "NONE"
COUNTER_SIL = (
    Path(__file__).resolve().parents[1] / "kaspa" / "counter.sil"
)
PAPER_FUND_SOMPI = 1 * C.SOMPI_PER_KAS


def _blake2b(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=32).hexdigest()


def _now() -> int:
    return int(time.time())


def _empty() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "contract": "Counter",
        "count": 0,
        "covenant_id": "",
        "address": "",
        "value_sompi": 0,
        "value_kas": C.format_kas(0),
        "history": [],
        "compiled": False,
        "bytecode_bytes": 0,
        "compile_note": "",
    }


def load_state() -> dict[str, Any]:
    row = C.load_json("covenant.json", _empty())
    row.setdefault("history", [])
    return row


def _address(count: int, covenant_id: str) -> str:
    digest = _blake2b(f"Counter|{count}|{covenant_id}".encode("utf-8"))
    return "paper:" + digest[:20]


def _write(state: dict[str, Any]) -> dict[str, Any]:
    state["value_kas"] = C.format_kas(int(state.get("value_sompi") or 0))
    state["schema"] = SCHEMA
    C.save_json("covenant.json", state)
    return snapshot()


def lab_status() -> dict[str, Any]:
    silverc = shutil.which("silverc") or ""
    kaspad = shutil.which("kaspad") or shutil.which("kaspa") or ""
    sdk = False
    try:
        import kaspa  # noqa: F401

        sdk = True
    except Exception:
        sdk = False
    return {
        "silverc": bool(silverc),
        "silverc_path": silverc,
        "node_bin": bool(kaspad),
        "sdk": sdk,
        "label": "SILVERC ON" if silverc else "SILVERC OFF",
        "rpc": C.RPC_ALLOWLIST.get(C.load_network(), ""),
    }


def snapshot() -> dict[str, Any]:
    chain = C.load_network()
    state = load_state()
    legend = "OBSERVE" if chain == "mainnet" else ("PAPER" if chain == "paper" else "TESTNET")
    return {
        "schema": SCHEMA,
        "network": chain,
        "legend": legend,
        "rpc": C.RPC_ALLOWLIST.get(chain, ""),
        "mainnet_armed": False,
        "mainnet_observe": chain == "mainnet",
        "action_authority": ACTION_AUTHORITY,
        "contract": state.get("contract") or "Counter",
        "source": str(COUNTER_SIL) if COUNTER_SIL.is_file() else "",
        "count": int(state.get("count") or 0),
        "covenant_id": str(state.get("covenant_id") or ""),
        "address": str(state.get("address") or ""),
        "value_sompi": int(state.get("value_sompi") or 0),
        "value_kas": state.get("value_kas") or C.format_kas(0),
        "history": list(state.get("history") or [])[-8:],
        "compiled": bool(state.get("compiled")),
        "bytecode_bytes": int(state.get("bytecode_bytes") or 0),
        "compile_note": str(state.get("compile_note") or ""),
        "lab": lab_status(),
        "hint": "UTXO successor, not an account. Covenant id stays; address changes with count.",
    }


def set_network(network: str) -> dict[str, Any]:
    C.save_network(network)
    return snapshot()


def genesis(*, value_sompi: int = PAPER_FUND_SOMPI) -> dict[str, Any]:
    try:
        amount = int(value_sompi)
    except (TypeError, ValueError) as exc:
        raise ValueError("KASPA_AMOUNT") from exc
    if amount <= 0:
        raise ValueError("KASPA_AMOUNT")
    covenant_id = _blake2b(f"genesis|{_now()}|{amount}".encode("utf-8"))
    state = {
        **_empty(),
        "count": 0,
        "covenant_id": covenant_id,
        "address": _address(0, covenant_id),
        "value_sompi": amount,
        "compiled": load_state().get("compiled") or False,
        "bytecode_bytes": load_state().get("bytecode_bytes") or 0,
        "compile_note": load_state().get("compile_note") or "",
        "history": [
            {
                "ts": _now(),
                "op": "genesis",
                "count": 0,
                "note": "paper Counter count=0",
            }
        ],
    }
    return _write(state)


def transition(function: str, amount: int) -> dict[str, Any]:
    fn = str(function or "").strip().lower()
    try:
        delta = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("KASPA_AMOUNT") from exc
    if delta <= 0:
        raise ValueError("KASPA_AMOUNT")
    state = load_state()
    if not state.get("covenant_id"):
        genesis()
        state = load_state()
    count = int(state.get("count") or 0)
    if fn == "add":
        count = count + delta
    elif fn == "subtract":
        if count - delta < 0:
            raise ValueError("KASPA_COUNT")
        count = count - delta
    else:
        raise ValueError("KASPA_AMOUNT")
    history = list(state.get("history") or [])
    history.append(
        {
            "ts": _now(),
            "op": fn,
            "amount": delta,
            "count": count,
            "note": fn + "(" + str(delta) + ")",
        }
    )
    state["count"] = count
    state["address"] = _address(count, str(state.get("covenant_id") or ""))
    state["history"] = history[-24:]
    return _write(state)


def compile_counter() -> dict[str, Any]:
    lab = lab_status()
    if not lab.get("silverc"):
        state = load_state()
        state["compiled"] = False
        state["compile_note"] = C.human_error("KASPA_SILVERC")
        _write(state)
        snap = snapshot()
        snap["error"] = "KASPA_SILVERC"
        snap["hint"] = C.human_error("KASPA_SILVERC")
        return snap
    if not COUNTER_SIL.is_file():
        raise FileNotFoundError("counter.sil")
    args = [{"kind": "int", "value": 0}]
    with tempfile.TemporaryDirectory(prefix="gg-silverc-") as tmp:
        work = Path(tmp)
        src = work / "counter.sil"
        ctor = work / "args.json"
        out = work / "counter.json"
        src.write_text(COUNTER_SIL.read_text(encoding="utf-8"), encoding="utf-8")
        ctor.write_text(json.dumps(args), encoding="utf-8")
        proc = subprocess.run(
            [
                str(lab["silverc_path"]),
                str(src),
                "--constructor-args",
                str(ctor),
                "-o",
                str(out),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode != 0 or not out.is_file():
            state = load_state()
            state["compiled"] = False
            state["compile_note"] = (proc.stderr or proc.stdout or "compile failed")[:180]
            _write(state)
            snap = snapshot()
            snap["error"] = "KASPA_COMPILE"
            snap["hint"] = state["compile_note"]
            return snap
        artifact = json.loads(out.read_text(encoding="utf-8"))
    script = ""
    contracts = artifact.get("contracts") if isinstance(artifact, dict) else None
    if isinstance(contracts, dict):
        first = next(iter(contracts.values()), {})
        compiled = first.get("compiled") if isinstance(first, dict) else {}
        if isinstance(compiled, dict):
            script = str(compiled.get("bytecode") or compiled.get("script") or "")
    state = load_state()
    state["compiled"] = True
    state["bytecode_bytes"] = max(0, len(script) // 2)
    state["compile_note"] = "silverc ok, " + str(state["bytecode_bytes"]) + " bytes"
    _write(state)
    return snapshot()
