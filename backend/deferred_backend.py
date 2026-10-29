"""Thread-safe lazy access to an optional local backend module.

Opening or closing the desktop does not construct a game world that was never
requested. Once loaded, every caller still shares the original module/runtime.
"""
import importlib
import sys
import threading


class DeferredBackend:
    def __init__(self,name):
        self._name=name
        self._lock=threading.RLock()

    @property
    def loaded(self):
        return self._name in sys.modules

    def __getattr__(self,name):
        with self._lock:
            # Cleanup must not allocate the service it is trying to stop.
            if name=='shutdown' and not self.loaded:return lambda:None
            module=importlib.import_module(self._name)
            return getattr(module,name)
