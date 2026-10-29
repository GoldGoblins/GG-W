"""Open regular files without following a final symlink or Windows reparse point."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import time

NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
CLOEXEC = getattr(os, "O_CLOEXEC", 0)
NONBLOCK = getattr(os, "O_NONBLOCK", 0)

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    # ctypes retains POINTER(T) globally. Creating T inside secure_open leaked
    # a new structure and pointer class on every file operation for the entire
    # application lifetime. Reuse the ABI types, not security/handle state.
    class _FileInformation(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD),
                    ("created", wintypes.FILETIME), ("accessed", wintypes.FILETIME),
                    ("written", wintypes.FILETIME), ("volume", wintypes.DWORD),
                    ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                    ("links", wintypes.DWORD), ("index_high", wintypes.DWORD),
                    ("index_low", wintypes.DWORD)]

    class _SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]


def atomic_replace(source, destination):
    """Allow brief Windows reader/antivirus sharing locks to clear."""
    deadline = time.monotonic() + 1.5
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if os.name != 'nt' or time.monotonic() >= deadline:
                raise
            time.sleep(.01)


def is_link(path):
    """Include Windows junctions and other reparse points in link checks."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def owned_by_current_user(path_or_fd):
    """Compare real Windows owner SIDs instead of the synthetic st_uid=0."""
    if os.name != "nt":
        info = os.fstat(path_or_fd) if isinstance(path_or_fd, int) else os.stat(path_or_fd, follow_symlinks=False)
        return info.st_uid == os.getuid()
    return _windows_security_matches(path_or_fd, private=False)


def _windows_security_matches(path_or_fd, *, private):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = ctypes.c_void_p()
    owner = ctypes.c_void_p()
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        user_sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        dacl = ctypes.c_void_p()
        flags = 5 if private else 1  # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        if isinstance(path_or_fd, int):
            security.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
                                                ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                                ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            error = security.GetSecurityInfo(msvcrt.get_osfhandle(path_or_fd), 1, flags,
                                             ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
        else:
            if is_link(path_or_fd):
                return False
            security.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
                                                      ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                                      ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            error = security.GetNamedSecurityInfoW(str(Path(path_or_fd)), 1, flags,
                                                   ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if error:
            raise ctypes.WinError(error)
        if not security.EqualSid(owner, user_sid):
            return False
        if not private:
            return True
        if not dacl:
            return False
        # Private app records may be accessible to this user, SYSTEM and
        # administrators. Broad inherited grants are not POSIX owner-only.
        trusted = []
        security.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
        security.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        try:
            for sid_text in ("S-1-5-18", "S-1-5-32-544"):
                sid = ctypes.c_void_p()
                if not security.ConvertStringSidToSidW(sid_text, ctypes.byref(sid)):
                    raise ctypes.WinError(ctypes.get_last_error())
                trusted.append(sid)
            # ACL header: revision, reserved, size, AceCount, reserved.
            count = ctypes.c_ushort.from_address(dacl.value + 4).value
            for index in range(count):
                ace = ctypes.c_void_p()
                if not security.GetAce(dacl, index, ctypes.byref(ace)):
                    raise ctypes.WinError(ctypes.get_last_error())
                kind = ctypes.c_ubyte.from_address(ace.value).value
                ace_flags = ctypes.c_ubyte.from_address(ace.value + 1).value
                if ace_flags & 0x08 or kind not in (0, 5, 9, 11):
                    continue
                offset = 8
                if kind in (5, 11):
                    object_flags = ctypes.c_ulong.from_address(ace.value + 8).value
                    offset = 12 + 16 * bool(object_flags & 1) + 16 * bool(object_flags & 2)
                sid = ctypes.c_void_p(ace.value + offset)
                if not any(security.EqualSid(sid, allowed) for allowed in (user_sid, *trusted)):
                    return False
            return True
        finally:
            for sid in trusted:
                kernel.LocalFree(sid)
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        kernel.CloseHandle(token)


def mode_matches(path, mode):
    """POSIX modes on Linux; real ownership and writable state on Windows."""
    if os.name != "nt":
        return stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) == mode
    if not _windows_security_matches(path, private=(mode & 0o077 == 0)):
        return False
    info = os.fstat(path) if isinstance(path, int) else os.stat(path, follow_symlinks=False)
    return bool(mode & 0o200) == bool(info.st_mode & stat.S_IWRITE)


def _private_security_descriptor(directory=False):
    """Build an owner/SYSTEM/admin DACL without persisting account identifiers."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    security.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    token = wintypes.HANDLE()
    sid_text = ctypes.c_wchar_p()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        data = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(data, ctypes.POINTER(ctypes.c_void_p))[0]
        if not security.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise ctypes.WinError(ctypes.get_last_error())
        inherit = "OICI" if directory else ""
        sddl = "D:P" + "".join(f"(A;{inherit};FA;;;{item})" for item in (sid_text.value, "SY", "BA"))
        descriptor = ctypes.c_void_p()
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return descriptor
    finally:
        if sid_text:
            kernel.LocalFree(sid_text)
        kernel.CloseHandle(token)


def set_private_mode(path, mode):
    """Apply actual private Windows ACLs, or the requested POSIX mode."""
    if os.name != "nt":
        os.chmod(path, mode)
        return
    if not owned_by_current_user(path):
        raise PermissionError("Private path owner mismatch")
    import ctypes
    from ctypes import wintypes
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    security.SetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = _private_security_descriptor(Path(path).is_dir())
    try:
        if not security.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
        os.chmod(path, mode)
    finally:
        kernel.LocalFree(descriptor)


def secure_open(path, flags, mode=0o600):
    if os.name != "nt":
        return os.open(path, flags | NOFOLLOW, mode)
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    information = kernel.GetFileInformationByHandle
    information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    information.restype = wintypes.BOOL
    access_mode = flags & (os.O_WRONLY | os.O_RDWR)
    access = 0x80000000 if access_mode != os.O_WRONLY else 0
    if access_mode in (os.O_WRONLY, os.O_RDWR):
        access |= 0x40000000
    disposition = 1 if flags & os.O_EXCL and flags & os.O_CREAT else 4 if flags & os.O_CREAT else 3
    # OPEN_REPARSE_POINT opens the link itself. Validate the handle before
    # truncation so no race can redirect a write to a linked file.
    # Apply private permissions at creation, before another process can read
    # a newly written approval record. Existing files retain their ACL.
    descriptor = _private_security_descriptor() if flags & os.O_CREAT and mode & 0o077 == 0 else None
    attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False) if descriptor else None
    try:
        handle = create(os.fspath(path), access, 7, ctypes.byref(attributes) if attributes else None, disposition, 0x00200000, None)
        creation_error = ctypes.get_last_error()
    finally:
        if descriptor:
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(descriptor)
    if handle == ctypes.c_void_p(-1).value:
        error = creation_error
        if error in (2, 3):
            raise FileNotFoundError(2, "File does not exist", os.fspath(path))
        if error in (80, 183):
            raise FileExistsError(17, "File already exists", os.fspath(path))
        raise ctypes.WinError(error)
    try:
        info = _FileInformation()
        if not information(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & (0x400 | 0x10):
            raise OSError("Reparse points and directories are not allowed")
        fd = msvcrt.open_osfhandle(handle, access_mode | os.O_BINARY | (flags & os.O_APPEND))
        handle = None
        try:
            os.set_inheritable(fd, False)
            if flags & os.O_TRUNC:
                os.ftruncate(fd, 0)
            from backend.platform_support import file_locks
            file_locks.fd_opened(fd)
            return fd
        except BaseException:
            os.close(fd)
            raise
    finally:
        if handle is not None:
            close(handle)


def sync_directory(path):
    """Flush a parent directory where the OS exposes POSIX directory fsync.

    On Windows the file itself is flushed before its atomic replacement;
    opening a directory as a Python file descriptor is not supported.
    """
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
