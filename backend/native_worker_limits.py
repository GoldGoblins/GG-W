"""Enforce native decoder memory limits on both supported operating systems."""
from __future__ import annotations
import os


def apply(memory_bytes):
    if os.name == 'nt':
        from backend.platform_process import apply_windows_worker_limits
        apply_windows_worker_limits(memory_bytes=memory_bytes, cpu_seconds=3600)
        import ctypes
        ctypes.WinDLL('kernel32').SetErrorMode(0x1 | 0x2 | 0x8000)
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
