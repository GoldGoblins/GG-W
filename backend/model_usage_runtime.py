"""One background reader for local Codex usage; no provider calls or CLI start."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot


def read_usage(session_id, sessions_root):
    from backend import codex_wallet
    root = Path(sessions_root)
    path = codex_wallet.session_path(session_id, sessions_root=root) if session_id else None
    # A temporarily missing active file must not adopt an unrelated rollout.
    return codex_wallet.snapshot(session=path, sessions_root=root, allow_latest=not bool(session_id))


class ModelUsageRuntime(QObject):
    updated = Signal(str)
    _prepared = Signal(int, str)

    def __init__(self, parent=None, *, source=read_usage):
        super().__init__(parent)
        self._source = source
        self._condition = threading.Condition()
        self._closed = False
        self._selection = None
        self._generation = 0
        self._pending = None
        self._worker = None
        self._published = None
        self._prepared.connect(self._deliver)

    def refresh(self, session_id, sessions_root):
        selection = (str(session_id or ''), str(sessions_root))
        with self._condition:
            if self._closed:
                return
            if selection != self._selection:
                self._selection = selection
                self._generation += 1
                self._published = None
            self._pending = (self._generation, selection)
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name='gg-model-usage', daemon=True)
                self._worker.start()
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                generation, selection = self._pending
                self._pending = None
            try:
                value = self._source(*selection)
                raw = json.dumps(value, separators=(',', ':'), allow_nan=False)
            except Exception:
                # A transient local read failure does not invent 0% or erase
                # the last known provider deadline. The next tick retries.
                continue
            with self._condition:
                if self._closed:
                    return
                if generation != self._generation or raw == self._published:
                    continue
                self._published = raw
            self._prepared.emit(generation, raw)

    @Slot(int, str)
    def _deliver(self, generation, raw):
        with self._condition:
            if self._closed or generation != self._generation:
                return
        self.updated.emit(raw)

    def close(self):
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2)
