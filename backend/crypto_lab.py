from __future__ import annotations

from backend.application_paths import HOME
from backend.platform_support import private_runtime_root, terminate_process_tree
from backend.platform_process import background_options, process_arguments

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from backend.crypto_contract import STATE_DIR, ensure_state_dir
from backend.crypto_contract import write_state_json
from backend.platform_files import is_link

VALIDATOR_BIN = Path(os.environ.get('GG_SOLANA_VALIDATOR', str(HOME / '.local/opt/solana-cli/bin/solana-test-validator')))
LEDGER_DIR = STATE_DIR / "local-ledger"
LOG_PATH = STATE_DIR / "local-validator.log"
PID_PATH = STATE_DIR / "local-validator.pid"
OWNER_PATH = STATE_DIR / "local-validator-owner.json"
RPC_URL = "http://127.0.0.1:8899"
SYSTEMD_UNIT = "gg-crypto-lab.service"
CPU_QUOTA = "85%"


def _cpu_count() -> int:
    return max(2, os.cpu_count() or 2)


def _worker_threads() -> int:
    return max(4, _cpu_count())


def _canonical(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _argument(args: list[str], flag: str) -> str:
    values = []
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            values.append(args[index + 1])
        elif value.startswith(flag + '='):
            values.append(value.split('=', 1)[1])
    return values[0] if len(values) == 1 else ''


def _process_matches(pid: int) -> bool:
    args = process_arguments(pid)
    if not args:
        return False
    try:
        ledger = _argument(args, '--ledger')
        if not ledger:
            return False
        return (_canonical(args[0]) == _canonical(VALIDATOR_BIN)
                and _canonical(ledger) == _canonical(LEDGER_DIR)
                and _argument(args, '--rpc-port') == '8899'
                and _argument(args, '--bind-address') == '127.0.0.1')
    except (OSError, ValueError):
        return False


def _creation_time(pid: int) -> float | None:
    import psutil
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return None


def _owner() -> dict[str, Any]:
    try:
        if is_link(OWNER_PATH) or is_link(LEDGER_DIR):
            return {}
        with OWNER_PATH.open('rb') as stream:
            raw = stream.read(16385)
        value = json.loads(raw.decode('utf-8')) if len(raw) <= 16384 else None
        if (not isinstance(value, dict) or value.get('schema') != 1
                or value.get('ledger') != _canonical(LEDGER_DIR)
                or value.get('validator') != _canonical(VALIDATOR_BIN)):
            return {}
        return value
    except (OSError, ValueError, UnicodeError):
        return {}


def _pid_alive(pid: int) -> bool:
    owner = _owner()
    if owner.get('pid') != pid or not _process_matches(pid):
        return False
    created = _creation_time(pid)
    return bool(created is not None and owner.get('created') == created)


def running_pid() -> int | None:
    # The private creation-time receipt survives an interrupted PID-file
    # publication. A PID file alone never confers process ownership.
    pid = _owner().get('pid')
    if type(pid) is not int or pid <= 0:
        return None
    if not _pid_alive(pid):
        return None
    return pid


_HEALTH_TTL = 15.0
_health_cache: tuple[float, bool] = (0.0, False)


def rpc_healthy(timeout: float = 2.0, *, force: bool = False) -> bool:
    global _health_cache
    now = time.monotonic()
    if not force and now - _health_cache[0] < _HEALTH_TTL:
        return _health_cache[1]
    try:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
        ).encode("utf-8")
        req = urllib.request.Request(
            RPC_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(65537)
        payload = json.loads(raw.decode('utf-8')) if len(raw) <= 65536 else None
        ok = isinstance(payload, dict) and payload.get("result") == "ok"
        _health_cache = (now, ok)
        return ok
    except (OSError, TimeoutError, json.JSONDecodeError, UnicodeError, urllib.error.URLError):
        _health_cache = (now, False)
        return False


def lab_status(*, refresh: bool = False) -> dict[str, Any]:
    pid = running_pid()
    rpc_ok = rpc_healthy(force=refresh)
    owned = pid is not None
    healthy = owned and rpc_ok
    running = owned
    available = VALIDATOR_BIN.is_file() and (os.name != 'nt' or VALIDATOR_BIN.suffix.lower() == '.exe')
    diagnostic = ''
    if healthy:
        label = "LAB ON"
    elif pid is not None:
        label = "LAB STARTING"
    elif rpc_ok:
        label = "EXTERNAL RPC"
        diagnostic = 'CRYPTO_LAB_FOREIGN_RPC'
    elif not available:
        label = "LAB UNAVAILABLE"
        diagnostic = 'CRYPTO_VALIDATOR_MISSING'
    else:
        label = "LAB OFF"
    return {
        "running": running,
        "healthy": healthy,
        "available": available,
        "owned": owned,
        "rpc_healthy": rpc_ok,
        "diagnostic": diagnostic,
        "pid": pid,
        "rpc": RPC_URL,
        "label": label,
        "cpus": _cpu_count(),
        "threads": _worker_threads(),
        "cpu_quota": CPU_QUOTA,
    }


def wait_healthy(timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    status = lab_status(refresh=True)
    while time.monotonic() < deadline:
        if status.get("healthy"):
            return status
        time.sleep(0.4)
        status = lab_status(refresh=True)
    return status


def has_blockhash() -> bool:
    payload = _rpc("getLatestBlockhash", [{"commitment": "confirmed"}], timeout=3.0)
    if not payload or payload.get("error"):
        return False
    result = payload.get("result")
    value = result.get("value") if isinstance(result, dict) else None
    return bool((value or {}).get("blockhash"))


def wait_ready(timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    status = lab_status(refresh=True)
    while time.monotonic() < deadline:
        slot = current_slot() or 0
        if status.get("healthy") and slot > 0 and has_blockhash():
            status["slot"] = slot
            return status
        time.sleep(0.4)
        status = lab_status(refresh=True)
    status["slot"] = current_slot()
    return status


def is_frozen() -> bool:
    slot = current_slot() or 0
    if slot < 8:
        return False
    return not slots_advance(1.6)


def _rpc(method: str, params: list[Any] | None = None, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params or [],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            RPC_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(65537)
        payload = json.loads(raw.decode('utf-8')) if len(raw) <= 65536 else None
    except (OSError, TimeoutError, json.JSONDecodeError, UnicodeError, urllib.error.URLError):
        return None
    return payload if isinstance(payload, dict) else None


def current_slot() -> int | None:
    payload = _rpc("getSlot", [])
    if not payload:
        return None
    try:
        return int(payload.get("result"))
    except (TypeError, ValueError):
        return None


def slots_advance(wait_s: float = 1.6) -> bool:
    first = current_slot()
    time.sleep(max(0.4, float(wait_s)))
    second = current_slot()
    if first is None or second is None:
        return False
    return second > first


def reset_ledger() -> None:
    if not _owner() or running_pid() is not None or rpc_healthy(force=True):
        raise RuntimeError('CRYPTO_LAB_LEDGER_REQUIRES_REVIEW')
    if is_link(LEDGER_DIR) or LEDGER_DIR.resolve().parent != STATE_DIR.resolve():
        raise RuntimeError('CRYPTO_LAB_LEDGER_REQUIRES_REVIEW')
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR, ignore_errors=True)
    LEDGER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def _user_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime = private_runtime_root()
    bus = runtime / "bus"
    if bus.exists():
        env.setdefault("XDG_RUNTIME_DIR", str(runtime))
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=" + str(bus))
    workers = str(_worker_threads())
    env["RAYON_NUM_THREADS"] = workers
    env["TOKIO_WORKER_THREADS"] = workers
    env.pop("GOMAXPROCS", None)
    return env


def _validator_args() -> list[str]:
    return [
        str(VALIDATOR_BIN),
        "--ledger",
        str(LEDGER_DIR),
        "--rpc-port",
        "8899",
        "--bind-address",
        "127.0.0.1",
        "--rpc-pubsub-notification-threads",
        "0",
        "--rpc-pubsub-worker-threads",
        str(_worker_threads()),
        "--limit-ledger-size",
        "100000",
        "--quiet",
    ]


def _stop_systemd_unit(env: dict[str, str], expected_pid: int) -> None:
    if os.name == 'nt':
        return
    if not _pid_alive(expected_pid) or _systemd_main_pid(env) != expected_pid:
        return
    subprocess.run(
        ["systemctl", "--user", "stop", SYSTEMD_UNIT],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    subprocess.run(
        ["systemctl", "--user", "reset-failed", SYSTEMD_UNIT],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )


def _systemd_main_pid(env: dict[str, str]) -> int | None:
    try:
        raw = subprocess.check_output(
            ["systemctl", "--user", "show", "-p", "MainPID", "--value", SYSTEMD_UNIT],
            env=env,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        pid = int(raw.decode("utf-8").strip() or "0")
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    if pid <= 0 or not _process_matches(pid):
        return None
    return pid


def _spawn_systemd(env: dict[str, str]) -> int | None:
    if os.name == 'nt':
        return None
    log = str(LOG_PATH)
    argv = [
        "systemd-run",
        "--user",
        "--unit=" + SYSTEMD_UNIT,
        "--collect",
        "-p",
        "CPUQuota=" + CPU_QUOTA,
        "-p",
        "Nice=10",
        "-p",
        "CPUWeight=20",
        "-p",
        "StandardOutput=append:" + log,
        "-p",
        "StandardError=append:" + log,
        "--setenv=RAYON_NUM_THREADS=" + env["RAYON_NUM_THREADS"],
        "--setenv=TOKIO_WORKER_THREADS=" + env["TOKIO_WORKER_THREADS"],
        "--",
        *_validator_args(),
    ]
    try:
        subprocess.run(
            argv,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        pid = _systemd_main_pid(env)
        if pid is not None:
            return pid
        time.sleep(0.15)
    # systemd accepted this launch. Do not start a second validator merely
    # because its process has not appeared within the observation budget.
    raise RuntimeError('CRYPTO_LAB_START_TIMEOUT')


def _spawn_popen(env: dict[str, str]) -> int:
    with LOG_PATH.open("ab") as log:
        proc = subprocess.Popen(
            (["nice", "-n", "10"] if os.name != 'nt' else []) + _validator_args(),
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            **background_options(),
            env=env,
            close_fds=True,
        )
    return int(proc.pid)


def _spawn_validator() -> dict[str, Any]:
    if not VALIDATOR_BIN.is_file():
        raise RuntimeError("CRYPTO_VALIDATOR_MISSING")
    if os.name == 'nt' and VALIDATOR_BIN.suffix.lower() != '.exe':
        raise RuntimeError('CRYPTO_VALIDATOR_UNSUPPORTED_PLATFORM')
    ensure_state_dir()
    if is_link(LEDGER_DIR) or LEDGER_DIR.resolve().parent != STATE_DIR.resolve():
        raise RuntimeError('CRYPTO_LAB_LEDGER_REQUIRES_REVIEW')
    if LEDGER_DIR.is_dir() and any(LEDGER_DIR.iterdir()) and not _owner():
        raise RuntimeError('CRYPTO_LAB_LEDGER_REQUIRES_REVIEW')
    LEDGER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    owner = {'schema': 1, 'ledger': _canonical(LEDGER_DIR), 'validator': _canonical(VALIDATOR_BIN)}
    write_state_json(OWNER_PATH, owner)
    env = _user_env()
    pid = _spawn_systemd(env)
    if pid is None:
        pid = _spawn_popen(env)
    created = _creation_time(pid)
    if created is None or not _process_matches(pid):
        raise RuntimeError('CRYPTO_LAB_PROCESS_IDENTITY')
    owner.update(pid=pid, created=created)
    write_state_json(OWNER_PATH, owner)
    PID_PATH.write_text(str(pid) + "\n", encoding="utf-8")
    PID_PATH.chmod(0o600)
    return wait_ready(30)


def start_lab(reset_if_frozen: bool = True) -> dict[str, Any]:
    current = running_pid()
    if current is not None:
        status = wait_ready(12)
        if status.get("healthy") and (current_slot() or 0) > 0 and not is_frozen():
            return status
        # Starting a frozen validator never erases an existing ledger. An
        # explicit, separately reviewed reset can call reset_ledger instead.
        diagnostic = 'CRYPTO_LAB_FROZEN_REQUIRES_REVIEW' if status.get('healthy') else 'LAB_STARTING'
        return {**status, 'diagnostic': diagnostic}
    if rpc_healthy(force=True):
        return {**lab_status(), 'diagnostic': 'CRYPTO_LAB_FOREIGN_RPC'}
    status = _spawn_validator()
    if status.get("healthy") and reset_if_frozen and is_frozen():
        return {**status, 'diagnostic': 'CRYPTO_LAB_FROZEN_REQUIRES_REVIEW'}
    return status


def stop_lab() -> dict[str, Any]:
    global _health_cache
    env = _user_env()
    pid = running_pid()
    if pid is None:
        return lab_status()
    try:
        _stop_systemd_unit(env, pid)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        if not _pid_alive(pid):
            pass
        elif os.name == 'nt':
            terminate_process_tree(pid)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pid = None
    if pid is not None:
        for _ in range(20):
            if not _pid_alive(pid):
                break
            time.sleep(0.2)
        if _pid_alive(pid):
            try:
                if os.name == 'nt':
                    terminate_process_tree(pid, force=True)
                else:
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.2)
    try:
        PID_PATH.unlink()
    except OSError:
        pass
    _health_cache = (0.0, False)
    return lab_status(refresh=True)
