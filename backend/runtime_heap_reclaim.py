"""One bounded release of unused Windows heap caches after the legacy repair.

This asks the allocator to decommit unused pages; it never trims the working
set, frees live objects or changes heap limits/security behavior.
Microsoft HeapSetInformation / HeapOptimizeResources, Windows 8.1+.
"""
import ctypes
import gc
import os
import sys

_done=False
MAINTENANCE_VERSION=2


def finish_repaired_heap():
    global _done
    if os.name!='nt' or _done:return
    from backend import runtime_memory_maintenance as maintenance
    if maintenance._report.get('state')!='REPAIRED':return
    _done=True
    with maintenance._lock:
        report=maintenance._report
        report.setdefault('private_before_heap_decommit_mib',maintenance._private_mib())
        gc.collect()
        clear=getattr(sys,'_clear_internal_caches',None)
        if callable(clear):clear()
        # A module-owned primitive array avoids introducing another transient
        # Structure→POINTER type into ctypes' process-global cache.
        if not report.get('unused_heap_decommit_succeeded'):
            info=(ctypes.c_uint32*2)(1,0)
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.HeapSetInformation.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_size_t]
            kernel.HeapSetInformation.restype=ctypes.c_int
            report['unused_heap_decommit_succeeded']=bool(kernel.HeapSetInformation(None,3,ctypes.byref(info),ctypes.sizeof(info)))
            report['private_after_heap_decommit_mib']=maintenance._private_mib()
        # Collect unreachable JS wrappers and unused components with Qt's safe
        # APIs. Never clear the component/type cache underneath live objects.
        from PySide6.QtCore import QCoreApplication,QThread
        app=QCoreApplication.instance()
        engine=getattr(app,'_gg_qml_engine',None) if app is not None else None
        if engine is not None and QThread.currentThread()==app.thread() and not report.get('qml_gc_completed'):
            report['private_before_qml_gc_mib']=maintenance._private_mib()
            engine.collectGarbage()
            engine.trimComponentCache()
            gc.collect()
            report['private_after_qml_gc_mib']=maintenance._private_mib()
            report['qml_gc_completed']=True
        report['allocated_python_blocks_after_repair']=sys.getallocatedblocks()
        maintenance._write_report()
