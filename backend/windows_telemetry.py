"""Read-only Windows metrics in the existing TMoG payload format."""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import os
import platform
import socket
import time
from typing import Any

import psutil

SCHEMA = "gg.ai-desktop.tmog-snapshot.v3"
_samples: dict[str, deque] = {}
_previous_io = None
_io_rates = (0.0, 0.0, 0.0, 0.0)
_last_pulse_at = 0.0
_interface = (0.0, "")
_process_details: dict[int, tuple[float, float, dict]] = {}
_cached_snapshot = None


def _history(name: str, value: float) -> list[float]:
    samples = _samples.setdefault(name, deque(maxlen=120))
    samples.append(float(value))
    return list(samples)


def pulse() -> dict[str, Any]:
    global _previous_io, _io_rates, _last_pulse_at, _interface
    now = time.monotonic()
    memory = psutil.virtual_memory()
    cores = psutil.cpu_percent(interval=None, percpu=True)
    delta = now - _last_pulse_at if _last_pulse_at else 0.0
    _last_pulse_at = now
    # Windows adapter enumeration costs about a frame per call on this host.
    # Read IO counters over a useful 100 ms rate window, then let the 60 Hz UI
    # follow the measured rate. Adapter names change much less frequently.
    if _previous_io is None or now - _previous_io[0] >= 0.1:
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()
        values = (net.bytes_recv, net.bytes_sent,
                  disk.read_bytes if disk else 0, disk.write_bytes if disk else 0)
        io_delta = now - _previous_io[0] if _previous_io else 0.0
        if _previous_io and io_delta > 0:
            _io_rates = tuple(max(0, (value - old) / io_delta)
                              for value, old in zip(values, _previous_io[1]))
        _previous_io = now, values
    if not _interface[0] or now - _interface[0] >= 5.0:
        _interface = (now, next((name for name, info in psutil.net_if_stats().items()
                                if info.isup and "loopback" not in name.lower()), ""))
    frequency = psutil.cpu_freq()
    battery = psutil.sensors_battery()
    return {
        "schema": SCHEMA,
        "platform": "Windows",
        "cpu_busy": round(sum(cores) / len(cores), 2) if cores else 0.0,
        "cores": cores[:32],
        "mhz": frequency.current if frequency else 0,
        "mhz_max": frequency.max if frequency else 0,
        "temp_c": None,
        "mem_used_kb": memory.used // 1024,
        "mem_total_kb": memory.total // 1024,
        "mem_pct": memory.percent,
        "load1": None, "load5": None, "load15": None,
        "net_iface": _interface[1],
        "net_rx_bps": _io_rates[0], "net_tx_bps": _io_rates[1],
        "disk_read_bps": _io_rates[2], "disk_write_bps": _io_rates[3],
        "gpu_busy": None,
        "energy_w": None,
        "energy_source": "AC" if battery is None or battery.power_plugged else "BATTERY",
        "dt": round(delta, 4),
        "unavailable": ["gpu_busy", "temp_c", "energy_w", "load_average"],
    }


def _processes(*, fill_limit=80, need_users=True, details=True) -> tuple[list[dict], dict[str, int], int]:
    rows = []
    users: dict[str, int] = {}
    count = 0
    processors = max(1, psutil.cpu_count() or 1)
    candidates = []
    now = time.monotonic()
    for process in psutil.process_iter(["pid", "name"], ad_value=None):
        count += 1
        if count > 512:
            break
        try:
            # PID 0 is System Idle Process: idle time is not a busy process.
            if process.pid == 0:
                continue
            cpu = round(process.cpu_percent(None) / processors, 1)
            candidates.append((cpu, process))
            if need_users:
                username = process.username()
                users[username] = users.get(username, 0) + 1
        except (psutil.Error, OSError):
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    for cpu, process in candidates[:fill_limit]:
        try:
            data = process.info
            created = process.create_time()
            cached = _process_details.get(process.pid)
            with process.oneshot():
                memory = process.memory_info()
                if details:
                    if cached and cached[0] == created and now - cached[1] < 30.0:
                        identity = cached[2]
                    else:
                        identity = process.as_dict(["ppid", "username"], ad_value=None)
                        _process_details[process.pid] = (created, now, identity)
                    # Process state, thread count and memory remain current;
                    # only stable owner/parent metadata uses the cache.
                    extra = {**identity, **process.as_dict(["status", "num_threads"], ad_value=None)}
                else:
                    extra = {}
            rows.append({
                "pid": data["pid"], "ppid": extra.get("ppid") or 0,
                "comm": data.get("name") or "", "cmdline": "",
                "state": "R" if extra.get("status") == "running" else "S",
                "status": extra.get("status") or "Unknown", "user": extra.get("username") or "",
                "rss_kb": memory.rss // 1024 if memory else 0,
                "virt_kb": memory.vms // 1024 if memory else 0,
                "cpu_pct": cpu,
                "threads": extra.get("num_threads") or 0, "tombstone": False,
            })
        except (psutil.Error, OSError):
            continue
    rows.sort(key=lambda row: (row["cpu_pct"], row["rss_kb"]), reverse=True)
    if len(_process_details) > 512:
        keep = {process.pid for _, process in candidates}
        for pid in list(_process_details):
            if pid not in keep:
                del _process_details[pid]
    return rows[:80], users, count


def _mounts() -> list[dict]:
    rows = []
    for partition in psutil.disk_partitions()[:16]:
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            rows.append({"path": partition.mountpoint, "src": partition.device,
                         "fstype": partition.fstype, "used": usage.used,
                         "total": usage.total, "free": usage.free,
                         "pct": usage.percent})
        except (OSError, psutil.Error):
            continue
    return rows


def _services() -> list[dict]:
    rows = []
    for service in psutil.win_service_iter():
        try:
            data = service.as_dict()
            rows.append({"name": data["name"], "label": data["display_name"],
                         "state": data["status"], "path": data["binpath"],
                         "enabled": data["start_type"] == "automatic"})
        except (psutil.Error, OSError):
            continue
        if len(rows) >= 64:
            break
    return rows


def _startup() -> list[dict]:
    import winreg
    rows = []
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for index in range(min(64 - len(rows), winreg.QueryInfoKey(key)[1])):
                    name, value, _ = winreg.EnumValue(key, index)
                    rows.append({"name": name, "label": name, "exec": str(value),
                                 "enabled": True, "source": "Windows registry"})
        except OSError:
            continue
    return rows


def _connections() -> list[dict]:
    try:
        return [{"pid": item.pid or 0, "comm": "", "state": item.status,
                 "local": f"{item.laddr.ip}:{item.laddr.port}" if item.laddr else "",
                 "remote": f"{item.raddr.ip}:{item.raddr.port}" if item.raddr else ""}
                for item in psutil.net_connections(kind="tcp")[:48]]
    except (OSError, psutil.Error):
        return []


@lru_cache(maxsize=1)
def _identity() -> dict[str, str]:
    return {"cpu_model": platform.processor(), "hostname": socket.gethostname(),
            "kernel": platform.release(), "os": platform.platform()}


def snapshot(page: str = "", *, live: dict[str, Any] | None = None) -> dict[str, Any]:
    global _cached_snapshot
    kind = str(page or "").strip().upper()
    now = time.monotonic()
    if _cached_snapshot and _cached_snapshot[1] == kind and now - _cached_snapshot[0] < 0.25:
        return _cached_snapshot[2]
    # The page worker reuses the meter lane's latest sample. It never steps
    # that lane's CPU/IO baselines or repeats Windows network enumeration.
    data = dict(live) if live is not None else pulse()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    processes, users, count = _processes(
        fill_limit=17 if kind in ("SUMMARY", "FLIGHT") else 80,
        need_users=kind in ("", "USERS"), details=kind in ("", "PROCESSES", "USERS"),
    ) if kind in ("", "SUMMARY", "PROCESSES", "USERS", "FLIGHT") else ([], {}, len(psutil.pids()))
    data.update({
        **_identity(),
        "uptime_s": max(0, int(time.time() - psutil.boot_time())),
        "core_count": psutil.cpu_count() or 0,
        "cores": [{"id": index, "pct": pct, "mhz": data["mhz"]}
                  for index, pct in enumerate(data["cores"])],
        "mem_cached_kb": 0, "mem_avail_kb": memory.available // 1024,
        "mem_buffers_kb": 0, "mem_shared_kb": 0, "mem_slab_kb": 0,
        "swap_used_kb": swap.used // 1024, "swap_total_kb": swap.total // 1024,
        "energy": {"watts": None, "source": data["energy_source"]},
        "pressure": {}, "gpus": [], "temps": [], "drivers": [],
        "process_count": count, "tasks_running": len(processes),
        "processes": processes, "tombstones": 0,
        "users": [{"name": name, "procs": count} for name, count in users.items()],
        "mounts": _mounts() if kind in ("", "DISK") else [],
        "connections": _connections() if kind in ("", "CONNECTIONS") else [],
        "startup": _startup() if kind in ("", "STARTUP") else [],
        "services": _services() if kind in ("", "SERVICES") else [],
        "apps": [], "appimage": "", "appimage_found": False,
        "page": kind or "FULL", "flight_history": [], "core_hist": [],
        "disk_led": min(1.0, (data["disk_read_bps"] + data["disk_write_bps"]) / (8 * 1024**2)),
    })
    values = {"cpu": data["cpu_busy"], "mem": data["mem_pct"],
              "net": (data["net_rx_bps"] + data["net_tx_bps"]) / 1024,
              "disk": (data["disk_read_bps"] + data["disk_write_bps"]) / 1024,
              "mhz": data["mhz"]}
    for name, value in values.items():
        data[name + "_hist"] = _history(name, value)
    for name in ("temp", "gpu", "energy"):
        data[name + "_hist"] = []
    _cached_snapshot = now, kind, data
    return data
