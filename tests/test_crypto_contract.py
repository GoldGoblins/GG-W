#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import crypto_contract


def main() -> int:
    src = (PROJECT / "backend" / "crypto_contract.py").read_text(encoding="utf-8")
    host_src = (PROJECT / "backend" / "crypto_host.py").read_text(encoding="utf-8")
    if "CXk2AMBfi3TwaEL2468s6zP8xq9NxTXjp9gjMgzeUynM" not in host_src:
        raise AssertionError("PYUSD mint missing")
    if "api.devnet.solana.com" not in src:
        raise AssertionError("public devnet RPC string missing")
    if "127.0.0.1:8899" not in src:
        raise AssertionError("local lab RPC missing")
    if "format_units" not in src:
        raise AssertionError("exact unit format missing")
    if '"testnet"' not in src or '"mainnet"' not in src:
        raise AssertionError("need testnet and mainnet only")
    if "127.0.0.1" in src and "webhook" in src and "0.0.0.0" in src:
        raise AssertionError("open bind not allowed in slice 1")
    tmp = Path(tempfile.mkdtemp(prefix="gg-crypto-"))
    crypto_contract.STATE_DIR = tmp
    try:
        crypto_contract.validate_pubkey("bad")
        raise AssertionError("invalid pubkey accepted")
    except ValueError:
        pass
    key = "11111111111111111111111111111111"
    parsed = crypto_contract.parse_signal(
        '{"side":"buy","size_sol":0.01,"symbol":"SOL","source":"tv"}'
    )
    if crypto_contract.format_units(100000000, 6) != "100.000000":
        raise AssertionError("pyusd 6 dp")
    if crypto_contract.format_units(1, 8) != "0.00000001":
        raise AssertionError("8 dp")
    if crypto_contract.format_units(1, 16) != "0.0000000000000001":
        raise AssertionError("16 dp")
    if crypto_contract.format_sol(100999980000) != "100.999980000":
        raise AssertionError("format_sol fees " + crypto_contract.format_sol(100999980000))
    if crypto_contract.format_sol(101000000000) != "101.000000000":
        raise AssertionError("format_sol 101")
    if parsed["mode"] != "TESTNET":
        raise AssertionError("testnet default")
    if crypto_contract.human_error("LAB_OFF") != crypto_contract.ERROR_HINTS["LAB_OFF"]:
        raise AssertionError("human_error LAB_OFF")
    if crypto_contract.short_error("-32603 Internal error") != "AIRDROP_FAIL":
        raise AssertionError("short -32603")
    decorated = crypto_contract.decorate_ledger_row(
        {"txid": "NONE", "error": "LAB_OFF"}
    )
    if "Start LAB first" not in str(decorated.get("hint") or ""):
        raise AssertionError("decorate hint")
    if crypto_contract.load_proven()["ready"]:
        raise AssertionError("empty proven ready")
    crypto_contract.mark_proven("lab")
    if not crypto_contract.load_proven()["lab"]:
        raise AssertionError("mark lab")
    wallet = crypto_contract.save_wallet(key, 0)
    if not wallet["connected"]:
        raise AssertionError("wallet not connected")
    if "WALLET ·" not in wallet["label"]:
        raise AssertionError("label " + wallet["label"])
    crypto_contract.append_ledger({"txid": "PAPER", "mode": "PAPER"})
    rows = crypto_contract.read_ledger()
    if not rows or rows[-1]["txid"] != "PAPER":
        raise AssertionError("ledger")
    from backend import crypto_keys
    from backend import crypto_tx

    if crypto_keys.b58encode(crypto_keys.b58decode("11111111111111111111111111111111")) != "11111111111111111111111111111111":
        raise AssertionError("b58 system program")
    if crypto_tx.compact_u16(1) != b"\x01":
        raise AssertionError("compact")
    if crypto_tx.transfer_data(1)[0:4] != (2).to_bytes(4, "little"):
        raise AssertionError("transfer ix")
    pub = crypto_keys.ensure_test_wallet()
    if len(pub) < 32:
        raise AssertionError("test pubkey " + pub)
    if not crypto_keys.has_signer():
        raise AssertionError("signer missing")
    copy = tmp / "import.json"
    copy.write_text((tmp / "test-keypair.json").read_text(encoding="utf-8"))
    imported = crypto_keys.import_solana_keypair(str(copy))
    if imported != pub:
        raise AssertionError("import pubkey mismatch")
    print("CRYPTO_CONTRACT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
