from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from backend.crypto_contract import ensure_state_dir

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
KEYPAIR_NAME = "test-keypair.json"
LIVE_KEYPAIR_NAME = "live-keypair.json"
PEM_NAME = "test-keypair.pem"


def keypair_path() -> Path:
    return ensure_state_dir() / KEYPAIR_NAME


def pem_path() -> Path:
    return ensure_state_dir() / PEM_NAME


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58[rem] + out
    pad = 0
    for byte in raw:
        if byte == 0:
            pad += 1
        else:
            break
    if not out:
        return "1" * (pad or 1)
    return ("1" * pad) + out


def b58decode(value: str) -> bytes:
    text = str(value or "")
    n = 0
    for char in text:
        idx = _B58.find(char)
        if idx < 0:
            raise ValueError("CRYPTO_B58")
        n = n * 58 + idx
    raw = n.to_bytes((n.bit_length() + 7) // 8 or 1, "big") if n else b""
    pad = 0
    for char in text:
        if char == "1":
            pad += 1
        else:
            break
    return (b"\x00" * pad) + raw


def _run_openssl(*args: str) -> bytes:
    argv = ["openssl", *args]
    return subprocess.check_output(argv, stderr=subprocess.DEVNULL)


def generate_ed25519() -> tuple[bytes, bytes, bytes]:
    der = _run_openssl("genpkey", "-algorithm", "ED25519", "-outform", "DER")
    marker = bytes([0x04, 0x20])
    idx = der.find(marker)
    if idx < 0 or idx + 34 > len(der):
        raise RuntimeError("CRYPTO_OPENSSL_SEED")
    seed = der[idx + 2 : idx + 34]
    pem = subprocess.run(
        ["openssl", "pkey", "-inform", "DER", "-outform", "PEM"],
        input=der,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    ).stdout
    pub_der = subprocess.run(
        ["openssl", "pkey", "-pubout", "-outform", "DER"],
        input=pem,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    ).stdout
    if len(pub_der) < 32:
        raise RuntimeError("CRYPTO_OPENSSL_PUB")
    pub = pub_der[-32:]
    return seed, pub, pem


def save_test_keypair(seed: bytes, pub: bytes, pem: bytes) -> str:
    ensure_state_dir()
    secret = seed + pub
    path = keypair_path()
    path.write_text(json.dumps(list(secret)) + "\n", encoding="utf-8")
    path.chmod(0o600)
    pem_file = pem_path()
    pem_file.write_bytes(pem)
    pem_file.chmod(0o600)
    return b58encode(pub)


def _pubkey_from_keypair_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, list) or len(data) < 64:
        return ""
    pub = bytes(int(x) & 0xFF for x in data[32:64])
    return b58encode(pub)


def load_test_pubkey() -> str:
    live = _pubkey_from_keypair_file(live_keypair_path())
    if live:
        return live
    return _pubkey_from_keypair_file(keypair_path())


def live_keypair_path() -> Path:
    return ensure_state_dir() / LIVE_KEYPAIR_NAME


def has_signer() -> bool:
    return keypair_path().is_file() or live_keypair_path().is_file()


def import_solana_keypair(path: str) -> str:
    target = Path(path)
    if not target.is_file():
        raise ValueError("CRYPTO_KEYPAIR_MISSING")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("CRYPTO_KEYPAIR_JSON") from exc
    if not isinstance(data, list) or len(data) < 64:
        raise ValueError("CRYPTO_KEYPAIR_JSON")
    secret = [int(x) & 0xFF for x in data[:64]]
    dest = live_keypair_path()
    dest.write_text(json.dumps(secret) + "\n", encoding="utf-8")
    dest.chmod(0o600)
    pub = bytes(secret[32:64])
    return b58encode(pub)


def ensure_test_wallet() -> str:
    existing = load_test_pubkey()
    if existing:
        return existing
    seed, pub, pem = generate_ed25519()
    return save_test_keypair(seed, pub, pem)


def _pem_from_seed(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise RuntimeError("CRYPTO_SEED")
    der = bytes.fromhex("302e020100300506032b657004220420") + seed
    return subprocess.run(
        ["openssl", "pkey", "-inform", "DER", "-outform", "PEM"],
        input=der,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    ).stdout


def signer_pem_bytes() -> bytes:
    live = live_keypair_path()
    if live.is_file():
        data = json.loads(live.read_text(encoding="utf-8"))
        seed = bytes(int(x) & 0xFF for x in data[:32])
        return _pem_from_seed(seed)
    pem = pem_path()
    if pem.is_file():
        return pem.read_bytes()
    path = keypair_path()
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        seed = bytes(int(x) & 0xFF for x in data[:32])
        return _pem_from_seed(seed)
    raise RuntimeError("CRYPTO_NO_SIGNER")


def sign_message(message: bytes) -> bytes:
    pem = signer_pem_bytes()
    key_fd, key_path = tempfile.mkstemp(prefix="gg-ed25519-")
    msg_fd, msg_path = tempfile.mkstemp(prefix="gg-ed25519-msg-")
    try:
        os.write(key_fd, pem)
        os.close(key_fd)
        os.chmod(key_path, 0o600)
        os.write(msg_fd, message)
        os.close(msg_fd)
        sig = subprocess.check_output(
            ["openssl", "pkeyutl", "-sign", "-inkey", key_path, "-rawin", "-in", msg_path],
            stderr=subprocess.DEVNULL,
        )
    finally:
        for item in (key_path, msg_path):
            try:
                os.unlink(item)
            except OSError:
                pass
    if len(sig) != 64:
        raise RuntimeError("CRYPTO_SIG")
    return sig
