"""Explicit background library work using isolated providers and SQLite state."""
from __future__ import annotations

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import media_health_audit as health, media_quick_availability as quick
from backend.media_index import MediaIndex, view_request


def movie(identifier, title=None):
    return dict(id=identifier, kind="TV", content_type="movie", title=title or identifier,
        source="https://example.invalid/" + identifier + ".mp4", media="vod")


def episode(identifier, series, number):
    return dict(movie(identifier, series + " S01E" + str(number).zfill(2)), content_type="episode",
        series_title=series, season=1, episode=number)


def proof(*args, **kwargs):
    now = time.time()
    return dict(schema=quick.SCHEMA, status="verified", checked_at=now, expires_at=now + 600,
        scope="http_media", evidence=dict(decoded=False, reachable=True, content_type="video/mp4"))


class MediaBackgroundWorkTests(unittest.TestCase):
    def setUp(self):
        from backend import media_background_work as background
        self.background = background
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-media-background-work-")
        self.index = MediaIndex(Path(self.temporary.name) / "index.sqlite3")
        self.index.initialize()
        self.stack = ExitStack()
        self.discovery = self.stack.enter_context(patch.object(background, "discover", return_value={
            "new_candidates": 0, "provider_calls": 1, "error": ""}))
        self.decode = self.stack.enter_context(patch.object(quick, "quick_check", side_effect=proof))
        self.stack.enter_context(patch.object(health.library, "_cached_json",
            side_effect=AssertionError("Unexpected external source access")))
        self.work = background.MediaBackgroundWork(self.index)

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def ready(self, rows):
        self.index.ingest(rows)
        for row in rows:
            self.index.record(row["id"], proof())

    def test_read_status_never_starts_discovery_or_source_checks(self):
        self.index.ingest([movie("candidate")])
        status = self.work.read_status()
        self.assertFalse(status["running"])
        self.assertTrue(status["paused"])
        self.discovery.assert_not_called()
        self.decode.assert_not_called()
        with self.index.connection() as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='media_audit_runs'").fetchone())

    def test_cancelled_start_has_no_provider_or_decoder_work(self):
        cancelled = threading.Event()
        cancelled.set()
        status = self.work.run(cancelled)
        self.assertFalse(status["running"])
        self.discovery.assert_not_called()
        self.decode.assert_not_called()

    def test_discoveries_are_checked_in_same_slice_and_counts_distinguish_titles_and_episodes(self):
        self.ready([movie("old-film"), episode("old-episode", "Existing series", 1)])
        discovered = {
            "movies": [movie("new-film", "One new film"), movie("new-film-alt", "One new film")],
            "series": [episode("new-episode-1", "New series", 1), episode("new-episode-2", "New series", 2),
                episode("new-episode-3", "New series", 3), episode("old-series-2", "Existing series", 2)],
        }
        def discover(index, page, **kwargs):
            self.assertIs(index, self.index)
            self.assertEqual(kwargs["max_pages"], 1)
            self.assertFalse(kwargs["cancel"].is_set())
            index.ingest_discovered(discovered[page])
            return dict(new_candidates=1 if page == "movies" else 2, provider_calls=1, error="")
        self.discovery.side_effect = discover
        status = self.work.run(threading.Event(), max_seconds=10)
        self.assertFalse(status["running"])
        self.assertEqual(self.discovery.call_count, 2)
        self.assertEqual(status["new_movies"], 1, "Alternative encodings inflated film additions")
        self.assertEqual(status["new_series"], 1, "Additional episodes inflated series additions")
        self.assertEqual(status["new_episodes"], 4)
        self.assertEqual(status["discovered_movies"], 1)
        self.assertEqual(status["discovered_series"], 2)
        self.assertTrue(self.index.is_verified("new-film"))
        self.assertTrue(self.index.is_verified("new-episode-3"))
        persisted = self.background.MediaBackgroundWork(self.index).read_status()
        for field in ("new_movies", "new_series", "new_episodes", "discovered_movies", "discovered_series"):
            self.assertEqual(persisted[field], status[field], field)

    def test_missing_decoder_does_not_block_fast_source_checks(self):
        self.index.ingest([movie("decoderless-candidate")])
        with patch.object(health.availability, "decoder_tools", side_effect=AssertionError("Decoder probe is not a source check")), \
             patch.object(health.availability, "verify", side_effect=AssertionError("Background work must not decode")):
            status = self.work.run(threading.Event())
        self.assertFalse(status["running"])
        self.assertEqual(self.discovery.call_count, 2)
        self.decode.assert_called_once()
        self.assertTrue(self.index.is_verified("decoderless-candidate"))

    def test_live_external_audit_is_visible_and_start_does_not_adopt_it(self):
        self.index.ingest([movie("candidate")])
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET status='running',owner='fixture-owner',lease_until=? WHERE id=?",
                (time.time() + 60, run_id))
        status = self.work.read_status()
        self.assertTrue(status["running"])
        self.assertTrue(status["external"])
        self.work.run(threading.Event())
        self.discovery.assert_not_called()
        self.decode.assert_not_called()
        with self.index.connection() as db:
            row = db.execute("SELECT owner,cancel_requested FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual(tuple(row), ("fixture-owner", 0))

    def test_pause_requests_checkpoint_without_taking_ownership_or_unbounded_wait(self):
        self.index.ingest([movie("candidate")])
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET status='running',owner='fixture-owner',lease_until=? WHERE id=?",
                (time.time() + 60, run_id))
        cancelled = threading.Event()
        before = time.monotonic()
        status = self.work.pause(cancelled, wait_seconds=0)
        self.assertLess(time.monotonic() - before, .5)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(status["pausing"])
        with self.index.connection() as db:
            row = db.execute("SELECT owner,cancel_requested FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual(tuple(row), ("fixture-owner", 1))
        self.discovery.assert_not_called()
        self.decode.assert_not_called()
        with self.index.connection() as db:
            db.execute("UPDATE media_audit_runs SET status='paused',owner='',lease_until=0 WHERE id=?", (run_id,))
        stopped = self.work.read_status()
        self.assertFalse(stopped["running"])
        self.assertFalse(stopped["pausing"])
        self.assertTrue(stopped["paused"])

    def test_explicit_slice_enforces_two_workers_and_five_minute_total_budget(self):
        self.index.ingest([movie("candidate")])
        calls = []
        def run(audit, run_id, **kwargs):
            calls.append(kwargs)
            self.assertEqual(self.discovery.call_count, 2, "Validation preceded bounded discovery")
            return {"status": "paused"}
        with patch.object(health.MediaHealthAudit, "run", autospec=True, side_effect=run):
            status = self.work.run(threading.Event(), max_seconds=1000000)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["workers"], 2)
        self.assertEqual(calls[0]["lanes"], ("movies", "series"))
        self.assertEqual(calls[0]["max_jobs"], 240)
        self.assertGreater(calls[0]["max_seconds"], 0)
        self.assertLessEqual(calls[0]["max_seconds"], 300)
        self.assertEqual(status["budget_seconds"], 300)
        self.assertFalse(status["running"])

    def test_discovery_uses_same_deadline_and_does_not_start_audit_after_budget(self):
        def discover(index, page, **kwargs):
            self.assertEqual(page, "movies")
            self.assertTrue(kwargs["cancel"].wait(.3))
            return {"new_candidates": 0, "error": ""}
        self.discovery.side_effect = discover
        with patch.object(self.background, "_make_audit", autospec=True) as audit:
            before = time.monotonic()
            status = self.work.run(threading.Event(), max_seconds=.1)
            self.assertLess(time.monotonic() - before, .8)
            audit.assert_not_called()
        self.assertEqual(self.discovery.call_count, 1)
        self.assertFalse(status["running"])
        self.decode.assert_not_called()

    def test_cancel_during_checks_retains_resumable_queue_without_claiming_unchecked_sources(self):
        self.index.ingest([movie("candidate-" + str(number)) for number in range(20)])
        cancelled = threading.Event()
        def decode(row, **kwargs):
            cancelled.set()
            return dict(status="unknown", checked_at=time.time(), error="cancelled", evidence={})
        self.decode.side_effect = decode
        status = self.work.run(cancelled, max_seconds=10)
        self.assertFalse(status["running"])
        self.assertGreater(self.decode.call_count, 0)
        rows = self.index.browse(view_request("movies"))["items"]
        self.assertTrue(rows, "Cancellation discarded browseable saved metadata")
        self.assertTrue(all(row["availability"] == "unknown" and row["availability_scope"] == "metadata"
                            and not row["availability_decoded"] for row in rows))
        self.assertGreater(health.MediaHealthAudit(self.index).status()["pending"], 0)

    def test_duplicate_start_during_discovery_does_not_reset_or_run_another_job(self):
        started, release = threading.Event(), threading.Event()
        def discover(index, page, **kwargs):
            if page == "movies":
                started.set()
                self.assertTrue(release.wait(2))
            return {"new_candidates": 0, "error": ""}
        self.discovery.side_effect = discover
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.work.run, threading.Event(), max_seconds=5)
            try:
                self.assertTrue(started.wait(1))
                status = self.work.run(threading.Event())
                self.assertTrue(status["running"])
                self.assertEqual(self.discovery.call_count, 1)
            finally:
                release.set()
            self.assertFalse(future.result(timeout=3)["running"])
        self.assertEqual(self.discovery.call_count, 2)

    def test_explicit_resume_uses_saved_queue_and_includes_new_discoveries(self):
        self.index.ingest([movie("saved-candidate")])
        audit = health.MediaHealthAudit(self.index)
        run_id = audit.start()
        audit.stop(run_id)
        def discover(index, page, **kwargs):
            if page == "movies":
                index.ingest_discovered([movie("new-candidate")])
            return {"new_candidates": int(page == "movies"), "error": ""}
        self.discovery.side_effect = discover
        status = self.work.run(threading.Event(), max_seconds=10)
        self.assertFalse(status["running"])
        self.assertTrue(self.index.is_verified("saved-candidate"))
        self.assertTrue(self.index.is_verified("new-candidate"))
        self.assertEqual(status["new_movies"], 2)
        with self.index.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM media_audit_runs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT cancel_requested FROM media_audit_runs WHERE id=?", (run_id,)).fetchone()[0], 0)

    def test_repeated_slice_does_not_recheck_or_recount_healthy_titles(self):
        self.index.ingest([movie("candidate")])
        first = self.work.run(threading.Event(), max_seconds=10)
        self.assertEqual(first["new_movies"], 1)
        self.assertEqual(self.decode.call_count, 1)
        second = self.work.run(threading.Event(), max_seconds=10)
        self.assertFalse(second["running"])
        self.assertEqual(second["new_movies"], 0)
        self.assertEqual(self.decode.call_count, 1)


if __name__ == "__main__":
    unittest.main()
