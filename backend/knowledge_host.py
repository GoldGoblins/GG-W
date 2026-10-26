"""Lazy Qt bridge for local material import, search and cached raster pages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, QUrl, Signal


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class KnowledgeHost(QObject):
    updated = Signal(str)
    importFinished = Signal(str)
    pageReady = Signal(str)

    def __init__(self, parent: QObject | None = None, *, root=None) -> None:
        super().__init__(parent)
        self.root = root
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gg-knowledge")
        self._closed = False
        self._busy = False
        self._cancelled = threading.Event()
        self._query = ""
        self._kind = "ALL"
        from backend.application_paths import STATE_ROOT

        folder = Path(root) if root is not None else STATE_ROOT / "knowledge-atlas"
        folder.mkdir(parents=True, exist_ok=True)
        scenes = folder / "scenes"
        scenes.mkdir(exist_ok=True)
        # Watching the store directory also observes SQLite's temporary WAL
        # files. A read would then trigger another read indefinitely.
        self._watcher = QFileSystemWatcher([str(scenes)], self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._watcher.directoryChanged.connect(lambda _path: self._refresh_timer.start())
        self._watcher.fileChanged.connect(lambda _path: self._refresh_timer.start())
        self._refresh_timer.timeout.connect(self._refresh_external)
        self._watch_database()
        QTimer.singleShot(0, self._watch_database)

    def _watch_database(self) -> None:
        if self._closed:
            return
        from backend.application_paths import STATE_ROOT

        folder = Path(self.root) if self.root is not None else STATE_ROOT / "knowledge-atlas"
        database = folder / "atlas.sqlite3"
        if database.is_file() and str(database) not in self._watcher.files():
            self._watcher.addPath(str(database))

    def _refresh_external(self) -> None:
        if self._closed:
            return
        self._watch_database()
        self.updated.emit(self.snapshot(self._query, self._kind))

    def snapshot(self, query: str = "", kind: str = "ALL") -> str:
        from backend import knowledge_atlas, knowledge_scenes

        with self._lock:
            if self._closed:
                return _json({"status": "CLOSED"})
            self._query, self._kind = str(query)[:240], str(kind)[:24]
        try:
            value = knowledge_atlas.snapshot(self._query, self._kind, root=self.root)
            value["scenes"] = knowledge_scenes.list_scenes(root=self.root)
            return _json(value)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            return _json({"status": "ERROR", "reason": type(exc).__name__})

    def detail(self, node_id: str) -> str:
        from backend import knowledge_atlas

        try:
            return _json(knowledge_atlas.detail(str(node_id)[:160], root=self.root))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            return _json({"status": "ERROR", "reason": type(exc).__name__})

    def scene(self, scene_id: str) -> str:
        from backend import knowledge_scenes

        return _json(knowledge_scenes.read(str(scene_id), root=self.root))

    def _body_explorer(self):
        explorer = getattr(self, "_body", None)
        if explorer is None:
            from backend.knowledge_body import BodyExplorer

            explorer = BodyExplorer(root=self.root)
            self._body = explorer
        return explorer

    def body(self) -> str:
        with self._lock:
            if self._closed:
                return _json({"status": "CLOSED"})
            return _json(self._body_explorer().snapshot())

    def body_evaluate(self, raw: str) -> str:
        with self._lock:
            if self._closed:
                return _json({"status": "CLOSED"})
            return _json(self._body_explorer().evaluate(raw))

    def _queue(self, work, signal: Signal, *, refresh: bool = False) -> bool:
        with self._lock:
            if self._closed or self._busy:
                return False
            self._busy = True
            try:
                future = self._pool.submit(work)
            except RuntimeError:
                self._busy = False
                return False

        def complete(result):
            try:
                payload = result.result()
            except Exception as exc:
                payload = {"status": "ERROR", "reason": type(exc).__name__}
            with self._lock:
                self._busy = False
                if self._closed:
                    return
                # Holding the lock prevents a shutdown from deleting this
                # QObject between its state check and signal delivery.
                try:
                    signal.emit(_json(payload))
                    if refresh:
                        self.updated.emit(self.snapshot(self._query, self._kind))
                except RuntimeError:
                    pass

        future.add_done_callback(complete)
        return True

    def import_paths(self, raw: str) -> bool:
        from backend import knowledge_atlas

        try:
            if len(raw) > 32768:
                return False
            values = json.loads(raw)
            if not isinstance(values, list) or not 1 <= len(values) <= 32:
                return False
            paths = []
            for value in values:
                if not isinstance(value, str) or not value or len(value) > 4096:
                    return False
                url = QUrl(value)
                if url.isLocalFile():
                    value = url.toLocalFile()
                elif url.scheme() and not (len(url.scheme()) == 1 and value[1:3] in (":/", ":\\")):
                    return False
                paths.append(value)
        except (ValueError, TypeError):
            return False
        return self._queue(
            lambda: knowledge_atlas.import_paths(paths, root=self.root, cancelled=self._cancelled.is_set),
            self.importFinished,
            refresh=True,
        )

    def page(self, source_id: str, page: int = 1) -> bool:
        from backend import knowledge_atlas

        if not isinstance(page, int) or not 1 <= page <= 1000:
            return False
        return self._queue(
            lambda: knowledge_atlas.page_image(str(source_id)[:160], page, root=self.root),
            self.pageReady,
        )

    def shutdown(self) -> None:
        self._refresh_timer.stop()
        with self._lock:
            self._closed = True
            self._cancelled.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
