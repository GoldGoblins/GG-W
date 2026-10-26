"""Fast availability uses bounded local HTTP fixtures and never starts a decoder."""
from __future__ import annotations

from contextlib import ExitStack
import http.server
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import media_quick_availability as quick
from backend import media_availability as deep
from backend.media_health_audit import MediaHealthAudit
from backend.media_index import MediaIndex


MP4 = b"\x00\x00\x00\x18ftypisom" + b"m" * 4096
TS = (b"\x47" + b"t" * 187) * 5


class FastAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def do_GET(self):
                cls.requests.append((self.path, self.headers.get("Range"), self.headers.get("User-Agent"), self.headers.get("Referer")))
                path = self.path.split("?", 1)[0]
                code, kind, body = 200, "video/mp4", MP4
                if path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/movie.mp4")
                    self.send_header("Content-Length", "999999999")
                    self.end_headers()
                    return
                if path == "/loop":
                    self.send_response(302)
                    self.send_header("Location", "/loop")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if path in ("/master.m3u8", "/unknown-playlist"):
                    kind, body = "application/vnd.apple.mpegurl", b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=10000\n/stream.m3u8\n"
                elif path == "/stream.m3u8":
                    kind, body = "application/vnd.apple.mpegurl", b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n/segment.ts\n#EXT-X-ENDLIST\n"
                elif path == "/broken.m3u8":
                    kind, body = "application/vnd.apple.mpegurl", b"#EXTM3U\n#EXTINF:4,\n/missing\n#EXT-X-ENDLIST\n"
                elif path == "/large.m3u8":
                    kind, body = "application/vnd.apple.mpegurl", b"#EXTM3U\n" + b"#A long playlist comment\n" * 10000
                elif path == "/drm.m3u8":
                    kind, body = "application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="/key"\n#EXTINF:4,\n/segment.ts\n'
                elif path == "/aes.m3u8":
                    kind, body = "application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="/key"\n#EXTINF:4,\n/cipher.ts\n#EXT-X-ENDLIST\n'
                elif path == "/key":
                    kind, body = "application/octet-stream", b"abcdefghijklmnop"
                elif path == "/cipher.ts":
                    kind, body = "application/octet-stream", b"\x90" * 4096
                elif path == "/segment.ts":
                    kind, body = "application/octet-stream", TS
                elif path == "/radio":
                    kind, body = "audio/mpeg", b"ID3" + b"a" * 2048
                elif path == "/html":
                    kind, body = "text/html", b"<html>provider error page</html>"
                elif path == "/html-octets":
                    kind, body = "application/octet-stream", b"<!DOCTYPE html><html>provider error</html>"
                elif path == "/missing":
                    code, kind, body = 404, "text/plain", b"missing"
                elif path == "/unavailable":
                    code, kind, body = 503, "text/plain", b"temporary"
                elif path == "/throttle":
                    code, kind, body = 429, "text/plain", b"later"
                elif path == "/denied-range" and self.headers.get("Range"):
                    code, kind, body = 403, "text/plain", b"no ranges"
                elif path == "/no-range" and self.headers.get("Range"):
                    code, kind, body = 416, "text/plain", b"no ranges"
                elif path == "/public-hints" and (self.headers.get("User-Agent") != "Fixture-player/1" or self.headers.get("Referer") != "https://publisher.invalid/watch"):
                    code, kind, body = 403, "text/plain", b"missing public playback context"
                elif path == "/slow":
                    time.sleep(.8)
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(2)

    def setUp(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(deep, "_decode", side_effect=AssertionError("Quick checks must never decode")))
        self.stack.enter_context(patch.object(deep, "decoder_tools", side_effect=AssertionError("Quick checks need no decoder tool")))
        self.start_requests = len(self.requests)

    def tearDown(self):
        self.stack.close()

    def check(self, path, **row):
        return quick.quick_check(dict(source=self.base + path, title="Fixture media", kind="TV", content_type="movie", **row))

    def test_readable_local_supported_file_needs_no_decoder(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "local song.mp3"
            path.write_bytes(b"not decoded: actual readable supported local file")
            report = quick.quick_check(dict(source=str(path), kind="MUSIC"))
            self.assertEqual((report["status"], report["scope"]), ("verified", "local_file"))
            self.assertFalse(report["evidence"]["decoded"])
            self.assertTrue(report["evidence"]["readable"])
            self.assertEqual(report["requests"], 0)
            path.write_bytes(b"")
            self.assertEqual(quick.quick_check(dict(source=path.as_uri()))["error"], "empty_media")
            path.unlink()
            self.assertEqual(quick.quick_check(dict(source=str(path)))["error"], "local_not_found")

    def test_progressive_and_radio_positives_are_reachability_not_decoded_proofs(self):
        for path, kind in (("/movie.mp4", "TV"), ("/radio", "RADIO")):
            with self.subTest(path=path):
                report = quick.quick_check(dict(source=self.base + path, title="Example", kind=kind))
                self.assertTrue(quick.is_fresh_available(report))
                self.assertEqual(report["scope"], "http_media")
                self.assertIs(report["evidence"]["decoded"], False)
                self.assertLessEqual(report["downloaded_bytes"], 768)
                self.assertNotIn(self.base, json.dumps(report))

    def test_nested_hls_checks_playlist_and_media_segment_without_decoding(self):
        report = self.check("/master.m3u8")
        self.assertEqual((report["status"], report["scope"], report["requests"]), ("verified", "hls_media", 3))
        self.assertTrue(report["evidence"]["segment_available"])
        self.assertFalse(report["evidence"]["decoded"])
        self.assertLessEqual(report["downloaded_bytes"], quick.MAX_BYTES)

    def test_unknown_extension_playlist_and_aes_keys_are_bounded_and_not_reported(self):
        self.assertEqual(self.check("/unknown-playlist")["status"], "verified")
        report = self.check("/aes.m3u8")
        self.assertEqual(report["status"], "verified")
        self.assertTrue(report["evidence"]["encrypted"])
        self.assertNotIn("abcdefghijklmnop", json.dumps(report))
        self.assertNotIn("/key", json.dumps(report))
        self.assertEqual(self.check("/drm.m3u8")["status"], "unknown")

    def test_html_missing_and_missing_segment_fail_while_transients_remain_unknown(self):
        for path in ("/html", "/html-octets", "/missing", "/broken.m3u8"):
            self.assertEqual(self.check(path)["status"], "failed", path)
        for path in ("/unavailable", "/throttle"):
            self.assertEqual(self.check(path)["status"], "unknown", path)

    def test_range_rejections_use_one_plain_get_under_same_budget(self):
        for path in ("/denied-range", "/no-range"):
            report = self.check(path)
            self.assertEqual((report["status"], report["requests"]), ("verified", 2))

    def test_published_request_hints_reach_actual_request_and_header_injection_is_rejected(self):
        report = self.check("/public-hints", user_agent="Fixture-player/1", referrer="https://publisher.invalid/watch")
        self.assertEqual(report["status"], "verified")
        before = len(self.requests)
        bad = self.check("/movie.mp4", user_agent="bad\r\nAuthorization: secret")
        self.assertEqual(bad["status"], "unknown")
        self.assertEqual(len(self.requests), before)
        self.assertNotIn("secret", json.dumps(bad))

    def test_redirect_does_not_drain_unbounded_body_and_loops_are_bounded(self):
        start = time.monotonic()
        report = self.check("/redirect")
        self.assertEqual(report["status"], "verified")
        self.assertLess(time.monotonic() - start, 1)
        report = self.check("/loop")
        self.assertEqual(report["status"], "unknown")
        self.assertLessEqual(report["requests"], 6)

    def test_time_byte_and_cancellation_limits_do_not_start_decoder_or_unbounded_reads(self):
        event = threading.Event()
        event.set()
        report = quick.quick_check(dict(source=self.base + "/movie.mp4"), cancel=event)
        self.assertEqual((report["error"], report["requests"]), ("cancelled", 0))
        start = time.monotonic()
        report = quick.quick_check(dict(source=self.base + "/slow"), max_seconds=.55)
        self.assertEqual(report["status"], "unknown")
        self.assertLess(time.monotonic() - start, 1)
        report = self.check("/large.m3u8")
        self.assertEqual((report["status"], report["error"]), ("unknown", "playlist_too_large"))
        self.assertLessEqual(report["downloaded_bytes"], quick.MAX_BYTES)

    def test_quick_identity_needs_no_provider_fetch_and_rejects_mismatched_archive_files(self):
        row = dict(source="https://archive.org/download/collection-one/Season%201/episode.mp4", title="A programme",
                   archive_id="collection-one", archive_file="Season 1/episode.mp4")
        with patch.object(quick.library, "_cached_json", side_effect=AssertionError("No provider request")):
            prepared, identity = quick.prepare_quick_identity(row)
        self.assertEqual(identity["status"], "consistent")
        self.assertFalse(identity["semantic_identity_verified"])
        self.assertEqual(prepared, row)
        self.assertEqual(quick.check_quick_identity(dict(row, archive_file="other.mp4"))["status"], "failed")
        descriptor = dict(row, source="https://archive.org/details/collection-one", archive_file="", content_type="series")
        self.assertEqual(quick.check_quick_identity(descriptor)["scope"], "archive_descriptor")

    def test_default_audit_uses_quick_check_without_decoder_or_provider_metadata_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            index = MediaIndex(Path(temporary) / "library.sqlite3")
            index.initialize()
            index.ingest([dict(id="movie", kind="TV", title="Fixture film", content_type="movie",
                source=self.base + "/movie.mp4", media="vod")])
            with patch.object(quick.library, "_cached_json", side_effect=AssertionError("No provider lookup")):
                audit = MediaHealthAudit(index)
                result = audit.run(audit.start(), max_seconds=2, max_jobs=1)
            self.assertEqual(result["healthy"], 1)
            with index.connection() as db:
                report = json.loads(db.execute("SELECT report FROM media_audit_jobs").fetchone()[0])
            self.assertEqual(report["scope"], "http_media")
            self.assertIs(report["evidence"]["decoded"], False)


if __name__ == "__main__":
    unittest.main()
