"""Cold production MEDIA calls and bounded real-QML browsing under load.

Each scenario runs in a ten-second subprocess with isolated user/media state.
Cold calls and persisted, checked catalogues catch work accidentally
performed on Qt's thread or repeated while merely browsing saved metadata.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def cold_fixture(root: Path):
    import faulthandler
    import threading
    import time
    from unittest.mock import patch
    import urllib.request

    faulthandler.dump_traceback_later(3, repeat=True)
    sys.path.insert(0, str(PROJECT))
    from PySide6.QtCore import QCoreApplication, QObject
    from backend import media_contract as contract, media_host as host
    from backend.chat_surface_host import ChatSurfaceHost

    app = QCoreApplication([])
    library = root / "fixture-library"
    library.mkdir()
    (library / "Example S01E01.mp4").write_bytes(b"fixture")
    contract.STATE_DIR = root / "media"
    host.STATE_DIR = contract.STATE_DIR
    contract.LIBRARY_DIRS = (library,)
    contract.FETCH_DIR = root / "fixture-downloads"
    contract._probe_cache = None
    host._catalog_memo.clear()
    contract.save_prefs({"mode": "MUSIC"})
    bridge = ChatSurfaceHost.__new__(ChatSurfaceHost)
    QObject.__init__(bridge)
    bridge._media_embed = None
    bridge._torlink_embed = None
    bridge._media_catalog = None

    main_thread = threading.get_ident()
    forbidden = {"_scan_files", "library_catalog", "radio_browser_stations", "homebrew_search",
                 "_group_library", "which_first", "_library_roots", "iptv_catalog", "parse_m3u_text",
                 "music_catalog", "fetch_catalog", "game_catalog"}
    gui_work = []
    network_threads = []

    def observe(frame, event, arg):
        if event == "call" and threading.get_ident() == main_thread and frame.f_code.co_name in forbidden:
            if str(PROJECT / "backend") in frame.f_code.co_filename:
                gui_work.append(frame.f_code.co_name)

    def unavailable(*args, **kwargs):
        network_threads.append(threading.get_ident())
        raise OSError("Offline loading regression fixture")

    timings, sizes = {}, {}
    try:
        with patch.object(urllib.request, "urlopen", side_effect=unavailable):
            sys.setprofile(observe)
            for label, work in (
                ("mediaStatus_cold", bridge.mediaStatus),
                ("mediaLiveStatus_cold", bridge.mediaLiveStatus),
                ("mediaSetMode_TV", lambda: bridge.mediaSetMode("TV")),
                ("mediaStatus_TV", bridge.mediaStatus),
                ("item_by_id_missing", lambda: host.item_by_id("missing-loading-test-item")),
            ):
                began = time.perf_counter()
                value = work()
                timings[label] = (time.perf_counter() - began) * 1000
                if isinstance(value, str):
                    assert value, (label, "Empty status is not a valid loading response")
                    payload = json.loads(value)
                    assert not payload.get("error"), (label, payload)
                    sizes[label] = {"rows": len(payload.get("items") or []), "bytes": len(value)}
                    assert sizes[label]["rows"] <= 80, (label, sizes[label])
            sys.setprofile(None)
            assert not gui_work, {"blocking_gui_calls": gui_work}
            assert main_thread not in network_threads, "A MEDIA GUI slot initiated HTTP"
            assert max(timings.values()) < 50, {"cold_gui_ms": timings}
    finally:
        sys.setprofile(None)
        service = bridge._media_catalog
        if service is not None:
            service.close()
            if hasattr(service, "_pool"):
                service._pool.shutdown(wait=True, cancel_futures=True)
            if hasattr(service, "_verify_pool"):
                service._verify_pool.shutdown(wait=True, cancel_futures=True)
        app.processEvents()
        faulthandler.cancel_dump_traceback_later()
    print(json.dumps({"cold_gui_ms": timings, "payloads": sizes, "gui_scan_or_probe_calls": gui_work,
                      "gui_network": main_thread in network_threads}))


def qml_fixture(root: Path):
    """Stress the production QML contract with a delayed 50k-row backend."""
    from concurrent.futures import ThreadPoolExecutor
    import faulthandler
    import threading
    import time

    sys.path.insert(0, str(PROJECT / "tests"))
    from test_media_library_ui import LibraryBridge, MediaScene
    from PySide6.QtCore import QTimer, Signal, Slot, Qt
    from PySide6.QtTest import QTest

    faulthandler.dump_traceback_later(3, repeat=True)

    class PagedBridge(LibraryBridge):
        ready = Signal(object)
        mediaLibraryChunkReady = Signal(int, str)

        def __init__(self):
            super().__init__()
            self.catalogue = [dict(id="load-" + str(index), kind="TV", title=("A" if index % 2 == 0 else "B") + " film " + str(index).zfill(5),
                content_type="movie", source="https://example.invalid/film.mp4", media="vod", is_live=False,
                provider="50k offline backend", category="Film", language="sv", player="qml", play="video") for index in range(50_000)]
            self.payload.update(items=[], mode="TV", library_busy=False)
            self.requests = []
            self.deliveries = []
            self.chunk_requests = []
            self.max_sent_rows = 0
            self.release_slow = threading.Event()
            self.slow_started = threading.Event()
            self.pool = ThreadPoolExecutor(max_workers=2)
            self.ready.connect(self.deliver)

        def raw(self):
            self.max_sent_rows = max(getattr(self, "max_sent_rows", 0), len(self.payload.get("items") or []))
            return super().raw()

        @Slot(str, str, str, str, str, str, int, result=str)
        def mediaLibraryBrowse(self, page, letter, category, language, season, query, offset):
            request = dict(library_page=page, library_letter=letter, library_category=category,
                           library_language=language, library_season=season, library_query=query,
                           library_offset=offset)
            self.requests.append(request)
            self.payload.update(library_busy=True)

            def work():
                if query == "slow":
                    self.slow_started.set()
                    self.release_slow.wait(3)
                rows = self.catalogue if page == "movies" else []
                if letter != "all":
                    rows = [row for row in rows if row["title"].startswith(letter)]
                if query and query != "slow":
                    rows = [row for row in rows if query.casefold() in row["title"].casefold()]
                return dict(request, items=rows[offset:offset + 80], library_page_size=80,
                    library_total=len(rows), library_has_more=offset + 80 < len(rows),
                    library_categories=[{"value": "Film", "label": "Film"}],
                    library_languages=[{"value": "sv", "label": "Svenska"}], library_seasons=[],
                    library_collection="", library_collection_key="", library_catalog_revision="1",
                    library_busy=False, library_error="")

            future = self.pool.submit(work)
            future.add_done_callback(lambda result: self.ready.emit(result.result()))
            return self.raw()

        @Slot(str, str, str, str, str, str, int, int)
        def mediaLibraryChunk(self, page, letter, category, language, season, query, offset, ticket):
            request = dict(library_page=page, library_letter=letter, library_category=category,
                           library_language=language, library_season=season, library_query=query,
                           library_offset=offset)
            self.chunk_requests.append(request)
            def work():
                rows = self.catalogue if page == "movies" else []
                if letter != "all":
                    rows = [row for row in rows if row["title"].startswith(letter)]
                if query:
                    rows = [row for row in rows if query.casefold() in row["title"].casefold()]
                return dict(request, items=rows[offset:offset + 80], library_page_size=80,
                    library_total=len(rows), library_has_more=offset + 80 < len(rows),
                    library_collection="", library_collection_key="", library_catalog_revision="1",
                    library_chunk_error="")
            def done(result):
                payload = result.result()
                self.max_sent_rows = max(self.max_sent_rows, len(payload["items"]))
                self.mediaLibraryChunkReady.emit(ticket, json.dumps(payload))
            self.pool.submit(work).add_done_callback(done)

        @Slot(object)
        def deliver(self, result):
            self.payload.update(result)
            self.payload["library_revision"] += 1
            self.deliveries.append(result)
            self.mediaStateChanged.emit()

    scene = MediaScene(PROJECT / "qml/components")
    bridge = PagedBridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.setProperty("statusJson", bridge.raw())
    scene.root.selectPage("movies")
    beats = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(time.perf_counter()))
    timer.start()

    def until(condition, timeout=2):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            scene.app.processEvents()
            if condition():
                return
            QTest.qWait(5)
        raise AssertionError("Paged QML operation did not settle")

    try:
        listing = scene.find("workspaceMediaCatalog")
        until(lambda: scene.root.property("pageTotal") == 50_000 and not scene.root.property("libraryBusy")
              and listing.property("count") == 160 and not scene.root.property("chunkBusy"))
        assert listing.property("count") == 160
        assert [request["library_offset"] for request in bridge.chunk_requests] == [80]
        assert len(scene.evaluate("items")) == 80
        before = len(bridge.requests)
        search = scene.find("workspaceMediaSearch")
        scene.click(search)
        for character in "a film":
            QTest.keyClick(scene.window, Qt.Key(ord(character.upper())), Qt.NoModifier, 4)
        QTest.qWait(30)
        assert len(bridge.requests) == before, "Typing synchronously searched on every keystroke"
        until(lambda: len(bridge.requests) > before and not scene.root.property("libraryBusy"))
        assert len(bridge.requests) == before + 1, "Typed query was not debounced into one request"
        assert bridge.requests[-1]["library_query"] == "a film"
        assert scene.root.property("pageTotal") == 25_000
        until(lambda: listing.property("count") == 160 and not scene.root.property("chunkBusy"))
        # Scroll beyond two boundaries without replacing the first page or
        # requiring any page-button clicks. Prefetch may keep two blocks ahead,
        # while leaving the rest of the catalogue untouched.
        prefix = scene.evaluate("catalogModel.get(0).entry.id")
        listing.positionViewAtEnd()
        until(lambda: listing.property("count") >= 240)
        assert bridge.chunk_requests[0]["library_offset"] == 80
        assert scene.evaluate("catalogModel.get(0).entry.id") == prefix
        listing.positionViewAtEnd()
        until(lambda: listing.property("count") >= 320)
        assert 160 in [request["library_offset"] for request in bridge.chunk_requests]
        QTest.qWait(100)
        assert listing.property("count") <= 400, "Scroll prefetch greedily loaded the entire catalogue"
        assert len(bridge.chunk_requests) <= 5, "Scroll prefetch was not bounded near the viewport"
        continuous_rows = listing.property("count")
        assert scene.root.property("pageOffset") == 0
        assert scene.evaluate("catalogModel.get(0).entry.id") == prefix
        assert bridge.max_sent_rows <= 80

        # A delayed response for a former query may arrive after a newer page.
        # The fake intentionally delivers it; production QML must reject its echo.
        scene.root.setProperty("localQuery", "slow")
        until(bridge.slow_started.is_set)
        scene.root.setProperty("localQuery", "B film")
        until(lambda: bridge.deliveries[-1]["library_query"] == "B film" and not scene.root.property("libraryBusy"))
        current_ids = scene.evaluate("filteredItems.map(function(row) { return row.id })")
        browse_key = scene.root.property("catalogBrowseKey")
        bridge.release_slow.set()
        until(lambda: bridge.deliveries[-1]["library_query"] == "slow")
        QTest.qWait(30)
        assert scene.root.property("catalogBrowseKey") == browse_key
        assert scene.evaluate("filteredItems.map(function(row) { return row.id })") == current_ids
        assert len(scene.evaluate("catalogItems")) <= 80

        # Timer heartbeat spans actual key events, delayed results and paging.
        QTest.qWait(50)
        gaps = [(right - left) * 1000 for left, right in zip(beats, beats[1:])]
        assert len(beats) >= 40, {"heartbeats": len(beats)}
        assert max(gaps, default=0) < 100, {"largest_qt_heartbeat_gap_ms": max(gaps)}
        assert not scene.warnings, scene.warnings
        print(json.dumps({"backend_rows": len(bridge.catalogue), "frontend_max_rows": bridge.max_sent_rows,
                          "continuous_scroll_rows": continuous_rows, "chunk_offsets": [r["library_offset"] for r in bridge.chunk_requests],
                          "debounced_search": True, "stale_page_rejected": True,
                          "heartbeats": len(beats), "max_heartbeat_gap_ms": round(max(gaps), 2), "warnings": 0}))
    finally:
        timer.stop()
        bridge.release_slow.set()
        bridge.pool.shutdown(wait=True)
        scene.close()
        faulthandler.cancel_dump_traceback_later()


def index_fixture(root: Path, *, prepare=False):
    """Load/query the production SQLite index while Qt continues ticking."""
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import ExitStack
    import faulthandler
    import threading
    import time
    from unittest.mock import patch
    import sqlite3
    import urllib.request

    sys.path.insert(0, str(PROJECT))
    from PySide6.QtCore import QCoreApplication, QTimer
    from PySide6.QtTest import QTest
    from backend import media_contract as contract, media_host as host
    from backend import media_availability as availability, media_quick_availability as quick, media_discovery as discovery, media_library as library
    from backend.media_index import MediaIndex
    from backend.media_catalog_service import MediaCatalogService

    faulthandler.dump_traceback_later(3, repeat=True)
    app = QCoreApplication([])
    contract.STATE_DIR = root / "media"
    host.STATE_DIR = contract.STATE_DIR
    contract.save_prefs({"mode": "TV"})
    main_thread = threading.get_ident()
    db_threads = []
    original_ingest, original_browse = MediaIndex.ingest, MediaIndex.browse
    original_connect = sqlite3.connect

    def ingest(index, rows):
        db_threads.append(threading.get_ident())
        return original_ingest(index, rows)

    def browse(index, view, **kwargs):
        db_threads.append(threading.get_ident())
        return original_browse(index, view, **kwargs)

    def connect(*args, **kwargs):
        db_threads.append(threading.get_ident())
        return original_connect(*args, **kwargs)

    beats = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(time.perf_counter()))
    timer.start()

    def until(condition, timeout=8.5):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            app.processEvents()
            if condition():
                return
            # QTest.qWait holds Python's GIL on some Windows Qt builds; release
            # it between event pumps as the real Qt event loop does, so SQLite
            # worker rows are not artificially starved by the fixture.
            time.sleep(0.003)
        raise AssertionError("Production SQLite operation did not finish")

    path = root / "index" / "library.sqlite3"
    index = MediaIndex(path)

    def populate():
        index.initialize()
        def row(number):
            item = dict(id="indexed-" + str(number), kind="TV", content_type="movie",
                title=("A" if number % 2 == 0 else "B") + " film " + str(number).zfill(5),
                source="https://example.invalid/" + str(number) + ".mp4", media="vod", language="sv", category="Film",
                is_live=False, player="qml", play="video", season=0, episode=0)
            if number == 0:
                item.update(source="https://archive.org/details/indexed-film", archive_id="indexed-film")
            return item
        count = index.ingest(row(number) for number in range(50_000))
        # Synthetic proofs isolate paging performance from real network work.
        # Metadata and stale positives remain browseable without a decoder;
        # a known failed source remains withdrawn until its retry window.
        with index.connection() as db:
            db.execute("UPDATE items SET status='verified',checked_at=?,verified_until=?",
                       (time.time(), time.time() + 600))
            db.execute("UPDATE items SET status='unknown',checked_at=0,verified_until=0 WHERE id='indexed-0'")
            db.execute("UPDATE items SET status='failed',checked_at=?,retry_at=? WHERE id='indexed-1'",
                       (time.time(), time.time() + 600))
            db.execute("UPDATE items SET status='verified',checked_at=?,verified_until=? WHERE id='indexed-2'",
                       (time.time() - 31 * 86400, time.time() - 30 * 86400))
        index.ingest([
            dict(id="saved-channel", kind="TV", content_type="live", title="Saved channel",
                 source="https://example.invalid/live.m3u8", media="stream", language="sv", category="Live"),
            dict(id="saved-series", kind="TV", content_type="series", title="Saved archive series",
                 source="https://archive.org/details/saved-series", archive_id="saved-series",
                 media="collection", language="sv", category="Series"),
            dict(id="saved-episode", kind="TV", content_type="episode", title="Saved archive series S01E01",
                 series_title="Saved archive series", source="https://example.invalid/episode.mp4",
                 media="vod", language="sv", season=1, episode=1),
        ])
        for identifier in ("saved-channel", "saved-episode"):
            index.record(identifier, dict(status="verified", checked_at=time.time(), expires_at=time.time() + 600))
        index.meta("starter_version", "verified-paged-v1")
        index.meta("starter_content_revision", library.starter_revision())
        return count

    service = None
    started = time.perf_counter()
    with patch.object(MediaIndex, "ingest", ingest), patch.object(MediaIndex, "browse", browse), \
            patch.object(sqlite3, "connect", side_effect=connect):
        if prepare:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(populate)
                until(future.done)
                assert future.result() == 50_000
            ingest_ms = (time.perf_counter() - started) * 1000
            gaps = [(right - left) * 1000 for left, right in zip(beats, beats[1:])]
            assert main_thread not in db_threads
            assert len(beats) >= 30
            assert max(gaps, default=0) < 100, {"max_heartbeat_gap_ms": max(gaps)}
            timer.stop()
            faulthandler.cancel_dump_traceback_later()
            print(json.dumps({"actual_sqlite_ingested_rows": 50_000, "ingest_ms": round(ingest_ms, 2),
                              "heartbeats": len(beats), "max_heartbeat_gap_ms": round(max(gaps), 2),
                              "gui_database_calls": False}))
            return
        forbidden_calls, slot_times, published_pages = [], [], []

        def forbidden(name):
            def called(*args, **kwargs):
                forbidden_calls.append(name)
                raise AssertionError("Saved metadata browsing performed " + name)
            return called

        def browse_page(page="movies", *, letter="all", query="", offset=0):
            began = time.perf_counter()
            service.browse(page, letter, "all", "all", "all", query, offset)
            slot_times.append((time.perf_counter() - began) * 1000)
            until(lambda: not service._pending)
            payload = host.status_payload()
            assert not payload.get("library_error"), payload.get("library_error")
            assert len(payload["items"]) <= 80
            assert len(host._library_items) <= 81
            published_pages.append(payload)
            return payload

        def close_service():
            service.close()
            for name in ("_pool", "_verify_pool", "_metadata_pool", "_discovery_pool"):
                getattr(service, name).shutdown(wait=True, cancel_futures=True)
            app.processEvents()

        with ExitStack() as guards:
            # Use the persisted production bootstrap, without _ready shortcuts.
            # Unexpected work is logged even when worker error handling catches
            # the exception, so a blank/error page cannot mask the regression.
            for target, name in (
                (availability, "verify"), (quick, "quick_check"), (library, "expand_item"), (library, "resolve_item"),
                (library, "search_archive"), (library, "starter_catalog"),
                (discovery, "discover"), (contract, "catalog_for"), (contract, "iptv_catalog"),
                (contract, "probe_tools"), (urllib.request, "urlopen"),
            ):
                guards.enter_context(patch.object(target, name, side_effect=forbidden(name)))
            try:
                service = MediaCatalogService(index_path=path)
                first = browse_page()
                assert first["library_total"] == 49_999
                assert len(first["items"]) == 80
                by_id = {row["id"]: row for row in first["items"]}
                assert "indexed-1" not in by_id
                assert by_id["indexed-0"]["availability"] == "unknown"
                assert by_id["indexed-2"]["availability"] == "expired"
                assert all(row["availability"] in ("unknown", "available", "expired") for row in first["items"])

                second = browse_page(letter="B", offset=80)
                assert second["library_total"] == 24_999
                assert second["library_offset"] == 80
                assert len(second["items"]) == 80
                assert all(row["title"].startswith("B") for row in second["items"])
                failed = browse_page(query="B film 00001")
                assert failed["library_total"] == 0
                assert failed["items"] == []
                assert not failed["library_has_more"], "Unknown health must not create a phantom next page"

                # The same saved metadata is reused across tab visits, paging,
                # pauses and a completely fresh service instance.
                for _ in range(2):
                    live = browse_page("live")
                    assert [row["id"] for row in live["items"]] == ["saved-channel"]
                    series = browse_page("series")
                    assert [row["id"] for row in series["items"]] == ["saved-series"]
                    assert series["items"][0]["content_type"] == "series"
                    browse_page(offset=160)
                    service.set_active(False)
                    service.set_active(True)
                close_service()
                service = MediaCatalogService(index_path=path)
                reused = browse_page()
                assert reused["library_total"] == 49_999
                assert [row["id"] for row in reused["items"]] == [row["id"] for row in first["items"]]
                QTest.qWait(30)
                assert not forbidden_calls, {"ordinary_browse_work": forbidden_calls}
                assert main_thread not in db_threads, "SQLite catalogue loading or querying ran on Qt's thread"
                assert max(slot_times) < 50, {"browse_slots_ms": slot_times}
                gaps = [(right - left) * 1000 for left, right in zip(beats, beats[1:])]
                assert len(beats) >= 30, {"heartbeats": len(beats)}
                assert max(gaps, default=0) < 100, {"max_heartbeat_gap_ms": max(gaps)}
                print(json.dumps({"actual_sqlite_rows": first["library_total"], "page_rows": len(second["items"]),
                                  "browse_slot_max_ms": round(max(slot_times), 2), "metadata_browseable_without_decoder": True,
                                  "known_failed_source_hidden": True, "undecoded_sources_not_labelled_decoded": True,
                                  "saved_catalogue_reused": True, "ordinary_browse_io": forbidden_calls,
                                  "published_pages": len(published_pages), "heartbeats": len(beats),
                                  "max_heartbeat_gap_ms": round(max(gaps), 2), "gui_database_calls": False}))
            finally:
                if service is not None:
                    close_service()
                timer.stop()
                faulthandler.cancel_dump_traceback_later()


class MediaLoadingTests(unittest.TestCase):
    def scenario(self, name):
        with tempfile.TemporaryDirectory(prefix="gg-media-loading-") as temporary:
            root = Path(temporary)
            env = os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(root / "state"), GG_DESKTOP_DATA_ROOT=str(root / "data"),
                       QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic",
                       QML_DISABLE_DISK_CACHE="1", GG_USER_HOME=str(root / "home"))
            phases = ("index-prepare", "index-query") if name == "index" else (name,)
            for phase in phases:
                try:
                    result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--" + phase, str(root)],
                                            cwd=PROJECT, env=env, capture_output=True, text=True, timeout=10)
                except subprocess.TimeoutExpired as error:
                    stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or "")
                    stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
                    self.fail(phase + " exceeded its ten-second subprocess budget\n" + stdout + stderr)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())

    def test_cold_production_gui_slots_are_bounded_and_do_not_load_catalogues(self):
        self.scenario("cold")

    def test_real_qml_50k_backend_is_paged_debounced_and_responsive(self):
        self.scenario("qml")

    def test_actual_sqlite_50k_ingestion_and_service_queries_keep_qt_responsive(self):
        self.scenario("index")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--cold":
        cold_fixture(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "--qml":
        qml_fixture(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] in ("--index-prepare", "--index-query"):
        index_fixture(Path(sys.argv[2]), prepare=sys.argv[1] == "--index-prepare")
    else:
        unittest.main()
