from __future__ import annotations

from backend.application_paths import DATA_HOME, HOME

import os
try:
    import pwd
except ImportError:
    pwd = None
import socket
import subprocess
import threading
import time
import ctypes
from collections import deque
from pathlib import Path
from typing import Any


SCHEMA = "gg.ai-desktop.tmog-snapshot.v3"
APPIMAGE_NAMES = frozenset(
    {
        "TMOG-Task-Manager-Linux-x86_64.AppImage",
    }
)
SEARCH_DIRS = (
    Path(str(HOME / 'Hämtningar')),
    Path.home() / "Hämtningar",
    Path.home() / "Downloads",
    Path(str(DATA_HOME / 'goldgoblins/tools/tmog')),
)
MIN_APPIMAGE_BYTES = 1_000_000
MAX_APPIMAGE_BYTES = 200_000_000
MAX_PROCESSES = 80
MAX_SCAN = 512
MAX_CMDLINE = 160
MAX_HISTORY = 120
_HISTORY_RAW_MAX = 7200
MAX_CORES = 32
MAX_CONNS = 48
MAX_MOUNTS = 16
MAX_NAMES = 64
WINDOW_TOKENS = ("tmog", "task manager og")
TCP_STATES = {
    "01": "ESTABLISHED",
    "02": "SYN_SENT",
    "03": "SYN_RECV",
    "04": "FIN_WAIT1",
    "05": "FIN_WAIT2",
    "06": "TIME_WAIT",
    "07": "CLOSE",
    "08": "CLOSE_WAIT",
    "09": "LAST_ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
}
PROC_STATES = {
    "R": "Running",
    "S": "Sleeping",
    "D": "Disk sleep",
    "Z": "Zombie",
    "T": "Stopped",
    "t": "Tracing",
    "I": "Idle",
}

_prev_times: dict[int, tuple[float, int]] = {}
_prev_mono = 0.0
_snapshot_mono = 0.0
CPU_WINDOW = 0.4
MIN_RATE_DT = 0.05
IO_WINDOW = 0.1
_cpu_win: deque[tuple[float, list[tuple[int, int]]]] = deque()
_net_win: deque[tuple[float, int, int]] = deque()
_disk_win: deque[tuple[float, int, int]] = deque()
_last_cpu: list[float] = []
_last_net = [0, 0]
_last_disk = [0, 0]
_prev_rapl: tuple[float, int] = (0.0, 0)
_inode_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_gpu_busy_path: Path | None = None
_gpu_busy_tried = False
_nvml: ctypes.CDLL | None = None
_nvml_handle: ctypes.c_void_p | None = None
_nvml_tried = False
_nvidia_value: float | None = None
_nvidia_thread: threading.Thread | None = None
_nvidia_next_poll = 0.0
_RAPL_PATH = Path("/sys/class/powercap/intel-rapl:0/energy_uj")
_MOUNT_SKIP = frozenset(
    {
        "proc",
        "sysfs",
        "devtmpfs",
        "devpts",
        "tmpfs",
        "cgroup2",
        "cgroup",
        "overlay",
        "squashfs",
        "efivarfs",
        "fusectl",
        "debugfs",
        "tracefs",
        "bpf",
        "configfs",
        "pstore",
        "securityfs",
        "mqueue",
        "hugetlbfs",
        "autofs",
        "nsfs",
        "ramfs",
        "rpc_pipefs",
        "binfmt_misc",
    }
)
_DESKTOP_ROOTS = (
    Path.home(),
    Path("/usr/share"),
    Path("/usr/local/share"),
    Path("/usr/lib"),
    Path("/etc"),
)
_cpu_hist: list[float] = []
_mem_hist: list[float] = []
_net_hist: list[float] = []
_disk_hist: list[float] = []
_temp_hist: list[float] = []
_mhz_hist: list[float] = []
_gpu_hist: list[float] = []
_energy_hist: list[float] = []
_core_hist: list[list[float]] = []
_history_samples: dict[str, deque[tuple[float, float]]] = {}
_last_proc: dict[int, dict[str, Any]] = {}
_tombstones: dict[int, dict[str, Any]] = {}
_flight_history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY)
_TOMBSTONE_TTL = 8.0


def resolve_appimage(
    search_dirs: tuple[Path, ...] | None = None,
) -> Path | None:
    dirs = search_dirs if search_dirs is not None else SEARCH_DIRS
    seen: set[Path] = set()
    for folder in dirs:
        try:
            folder = folder.resolve()
        except OSError:
            continue
        if folder in seen or not folder.is_dir() or folder.is_symlink():
            continue
        seen.add(folder)
        for name in sorted(APPIMAGE_NAMES):
            path = folder / name
            if _usable_appimage(path):
                return path
    return None


def _usable_appimage(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_file():
            return False
        info = path.stat()
    except OSError:
        return False
    if info.st_uid != os.getuid():
        return False
    if not os.access(path, os.X_OK):
        return False
    if info.st_size < MIN_APPIMAGE_BYTES or info.st_size > MAX_APPIMAGE_BYTES:
        return False
    return path.name in APPIMAGE_NAMES


def _read_text(path: Path, limit: int = 4096) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _push(hist: list[float], value: float) -> list[float]:
    hist.append(round(float(value), 2))
    if len(hist) > MAX_HISTORY:
        del hist[: len(hist) - MAX_HISTORY]
    return list(hist)


def _history(name: str, value: float, now: float | None = None) -> list[float]:
    """Return a log-time history: seconds are dense, older time is coarser."""
    stamp = time.monotonic() if now is None else float(now)
    samples = _history_samples.setdefault(name, deque(maxlen=_HISTORY_RAW_MAX))
    samples.append((stamp, float(value)))
    buckets: dict[tuple[int, int], list[float]] = {}
    for sample_time, sample_value in samples:
        age = max(0.0, stamp - sample_time)
        if age < 60.0:
            width = 1
        elif age < 600.0:
            width = 5
        elif age < 3600.0:
            width = 30
        elif age < 21600.0:
            width = 300
        else:
            width = 1800
        key = (width, int(age // width))
        buckets.setdefault(key, []).append(sample_value)
    rows = sorted(
        ((key[1] * key[0], sum(values) / len(values)) for key, values in buckets.items()),
        key=lambda row: row[0],
        reverse=True,
    )
    if len(rows) > MAX_HISTORY:
        stride = (len(rows) + MAX_HISTORY - 1) // MAX_HISTORY
        rows = rows[::stride]
        if rows and rows[-1][0] != 0:
            rows.append((0, float(value)))
    return [round(float(row[1]), 2) for row in rows]


def _clk() -> int:
    try:
        value = int(os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, AttributeError):
        return 100
    return value if value > 0 else 100


def _page_kb() -> int:
    try:
        page = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, AttributeError):
        page = 4096
    return max(1, page // 1024)


def _meminfo() -> dict[str, int]:
    data = {
        "total": 0,
        "available": 0,
        "cached": 0,
        "buffers": 0,
        "shared": 0,
        "slab": 0,
        "swap_total": 0,
        "swap_free": 0,
    }
    for line in _read_text(Path("/proc/meminfo"), 8192).splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0]
        try:
            value = int(parts[1])
        except ValueError:
            continue
        if key == "MemTotal:":
            data["total"] = value
        elif key == "MemAvailable:":
            data["available"] = value
        elif key == "Cached:":
            data["cached"] = value
        elif key == "Buffers:":
            data["buffers"] = value
        elif key == "Shmem:":
            data["shared"] = value
        elif key == "SReclaimable:" or key == "Slab:":
            if key == "Slab:":
                data["slab"] = value
        elif key == "SwapTotal:":
            data["swap_total"] = value
        elif key == "SwapFree:":
            data["swap_free"] = value
    used = data["total"] - data["available"] if data["total"] >= data["available"] else 0
    data["used"] = max(0, used)
    data["swap_used"] = max(0, data["swap_total"] - data["swap_free"])
    return data


def _loadavg() -> tuple[float, float, float]:
    parts = _read_text(Path("/proc/loadavg"), 128).split()
    if len(parts) < 3:
        return 0.0, 0.0, 0.0
    try:
        return (
            round(float(parts[0]), 2),
            round(float(parts[1]), 2),
            round(float(parts[2]), 2),
        )
    except ValueError:
        return 0.0, 0.0, 0.0


def _uptime() -> float:
    parts = _read_text(Path("/proc/uptime"), 64).split()
    if not parts:
        return 0.0
    try:
        return float(parts[0])
    except ValueError:
        return 0.0


def _cpu_times() -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    for line in _read_text(Path("/proc/stat"), 8192).splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            nums = [int(item) for item in parts[1:8]]
        except ValueError:
            continue
        total = sum(nums)
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        rows.append((total, idle))
        if len(rows) > MAX_CORES:
            break
    return rows


def _cpu_pcts(now_rows: list[tuple[int, int]]) -> list[float]:
    global _last_cpu
    now = time.monotonic()
    _cpu_win.append((now, now_rows))
    while len(_cpu_win) >= 2 and _cpu_win[1][0] <= now - CPU_WINDOW:
        _cpu_win.popleft()
    t0, prev_rows = _cpu_win[0]
    dt = now - t0
    out: list[float] = []
    for index, current in enumerate(now_rows):
        total, idle = current
        sample = None
        if dt >= MIN_RATE_DT and index < len(prev_rows):
            tick_dt = total - prev_rows[index][0]
            di = idle - prev_rows[index][1]
            if tick_dt > 0:
                sample = max(0.0, min(100.0, (1.0 - di / tick_dt) * 100.0))
        if sample is None:
            sample = _last_cpu[index] if index < len(_last_cpu) else 0.0
        out.append(round(float(sample), 1))
    _last_cpu = out
    return out


def _cpu_mhz() -> list[int]:
    mhz: list[int] = []
    cpu_root = Path("/sys/devices/system/cpu")
    try:
        names = sorted(
            cpu_root.iterdir(),
            key=lambda item: int(item.name[3:])
            if item.name.startswith("cpu") and item.name[3:].isdigit()
            else 10**6,
        )
    except OSError:
        names = []
    for entry in names:
        if not entry.name.startswith("cpu") or not entry.name[3:].isdigit():
            continue
        raw = _read_text(entry / "cpufreq/scaling_cur_freq", 64).strip()
        if not raw:
            raw = _read_text(entry / "cpufreq/cpuinfo_cur_freq", 64).strip()
        try:
            mhz.append(int(raw) // 1000)
        except ValueError:
            mhz.append(0)
        if len(mhz) >= MAX_CORES:
            break
    if mhz:
        return mhz
    for line in _read_text(Path("/proc/cpuinfo"), 65536).splitlines():
        if not line.lower().startswith("cpu mhz"):
            continue
        try:
            mhz.append(int(float(line.split(":")[-1].strip())))
        except ValueError:
            continue
        if len(mhz) >= MAX_CORES:
            break
    return mhz


def _cpu_model() -> str:
    for line in _read_text(Path("/proc/cpuinfo"), 8192).splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[-1].strip()[:80]
    return ""


_TEMP_FILES: tuple[float, list[tuple[str, str, str]]] | None = None
_TEMP_DISC_TTL = 30.0
_SLOW_CHIPS = ("nvme", "pch", "bat", "hp", "acad", "iwlwifi", "amdgpu")


def _chip_slow(chip: str) -> bool:
    low = chip.lower()
    return any(low.startswith(prefix) for prefix in _SLOW_CHIPS)


def _discover_temp_files() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    hwmon = Path("/sys/class/hwmon")
    try:
        chips = sorted(hwmon.glob("hwmon*"))
    except OSError:
        chips = []
    for chip in chips:
        label = _read_text(chip / "name", 64).strip() or chip.name
        if _chip_slow(label):
            continue
        for temp_file in sorted(chip.glob("temp*_input")):
            sibling = temp_file.name.replace("_input", "_label")
            named = _read_text(chip / sibling, 64).strip()
            tag = named or label
            rows.append((str(temp_file), tag[:24], label[:16]))
            if len(rows) >= 12:
                break
        if len(rows) >= 12:
            break
    rows.sort(
        key=lambda item: (
            0
            if "pkg" in item[1].lower()
            or item[2] in {"coretemp", "k10temp", "zenpower"}
            else 1,
            item[2],
        )
    )
    return rows


def _temp_files() -> list[tuple[str, str, str]]:
    global _TEMP_FILES
    now = time.monotonic()
    hit = _TEMP_FILES
    if hit is not None and now - hit[0] < _TEMP_DISC_TTL:
        return hit[1]
    rows = _discover_temp_files()
    _TEMP_FILES = (now, rows)
    return rows


def _temps(limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cap = max(1, min(10, int(limit)))
    for path, tag, chip in _temp_files():
        raw = _read_text(Path(path), 32).strip()
        try:
            celsius = int(raw) / 1000.0
        except ValueError:
            continue
        if celsius < 20 or celsius > 110:
            continue
        rows.append({"name": tag, "c": round(celsius, 1), "chip": chip})
        if len(rows) >= cap:
            break
    rows.sort(
        key=lambda item: (
            0 if "pkg" in item["name"].lower() or item.get("chip") == "coretemp" else 1,
            -float(item["c"]),
        )
    )
    return rows


def _net_bytes() -> tuple[int, int, str]:
    rx = 0
    tx = 0
    primary = ""
    best = 0
    for line in _read_text(Path("/proc/net/dev"), 8192).splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        iface = name.strip()
        if iface in {"lo", ""}:
            continue
        parts = rest.split()
        if len(parts) < 10:
            continue
        try:
            irx = int(parts[0])
            itx = int(parts[8])
        except ValueError:
            continue
        rx += irx
        tx += itx
        if irx + itx > best:
            best = irx + itx
            primary = iface
    return rx, tx, primary


def _disk_bytes() -> tuple[int, int]:
    read_s = 0
    write_s = 0
    for line in _read_text(Path("/proc/diskstats"), 16384).splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        if name.startswith("loop") or name.startswith("ram") or name.startswith("dm-"):
            continue
        if any(name.startswith(prefix) and name != prefix and name[-1].isdigit()
               for prefix in ("sd", "vd", "nvme", "hd")):
            if "nvme" in name and "p" in name:
                continue
            if name[-1].isdigit() and "nvme" not in name:
                continue
        try:
            read_s += int(parts[5])
            write_s += int(parts[9])
        except ValueError:
            continue
    return read_s * 512, write_s * 512


def _io_rate(
    win: deque[tuple[float, int, int]],
    now: float,
    a: int,
    b: int,
    span: float,
    held: list[int],
) -> tuple[int, int]:
    win.append((now, a, b))
    while len(win) >= 2 and win[1][0] <= now - span:
        win.popleft()
    t0, a0, b0 = win[0]
    dt = now - t0
    if dt < MIN_RATE_DT:
        return held[0], held[1]
    held[0] = max(0, int(round((a - a0) / dt)))
    held[1] = max(0, int(round((b - b0) / dt)))
    return held[0], held[1]


_UID_NAMES: dict[int, str] = {}
_HOST_IDENTITY: dict[str, str] | None = None
_NAME_CACHE: dict[str, tuple[float, list[str]]] = {}
_APPIMAGE_CACHE: tuple[float, str] | None = None
_NAME_TTL = 20.0
_APPIMAGE_TTL = 30.0


def _user_name(uid: int) -> str:
    hit = _UID_NAMES.get(uid)
    if hit is not None:
        return hit
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = str(uid)
    _UID_NAMES[uid] = name
    return name


def _os_name() -> str:
    for line in _read_text(Path("/etc/os-release"), 2048).splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')[:48]
    return os.uname().sysname[:48]


def _host_identity() -> dict[str, str]:
    global _HOST_IDENTITY
    if _HOST_IDENTITY is not None:
        return _HOST_IDENTITY
    _HOST_IDENTITY = {
        "hostname": socket.gethostname()[:48],
        "kernel": os.uname().release[:48],
        "cpu_model": _cpu_model(),
        "os": _os_name(),
    }
    return _HOST_IDENTITY


def _cached_names(key: str, folder: Path, suffix: str) -> list[str]:
    now = time.monotonic()
    hit = _NAME_CACHE.get(key)
    if hit is not None and now - hit[0] < _NAME_TTL:
        return hit[1]
    rows = _names_from_dir(folder, suffix)
    _NAME_CACHE[key] = (now, rows)
    return rows


def _cached_appimage() -> str:
    global _APPIMAGE_CACHE
    now = time.monotonic()
    hit = _APPIMAGE_CACHE
    if hit is not None and now - hit[0] < _APPIMAGE_TTL:
        return hit[1]
    app = resolve_appimage()
    path = str(app) if app is not None else ""
    _APPIMAGE_CACHE = (now, path)
    return path


def _fill_proc(row: dict[str, Any]) -> dict[str, Any]:
    proc_dir = row.pop("_dir", None)
    if not isinstance(proc_dir, Path):
        return row
    comm = _read_text(proc_dir / "comm", 64).strip() or "?"
    cmdline = _read_text(proc_dir / "cmdline", 512).replace("\x00", " ").strip()
    if len(cmdline) > MAX_CMDLINE:
        cmdline = cmdline[: MAX_CMDLINE - 1] + "…"
    row["comm"] = comm[:32]
    row["cmdline"] = cmdline
    return row


def _task_hint() -> tuple[int, int]:
    parts = _read_text(Path("/proc/loadavg"), 64).split()
    if len(parts) < 4 or "/" not in parts[3]:
        return 0, 0
    run_s, total_s = parts[3].split("/", 1)
    try:
        return int(run_s), int(total_s)
    except ValueError:
        return 0, 0


def _processes(
    now: float,
    dt: float,
    clk: int,
    fill_limit: int = MAX_PROCESSES,
    need_users: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    global _prev_times, _last_proc, _tombstones
    scanned: list[tuple[float, int, int, Path, str, int, int, int]] = []
    next_times: dict[int, tuple[float, int]] = {}
    users: dict[str, int] = {}
    running = 0
    page = _page_kb()
    try:
        entries = os.scandir("/proc")
    except OSError:
        entries = None
    if entries is not None:
        with entries:
            for ent in entries:
                if not ent.name.isdigit():
                    continue
                try:
                    pid = int(ent.name)
                except ValueError:
                    continue
                try:
                    with open(ent.path + "/stat", "r", encoding="utf-8", errors="replace") as fh:
                        stat = fh.read(2048)
                except OSError:
                    continue
                if not stat:
                    continue
                rparen = stat.rfind(")")
                if rparen < 0:
                    continue
                rest = stat[rparen + 2 :].split()
                if len(rest) < 22:
                    continue
                state = rest[0]
                try:
                    ppid = int(rest[1])
                    utime = int(rest[11])
                    stime = int(rest[12])
                    threads = int(rest[17])
                    vsize = int(rest[20])
                    rss_pages = int(rest[21])
                except ValueError:
                    continue
                ticks = utime + stime
                next_times[pid] = (now, ticks)
                cpu_pct = 0.0
                prev = _prev_times.get(pid)
                if prev is not None and dt > 0.05:
                    cpu_pct = max(0.0, min(100.0, (ticks - prev[1]) / clk / dt * 100.0))
                if state == "R":
                    running += 1
                if need_users:
                    try:
                        uid = ent.stat().st_uid
                    except OSError:
                        uid = os.getuid()
                    user = _user_name(uid)
                    users[user] = users.get(user, 0) + 1
                scanned.append(
                    (
                        cpu_pct,
                        max(0, rss_pages * page),
                        pid,
                        Path(ent.path),
                        state[:1],
                        ppid,
                        max(1, threads),
                        max(0, vsize // 1024),
                    )
                )
                if len(next_times) >= MAX_SCAN:
                    break
    gone = set(_last_proc) - set(next_times)
    for pid in gone:
        marker = dict(_last_proc.pop(pid))
        marker.pop("_dir", None)
        marker["tombstone"] = True
        marker["status"] = "Tombstone"
        marker["state"] = "X"
        marker["cpu_pct"] = 0.0
        marker["gone_at"] = now
        _tombstones[pid] = marker
    for pid, marker in list(_tombstones.items()):
        if pid in next_times or now - float(marker.get("gone_at") or 0) > _TOMBSTONE_TTL:
            _tombstones.pop(pid, None)
    _prev_times = next_times
    scanned.sort(key=lambda item: (item[0], item[1]), reverse=True)
    stones = list(_tombstones.values())
    stones.sort(key=lambda item: float(item.get("gone_at") or 0), reverse=True)
    shown_cap = max(0, min(MAX_PROCESSES, int(fill_limit)))
    live_cap = max(0, shown_cap - len(stones))
    kept_src = scanned[:live_cap]
    kept: list[dict[str, Any]] = []
    fill_n = max(0, min(len(kept_src), int(fill_limit)))
    for index, item in enumerate(kept_src):
        cpu_pct, rss_kb, pid, proc_dir, state, ppid, threads, virt_kb = item
        row = {
            "pid": pid,
            "ppid": ppid,
            "comm": "",
            "state": state,
            "status": PROC_STATES.get(state, state),
            "user": "",
            "rss_kb": rss_kb,
            "virt_kb": virt_kb,
            "cpu_pct": round(cpu_pct, 1),
            "threads": threads,
            "cmdline": "",
            "tombstone": False,
            "_dir": proc_dir,
        }
        prev = _last_proc.get(pid)
        if prev:
            row["comm"] = str(prev.get("comm") or "")
            row["cmdline"] = str(prev.get("cmdline") or "")
            row["user"] = str(prev.get("user") or "")
        if index < fill_n:
            _fill_proc(row)
            if not row.get("user"):
                try:
                    row["user"] = _user_name(proc_dir.stat().st_uid)[:24]
                except OSError:
                    row["user"] = _user_name(os.getuid())[:24]
        row.pop("_dir", None)
        kept.append(row)
    _last_proc = {int(row["pid"]): dict(row) for row in kept}
    _flight_history.append(
        {
            "t": round(float(now), 3),
            "processes": [
                {
                    "pid": int(row.get("pid") or 0),
                    "comm": str(row.get("comm") or ""),
                    "cpu_pct": float(row.get("cpu_pct") or 0.0),
                    "rss_kb": int(row.get("rss_kb") or 0),
                }
                for row in kept[:17]
                if not row.get("tombstone")
            ],
        }
    )
    shown = stones + kept
    counts = {
        "running": running,
        "total": len(next_times),
        "shown": len(shown),
        "tombstones": len(stones),
    }
    return shown, counts, users


def _mounts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in _read_text(Path("/proc/mounts"), 16384).splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        src, dest, fstype = parts[0], parts[1], parts[2]
        if fstype in _MOUNT_SKIP:
            continue
        if not dest.startswith("/") or dest in seen:
            continue
        seen.add(dest)
        try:
            st = os.statvfs(dest)
        except OSError:
            continue
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        used = max(0, total - free)
        if total <= 0:
            continue
        rows.append(
            {
                "path": dest[:48],
                "src": src[:32],
                "fstype": fstype[:12],
                "used": used,
                "total": total,
            }
        )
        if len(rows) >= MAX_MOUNTS:
            break
    rows.sort(key=lambda item: int(item["total"]), reverse=True)
    return rows


def _endpoint(ip: str, port: str) -> str:
    host = str(ip or "")
    if ":" in host:
        return "[" + host + "]:" + str(port or "")
    return host + ":" + str(port or "")


def _hex_ip(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) == 8:
        try:
            parts = [str(int(raw[i : i + 2], 16)) for i in (6, 4, 2, 0)]
            return ".".join(parts)
        except ValueError:
            return raw
    if len(raw) == 32:
        return _hex_ip6(raw)
    return raw


def _hex_ip6(value: str) -> str:
    chunks: list[str] = []
    try:
        for i in range(0, 32, 8):
            word = value[i : i + 8]
            le = word[6:8] + word[4:6] + word[2:4] + word[0:2]
            chunks.append(le[:4])
            chunks.append(le[4:8])
    except (ValueError, IndexError):
        return value
    groups = [item.lstrip("0") or "0" for item in chunks]
    best_i = -1
    best_n = 1
    i = 0
    while i < 8:
        if groups[i] != "0":
            i += 1
            continue
        j = i
        while j < 8 and groups[j] == "0":
            j += 1
        if j - i > best_n:
            best_i = i
            best_n = j - i
        i = j
    if best_i >= 0:
        head = ":".join(groups[:best_i])
        tail = ":".join(groups[best_i + best_n :])
        if head and tail:
            return head + "::" + tail
        if tail:
            return "::" + tail
        if head:
            return head + "::"
        return "::"
    return ":".join(groups)


def _inode_owners() -> dict[str, dict[str, Any]]:
    global _inode_cache
    now = time.monotonic()
    hit_t, hit = _inode_cache
    if now - hit_t < 2.0:
        return hit
    mapping: dict[str, dict[str, Any]] = {}
    scanned = 0
    try:
        entries = os.scandir("/proc")
    except OSError:
        _inode_cache = (now, mapping)
        return mapping
    with entries:
        for ent in entries:
            if not ent.name.isdigit():
                continue
            pid = int(ent.name)
            comm = ""
            try:
                with open(ent.path + "/comm", "r", encoding="utf-8", errors="replace") as fh:
                    comm = fh.read(32).strip()[:24]
            except OSError:
                comm = ""
            try:
                fds = os.scandir(ent.path + "/fd")
            except OSError:
                continue
            with fds:
                for fd in fds:
                    try:
                        target = os.readlink(fd.path)
                    except OSError:
                        continue
                    if not target.startswith("socket:["):
                        continue
                    inode = target[8:-1]
                    if inode and inode not in mapping:
                        mapping[inode] = {"pid": pid, "comm": comm}
            scanned += 1
            if scanned >= 220:
                break
    _inode_cache = (now, mapping)
    return mapping


def _connections() -> list[dict[str, Any]]:
    owners = _inode_owners()
    rows: list[dict[str, Any]] = []
    for path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        lines = _read_text(path, 131072).splitlines()[1:]
        for line in lines:
            parts = line.split()
            if len(parts) < 10:
                continue
            local = parts[1]
            remote = parts[2]
            state = TCP_STATES.get(parts[3].upper(), parts[3])
            inode = parts[9]
            lip, _, lport = local.partition(":")
            rip, _, rport = remote.partition(":")
            try:
                lp = str(int(lport, 16))
                rp = str(int(rport, 16))
            except ValueError:
                lp, rp = lport, rport
            owner = owners.get(inode) or {}
            rows.append(
                {
                    "local": _endpoint(_hex_ip(lip), lp),
                    "remote": _endpoint(_hex_ip(rip), rp),
                    "state": state,
                    "pid": int(owner.get("pid") or 0),
                    "comm": str(owner.get("comm") or ""),
                }
            )
            if len(rows) >= MAX_CONNS:
                return rows
    return rows


def _rapl_watts(now: float) -> float | None:
    global _prev_rapl
    raw = _read_text(_RAPL_PATH, 32).strip()
    if not raw:
        return None
    try:
        uj = int(raw)
    except ValueError:
        return None
    prev_t, prev_uj = _prev_rapl
    _prev_rapl = (now, uj)
    if prev_t <= 0 or now <= prev_t:
        return None
    watts = (uj - prev_uj) / (now - prev_t) / 1_000_000.0
    if watts < 0 or watts > 400:
        return None
    return round(watts, 1)


def _energy(now: float | None = None) -> dict[str, Any]:
    supply = Path("/sys/class/power_supply")
    payload = {
        "source": "",
        "watts": None,
        "battery_pct": None,
        "charging": False,
    }
    try:
        nodes = sorted(supply.iterdir())
    except OSError:
        nodes = []
    for node in nodes:
        kind = _read_text(node / "type", 32).strip().upper()
        if kind == "MAINS" or kind == "ADP":
            online = _read_text(node / "online", 16).strip() == "1"
            if online:
                payload["source"] = "AC"
        if kind == "BAT":
            cap = _read_text(node / "capacity", 16).strip()
            try:
                payload["battery_pct"] = int(cap)
            except ValueError:
                pass
            status = _read_text(node / "status", 32).strip().lower()
            payload["charging"] = status == "charging"
            if not payload["source"]:
                payload["source"] = "BATTERY"
        micro = _read_text(node / "power_now", 32).strip()
        if not micro:
            continue
        try:
            payload["watts"] = round(int(micro) / 1_000_000.0, 1)
        except ValueError:
            continue
    if payload["watts"] is None:
        rapl = _rapl_watts(now if now is not None else time.monotonic())
        if rapl is not None:
            payload["watts"] = rapl
    if not payload["source"]:
        payload["source"] = "AC"
    return payload


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _safe_listed_file(path: Path) -> Path | None:
    try:
        if path.is_symlink():
            real = path.resolve()
            if not any(_under_root(real, root) for root in _DESKTOP_ROOTS):
                return None
            if not real.is_file():
                return None
            return real
        if path.is_file():
            return path
    except OSError:
        return None
    return None


def _parse_desktop(path: Path) -> dict[str, Any] | None:
    text = _read_text(path, 4096)
    if not text:
        return None
    name = path.stem[:48]
    hidden = False
    nodisplay = False
    kind = "Application"
    for line in text.splitlines():
        if line.startswith("Name=") and "=" in line:
            name = line.split("=", 1)[1].strip()[:48] or name
        elif line.startswith("Hidden="):
            hidden = line.split("=", 1)[1].strip().lower() == "true"
        elif line.startswith("NoDisplay="):
            nodisplay = line.split("=", 1)[1].strip().lower() == "true"
        elif line.startswith("Type="):
            kind = line.split("=", 1)[1].strip() or kind
    if kind and kind != "Application":
        return None
    return {
        "id": path.stem[:40],
        "name": name,
        "hidden": hidden,
        "nodisplay": nodisplay,
        "path": str(path)[:160],
    }


def _desktop_entries(folders: tuple[Path, ...], *, apps: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for folder in folders:
        try:
            entries = sorted(folder.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for entry in entries:
            if not entry.name.endswith(".desktop"):
                continue
            real = _safe_listed_file(entry)
            if real is None:
                continue
            parsed = _parse_desktop(real)
            if parsed is None:
                continue
            key = str(parsed["id"])
            if key in seen:
                continue
            if apps and (parsed["hidden"] or parsed["nodisplay"]):
                continue
            seen.add(key)
            rows.append(parsed)
            if len(rows) >= MAX_NAMES:
                return rows
    rows.sort(key=lambda item: str(item.get("name") or "").lower())
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("name") or "")
        counts[key] = counts.get(key, 0) + 1
    for row in rows:
        key = str(row.get("name") or "")
        if counts.get(key, 0) > 1:
            row["name"] = key + "  " + str(row.get("id") or "")
    return rows[:MAX_NAMES]


def _startup_entries() -> list[dict[str, Any]]:
    return _desktop_entries(
        (Path.home() / ".config/autostart", Path("/etc/xdg/autostart")),
        apps=False,
    )


def _app_entries() -> list[dict[str, Any]]:
    return _desktop_entries(
        (
            Path.home() / ".local/share/applications",
            Path("/usr/share/applications"),
            Path("/usr/local/share/applications"),
        ),
        apps=True,
    )


def _service_entries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(name: str, state: str, scope: str) -> None:
        key = name + ":" + scope
        if key in seen or not name:
            return
        seen.add(key)
        rows.append(
            {
                "id": name[:48],
                "name": name[:48],
                "state": state,
                "scope": scope,
            }
        )

    slices = [Path("/sys/fs/cgroup/system.slice")]
    uid = os.getuid()
    slices.append(
        Path(
            f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice"
        )
    )
    slices.append(Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice"))
    for folder in slices:
        try:
            entries = folder.iterdir()
        except OSError:
            continue
        scope = "user" if "user.slice" in str(folder) else "system"
        for entry in entries:
            if not entry.name.endswith(".service"):
                continue
            add(entry.name[: -len(".service")], "running", scope)
            if len(rows) >= MAX_NAMES:
                rows.sort(key=lambda item: str(item.get("name") or "").lower())
                return rows
    rows.sort(key=lambda item: str(item.get("name") or "").lower())
    return rows


def _names_from_dir(folder: Path, suffix: str) -> list[str]:
    names: list[str] = []
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    for entry in entries:
        real = _safe_listed_file(entry)
        if real is None:
            continue
        if suffix and not entry.name.endswith(suffix):
            continue
        names.append(entry.stem[:40] if suffix == ".desktop" else entry.name[:40])
        if len(names) >= MAX_NAMES:
            break
    return names


_last_snap: tuple[float, str, dict[str, Any]] | None = None
_SNAP_DEBOUNCE = 0.18
_last_mhz_val = 0
_last_mhz_max = 0
_last_mhz_at = 0.0
_last_temp_c = 0.0


def _refresh_slow_meters(now: float, force: bool = False) -> None:
    global _last_mhz_val, _last_mhz_max, _last_mhz_at, _last_temp_c
    if not force and _last_mhz_at and now - _last_mhz_at < 0.75:
        return
    mhz = _cpu_mhz()
    _last_mhz_val = mhz[0] if mhz else 0
    _last_mhz_max = max(mhz) if mhz else 0
    _last_mhz_at = now
    temps = _temps(1)
    if temps:
        _last_temp_c = float(temps[0]["c"])


def _gpu_busy() -> float | None:
    global _gpu_busy_path, _gpu_busy_tried
    if not _gpu_busy_tried:
        _gpu_busy_tried = True
        drm = Path("/sys/class/drm")
        if drm.is_dir():
            for card in sorted(drm.glob("card*/device/gpu_busy_percent")):
                _gpu_busy_path = card
                break
    if _gpu_busy_path is None:
        value = _nvml_gpu_busy()
        return value if value is not None else _nvidia_gpu_busy()
    try:
        raw = _gpu_busy_path.read_text(encoding="ascii").strip()
        return float(raw or "0")
    except (OSError, ValueError):
        pass
    value = _nvml_gpu_busy()
    return value if value is not None else _nvidia_gpu_busy()


def _pressure() -> dict[str, float | None]:
    """Read Linux pressure stall averages without spawning a helper process."""
    values: dict[str, float | None] = {"cpu_some": None, "memory_some": None}
    for key, path in (
        ("cpu_some", Path("/proc/pressure/cpu")),
        ("memory_some", Path("/proc/pressure/memory")),
    ):
        line = _read_text(path, 512).splitlines()
        if not line:
            continue
        for token in line[0].split():
            if not token.startswith("avg10="):
                continue
            try:
                values[key] = round(float(token.split("=", 1)[1]), 2)
            except ValueError:
                pass
            break
    return values


def _gpu_rows(gpu_busy: float | None, temp_c: float) -> list[dict[str, Any]]:
    """Return lightweight GPU identity rows for the summary and system views."""
    rows: list[dict[str, Any]] = []
    drm = Path("/sys/class/drm")
    try:
        cards = sorted(drm.glob("card[0-9]"))
    except OSError:
        cards = []
    for index, card in enumerate(cards):
        device = card / "device"
        try:
            driver = device / "driver"
            driver_name = driver.resolve().name if driver.exists() else ""
        except OSError:
            driver_name = ""
        vendor = _read_text(device / "vendor", 32).strip()
        device_id = _read_text(device / "device", 32).strip()
        name = driver_name or card.name
        if vendor and device_id:
            name += " " + vendor + ":" + device_id
        rows.append(
            {
                "id": index,
                "name": name[:64],
                "busy": round(float(gpu_busy or 0.0), 1) if index == 0 else 0.0,
                "temp_c": round(float(temp_c), 1) if index == 0 else 0.0,
            }
        )
        if len(rows) >= 4:
            break
    if not rows and gpu_busy is not None:
        rows.append(
            {
                "id": 0,
                "name": "GPU 0",
                "busy": round(float(gpu_busy), 1),
                "temp_c": round(float(temp_c), 1),
            }
        )
    return rows


def _drivers() -> list[dict[str, Any]]:
    """List loaded kernel modules, matching TMOG's driver inspection purpose."""
    rows: list[dict[str, Any]] = []
    for line in _read_text(Path("/proc/modules"), 65536).splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        size = parts[1] if len(parts) > 1 else "0"
        users = parts[2] if len(parts) > 2 else "0"
        rows.append({"name": name[:48], "size": size, "users": users})
        if len(rows) >= MAX_NAMES:
            break
    return rows


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


def _nvml_gpu_busy() -> float | None:
    """Read NVIDIA utilization directly; never spawn nvidia-smi per frame."""
    global _nvml, _nvml_handle, _nvml_tried
    if _nvml_tried:
        if _nvml is None or _nvml_handle is None:
            return None
    else:
        _nvml_tried = True
        try:
            lib = ctypes.CDLL("libnvidia-ml.so.1")
            if lib.nvmlInit_v2() != 0:
                return None
            count = ctypes.c_uint()
            if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0 or count.value < 1:
                return None
            handle = ctypes.c_void_p()
            if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                return None
            _nvml, _nvml_handle = lib, handle
        except (AttributeError, OSError):
            return None
    util = _NvmlUtilization()
    try:
        result = _nvml.nvmlDeviceGetUtilizationRates(
            _nvml_handle, ctypes.byref(util)
        )
    except (AttributeError, OSError):
        return None
    return float(util.gpu) if result == 0 else None


def _nvidia_worker() -> None:
    global _nvidia_value
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        value = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        _nvidia_value = float(value) if value else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        _nvidia_value = None


def _nvidia_gpu_busy() -> float | None:
    """Use nvidia-smi off the GUI thread when NVML is unavailable."""
    global _nvidia_thread, _nvidia_next_poll
    now = time.monotonic()
    thread = _nvidia_thread
    if (thread is None or not thread.is_alive()) and now >= _nvidia_next_poll:
        _nvidia_next_poll = now + 2.0
        _nvidia_thread = threading.Thread(target=_nvidia_worker, name="gg-nvidia-meter", daemon=True)
        _nvidia_thread.start()
    return _nvidia_value


def pulse() -> dict[str, Any]:
    if os.name == "nt":
        from backend.windows_telemetry import pulse as windows_pulse
        return windows_pulse()
    global _prev_mono
    now = time.monotonic()
    dt = now - _prev_mono if _prev_mono else 0.0
    mem = _meminfo()
    load1, load5, load15 = _loadavg()
    cpu_pcts = _cpu_pcts(_cpu_times())
    overall = cpu_pcts[0] if cpu_pcts else 0.0
    _refresh_slow_meters(now)
    energy = _energy(now)
    rx, tx, iface = _net_bytes()
    rx_bps, tx_bps = _io_rate(_net_win, now, rx, tx, IO_WINDOW, _last_net)
    dread, dwrite = _disk_bytes()
    read_bps, write_bps = _io_rate(
        _disk_win, now, dread, dwrite, IO_WINDOW, _last_disk
    )
    _prev_mono = now
    mem_pct = (mem["used"] / mem["total"] * 100.0) if mem["total"] else 0.0
    return {
        "schema": SCHEMA,
        "cpu_busy": overall,
        "cores": [float(pct) for pct in cpu_pcts[1:MAX_CORES + 1]],
        "mhz": _last_mhz_val,
        "mhz_max": _last_mhz_max,
        "temp_c": _last_temp_c,
        "mem_used_kb": mem["used"],
        "mem_total_kb": mem["total"],
        "mem_pct": round(mem_pct, 2),
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "net_iface": iface,
        "net_rx_bps": rx_bps,
        "net_tx_bps": tx_bps,
        "disk_read_bps": read_bps,
        "disk_write_bps": write_bps,
        "gpu_busy": _gpu_busy(),
        "energy_w": energy.get("watts"),
        "energy_source": energy.get("source") or "AC",
        "dt": round(dt, 4),
    }


def snapshot(page: str = "", *, live: dict[str, Any] | None = None) -> dict[str, Any]:
    if os.name == "nt":
        from backend.windows_telemetry import snapshot as windows_snapshot
        return windows_snapshot(page, live=live)
    global _snapshot_mono, _last_snap
    kind = str(page or "").strip().upper()
    full = kind == ""
    now = time.monotonic()
    hit = _last_snap
    if hit is not None and hit[1] == kind and now - hit[0] < _SNAP_DEBOUNCE:
        return hit[2]
    want_procs = full or kind in {"SUMMARY", "PROCESSES", "USERS", "FLIGHT"}
    want_conns = full or kind == "CONNECTIONS"
    want_mounts = full or kind == "DISK"
    want_names = full or kind in {"STARTUP", "APPS", "SERVICES"}
    want_cores = full or kind in {"PERFORMANCE", "FREQ"}
    want_core_hist = full or kind == "PERFORMANCE"
    want_gpus = full or kind in {"SUMMARY", "PERFORMANCE", "SYSTEM"}
    want_drivers = full or kind == "DRIVERS"
    dt = now - _snapshot_mono if _snapshot_mono else 0.0
    clk = _clk()
    mem = _meminfo()
    load1, load5, load15 = _loadavg()
    cpu_pcts = (_cpu_pcts(_cpu_times()) if live is None else
                [float(live.get("cpu_busy") or 0)] + list(live.get("cores") or []))
    overall = cpu_pcts[0] if cpu_pcts else 0.0
    mhz = _cpu_mhz()
    if live is None:
        _refresh_slow_meters(now, force=True)
    gpu_busy = _gpu_busy() if live is None else live.get("gpu_busy")
    per_core = cpu_pcts[1:]
    while len(_core_hist) < len(per_core):
        _core_hist.append([])
    cores: list[dict[str, Any]] = []
    core_hist: list[list[float]] = []
    for index, pct in enumerate(per_core):
        _push(_core_hist[index], float(pct))
        if want_cores:
            cores.append(
                {
                    "id": index,
                    "pct": pct,
                    "mhz": mhz[index] if index < len(mhz) else 0,
                }
            )
        if want_core_hist:
            core_hist.append(list(_core_hist[index]))
    temps = _temps(1 if kind == "SUMMARY" else 3)
    temp_c = temps[0]["c"] if temps else 0.0
    energy = (_energy(now) if live is None else
              {"watts": live.get("energy_w"), "source": live.get("energy_source") or "AC"})
    pressure = _pressure()
    if live is None:
        rx, tx, iface = _net_bytes()
        rx_bps, tx_bps = _io_rate(_net_win, now, rx, tx, IO_WINDOW, _last_net)
        dread, dwrite = _disk_bytes()
        read_bps, write_bps = _io_rate(
            _disk_win, now, dread, dwrite, IO_WINDOW, _last_disk
        )
    else:
        iface = str(live.get("net_iface") or "")
        rx_bps, tx_bps = live.get("net_rx_bps", 0), live.get("net_tx_bps", 0)
        read_bps, write_bps = live.get("disk_read_bps", 0), live.get("disk_write_bps", 0)
    procs: list[dict[str, Any]] = []
    users: dict[str, int] = {}
    if want_procs:
        fill_limit = 17 if kind in {"SUMMARY", "FLIGHT"} else MAX_PROCESSES
        procs, tasks, users = _processes(
            now,
            dt,
            clk,
            fill_limit=fill_limit,
            need_users=full or kind == "USERS",
        )
    else:
        run, total = _task_hint()
        tasks = {"running": run, "total": total, "tombstones": 0}
    _snapshot_mono = now
    user_rows = [
        {"name": name, "procs": count}
        for name, count in sorted(users.items(), key=lambda item: item[1], reverse=True)[:16]
    ]
    ident = _host_identity()
    app = _cached_appimage()
    gpus = _gpu_rows(gpu_busy, temp_c) if want_gpus else []
    payload = {
        "schema": SCHEMA,
        "cpu_busy": overall,
        "cpu_model": ident["cpu_model"],
        "cores": cores,
        "mhz": mhz[0] if mhz else 0,
        "mhz_max": max(mhz) if mhz else 0,
        "temps": temps,
        "temp_c": temp_c,
        "gpu_busy": float(gpu_busy or 0.0),
        "mem_used_kb": mem["used"],
        "mem_total_kb": mem["total"],
        "mem_cached_kb": mem["cached"],
        "mem_avail_kb": mem["available"],
        "mem_buffers_kb": mem["buffers"],
        "mem_shared_kb": mem["shared"],
        "mem_slab_kb": mem["slab"],
        "swap_used_kb": mem["swap_used"],
        "swap_total_kb": mem["swap_total"],
        "energy": energy,
        "pressure": pressure,
        "gpus": gpus,
        "drivers": _drivers() if want_drivers else [],
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "uptime_s": int(_uptime()),
        "hostname": ident["hostname"],
        "kernel": ident["kernel"],
        "os": ident.get("os") or "",
        "core_count": max(len(per_core), len(mhz)),
        "process_count": tasks["total"],
        "tasks_running": tasks["running"],
        "net_iface": iface,
        "net_rx_bps": rx_bps,
        "net_tx_bps": tx_bps,
        "disk_read_bps": read_bps,
        "disk_write_bps": write_bps,
        "disk_led": round(min(1.0, (read_bps + write_bps) / float(8 * 1024 * 1024)), 3),
        "tombstones": int(tasks.get("tombstones") or 0),
        "cpu_hist": _history("cpu", overall, now),
        "core_hist": core_hist,
        "mem_hist": _history(
            "memory",
            (mem["used"] / mem["total"] * 100.0) if mem["total"] else 0.0,
            now,
        ),
        "net_hist": _history("network", (rx_bps + tx_bps) / 1024.0, now),
        "disk_hist": _history("disk", (read_bps + write_bps) / 1024.0, now),
        "temp_hist": _history("temperature", temp_c, now),
        "mhz_hist": _history("clock", float(mhz[0] if mhz else 0.0), now),
        "gpu_hist": _history("gpu", float(gpu_busy or 0.0), now),
        "energy_hist": _history("energy", float(energy.get("watts") or 0.0), now),
        "processes": procs,
        "users": user_rows,
        "mounts": _mounts() if want_mounts else [],
        "connections": _connections() if want_conns else [],
        "startup": _startup_entries() if want_names else [],
        "apps": _app_entries() if want_names else [],
        "services": _service_entries() if want_names else [],
        "flight_history": list(_flight_history)
        if full or kind in {"PERFORMANCE", "FLIGHT"}
        else [],
        "appimage": app,
        "appimage_found": bool(app),
        "page": kind or "FULL",
    }
    _last_snap = (now, kind, payload)
    return payload


def format_kib(value: int) -> str:
    amount = max(0, int(value))
    if amount >= 1024 * 1024:
        return str(round(amount / 1024 / 1024, 1)) + " GiB"
    if amount >= 1024:
        return str(round(amount / 1024, 1)) + " MiB"
    return str(amount) + " KiB"
