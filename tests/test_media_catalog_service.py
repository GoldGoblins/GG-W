"""MEDIA catalogue/bridge races, isolated from user state and external services."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtGui import QGuiApplication
from backend import media_contract, media_host, media_library, media_availability, media_health_audit, media_quick_availability
from backend.media_index import MediaIndex
from backend.chat_surface_host import ChatSurfaceHost


def video(identifier, title, kind="TV", **values):
    return dict(id=identifier, title=title, kind=kind,
                source="https://example.invalid/" + identifier + ".mp4",
                media="vod", content_type="movie", play="video", player="qml", **values)


class IsolatedBridge(ChatSurfaceHost):
    """Run actual MEDIA slots while bypassing unrelated app/session startup."""

    def __init__(self):
        QObject.__init__(self)
        self._media_catalog = None
        self._media_embed = None
        self._torlink_embed = None
        self.publications = []

    def _console_sync(self, payload):
        pass

    def _media_follow(self, payload):
        return payload

    def _media_changed(self, payload):
        self.publications.append(payload)
        return super()._media_changed(payload)


class CatalogServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-media-service-")
        self.root = Path(self.temporary.name)
        self.library = self.root / "library"
        self.downloads = self.root / "downloads"
        self.library.mkdir()
        self.downloads.mkdir()
        self.stack = ExitStack()
        self.gates = []
        self.base = [video("film-alpha", "Alpha film"), video("film-beta", "Beta film")]
        self.music = [dict(video("music-alpha", "Alpha song", kind="MUSIC"), content_type="music", play="audio")]
        self.fetch = [video("fetch-alpha", "Finished download", kind="FETCH")]
        self.memo = {}
        host_values = dict(
            STATE_DIR=self.root / "state", _catalog_memo=self.memo, _extra_items=[],
            _search_mode="", _search_query="", _search_active=False, _library_busy=False,
            _library_error="", _library_collection="", _library_revision=0,
            _library_items={}, _library_children={}, _library_page_state={}, _library_page_items=[],
            _live_json="", _live_payload={}, _item=None, _backend="", _paused=False,
            _kind="audio", _want_source="", _qml_position=0.0, _qml_duration=0.0,
            _qml_playing=False, _qml_buffering=False, _qml_generation=0)
        for key, value in host_values.items():
            self.stack.enter_context(patch.object(media_host, key, value))
        self.stack.enter_context(patch.object(media_contract, "STATE_DIR", self.root / "state"))
        self.stack.enter_context(patch.object(media_contract, "LIBRARY_DIRS", (self.library,)))
        self.stack.enter_context(patch.object(media_contract, "FETCH_DIR", self.downloads))
        self.stack.enter_context(patch.object(media_contract, "_PREFS_CACHE", None))
        tools = {key: {"present": False, "path": ""} for key in ("cliamp", "vlc", "ffplay", "torlink", "yt-dlp", "retroarch")}
        tools["cores"] = {}
        self.stack.enter_context(patch.object(media_host, "probe_tools", return_value=tools))
        self.stack.enter_context(patch.object(media_host, "fetch_status", return_value={"present": False}))
        self.stack.enter_context(patch.object(media_host, "player_bin", return_value=""))
        self.stack.enter_context(patch.object(media_host, "_cached_rf", return_value={"kind": "NONE"}))
        self.stack.enter_context(patch.object(media_host, "library_roots", return_value=[self.library]))
        self.stack.enter_context(patch.object(media_host, "_cliamp_alive", return_value=False))
        self.stack.enter_context(patch.object(media_host, "_stop_spectrum_stream"))
        self.stack.enter_context(patch.object(media_host, "_stop_proc"))
        self.stack.enter_context(patch.object(media_host.libretro_host, "loaded", return_value=False))
        self.archive = self.stack.enter_context(patch.object(media_library, "search_archive", return_value=[]))
        self.verifier = self.stack.enter_context(patch.object(media_quick_availability, "quick_check", side_effect=lambda row, **kw:
            {"schema": media_quick_availability.SCHEMA, "status": "verified", "checked_at": time.time(), "expires_at": time.time() + 600,
             "scope": "http_media", "evidence": {"decoded": False, "reachable": True, "content_type": "video/mp4"}}))
        # These are synthetic source fixtures. Real metadata correspondence
        # cases are exercised by test_media_health_audit.py; catalogue tests
        # retain the production identity gate without making external requests.
        self.identity_checker = self.stack.enter_context(patch.object(media_quick_availability, "check_quick_identity",
            return_value={"status": "consistent", "scope": "fixture_metadata"}))
        self.stack.enter_context(patch.object(media_library, "_download_json", side_effect=AssertionError("Unexpected network access")))
        media_contract.save_prefs({"mode": "TV"})
        self.bridge = IsolatedBridge()
        self.service = self.bridge._media_library_service()
        self.gui_database_calls = []
        main_thread = threading.get_ident()
        original_connection = MediaIndex.connection
        @contextmanager
        def connection(index):
            if threading.get_ident() == main_thread:
                self.gui_database_calls.append("connection")
            with original_connection(index) as db:
                yield db
        self.stack.enter_context(patch.object(MediaIndex, "connection", connection))
        self.db_work(self.service.index.initialize)
        self.service._ready = True
        # Ordinary race tests isolate search/paging from bulk enrichment; the
        # discovery lifecycle has its own explicitly mocked checks below.
        self.service._discovery_started.update({"movies", "series"})
        self.service._scanned.update(media_contract.MODES)
        self.ingest(self.base + self.music + self.fetch)
        self.browse("movies")

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        self.service.close()
        self.service._pool.shutdown(wait=True, cancel_futures=True)
        self.service._verify_pool.shutdown(wait=True, cancel_futures=True)
        self.service._metadata_pool.shutdown(wait=True, cancel_futures=True)
        self.service._discovery_pool.shutdown(wait=True, cancel_futures=True)
        self.service._background_pool.shutdown(wait=True, cancel_futures=True)
        self.app.processEvents()
        self.assertFalse(self.gui_database_calls, "A GUI callback opened the catalogue database")
        self.stack.close()
        self.temporary.cleanup()

    def until(self, condition, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.005)
        self.fail("Timed out waiting for Qt catalogue operation")

    def settled(self):
        self.until(lambda: not self.service._pending and not self.service._checking
                   and not self.service._discovering and not self.service._refresh_timer.isActive())
        self.app.processEvents()

    def db_work(self, work):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(work)
            # Fixture setup can commit hundreds of independent source proofs.
            # GUI operations and race assertions retain their shorter budget.
            self.until(future.done, timeout=10)
            return future.result()

    def ingest(self, rows, *, verified=True):
        def work():
            self.service.index.ingest(rows)
            if verified:
                for row in rows:
                    self.service.index.record(row["id"], {"status": "verified", "checked_at": time.time(), "expires_at": time.time() + 600,
                        "evidence": {"decoded": True, "video_frames": 3, "audio_frames": 2}})
        self.db_work(work)

    def mark_ready(self, *identifiers):
        """Simulate completed background decoder proofs, using the real index."""
        def work():
            for identifier in identifiers:
                row = self.service.index.get(identifier)
                self.assertIsNotNone(row)
                self.service.index.record(identifier, {"status": "verified", "checked_at": time.time(),
                                          "expires_at": time.time() + 600,
                                          "evidence": {"video_frames": 3, "audio_frames": 2}}, source=row["source"])
        self.db_work(work)

    def browse(self, page, letter="all", season="all", query="", offset=0):
        self.bridge.mediaLibraryBrowse(page, letter, "all", "all", season, query, offset)
        self.settled()

    def identifiers(self, mode="TV"):
        return [row["id"] for row in media_host._catalog_rows(mode)]

    def test_empty_search_stays_empty_during_status_and_does_not_leak_between_modes(self):
        self.bridge.mediaLibrarySearch("nothing here")
        self.settled()
        self.assertEqual(self.identifiers(), [])
        self.assertEqual(media_host.status_payload()["items"], [])
        self.assertEqual(media_host.status_payload(live=True)["library_query"], "nothing here")
        self.assertEqual(self.identifiers("MUSIC"), [])
        self.bridge.mediaSetMode("MUSIC")
        self.settled()
        self.assertEqual(self.identifiers("MUSIC"), ["music-alpha"])

    def test_subsequent_query_searches_base_catalogue_instead_of_previous_results(self):
        self.bridge.mediaLibrarySearch("Alpha")
        self.settled()
        self.assertEqual(self.identifiers(), ["film-alpha"])
        self.bridge.mediaLibrarySearch("Beta")
        self.settled()
        self.assertEqual(self.identifiers(), ["film-beta"])
        self.browse("movies")
        self.assertEqual(set(self.identifiers()), {"film-alpha", "film-beta", "fetch-alpha"})

    def test_failed_archive_search_keeps_matching_local_title(self):
        self.archive.side_effect = TimeoutError("synthetic service failure")
        self.bridge.mediaLibrarySearch("Alpha")
        self.settled()
        self.assertEqual(self.identifiers(), ["film-alpha"])
        self.assertFalse(media_host.library_state()["library_busy"])

    def test_outdated_search_cannot_replace_more_recent_query(self):
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)

        def remote(query, **kwargs):
            if query == "Alpha":
                started.set()
                self.assertTrue(release.wait(2))
            return []

        self.archive.side_effect = remote
        self.bridge.mediaLibrarySearch("Alpha")
        self.assertTrue(started.wait(1))
        first_future = self.service._futures["search"]
        completed = threading.Event()
        first_future.add_done_callback(lambda future: completed.set())
        self.bridge.mediaLibrarySearch("Beta")
        self.until(lambda: media_host.library_state()["library_query"] == "Beta"
                   and not media_host.library_state()["library_busy"] and self.identifiers() == ["film-beta"])
        release.set()
        self.until(completed.is_set)
        self.app.processEvents()
        self.assertEqual(self.identifiers(), ["film-beta"])
        self.assertEqual(media_host.library_state()["library_query"], "Beta")

    def test_navigation_cancels_old_search_even_if_user_returns_to_same_mode(self):
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)

        def remote(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return [video("late-remote", "Late remote")]

        self.archive.side_effect = remote
        self.bridge.mediaLibrarySearch("Alpha")
        self.assertTrue(started.wait(1))
        future = self.service._futures["search"]
        completed = threading.Event()
        future.add_done_callback(lambda result: completed.set())
        self.bridge.mediaSetMode("MUSIC")
        self.bridge.mediaSetMode("TV")
        self.bridge.mediaLibraryBrowse("movies", "all", "all", "all", "all", "", 0)
        after_navigation = len(self.bridge.publications)
        release.set()
        self.until(completed.is_set)
        self.app.processEvents()
        self.settled()
        self.assertTrue({"film-alpha", "film-beta", "fetch-alpha"}.issubset(self.identifiers()))
        self.assertEqual(media_host.library_state()["library_page"], "movies")
        self.assertFalse(any(payload.get("library_query") == "Alpha"
                             for payload in self.bridge.publications[after_navigation:]),
                         "The obsolete search republished its former view after navigation")
        self.assertEqual(media_host.library_state()["library_query"], "")
        self.assertFalse(media_host.library_state()["library_busy"])

    def test_stop_prevents_pending_archive_resolution_from_starting_playback(self):
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        descriptor = dict(video("archive-pending", "Pending film"), archive_id="pending",
                          source="https://archive.org/details/pending")
        media_host.library_store(descriptor)

        def resolve(item):
            started.set()
            self.assertTrue(release.wait(2))
            return dict(item, source="https://archive.org/download/pending/film.mp4")

        with patch.object(media_library, "resolve_item", side_effect=resolve), patch.object(media_host, "play_item") as play:
            self.bridge.mediaPlay(descriptor["id"])
            self.assertTrue(started.wait(1))
            future = self.service._futures["play"]
            completed = threading.Event()
            future.add_done_callback(lambda result: completed.set())
            self.bridge.mediaStop()
            release.set()
            self.until(completed.is_set)
            self.app.processEvents()
            play.assert_not_called()
            self.assertIsNone(media_host._item)
            self.assertFalse(media_host.library_state()["library_busy"])

    def test_fetch_video_playback_retains_fetch_kind_and_browser_context(self):
        path = self.downloads / "Finished film.mp4"
        path.write_bytes(b"synthetic video path; decoder mocked")
        item = dict(self.fetch[0], source=str(path), media="file")
        self.ingest([item])
        self.bridge.mediaSetMode("FETCH")
        self.settled()
        with patch.object(media_host, "_halt_audio"):
            self.bridge.mediaPlay(item["id"])
            self.settled()
            payload = media_host.status_payload()
        self.assertEqual(payload["mode"], "FETCH")
        self.assertEqual(payload["now"]["kind"], "FETCH")
        self.assertEqual(payload["backend"], "qml")
        self.assertEqual(payload["now"]["source"], str(path.resolve()))

    def test_fetched_film_played_from_tv_library_keeps_tv_browser_context(self):
        path = self.downloads / "Finished film.mp4"
        path.write_bytes(b"synthetic video path; decoder mocked")
        item = dict(self.fetch[0], source=str(path), media="file")
        self.ingest([item])
        self.browse("movies")
        with patch.object(media_host, "_halt_audio"):
            self.bridge.mediaPlay(item["id"])
            self.settled()
            payload = media_host.status_payload()
        self.assertEqual(payload["mode"], "TV", "Playback changed the source-independent browser page")
        self.assertEqual(payload["now"]["kind"], "FETCH", "Source confinement metadata was lost")
        self.assertEqual(payload["backend"], "qml")

    def test_local_series_groups_without_losing_ids_and_opens_in_numeric_order(self):
        rows = [dict(video("episode-" + str(number), "Example S01E" + str(number)),
                     content_type="episode", series_title="Example", season=1, episode=number)
                for number in (10, 2, 1)]
        self.ingest(rows)
        self.browse("series")
        grouped = media_host._catalog_rows("TV")
        self.assertEqual(len(grouped), 1)
        parent = grouped[0]
        self.assertEqual((parent["content_type"], parent["title"]), ("series", "Example"))
        self.assertIsNone(media_host.item_by_id("episode-10"), "A non-visible ID leaked into GUI lookup state")
        self.bridge.mediaOpenCollection(parent["id"])
        self.settled()
        self.assertEqual(media_host.library_state()["library_collection"], "Example")
        self.assertEqual(self.identifiers(), ["episode-1", "episode-2", "episode-10"])
        self.assertEqual(media_host.item_by_id("episode-10")["episode"], 10)

    def test_separate_archive_uploads_join_one_series_and_preserve_episode_ids(self):
        rows = [dict(video("archive:" + identifier, "Example S01E" + str(number)),
                     source="https://archive.org/details/" + identifier, archive_id=identifier,
                     content_type="episode", provider="Internet Archive", language="sv",
                     series_title="Example", season=1, episode=number)
                for identifier, number in (("upload-ten", 10), ("upload-two", 2), ("upload-one", 1))]
        self.ingest(rows)
        self.browse("series")
        grouped = media_host._catalog_rows("TV")
        self.assertEqual(len(grouped), 1, "One series was fragmented by archive upload IDs")
        parent = grouped[0]
        self.bridge.mediaOpenCollection(parent["id"])
        self.settled()
        children = media_host._catalog_rows("TV")
        self.assertEqual([row["episode"] for row in children], [1, 2, 10])
        self.assertEqual({row["archive_id"] for row in children}, {"upload-one", "upload-two", "upload-ten"})
        self.assertEqual(media_host.item_by_id("archive:upload-ten")["episode"], 10)

    def test_direct_archive_link_search_skips_remote_discovery(self):
        self.bridge.mediaLibrarySearch("https://archive.org/details/example-film")
        self.settled()
        self.archive.assert_not_called()
        row = self.db_work(lambda: self.service.index.get(media_contract.item_id("TV", "https://archive.org/details/example-film")))
        self.assertEqual(row["archive_id"], "example-film")
        self.assertEqual(row["media"], "vod")
        self.assertFalse(row["is_live"])
        self.assertEqual(media_host.library_state()["library_query"], "https://archive.org/details/example-film",
                         "Direct-link lookup changed the public query echo and made QML reject its page")

    def test_direct_archive_link_ignores_active_letter_and_retains_public_echo(self):
        self.browse("movies", letter="B")
        url = "https://archive.org/details/example-film"
        descriptor = media_contract.query_item("TV", url)
        playable = dict(descriptor, source="https://archive.org/download/example-film/film.mp4")
        with patch.object(media_library, "expand_item", return_value=[playable]):
            self.bridge.mediaLibrarySearch(url)
            self.settled()
            self.assertIn(descriptor["id"], self.identifiers(), "A direct catalogue source should be selectable before checks")
            self.verifier.assert_not_called()
            self.bridge.mediaPlay(descriptor["id"])
            self.settled()
        self.archive.assert_not_called()
        self.assertIn(descriptor["id"], self.identifiers(),
                      "An unrelated active letter prevented direct source verification")
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], [descriptor["id"]])
        self.assertEqual(media_host.library_state()["library_query"], url)
        self.assertEqual(media_host.library_state()["library_letter"], "B")

    def test_known_metadata_and_inconclusive_checks_remain_browseable_but_definite_failures_wait_for_retry(self):
        rows = [video(identifier, identifier) for identifier in ("health-good", "health-unknown", "health-failed", "health-expired")]
        self.ingest(rows, verified=False)
        def mark():
            for identifier, status, expiry in (
                ("health-good", "verified", time.time() + 600),
                ("health-unknown", "unknown", 0), ("health-failed", "failed", 0),
                ("health-expired", "verified", time.time() - 1),
            ):
                self.service.index.record(identifier, {"status": status, "checked_at": time.time(), "expires_at": expiry})
        self.db_work(mark)
        self.verifier.side_effect = lambda row, **kw: {"status": "unknown", "checked_at": time.time(),
                                                     "expires_at": 0, "reason": "synthetic decoder unavailable"}
        self.browse("movies")
        self.assertIn("health-good", self.identifiers())
        states = {row["id"]:row["availability"] for row in media_host._catalog_rows("TV")}
        self.assertEqual({key:states[key] for key in states if key.startswith("health-")},
                         {"health-good":"available", "health-expired": "expired", "health-unknown": "unknown"})
        self.assertEqual(media_host.library_state()["library_total"], 6)
        for identifier in ("health-unknown", "health-failed", "health-expired"):
            self.assertIsNotNone(self.db_work(lambda identifier=identifier: self.service.index.get(identifier)),
                                 "Unready candidates must remain available to the independent checker")
        self.verifier.assert_not_called()
        # A known series can be browsed before checking its episodes; a check
        # of its container must not pretend those episodes were decoded.
        parent = dict(video("container-proof", "Container proof"), content_type="series")
        child = dict(video("unchecked-child", "Container S01E01"), content_type="episode",
                     series_title="Container proof", season=1, episode=1)
        self.ingest([parent])
        self.ingest([child], verified=False)
        self.browse("series")
        self.assertEqual(len(self.identifiers()), 1)
        self.assertNotEqual(media_host._catalog_rows("TV")[0]["availability_scope"], "checked_episodes",
                            "A container check was presented as checked episodes")
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified(child["id"])))
        self.mark_ready(child["id"])
        self.browse("series")
        self.assertEqual(len(self.identifiers()), 1)

    def test_changed_source_invalidates_old_verification(self):
        item = dict(self.base[0], source="https://example.invalid/replacement.mp4")
        self.ingest([item], verified=False)
        self.browse("movies")
        self.assertIn(item["id"], self.identifiers())
        self.assertEqual(next(row for row in media_host._catalog_rows("TV") if row["id"] == item["id"])["availability"], "unknown")
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified(item["id"])))
        self.verifier.assert_not_called()

    def test_fresh_radio_presets_are_browseable_without_bulk_checks_and_only_selected_station_is_checked(self):
        self.service._scanned.discard("RADIO")
        with patch.object(media_contract, "_http_get", side_effect=AssertionError("Radio opening fetched provider metadata")):
            self.bridge.mediaSetMode("RADIO")
            self.settled()
        rows = media_host._catalog_rows("RADIO")
        self.assertEqual(len(rows), len(media_contract.RADIO_PRESETS))
        self.assertTrue(rows)
        self.assertTrue(all(row["kind"] == "RADIO" and row["availability"] == "unknown"
                            and not row["availability_decoded"] for row in rows))
        self.verifier.assert_not_called()
        self.identity_checker.assert_not_called()
        selected = rows[0]["id"]
        with patch.object(media_host, "play_item", return_value=media_host.status_payload()) as play:
            self.bridge.mediaPlay(selected)
            self.settled()
            play.assert_called_once_with(selected)
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], [selected])
        self.assertEqual(self.verifier.call_args.kwargs["max_bytes"], 65536)

    def test_fresh_local_music_scan_keeps_all_1500_files_and_filters_by_artist(self):
        def clear_fixture_music():
            with self.service.index.connection() as db:
                db.execute("DELETE FROM items WHERE kind='MUSIC'")
        self.db_work(clear_fixture_music)
        rows = [dict(id="local-track-" + str(number), kind="MUSIC", content_type="music",
            source=str(self.library / (str(number) + ".mp3")), media="file", local=True,
            title="Local song " + str(number).zfill(4), artist="Artist " + str(number % 320).zfill(4),
            category="Artist " + str(number % 320).zfill(4), album="Local album", source_label="LOKAL",
            provider="Local", play="audio") for number in range(1500)]
        self.service._scanned.discard("MUSIC")
        with patch.object(media_contract, "music_catalog", return_value=rows) as scan:
            self.bridge.mediaSetMode("MUSIC")
            self.settled()
        scan.assert_called_once()
        self.assertEqual(media_host.library_state()["library_total"], 1500)
        visible = media_host._catalog_rows("MUSIC")
        self.assertEqual(len(visible), 80)
        self.assertTrue(all(row["media"] == "file" and row["source_label"] == "LOKAL"
                            and row["availability"] == "unknown" for row in visible))
        self.assertEqual([(row["artist"], row["title"]) for row in visible],
                         sorted((row["artist"], row["title"]) for row in visible))
        options = media_host.library_state()["library_categories"]
        self.assertEqual(len(options), 321, "Artist options were truncated to the old category limit")
        self.assertEqual(options[0]["label"], "Alla artister")
        artist = "Artist 0319"
        self.bridge.mediaLibraryBrowse("music", "all", artist, "all", "all", "", 0)
        self.settled()
        filtered = media_host._catalog_rows("MUSIC")
        self.assertTrue(filtered)
        self.assertTrue(all(row["artist"] == artist for row in filtered))
        self.assertEqual([row["title"] for row in filtered], sorted(row["title"] for row in filtered))
        self.verifier.assert_not_called()
        self.identity_checker.assert_not_called()

    def test_inconclusive_quick_check_attempts_actual_playback_without_claiming_a_check(self):
        item = video("quick-inconclusive", "Inconclusive source")
        self.ingest([item], verified=False)
        self.verifier.side_effect = lambda row, **kwargs: dict(status="unknown", checked_at=time.time(),
            expires_at=0, error="timeout", evidence={"decoded": False})
        with patch.object(media_availability, "verify", side_effect=AssertionError("Play invoked a decoder probe")), \
             patch.object(media_host, "play_item", return_value=media_host.status_payload()) as play:
            self.bridge.mediaPlay(item["id"])
            self.settled()
            play.assert_called_once_with(item["id"])
        saved = self.db_work(lambda: self.service.index.get(item["id"]))
        self.assertEqual(saved["source"], item["source"])
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified(item["id"])))
        self.assertFalse(media_host.library_state()["library_selection_error"])

    def test_saved_transport_selection_resolves_off_page_without_gui_lookup_scan(self):
        self.browse("movies", query="Alpha")
        self.assertIsNone(media_host.item_by_id("film-beta"))
        self.bridge.mediaPlay("film-beta")
        self.settled()
        self.assertEqual(media_host._item["id"], "film-beta")
        self.assertEqual(media_host.load_prefs()["mode"], "TV")
        self.assertFalse(self.gui_database_calls)

    def test_failed_actual_playback_withdraws_only_the_failed_source(self):
        self.bridge.mediaPlay("film-beta")
        self.settled()
        self.bridge.mediaReportSourceFailure("film-beta", media_host._qml_generation - 1)
        self.assertIn("film-beta", self.identifiers())
        self.bridge.mediaReportSourceFailure("film-beta", media_host._qml_generation)
        self.until(lambda: "film-beta" not in self.identifiers())
        self.assertEqual(set(self.identifiers()), {"film-alpha", "fetch-alpha"})
        self.assertEqual(media_host._item["availability"], "failed")

    def test_late_old_player_failure_cannot_revoke_replacement_source_proof(self):
        self.bridge.mediaPlay("film-beta")
        self.settled()
        old_source = media_host._item["source"]
        generation = media_host._qml_generation
        replacement = dict(self.base[1], title="Replacement film", source="https://example.invalid/new-beta.mp4")
        self.ingest([replacement])
        self.identity_checker.reset_mock()
        before_revision = media_host._library_revision
        self.bridge.mediaReportSourceFailure("film-beta", generation)
        self.until(lambda: media_host._library_revision > before_revision)
        self.settled()
        saved = self.db_work(lambda: self.service.index.get("film-beta"))
        self.assertEqual(saved["source"], replacement["source"])
        self.assertEqual(saved["title"], replacement["title"])
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified("film-beta")))
        visible = next(row for row in media_host._catalog_rows("TV") if row["id"] == "film-beta")
        self.assertEqual(visible["title"], replacement["title"])
        self.assertEqual(visible["availability"], "verified")
        self.assertEqual(media_host._item["source"], old_source)
        self.assertEqual(media_host._item["availability"], "failed")
        self.identity_checker.assert_not_called()
        self.verifier.assert_not_called()

    def test_late_old_player_failure_cannot_revoke_relabelled_same_url_proof(self):
        self.bridge.mediaPlay("film-beta")
        self.settled()
        replacement = dict(self.base[1], title="Updated programme", language="sv")
        self.ingest([replacement])
        before_revision = media_host._library_revision
        self.bridge.mediaReportSourceFailure("film-beta", media_host._qml_generation)
        self.until(lambda: media_host._library_revision > before_revision)
        self.settled()
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified("film-beta")))
        saved = self.db_work(lambda: self.service.index.get("film-beta"))
        self.assertEqual(saved["title"], replacement["title"])
        self.assertEqual(saved["language"], replacement["language"])
        self.assertIn("film-beta", self.identifiers())

    def test_gui_item_lookup_only_retains_current_page_and_selected_player(self):
        rows = [video("paged-" + str(number), "Paged film " + str(number).zfill(3)) for number in range(180)]
        self.ingest(rows)
        self.browse("movies", query="Paged")
        self.assertEqual(len(self.identifiers()), 80)
        first = self.identifiers()[0]
        self.browse("movies", query="Paged", offset=80)
        self.assertEqual(len(self.identifiers()), 80)
        self.assertIsNone(media_host.item_by_id(first))
        self.assertLessEqual(len(media_host._library_items), 81)
        with patch.object(media_contract, "catalog_for", side_effect=AssertionError("GUI fallback scan")):
            self.assertIsNone(media_host.item_by_id("missing-source-id"))

    def test_scroll_chunks_read_saved_labels_without_replacing_active_page_or_player(self):
        rows = [video("chunk-" + str(number), "Chunk film " + str(number).zfill(3)) for number in range(181)]
        self.ingest(rows)
        self.ingest([video("chunk-hidden", "Chunk film hidden")], verified=False)
        self.browse("movies", query="Chunk")
        active = media_host._library_page_state.copy()
        before_rows = self.identifiers()
        before_revision = media_host._library_revision
        before_publications = len(self.bridge.publications)
        playing = dict(id="already-playing", title="Already playing", source="file:///fixture.mp4")
        media_host._item = playing
        received = []
        self.bridge.mediaLibraryChunkReady.connect(lambda ticket, raw: received.append((ticket, json.loads(raw))))
        with patch.object(media_library, "expand_item", side_effect=AssertionError("Chunk expanded metadata")), \
             patch.object(media_library, "resolve_item", side_effect=AssertionError("Chunk resolved a source")), \
             patch.object(media_contract, "catalog_for", side_effect=AssertionError("Chunk scanned providers")):
            for ticket, offset, count in ((10, 80, 80), (11, 160, 22)):
                self.bridge.mediaLibraryChunk("movies", "all", "all", "all", "all", "Chunk", offset, ticket)
                self.until(lambda: received and received[-1][0] == ticket)
                payload = received[-1][1]
                self.assertEqual(payload["library_offset"], offset)
                self.assertEqual(payload["library_total"], 182)
                self.assertEqual(len(payload["items"]), count)
                self.assertEqual(payload["items"][0]["id"], "chunk-" + str(offset))
                self.assertNotIn("source", payload["items"][0])
                self.assertEqual(payload["library_chunk_error"], "")
        self.assertEqual(self.identifiers(), before_rows)
        self.assertEqual(media_host._library_page_state, active)
        self.assertEqual(media_host._library_revision, before_revision)
        self.assertEqual(len(self.bridge.publications), before_publications)
        self.assertIs(media_host._item, playing)
        self.assertLessEqual(len(media_host._library_items), 81)
        self.verifier.assert_not_called()

    def test_old_scroll_chunk_is_cancelled_when_filter_changes(self):
        self.ingest([video("chunk-" + str(number), "Chunk film " + str(number).zfill(3))
                     for number in range(180)])
        self.browse("movies", query="Chunk")
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        snapshot = self.service._accepted_snapshot
        original = snapshot.page
        def delayed(offset, **kwargs):
            if offset == 80:
                started.set()
                self.assertTrue(release.wait(2))
            return original(offset, **kwargs)
        received = []
        self.bridge.mediaLibraryChunkReady.connect(lambda ticket, raw: received.append((ticket, raw)))
        with patch.object(self.service, "_warm_snapshot"), patch.object(snapshot, "page", side_effect=delayed):
            self.bridge.mediaLibraryChunk("movies", "all", "all", "all", "all", "Chunk", 80, 20)
            self.until(started.is_set)
            old_future = self.service._futures["chunk"]
            self.bridge.mediaLibraryBrowse("movies", "all", "all", "all", "all", "Beta", 0)
            self.until(lambda: self.identifiers() == ["film-beta"] and not media_host.library_state()["library_busy"])
            release.set()
            self.until(old_future.done)
            self.settled()
        self.assertEqual(received, [])
        self.assertEqual(self.identifiers(), ["film-beta"])
        self.assertEqual(media_host.library_state()["library_offset"], 0)
        self.verifier.assert_not_called()

    def test_playing_off_page_channel_keeps_cursor_and_next_chunk_without_rescanning_inventory(self):
        rows = [dict(video("stable-channel-" + str(number), "Stable channel " + str(number).zfill(3)),
                     content_type="live", media="stream", is_live=True, channel_id="stable-" + str(number))
                for number in range(241)]
        self.ingest(rows)
        self.browse("live")
        self.service._audit_timer.stop()
        snapshot = self.service._accepted_snapshot
        before_rows = self.identifiers()
        received = []
        self.bridge.mediaLibraryChunkReady.connect(lambda ticket, raw: received.append((ticket, json.loads(raw))))
        self.bridge.mediaLibraryChunk("live", "all", "all", "all", "all", "", 80, 100)
        self.until(lambda: received and received[-1][0] == 100)
        self.assertEqual(received[-1][1]["items"][0]["id"], rows[80]["id"])
        with patch.object(self.service.index, "snapshot_groups", side_effect=AssertionError("Play rebuilt the browse inventory")):
            self.bridge.mediaPlay(rows[95]["id"])
            self.settled()
        self.assertEqual(media_host._item["id"], rows[95]["id"])
        self.assertIs(self.service._accepted_snapshot, snapshot)
        self.assertEqual(media_host.library_state()["library_catalog_revision"], snapshot.revision)
        self.assertEqual(self.identifiers(), before_rows)
        self.assertFalse(media_host.library_state()["library_requires_reset"])
        self.bridge.mediaLibraryChunk("live", "all", "all", "all", "all", "", 160, 101)
        self.until(lambda: received and received[-1][0] == 101)
        self.assertEqual(received[-1][1]["library_catalog_revision"], snapshot.revision)
        self.assertEqual(received[-1][1]["items"][0]["id"], rows[160]["id"])
        self.verifier.assert_not_called()

    def test_play_refresh_does_not_adopt_a_deferred_positive_admission_snapshot(self):
        rows = [dict(video("admission-channel-" + str(number), "Admission channel " + str(number).zfill(3)),
                     content_type="live", media="stream", is_live=True, channel_id="admission-" + str(number))
                for number in range(181)]
        self.ingest(rows)
        self.browse("live")
        self.service._audit_timer.stop()
        snapshot = self.service._accepted_snapshot
        inserted = dict(video("admission-new-channel", "A newly admitted channel"),
                        content_type="live", media="stream", is_live=True, channel_id="admission-new")
        self.ingest([inserted])
        self.service._poll_audit()
        self.settled()
        self.assertTrue(media_host.library_state()["library_background_refresh"])
        self.assertNotEqual(media_host.library_state()["library_catalog_revision"], snapshot.revision)
        self.assertIs(self.service._accepted_snapshot, snapshot, "Unaccepted admission replaced the active cursor")
        self.bridge.mediaPlay(rows[95]["id"])
        self.settled()
        self.assertIs(self.service._accepted_snapshot, snapshot)
        self.assertEqual(media_host.library_state()["library_catalog_revision"], snapshot.revision)
        self.assertNotIn(inserted["id"], self.identifiers())
        self.assertEqual(media_host._item["id"], rows[95]["id"])

    def test_failed_unknown_selection_keeps_existing_browse_snapshot(self):
        snapshot = self.service._accepted_snapshot
        before_rows = self.identifiers()
        self.bridge.mediaPlay("nonexistent-selected-source")
        self.settled()
        self.assertTrue(media_host.library_state()["library_selection_error"])
        self.assertIs(self.service._accepted_snapshot, snapshot)
        self.assertEqual(media_host.library_state()["library_catalog_revision"], snapshot.revision)
        self.assertEqual(self.identifiers(), before_rows)

    def test_failed_retained_channel_still_invalidates_snapshot_and_withdraws_dead_source(self):
        channel = dict(video("retained-dead-channel", "Retained channel"),
                       content_type="live", media="stream", is_live=True, channel_id="retained-channel")
        self.ingest([channel], verified=False)
        checked = time.time() - 3600
        self.db_work(lambda: self.service.index.record(channel["id"], dict(status="verified", checked_at=checked,
                     expires_at=checked + 900), source=channel["source"]))
        self.browse("live")
        snapshot = self.service._accepted_snapshot
        self.assertIn(channel["id"], self.identifiers())
        self.verifier.side_effect = lambda row, **kwargs: dict(status="failed", checked_at=time.time(), error="http_not_found")
        self.bridge.mediaPlay(channel["id"])
        self.settled()
        self.assertTrue(media_host.library_state()["library_selection_error"])
        self.assertIsNot(self.service._accepted_snapshot, snapshot)
        self.assertTrue(media_host.library_state()["library_requires_reset"])
        self.assertNotIn(channel["id"], self.identifiers())
        self.assertEqual(self.verifier.call_count, 1)

    def test_status_refresh_recovers_when_source_is_withdrawn_during_snapshot_read(self):
        snapshot = self.service._accepted_snapshot
        original_page = snapshot.page
        self.service._warm_cancel.set()
        if self.service._warm_future is not None:
            self.until(self.service._warm_future.done)
        def withdraw_then_read(offset, **kwargs):
            self.service.index.record("film-beta", dict(status="failed", checked_at=time.time()),
                                      source=self.base[1]["source"])
            return original_page(offset, **kwargs)
        with patch.object(snapshot, "page", side_effect=withdraw_then_read), \
             patch.object(self.service, "_warm_snapshot"):
            self.service._query(preserve_snapshot=True)
            self.settled()
        self.assertIsNot(self.service._accepted_snapshot, snapshot)
        self.assertNotIn("film-beta", self.identifiers())
        self.assertEqual(set(self.identifiers()), {"film-alpha", "fetch-alpha"})
        self.assertTrue(media_host.library_state()["library_requires_reset"])
        self.assertFalse(media_host.library_state()["library_error"])

    def test_scroll_chunk_keeps_selected_series_context_and_can_open_an_off_page_series(self):
        descriptor = dict(video("chunk-series", "Chunk series"), content_type="series", archive_id="chunk-series",
                          source="https://archive.org/details/chunk-series")
        episodes = [dict(video("chunk-episode-" + str(number), "Chunk S01E" + str(number).zfill(3)),
                         content_type="episode", series_title="Chunk series", archive_id="chunk-series",
                         season=1, episode=number, _encoding_groups_version=media_library.ENCODING_GROUPS_VERSION)
                    for number in range(1, 182)]
        self.ingest([descriptor], verified=False)
        self.ingest(episodes)
        # The GUI only retains movie labels here; a scrolled-off series opens
        # through a worker lookup, then reuses its saved episode inventory.
        self.browse("movies")
        self.assertIsNone(media_host.item_by_id(descriptor["id"]))
        with patch.object(media_library, "expand_item", side_effect=AssertionError("Cached episodes refetched")):
            self.bridge.mediaOpenCollection(descriptor["id"])
            self.settled()
            collection = self.service._view["collection_key"]
            before_rows = self.identifiers()
            received = []
            self.bridge.mediaLibraryChunkReady.connect(lambda ticket, raw: received.append((ticket, json.loads(raw))))
            self.bridge.mediaLibraryChunk("movies", "all", "all", "all", "all", "", 80, 30)
            self.until(lambda: received)
        payload = received[0][1]
        self.assertEqual(payload["library_collection_key"], collection)
        self.assertEqual(payload["library_total"], 181)
        self.assertEqual(payload["items"][0]["episode"], 81)
        self.assertEqual(self.identifiers(), before_rows)
        self.assertEqual(self.service._view["offset"], 0)
        self.verifier.assert_not_called()

    def test_scroll_chunk_failure_is_delivered_without_clearing_the_catalogue(self):
        received = []
        self.bridge.mediaLibraryChunkReady.connect(lambda ticket, raw: received.append((ticket, json.loads(raw))))
        before = self.identifiers()
        snapshot = self.service._accepted_snapshot
        with patch.object(self.service, "_warm_snapshot"), \
             patch.object(snapshot, "page", side_effect=RuntimeError("synthetic read failure")):
            self.bridge.mediaLibraryChunk("movies", "all", "all", "all", "all", "", 80, 40)
            self.until(lambda: received)
        self.assertEqual(received[0][0], 40)
        self.assertTrue(received[0][1]["library_chunk_error"])
        self.assertEqual(received[0][1]["items"], [])
        self.assertEqual(self.identifiers(), before)
        self.assertFalse(media_host.library_state()["library_busy"])

    def test_audit_progress_reads_only_cached_counts_off_gui_without_replacing_catalogue(self):
        import sqlite3
        from backend.media_health_audit import MediaHealthAudit
        self.ingest([video("audit-unchecked", "Audit unchecked")], verified=False)
        self.browse("movies")
        audit = MediaHealthAudit(self.service.index)
        run_id = self.db_work(audit.start)
        def progress_fixture():
            with self.service.index.connection() as db:
                keys = [row[0] for row in db.execute("SELECT source_key FROM media_audit_jobs WHERE run_id=? ORDER BY source_key", (run_id,))]
                self.assertEqual(len(keys), 4)
                for key, state in zip(keys, ("healthy", "failed", "queued", "running")):
                    db.execute("UPDATE media_audit_jobs SET state=? WHERE run_id=? AND source_key=?", (state, run_id, key))
                db.execute("UPDATE media_audit_runs SET status='running' WHERE id=?", (run_id,))
        self.db_work(progress_fixture)
        self.service._audit_timer.stop()
        before_rows = self.identifiers()
        before_revision = media_host._library_revision
        before_view = dict(self.service._view)
        main_thread = threading.get_ident()
        database_threads, statements = [], []
        original_connect = sqlite3.connect
        def connect(*args, **kwargs):
            database_threads.append(threading.get_ident())
            db = original_connect(*args, **kwargs)
            db.set_trace_callback(statements.append)
            return db
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        original_read = self.service._read_audit_progress
        def delayed_read():
            started.set()
            self.assertTrue(release.wait(2))
            return original_read()
        with patch.object(sqlite3, "connect", side_effect=connect), \
             patch.object(self.service, "_read_audit_progress", side_effect=delayed_read), \
             patch.object(self.service.index, "browse", side_effect=AssertionError("Progress rebuilt a catalogue page")), \
             patch.object(media_library, "expand_item", side_effect=AssertionError("Progress expanded metadata")):
            self.service._poll_audit()
            self.until(started.is_set)
            queued = self.service._futures["audit"]
            generation = self.service._generation["audit"]
            for _ in range(12):
                self.service._poll_audit()
            self.assertIs(self.service._futures["audit"], queued)
            self.assertEqual(self.service._generation["audit"], generation)
            release.set()
            self.settled()
        self.assertEqual(media_host.library_state()["library_audit"],
                             dict(total=4, done=2, healthy=1, pending=1, running=1, status="running", active_lanes=[]))
        self.assertEqual(self.identifiers(), before_rows)
        self.assertEqual(media_host._library_revision, before_revision)
        self.assertEqual(self.service._view, before_view)
        self.assertNotIn(main_thread, database_threads)
        self.assertTrue(database_threads)
        self.assertTrue(all("payload" not in statement.lower() for statement in statements))
        self.verifier.assert_not_called()

    def test_missing_audit_progress_does_not_initialize_tables_and_hidden_pane_does_not_poll(self):
        from backend.media_health_audit import MediaHealthAudit
        self.service._audit_timer.stop()
        with patch.object(MediaHealthAudit, "initialize", side_effect=AssertionError("Progress created an audit")):
            self.service._poll_audit()
            self.settled()
        self.assertNotIn("library_audit", media_host.library_state())
        def tables():
            with self.service.index.connection() as db:
                return [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'media_audit_%'")]
        self.assertEqual(self.db_work(tables), [])
        self.service.set_active(False)
        before_generation = self.service._generation["audit"]
        self.service._poll_audit()
        self.assertEqual(self.service._generation["audit"], before_generation)
        self.assertFalse(self.service._audit_timer.isActive())
        self.verifier.assert_not_called()

    def test_external_admission_refreshes_only_small_local_page_without_source_io(self):
        item = video("audit-new-ready", "Audit admitted film")
        self.browse("movies")
        self.service._audit_timer.stop()
        self.assertNotIn(item["id"], self.identifiers())
        before_view = dict(self.service._view)
        self.ingest([item])
        main_thread = threading.get_ident()
        threads, requests = [], []
        original = self.service.index.browse
        def browse(view, **kwargs):
            threads.append(threading.get_ident())
            requests.append(dict(view))
            return original(view, **kwargs)
        with patch.object(self.service.index, "browse", side_effect=browse), \
             patch.object(media_library, "expand_item", side_effect=AssertionError("Audit publication expanded a source")), \
             patch.object(media_library, "search_archive", side_effect=AssertionError("Audit publication searched providers")):
            self.service._poll_audit()
            self.settled()
            self.assertIn(item["id"], self.identifiers())
            self.assertTrue(media_host.library_state()["library_background_refresh"])
            self.assertEqual(self.service._view, before_view)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["offset"], before_view["offset"])
            self.assertNotIn(main_thread, threads)
            # Counters with the same catalogue marker do not rebuild the page.
            self.service._poll_audit()
            self.settled()
            self.assertEqual(len(requests), 1)
        self.verifier.assert_not_called()

    def test_retained_decoded_source_is_visible_and_rechecked_on_play(self):
        item = video("retained-film", "Previously checked film")
        self.ingest([item], verified=False)
        checked = time.time() - 3600
        self.db_work(lambda: self.service.index.record(item["id"], {
            "status": "verified", "checked_at": checked, "expires_at": checked + 900,
            "evidence": {"decoded": True, "video_frames": 3, "audio_frames": 2}}, source=item["source"]))
        self.browse("movies")
        summary = next(row for row in media_host._catalog_rows("TV") if row["id"] == item["id"])
        self.assertFalse(summary["availability_fresh"])
        self.assertEqual(summary["availability_scope"], "previously_decoded")
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified(item["id"])))
        self.bridge.mediaPlay(item["id"])
        self.settled()
        self.assertEqual(self.verifier.call_count, 1)
        self.assertEqual(self.verifier.call_args.args[0]["id"], item["id"])
        self.assertEqual(media_host._item["id"], item["id"])
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified(item["id"])))

    def test_optional_descriptive_metadata_is_not_a_selected_playback_prerequisite(self):
        item = dict(video("unconfirmed-label", "Example bonus"), content_type="episode",
                    series_title="Example", language="", season=0, episode=0)
        self.ingest([item], verified=False)
        self.verifier.reset_mock()
        with patch.object(media_health_audit, "prepare_identity", side_effect=AssertionError("Selected play requested deep metadata")):
            self.bridge.mediaPlay(item["id"])
            self.settled()
        self.verifier.assert_called_once()
        checked = self.verifier.call_args.args[0]
        self.assertEqual((checked["language"], checked["season"], checked["episode"], checked["title"]),
                         ("", 0, 0, "Example bonus"))
        self.assertEqual(media_host._item["title"], "Example bonus")
        self.assertEqual(self.db_work(lambda: self.service.index.get(item["id"]))["source"], item["source"])

    def test_metadata_correction_cannot_replace_a_newer_source_while_it_is_being_prepared(self):
        item = dict(video("correction-race", "Original programme"), language="sv")
        replacement = dict(item, title="New programme", source="https://example.invalid/new-source.mp4")
        self.ingest([item])
        def prepare(row):
            self.service.index.ingest([replacement])
            self.service.index.record(item["id"], dict(status="verified", checked_at=time.time(),
                expires_at=time.time() + 600), source=replacement["source"])
            return dict(row, language=""), dict(status="consistent", scope="link_identity")
        self.verifier.reset_mock()
        with patch.object(media_quick_availability, "prepare_quick_identity", side_effect=prepare):
            self.bridge.mediaPlay(item["id"])
            self.settled()
        saved = self.db_work(lambda: self.service.index.get(item["id"]))
        self.assertEqual((saved["title"], saved["source"]), (replacement["title"], replacement["source"]))
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified(item["id"])))
        self.verifier.assert_not_called()
        self.assertIsNone(media_host._item)

    def test_provider_resolver_cannot_overwrite_checked_curated_episode_identity(self):
        curated = dict(video("curated-episode", "Chosen title S02E03"), content_type="episode",
                       series_title="Chosen title", language="sv", season=2, episode=3,
                       collection_key="chosen-collection", archive_id="chosen-provider",
                       archive_file="S02E03.mp4")
        self.ingest([curated])
        provider = dict(curated, title="Provider container S01E01", series_title="Provider container",
                        language="en", season=1, episode=1, collection_key="provider-container")
        with patch.object(media_library, "resolve_item", return_value=provider):
            self.bridge.mediaPlay(curated["id"])
            self.settled()
        saved = self.db_work(lambda: self.service.index.get(curated["id"]))
        for key in ("title", "series_title", "language", "season", "episode", "collection_key"):
            self.assertEqual(saved[key], curated[key])
            self.assertEqual(self.identity_checker.call_args.args[0][key], curated[key])
            self.assertEqual(media_host._item[key], curated[key])
        self.verifier.assert_not_called()

    def test_actual_qml_background_admission_preserves_deep_scroll_then_updates_at_top(self):
        sys.path.insert(0, str(PROJECT / "tests"))
        from test_media_library_ui import MediaScene
        rows = [video("catalog-row-" + str(number), "Catalog film " + str(number).zfill(3))
                for number in range(240)]
        self.ingest(rows)
        self.service._audit_timer.stop()
        scene = MediaScene(PROJECT / "qml/components")
        scene.root.setProperty("surfaceHost", self.bridge)
        scene.root.applyStatus(self.bridge.mediaStatus())
        scene.root.selectPage("movies")
        scene.root.setProperty("localQuery", "Catalog film")
        try:
            listing = scene.find("workspaceMediaCatalog")
            self.until(lambda: scene.root.property("pageTotal") == 240 and not scene.root.property("libraryBusy")
                       and listing.property("count") == 80 and not scene.root.property("catalogSyncing"))
            scene.root.loadMore(False)
            self.until(lambda: listing.property("count") >= 160)
            listing.setProperty("currentIndex", 100)
            scene.evaluate("positionViewAtIndex(100, ListView.Center)", listing)
            self.until(lambda: listing.property("contentY") - listing.property("originY") >= 4000)
            before_y = listing.property("contentY")
            before_count = listing.property("count")
            before_ids = scene.evaluate("Array.from({length:catalogModel.count},function(_,i){return catalogModel.get(i).entry.id})")
            before_revision = scene.root.property("catalogStructureRevision")
            added = video("catalog-new-film", "Catalog film 000 extra")
            self.ingest([added])
            self.service._poll_audit()
            self.settled()
            self.until(lambda: scene.root.property("catalogUpdatePending"))
            self.assertGreaterEqual(listing.property("count"), before_count)
            self.assertLessEqual(listing.property("count"), before_count + 160)
            self.assertEqual(scene.evaluate("Array.from({length:" + str(before_count)
                + "},function(_,i){return catalogModel.get(i).entry.id})"), before_ids)
            self.assertEqual(listing.property("currentIndex"), 100)
            self.assertAlmostEqual(listing.property("contentY"), before_y, delta=1)
            self.assertEqual(scene.root.property("catalogStructureRevision"), before_revision)
            self.assertEqual(scene.root.property("pageTotal"), 240)
            scene.evaluate("positionViewAtBeginning()", listing)
            self.until(lambda: not scene.root.property("catalogUpdatePending")
                       and scene.root.property("pageTotal") == 241)
            self.assertIn(added["id"], scene.evaluate("catalogItems.map(function(row){return row.id})"))
            self.assertNotEqual(scene.root.property("catalogStructureRevision"), before_revision)
            self.assertFalse(scene.warnings, scene.warnings)
        finally:
            scene.close()
        self.verifier.assert_not_called()

    def test_real_qml_uses_actual_bridge_worker_pages_and_keeps_playing_when_filtered(self):
        sys.path.insert(0, str(PROJECT / "tests"))
        from test_media_library_ui import MediaScene
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        scene = MediaScene(PROJECT / "qml/components")
        scene.root.setProperty("surfaceHost", self.bridge)
        scene.root.applyStatus(self.bridge.mediaStatus())
        scene.root.selectPage("movies")
        try:
            self.until(lambda: scene.root.property("pageTotal") == 3 and not scene.root.property("libraryBusy"))
            listing = scene.find("workspaceMediaCatalog")
            self.assertEqual(listing.property("count"), 3)
            scene.click("workspaceMediaSearch")
            for letter in "alpha":
                QTest.keyClick(scene.window, Qt.Key(ord(letter.upper())), Qt.NoModifier)
            self.until(lambda: scene.root.property("pageTotal") == 1 and not scene.root.property("libraryBusy"))
            self.assertEqual(self.identifiers(), ["film-alpha"])
            scene.click("mediaLibrarySearchButton")
            self.until(lambda: not scene.root.property("libraryBusy"))
            self.archive.assert_called_with("alpha", limit=200)
            with patch.object(media_host, "_halt_audio"):
                scene.click("mediaCatalogRow_film-alpha")
                self.until(lambda: bool(media_host._item))
            self.assertEqual(media_host._item["id"], "film-alpha")
            player = scene.find("mediaVideoPlayer")
            self.until(lambda: player.property("sourceLoads") > 0)
            source_loads = player.property("sourceLoads")
            scene.root.setProperty("localQuery", "")
            scene.click("mediaNav_downloads")
            self.until(lambda: scene.root.property("pageTotal") == 1 and not scene.root.property("libraryBusy"))
            self.assertEqual(media_host._item["id"], "film-alpha")
            self.assertEqual(player.property("sourceLoads"), source_loads)
            self.assertLessEqual(len(scene.evaluate("catalogItems")), 80)
            self.assertFalse(scene.warnings, scene.warnings)
        finally:
            scene.close()

    def test_ordinary_browse_never_starts_source_checks_expansion_or_discovery(self):
        from backend import media_discovery
        unknown = video("discovered-unknown", "Discovered unknown film")
        self.ingest([unknown], verified=False)
        with patch.object(media_discovery, "discover", side_effect=AssertionError("browse discovery")) as discovery, \
             patch.object(media_library, "expand_item", side_effect=AssertionError("browse metadata")) as expansion:
            for page in ("movies", "live", "series", "movies"):
                self.browse(page)
            self.service.set_active(False)
            self.service.set_active(True)
            self.settled()
            self.assertIn(unknown["id"], self.identifiers())
            self.assertEqual(set(self.identifiers()), {"film-alpha", "film-beta", "fetch-alpha", unknown["id"]})
            self.assertEqual(next(row for row in media_host._catalog_rows("TV") if row["id"] == unknown["id"])["availability"], "unknown")
            discovery.assert_not_called()
            expansion.assert_not_called()
            self.verifier.assert_not_called()
            self.identity_checker.assert_not_called()
            self.assertFalse(media_host.library_state()["library_indexing"])

    def test_only_explicit_background_switch_starts_work_and_close_cancels_it(self):
        from backend import media_discovery, media_initial_validation
        from backend.media_background_work import empty_status
        started, cancelled = threading.Event(), threading.Event()
        self.service.set_active(False)
        def run(cancel, *, notify):
            started.set()
            notify(dict(empty_status(), running=True, paused=False, phase="checking"))
            if cancel.wait(2):
                cancelled.set()
            return empty_status()
        with patch.object(self.service._background_work, "run", side_effect=run) as work, \
             patch.object(media_discovery, "discover", side_effect=AssertionError("Implicit discovery")), \
             patch.object(media_initial_validation, "validate_initial", side_effect=AssertionError("Implicit initial check")):
            self.browse("movies")
            self.service.set_active(True)
            self.settled()
            self.bridge.mediaLibraryRefresh()
            self.settled()
            work.assert_not_called()
            before = time.monotonic()
            self.bridge.mediaLibraryBackground(True)
            self.assertLess(time.monotonic() - before, .1)
            self.until(started.is_set)
            self.service.set_active(False)
            self.assertFalse(cancelled.is_set(), "Hiding MEDIA cancelled explicitly started background work")
            self.service.close()
            self.assertTrue(cancelled.wait(1))

    def test_filter_change_cancels_abandoned_snapshot_builds_before_latest_view(self):
        began = {page: threading.Event() for page in ("movies", "series")}
        cancelled = {page: threading.Event() for page in began}
        original = self.service.index.snapshot_groups
        def scan(view, cancel=None):
            page = view["page"]
            if view["query"] == "slow" and page in began:
                began[page].set()
                if cancel is not None and cancel.wait(1):
                    cancelled[page].set()
                raise ValueError("MEDIA_SNAPSHOT_CANCELLED")
            return original(view, cancel=cancel)
        with patch.object(self.service.index, "snapshot_groups", side_effect=scan):
            for page in began:
                self.bridge.mediaLibraryBrowse(page, "all", "all", "all", "all", "slow", 0)
                self.until(began[page].is_set)
            started = time.monotonic()
            self.bridge.mediaLibraryBrowse("live", "all", "all", "all", "all", "", 0)
            self.settled()
            self.assertTrue(all(event.is_set() for event in cancelled.values()))
            self.assertLess(time.monotonic() - started, .75)
            self.assertEqual(media_host.library_state()["library_page"], "live")

    def test_channel_refresh_stays_local_when_background_switch_is_off(self):
        from backend import media_sources
        calls = []
        def refresh(index, *, cancel):
            calls.append(threading.get_ident())
            index.ingest_discovered([dict(video("new-channel", "A newly found channel"), content_type="live")])
            return dict(error="", candidate_sources=1, verified_by_import=0)
        with patch.object(media_sources, "refresh", side_effect=refresh) as official, \
             patch.object(media_contract, "iptv_catalog", side_effect=AssertionError("Unneeded duplicate source import")):
            self.browse("live")
            self.settled()
            official.assert_not_called()
            self.bridge.mediaLibraryRefresh()
            self.settled()
            official.assert_not_called()
            self.assertEqual(calls, [])
            self.assertNotIn("new-channel", self.identifiers())
            self.verifier.assert_not_called()

    def test_verified_matches_are_published_before_slow_external_search_finishes(self):
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        def remote(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return []
        self.archive.side_effect = remote
        self.bridge.mediaLibrarySearch("Alpha")
        self.assertTrue(started.wait(1))
        self.until(lambda: self.identifiers() == ["film-alpha"]
                   and not media_host.library_state()["library_busy"])
        self.assertIn("search", self.service._pending)
        self.assertTrue(media_host.library_state()["library_indexing"])
        release.set()
        self.settled()
        self.assertEqual(self.identifiers(), ["film-alpha"])
        self.assertFalse(media_host.library_state()["library_indexing"])

    def test_background_discovery_cannot_occupy_interactive_paging_workers(self):
        from backend.media_background_work import empty_status
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        self.service._discovery_started.discard("movies")
        def run(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return empty_status()
        with patch.object(self.service._background_work, "run", side_effect=run):
            self.bridge.mediaLibraryBackground(True)
            self.until(started.is_set)
            self.bridge.mediaLibraryBrowse("movies", "all", "all", "all", "all", "Beta", 0)
            self.until(lambda: self.identifiers() == ["film-beta"]
                       and not media_host.library_state()["library_busy"])
            self.assertFalse(release.is_set(), "Paging waited until discovery finished")
            release.set()
            self.until(self.service._background_future.done)
            self.settled()

    def test_refresh_and_repeated_start_do_not_duplicate_running_background_job(self):
        from backend.media_background_work import empty_status
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        self.service._discovery_started.discard("movies")
        def run(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return empty_status()
        with patch.object(self.service._background_work, "run", side_effect=run) as work:
            self.bridge.mediaLibraryBackground(True)
            self.until(started.is_set)
            self.bridge.mediaLibraryBackground(True)
            self.bridge.mediaLibraryRefresh()
            self.until(lambda: not media_host.library_state()["library_busy"])
            self.assertEqual(work.call_count, 1)
            release.set()
            self.until(self.service._background_future.done)
            self.settled()

    def test_switch_pauses_existing_external_audit_off_gui_and_reports_real_checkpoint(self):
        from backend.media_health_audit import MediaHealthAudit
        audit = MediaHealthAudit(self.service.index)
        run_id = self.db_work(audit.start)
        def running_fixture():
            with self.service.index.connection() as db:
                db.execute("UPDATE media_audit_runs SET status='running',owner='external-fixture',lease_until=? WHERE id=?",
                           (time.time() + 60, run_id))
        self.db_work(running_fixture)
        self.service._poll_audit()
        self.settled()
        state = json.loads(self.bridge.mediaLibraryBackgroundStatus())
        self.assertTrue(state["running"])
        self.assertTrue(state["external"])
        original = self.service._background_work.pause
        def pause(cancel, *, notify):
            return original(cancel, wait_seconds=0, notify=notify)
        with patch.object(self.service._background_work, "pause", side_effect=pause):
            before = time.monotonic()
            self.bridge.mediaLibraryBackground(False)
            self.assertLess(time.monotonic() - before, .1)
            self.until(self.service._background_pause_future.done)
            self.app.processEvents()
        self.assertTrue(self.db_work(audit.status)["cancel_requested"])
        self.assertTrue(json.loads(self.bridge.mediaLibraryBackgroundStatus())["pausing"])
        def stopped_fixture():
            with self.service.index.connection() as db:
                db.execute("UPDATE media_audit_runs SET status='paused',owner='',lease_until=0 WHERE id=?", (run_id,))
        self.db_work(stopped_fixture)
        self.service._poll_audit()
        self.settled()
        state = json.loads(self.bridge.mediaLibraryBackgroundStatus())
        self.assertTrue(state["paused"])
        self.assertFalse(state["running"])
        self.verifier.assert_not_called()

    def test_replaced_source_rejects_proof_from_former_url(self):
        original = video("source-proof", "Source proof")
        replacement = dict(original, source="https://example.invalid/replacement.mp4")
        def exercise():
            self.service.index.ingest([original])
            self.service.index.ingest([replacement])
            self.service.index.record(original["id"], {"status": "verified", "checked_at": time.time(),
                                      "expires_at": time.time() + 600}, source=original["source"])
            return self.service.index.is_verified(original["id"])
        self.assertFalse(self.db_work(exercise), "A completed old-URL probe certified its replacement")

    def test_selecting_another_source_cancels_previous_check_without_failure_backoff(self):
        item = video("pending-health", "Pending health")
        self.ingest([item], verified=False)
        started, cancelled = threading.Event(), threading.Event()
        def check(row, *, cancel, **limits):
            started.set()
            if cancel.wait(2):
                cancelled.set()
            return {"status": "unknown", "checked_at": time.time(), "expires_at": 0}
        self.verifier.side_effect = check
        self.bridge.mediaPlay(item["id"])
        self.until(started.is_set)
        self.bridge.mediaPlay("film-beta")
        self.until(cancelled.is_set)
        self.settled()
        def health():
            with self.service.index.connection() as db:
                return tuple(db.execute("SELECT status,checked_at,retry_at FROM items WHERE id=?", (item["id"],)).fetchone())
        self.assertEqual(self.db_work(health), ("unknown", 0, 0))
        self.assertEqual(media_host._item["id"], "film-beta")

    def test_check_refresh_coalesces_behind_in_flight_user_browse(self):
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        original = self.service.index.browse
        def browse(view, **kwargs):
            if view["query"] == "Beta" and not release.is_set():
                started.set()
                self.assertTrue(release.wait(2))
            return original(view, **kwargs)
        with patch.object(self.service.index, "browse", side_effect=browse):
            self.bridge.mediaLibraryBrowse("movies", "all", "all", "all", "all", "Beta", 0)
            self.assertTrue(started.wait(1))
            ticket = self.service._generation["browse"]
            for _ in range(10):
                self.service._refresh_page()
            self.assertEqual(self.service._generation["browse"], ticket,
                             "A background timer superseded the active user browse")
            release.set()
            self.settled()
        self.assertEqual(self.identifiers(), ["film-beta"])
        self.assertLessEqual(self.service._generation["browse"] - ticket, 1,
                             "Ten check completions queued more than one follow-up page")

    def test_large_series_catalogue_uses_indexed_known_children_without_bulk_checks(self):
        from backend.media_index import view_request
        rows = [dict(video("series-load-" + str(number),
                    "Load series " + str(number % 5000).zfill(5) + " S01E01"),
                    content_type="episode", series_title="Load series " + str(number % 5000).zfill(5),
                    season=1, episode=number // 5000 + 1)
                for number in range(20000)]
        view = view_request("series", query="Load series")
        def exercise():
            self.service.index.ingest(rows)
            with self.service.index.connection() as db:
                db.execute("UPDATE items SET status='verified',checked_at=?,verified_until=? "
                           "WHERE type='episode' AND rowid % 43=0", (time.time(), time.time() + 600))
                expected = db.execute("SELECT COUNT(DISTINCT parent_key) FROM items WHERE type='episode' "
                                      "AND parent_key<>''").fetchone()[0]
                where, args = self.service.index._where(view, verified=True)
                plan = db.execute("EXPLAIN QUERY PLAN SELECT COUNT(DISTINCT i.group_key) FROM items i WHERE "
                                  + where, args).fetchall()
            began = time.perf_counter()
            result = self.service.index.browse(view)
            return result, expected, time.perf_counter() - began, " ".join(str(tuple(row)) for row in plan)
        result, expected, elapsed, plan = self.db_work(exercise)
        self.assertIn("media_series", plan)
        self.assertEqual(result["library_total"], expected)
        self.assertGreater(expected, 100)
        self.assertEqual(expected, 5000)
        self.assertEqual(len(result["items"]), 80)
        self.assertLess(elapsed, 1.0, "Series paging regressed to a correlated catalogue scan")

    def test_invalid_playlist_html_preserves_last_successful_cache(self):
        good = b'#EXTM3U\n#EXTINF:-1 tvg-id="sample",Sample\nhttps://example.invalid/live.m3u8\n'
        path = media_contract.ensure_state_dir() / "tv-test.m3u"
        path.write_bytes(good)
        os.utime(path, (0, 0))
        with patch.object(media_contract, "_http_get", return_value=b"<!doctype html><title>Service unavailable</title>"):
            result = media_contract._cached_bytes("tv-test.m3u", "https://example.invalid/list.m3u")
        self.assertEqual(result, good)
        self.assertEqual(path.read_bytes(), good)

    def test_click_checks_only_selected_source_and_keeps_catalogue_interactive(self):
        rows = [video("lazy-selected", "Selected film"), video("lazy-other", "Other film")]
        self.ingest(rows, verified=False)
        self.browse("movies")
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        def verify(row, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return {"status": "verified", "checked_at": time.time(), "expires_at": time.time() + 600}
        self.verifier.side_effect = verify
        self.bridge.mediaPlay("lazy-selected")
        self.until(started.is_set)
        state = media_host.library_state()
        self.assertFalse(state["library_busy"])
        self.assertEqual(state["library_loading_id"], "lazy-selected")
        self.assertEqual(set(self.identifiers()), {"film-alpha", "film-beta", "fetch-alpha", "lazy-selected", "lazy-other"})
        release.set()
        self.settled()
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], ["lazy-selected"])
        self.assertEqual(media_host._item["id"], "lazy-selected")
        self.assertEqual(media_host._item["availability"], "available")
        states = {row["id"]: row["availability"] for row in media_host._catalog_rows("TV")}
        self.assertEqual(states["lazy-selected"], "available")
        self.assertEqual(states["lazy-other"], "unknown")
        self.assertEqual(media_host.library_state()["library_loading_id"], "")

    def test_selected_unready_source_failure_stays_hidden_and_preserves_working_playback(self):
        self.ingest([video("lazy-failed", "Selected failed film")], verified=False)
        self.browse("movies")
        before = self.identifiers()
        self.bridge.mediaPlay("film-alpha")
        self.settled()
        self.verifier.return_value = None
        self.verifier.side_effect = lambda row, **kwargs: {"status": "failed", "checked_at": time.time()}
        self.bridge.mediaPlay("lazy-failed")
        self.settled()
        self.assertEqual(self.identifiers(), [identifier for identifier in before if identifier != "lazy-failed"])
        self.assertNotIn("lazy-failed", self.identifiers())
        def stored_status():
            with self.service.index.connection() as db:
                return db.execute("SELECT status FROM items WHERE id='lazy-failed'").fetchone()[0]
        self.assertEqual(self.db_work(stored_status), "failed")
        self.assertTrue(media_host.library_state()["library_selection_error"])
        self.assertFalse(media_host.library_state()["library_loading_id"])
        self.assertEqual(media_host._item["id"], "film-alpha")

    def test_one_click_uses_fresh_checked_alternate_when_selected_source_fails(self):
        selected = video("same-film-dead", "Same film")
        alternate = video("same-film-working", "Same film")
        self.ingest([selected], verified=False)
        self.ingest([alternate])
        self.verifier.reset_mock()
        self.verifier.side_effect = lambda row, **kwargs: dict(status="failed", checked_at=time.time(), error="http_not_found")
        ready = []
        self.service.playReady.connect(ready.append)
        self.bridge.mediaPlay(selected["id"])
        self.settled()
        self.assertEqual([item["id"] for item in ready], [alternate["id"]])
        self.assertEqual(media_host._item["id"], alternate["id"])
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], [selected["id"]])
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified(selected["id"])))
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified(alternate["id"])))
        self.assertFalse(media_host.library_state()["library_selection_error"])

    def test_fallback_does_not_probe_unknown_or_outdated_alternatives(self):
        selected = video("same-film-dead", "Same film")
        unknown = video("same-film-unknown", "Same film")
        retained = video("same-film-retained", "Same film")
        self.ingest([selected, unknown, retained], verified=False)
        self.db_work(lambda: self.service.index.record(retained["id"], dict(status="verified",
            checked_at=time.time() - 3600, expires_at=time.time() - 1)))
        self.verifier.reset_mock()
        self.verifier.side_effect = lambda row, **kwargs: dict(status="failed", checked_at=time.time(), error="http_not_found")
        self.identity_checker.reset_mock()
        self.bridge.mediaPlay(selected["id"])
        self.settled()
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], [selected["id"]])
        self.assertEqual([call.args[0]["id"] for call in self.identity_checker.call_args_list], [selected["id"]])
        self.assertIsNone(media_host._item)
        self.assertTrue(media_host.library_state()["library_selection_error"])

    def test_new_selection_cancels_old_failed_source_before_it_can_start_an_alternate(self):
        selected = video("same-film-dead", "Same film")
        alternate = video("same-film-working", "Same film")
        self.ingest([selected], verified=False)
        self.ingest([alternate])
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        def failed(row, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return dict(status="failed", checked_at=time.time(), error="http_not_found")
        self.verifier.side_effect = failed
        ready = []
        self.service.playReady.connect(ready.append)
        with patch.object(self.service.index, "group_sources", wraps=self.service.index.group_sources) as groups:
            self.bridge.mediaPlay(selected["id"])
            self.until(started.is_set)
            self.bridge.mediaPlay("film-alpha")
            self.until(lambda: media_host._item and media_host._item["id"] == "film-alpha")
            release.set()
            self.settled()
            groups.assert_not_called()
        self.assertEqual([item["id"] for item in ready], ["film-alpha"])
        self.assertEqual(media_host._item["id"], "film-alpha")

    def test_changed_selected_title_cannot_trigger_an_alternate_from_the_former_group(self):
        selected = video("same-film-dead", "Same film")
        alternate = video("same-film-working", "Same film")
        self.ingest([selected], verified=False)
        self.ingest([alternate])
        def failed(row, **kwargs):
            self.service.index.ingest([dict(selected, title="Different film")])
            return dict(status="failed", checked_at=time.time(), error="http_not_found")
        self.verifier.side_effect = failed
        ready = []
        self.service.playReady.connect(ready.append)
        self.bridge.mediaPlay(selected["id"])
        self.settled()
        self.assertEqual(ready, [])
        self.assertIsNone(media_host._item)
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified(alternate["id"])))

    def test_fallback_attempts_at_most_three_fresh_alternatives_and_never_new_probes(self):
        selected = video("same-film-dead", "Same film")
        alternatives = [video("same-film-alt-" + str(n), "Same film") for n in range(5)]
        self.ingest([selected], verified=False)
        self.ingest(alternatives)
        self.verifier.reset_mock()
        self.verifier.side_effect = lambda row, **kwargs: dict(status="failed", checked_at=time.time(), error="http_not_found")
        def identity(row):
            return dict(status="consistent" if row["id"] == selected["id"] else "unknown", scope="fixture_metadata")
        self.identity_checker.reset_mock()
        self.identity_checker.side_effect = identity
        self.bridge.mediaPlay(selected["id"])
        self.settled()
        self.assertEqual(self.identity_checker.call_count, 4)
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], [selected["id"]])
        self.assertIsNone(media_host._item)

    def test_same_url_different_public_header_context_can_be_a_checked_alternate(self):
        source = "https://example.invalid/shared.mp4"
        selected = dict(video("same-film-denied", "Same film"), source=source, referrer="https://publisher.invalid/denied")
        alternate = dict(video("same-film-allowed", "Same film"), source=source, referrer="https://publisher.invalid/allowed")
        self.ingest([selected], verified=False)
        self.ingest([alternate])
        self.verifier.reset_mock()
        self.verifier.side_effect = lambda row, **kwargs: dict(status="failed", checked_at=time.time(), error="access_denied")
        self.bridge.mediaPlay(selected["id"])
        self.settled()
        self.assertEqual(media_host._item["id"], alternate["id"])
        self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], [selected["id"]])

    def test_fallback_does_not_retry_the_same_known_failed_request_context_under_another_id(self):
        source = "https://example.invalid/shared.mp4"
        selected = dict(video("same-context-failed", "Same film"), source=source)
        duplicate = dict(video("same-context-cached", "Same film"), source=source)
        self.ingest([selected], verified=False)
        self.ingest([duplicate])
        self.verifier.reset_mock()
        self.verifier.side_effect = lambda row, **kwargs: dict(status="failed", checked_at=time.time(), error="http_not_found")
        self.identity_checker.reset_mock()
        self.bridge.mediaPlay(selected["id"])
        self.settled()
        self.assertIsNone(media_host._item)
        self.assertEqual([call.args[0]["id"] for call in self.identity_checker.call_args_list], [selected["id"]])
        self.assertEqual(self.verifier.call_count, 1)

    def test_selected_archive_live_and_other_vod_all_use_the_same_fast_budget(self):
        archive = dict(video("archive-budget", "Archive feature"), archive_id="feature",
                       archive_file="feature.mp4", source="https://archive.org/download/feature/feature.mp4")
        live = dict(video("live-budget", "Live channel"), content_type="live", media="stream", is_live=True)
        other = video("other-budget", "Other feature")
        for item in (archive, live, other):
            with self.subTest(identifier=item["id"]):
                self.ingest([item], verified=False)
                self.verifier.reset_mock()
                self.bridge.mediaPlay(item["id"])
                self.settled()
                self.verifier.assert_called_once()
                kwargs = self.verifier.call_args.kwargs
                self.assertIn("cancel", kwargs)
                self.assertEqual((kwargs["max_seconds"], kwargs["max_bytes"]), (4.0, 65536))
                self.assertEqual(media_host._item["id"], item["id"])

    def test_selected_source_rejects_old_identity_proof_before_starting_playback(self):
        original = video("renamed-during-check", "Original programme")
        replacement = dict(original, title="Different programme", language="sv", year="2001")
        self.ingest([original], verified=False)
        self.bridge.mediaPlay("film-alpha")
        self.settled()
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        def verify(row, **kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return {"status": "verified", "checked_at": time.time(), "expires_at": time.time() + 600,
                    "evidence": {"video_frames": 3, "audio_frames": 2}}
        self.verifier.side_effect = verify
        self.bridge.mediaPlay(original["id"])
        self.until(started.is_set)
        self.ingest([replacement], verified=False)
        release.set()
        self.settled()
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified(original["id"])))
        saved = self.db_work(lambda: self.service.index.get(original["id"]))
        self.assertEqual(saved["title"], replacement["title"])
        self.assertEqual(media_host._item["id"], "film-alpha")
        self.assertNotIn(original["id"], self.identifiers())
        self.assertTrue(media_host.library_state()["library_selection_error"])

    def test_selected_resolution_cannot_overwrite_newer_source_before_checking(self):
        original = video("changed-during-resolution", "Original programme")
        replacement = dict(original, title="Replacement programme", source="https://example.invalid/replacement.mp4")
        self.ingest([original], verified=False)
        ready = []
        self.service.playReady.connect(ready.append)
        def resolve(row):
            self.service.index.ingest([replacement])
            return dict(row)
        with patch.object(media_library, "resolve_item", side_effect=resolve):
            self.bridge.mediaPlay(original["id"])
            self.settled()
        saved = self.db_work(lambda: self.service.index.get(original["id"]))
        self.assertEqual(saved["source"], replacement["source"])
        self.assertEqual(saved["title"], replacement["title"])
        self.identity_checker.assert_not_called()
        self.verifier.assert_not_called()
        self.assertEqual(ready, [])
        self.assertIsNone(media_host._item)
        self.assertTrue(media_host.library_state()["library_selection_error"])

    def test_selected_collection_resolution_rejects_changed_descriptor_without_inserting_children(self):
        original = dict(video("changed-descriptor", "Original archive"), archive_id="original-archive",
                        source="https://archive.org/details/original-archive")
        replacement = dict(original, title="Replacement archive", archive_id="replacement-archive",
                           source="https://archive.org/details/replacement-archive")
        child = dict(video("obsolete-child", "Original series S01E01"), content_type="episode",
                     series_title="Original series", season=1, episode=1)
        self.ingest([original], verified=False)
        def expand(row):
            self.service.index.ingest([replacement])
            return [child]
        with patch.object(media_library, "resolve_item", side_effect=RuntimeError("MEDIA_ARCHIVE_CHOOSE_EPISODE")), \
             patch.object(media_library, "expand_item", side_effect=expand):
            self.bridge.mediaPlay(original["id"])
            self.settled()
        saved = self.db_work(lambda: self.service.index.get(original["id"]))
        self.assertEqual(saved["source"], replacement["source"])
        self.assertEqual(saved["title"], replacement["title"])
        self.assertIsNone(self.db_work(lambda: self.service.index.get(child["id"])))
        self.identity_checker.assert_not_called()
        self.verifier.assert_not_called()
        self.assertIsNone(media_host._item)
        self.assertEqual(media_host.library_state()["library_collection"], "")
        self.assertTrue(media_host.library_state()["library_selection_error"])

    def test_selected_cached_decoder_proof_cannot_bypass_definite_source_identity_failure(self):
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified("film-beta")))
        self.identity_checker.return_value = {"status": "failed", "scope": "source_metadata", "reason": "archive_source_mismatch"}
        self.bridge.mediaPlay("film-beta")
        self.settled()
        self.identity_checker.assert_called_once()
        self.verifier.assert_not_called()
        self.assertFalse(self.db_work(lambda: self.service.index.is_verified("film-beta")))
        self.assertNotIn("film-beta", self.identifiers())
        self.assertEqual(set(self.identifiers()), {"film-alpha", "fetch-alpha"})
        self.assertIsNone(media_host._item)
        self.assertTrue(media_host.library_state()["library_selection_error"])

    def test_selected_series_expands_only_its_metadata_and_checks_only_clicked_episode(self):
        descriptors = [dict(video("lazy-series-" + suffix, title), content_type="series",
                            archive_id=suffix, source="https://archive.org/details/" + suffix)
                       for suffix, title in (("chosen", "Chosen series"), ("other", "Other series"))]
        self.ingest(descriptors, verified=False)
        children = [dict(video("chosen-episode-" + str(number), "Chosen S01E" + str(number)),
                         content_type="episode", series_title="Chosen series", season=1, episode=number,
                         archive_id="chosen", archive_file="ep" + str(number) + ".mp4",
                         source="https://archive.org/download/chosen/ep" + str(number) + ".mp4")
                    for number in (2, 1)]
        with patch.object(media_library, "expand_item", return_value=children) as expansion:
            self.browse("series")
            self.assertEqual(set(self.identifiers()), {row["id"] for row in descriptors})
            self.assertTrue(all(row["availability"] == "unknown" for row in media_host._catalog_rows("TV")))
            expansion.assert_not_called()
            self.bridge.mediaOpenCollection("lazy-series-chosen")
            self.settled()
            self.assertEqual(self.identifiers(), ["chosen-episode-1", "chosen-episode-2"])
            self.assertTrue(all(not row["availability_decoded"] for row in media_host._catalog_rows("TV")))
            self.assertIsNotNone(self.db_work(lambda: self.service.index.get("chosen-episode-1")))
            self.assertIsNotNone(self.db_work(lambda: self.service.index.get("chosen-episode-2")))
            self.assertEqual([call.args[0]["archive_id"] for call in expansion.call_args_list], ["chosen"])
            self.verifier.assert_not_called()
            self.bridge.mediaPlay("chosen-episode-2")
            self.settled()
            self.assertEqual([call.args[0]["id"] for call in self.verifier.call_args_list], ["chosen-episode-2"])
            self.assertEqual(media_host._item["id"], "chosen-episode-2")
            self.assertEqual(self.identifiers(), ["chosen-episode-1", "chosen-episode-2"])

    def test_selected_series_preserves_identity_when_metadata_adds_language_and_new_title(self):
        descriptor = dict(video("lazy-unnamed", "Saved series title"), content_type="series",
                          archive_id="unknown-language", language="",
                          source="https://archive.org/details/unknown-language")
        self.ingest([descriptor], verified=False)
        child = dict(video("enriched-child", "New provider name S01E01"),
                     content_type="episode", series_title="New provider name", language="en",
                     archive_id="unknown-language", season=1, episode=1)
        self.browse("series")
        self.assertEqual(self.identifiers(), [descriptor["id"]])
        original_key = self.db_work(lambda: self.service.index.get(descriptor["id"]))["collection_key"]
        with patch.object(media_library, "expand_item", return_value=[child]):
            self.bridge.mediaOpenCollection(descriptor["id"])
            self.settled()
        self.assertEqual(self.identifiers(), [child["id"]])
        self.assertEqual(media_host.library_state()["library_collection"], descriptor["title"])
        saved = self.db_work(lambda: self.service.index.get(child["id"]))
        self.assertEqual(saved["collection_key"], original_key)
        self.assertEqual(saved["series_title"], descriptor["title"])
        self.assertEqual(saved["language"], "en")
        self.verifier.assert_not_called()
        self.mark_ready(child["id"])
        self.browse("series")
        self.assertEqual(self.identifiers(), [child["id"]])

    def test_cached_series_reopen_does_not_fetch_metadata_again(self):
        descriptor = dict(video("cached-series", "Cached series"), content_type="series",
                          archive_id="cached-series", source="https://archive.org/details/cached-series")
        child = dict(video("cached-child", "Cached S01E01"), content_type="episode",
                     series_title="Cached series", archive_id="cached-series", season=1, episode=1,
                     _encoding_groups_version=media_library.ENCODING_GROUPS_VERSION)
        self.ingest([descriptor], verified=False)
        self.ingest([child])
        self.browse("series")
        with patch.object(media_library, "expand_item", side_effect=AssertionError("cached metadata refetched")) as expansion:
            for _ in range(2):
                self.bridge.mediaOpenCollection(descriptor["id"])
                self.settled()
                self.assertEqual(self.identifiers(), [child["id"]])
                self.bridge.mediaLibraryBack()
                self.settled()
            expansion.assert_not_called()
        self.verifier.assert_not_called()

    def test_legacy_collapsed_episode_cache_expands_metadata_without_removing_checked_episode(self):
        descriptor = dict(video("legacy-series", "Legacy series"), content_type="series", archive_id="legacy-archive",
                          source="https://archive.org/details/legacy-archive")
        first = dict(video("legacy-episode-1", "Legacy S01E01"), content_type="episode", series_title="Legacy series",
                     archive_id="legacy-archive", season=1, episode=1)
        children = [dict(first, id="legacy-episode-" + str(number),
                         title="Legacy S01E" + str(number).zfill(2), episode=number,
                         source="https://example.invalid/legacy-episode-" + str(number) + ".mp4")
                    for number in (1, 2, 3)]
        self.ingest([descriptor], verified=False)
        self.ingest([first])
        self.browse("series")
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        def expand(row):
            started.set()
            self.assertTrue(release.wait(2))
            return children
        with patch.object(media_library, "expand_item", side_effect=expand) as expansion:
            self.bridge.mediaOpenCollection(descriptor["id"])
            self.until(started.is_set)
            self.until(lambda: self.identifiers() == [first["id"]])
            release.set()
            self.settled()
            expansion.assert_called_once()
        self.assertEqual(self.identifiers(), [row["id"] for row in children])
        scope = {row["id"]: row["availability_scope"] for row in media_host._catalog_rows("TV")}
        self.assertEqual(scope[children[1]["id"]], "metadata")
        self.assertEqual(scope[children[2]["id"]], "metadata")
        self.assertTrue(self.db_work(lambda: self.service.index.is_verified(first["id"])))
        for child in children:
            saved = self.db_work(lambda child=child: self.service.index.get(child["id"]))
            self.assertEqual(saved["_encoding_groups_version"], media_library.ENCODING_GROUPS_VERSION)
        self.verifier.assert_not_called()

    def parent_snapshot_fixture(self):
        episodes = [dict(video("parent-episode-" + str(number), "Parent " + str(number).zfill(3) + " S01E01"),
                         content_type="episode", series_title="Parent " + str(number).zfill(3), season=1, episode=1)
                    for number in range(321)]
        self.ingest(episodes)
        self.browse("series", query="Parent")
        parent = self.service._accepted_snapshot
        selected = self.identifiers()[0]
        received = []
        self.bridge.mediaLibraryChunkReady.connect(lambda ticket, raw: received.append(json.loads(raw)))
        for offset in (80, 160):
            self.bridge.mediaLibraryChunk("series", "all", "all", "all", "all", "Parent", offset, offset)
            self.settled()
        self.assertTrue(all(row["library_catalog_revision"] == parent.revision for row in received))
        return parent, selected, received

    def test_back_reuses_parent_snapshot_and_continues_after_visited_prefix_with_restored_filters(self):
        parent, selected, received = self.parent_snapshot_fixture()
        origin = parent.origin_revision
        self.bridge.mediaOpenCollection(selected)
        self.settled()
        added = dict(video("parent-new-episode", "Parent 000 extra S01E01"), content_type="episode",
                     series_title="Parent 000 extra", season=1, episode=1)
        self.ingest([added])
        self.bridge.mediaLibraryBack()
        self.settled()
        # Back first publishes its default filters; QML then restores these.
        self.browse("series", query="Parent")
        self.assertIs(self.service._accepted_snapshot, parent)
        self.assertEqual(media_host.library_state()["library_catalog_revision"], parent.revision)
        self.assertEqual(media_host.library_state()["library_total"], 321)
        self.assertEqual(self.service._inventory_structure_revision, origin)
        self.bridge.mediaLibraryChunk("series", "all", "all", "all", "all", "Parent", 240, 900)
        self.settled()
        self.assertEqual(received[-1]["library_catalog_revision"], parent.revision)
        self.assertEqual(len(received[-1]["items"]), 80)
        self.assertFalse(received[-1].get("library_snapshot_invalid"))
        self.assertTrue(received[-1]["items"][0]["title"].startswith("Parent 240"))
        self.service._poll_audit()
        self.settled()
        self.assertTrue(media_host.library_state()["library_background_refresh"])
        self.assertNotEqual(media_host.library_state()["library_catalog_revision"], parent.revision)
        self.assertIs(self.service._accepted_snapshot, parent, "An unacknowledged proposal replaced the restored cursor")

    def test_back_builds_fresh_snapshot_when_parent_source_is_withdrawn(self):
        parent, selected, received = self.parent_snapshot_fixture()
        self.bridge.mediaOpenCollection(selected)
        self.settled()
        self.db_work(lambda: self.service.index.record("parent-episode-120", dict(status="failed", checked_at=time.time())))
        self.bridge.mediaLibraryBack()
        self.settled()
        self.browse("series", query="Parent")
        fresh = self.service._accepted_snapshot
        self.assertIsNot(fresh, parent)
        self.assertNotEqual(fresh.revision, parent.revision)
        self.assertEqual(media_host.library_state()["library_total"], 320)
        self.assertTrue(media_host.library_state()["library_requires_reset"])
        self.browse("series", query="Parent")
        self.assertEqual(self.service._accepted_snapshot.revision, fresh.revision)

    def test_actual_qml_back_keeps_parent_session_anchor_and_next_chunk_without_manual_refresh(self):
        sys.path.insert(0, str(PROJECT / "tests"))
        from test_media_library_ui import MediaScene
        episodes = [dict(video("back-qt-episode-" + str(number), "Back Qt " + str(number).zfill(3) + " S01E01"),
                         content_type="episode", series_title="Back Qt " + str(number).zfill(3), season=1, episode=1)
                    for number in range(321)]
        self.ingest(episodes)
        scene = MediaScene(PROJECT / "qml/components")
        scene.root.setProperty("surfaceHost", self.bridge)
        scene.root.applyStatus(self.bridge.mediaStatus())
        scene.root.selectPage("series")
        scene.root.setProperty("localQuery", "Back Qt")
        try:
            listing = scene.find("workspaceMediaCatalog")
            self.until(lambda: scene.root.property("pageTotal") == 321 and listing.property("count") >= 160
                       and not scene.root.property("libraryBusy") and not scene.root.property("chunkBusy"))
            scene.root.loadMore(False)
            self.until(lambda: listing.property("count") >= 240 and not scene.root.property("chunkBusy"))
            listing.setProperty("currentIndex", 90)
            scene.evaluate("positionViewAtIndex(90, ListView.Center)", listing)
            self.app.processEvents()
            before_y = listing.property("contentY") - listing.property("originY")
            token = scene.root.property("catalogStructureRevision")
            selected = scene.evaluate("catalogModel.get(90).entry.id")
            scene.root.activateItem(scene.evaluate("catalogModel.get(90).entry"))
            self.until(lambda: bool(scene.root.property("collectionTitle")) and listing.property("count") == 1
                       and not scene.root.property("libraryBusy"))
            scene.root.goBack()
            self.until(lambda: not scene.root.property("collectionTitle") and listing.property("count") >= 240
                       and not scene.root.property("libraryBusy") and not scene.root.property("catalogSyncing"))
            self.assertEqual(scene.root.property("catalogStructureRevision"), token)
            self.assertEqual(scene.evaluate("catalogModel.get(90).entry.id"), selected)
            self.assertEqual(listing.property("currentIndex"), 90)
            self.assertAlmostEqual(listing.property("contentY") - listing.property("originY"), before_y, delta=1)
            scene.root.loadMore(False)
            self.until(lambda: listing.property("count") >= 320 and not scene.root.property("chunkBusy"))
            self.assertFalse(scene.root.property("chunkError"))
            self.assertEqual(scene.root.property("catalogStructureRevision"), token)
            self.assertTrue(scene.evaluate("catalogModel.get(240).entry.title").startswith("Back Qt 240"))
            self.assertFalse(scene.warnings, scene.warnings)
        finally:
            scene.close()

    def test_background_unrelated_admission_keeps_existing_view_snapshot_token(self):
        self.browse("movies", query="Alpha")
        snapshot = self.service._accepted_snapshot
        self.ingest([video("unrelated-ready", "Unrelated film")])
        self.service._poll_audit()
        self.settled()
        self.assertEqual(self.service._accepted_snapshot.revision, snapshot.revision)
        self.assertEqual(media_host.library_state()["library_catalog_revision"], snapshot.revision)
        self.assertEqual(self.identifiers(), ["film-alpha"])
        self.assertEqual(self.service._inventory_structure_revision,
                         self.db_work(lambda: self.service.index.meta("inventory_structure_revision")))

    def test_selected_series_loads_missing_season_without_refetching_cached_archive(self):
        descriptors = [dict(video("season-" + str(number), "Seasoned series"), content_type="series",
                            archive_id="season-" + str(number), source="https://archive.org/details/season-" + str(number))
                       for number in (1, 2)]
        cached = dict(video("season-1-episode", "Seasoned S01E01"), content_type="episode",
                      series_title="Seasoned series", archive_id="season-1", season=1, episode=1,
                      _encoding_groups_version=media_library.ENCODING_GROUPS_VERSION)
        missing = dict(video("season-2-episode", "Seasoned S02E01"), content_type="episode",
                       series_title="Seasoned series", archive_id="season-2", season=2, episode=1)
        self.ingest(descriptors, verified=False)
        self.ingest([cached])
        self.browse("series")
        with patch.object(media_library, "expand_item", return_value=[missing]) as expansion:
            self.bridge.mediaOpenCollection(media_host._catalog_rows("TV")[0]["id"])
            self.settled()
        self.assertEqual(self.identifiers(), [cached["id"], missing["id"]])
        self.assertIsNotNone(self.db_work(lambda: self.service.index.get(missing["id"])))
        self.assertEqual([call.args[0]["archive_id"] for call in expansion.call_args_list], ["season-2"])
        self.verifier.assert_not_called()
        self.mark_ready(missing["id"])
        self.browse("series")
        self.assertEqual(self.identifiers(), [cached["id"], missing["id"]])

    def test_back_cancels_selected_series_metadata_without_replacing_parent_list(self):
        descriptor = dict(video("cancelled-series", "Cancelled series"), content_type="series",
                          archive_id="cancelled-series", source="https://archive.org/details/cancelled-series")
        child = dict(video("cancelled-child", "Cancelled S01E01"), content_type="episode",
                     series_title="Cancelled series", season=1, episode=1)
        self.ingest([descriptor], verified=False)
        self.ingest([dict(video("ready-other-episode", "Ready other S01E01"), content_type="episode",
                          series_title="Ready other", season=1, episode=1)])
        self.browse("series")
        previous_parent_list = self.identifiers()
        started, release = threading.Event(), threading.Event()
        self.gates.append(release)
        def expand(row):
            started.set()
            self.assertTrue(release.wait(2))
            return [child]
        with patch.object(media_library, "expand_item", side_effect=expand):
            self.bridge.mediaOpenCollection(descriptor["id"])
            self.until(started.is_set)
            future = self.service._futures["collection"]
            self.bridge.mediaLibraryBack()
            release.set()
            self.until(future.done)
            self.settled()
        self.assertEqual(media_host.library_state()["library_collection"], "")
        self.assertEqual(self.identifiers(), previous_parent_list)
        self.assertIn(descriptor["id"], self.identifiers(), "Back lost a known series descriptor")
        self.assertIsNotNone(self.db_work(lambda: self.service.index.get(descriptor["id"])))
        self.assertIsNone(self.db_work(lambda: self.service.index.get(child["id"])))
        self.assertEqual(media_host.library_state()["library_loading_id"], "")

    def test_off_page_saved_series_selection_still_loads_its_episodes_lazily(self):
        descriptor = dict(video("offpage-series", "Offpage series"), content_type="series",
                          archive_id="offpage-series", source="https://archive.org/details/offpage-series")
        child = dict(video("offpage-child", "Offpage S01E01"), content_type="episode",
                     series_title="Offpage series", season=1, episode=1)
        self.ingest([descriptor], verified=False)
        self.browse("movies")
        self.assertIsNone(media_host.item_by_id(descriptor["id"]))
        with patch.object(media_library, "expand_item", return_value=[child]) as expansion:
            self.bridge.mediaPlay(descriptor["id"])
            self.settled()
        expansion.assert_called_once()
        self.assertEqual(self.identifiers(), [child["id"]])
        self.assertIsNotNone(self.db_work(lambda: self.service.index.get(child["id"])))
        self.verifier.assert_not_called()
        self.mark_ready(child["id"])
        self.browse("movies")
        self.assertEqual(self.identifiers(), [child["id"]])

    def test_archive_with_multiple_episodes_opens_a_list_instead_of_guessing_playback(self):
        descriptor = dict(video("multi-archive", "Multi episode archive"), archive_id="multi-archive",
                          source="https://archive.org/details/multi-archive")
        children = [dict(video("multi-episode-" + str(number), "Multi S01E0" + str(number)),
                         content_type="episode", series_title="Multi series", season=1, episode=number)
                    for number in (1, 2)]
        self.ingest([descriptor], verified=False)
        self.browse("movies")
        with patch.object(media_library, "resolve_item", side_effect=RuntimeError("MEDIA_ARCHIVE_CHOOSE_EPISODE")), \
             patch.object(media_library, "expand_item", return_value=children):
            self.bridge.mediaPlay(descriptor["id"])
            self.settled()
        self.assertEqual(self.identifiers(), [row["id"] for row in children])
        for row in children:
            self.assertIsNotNone(self.db_work(lambda row=row: self.service.index.get(row["id"])))
        self.assertEqual(media_host.library_state()["library_collection"], "Multi series")
        self.verifier.assert_not_called()
        self.mark_ready(*(row["id"] for row in children))
        self.browse("movies")
        self.assertEqual(self.identifiers(), [row["id"] for row in children])

    def test_invalid_radio_json_preserves_last_successful_cache(self):
        good = b'[{"name":"Sample radio","url":"https://example.invalid/radio.mp3"}]'
        path = media_contract.ensure_state_dir() / "radio-test.json"
        for invalid in (b"<!doctype html><title>Service unavailable</title>", b"\xff\xfe broken UTF-8", b'"unexpected scalar"'):
            with self.subTest(response=invalid):
                path.write_bytes(good)
                os.utime(path, (0, 0))
                with patch.object(media_contract, "_http_get", return_value=invalid):
                    result = media_contract._cached_bytes("radio-test.json", "https://example.invalid/stations.json")
                self.assertEqual(result, good)
                self.assertEqual(path.read_bytes(), good)

    def test_invalid_archive_payload_preserves_last_successful_metadata_cache(self):
        url = "https://archive.org/metadata/test-series"
        good = {"metadata": {"identifier": "test-series", "title": "Example"}, "files": []}
        path = media_library._cache_dir() / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")
        saved = json.dumps({"schema": "gg.media.archive-cache.v1", "payload": good}).encode()
        path.write_bytes(saved)
        os.utime(path, (0, 0))
        with patch.object(media_library, "_download_json", return_value={"html": "upstream error"}):
            result = media_library._cached_json(url, media_library._valid_metadata)
        self.assertEqual(result, good)
        self.assertEqual(path.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
