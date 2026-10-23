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

VALIDATOR_BIN = Path(os.environ.get('GG_SOLANA_VALIDATOR', str(HOME / '.local/opt/solana-cli/bin/solana-test-validator')))
LEDGER_DIR = STATE_DIR / "local-ledger"
LOG_PATH = STATE_DIR / "local-validator.log"
PID_PATH = STATE_DIR / "local-validator.pid"
RPC_URL = "http://127.0.0.1:8899"
SYSTEMD_UNIT = "gg-crypto-lab.service"
CPU_QUOTA = "85%"


def _cpu_count() -> int:
    return max(2, os.cpu_count() or 2)


def _worker_threads() -> int:
    return max(4, _cpu_count())


def _pid_alive(pid: int) -> bool:
    if os.name == 'nt':
        args = process_arguments(pid)
        return bool(args and Path(args[0]).name.lower() == 'solana-test-validator.exe')
    comm = Path("/proc") / str(pid) / "comm"
    try:
        name = comm.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return name.startswith("solana-test-val")


def running_pid() -> int | None:
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if not _pid_alive(pid):
        return None
    return pid


_HEALTH_TTL = 15.0
_health_cache: tuple[float, bool] = (0.0, False)


def rpc_healthy(timeout: float = 2.0) -> bool:
    global _health_cache
    now = time.monotonic()
    if now - _health_cache[0] < _HEALTH_TTL:
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
        payload = json.loads(
            urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        )
        ok = payload.get("result") == "ok"
        _health_cache = (now, ok)
        return ok
    except (OSError, TimeoutError, json.JSONDecodeError, urllib.error.URLError):
        _health_cache = (now, False)
        return False


def lab_status() -> dict[str, Any]:
    pid = running_pid()
    healthy = rpc_healthy()
    running = pid is not None or healthy
    if healthy:
        label = "LAB ON"
    elif pid is not None:
        label = "LAB STARTING"
    else:
        label = "LAB OFF"
    return {
        "running": running,
        "healthy": healthy,
        "pid": pid,
        "rpc": RPC_URL,
        "label": label,
        "cpus": _cpu_count(),
        "threads": _worker_threads(),
        "cpu_quota": CPU_QUOTA,
    }


def wait_healthy(timeout_s: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    status = lab_status()
    while time.monotonic() < deadline:
        if status.get("healthy"):
            return status
        time.sleep(0.4)
        status = lab_status()
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
    status = lab_status()
    while time.monotonic() < deadline:
        slot = current_slot() or 0
        if status.get("healthy") and slot > 0 and has_blockhash():
            status["slot"] = slot
            return status
        time.sleep(0.4)
        status = lab_status()
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
        payload = json.loads(
            urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        )
    except (OSError, TimeoutError, json.JSONDecodeError, urllib.error.URLError):
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


def _stop_systemd_unit(env: dict[str, str]) -> None:
    if os.name == 'nt':
        return
    subprocess.run(
        ["systemctl", "--user", "stop", SYSTEMD_UNIT],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    subprocess.run(
        ["systemctl", "--user", "reset-failed", SYSTEMD_UNIT],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _systemd_main_pid(env: dict[str, str]) -> int | None:
    try:
        raw = subprocess.check_output(
            ["systemctl", "--user", "show", "-p", "MainPID", "--value", SYSTEMD_UNIT],
            env=env,
            stderr=subprocess.DEVNULL,
        )
        pid = int(raw.decode("utf-8").strip() or "0")
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    if pid <= 0 or not _pid_alive(pid):
        return None
    return pid


def _spawn_systemd(env: dict[str, str]) -> int | None:
    if os.name == 'nt':
        return None
    _stop_systemd_unit(env)
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
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    for _ in range(20):
        pid = _systemd_main_pid(env)
        if pid is not None:
            return pid
        time.sleep(0.15)
    return None


def _spawn_popen(env: dict[str, str]) -> int:
    log = LOG_PATH.open("ab")
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
    ensure_state_dir()
    LEDGER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = _user_env()
    pid = _spawn_systemd(env)
    if pid is None:
        pid = _spawn_popen(env)
    PID_PATH.write_text(str(pid) + "\n", encoding="utf-8")
    PID_PATH.chmod(0o600)
    return wait_ready(30)


def start_lab(reset_if_frozen: bool = True) -> dict[str, Any]:
    current = running_pid()
    if current is not None:
        status = wait_ready(12)
        if status.get("healthy") and (current_slot() or 0) > 0 and not is_frozen():
            return status
        if not reset_if_frozen or not is_frozen():
            return wait_ready(20)
        stop_lab()
        time.sleep(0.8)
        reset_ledger()
        return _spawn_validator()
    if rpc_healthy():
        status = wait_ready(12)
        if (current_slot() or 0) > 0 and not is_frozen():
            return status
        if not reset_if_frozen:
            return status
    status = _spawn_validator()
    if status.get("healthy") and reset_if_frozen and is_frozen():
        stop_lab()
        time.sleep(0.8)
        reset_ledger()
        return _spawn_validator()
    return status


def stop_lab() -> dict[str, Any]:
    env = _user_env()
    _stop_systemd_unit(env)
    pid = running_pid()
    if pid is None:
        try:
            PID_PATH.unlink()
        except OSError:
            pass
        return lab_status()
    try:
        if os.name == 'nt':
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
    return lab_status()
