"""Local catalogue browsing with details and playback loaded only on selection."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from collections import OrderedDict
import threading
import time
import sqlite3
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot, QTimer

from backend import media_contract as contract, media_host as host, media_library as library
from backend.media_index import MediaIndex, PAGES, echo, view_request
from backend.media_browse_session import BrowseSession, SnapshotInvalid
from backend.media_background_work import MediaBackgroundWork, empty_status


class MediaCatalogService(QObject):
    changed = Signal()
    playReady = Signal(object)
    chunkReady = Signal(int, object)
    _completed = Signal(object)

    def __init__(self, parent=None, *, index_path=None):
        super().__init__(parent)
        self.index = MediaIndex(index_path)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gg-media-index")
        self._verify_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gg-media-check")
        # Enrichment may wait for providers; paging never queues behind that IO.
        self._metadata_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gg-media-search")
        self._discovery_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gg-media-discover")
        self._initial_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gg-media-initial")
        self._background_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gg-media-background")
        self._background_work = MediaBackgroundWork(self.index)
        self._background_status = empty_status()
        self._background_cancel = threading.Event()
        self._background_future = None
        self._background_pause_future = None
        self._background_generation = 0
        self._generation = {"browse": 0, "play": 0, "search": 0, "collection": 0, "chunk": 0, "audit": 0}
        self._futures: dict[str, Future] = {}
        self._pending: set[str] = set()
        self._closed = False
        self._cancel = threading.Event()
        self._browse_cancel = threading.Event()
        self._play_cancel = threading.Event()
        self._collection_cancel = threading.Event()
        self._chunk_cancel = threading.Event()
        self._boot_lock = threading.Lock()
        self._ready = False
        self._scanned: set[str] = set()
        self._checking: set[str] = set()
        self._refresh_again = False
        self._refresh_selected_id = ""
        self._notice = ""
        self._initial_notice = ""
        self._initial_eligible = False
        self._initial_visible = False
        self._initial_blocked = False
        self._initial_future = None
        self._initial_cancel = threading.Event()
        self._initial_remaining = 300.0
        self._selection_error = ""
        self._loading_id = ""
        self._active = True
        self._discovery_started: set[str] = set()
        self._discovering: set[str] = set()
        self._audit_snapshot: dict[str, Any] = {}
        self._inventory_structure_revision: str | None = None
        self._audit_refresh_requested = False
        self._view = view_request()
        self._accepted_snapshot = None
        self._parent_snapshot = None
        self._restore_parent_snapshot = False
        self._parent_restore_context_seen = False
        self._snapshot_proposals = OrderedDict()
        self._warm_cancel = threading.Event()
        self._warm_future = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(180)
        self._refresh_timer.timeout.connect(self._refresh_page)
        self._audit_timer = QTimer(self)
        self._audit_timer.setInterval(5000)
        self._audit_timer.timeout.connect(self._poll_audit)
        self._audit_timer.start()
        self._completed.connect(self._finish)

    def _read_audit_progress(self):
        """Read counts from an existing audit; never create or run one here."""
        if not self.index.path.is_file():
            return {}
        connection = None
        try:
            connection = sqlite3.connect(self.index.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.25)
            structure = connection.execute("SELECT value FROM meta WHERE key='inventory_structure_revision'").fetchone()
            revision = str(structure[0]) if structure else "0"
            tables = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                                        "AND name IN ('media_audit_runs','media_audit_jobs')").fetchone()[0]
            if tables != 2:
                return {"_inventory_structure_revision": revision}
            columns = {row[1] for row in connection.execute("PRAGMA table_info(media_audit_runs)")}
            run = connection.execute("SELECT id,status," + ("lanes" if "lanes" in columns else "'[]'") +
                                     " FROM media_audit_runs ORDER BY id DESC LIMIT 1").fetchone()
            if run is None:
                return {"_inventory_structure_revision": revision}
            import json
            lanes = tuple(value for value in json.loads(run[2] or "[]") if value in ("live", "movies", "series"))
            job_columns = {row[1] for row in connection.execute("PRAGMA table_info(media_audit_jobs)")}
            focus = " AND lane IN (" + ",".join("?" for _ in lanes) + ")" if lanes and "lane" in job_columns else ""
            counts = dict(connection.execute("SELECT state,COUNT(*) FROM media_audit_jobs WHERE run_id=?" + focus + " GROUP BY state",
                                             [run[0], *lanes] if focus else [run[0]]))
            total = sum(counts.values())
            terminal = ("healthy", "failed", "unknown", "expanded", "changed")
            return dict(total=total, done=sum(counts.get(state, 0) for state in terminal),
                        healthy=counts.get("healthy", 0), pending=counts.get("queued", 0),
                        running=counts.get("running", 0), status=str(run[1]),
                        active_lanes=list(lanes), _inventory_structure_revision=revision)
        except (OSError, sqlite3.Error):
            # A fresh installation may not have audit tables yet. Reads must
            # not initialize the audit or interfere with its write transaction.
            return None
        finally:
            if connection is not None:
                connection.close()

    @Slot()
    def _poll_audit(self):
        if self._closed or not self._active or "audit" in self._pending:
            return
        def work():
            progress = self._read_audit_progress()
            if progress is not None:
                progress["_background_status"] = self._background_work.read_status()
            return progress
        self._queue("audit", "audit", work)

    def _publish_background(self, status):
        self._background_status = dict(status)
        host._library_page_state["library_background"] = dict(status)

    def background(self, enabled):
        """Explicit source work; browsing and Refresh do not start this lane."""
        if self._closed:
            return
        if enabled and (self._background_future is not None and not self._background_future.done()
                        or self._background_pause_future is not None and not self._background_pause_future.done()):
            return
        if not enabled and self._background_pause_future is not None and not self._background_pause_future.done():
            return
        self._background_generation += 1
        generation = self._background_generation
        current = dict(self._background_status)
        current.update(running=bool(enabled), pausing=not enabled, paused=False,
                       phase="starting" if enabled else "pausing", notice="")
        self._publish_background(current)
        self.changed.emit()
        def notify(status):
            if not self._closed:
                self._completed.emit(("background_progress", generation, "background", {}, status, ""))
        if enabled:
            cancelled = self._background_cancel = threading.Event()
            def work():
                self._bootstrap()
                return self._background_work.run(cancelled, notify=notify)
        else:
            self._background_cancel.set()
            cancelled = self._background_cancel
            def work():
                return self._background_work.pause(cancelled, notify=notify)
        future = self._background_pool.submit(work)
        if enabled:
            self._background_future = future
        else:
            self._background_pause_future = future
        def done(result):
            try:
                status = result.result()
            except Exception:
                status = dict(empty_status(), phase="error", errors=1,
                              notice="Bakgrundsarbetet kunde inte slutföras. Försök igen.")
            if not self._closed:
                self._completed.emit(("background_done", generation, "background", {}, status, ""))
        future.add_done_callback(done)

    def _cancel_audit_poll(self):
        self._generation["audit"] += 1
        self._pending.discard("audit")
        future = self._futures.get("audit")
        if future:
            future.cancel()

    def _bootstrap(self):
        with self._boot_lock:
            if self._ready:
                return
            self.index.initialize()
            if self.index.meta("starter_version") != "verified-paged-v1":
                self.index.ingest(contract.parse_m3u(contract.BUNDLED_CHANNELS, "TV"))
                self.index.meta("starter_version", "verified-paged-v1")
            content_revision = library.starter_revision()
            if self.index.meta("starter_content_revision") != content_revision:
                self.index.ingest_discovered(library.starter_catalog())
                self.index.meta("starter_content_revision", content_revision)
            # Persisted catalogue startup never opens sources or probes players.
            self._ready = True
            self._initial_eligible = True

    def _start_initial_validation(self, *, explicit=False):
        if (self._closed or not self._active or not self._initial_visible or not self._initial_eligible
                or self._initial_future is not None
                or self._view["page"] not in ("movies", "series", "live")):
            return
        if not explicit and (self._initial_blocked or self._initial_remaining <= 0):
            return
        if explicit:
            self._initial_blocked = False
            self._initial_remaining = 300.0
            self._initial_notice = ""
        cancelled = self._initial_cancel = threading.Event()
        started = time.monotonic()
        def work():
            from backend.media_initial_validation import validate_initial
            return validate_initial(self.index, cancel=cancelled, max_seconds=self._initial_remaining, explicit=explicit)
        future = self._initial_pool.submit(work)
        self._initial_future = future
        def done(result):
            try:
                value = result.result()
            except Exception:
                value = {"state": "error", "notice": "Källkontrollen kunde inte starta. Välj uppdatera för att försöka igen."}
            if not self._closed:
                self._completed.emit(("initial_validation", 0, "initial_validation", {"started": started}, value, ""))
        future.add_done_callback(done)

    def _scan_mode(self, mode):
        if mode in self._scanned:
            return
        # These crawls and tool probes are never called from a Qt slot.
        if mode in ("MUSIC", "FETCH", "GAME", "RADIO"):
            # Stations and the local library are browseable metadata. Opening
            # RADIO uses presets/last-good cache, never waits on every provider.
            rows = (contract.radio_catalog(refresh=False) if mode == "RADIO"
                    else contract.music_catalog(cancel=self._cancel) if mode == "MUSIC"
                    else contract.catalog_for(mode))
            self.index.ingest(rows)
            if mode == "FETCH":
                host._library_fetch_info = host.fetch_status()
        self._scanned.add(mode)

    def _queue(self, lane: str, action: str, work: Callable, *, pool=None, **context):
        self._generation[lane] += 1
        ticket = self._generation[lane]
        previous = self._futures.get(lane)
        if previous:
            previous.cancel()
        self._pending.add(lane)
        future = (pool or self._pool).submit(work)
        self._futures[lane] = future

        def done(result):
            if self._closed or result.cancelled():
                return
            try:
                value, error = result.result(), ""
            except Exception as exc:
                if action == "chunk":
                    error = "Nästa del av listan kunde inte läsas. Försök igen."
                elif str(exc) == "MEDIA_SOURCE_UNAVAILABLE":
                    error = "Källan svarar inte just nu. Försök igen eller välj en annan titel."
                elif str(exc) == "MEDIA_COLLECTION_EMPTY":
                    error = "Inga tillgängliga avsnitt hittades för den valda serien."
                else:
                    error = "Den valda källan kunde inte öppnas. Försök igen senare."
                value = None
            if not self._closed:
                self._completed.emit((lane, ticket, action, context, value, error))
        future.add_done_callback(done)

    def _selection(self, identifier="", error=""):
        self._loading_id = str(identifier)
        self._selection_error = str(error)
        host._library_page_state.update(library_loading_id=self._loading_id,
                                        library_selection_error=self._selection_error)
        if error:
            host._library_error = self._selection_error

    def _cancel_collection(self):
        self._collection_cancel.set()
        self._generation["collection"] += 1
        self._pending.discard("collection")
        future = self._futures.get("collection")
        if future:
            future.cancel()
        if "play" not in self._pending:
            self._selection()

    def ensure_started(self):
        if not self._ready and "browse" not in self._pending:
            mode = contract.load_prefs()["mode"]
            page = {"TV": "live", "MUSIC": "music", "FETCH": "downloads", "RADIO": "radio", "GAME": "games"}[mode]
            self.browse(page, "all", "all", "all", "all", "", 0)

    def browse(self, page, letter, category, language, season, query, offset):
        self._reset_snapshot()
        self._cancel_chunk()
        keep = self._view if page == self._view["page"] else {}
        view = view_request(page, letter, category, language, season, query, offset,
                            collection_key=keep.get("collection_key"), collection_title=keep.get("collection_title"))
        if (self._restore_parent_snapshot and self._parent_restore_context_seen and self._parent_snapshot is not None
                and self._chunk_context(view) != self._parent_snapshot.context):
            self._restore_parent_snapshot = False
            self._parent_snapshot = None
        self._cancel_search()
        if view.get("collection_key") != self._view.get("collection_key"):
            self._cancel_collection()
        self._view = view
        self._notice = ""
        host.library_begin()
        host.library_publish_page({**echo(self._view), "items": [], "library_total": 0,
                                   "library_has_more": False, "library_indexing": False,
                                   "library_loading_id": self._loading_id,
                                   "library_selection_error": self._selection_error})
        self._query()

    @staticmethod
    def _chunk_context(view):
        return tuple(view.get(key, "") for key in
                     ("page", "letter", "category", "language", "season", "query", "collection_key", "lookup_query"))

    def _reset_snapshot(self):
        self._browse_cancel.set()
        self._warm_cancel.set()
        if self._warm_future:
            self._warm_future.cancel()
        self._accepted_snapshot = None
        self._snapshot_proposals.clear()

    def accept_snapshot(self, revision):
        snapshot = self._snapshot_proposals.get(str(revision))
        if snapshot is not None and snapshot.context == self._chunk_context(self._view):
            self._accepted_snapshot = snapshot
            if (self._restore_parent_snapshot and self._parent_snapshot is not None
                    and snapshot.context == self._parent_snapshot.context):
                self._parent_snapshot = snapshot
            self._warm_snapshot(snapshot, snapshot.start_next)

    def _warm_snapshot(self, snapshot, offset):
        self._warm_cancel.set()
        if self._warm_future:
            self._warm_future.cancel()
        cancelled = self._warm_cancel = threading.Event()
        def work():
            if cancelled.is_set() or self._cancel.is_set() or self._closed:
                return
            try:
                snapshot.warm_after(offset, cancelled)
            except (ValueError, OSError, sqlite3.Error):
                pass
        self._warm_future = self._pool.submit(work)

    def _cancel_chunk(self):
        self._chunk_cancel.set()
        self._generation["chunk"] += 1
        self._pending.discard("chunk")
        future = self._futures.get("chunk")
        if future:
            future.cancel()

    def chunk(self, page, letter, category, language, season, query, offset, ticket):
        """Read one more saved page without changing the active catalogue/player."""
        active = dict(self._view)
        view = view_request(page, letter, category, language, season, query, offset,
                            collection_key=active.get("collection_key"),
                            collection_title=active.get("collection_title"))
        if active.get("lookup_query"):
            view["lookup_query"] = active["lookup_query"]
        if self._closed or not self._active or self._chunk_context(view) != self._chunk_context(active):
            return
        self._cancel_chunk()
        cancelled = self._chunk_cancel = threading.Event()
        context = self._chunk_context(view)
        snapshot = self._accepted_snapshot
        def work():
            if cancelled.is_set() or self._cancel.is_set():
                return None
            self._bootstrap()
            lookup = dict(view, query=view.get("lookup_query") or view["query"])
            if view.get("lookup_query"):
                lookup["letter"] = "all"
            try:
                payload = (snapshot.page(view["offset"], cancel=cancelled) if snapshot is not None
                           and snapshot.context == context else self.index.browse(lookup))
            except SnapshotInvalid:
                return {**echo(view), "items": [], "library_snapshot_invalid": True,
                        "library_catalog_revision": snapshot.revision}
            if cancelled.is_set() or self._cancel.is_set():
                return None
            payload.update(echo(view))
            payload["library_collection_key"] = view.get("collection_key", "")
            payload["library_chunk_error"] = ""
            if snapshot is not None:
                self._warm_snapshot(snapshot, view["offset"] + len(payload["items"]))
            return payload
        self._queue("chunk", "chunk", work, request=view, view_context=context, client_ticket=int(ticket))

    def _query(self, *, background=False, preserve_snapshot=False, selected_id=""):
        self._browse_cancel.set()
        browse_cancel = self._browse_cancel = threading.Event()
        view = dict(self._view)
        notice = self._notice
        previous_snapshot = self._accepted_snapshot
        status_snapshot = (previous_snapshot if preserve_snapshot and not background
                           and previous_snapshot is not None
                           and previous_snapshot.context == self._chunk_context(view) else None)
        parent_snapshot = (self._parent_snapshot if self._restore_parent_snapshot and not background
                           and self._parent_snapshot is not None
                           and self._parent_snapshot.context == self._chunk_context(view) else None)
        if parent_snapshot is not None:
            self._parent_restore_context_seen = True
        def work():
            self._bootstrap()
            self._scan_mode(PAGES[view["page"]][0])
            lookup = dict(view, query=view.get("lookup_query") or view["query"])
            if view.get("lookup_query"):
                # A pasted source link identifies its title independently of
                # the selected initial; keep the public echo for QML matching.
                lookup["letter"] = "all"
            # Read the structural marker first. If an external audit commits
            # during this page read, the next poll safely requests another
            # small page instead of masking that admission behind a new marker.
            structure = self.index.meta("inventory_structure_revision")
            parent_invalid = bool(parent_snapshot is not None
                and parent_snapshot.withdraw_revision != self.index.meta("inventory_withdraw_revision"))
            # Playing a channel changes transport/status, not the list being
            # browsed. Keep its accepted cursor, including when an admission
            # proposal is waiting for the reader to return to the beginning.
            # A withdrawn source still requires a newly checked snapshot.
            status_valid = bool(status_snapshot is not None
                and status_snapshot.withdraw_revision == self.index.meta("inventory_withdraw_revision"))
            if status_valid and selected_id:
                with self.index.connection() as db:
                    selected_group = db.execute("SELECT group_key FROM items WHERE id=?", (selected_id,)).fetchone()
                # A direct link or an unchecked episode may become available
                # through this Play request. Publish that newly admitted group
                # rather than retaining a snapshot in which it never existed.
                status_valid = bool(selected_group is None or selected_group[0] in status_snapshot.groups)
            snapshot = (parent_snapshot if parent_snapshot is not None and not parent_invalid
                        else status_snapshot if status_valid
                        else BrowseSession(self.index, lookup, cancel=browse_cancel))
            snapshot.context = self._chunk_context(view)
            if (background and previous_snapshot is not None
                    and previous_snapshot.context == snapshot.context
                    and previous_snapshot.withdraw_revision == snapshot.withdraw_revision
                    and previous_snapshot.groups == snapshot.groups):
                # Unrelated admissions/alternate sources do not change this
                # view's sequence. Retain its cursor and settle the marker.
                previous_snapshot.origin_revision = snapshot.origin_revision
                snapshot = previous_snapshot
            try:
                result = snapshot.page(view["offset"], cancel=browse_cancel)
            except SnapshotInvalid:
                if snapshot is not parent_snapshot and snapshot is not status_snapshot:
                    raise
                parent_invalid = snapshot is parent_snapshot
                snapshot = BrowseSession(self.index, lookup, cancel=browse_cancel)
                snapshot.context = self._chunk_context(view)
                result = snapshot.page(view["offset"], cancel=browse_cancel)
            snapshot.start_next = view["offset"] + len(result["items"])
            result["library_requires_reset"] = bool(parent_invalid or previous_snapshot is not None
                and previous_snapshot.withdraw_revision != snapshot.withdraw_revision)
            result["_inventory_structure_revision"] = str(getattr(snapshot, "origin_revision", structure) or "0")
            result["_replaced_parent_snapshot"] = parent_invalid
            result["library_background_refresh"] = bool(background)
            result.update(echo(view))
            if notice:
                result["_error"] = notice
            return result, snapshot
        self._queue("browse", "view", work, view=view)

    @Slot()
    def _refresh_page(self):
        if self._closed or not self._active:
            return
        # A clock/check timer cannot supersede the user's in-flight operation.
        if "browse" in self._pending:
            self._refresh_again = True
            return
        background = self._audit_refresh_requested
        self._audit_refresh_requested = False
        selected_id, self._refresh_selected_id = self._refresh_selected_id, ""
        self._query(background=background, preserve_snapshot=True, selected_id=selected_id)

    @Slot(object)
    def _finish(self, completed):
        lane, ticket, action, context, value, error = completed
        if self._closed:
            return
        if lane in ("background_progress", "background_done"):
            if ticket == self._background_generation:
                self._publish_background(value or empty_status())
                self.changed.emit()
                if lane == "background_done" and self._active:
                    self._poll_audit()
            return
        if lane == "initial_validation":
            self._initial_future = None
            self._initial_remaining = max(0.0, self._initial_remaining - (time.monotonic() - context["started"]))
            self._initial_notice = str((value or {}).get("notice") or "")
            self._initial_blocked = (value or {}).get("state") in ("manual", "existing", "external", "stopped", "complete", "paused", "decoder_missing", "error")
            if self._active:
                if self._initial_notice:
                    host._library_error = self._initial_notice
                self._poll_audit()
                self._refresh_timer.start()
                self.changed.emit()
            return
        if lane == "audit":
            if ticket != self._generation["audit"]:
                return
            self._pending.discard("audit")
            if not self._active or value is None:
                return
            snapshot = dict(value or {})
            background = snapshot.pop("_background_status", None)
            background_changed = background is not None and background != self._background_status
            if background is not None:
                self._publish_background(background)
            revision = snapshot.pop("_inventory_structure_revision", None)
            if revision is not None and revision != self._inventory_structure_revision:
                self._inventory_structure_revision = revision
                # Only actual membership/order changes refresh the small local
                # page. Audit counters alone must not disturb visited chunks.
                self._audit_refresh_requested = True
                self._refresh_timer.start()
            if snapshot != self._audit_snapshot or background_changed:
                self._audit_snapshot = snapshot
                if snapshot:
                    host._library_page_state["library_audit"] = dict(snapshot)
                else:
                    host._library_page_state.pop("library_audit", None)
                # Progress is status-only: preserve the catalogue revision,
                # first page, loaded scroll chunks and current playback.
                self.changed.emit()
            return
        if lane == "chunk":
            if ticket != self._generation["chunk"]:
                return
            self._pending.discard("chunk")
            if context["view_context"] != self._chunk_context(self._view) or not self._active:
                return
            payload = value or {**echo(context["request"]), "items": [],
                                "library_collection_key": context["request"].get("collection_key", "")}
            payload["library_chunk_error"] = error
            self.chunkReady.emit(context["client_ticket"], payload)
            return
        if lane == "collection_progress":
            if (ticket == self._generation["collection"]
                    and context["collection_key"] == self._view.get("collection_key") and self._active):
                self._query()
            return
        if lane == "discovery":
            self._discovering.discard(context["page"])
            if self._active:
                self._refresh_timer.start()
            return
        if lane == "invalidated":
            if self._active:
                self._refresh_timer.start()
            return
        if ticket != self._generation.get(lane):
            return
        self._pending.discard(lane)
        if action == "enrich":
            self._notice = error or str(value or "")
            if self._active:
                self._query()
            return
        host._library_busy = "browse" in self._pending
        host._library_error = self._selection_error or error
        if action == "view" and value is not None:
            payload, snapshot = value
            if payload.pop("_replaced_parent_snapshot", False):
                self._parent_snapshot = snapshot
            if isinstance(snapshot, BrowseSession):
                self._snapshot_proposals[snapshot.revision] = snapshot
                while len(self._snapshot_proposals) > 2:
                    self._snapshot_proposals.popitem(last=False)
                if not payload.get("library_background_refresh") or self._accepted_snapshot is None:
                    self._accepted_snapshot = snapshot
                self._warm_snapshot(snapshot, self._view["offset"] + len(payload["items"]))
            self._inventory_structure_revision = payload.pop("_inventory_structure_revision", self._inventory_structure_revision)
            host._library_error = self._selection_error or payload.pop("_error", error) or self._initial_notice
            payload["library_indexing"] = bool("search" in self._pending or self._discovering)
            payload["library_loading_id"] = self._loading_id
            payload["library_selection_error"] = self._selection_error
            payload["library_background"] = dict(self._background_status)
            if self._audit_snapshot:
                payload["library_audit"] = dict(self._audit_snapshot)
            host.library_publish_page(payload)

        elif action == "collection":
            if context["collection_key"] != self._view.get("collection_key"):
                return
            self._selection(error=error)
            if not error:
                self._query()
        elif action == "play":
            self._selection(error=error)
            self._refresh_selected_id = ""
        if action == "play" and value is not None:
            if value.get("collection"):
                if value.get("row"):
                    host.library_store(value["row"])
                    self.open_collection(str(value["row"]["id"]))
                    self.changed.emit()
                    return
                self._view.pop("lookup_query", None)
                self._view.update(collection_key=value["collection"], collection_title=value["title"], offset=0,
                                  letter="all", category="all", language="all", season="all", query="")
                self._query()
            else:
                host.library_store(value)
                self._refresh_selected_id = str(value.get("id") or "")
                self.playReady.emit(value)
        self.changed.emit()
        if action == "play" and self._active:
            # Reflect only this chosen source's new status in the local list.
            self._refresh_timer.start()
        if self._refresh_again:
            self._refresh_again = False
            self._refresh_timer.start()

    def _start_discovery(self, page, *, force=False):
        if (page not in ("movies", "series") or page in self._discovering or not self._active
                or (page in self._discovery_started and not force)):
            return
        self._discovery_started.add(page)
        self._discovering.add(page)
        host._library_page_state["library_indexing"] = True
        def work():
            from backend.media_discovery import discover
            self._bootstrap()
            return discover(self.index, page, cancel=self._cancel)
        future = self._discovery_pool.submit(work)
        def done(result):
            try:
                result.result()
            except Exception:
                pass
            if not self._closed:
                self._completed.emit(("discovery", 0, "discovery", {"page": page}, None, ""))
        future.add_done_callback(done)

    def set_active(self, active):
        self._active = bool(active)
        self._initial_visible = bool(active)
        if not self._active:
            self._initial_cancel.set()
            self._refresh_timer.stop()
            self._cancel_chunk()
            self._audit_timer.stop()
            self._cancel_audit_poll()
        else:
            self._audit_timer.start()
            self._poll_audit()
        # Saved lists start no imports. Only the finite first-install audit
        # may resume its remaining budget while the MEDIA pane is visible.

    def refresh(self):
        # Keep the checked page interactive while providers refresh off its lane.
        self._cancel_search()
        if not self._view.get("collection_key"):
            self._restore_parent_snapshot = False
            self._parent_snapshot = None
        self._cancel_chunk()
        self._notice = ""
        self._initial_notice = ""
        view = dict(self._view)
        if view["page"] in ("movies", "series"):
            # Source discovery/checking belongs to the explicit finite switch.
            # Refresh only republishes the saved catalogue and never launches
            # an additional importer outside that worker's budget.
            host.library_begin()
            self._query()
            return
        if view["page"] == "live":
            host.library_begin()
            self._query()
            return
        def work():
            self._bootstrap()
            self._scanned.discard(PAGES[view["page"]][0])
            if view["page"] == "radio":
                self.index.ingest(contract.radio_catalog(refresh=True))
                self._scanned.add("RADIO")
                return ""
            if view["page"] == "live":
                from backend.media_sources import refresh as refresh_sources
                result = refresh_sources(self.index, cancel=self._cancel)
                if result.get("error"):
                    self.index.ingest_discovered(contract.iptv_catalog(refresh=True))
            self._scan_mode(PAGES[view["page"]][0])
            return ""
        host.library_begin()
        host._library_page_state["library_indexing"] = True
        self._query()
        self._queue("search", "enrich", work, pool=self._metadata_pool, view=view)

    def search(self, query):
        if not self._view.get("collection_key"):
            self._restore_parent_snapshot = False
            self._parent_snapshot = None
        cleaned = str(query).strip()[:160]
        self._cancel_search()
        self._cancel_chunk()
        self._cancel_collection()
        self._view.update(query=cleaned, offset=0)
        self._view.pop("lookup_query", None)
        self._notice = ""
        direct = contract.query_item("TV", cleaned) if PAGES[self._view["page"]][0] == "TV" else None
        if direct:
            self._view["lookup_query"] = str(direct["title"])
        view = dict(self._view)
        host.library_begin()
        # Publish already verified matches without waiting for external search.
        self._query()
        if not cleaned or PAGES[view["page"]][0] != "TV":
            return
        def work():
            self._bootstrap()
            if direct:
                self.index.ingest_discovered([library.annotate(direct)])
            else:
                try:
                    self.index.ingest_discovered(library.search_archive(cleaned, limit=200))
                except (OSError, RuntimeError, ValueError, TimeoutError):
                    return "Arkivsökningen svarar inte. Titlar i det sparade biblioteket visas."
            return ""
        self._queue("search", "enrich", work, pool=self._metadata_pool, view=view)

    def open_collection(self, identifier):
        row = host.item_by_id(identifier)
        if not row:
            raise ValueError("MEDIA_ITEM_UNKNOWN")
        if not self._view.get("collection_key"):
            self._parent_snapshot = self._accepted_snapshot
        self._restore_parent_snapshot = False
        self._parent_restore_context_seen = False
        self._reset_snapshot()
        self._cancel_chunk()
        self._cancel_search()
        self.cancel_play()
        self._cancel_collection()
        self._notice = ""
        self._view.pop("lookup_query", None)
        collection = row.get("collection_key") or MediaIndex.series_key(row)
        self._view.update(collection_key=collection, collection_title=str(row["title"]), offset=0,
                          letter="all", category="all", language="all", season="all", query="")
        host.library_begin()
        self._selection(str(identifier))
        host.library_publish_page({**echo(self._view), "items": [], "library_total": 0,
                                   "library_has_more": False, "library_indexing": False,
                                   "library_loading_id": self._loading_id, "library_selection_error": ""})
        self._query()
        cancelled = self._collection_cancel = threading.Event()
        view = dict(self._view)
        ticket = self._generation["collection"] + 1
        def work():
            self._bootstrap()
            has_children = self.index.browse(view)["library_total"] > 0
            descriptors = self.index.collection_descriptors(collection)
            if not descriptors and not has_children:
                selected = self.index.get(str(identifier))
                if selected and selected.get("archive_id") and "/details/" in str(selected.get("source") or ""):
                    descriptors = [selected]
            last_error = None
            for descriptor in descriptors:
                if cancelled.is_set() or self._cancel.is_set():
                    return False
                # A curated/cached archive already has its episode summaries;
                # reopening that series should not refetch all those files.
                with self.index.connection() as db:
                    cached = db.execute("SELECT 1 FROM items WHERE parent_key=? "
                                        "AND json_extract(payload,'$.archive_id')=? "
                                        "AND COALESCE(json_extract(payload,'$._encoding_groups_version'),0)>=? LIMIT 1",
                                        (collection, str(descriptor["archive_id"]), library.ENCODING_GROUPS_VERSION)).fetchone()
                if cached:
                    continue
                try:
                    children = library.expand_item(descriptor)
                except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                    last_error = exc
                    continue
                if cancelled.is_set() or self._cancel.is_set():
                    return False
                if not children:
                    continue
                children = [dict(child, collection_key=collection, _encoding_groups_version=library.ENCODING_GROUPS_VERSION,
                                 series_title=str(row.get("series_title") or row["title"])) for child in children]
                self.index.ingest_discovered(children, expected={str(descriptor["id"]): descriptor})
                self.index.mark_expanded(str(descriptor["id"]))
                has_children = True
                if not self._closed:
                    self._completed.emit(("collection_progress", ticket, "collection_progress",
                                          {"collection_key": collection}, None, ""))
            if not has_children:
                raise last_error or RuntimeError("MEDIA_COLLECTION_EMPTY")
            return True
        self._queue("collection", "collection", work, pool=self._metadata_pool, collection_key=collection)

    def back(self):
        self._restore_parent_snapshot = bool(self._view.get("collection_key") and self._parent_snapshot is not None)
        self._parent_restore_context_seen = False
        self._cancel_collection()
        self._view.update(collection_key="", collection_title="", offset=0)
        self.browse(**{key: self._view[key] for key in ("page", "letter", "category", "language", "season", "query", "offset")})

    def play(self, row):
        self.play_id(str(row["id"]), fallback=row)

    def play_id(self, identifier, *, fallback=None):
        """Resolve and check only the selected source, including off-page IDs."""
        self.cancel_play()
        self._cancel_collection()
        self._selection(str(identifier))
        host._library_error = ""
        cancelled = self._play_cancel = threading.Event()
        def work():
            from backend.media_quick_availability import quick_check as verify, prepare_quick_identity as prepare_identity
            self._bootstrap()
            row = self.index.get(str(identifier))
            if row is None and fallback and fallback.get("source"):
                row = dict(fallback)
                self.index.ingest([row])
            if row is None:
                raise ValueError("MEDIA_ITEM_UNKNOWN")
            if cancelled.is_set() or self._cancel.is_set():
                return None
            if row.get("content_type") == "series":
                return {"collection": row.get("collection_key") or MediaIndex.series_key(row),
                        "title": row["title"], "row": row}
            if row.get("kind") == "GAME":
                return row
            selected_id = str(identifier)
            selected_expected = dict(row)
            with self.index.connection() as db:
                group = db.execute("SELECT group_key FROM items WHERE id=?", (selected_id,)).fetchone()
            if group is None:
                raise ValueError("MEDIA_ITEM_UNKNOWN")
            selected_group = str(group[0])
            def remember_selected(item):
                nonlocal selected_expected
                if str(item.get("id") or "") == selected_id:
                    selected_expected = dict(item)
            def same_group(item):
                with self.index.connection() as db:
                    current = db.execute("SELECT group_key FROM items WHERE id=?", (str(item.get("id") or ""),)).fetchone()
                return current is not None and str(current[0]) == selected_group
            def selection_unchanged():
                current = self.index.get(selected_id)
                return (current is not None and current.get("source") == selected_expected.get("source")
                        and self.index.identity_key(current) == self.index.identity_key(selected_expected)
                        and same_group(current))
            from backend.media_request import public_headers
            def request_context(item):
                return (str(item.get("source") or ""), tuple(sorted(public_headers(item).items())))
            def attempt(row, *, cached_only=False):
                def commit_resolution(rows):
                    try:
                        canonical = self.index.ingest_discovered(rows, expected={str(row["id"]): row})
                    except ValueError as exc:
                        if str(exc) == "MEDIA_SOURCE_CHANGED":
                            raise ValueError("MEDIA_SOURCE_UNAVAILABLE") from None
                        raise
                    if not canonical:
                        raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                    return canonical
                try:
                    item = library.resolve_item(row)
                except RuntimeError as exc:
                    if str(exc) != "MEDIA_ARCHIVE_CHOOSE_EPISODE" or cached_only:
                        raise
                    children = library.expand_item(row)
                    if cancelled.is_set() or self._cancel.is_set():
                        return None
                    children = commit_resolution(children)
                    collection = MediaIndex.series_key(children[0])
                    parent = dict(row, title=children[0].get("series_title") or row["title"],
                                  collection_key=collection)
                    return {"collection": collection, "title": parent["title"], "row": parent}
                if cancelled.is_set() or self._cancel.is_set():
                    return None
                item = commit_resolution([item])[0]
                remember_selected(item)
                try:
                    prepared, source_identity = prepare_identity(item)
                    if (source_identity.get("status") == "consistent"
                            and self.index.identity_key(prepared) != self.index.identity_key(item)):
                        item = self.index.correct_metadata(prepared, expected=item)
                        remember_selected(item)
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    source_identity = {"status": "unknown"}
                identity = self.index.identity_key(item)
                if cancelled.is_set() or self._cancel.is_set():
                    return None
                if source_identity.get("status") != "consistent":
                    self.index.record(str(item["id"]), {"status": "failed" if source_identity.get("status") == "failed" else "unknown", "checked_at": time.time(),
                                      "error": "identity_not_confirmed"}, source=item.get("source", ""), identity=identity)
                    raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                report = None
                if not self.index.is_verified(str(item["id"])):
                    if cached_only:
                        raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                    report = verify(item, cancel=cancelled, max_seconds=4.0, max_bytes=65536)
                    if cancelled.is_set() or self._cancel.is_set():
                        return None
                    if report.get("status") in ("verified", "failed"):
                        self.index.record(str(item["id"]), report, source=item.get("source", ""), identity=identity)
                    if report.get("status") == "failed":
                        raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                current = self.index.get(str(item["id"]))
                confirmed = self.index.is_verified(str(item["id"]))
                inconclusive = not cached_only and report is not None and report.get("status") == "unknown"
                if ((not confirmed and not inconclusive) or not current
                        or self.index.identity_key(current) != identity
                        or str(current.get("source") or "") != str(item.get("source") or "")):
                    raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                # An inconclusive fast response does not pre-empt the actual
                # player's attempt, and must never become a fabricated proof.
                item["availability"] = "available" if confirmed else "unknown"
                item["availability_scope"] = str((report or {}).get("scope") or "previous_check")
                item["availability_decoded"] = bool((report or {}).get("evidence", {}).get("decoded", False))
                if report:
                    item.update(availability_checked_at=report.get("checked_at", 0),
                                availability_expires_at=report.get("expires_at", 0))
                return item
            try:
                return attempt(row)
            except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                selected_error = error
            if cancelled.is_set() or self._cancel.is_set():
                return None
            if not selection_unchanged():
                raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
            try:
                attempted = {request_context(selected_expected)}
            except ValueError:
                attempted = set()
            alternate_count = 0
            # Only already checked, still-fresh alternatives of this exact
            # selected group qualify. No discovery or unknown-source probes.
            for alternate in self.index.group_sources(selected_id, limit=12):
                if cancelled.is_set() or self._cancel.is_set():
                    return None
                if not selection_unchanged():
                    raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                alternate_id = str(alternate.get("id") or "")
                if (alternate_id == selected_id or alternate.get("content_type") in ("series", "game")
                        or not same_group(alternate) or not self.index.is_verified(alternate_id)):
                    continue
                try:
                    context = request_context(alternate)
                except ValueError:
                    continue
                if context in attempted:
                    continue
                attempted.add(context)
                alternate_count += 1
                try:
                    result = attempt(alternate, cached_only=True)
                except (OSError, ValueError, RuntimeError, TimeoutError):
                    result = None
                if cancelled.is_set() or self._cancel.is_set():
                    return None
                if not selection_unchanged():
                    raise ValueError("MEDIA_SOURCE_UNAVAILABLE")
                if result is not None and same_group(result):
                    return result
                if alternate_count >= 3:
                    break
            raise selected_error
        self._queue("play", "play", work, pool=self._verify_pool)

    def invalidate(self, identifier, *, expected=None):
        # A player's late error belongs to the source it actually opened. An
        # external refresh may already have replaced the same catalogue ID.
        snapshot = dict(expected if expected is not None else host._item or {})
        if str(snapshot.get("id") or "") != str(identifier) or not snapshot.get("source"):
            return
        def work():
            self._bootstrap()
            self.index.record(str(identifier), {"status": "failed", "checked_at": time.time()},
                              source=snapshot["source"], identity=self.index.identity_key(snapshot))
        future = self._pool.submit(work)
        def done(result):
            try:
                result.result()
            except Exception:
                return
            if not self._closed:
                self._completed.emit(("invalidated", 0, "invalidated", {}, None, ""))
        future.add_done_callback(done)

    def _cancel_search(self):
        self._generation["search"] += 1
        self._pending.discard("search")
        future = self._futures.get("search")
        if future:
            future.cancel()

    def cancel_browse(self):
        self._browse_cancel.set()
        self._cancel_chunk()
        self._cancel_search()
        self._cancel_collection()
        self._generation["browse"] += 1
        self._pending.discard("browse")
        future = self._futures.get("browse")
        if future:
            future.cancel()

    def cancel_play(self):
        self._play_cancel.set()
        self._selection()
        self._generation["play"] += 1
        self._pending.discard("play")
        future = self._futures.get("play")
        if future:
            future.cancel()

    def close(self):
        self._closed = True
        self._background_cancel.set()
        self._initial_cancel.set()
        self._reset_snapshot()
        self._cancel.set()
        self._refresh_timer.stop()
        self._audit_timer.stop()
        self._cancel_audit_poll()
        self.cancel_browse()
        self.cancel_play()
        self._verify_pool.shutdown(wait=False, cancel_futures=True)
        self._metadata_pool.shutdown(wait=False, cancel_futures=True)
        self._discovery_pool.shutdown(wait=False, cancel_futures=True)
        self._initial_pool.shutdown(wait=False, cancel_futures=True)
        self._background_pool.shutdown(wait=False, cancel_futures=True)
        self._pool.shutdown(wait=False, cancel_futures=True)
