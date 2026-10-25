from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from backend.crypto_contract import ensure_state_dir, validate_pubkey
from backend.platform_files import atomic_replace, secure_open, set_private_mode
from backend.platform_process import background_options
from backend.platform_support import find_executable

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
KEYPAIR_NAME = "test-keypair.json"
LIVE_KEYPAIR_NAME = "live-keypair.json"
PEM_NAME = "test-keypair.pem"
_KEYPAIR_LIMIT = 4096
_OPENSSL_TIMEOUT = 5


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


def openssl_binary() -> str:
    """Use installed OpenSSL, including Git for Windows' private tool folder."""
    override = os.environ.get("GG_OPENSSL_BINARY")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
        raise RuntimeError("CRYPTO_OPENSSL_MISSING")
    found = shutil.which("openssl")
    if found:
        return found
    if os.name == "nt":
        candidates = []
        git = find_executable("git")
        if git:
            candidates.append(Path(git).resolve().parents[1] / "usr/bin/openssl.exe")
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidates.extend(Path(base) / relative for relative in (
                    "Git/usr/bin/openssl.exe", "Programs/Git/usr/bin/openssl.exe",
                    "OpenSSL-Win64/bin/openssl.exe", "OpenSSL-Win32/bin/openssl.exe"))
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("CRYPTO_OPENSSL_MISSING")


def _run_openssl(*args: str, input_data: bytes | None = None) -> bytes:
    tool = openssl_binary()
    # Do not hand provider tokens or an arbitrary OPENSSL_CONF to this child.
    environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP")
                   if name in os.environ}
    environment["OPENSSL_CONF"] = os.devnull
    environment["PATH"] = str(Path(tool).resolve().parent)
    try:
        result = subprocess.run([tool, *args], input=input_data,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=_OPENSSL_TIMEOUT, env=environment,
                                check=True, **background_options())
    except subprocess.TimeoutExpired:
        raise RuntimeError("CRYPTO_OPENSSL_TIMEOUT") from None
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError("CRYPTO_OPENSSL_FAILED") from None
    return result.stdout


def _public_from_pem(pem: bytes) -> bytes:
    public = _run_openssl("pkey", "-pubout", "-outform", "DER", input_data=pem)
    prefix = bytes.fromhex("302a300506032b6570032100")
    if len(public) != len(prefix) + 32 or not public.startswith(prefix):
        raise RuntimeError("CRYPTO_OPENSSL_PUB")
    return public[-32:]


def _keypair_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            encoded = stream.read(_KEYPAIR_LIMIT + 1)
        if len(encoded) > _KEYPAIR_LIMIT:
            raise ValueError("CRYPTO_KEYPAIR_JSON")
        data = json.loads(encoded.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("CRYPTO_KEYPAIR_JSON") from None
    if (not isinstance(data, list) or len(data) != 64
            or any(type(value) is not int or not 0 <= value <= 255 for value in data)):
        raise ValueError("CRYPTO_KEYPAIR_JSON")
    return bytes(data)


def _write_private(path: Path, data: bytes) -> None:
    """Publish with real Windows private ACLs, preserving the old file on error."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".new")
    try:
        descriptor = secure_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        set_private_mode(temporary, 0o600)
        atomic_replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def generate_ed25519() -> tuple[bytes, bytes, bytes]:
    der = _run_openssl("genpkey", "-algorithm", "ED25519", "-outform", "DER")
    prefix = bytes.fromhex("302e020100300506032b657004220420")
    if len(der) != len(prefix) + 32 or not der.startswith(prefix):
        raise RuntimeError("CRYPTO_OPENSSL_SEED")
    seed = der[-32:]
    pem = _run_openssl("pkey", "-inform", "DER", "-outform", "PEM", input_data=der)
    pub = _public_from_pem(pem)
    return seed, pub, pem


def save_test_keypair(seed: bytes, pub: bytes, pem: bytes) -> str:
    ensure_state_dir()
    if (len(seed) != 32 or len(pub) != 32 or _public_from_pem(pem) != pub
            or _public_from_pem(_pem_from_seed(seed)) != pub):
        raise ValueError("CRYPTO_KEYPAIR_JSON")
    secret = seed + pub
    path = keypair_path()
    pem_file = pem_path()
    _write_private(pem_file, pem)
    _write_private(path, (json.dumps(list(secret)) + "\n").encode("utf-8"))
    return b58encode(pub)


def _pubkey_from_keypair_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        data = _keypair_bytes(path)
    except ValueError:
        return ""
    return b58encode(data[32:])


def load_test_pubkey() -> str:
    live = live_keypair_path()
    if live.is_file():
        return _pubkey_from_keypair_file(live)
    return _pubkey_from_keypair_file(keypair_path())


def live_keypair_path() -> Path:
    return ensure_state_dir() / LIVE_KEYPAIR_NAME


def has_signer() -> bool:
    return keypair_path().is_file() or live_keypair_path().is_file()


def signer_for(pubkey: str) -> bool:
    """A selected watch account is signable only by the matching local key."""
    try:
        requested = validate_pubkey(pubkey)
    except ValueError:
        return False
    return load_test_pubkey() == requested


def import_solana_keypair(path: str) -> str:
    target = Path(path)
    if not target.is_file():
        raise ValueError("CRYPTO_KEYPAIR_MISSING")
    data = _keypair_bytes(target)
    if _public_from_pem(_pem_from_seed(data[:32])) != data[32:]:
        raise ValueError("CRYPTO_KEYPAIR_JSON")
    dest = live_keypair_path()
    _write_private(dest, (json.dumps(list(data)) + "\n").encode("utf-8"))
    return b58encode(data[32:])


def ensure_test_wallet() -> str:
    existing = load_test_pubkey()
    if existing:
        return existing
    if keypair_path().exists() or live_keypair_path().exists():
        raise ValueError('CRYPTO_KEYPAIR_JSON')
    seed, pub, pem = generate_ed25519()
    return save_test_keypair(seed, pub, pem)


def _pem_from_seed(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise RuntimeError("CRYPTO_SEED")
    der = bytes.fromhex("302e020100300506032b657004220420") + seed
    return _run_openssl("pkey", "-inform", "DER", "-outform", "PEM", input_data=der)


def signer_pem_bytes() -> bytes:
    live = live_keypair_path()
    if live.is_file():
        data = _keypair_bytes(live)
        pem = _pem_from_seed(data[:32])
        if _public_from_pem(pem) != data[32:]:
            raise ValueError("CRYPTO_KEYPAIR_JSON")
        return pem
    path = keypair_path()
    if path.is_file():
        data = _keypair_bytes(path)
        pem = _pem_from_seed(data[:32])
        if _public_from_pem(pem) != data[32:]:
            raise ValueError("CRYPTO_KEYPAIR_JSON")
        return pem
    raise RuntimeError("CRYPTO_NO_SIGNER")


def sign_message(message: bytes) -> bytes:
    pem = signer_pem_bytes()
    key_fd = msg_fd = None
    key_path = msg_path = None
    try:
        key_fd, key_path = tempfile.mkstemp(prefix="gg-ed25519-")
        msg_fd, msg_path = tempfile.mkstemp(prefix="gg-ed25519-msg-")
        set_private_mode(key_path, 0o600)
        set_private_mode(msg_path, 0o600)
        os.write(key_fd, pem)
        os.close(key_fd)
        key_fd = None
        os.write(msg_fd, message)
        os.close(msg_fd)
        msg_fd = None
        sig = _run_openssl("pkeyutl", "-sign", "-inkey", key_path, "-rawin", "-in", msg_path)
    finally:
        for descriptor in (key_fd, msg_fd):
            if descriptor is not None:
                os.close(descriptor)
        for item in (key_path, msg_path):
            if item is None:
                continue
            try:
                os.unlink(item)
            except OSError:
                pass
    if len(sig) != 64:
        raise RuntimeError("CRYPTO_SIG")
    return sig
