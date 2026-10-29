"""One-time compatibility repair for the former Windows secure_open type leak.

The desktop's existing source-refresh lane may load this fixed maintenance
operation into an older running session. It does not execute input, alter file
permissions, accept a target, or add a command/approval capability. Cold starts
already use the fixed shared ABI types and require no function update.
"""
from __future__ import annotations
import ctypes
import gc
import importlib
import json
import os
from pathlib import Path
import threading

_lock=threading.Lock()
_attempted=False
_report={}
_QUALNAME='secure_open.<locals>.FileInformation'


def _legacy_type(value):
    return (isinstance(value,type) and value.__module__=='backend.platform_files'
            and value.__qualname__==_QUALNAME)


def _private_mib():
    import psutil
    return round(psutil.Process().memory_info().private/1048576,3)


def _write_report():
    from backend.application_paths import STATE_ROOT
    from backend import platform_files
    path=STATE_ROOT/'runtime-memory-maintenance.json'
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=json.dumps(_report,sort_keys=True,separators=(',',':')).encode()
    # This is public diagnostic metadata only, written with the same repaired
    # file policy. No addresses, heap contents or credentials enter the report.
    fd=platform_files.secure_open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw)


def _cleanup():
    cache=ctypes._pointer_type_cache
    stale=[key for key in list(cache) if _legacy_type(key)]
    for key in stale:cache.pop(key,None)
    count=len(stale)
    stale.clear()
    gc.collect()
    return count


def repair_legacy_windows_file_types():
    """Upgrade only the exact legacy function, preserving imported aliases."""
    global _attempted,_report
    if os.name!='nt':return {'state':'NOT_APPLICABLE'}
    with _lock:
        if _attempted:return dict(_report)
        _attempted=True
        from backend import platform_files
        previous=platform_files.secure_open
        _report={'schema':'gg.runtime-memory-maintenance.v1','state':'CHECKING',
                 'private_before_mib':_private_mib(),'patched_in_place':False,'legacy_pointer_types_released':0}
        try:
            code=previous.__code__
            legacy=any(isinstance(c,type(code)) and c.co_name=='FileInformation' for c in code.co_consts)
            if legacy:
                if (previous.__globals__ is not platform_files.__dict__ or previous.__closure__ is not None
                    or code.co_argcount!=3 or code.co_kwonlyargcount or previous.__defaults__!=(0o600,)):
                    raise RuntimeError('UNEXPECTED_LEGACY_SIGNATURE')
                expected_fields=('attributes','created','accessed','written','volume','size_high','size_low','links','index_high','index_low')
                legacy_types=[key for key in ctypes._pointer_type_cache if _legacy_type(key)]
                platform_files=importlib.reload(platform_files)
                replacement=platform_files.secure_open
                fixed=platform_files._FileInformation
                if (replacement.__code__.co_argcount!=3 or replacement.__closure__ is not None
                    or '_FileInformation' not in replacement.__code__.co_names
                    or tuple(name for name,*_ in fixed._fields_)!=expected_fields
                    or any(ctypes.sizeof(item)!=ctypes.sizeof(fixed) or tuple(name for name,*_ in item._fields_)!=expected_fields for item in legacy_types)):
                    raise RuntimeError('UNEXPECTED_REPLACEMENT_ABI')
                # Assignment is atomic under Python's GIL. Existing in-flight
                # frames retain their original code and per-call handle/types.
                previous.__code__=replacement.__code__
                previous.__defaults__=replacement.__defaults__
                previous.__kwdefaults__=replacement.__kwdefaults__
                platform_files.secure_open=previous
                legacy_types.clear()
                _report['patched_in_place']=True
            _report['legacy_pointer_types_released']=_cleanup()
            _report.update(state='REPAIRED' if legacy else 'ALREADY_FIXED',private_after_mib=_private_mib())
            if legacy or _report['legacy_pointer_types_released']:_write_report()
            if legacy:
                # An already-running old frame may populate one late cache
                # entry after the first scan. Exactly one later pass is bounded.
                from PySide6.QtCore import QCoreApplication,QTimer
                if QCoreApplication.instance() is not None:
                    def finish():
                        with _lock:
                            _report['legacy_pointer_types_released']+=_cleanup()
                            _report['private_after_quiescence_mib']=_private_mib()
                            _report['quiescence_pass_complete']=True
                            _write_report()
                    QTimer.singleShot(1000,finish)
            return dict(_report)
        except Exception:
            _report['state']='RESTART_REQUIRED'
            try:_write_report()
            except OSError:pass
            return dict(_report)
