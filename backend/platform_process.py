"""Bounded child-process IO and native resource limits for desktop workers."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading
import time

from backend.platform_support import host_environment, terminate_process_tree

_WINDOWS_JOBS = []


def background_options():
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def process_arguments(pid):
    if int(pid) <= 0:
        return []
    if os.name == 'nt':
        import psutil
        try:
            return psutil.Process(int(pid)).cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []
    try:
        return [part.decode('utf-8', 'replace') for part in Path(f'/proc/{int(pid)}/cmdline').read_bytes().split(b'\0') if part]
    except OSError:
        return []


def run_bounded(argv, *, cwd=None, env=None, timeout=20, max_output_bytes=32768, cancelled=None):
    """Drain both pipes on Windows as well as POSIX, retaining bounded output."""
    if timeout <= 0 or max_output_bytes <= 0:
        raise ValueError('INVALID_PROCESS_LIMIT')
    process = subprocess.Popen(argv, cwd=cwd, env=host_environment(env) if env is not None else None,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               bufsize=0, shell=False, **background_options())
    buffers = [bytearray(), bytearray()]
    lock = threading.Lock()
    overflow = threading.Event()

    def read_pipe(index, pipe):
        try:
            while True:
                chunk = os.read(pipe.fileno(), 4096)
                if not chunk:
                    return
                with lock:
                    available = max_output_bytes - sum(map(len, buffers))
                    buffers[index].extend(chunk[:available])
                    if len(chunk) > available:
                        overflow.set()
                        return
        except (OSError, ValueError):
            return

    readers = [threading.Thread(target=read_pipe, args=(index, pipe), daemon=True)
               for index, pipe in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    trigger = 'NONE'
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None or any(reader.is_alive() for reader in readers):
            if overflow.is_set():
                trigger = 'OUTPUT_LIMIT'
                break
            if cancelled and cancelled():
                trigger = 'CANCELLED'
                break
            if time.monotonic() >= deadline:
                trigger = 'TIMEOUT'
                break
            time.sleep(0.01)
        if trigger != 'NONE' or process.poll() is None:
            terminate_process_tree(process.pid, force=True)
        process.wait(timeout=3)
        for reader in readers:
            reader.join(timeout=1)
        if overflow.is_set() and trigger == 'NONE':
            trigger = 'OUTPUT_LIMIT'
        return process.returncode, bytes(buffers[0]), bytes(buffers[1]), trigger
    finally:
        if process.poll() is None:
            terminate_process_tree(process.pid, force=True)
            process.wait(timeout=3)
        process.stdout.close()
        process.stderr.close()


def apply_windows_worker_limits(*, memory_bytes, cpu_seconds):
    """Place this worker and its descendants in a real Windows Job Object."""
    if os.name != 'nt':
        raise RuntimeError('WINDOWS_WORKER_LIMITS_REQUIRE_WINDOWS')
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                    ('max_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('basic', BasicLimits), ('io', IoCounters), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t),
                    ('peak_job_memory', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000 | 0x100 | 0x2  # kill children on close, process memory, process CPU time
    limits.basic.process_time = int(cpu_seconds * 10_000_000)
    limits.process_memory = int(memory_bytes)
    if memory_bytes <= 0 or cpu_seconds <= 0:
        raise ValueError('INVALID_WORKER_LIMIT')
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
        actual = ExtendedLimits()
        if not kernel.QueryInformationJobObject(job, 9, ctypes.byref(actual), ctypes.sizeof(actual), None):
            raise ctypes.WinError(ctypes.get_last_error())
        _WINDOWS_JOBS.append(job)
        job = None
        return {'memory_bytes': actual.process_memory, 'cpu_seconds': actual.basic.process_time / 10_000_000,
                'kill_children_on_exit': bool(actual.basic.flags & 0x2000)}
    finally:
        if job:
            kernel.CloseHandle(job)
