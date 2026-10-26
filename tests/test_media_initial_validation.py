"""Fresh installations build their own finite checked catalogue offline fixtures."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import media_initial_validation as initial, media_health_audit as health
from backend import media_quick_availability as quick
from backend.media_index import MediaIndex, view_request


def row(identifier, **values):
    return dict(id=identifier, kind="TV", content_type="movie", title=identifier,
                source="https://example.invalid/" + identifier + ".mp4", media="vod", **values)


def proof(*args, **kwargs):
    now = time.time()
    return dict(schema=quick.SCHEMA, status="verified", scope="http_media", checked_at=now, expires_at=now + 600,
                evidence=dict(decoded=False, reachable=True))


class InitialValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-initial-validation-")
        self.index = MediaIndex(Path(self.temporary.name) / "index.sqlite3")
        self.index.initialize()
        self.index.ingest([row("film"), dict(row("episode"), content_type="episode", series_title="A series", season=1, episode=1)])
        self.stack = ExitStack()
        self.tools = self.stack.enter_context(patch.object(health.availability, "decoder_tools", return_value={"ffmpeg": "", "ffprobe": ""}))
        self.decode = self.stack.enter_context(patch.object(quick, "quick_check", side_effect=proof))
        self.stack.enter_context(patch.object(health.library, "_cached_json", side_effect=AssertionError("Unexpected external access")))

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def tables(self):
        with self.index.connection() as db:
            return [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'media_audit_%'")]

    def test_fresh_install_admits_checked_films_and_episodes_without_imported_proofs(self):
        self.assertFalse(self.index.is_verified("film"))
        result = initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(result["state"], "complete")
        self.assertEqual(self.decode.call_count, 2)
        self.assertEqual(len(self.index.browse(view_request("movies"))["items"]), 1)
        self.assertEqual(len(self.index.browse(view_request("series"))["items"]), 1)
        self.assertTrue(self.index.meta("starter_audit_run"))
        initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(self.decode.call_count, 2)

    def test_existing_manual_and_stopped_runs_are_untouched(self):
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start()
        for stopped in (False, True):
            if stopped:
                audit.stop(run_id)
            before = audit.status(run_id)
            result = initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)
            self.assertEqual(result["state"], "manual")
            self.assertEqual(audit.status(run_id), before)
            self.assertEqual(self.index.meta("starter_audit_run"), "")
        self.decode.assert_not_called()

    def test_missing_decoders_do_not_block_fast_file_and_http_checks(self):
        result = initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(result["state"], "complete")
        self.assertEqual(self.decode.call_count, 2)
        self.tools.assert_not_called()

    def test_established_checked_library_does_not_start_a_bulk_first_install_audit(self):
        self.index.record("film", proof())
        result = initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(result["state"], "existing")
        self.assertEqual(self.tables(), [])
        self.decode.assert_not_called()

    def test_initial_audit_cannot_adopt_a_concurrently_created_manual_run(self):
        audit = health.MediaHealthAudit(self.index)
        manual = audit.start()
        self.assertIsNone(audit.start(initial=True))
        self.assertEqual(audit.status()["status"], "ready")
        self.assertEqual(self.index.meta("starter_audit_run"), "")
        with self.index.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM media_audit_runs").fetchone()[0], 1)

    def test_another_process_running_the_initial_audit_is_untouched(self):
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start(initial=True)
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET owner='fixture-owner',lease_until=?,status='running' WHERE id=?", (time.time() + 60, run_id))
        before = audit.status(run_id)
        self.assertEqual(initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)["state"], "external")
        self.assertEqual(audit.status(run_id), before)
        self.decode.assert_not_called()

    def test_explicit_refresh_adds_new_candidates_after_initial_completion(self):
        initial.validate_initial(self.index, cancel=threading.Event())
        self.index.ingest_discovered([row("new-film")])
        initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(self.decode.call_count, 2)
        self.assertFalse(self.index.is_verified("new-film"))
        initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)
        self.assertTrue(self.index.is_verified("new-film"))
        self.assertEqual(self.decode.call_count, 3)

    def test_explicit_refresh_recovers_an_exhausted_initial_network_outage(self):
        self.decode.side_effect = lambda *args, **kwargs: dict(status="unknown", checked_at=time.time(),
            error="network_error", max_bytes=health.availability.MAX_CHECK_BYTES, evidence={"decoded": False})
        self.assertEqual(initial.validate_initial(self.index, cancel=threading.Event())["state"], "complete")
        self.assertEqual(self.decode.call_count, 4)  # Two sources, two attempts each.
        films = self.index.browse(view_request("movies"))["items"]
        self.assertEqual([film["id"] for film in films], ["film"])
        self.assertEqual(films[0]["availability"], "unknown")
        self.assertEqual(films[0]["availability_scope"], "metadata")
        self.assertFalse(films[0]["availability_decoded"])
        self.assertFalse(self.index.is_verified("film"))
        self.decode.side_effect = proof
        initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(self.decode.call_count, 4, "Opening reset exhausted attempts")
        initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)
        self.assertEqual(self.decode.call_count, 6)
        self.assertTrue(self.index.is_verified("film"))
        initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)
        self.assertEqual(self.decode.call_count, 6, "Refresh rechecked healthy sources")

    def test_explicit_transient_retry_remains_finite_and_permanent_failures_stay_excluded(self):
        self.decode.side_effect = lambda *args, **kwargs: dict(status="unknown", checked_at=time.time(),
            error="network_error", max_bytes=health.availability.MAX_CHECK_BYTES, evidence={"decoded": False})
        initial.validate_initial(self.index, cancel=threading.Event())
        initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)
        self.assertEqual(self.decode.call_count, 8)
        with self.index.connection() as db:
            self.assertEqual([row[0] for row in db.execute("SELECT attempts FROM media_audit_jobs")], [2, 2])
        initial.validate_initial(self.index, cancel=threading.Event())
        self.assertEqual(self.decode.call_count, 8)
        # Permanent source rejection is outside the new explicit retry grant.
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_jobs SET state='failed',report=?", ('{"error":"http_rejected"}',))
        initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)
        self.assertEqual(self.decode.call_count, 8)

    def test_explicit_initial_retry_cannot_be_applied_to_a_manual_audit(self):
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start()
        with self.assertRaisesRegex(RuntimeError, "MEDIA_INITIAL_AUDIT_SCOPE"):
            audit.repair(run_id, initial_retry=True)
        self.decode.assert_not_called()

    def test_stopped_initial_audit_requires_explicit_refresh(self):
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start(initial=True)
        audit.stop(run_id)
        self.assertEqual(initial.validate_initial(self.index, cancel=threading.Event())["state"], "stopped")
        self.decode.assert_not_called()
        self.assertEqual(initial.validate_initial(self.index, cancel=threading.Event(), explicit=True)["state"], "complete")
        self.assertEqual(self.decode.call_count, 2)

    def test_cancellation_keeps_sources_unconfirmed_and_checkpoint_resumable(self):
        cancelled = threading.Event()
        def decode(item, **kwargs):
            cancelled.set()
            self.assertTrue(kwargs["cancel"].wait(1))
            return proof()
        self.decode.side_effect = decode
        result = initial.validate_initial(self.index, cancel=cancelled)
        self.assertEqual(result["state"], "cancelled")
        self.assertFalse(self.index.is_verified("film"))
        self.assertFalse(self.index.is_verified("episode"))
        self.assertGreater(health.MediaHealthAudit(self.index).status()["pending"], 0)


class InitialServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_visible_only_worker_is_cancelled_on_hide_and_close_and_never_blocks_gui(self):
        from backend.media_paged_service import MediaCatalogService
        with tempfile.TemporaryDirectory(prefix="gg-initial-service-") as directory:
            service = MediaCatalogService(index_path=Path(directory) / "index.sqlite3")
            service._initial_eligible = True
            service._view = view_request("movies")
            service._start_initial_validation(explicit=True)
            self.assertIsNone(service._initial_future, "Hidden component started a source check")
            service.set_active(True)
            started, finished = threading.Event(), threading.Event()
            worker_threads = []
            def work(index, *, cancel, **kwargs):
                worker_threads.append(threading.get_ident())
                started.set()
                cancel.wait(2)
                finished.set()
                return {"state": "cancelled", "notice": ""}
            try:
                with patch.object(initial, "validate_initial", side_effect=work):
                    before = time.monotonic()
                    service._start_initial_validation()
                    self.assertLess(time.monotonic() - before, .1)
                    self.assertTrue(started.wait(1))
                    self.assertNotEqual(worker_threads[0], threading.get_ident())
                    service.set_active(False)
                    self.assertTrue(finished.wait(1))
                    self.assertTrue(service._initial_cancel.is_set())
                    service._start_initial_validation(explicit=True)
                    self.assertEqual(len(worker_threads), 1)
                    service.close()
                    self.app.processEvents()
                    self.assertFalse(service._refresh_timer.isActive())
            finally:
                service.close()
                service._initial_pool.shutdown(wait=True, cancel_futures=True)
                service._pool.shutdown(wait=True, cancel_futures=True)
                service._verify_pool.shutdown(wait=True, cancel_futures=True)
                service._metadata_pool.shutdown(wait=True, cancel_futures=True)
                service._discovery_pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
