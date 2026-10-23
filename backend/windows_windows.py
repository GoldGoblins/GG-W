"""Find only the native windows belonging to the requested desktop worker."""
from __future__ import annotations

import os


def window_ids(pids: set[int], tokens: tuple[str, ...] = (), *, include_hidden=False,
               include_children=False, main_only=False) -> list[int]:
    if os.name != 'nt' or not pids:
        return []
    import ctypes
    from ctypes import wintypes
    import psutil
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found = []
    seen = set()
    wanted = tuple(token.lower() for token in tokens if token)

    def visit(handle, _context):
        if handle in seen:
            return True
        seen.add(handle)
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if pid.value not in pids or (not include_hidden and not user.IsWindowVisible(handle)):
            return True
        if main_only:
            kind = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(handle, kind, len(kind))
            if "ghost" not in kind.value.lower():
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

    callback = callback_type(visit)
    def top(handle, context):
        visit(handle, context)
        if include_children:
            user.EnumChildWindows(handle, callback, 0)
        return True
    user.EnumWindows(callback_type(top), 0)
    return found
