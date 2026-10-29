"""Verified resource lease for the one owned, disposable GG dev-node process.

Windows limits are a Job Object attached to the child, never the GG desktop.
This is resource containment, not an operating-system security sandbox.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import threading

MEMORY_BYTES = 512 * 1024 * 1024
CPU_SECONDS = 300
ACTIVE_PROCESS_LIMIT = 1
_PROCESS_TIME = 0x0002
_ACTIVE_PROCESS = 0x0008
_PROCESS_MEMORY = 0x0100
_KILL_ON_CLOSE = 0x2000
_FLAGS = _PROCESS_TIME | _ACTIVE_PROCESS | _PROCESS_MEMORY | _KILL_ON_CLOSE
_EXTENDED_LIMIT_INFORMATION = 9


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _IoCounters),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                      ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                      wintypes.BOOL, wintypes.DWORD]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _stop_owned(process):
    """Only use the Popen object's owned process handle, never a searched PID."""
    try:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


class ProcessLease:
    def __init__(self, *, kernel=None, job=None, facts=None):
        self._kernel = kernel
        self._job = job
        self._facts = dict(facts or {})
        self._lock = threading.Lock()

    @property
    def facts(self):
        return dict(self._facts)

    @property
    def closed(self):
        with self._lock:
            return self._job is None

    def close(self):
        """Release the non-inheritable job handle; Windows kills its child."""
        with self._lock:
            if self._job is not None:
                job = self._job
                if not self._kernel.CloseHandle(job):
                    raise RuntimeError("GG_TESTNET_CONTAINMENT_CLOSE_FAILED")
                self._job = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def contain(process):
    """Contain the already-created owned child, or fail closed on Windows.

    The caller must retain the returned lease until its explicit stop path.
    No external endpoint should be accepted before this function succeeds.
    Non-Windows callers receive truthful unavailable facts and retain their
    normal Popen termination responsibility.
    """
    if not isinstance(process, subprocess.Popen) or type(process.pid) is not int or process.pid <= 0 or process.pid == os.getpid():
        raise ValueError("GG_TESTNET_OWNED_CHILD_REQUIRED")
    if process.poll() is not None:
        raise ValueError("GG_TESTNET_CHILD_NOT_RUNNING")
    if os.name != "nt":
        return ProcessLease(facts={"provider": "UNAVAILABLE", "verified": False,
            "memory_bytes": None, "cpu_seconds": None, "active_process_limit": None,
            "kill_on_close": False})
    kernel = None
    job = None
    child = wintypes.HANDLE()
    try:
        kernel = _kernel()
        current = kernel.GetCurrentProcess()
        # Duplicate the exact Popen-owned handle. Reopening a PID alone could
        # race process exit and PID reuse between validation and assignment.
        if not kernel.DuplicateHandle(current, wintypes.HANDLE(int(process._handle)),
                                      current, ctypes.byref(child), 0, False, 0x0002):
            raise RuntimeError("DUPLICATE")
        if kernel.GetProcessId(child) != process.pid:
            raise RuntimeError("IDENTITY")
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise RuntimeError("CREATE")
        limits = _ExtendedLimits()
        limits.basic.flags = _FLAGS
        limits.basic.process_time = CPU_SECONDS * 10_000_000
        limits.basic.active_processes = ACTIVE_PROCESS_LIMIT
        limits.process_memory = MEMORY_BYTES
        if not kernel.SetInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION,
                                               ctypes.byref(limits), ctypes.sizeof(limits)):
            raise RuntimeError("SET")
        if not kernel.AssignProcessToJobObject(job, child):
            raise RuntimeError("ASSIGN")
        actual = _ExtendedLimits()
        if not kernel.QueryInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION,
                                                 ctypes.byref(actual), ctypes.sizeof(actual), None):
            raise RuntimeError("QUERY")
        member = wintypes.BOOL()
        if not kernel.IsProcessInJob(child, job, ctypes.byref(member)) or not member.value:
            raise RuntimeError("MEMBERSHIP")
        if actual.basic.flags & _FLAGS != _FLAGS or actual.process_memory != MEMORY_BYTES or \
                actual.basic.active_processes != ACTIVE_PROCESS_LIMIT or actual.basic.process_time != CPU_SECONDS * 10_000_000:
            raise RuntimeError("LIMIT_MISMATCH")
        lease = ProcessLease(kernel=kernel, job=job, facts={"provider": "WINDOWS_JOB_OBJECT",
            "verified": True, "memory_bytes": actual.process_memory,
            "cpu_seconds": actual.basic.process_time // 10_000_000,
            "active_process_limit": actual.basic.active_processes,
            "kill_on_close": bool(actual.basic.flags & _KILL_ON_CLOSE)})
        job = None
        return lease
    except Exception:
        _stop_owned(process)
        raise RuntimeError("GG_TESTNET_CONTAINMENT_FAILED") from None
    finally:
        if kernel is not None:
            if child.value:
                kernel.CloseHandle(child)
            if job:
                kernel.CloseHandle(job)
