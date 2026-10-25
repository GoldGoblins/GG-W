from __future__ import annotations

import base64
import time
from typing import Any

from backend.crypto_keys import b58decode, b58encode, load_test_pubkey, sign_message

SYSTEM_PROGRAM = b"\x00" * 32


class ConfirmationError(RuntimeError):
    def __init__(self, txid: str, status: str):
        super().__init__("CRYPTO_TX_" + status.upper())
        self.txid = txid
        self.status = status


def compact_u16(value: int) -> bytes:
    n = int(value)
    if n < 0 or n > 0xFFFF:
        raise ValueError("CRYPTO_COMPACT")
    out = bytearray()
    while True:
        elem = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(elem)
            break
        out.append(elem | 0x80)
    return bytes(out)


def transfer_data(lamports: int) -> bytes:
    return (2).to_bytes(4, "little") + int(lamports).to_bytes(8, "little")


def build_transfer_message(
    from_pub: bytes,
    to_pub: bytes,
    lamports: int,
    recent_blockhash: bytes,
) -> bytes:
    if len(from_pub) != 32 or len(to_pub) != 32 or len(recent_blockhash) != 32:
        raise ValueError("CRYPTO_KEYS")
    same = from_pub == to_pub
    if same:
        keys = from_pub + SYSTEM_PROGRAM
        header = bytes([1, 0, 1])
        accounts = bytes([0, 0])
        program_index = 1
    else:
        keys = from_pub + to_pub + SYSTEM_PROGRAM
        header = bytes([1, 0, 1])
        accounts = bytes([0, 1])
        program_index = 2
    data = transfer_data(lamports)
    ix = bytes([program_index]) + compact_u16(len(accounts)) + accounts + compact_u16(len(data)) + data
    nkeys = 2 if same else 3
    return header + compact_u16(nkeys) + keys + recent_blockhash + compact_u16(1) + ix


def signed_transfer_bytes(
    from_pub: bytes,
    to_pub: bytes,
    lamports: int,
    recent_blockhash: bytes,
) -> bytes:
    message = build_transfer_message(from_pub, to_pub, lamports, recent_blockhash)
    sig = sign_message(message)
    return compact_u16(1) + sig + message


def confirm_signature(rpc_call, sig: str, timeout_s: float = 8.0) -> bool:
    token = str(sig or "")
    if not token:
        return False
    deadline = time.monotonic() + max(0.2, float(timeout_s))
    while time.monotonic() < deadline:
        payload = rpc_call(
            "getSignatureStatuses",
            [[token], {"searchTransactionHistory": True}],
        )
        result = payload.get("result") if isinstance(payload, dict) else None
        value = result.get("value") if isinstance(result, dict) else None
        if isinstance(value, list) and value and isinstance(value[0], dict):
            row = value[0]
            if row.get("err"):
                raise ConfirmationError(token, "failed")
            status = str(row.get("confirmationStatus") or "")
            if status in ("confirmed", "finalized"):
                return True
        time.sleep(0.25)
    return False


def _pad32(raw: bytes) -> bytes:
    if len(raw) < 32:
        return (b"\x00" * (32 - len(raw))) + raw
    if len(raw) > 32:
        return raw[-32:]
    return raw


def send_self_transfer(rpc_call, lamports: int, *, expected_pubkey: str | None = None) -> dict[str, Any]:
    if isinstance(lamports, bool) or not isinstance(lamports, int) or not 0 < lamports < 2**64:
        raise ValueError("CRYPTO_SIGNAL_SIZE")
    pubkey = load_test_pubkey()
    if not pubkey:
        raise RuntimeError("CRYPTO_NO_SIGNER")
    if expected_pubkey is not None and str(expected_pubkey) != pubkey:
        raise RuntimeError("CRYPTO_SIGNER_MISMATCH")
    from_pub = _pad32(b58decode(pubkey))
    last_fault = "CRYPTO_RPC"
    for attempt in range(6):
        payload = rpc_call(
            "getLatestBlockhash",
            [{"commitment": "confirmed"}],
        )
        if not isinstance(payload, dict):
            last_fault = "CRYPTO_RPC"
            time.sleep(0.2)
            continue
        if payload.get("error"):
            last_fault = "CRYPTO_BLOCKHASH"
            time.sleep(0.2)
            continue
        result = payload.get("result")
        value = result.get("value") if isinstance(result, dict) else None
        blockhash = str((value or {}).get("blockhash") or "")
        if not blockhash:
            last_fault = "CRYPTO_BLOCKHASH"
            time.sleep(0.2)
            continue
        raw_hash = _pad32(b58decode(blockhash))
        tx = signed_transfer_bytes(from_pub, from_pub, int(lamports), raw_hash)
        encoded = base64.b64encode(tx).decode("ascii")
        sent = rpc_call(
            "sendTransaction",
            [
                encoded,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "maxRetries": 5,
                    "preflightCommitment": "confirmed",
                },
            ],
        )
        if not isinstance(sent, dict):
            # The server may have accepted it. Never re-sign an ambiguous send.
            raise ConfirmationError(b58encode(tx[1:65]), "unconfirmed")
        if sent.get("error"):
            fault = sent["error"]
            msg = str(fault.get("message") if isinstance(fault, dict) else fault)
            last_fault = msg
            if "blockhash" in msg.lower() and attempt < 5:
                continue
            raise RuntimeError(msg)
        sig = str(sent.get("result") or "")
        if not sig:
            raise ConfirmationError(b58encode(tx[1:65]), "unconfirmed")
        if not confirm_signature(rpc_call, sig):
            checked = rpc_call("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
            values = ((checked or {}).get("result") or {}).get("value") or []
            state = "failed" if values and isinstance(values[0], dict) and values[0].get("err") else "unconfirmed"
            last_height = (value or {}).get("lastValidBlockHeight")
            if state == "unconfirmed" and last_height is not None:
                height = rpc_call("getBlockHeight", [{"commitment": "confirmed"}])
                if isinstance((height or {}).get("result"), int) and height["result"] > int(last_height):
                    state = "expired"
            raise ConfirmationError(sig, state)
        return {
            "status": "confirmed",
            "txid": sig,
            "wallet": pubkey,
            "blockhash": blockhash,
            "lamports": int(lamports),
        }
    raise RuntimeError(last_fault)
