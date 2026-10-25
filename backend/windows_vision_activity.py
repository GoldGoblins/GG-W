"""Bounded observation activity shared through Windows RAM, never image data.

The desktop retains this module's channel handle. Short-lived CLI and capture
workers can then publish activity without files, sockets, or a capture daemon.
"""
from __future__ import annotations

import atexit
import copy
import hashlib
import json
import math
import mmap
import os
import struct
import threading
import time
import uuid

from backend.application_paths import STATE_ROOT

CHANNEL_BYTES = 16 * 1024
MAX_ACTIVE = 8
RECENT_SECONDS = 3.0
KINDS = frozenset({"frame", "clip", "video"})
_ERRORS = frozenset({"TimeoutError", "RuntimeError", "ValueError", "OSError",
                     "ConnectionError", "JSONDecodeError", "CaptureError",
                     "NoFrames", "OwnerExited", "TIMEOUT", "OUTPUT_LIMIT", "CANCELLED"})


def _alive(pid: int) -> bool:
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        return False
    import psutil
    try:
        return psutil.pid_exists(pid)
    except (OverflowError, ValueError):
        return False
    except (OSError, psutil.Error):
        # A denied query is not evidence of death; the deadline still bounds it.
        return True


def _number(value, *, maximum: float = 1e15) -> bool:
    # Check the range before isfinite so corrupt huge integers cannot overflow
    # Python's float conversion.
    return (type(value) in (int, float) and 0 <= value <= maximum
            and math.isfinite(value))


def _error(value: str | None) -> str:
    # Exceptions can contain file paths, URLs and other private input.
    return value if type(value) is str and value in _ERRORS else "CaptureError"


class _MemoryStore:
    """Pure in-memory state machine; clock and owner checks are injectable."""

    def __init__(self, *, clock=time.monotonic, alive=_alive, pid=None, data=None):
        self.clock, self.alive = clock, alive
        self.pid = os.getpid() if pid is None else pid
        self.data = {"version": 1, "generation": 0, "active": {}, "recent": None}
        if data is not None:
            self._restore(data)

    def _restore(self, data):
        now = self.clock()
        if (not isinstance(data, dict) or set(data) != set(self.data)
                or data["version"] != 1 or type(data["generation"]) is not int
                or not 0 <= data["generation"] < 2**63
                or not isinstance(data["active"], dict) or len(data["active"]) > MAX_ACTIVE):
            raise ValueError("Invalid observation activity")
        for token, record in data["active"].items():
            if (not isinstance(token, str) or len(token) != 32
                    or any(c not in "0123456789abcdef" for c in token)
                    or not isinstance(record, dict)
                    or set(record) != {"kind", "pid", "deadline", "frames", "last_frame_at", "fps"}
                    or record["kind"] not in KINDS
                    or type(record["pid"]) is not int or not 0 < record["pid"] <= 0xFFFFFFFF
                    or not _number(record["deadline"])
                    or record["deadline"] > now + (120 if record["kind"] == "video" else 8)
                    or type(record["frames"]) is not int or not 0 <= record["frames"] <= 10**9
                    or (record["last_frame_at"] is not None and
                        (not _number(record["last_frame_at"]) or record["last_frame_at"] > now))
                    or not _number(record["fps"], maximum=1000)):
                raise ValueError("Invalid observation activity")
        recent = data["recent"]
        if recent is not None and (
                not isinstance(recent, dict)
                or set(recent) != {"at", "kind", "error", "frames", "fps"}
                or not _number(recent["at"]) or recent["at"] > now or recent["kind"] not in KINDS
                or (recent["error"] is not None and recent["error"] not in _ERRORS)
                or type(recent["frames"]) is not int or not 0 <= recent["frames"] <= 10**9
                or not _number(recent["fps"], maximum=1000)):
            raise ValueError("Invalid observation activity")
        self.data = copy.deepcopy(data)

    def _prune(self, now):
        if self.data["recent"] and now - self.data["recent"]["at"] >= RECENT_SECONDS:
            self.data["recent"] = None
        for token, record in list(self.data["active"].items()):
            expired = now >= record["deadline"]
            if expired or not self.alive(record["pid"]):
                del self.data["active"][token]
                self.data["recent"] = {"at": now, "kind": record["kind"],
                    "error": "TimeoutError" if expired else "OwnerExited", "frames": 0, "fps": 0}

    def _record(self, lease):
        if (not isinstance(lease, dict) or lease.get("generation") != self.data["generation"]
                or not isinstance(lease.get("token"), str)):
            return None
        return self.data["active"].get(lease["token"])

    def begin(self, kind: str, timeout: float) -> dict:
        if kind not in KINDS or not _number(timeout) or timeout <= 0:
            raise ValueError("Invalid observation activity limits")
        now = self.clock()
        self._prune(now)
        if len(self.data["active"]) >= MAX_ACTIVE:
            raise RuntimeError("Too many active observations")
        token = uuid.uuid4().hex
        self.data["active"][token] = {"kind": kind, "pid": self.pid,
            "deadline": now + min(timeout, 120 if kind == "video" else 8),
            "frames": 0, "last_frame_at": None, "fps": 0}
        return {"token": token, "generation": self.data["generation"]}

    def update(self, lease, *, frames: int, last_frame_at: float | None,
               received_fps: float = 0) -> bool:
        now = self.clock()
        self._prune(now)
        record = self._record(lease)
        if record is None:
            return False
        if (type(frames) is not int or not 0 <= frames <= 10**9
                or (last_frame_at is not None and
                    (not _number(last_frame_at) or last_frame_at > now))
                or not _number(received_fps, maximum=1000)):
            raise ValueError("Invalid observation progress")
        if frames >= record["frames"]:
            record["frames"] = frames
            if last_frame_at is not None:
                record["last_frame_at"] = max(record["last_frame_at"] or 0, last_frame_at)
            record["fps"] = received_fps
        return True

    def finish(self, lease, result: dict | None = None, error: str | None = None) -> None:
        now = self.clock()
        self._prune(now)
        record = self._record(lease)
        if record is None:
            return
        del self.data["active"][lease["token"]]
        frames = result.get("frame_count", 0) if isinstance(result, dict) else 0
        fps = result.get("received_fps", 0) if isinstance(result, dict) else 0
        if type(frames) is not int or not 0 < frames <= 10**9:
            frames = 0
        if not _number(fps, maximum=1000):
            fps = 0
        failure = _error(error) if error is not None else (None if frames else "NoFrames")
        self.data["recent"] = {"at": now, "kind": record["kind"], "error": failure,
                               "frames": frames if failure is None else 0,
                               "fps": fps if failure is None else 0}

    def cancelled(self, lease) -> bool:
        self._prune(self.clock())
        return self._record(lease) is None

    def snapshot(self) -> dict:
        now = self.clock()
        self._prune(now)
        active = list(self.data["active"].values())
        recent = self.data["recent"]
        value = {"state": "off", "active_count": len(active), "capture_mode": "on_demand",
            "storage": "RAM", "buffer_bytes": 0, "received_fps": 0,
            "frame_count": 0, "frame_age_ms": None, "last_delivered_age_ms": None,
            "last_observation_fps": 0, "last_observation_frames": 0,
            "reason": "Ingen observation pågår."}
        if recent and recent["error"] is None:
            value.update(last_delivered_age_ms=max(0, round((now - recent["at"]) * 1000)),
                         last_observation_fps=recent["fps"], last_observation_frames=recent["frames"])
        if active:
            kinds = {record["kind"] for record in active}
            latest = max(active, key=lambda r: -1 if r["last_frame_at"] is None else r["last_frame_at"])
            stamp = latest["last_frame_at"]
            value.update(state="capturing", frame_count=sum(r["frames"] for r in active),
                observation_kind="video" if kinds == {"video"} else "screen",
                received_fps=latest["fps"] if latest["frames"] and stamp is not None else 0,
                frame_age_ms=max(0, round((now - stamp) * 1000)) if stamp is not None else None,
                reason="Avkodar videobilder." if kinds == {"video"} else "Hämtar bild på begäran.")
        elif recent:
            if recent["error"] is None:
                value.update(state="observed", last_observation_kind=recent["kind"],
                    reason="Bild hämtad; ingen kontinuerlig fångst pågår.")
            else:
                value.update(state="error", error=recent["error"], reason="Observationen misslyckades.")
        return value

    def stop(self) -> None:
        self.data["generation"] = (self.data["generation"] + 1) % (2**63)
        self.data["active"].clear()
        self.data["recent"] = None


class _WindowsChannel:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows activity channel requires Windows")
        import ctypes
        from ctypes import wintypes
        name = "Local\\GoldGoblins.Eyes." + hashlib.sha256(
            os.path.normcase(os.path.abspath(str(STATE_ROOT))).encode("utf-8")).hexdigest()[:24]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        self.mutex = kernel.CreateMutexW(None, False, name + ".Lock")
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.memory = mmap.mmap(-1, CHANNEL_BYTES, tagname=name)
        except BaseException:
            kernel.CloseHandle(self.mutex)
            raise
        self.cached = _MemoryStore().data

    def _load(self):
        try:
            size = struct.unpack("!I", self.memory[:4])[0]
            if not 0 < size <= CHANNEL_BYTES - 4:
                return _MemoryStore()
            return _MemoryStore(data=json.loads(self.memory[4:4 + size]))
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            return _MemoryStore()

    def call(self, operation, *args, **kwargs):
        result = self.kernel.WaitForSingleObject(self.mutex, 0 if operation == "snapshot" else 50)
        if result not in (0, 0x80):  # WAIT_OBJECT_0 or ownership of abandoned mutex
            if operation == "snapshot":
                cached = _MemoryStore(data=self.cached)
                answer = cached.snapshot()
                self.cached = copy.deepcopy(cached.data)
                return answer
            raise RuntimeError("Observation activity channel is busy")
        try:
            store = self._load()
            answer = getattr(store, operation)(*args, **kwargs)
            body = json.dumps(store.data, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(body) > CHANNEL_BYTES - 4:
                raise RuntimeError("Observation activity exceeds memory limit")
            self.memory[4:4 + len(body)] = body
            self.memory[:4] = struct.pack("!I", len(body))
            self.cached = copy.deepcopy(store.data)
            return answer
        finally:
            self.kernel.ReleaseMutex(self.mutex)

    def close(self):
        self.memory.close()
        self.kernel.CloseHandle(self.mutex)


class _MemoryChannel:
    """No-OS adapter for portable unit tests; Linux capture uses its own service."""
    def __init__(self):
        self.store = _MemoryStore()
        self.lock = threading.Lock()

    def call(self, operation, *args, **kwargs):
        with self.lock:
            return getattr(self.store, operation)(*args, **kwargs)

    def close(self):
        pass


_channel = None
_channel_lock = threading.Lock()


def _get_channel():
    global _channel
    with _channel_lock:
        if _channel is None:
            _channel = _WindowsChannel() if os.name == "nt" else _MemoryChannel()
            atexit.register(_channel.close)
        return _channel


def begin(kind: str, timeout: float) -> dict:
    return _get_channel().call("begin", kind, timeout)


def update(lease, *, frames: int, last_frame_at: float | None, received_fps: float = 0) -> bool:
    return _get_channel().call("update", lease, frames=frames,
                               last_frame_at=last_frame_at, received_fps=received_fps)


def finish(lease, result: dict | None = None, error: str | None = None) -> None:
    _get_channel().call("finish", lease, result, error)


def cancelled(lease) -> bool:
    return _get_channel().call("cancelled", lease)


def snapshot() -> dict:
    return _get_channel().call("snapshot")


def stop() -> None:
    _get_channel().call("stop")
