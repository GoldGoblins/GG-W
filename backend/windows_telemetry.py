"""Read-only Windows metrics in the existing TMoG payload format."""
from __future__ import annotations

from collections import deque
from functools import lru_cache
import os
import math
import platform
import socket
import time
from typing import Any

import psutil

SCHEMA = "gg.ai-desktop.tmog-snapshot.v3"
_samples: dict[str, deque] = {}
_history_stamps: dict[str, float] = {}
_history_clock: float | None = None
_UNSTAMPED = object()
_previous_io = None
_io_rates = (0.0, 0.0, 0.0, 0.0)
_last_pulse_at: float | None = None
_interface = (None, "")
_probe_cache: dict[str, dict[str, Any]] = {}
CPU_SAMPLE_SECONDS = 0.1
MEMORY_SAMPLE_SECONDS = 0.25
FREQUENCY_SAMPLE_SECONDS = 1.0
BATTERY_SAMPLE_SECONDS = 5.0
IO_SAMPLE_SECONDS = 0.1
_process_details: dict[int, tuple[float, float, dict]] = {}
_cached_snapshot = None


def _history(name: str, value: float, *, sampled_at=_UNSTAMPED) -> list[float]:
    samples = _samples.setdefault(name, deque(maxlen=120))
    if value is None or not math.isfinite(float(value)):
        return list(samples)
    if sampled_at is not _UNSTAMPED:
        if (isinstance(sampled_at, bool) or not isinstance(sampled_at, (int, float))
                or not math.isfinite(sampled_at) or sampled_at < 0):
            return list(samples)
        if _history_stamps.get(name) == sampled_at:
            return list(samples)
        _history_stamps[name] = float(sampled_at)
    samples.append(float(value))
    return list(samples)


def _probe(name: str) -> dict[str, Any]:
    return _probe_cache.setdefault(name, {
        "value": None, "sampled_at": None, "attempted_at": None, "error": None,
    })


def _due(now: float, previous: float | None, period: float) -> bool:
    # A tiny comparison tolerance includes exact decimal mock-clock boundaries.
    return previous is None or now - previous + 1e-9 >= period


def _read_probe(name: str, period: float, now: float, read) -> dict[str, Any]:
    sample = _probe(name)
    if _due(now, sample["attempted_at"], period):
        sample["attempted_at"] = now
        try:
            value = read()
        except (OSError, psutil.Error, ValueError, TypeError, AttributeError) as exc:
            # Preserve the last successful observation and its timestamp.
            sample["error"] = type(exc).__name__
        else:
            sample.update(value=value, sampled_at=now, error=None)
    return sample


def _read_cpu(now: float) -> dict[str, Any]:
    sample = _probe("cpu")
    if not _due(now, sample["attempted_at"], CPU_SAMPLE_SECONDS):
        return sample
    sample["attempted_at"] = now
    try:
        values = psutil.cpu_percent(interval=None, percpu=True)
        if not isinstance(values, (list, tuple)) or not values or len(values) > 4096:
            raise ValueError("INVALID_CPU_SAMPLE")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or not 0 <= value <= 100 for value in values):
            raise ValueError("INVALID_CPU_SAMPLE")
    except (OSError, psutil.Error, ValueError, TypeError) as exc:
        sample["error"] = type(exc).__name__
        # A failed psutil read may have changed its hidden baseline. Prime it
        # again on recovery instead of publishing a short/invalid interval.
        sample["baseline_at"] = None
        return sample
    baseline_at = sample.get("baseline_at")
    baseline_count = sample.get("baseline_count")
    if baseline_count is not None and baseline_count != len(values):
        sample.update(value=None, sampled_at=None)
        baseline_at = None
    if baseline_at is not None and _due(now, baseline_at, CPU_SAMPLE_SECONDS):
        sample.update(value=list(values), sampled_at=now,
                      interval_seconds=now - baseline_at)
    sample.update(baseline_at=now, baseline_count=len(values), error=None)
    return sample


def _read_memory():
    memory = psutil.virtual_memory()
    if (memory.total <= 0 or memory.used < 0 or not math.isfinite(memory.percent)
            or not 0 <= memory.percent <= 100):
        raise ValueError("INVALID_MEMORY_SAMPLE")
    return memory


def _read_frequency():
    frequency = psutil.cpu_freq()
    if frequency is not None and (not math.isfinite(frequency.current)
            or not math.isfinite(frequency.max) or frequency.current < 0 or frequency.max < 0):
        raise ValueError("INVALID_FREQUENCY_SAMPLE")
    return frequency


def _read_io(now: float) -> dict[str, Any]:
    global _previous_io, _io_rates
    sample = _probe("io")
    if not _due(now, sample["attempted_at"], IO_SAMPLE_SECONDS):
        return sample
    sample["attempted_at"] = now
    try:
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()
        values = (net.bytes_recv, net.bytes_sent,
                  disk.read_bytes if disk else 0, disk.write_bytes if disk else 0)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("INVALID_IO_SAMPLE")
        io_delta = now - _previous_io[0] if _previous_io else 0.0
        if _previous_io and io_delta > 0:
            _io_rates = tuple(max(0, (value - old) / io_delta)
                              for value, old in zip(values, _previous_io[1]))
        _previous_io = now, values
    except (OSError, psutil.Error, ValueError, TypeError, AttributeError) as exc:
        sample["error"] = type(exc).__name__
    else:
        sample.update(value=_io_rates, sampled_at=now, error=None)
    return sample


def pulse() -> dict[str, Any]:
    global _previous_io, _io_rates, _last_pulse_at, _interface
    now = time.monotonic()
    if _last_pulse_at is not None and now < _last_pulse_at:
        # Also supports monotonic-clock replacement in tests and driver recovery.
        # Old future timestamps must not freeze probes or create negative rates.
        _probe_cache.clear()
        _previous_io = None
        _io_rates = (0.0, 0.0, 0.0, 0.0)
        _interface = (None, "")
    delta = max(0.0, now - _last_pulse_at) if _last_pulse_at is not None else 0.0
    _last_pulse_at = now
    cpu_sample = _read_cpu(now)
    memory_sample = _read_probe("memory", MEMORY_SAMPLE_SECONDS, now, _read_memory)
    frequency_sample = _read_probe("frequency", FREQUENCY_SAMPLE_SECONDS, now, _read_frequency)
    battery_sample = _read_probe("battery", BATTERY_SAMPLE_SECONDS, now, psutil.sensors_battery)
    _read_io(now)
    interface_sample = _read_probe("interface", 5.0, now, lambda: next(
        (name for name, info in psutil.net_if_stats().items()
         if info.isup and "loopback" not in name.lower()), ""))
    if interface_sample["sampled_at"] is not None:
        _interface = (interface_sample["sampled_at"], interface_sample["value"])
    cores = cpu_sample["value"]
    memory = memory_sample["value"]
    frequency = frequency_sample["value"]
    battery = battery_sample["value"]
    unavailable = ["gpu_busy", "temp_c", "energy_w", "load_average"]
    if cores is None:
        unavailable.extend(("cpu_busy", "cores"))
    if memory is None:
        unavailable.extend(("mem_used_kb", "mem_total_kb", "mem_pct"))
    if frequency is None:
        unavailable.extend(("mhz", "mhz_max"))
    if battery_sample["sampled_at"] is None:
        energy_source = "UNKNOWN"
    else:
        plugged = True if battery is None else battery.power_plugged
        energy_source = "AC" if plugged is True else "BATTERY" if plugged is False else "UNKNOWN"
    sampled_at = {name: _probe(name)["sampled_at"]
                  for name in ("cpu", "memory", "io", "frequency", "battery")}
    return {
        "schema": SCHEMA,
        "platform": "Windows",
        "cpu_busy": round(sum(cores) / len(cores), 2) if cores is not None else None,
        "cores": cores[:32] if cores is not None else [],
        "cpu_pending": cores is None,
        "cpu_sample_age_ms": round(max(0.0, now - sampled_at["cpu"]) * 1000, 3)
            if sampled_at["cpu"] is not None else None,
        "cpu_sample_interval_ms": round(cpu_sample["interval_seconds"] * 1000, 3)
            if cpu_sample.get("interval_seconds") is not None else None,
        "mhz": frequency.current if frequency is not None else None,
        "mhz_max": frequency.max if frequency is not None else None,
        "temp_c": None,
        "mem_used_kb": memory.used // 1024 if memory is not None else None,
        "mem_total_kb": memory.total // 1024 if memory is not None else None,
        "mem_pct": memory.percent if memory is not None else None,
        "load1": None, "load5": None, "load15": None,
        "net_iface": _interface[1],
        "net_rx_bps": _io_rates[0], "net_tx_bps": _io_rates[1],
        "disk_read_bps": _io_rates[2], "disk_write_bps": _io_rates[3],
        "gpu_busy": None,
        "energy_w": None,
        "energy_source": energy_source,
        "dt": round(delta, 4),
        "sampled_at": sampled_at,
        "sample_clock": "monotonic_seconds",
        "sample_errors": {name: sample["error"] for name, sample in _probe_cache.items()
                          if sample["error"] is not None},
        "unavailable": unavailable,
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
    global _cached_snapshot, _history_clock
    kind = str(page or "").strip().upper()
    now = time.monotonic()
    if (_cached_snapshot and _cached_snapshot[1] == kind
            and 0 <= now - _cached_snapshot[0] < 0.25):
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
        "mem_cached_kb": None, "mem_avail_kb": memory.available // 1024,
        "mem_buffers_kb": None, "mem_shared_kb": None, "mem_slab_kb": None,
        "unavailable": list(dict.fromkeys([*(data.get("unavailable") or []),
            "mem_cached_kb", "mem_buffers_kb", "mem_shared_kb", "mem_slab_kb"])),
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
    observed = data.get("sampled_at")
    sources = {"cpu": "cpu", "mem": "memory", "net": "io", "disk": "io", "mhz": "frequency"}
    if isinstance(observed, dict):
        stamps = [stamp for key, stamp in observed.items() if key in sources.values()
                  and not isinstance(stamp, bool) and isinstance(stamp, (int, float))
                  and math.isfinite(stamp) and stamp >= 0]
        if stamps:
            clock = max(stamps)
            if _history_clock is not None and clock < _history_clock:
                # The isolated page worker may receive a newly primed meter
                # generation after clock reset. Accept its first observations.
                _history_stamps.clear()
            _history_clock = clock
        for name, value in values.items():
            data[name + "_hist"] = _history(name, value, sampled_at=observed.get(sources[name]))
    else:
        # Older callers have no observation metadata; retain their established
        # page-query history behavior instead of treating every value as missing.
        for name, value in values.items():
            data[name + "_hist"] = _history(name, value)
    for name in ("temp", "gpu", "energy"):
        data[name + "_hist"] = []
    _cached_snapshot = now, kind, data
    return data
