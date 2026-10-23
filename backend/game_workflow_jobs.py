"""One supervised, time-bounded game workflow worker; no UI-thread file scans."""
from __future__ import annotations

import argparse
from backend.platform_support import file_locks as fcntl
import json
import os
from pathlib import Path
import re
try:
    import resource
except ImportError:
    resource = None
import signal
import subprocess
import sys
import time
import threading
import uuid

from backend import game_workflow_common as common, game_workflows
from backend.platform_support import host_environment, terminate_process_tree
from backend.platform_process import background_options, process_arguments, apply_windows_worker_limits

PROJECT = Path(__file__).resolve().parents[1]
TIMEOUT = 60
BUSY = {"QUEUED", "RUNNING"}
MAX_JOBS = 8


def _folder(job_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", str(job_id)):
        raise ValueError("INVALID_WORKFLOW_JOB")
    path = common.ROOT / "jobs" / job_id
    if path.is_symlink():
        raise ValueError("INVALID_WORKFLOW_JOB")
    return path


def _alive(value):
    try:
        pid = int(value.get("pid", 0))
        command = process_arguments(pid)
        return "backend.game_workflow_jobs" in command and value["job_id"] in command
    except (ValueError, OSError, KeyError):
        return False


def status(job_id: str):
    try:
        folder = _folder(job_id)
        _, state, _ = common.read_json(folder / "state.json")
        if state["status"] in BUSY:
            pid_path = folder / "pid.json"
            if pid_path.is_file():
                _, pid_record, _ = common.read_json(pid_path)
                state["pid"] = pid_record["pid"]
            if time.time() - state["created"] > TIMEOUT + 5:
                if _alive(state):
                    terminate_process_tree(state["pid"], force=True)
                state.update(status="ERROR", reason="WORKFLOW_TIMEOUT")
                common.write_json(folder / "state.json", state)
            elif not _alive(state) and time.time() - state["created"] > 3:
                state.update(status="ERROR", reason="WORKFLOW_WORKER_STOPPED")
                common.write_json(folder / "state.json", state)
        if state["status"] == "COMPLETE":
            _, result, _ = common.read_json(folder / "result.json")
            state["result"] = result
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "ERROR", "reason": "WORKFLOW_JOB_NOT_FOUND"}


def start(operation: str, payload: dict):
    try:
        if resource is None and os.name != "nt":
            raise ValueError("GAME_WORKFLOW_WINDOWS_RESOURCE_LIMITS_UNAVAILABLE")
        if operation not in game_workflows.OPERATIONS or not isinstance(payload, dict):
            raise ValueError("UNKNOWN_GAME_WORKFLOW_OPERATION")
        payload = dict(payload)
        # Resolve paths in the caller's workspace before the worker changes cwd.
        for field in ("path", "target", "context", "candidate", "animation"):
            if payload.get(field):
                payload[field] = str(common.local_path(str(payload[field])))
        if operation == "asset_profile" and isinstance(payload.get("assets"), list):
            payload["assets"] = [{**row, **{field: str(common.local_path(str(row[field]))) for field in ("path", "lod_path") if row.get(field)}}
                                 for row in payload["assets"]]
        encoded = json.dumps(payload, allow_nan=False).encode()
        if len(encoded) > 65536:
            raise ValueError("WORKFLOW_REQUEST_LIMIT")
        root = common.ROOT / "jobs"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (root / ".admission").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            folders = sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and re.fullmatch(r"[0-9a-f]{32}", p.name)), key=lambda p: p.stat().st_mtime, reverse=True)
            for folder in folders:
                if status(folder.name).get("status") in BUSY:
                    raise ValueError("GAME_WORKFLOW_ALREADY_RUNNING")
            import shutil
            for folder in folders[MAX_JOBS - 1:]:
                shutil.rmtree(folder)
            job_id = uuid.uuid4().hex
            folder = _folder(job_id)
            state = {"job_id": job_id, "status": "QUEUED", "operation": operation, "created": time.time()}
            common.write_json(folder / "request.json", {"operation": operation, "payload": payload})
            common.write_json(folder / "state.json", state)
            env = host_environment({"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONPATH": str(PROJECT), "PYTHONDONTWRITEBYTECODE": "1",
                   "GG_GAME_WORKFLOWS_ROOT": str(common.ROOT)})
            if operation == "scene_measure":
                for name in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY", "QT_QPA_PLATFORM", "QSG_RHI_BACKEND"):
                    if name in os.environ:
                        env[name] = os.environ[name]
            # Context enrichment uses the same report store as the existing RE lab.
            from backend import research_jobs, research_lab, research_desk
            env.update(GG_RESEARCH_JOBS_ROOT=str(research_jobs.ROOT), GG_RESEARCH_TOOLS_ROOT=str(research_lab.TOOLS_ROOT), GG_RESEARCH_DESK_ROOT=str(research_desk.ROOT))
            process = subprocess.Popen([sys.executable, "-B", "-m", "backend.game_workflow_jobs", "--worker", job_id],
                                       cwd=PROJECT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, **background_options())
            threading.Thread(target=process.wait, daemon=True, name="gg-game-workflow-reaper").start()
            common.write_json(folder / "pid.json", {"pid": process.pid})
            return state
    except (OSError, ValueError, TypeError) as exc:
        return common.error(exc)


def cancel(job_id: str):
    state = status(job_id)
    if state.get("status") in BUSY:
        if _alive(state):
            terminate_process_tree(state["pid"], force=True)
        state.update(status="CANCELLED", reason="USER_CANCELLED")
        common.write_json(_folder(job_id) / "state.json", state)
    return state


def _worker(job_id):
    watchdog = None
    if os.name == "nt":
        apply_windows_worker_limits(memory_bytes=2 * 1024 * 1024 * 1024, cpu_seconds=45)
        watchdog = threading.Timer(TIMEOUT, lambda: os._exit(124))
        watchdog.daemon = True
        watchdog.start()
    else:
        _posix_worker_limits()
    folder = _folder(job_id)
    _, state, _ = common.read_json(folder / "state.json")
    _, request, _ = common.read_json(folder / "request.json")
    state.update(status="RUNNING", pid=os.getpid())
    common.write_json(folder / "state.json", state)
    try:
        result = game_workflows.execute(request["operation"], request["payload"])
        common.write_json(folder / "result.json", result)
        state.update(status="COMPLETE")
    except Exception as exc:
        state.update(status="ERROR", reason=type(exc).__name__)
    finally:
        if watchdog:
            watchdog.cancel()
        else:
            signal.alarm(0)
        common.write_json(folder / "state.json", state)


def _posix_worker_limits():
    # The existing supervised GgEngine child sets its own 2 GiB address-space
    # limit; keep that hard ceiling available while bounding this parent.
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 2 * 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    # The measured 26k-file catalog already occupies ~70 MiB. Bound SQLite to
    # its explicit 256 MiB quota; generated packets still have their own smaller
    # byte/count quotas. The old 64 MiB process cap made catalog writes fail.
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    def expired(_signum, _frame):
        raise TimeoutError("WORKFLOW_TIMEOUT")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(TIMEOUT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True)
    _worker(parser.parse_args().worker)
