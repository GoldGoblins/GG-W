"""Stable continuation under background admissions, withdrawal and cancellation."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.media_index import MediaIndex, view_request
from backend.media_browse_session import BrowseSession, SnapshotInvalid


class BrowseSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-media-browse-session-")
        self.index = MediaIndex(Path(self.temporary.name) / "index.sqlite3")
        self.index.initialize()
        self.rows = [dict(id=str(n), kind="TV", content_type="movie", title=f"Film {n:04}",
                         source=f"https://example.invalid/{n}.mp4") for n in range(260)]
        self.index.ingest(self.rows)
        now = time.time()
        with self.index.connection() as db:
            db.execute("UPDATE items SET status='verified',checked_at=?,verified_until=?", (now, now + 600))

    def tearDown(self):
        self.temporary.cleanup()

    def add_healthy(self, row):
        self.index.ingest([row])
        self.index.record(row["id"], dict(status="verified", checked_at=time.time(), expires_at=time.time() + 600))

    def test_admissions_before_cursor_never_shift_or_duplicate_an_existing_scroll(self):
        session = BrowseSession(self.index, view_request("movies"))
        first = session.page(0)
        session.warm_after(80, threading.Event())
        self.add_healthy(dict(self.rows[0], id="new", title="AAA new film", source="https://example.invalid/new.mp4"))
        second = session.page(80)
        third = session.page(160)
        self.assertEqual(first["library_catalog_revision"], second["library_catalog_revision"])
        self.assertEqual([row["id"] for row in first["items"] + second["items"] + third["items"]],
                         [str(n) for n in range(240)])
        new_session = BrowseSession(self.index, view_request("movies"))
        self.assertEqual(new_session.page(0)["items"][0]["id"], "new")

    def test_failed_source_invalidates_buffer_and_a_new_view_excludes_it(self):
        session = BrowseSession(self.index, view_request("movies"))
        session.page(0)
        session.warm_after(80, threading.Event())
        self.index.record("120", dict(status="failed", checked_at=time.time()))
        with self.assertRaises(SnapshotInvalid):
            session.page(80)
        replacement = BrowseSession(self.index, view_request("movies"))
        first = replacement.page(0)
        second = replacement.page(len(first["items"]))
        self.assertNotIn("120", [row["id"] for row in second["items"]])

    def test_legacy_proof_reset_invalidates_an_already_buffered_snapshot(self):
        session = BrowseSession(self.index, view_request("movies"))
        self.assertTrue(session.page(0)["items"])
        self.index.meta("health_policy", "legacy")
        self.index.initialize()
        self.assertEqual(self.index.browse(view_request("movies"))["items"], [])
        with self.assertRaises(SnapshotInvalid):
            session.page(0)

    def test_same_source_positive_refresh_keeps_snapshot_but_changed_headers_invalidate_it(self):
        session = BrowseSession(self.index, view_request("movies"))
        session.page(0)
        self.index.record("3", dict(status="verified", checked_at=time.time(), expires_at=time.time() + 900))
        self.assertEqual(len(session.page(80)["items"]), 80)
        self.index.ingest_discovered([dict(self.rows[3], user_agent="Published/2.0")])
        with self.assertRaises(SnapshotInvalid):
            session.page(160)

    def test_warming_is_bounded_and_last_page_has_no_phantom_continuation(self):
        session = BrowseSession(self.index, view_request("movies"))
        session.page(0)
        session.warm_after(80, threading.Event())
        self.assertEqual(set(session._pages), {0, 80, 160})
        last = session.page(240)
        self.assertEqual(len(last["items"]), 20)
        self.assertFalse(last["library_has_more"])
        self.assertEqual(last["library_total"], 260)

    def test_explicit_nonzero_page_and_cancelled_speculation_are_safe(self):
        session = BrowseSession(self.index, view_request("movies", offset=80))
        self.assertEqual(session.page(80)["items"][0]["id"], "80")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(SnapshotInvalid):
            session.page(160, cancel=cancel)
        session.warm_after(160, cancel)
        self.assertNotIn(160, session._pages)


if __name__ == "__main__":
    unittest.main()
