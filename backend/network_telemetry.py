"""Visible-only, coalesced observations of already-owned local test engines.

The worker performs actual reads. Qt receives at most one pending notification,
not an unbounded queue of frames. It never starts a node, signs a transaction,
or invents a block. The normal account/wallet snapshot remains a separate lane.
"""
from __future__ import annotations

import json
import re
import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

# Headroom for scheduling/RPC work: the target is 75 real observations/s,
# while the display presents them on its actual (typically60Hz) frame clock.
SAMPLE_SECONDS = 1 / 75


def dag_source():
    from backend import gg_parallel_dag, lan_dag_runtime
    manager = lan_dag_runtime.active_manager()
    if manager is not None:return manager
    from backend.local_node_observation import active_source
    return active_source() or gg_parallel_dag


def observe(page):
    if page == 'TESTNET':
        from backend import gg_testnet
        return gg_testnet.telemetry_snapshot()
    if page == 'DAG':
        source = dag_source()
        # Capture the revision first: a concurrent admission may cause one
        # extra read, but cannot hide a newer graph behind a newer revision.
        revision = source.telemetry_revision()
        body = source.snapshot()
        if body is None:
            from backend import gg_parallel_dag
            body=gg_parallel_dag.snapshot()
        return {'network_page': page, 'revision': revision, 'parallel_dag': body,
                'observed_monotonic':time.monotonic()}
    return None


class NetworkTelemetryRuntime(QObject):
    updated = Signal(str)
    _ready = Signal()

    def __init__(self, parent=None, *, source=observe, interval=SAMPLE_SECONDS):
        super().__init__(parent)
        self._source = source
        self._interval = max(SAMPLE_SECONDS, float(interval))
        self._condition = threading.Condition()
        self._view = ''
        self._generation = 0
        self._closed = False
        self._worker = None
        self._latest = None
        self._notified = False
        self._legacy_view = ''
        self._owners = {}
        self._owner_order = 0
        self._ready.connect(self._deliver)

    def set_view(self, page):
        """Compatibility lane for a single caller without a QML owner."""
        self._legacy_view = page if page in ('TESTNET', 'DAG') else ''
        self._select_owner_view()

    def set_owner(self, owner, page):
        """A hidden hub releases only its own interest in the observer.

        Several real OmniSurfaces coexist (workspace, marketplace, wallet).
        Their completion/destruction must not cancel the visible workspace.
        QObject destruction removes the entry; no polling or owner timer.
        """
        if owner is None or self._closed:
            return
        page = page if page in ('TESTNET', 'DAG') else ''
        key = id(owner)
        entry = self._owners.get(key)
        if entry is None:
            if not page:
                return  # A never-active hidden surface has nothing to release.
            owner.destroyed.connect(lambda *_args, owner_key=key: self._release_owner(owner_key))
        elif entry[1] == page:
            return
        self._owner_order += 1
        self._owners[key] = (owner, page, self._owner_order)
        self._select_owner_view()

    def _release_owner(self, key):
        self._owners.pop(key, None)
        self._select_owner_view()

    def _select_owner_view(self):
        active = [entry for entry in self._owners.values() if entry[1]]
        page = max(active, key=lambda entry: entry[2])[1] if active else self._legacy_view
        self._set_view(page)

    def _set_view(self, page):
        page = page if page in ('TESTNET', 'DAG') else ''
        with self._condition:
            if self._closed or page == self._view:
                return
            self._view = page
            self._generation += 1
            self._latest = None
            if page and self._worker is None:
                self._worker = threading.Thread(target=self._run, name='gg-network-observer', daemon=True)
                self._worker.start()
            self._condition.notify_all()

    def _run(self):
        previous = None
        deadline = time.monotonic()
        while True:
            with self._condition:
                while not self._closed and not self._view:
                    self._condition.wait()
                    previous = None
                    deadline = time.monotonic()
                if self._closed:
                    return
                delay = deadline - time.monotonic()
                page, generation = self._view, self._generation
            if delay > 0:
                # CPython uses a high-resolution waitable timer for sleep on
                # Windows. Condition.wait uses coarse kernel timeout ticks.
                # Sleep is at most one13.3ms period; view/close is checked
                # again before doing IO. No spin or system timer change.
                time.sleep(delay)
                continue
            try:
                unchanged_dag = False
                if page == 'DAG' and self._source is observe:
                    unchanged_dag = previous == (page, generation, dag_source().telemetry_revision())
                if unchanged_dag:
                    # Keep the real 75Hz observation cadence, but do not copy
                    # 128 unchanged proposals/parent lists on every read.
                    fingerprint, raw = previous, None
                else:
                    value = self._source(page)
                    fingerprint = (page, generation, value.get('revision')) if value else None
                    raw = json.dumps(value, separators=(',', ':'), allow_nan=False) if value and fingerprint != previous else None
            except Exception as error:
                code = str(error)
                if not re.fullmatch(r'[A-Z][A-Z0-9_]{1,79}', code):
                    code = 'GG_NETWORK_OBSERVATION_FAILED'
                fingerprint = (page, generation, code)
                raw = json.dumps({'network_page': page, 'error': code}) if fingerprint != previous else None
            notify = False
            with self._condition:
                if self._closed:
                    return
                if page == self._view and generation == self._generation:
                    if raw:
                        self._latest = (generation, raw)
                        if not self._notified:
                            self._notified = True
                            notify = True
                    previous = fingerprint
                now = time.monotonic()
                deadline += self._interval
                if deadline < now:
                    deadline = now + self._interval  # Missed reads are skipped, never queued.
            if notify:
                self._ready.emit()

    @Slot()
    def _deliver(self):
        with self._condition:
            latest, self._latest = self._latest, None
            self._notified = False
            if self._closed or not latest or latest[0] != self._generation or not self._view:
                return
            raw = latest[1]
        self.updated.emit(raw)

    def close(self):
        with self._condition:
            self._closed = True
            self._view = ''
            self._legacy_view = ''
            self._owners.clear()
            self._latest = None
            self._generation += 1
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=7)  # At most two owned HTTP reads,3s each.
