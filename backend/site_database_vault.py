"""Current-user Windows vault for a local SITE database administrator.

The canonical data directory binds the credential to one database instance.
Secret values are never placed in command arguments, application files or logs.
The public functions deliberately expose only constant error codes.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import hashlib
import os
from pathlib import Path

from backend.platform_files import is_link

_TYPE_GENERIC = 1
_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168
_MAX_BLOB = 2560
_PREFIX = b'gg-site-db-v1\0'
_TARGET_PREFIX = 'GoldGoblins.GGAIDesktop.SITE.MariaDB.'
_BYTE = ctypes.c_ubyte
_LPBYTE = ctypes.POINTER(_BYTE)


class _FILETIME(ctypes.Structure):
    _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]


class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [('Keyword', ctypes.c_wchar_p), ('Flags', ctypes.c_uint32),
                ('ValueSize', ctypes.c_uint32), ('Value', _LPBYTE)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [('Flags', ctypes.c_uint32), ('Type', ctypes.c_uint32),
                ('TargetName', ctypes.c_wchar_p), ('Comment', ctypes.c_wchar_p),
                ('LastWritten', _FILETIME), ('CredentialBlobSize', ctypes.c_uint32),
                ('CredentialBlob', _LPBYTE), ('Persist', ctypes.c_uint32),
                ('AttributeCount', ctypes.c_uint32),
                ('Attributes', ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
                ('TargetAlias', ctypes.c_wchar_p), ('UserName', ctypes.c_wchar_p)]


@lru_cache(maxsize=1)
def _api():
    if os.name != 'nt':
        raise RuntimeError('SITE_DATABASE_WINDOWS_VAULT_REQUIRED')
    try:
        api = ctypes.WinDLL('advapi32.dll', use_last_error=True)
        api.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
        api.CredReadW.restype = ctypes.c_int
        api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), ctypes.c_uint32]
        api.CredWriteW.restype = ctypes.c_int
        api.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
        api.CredDeleteW.restype = ctypes.c_int
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return api
    except (OSError, AttributeError):
        raise RuntimeError('SITE_DATABASE_VAULT_UNAVAILABLE') from None


def _target(datadir: Path) -> str:
    try:
        raw = os.fspath(datadir)
        if not isinstance(raw, str) or not raw or '\0' in raw or raw.startswith(('\\\\', '//')):
            raise ValueError()
        path = Path(raw)
        if not path.is_absolute() or any(is_link(item) for item in (path, *path.parents)):
            raise ValueError()
        if path.exists() and not path.is_dir():
            raise ValueError()
        canonical = os.path.normcase(str(path.resolve())).encode('utf-8')
    except (OSError, ValueError, TypeError, UnicodeError):
        raise ValueError('SITE_DATABASE_VAULT_TARGET_INVALID') from None
    return _TARGET_PREFIX + hashlib.sha256(canonical).hexdigest()


def get_secret(datadir: Path) -> str | None:
    target = _target(datadir)
    api = _api()
    pointer = ctypes.POINTER(_CREDENTIALW)()
    if not api.CredReadW(target, _TYPE_GENERIC, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return None
        raise RuntimeError('SITE_DATABASE_VAULT_READ_FAILED')
    try:
        if not pointer:
            raise ValueError()
        record = pointer.contents
        size = record.CredentialBlobSize
        if (record.Type != _TYPE_GENERIC or record.UserName != 'root' or
                not record.TargetName or record.TargetName.casefold() != target.casefold() or
                size <= len(_PREFIX) or size > _MAX_BLOB or not record.CredentialBlob):
            raise ValueError()
        data = bytearray(ctypes.string_at(record.CredentialBlob, size))
        try:
            if not data.startswith(_PREFIX):
                raise ValueError()
            secret = data[len(_PREFIX):].decode('utf-8')
            if not secret or '\0' in secret:
                raise ValueError()
            return secret
        finally:
            data[:] = b'\0' * len(data)
    except (ValueError, UnicodeError, TypeError):
        raise RuntimeError('SITE_DATABASE_VAULT_RECORD_INVALID') from None
    finally:
        if pointer:
            # CredRead returns one allocated block; its pointers are valid only
            # until CredFree. Wipe the bounded blob before releasing that block.
            record = pointer.contents
            if record.CredentialBlob and 0 < record.CredentialBlobSize <= _MAX_BLOB:
                ctypes.memset(record.CredentialBlob, 0, record.CredentialBlobSize)
            api.CredFree(pointer)


def put_secret(datadir: Path, secret: str) -> None:
    target = _target(datadir)
    data = bytearray()
    try:
        if not isinstance(secret, str) or not secret or '\0' in secret:
            raise ValueError()
        data.extend(_PREFIX)
        data.extend(secret.encode('utf-8'))
        if len(data) > _MAX_BLOB:
            raise ValueError()
    except (ValueError, UnicodeError):
        data[:] = b'\0' * len(data)
        raise ValueError('SITE_DATABASE_VAULT_SECRET_INVALID') from None
    try:
        blob = (_BYTE * len(data)).from_buffer(data)
        record = _CREDENTIALW()
        record.Type = _TYPE_GENERIC
        record.TargetName = target
        record.Comment = 'GG AI Desktop local SITE database administrator'
        record.CredentialBlobSize = len(data)
        record.CredentialBlob = ctypes.cast(blob, _LPBYTE)
        record.Persist = _PERSIST_LOCAL_MACHINE
        record.UserName = 'root'
        if not _api().CredWriteW(ctypes.byref(record), 0):
            raise RuntimeError('SITE_DATABASE_VAULT_WRITE_FAILED')
    finally:
        data[:] = b'\0' * len(data)


def delete_secret(datadir: Path) -> None:
    target = _target(datadir)
    if not _api().CredDeleteW(target, _TYPE_GENERIC, 0) and ctypes.get_last_error() != _ERROR_NOT_FOUND:
        raise RuntimeError('SITE_DATABASE_VAULT_DELETE_FAILED')
