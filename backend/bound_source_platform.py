"""Native file IO for content-pinned policy modules on Windows.

Only a loaded module's OS binding is adapted. Its bytes, source pins, approval
decisions and scope checks are preserved. There is no global os monkeypatch.
"""
from __future__ import annotations

import functools
import builtins
import os
from types import ModuleType

from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK
from backend.platform_support import file_locks


class _WindowsFileOs:
    # These flags are implemented by secure_open's Win32 handle checks and
    # non-inheritable descriptors, rather than passed through to a POSIX API.
    O_NOFOLLOW = NOFOLLOW
    O_CLOEXEC = CLOEXEC
    O_NONBLOCK = NONBLOCK
    open = staticmethod(secure_open)

    def __getattr__(self, name):
        return getattr(os, name)


_WINDOWS_FILES = _WindowsFileOs()
_BOUND_LOADERS = ('_load_bound_source', '_load_bound_authority', '_load_source_authority', '_load_authority')


def prepare_bound_namespace(namespace):
    """Supply native equivalents only inside verified policy-module imports."""
    if os.name != 'nt':
        return
    def import_native(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name == 'os':
            return _WINDOWS_FILES
        if level == 0 and name == 'fcntl':
            return file_locks
        return builtins.__import__(name, globals, locals, fromlist, level)
    private_builtins = dict(builtins.__dict__)
    private_builtins['__import__'] = import_native
    namespace['__builtins__'] = private_builtins


def adapt_bound_sources(value):
    """Call only after the caller has verified the published source pin."""
    if os.name != 'nt':
        return value
    namespace = value.__dict__ if isinstance(value, ModuleType) else value
    if not isinstance(namespace, dict):
        return value
    prepare_bound_namespace(namespace)
    if namespace.get('os') is os:
        namespace['os'] = _WINDOWS_FILES
    for name in _BOUND_LOADERS:
        loader = namespace.get(name)
        if callable(loader) and not getattr(loader, '_gg_windows_file_adapter', False):
            @functools.wraps(loader)
            def load(*args, _original=loader, **kwargs):
                return adapt_bound_sources(_original(*args, **kwargs))
            load._gg_windows_file_adapter = True
            namespace[name] = load
    return value
