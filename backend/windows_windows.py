"""Find only the native windows belonging to the requested desktop worker."""
from __future__ import annotations

import os


def window_ids(pids: set[int], tokens: tuple[str, ...] = ()) -> list[int]:
    if os.name != 'nt' or not pids:
        return []
    import ctypes
    from ctypes import wintypes
    import psutil
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []
    wanted = tuple(token.lower() for token in tokens if token)

    def visit(handle, _context):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value not in pids or not user.IsWindowVisible(handle):
            return True
        length = user.GetWindowTextLengthW(handle)
        title = ctypes.create_unicode_buffer(length + 1)
        user.GetWindowTextW(handle, title, length + 1)
        try:
            process_name = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        identity = (title.value + ' ' + process_name).lower()
        if 'gg ai desktop' not in identity and (not wanted or any(token in identity for token in wanted)):
            found.append(int(handle))
        return True

    user.EnumWindows(callback_type(visit), 0)
    return found
