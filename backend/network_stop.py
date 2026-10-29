"""Priority cancellation of the two already-owned local network engines.

No general action queue, endpoint, PID or credential is accepted here. The
interrupt is issued immediately; one bounded cleanup worker per engine waits
for owned work to drain without blocking Qt or the ordinary wallet lane.
"""
from __future__ import annotations
import re
import threading
import time
from PySide6.QtCore import QObject, Signal


def interrupt(page):
    if page == 'TESTNET':
        from backend import gg_testnet
        gg_testnet.request_stop()
        return gg_testnet.stop
    else:
        from backend import gg_parallel_dag, lan_dag_runtime
        manager = lan_dag_runtime.active_manager()
        if manager is not None:
            manager.request_stop()
            return manager.stop
        gg_parallel_dag.request_stop()
        return gg_parallel_dag.stop


def cleanup(page):
    if page == 'TESTNET':
        from backend import gg_testnet
        gg_testnet.stop()
    else:
        from backend import gg_parallel_dag
        gg_parallel_dag.stop()


class NetworkStopRuntime(QObject):
    finished = Signal(str, str)

    def __init__(self, parent=None, *, interrupt_source=interrupt, cleanup_source=cleanup):
        super().__init__(parent)
        self._interrupt = interrupt_source
        self._cleanup = cleanup_source
        self._lock = threading.Lock()
        self._workers = {}
        self._closed = False

    def request(self, page):
        if page not in ('TESTNET', 'DAG'):
            return False
        with self._lock:
            if self._closed:
                return False
            if page in self._workers:
                return True
            self._workers[page] = None
        try:
            stop_action = self._interrupt(page)
            if self._cleanup is not cleanup:
                stop_action = None  # Preserve explicitly injected cleanup lanes.
            worker = threading.Thread(target=self._run, args=(page, stop_action), name='gg-network-stop-'+page.lower(), daemon=True)
            with self._lock:
                self._workers[page] = worker
            worker.start()
        except Exception:
            with self._lock:
                self._workers.pop(page, None)
            self.finished.emit(page, 'GG_NETWORK_STOP_REQUEST_FAILED')
            return False
        return True

    def _run(self, page, stop_action=None):
        error = ''
        try:
            # Use the same owned engine captured by the immediate interrupt,
            # even if the selected mode changes while cleanup is waiting.
            if callable(stop_action):
                stop_action()
            else:
                self._cleanup(page)
        except Exception as exception:
            code = str(exception)
            error = code if re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}', code) else 'GG_NETWORK_STOP_FAILED'
        finally:
            with self._lock:
                closed = self._closed
            if not closed:
                try:
                    self.finished.emit(page, error)
                except RuntimeError:
                    pass  # The owning QObject was destroyed during shutdown.
            with self._lock:
                self._workers.pop(page, None)

    def close(self):
        with self._lock:
            self._closed = True
            workers = list(self._workers.values())
        deadline = time.monotonic()+8
        for worker in workers:
            if worker is not None and worker is not threading.current_thread():
                worker.join(max(0, deadline-time.monotonic()))
