"""Official source snapshots stay bounded, canonical and unverified."""
from __future__ import annotations

from contextlib import ExitStack
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import media_sources as sources
from backend.media_index import MediaIndex, view_request


def stream(number, **values):
    row = dict(channel="Example.tv", feed="HD", title="Example Television", quality="1080p",
               url="https://example.invalid/" + str(number) + ".m3u8", labels=[])
    row.update(values)
    return row


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gg-media-sources-")
        self.index = MediaIndex(Path(self.temporary.name) / "index.sqlite3")
        self.index.initialize()
        self.stack = ExitStack()
        self.fetch = self.stack.enter_context(patch.object(sources, "_fetch_json"))

    def tearDown(self):
        self.stack.close()
        self.temporary.cleanup()

    def test_large_snapshot_uses_200_row_batches_without_claiming_any_healthy_link(self):
        self.fetch.return_value = [stream(n) for n in range(12001)]
        batches, ingest = [], self.index.ingest_discovered
        def import_batch(rows, **kwargs):
            batches.append(len(rows))
            return ingest(rows, **kwargs)
        with patch.object(self.index, "ingest_discovered", side_effect=import_batch):
            result = sources.refresh(self.index, metadata=False)
        self.assertEqual((result["api_calls"], result["candidate_sources"], result["new_sources"],
                          result["verified_by_import"]), (1, 12001, 12001, 0))
        self.assertEqual(max(batches), 200)
        self.assertEqual(batches[-1], 1)
        self.assertEqual(self.index.browse(view_request("live", language="sv; en"))["library_total"], 0)
        with self.index.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items WHERE status='verified'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(DISTINCT group_key) FROM items").fetchone()[0], 1)

    def test_joined_metadata_matches_feed_and_public_request_options(self):
        entries = {
            "streams": [stream(1, referrer="https://broadcaster.example/watch", user_agent="Public Player/1.0")],
            "channels": [dict(id="Example.tv", name="Example", country="SE", categories=["news"])],
            "feeds": [dict(channel="Example.tv", id="HD", languages=["swe"], is_main=True),
                      dict(channel="Example.tv", id="Other", languages=["eng"])],
        }
        self.fetch.side_effect = lambda endpoint, **kwargs: entries[endpoint]
        result = sources.refresh(self.index)
        self.assertEqual(result["api_calls"], 3)
        with self.index.connection() as db:
            row = json.loads(db.execute("SELECT payload FROM items").fetchone()[0])
        self.assertEqual((row["channel_id"], row["base_channel_id"], row["feed"], row["language"], row["country"]),
                         ("Example.tv@HD", "Example.tv", "HD", "sv", "SE"))
        self.assertEqual(row["referrer"], "https://broadcaster.example/watch")
        self.assertEqual(row["user_agent"], "Public Player/1.0")

    def test_bad_or_credential_sources_and_header_injection_are_not_imported(self):
        self.fetch.return_value = [stream(1), stream(1), stream(2, url="file:///private.mp4"),
            stream(3, url="https://user:secret@example.invalid/live"), stream(4, user_agent="x\r\nCookie: value"),
            stream(5, referrer="https://a.invalid/with spaces"), stream(6, channel="bad@id"), stream(7, title="")]
        result = sources.refresh(self.index, metadata=False)
        self.assertEqual((result["candidate_sources"], result["duplicate_urls"], result["rejected_streams"]), (1, 1, 6))

    def test_optional_metadata_failure_keeps_direct_stream_title_and_missing_metadata_truthful(self):
        def fetch(endpoint, **kwargs):
            if endpoint != "streams":
                raise TimeoutError("private-provider-details")
            return [stream(1, channel=None, feed=None)]
        self.fetch.side_effect = fetch
        result = sources.refresh(self.index)
        self.assertEqual((result["api_calls"], result["candidate_sources"]), (3, 1))
        self.assertEqual(result["metadata_warnings"], ["channels_unavailable", "feeds_unavailable"])
        with self.index.connection() as db:
            row = json.loads(db.execute("SELECT payload FROM items").fetchone()[0])
        self.assertEqual((row["title"], row["country"], row["language"]), ("Example Television", "", ""))
        self.assertNotIn("private-provider", json.dumps(result))

    def test_repeat_import_preserves_existing_canonical_label_and_genuine_proof(self):
        original = sources._candidate(stream(1), {}, {}, {})
        original["title"] = "Saved canonical title"
        self.index.ingest([original])
        now = time.time()
        self.index.record(original["id"], dict(status="verified", checked_at=now, expires_at=now + 600))
        self.fetch.return_value = [stream(1)]
        result = sources.refresh(self.index, metadata=False)
        self.assertEqual((result["candidate_sources"], result["new_sources"]), (1, 0))
        self.assertEqual(self.index.get(original["id"])["title"], "Saved canonical title")
        self.assertTrue(self.index.is_verified(original["id"]))

    def test_cancel_before_fetch_and_between_batches_keeps_only_completed_block(self):
        cancelled = threading.Event()
        cancelled.set()
        self.assertTrue(sources.refresh(self.index, cancel=cancelled)["cancelled"])
        self.fetch.assert_not_called()
        cancelled.clear()
        self.fetch.return_value = [stream(n) for n in range(401)]
        ingest = self.index.ingest_discovered
        def import_block(rows, **kwargs):
            result = ingest(rows, **kwargs)
            cancelled.set()
            return result
        with patch.object(self.index, "ingest_discovered", side_effect=import_block):
            result = sources.refresh(self.index, cancel=cancelled, metadata=False)
        self.assertEqual((result["cancelled"], result["candidate_sources"]), (True, 200))
        with self.index.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items").fetchone()[0], 200)

    def test_unavailable_required_api_never_mutates_source_index(self):
        self.fetch.side_effect = ValueError("private-response-diagnostics")
        result = sources.refresh(self.index)
        self.assertEqual((result["api_calls"], result["candidate_sources"], result["error"]),
                         (1, 0, "source_api_unavailable"))
        with self.index.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)
        self.assertNotIn("private-response", json.dumps(result))

    def test_actual_reader_rejects_oversized_wrong_origin_and_nonlist_payloads(self):
        self.stack.close()
        endpoint = sources.ENDPOINTS["streams"][0]
        for raw, final, maximum in [(b"[{}]xxxxx", endpoint, 4), (b"[]", "https://evil.invalid/api/streams.json", 20),
                                     (b"{}", endpoint, 20)]:
            with self.subTest(final=final, raw=raw):
                with patch.dict(sources.ENDPOINTS, streams=(endpoint, maximum)), \
                     patch.object(sources.urllib.request, "build_opener") as build:
                    build.return_value.open.return_value = Response(raw, final)
                    with self.assertRaises(ValueError):
                        sources._fetch_json("streams", deadline=time.monotonic() + 3)

    def test_metadata_redirects_cannot_follow_another_origin_or_endpoint(self):
        endpoint = sources.ENDPOINTS["streams"][0]
        handler = sources._OfficialRedirect(endpoint)
        request = urllib.request.Request(endpoint)
        for target in ("http://127.0.0.1/private", "https://evil.invalid/api/streams.json",
                       "https://iptv-org.github.io/api/channels.json", endpoint + "?extra=value"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "Found", {}, target)
        redirected = handler.redirect_request(request, None, 302, "Found", {}, endpoint)
        self.assertEqual(redirected.full_url, endpoint)


if __name__ == "__main__":
    unittest.main()
