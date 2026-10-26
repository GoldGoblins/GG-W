"""Real bounded HTTP/range/HLS checks and actual decoder evidence."""
from __future__ import annotations

import functools
import gzip
import http.server
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import media_availability as availability


class Source(http.server.BaseHTTPRequestHandler):
    fixtures = {}
    transferred = 0
    range_requests = []
    requests = []
    encodings = {}
    headers_seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        type(self).requests.append((path, self.headers.get("Range")))
        if path.startswith("/headers"):
            type(self).headers_seen.append((path, self.headers.get("User-Agent"), self.headers.get("Referer")))
            if (self.headers.get("User-Agent") != "PublishedPlayer/1.0"
                    or self.headers.get("Referer") != "https://publisher.invalid/player"):
                self.send_error(403)
                return
            if path == "/headers-redirect.m3u8":
                self.send_response(302)
                self.send_header("Location", "/headers.m3u8")
                self.end_headers()
                return
        if path == "/range-reject.m3u8" and self.headers.get("Range"):
            self.send_error(416)
            return
        if path == "/range-reject.ts" and self.headers.get("Range"):
            self.send_error(416)
            return
        if path.startswith("/status/"):
            self.send_error(int(path.rsplit("/", 1)[1]), "private upstream diagnostic")
            return
        if path == "/slow":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            try:
                for byte in b"#EXTM3U\n# slow body\n" * 100:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(.02)
            except OSError:
                pass
            return
        if path not in self.fixtures:
            self.send_error(404)
            return
        content_type, payload = self.fixtures[path]
        start, end, partial = 0, len(payload) - 1, False
        value = self.headers.get("Range")
        if value and path not in ("/no-range.mp4", "/no-range-fast.mp4", "/audio-stream.wav"):
            bounds = value.removeprefix("bytes=").split("-", 1)
            start = int(bounds[0])
            end = min(int(bounds[1]) if bounds[1] else end, end)
            if start >= len(payload):
                self.send_error(416)
                return
            partial = True
            type(self).range_requests.append((path, start, end))
        body = payload[start:end + 1]
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type)
        if path in self.encodings:
            self.send_header("Content-Encoding", self.encodings[path])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(payload)}")
        self.end_headers()
        try:
            self.wfile.write(body)
            type(self).transferred += len(body)
        except OSError:
            pass


class AvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="gg-availability-tests-")
        cls.directory = Path(cls.temporary.name)
        cls.tools = availability.decoder_tools()
        cls.real_decoder = bool(cls.tools.get("ffmpeg") and cls.tools.get("ffprobe"))
        cls.mp4 = cls.ts = b""
        if cls.real_decoder:
            movie = cls.directory / "movie.mp4"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "6", "-c:v", "libx264",
                "-preset", "ultrafast", "-crf", "18", "-g", "25", "-c:a", "aac", "-pix_fmt", "yuv420p", str(movie)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            transport = cls.directory / "movie.ts"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-i", str(movie), "-c", "copy", "-f", "mpegts", str(transport)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            cls.mp4, cls.ts = movie.read_bytes(), transport.read_bytes()
            fast = cls.directory / "fast.mp4"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-i", str(movie), "-c", "copy", "-movflags", "+faststart", str(fast)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            cls.test_key = bytes(range(16))
            encrypted = cls.directory / "encrypted.bin"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-f", "data", "-i", str(transport),
                "-map", "0:0", "-c", "copy", "-f", "data", "-key", cls.test_key.hex(), "-iv", (18).to_bytes(16, "big").hex(),
                "crypto:" + str(encrypted)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            audio_lead = cls.directory / "audio-lead.mp4"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-itsoffset", "2", "-i", str(movie),
                "-i", str(movie), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-t", "6", str(audio_lead)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            audio = cls.directory / "audio.wav"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "1", str(audio)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            packed = cls.directory / "packed.aac"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-i", str(movie), "-map", "0:a:0", "-c", "copy", "-f", "adts", str(packed)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            hls = cls.directory / "fmp4.m3u8"
            subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-i", str(movie), "-c", "copy", "-hls_time", "1",
                "-hls_segment_type", "fmp4", "-hls_list_size", "0", "-hls_segment_filename", str(cls.directory / "piece%d.m4s"), str(hls)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10, cwd=str(cls.directory),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        Source.fixtures = {
            "/html": ("text/html", b"<html>Not a video, even though the server returned200.</html>"),
            "/bad.m3u8": ("application/vnd.apple.mpegurl", b"not a playlist"),
            "/master.m3u8": ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=320x180\n/nested.m3u8\n'),
            "/nested.m3u8": ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=320x180\n/media.m3u8\n'),
            "/media.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXTINF:3.0,\n/segment.ts\n#EXT-X-ENDLIST\n"),
            "/range-reject.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n#EXTINF:3.0,\n/segment.ts\n#EXT-X-ENDLIST\n"),
            "/encrypted.m3u8": ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="/must-not-fetch.key"\n#EXTINF:3,\n/segment.ts\n'),
            "/empty.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n#EXT-X-TARGETDURATION:3\n"),
            "/movie.mp4": ("video/mp4", cls.mp4),
            "/no-range.mp4": ("video/mp4", cls.mp4),
            "/segment.ts": ("video/mp2t", cls.ts),
            "/large.ts": ("video/mp2t", cls.ts * 20),
            "/large.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n#EXTINF:3.0,\n/large.ts\n#EXT-X-ENDLIST\n"),
            "/range-reject.ts": ("video/mp2t", cls.ts),
            "/range-segment.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n#EXTINF:3,\n/range-reject.ts\n#EXT-X-ENDLIST\n"),
            "/larger-valid.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n" + b"# public comment\n" * 24000 + b"#EXTINF:3,\n/segment.ts\n#EXT-X-ENDLIST\n"),
            "/too-large.m3u8": ("application/vnd.apple.mpegurl", b"#EXTM3U\n" + b"# public comment\n" * 80000),
            "/gzip.m3u8": ("application/vnd.apple.mpegurl", gzip.compress(b"#EXTM3U\n#EXTINF:3,\n/segment.ts\n#EXT-X-ENDLIST\n")),
            "/gzip-bomb.m3u8": ("application/vnd.apple.mpegurl", gzip.compress(b"#EXTM3U\n" + b" " * (availability.MAX_MANIFEST_BYTES * 8))),
        }
        Source.encodings = {"/gzip.m3u8": "gzip", "/gzip-bomb.m3u8": "gzip"}
        if cls.real_decoder:
            Source.fixtures["/no-range-fast.mp4"] = ("video/mp4", fast.read_bytes())
            Source.fixtures["/identity.key"] = ("application/octet-stream", cls.test_key)
            Source.fixtures["/encrypted.ts"] = ("video/mp2t", encrypted.read_bytes())
            Source.fixtures["/aes-sequence.m3u8"] = ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:17\n#EXT-X-KEY:METHOD=AES-128,URI="/identity.key"\n#EXTINF:3,\n/unused.ts\n#EXTINF:3,\n/encrypted.ts\n#EXTINF:3,\n/unused.ts\n')
            Source.fixtures["/aes-explicit.m3u8"] = ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="/identity.key",IV=0x12\n#EXTINF:3,\n/encrypted.ts\n#EXT-X-ENDLIST\n')
            Source.fixtures["/packed.aac"] = ("audio/aac", b"ID3\x04\0\0\0\0\0\0" + packed.read_bytes())
            Source.fixtures["/packed.m3u8"] = ("application/vnd.apple.mpegurl", b"#EXTM3U\n#EXTINF:3,\n/packed.aac\n#EXT-X-ENDLIST\n")
            Source.fixtures["/packed-master.m3u8"] = ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="/packed.m3u8",DEFAULT=YES\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=320x180,AUDIO="audio"\n/media.m3u8\n')
            Source.fixtures["/headers.m3u8"] = ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="/headers.key",IV=0x12\n#EXTINF:3,\n/headers-encrypted.ts\n#EXT-X-ENDLIST\n')
            Source.fixtures["/headers.key"] = ("application/octet-stream", cls.test_key)
            Source.fixtures["/headers-encrypted.ts"] = ("video/mp2t", encrypted.read_bytes())
            Source.fixtures["/audio-lead.mp4"] = ("video/mp4", audio_lead.read_bytes())
            Source.fixtures["/audio-stream.wav"] = ("audio/wav", audio.read_bytes())
            Source.fixtures["/fmp4.m3u8"] = ("application/vnd.apple.mpegurl", hls.read_bytes())
            for file in cls.directory.glob("*.m4s"):
                Source.fixtures["/" + file.name] = ("video/mp4", file.read_bytes())
            for file in cls.directory.glob("init*.mp4"):
                Source.fixtures["/" + file.name] = ("video/mp4", file.read_bytes())
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Source)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)
        cls.temporary.cleanup()

    def setUp(self):
        Source.range_requests = []
        Source.transferred = 0
        Source.requests = []
        Source.headers_seen = []

    def verify(self, path, **fields):
        return availability.verify({"source": self.base + path, **fields})

    def test_real_mp4_moov_at_end_decodes_through_bounded_range_bridge(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        self.assertGreater(self.mp4.find(b"moov"), 512 * 1024)
        result = self.verify("/movie.mp4", content_type="movie")
        self.assertEqual(result["status"], "verified", result)
        self.assertTrue(result["evidence"]["range_verified"])
        self.assertEqual(result["evidence"]["decoder_input"], "bounded_range_bridge")
        self.assertGreater(result["evidence"]["video_frames"], 0)
        self.assertGreater(result["evidence"]["audio_frames"], 0)
        self.assertLessEqual(result["downloaded_bytes"], availability.MAX_BYTES)
        self.assertLess(result["elapsed_seconds"], availability.MAX_SECONDS)
        self.assertTrue(any(start >= len(self.mp4) - 32 for _, start, _ in Source.range_requests))
        self.assertTrue(availability.is_fresh_verified(result))

    def test_nested_hls_fetches_actual_segment_and_decodes_video_and_audio(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        result = self.verify("/master.m3u8", content_type="live", is_live=True)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["selected_source"], self.base + "/media.m3u8")
        self.assertEqual(result["evidence"]["transport"], "hls_segment")
        self.assertGreater(result["evidence"]["video_frames"], 0)
        self.assertGreater(result["evidence"]["audio_frames"], 0)
        self.assertTrue(any(path == "/segment.ts" for path, _, _ in Source.range_requests))
        self.assertLessEqual(result["downloaded_bytes"], availability.MAX_BYTES)
        for manifest in ("/master.m3u8", "/nested.m3u8", "/media.m3u8"):
            self.assertEqual([request for request in Source.requests if request[0] == manifest], [(manifest, None)])

    def test_ranged_manifest_rejection_does_not_hide_working_hls(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        result = self.verify("/range-reject.m3u8", content_type="live", is_live=True)
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual([r for r in Source.requests if r[0] == "/range-reject.m3u8"], [("/range-reject.m3u8", None)])
        self.assertGreater(result["evidence"]["video_frames"], 0)
        self.assertGreater(result["evidence"]["audio_frames"], 0)

    def test_audio_leading_mp4_reaches_video_in_bounded_decoder_sample(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        result = self.verify("/audio-lead.mp4", content_type="movie")
        self.assertEqual(result["status"], "verified", result)
        self.assertGreater(result["evidence"]["video_frames"], 0)
        self.assertGreater(result["evidence"]["audio_frames"], 0)
        self.assertLessEqual(result["downloaded_bytes"], availability.MAX_BYTES)
        self.assertLess(result["elapsed_seconds"], availability.MAX_SECONDS)

    def test_separately_decoded_hls_audio_counts_for_the_selected_rendition(self):
        fixture = b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="/media.m3u8",DEFAULT=YES\n#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=320x180,AUDIO="audio"\n/media.m3u8\n'
        Source.fixtures["/external.m3u8"] = ("application/vnd.apple.mpegurl", fixture)
        video = {"video_frames": 3, "video_stream": True, "audio_stream": True, "audio_frames": 0}
        audio = {"video_frames": 0, "video_stream": False, "audio_stream": True, "audio_frames": 5, "audio_codec": "aac"}
        try:
            with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}), \
                 patch.object(availability, "_segment_sample", side_effect=[video, audio]):
                result = self.verify("/external.m3u8", content_type="live", is_live=True)
        finally:
            del Source.fixtures["/external.m3u8"]
        self.assertEqual(result["status"], "verified", result)
        self.assertEqual(result["evidence"]["audio_frames"], 5)
        self.assertEqual(result["evidence"]["separate_audio_frames"], 5)

    def test_manifest_success_cannot_verify_missing_segment(self):
        old = Source.fixtures["/segment.ts"]
        del Source.fixtures["/segment.ts"]
        try:
            with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
                result = self.verify("/master.m3u8", is_live=True)
        finally:
            Source.fixtures["/segment.ts"] = old
        self.assertEqual((result["status"], result["error"]), ("failed", "http_not_found"))
        self.assertFalse(result["eligible"])

    def test_fragmented_mp4_hls_uses_initialization_map_and_decoded_frames(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        result = self.verify("/fmp4.m3u8", is_live=True)
        self.assertEqual(result["status"], "verified", result)
        self.assertTrue(any("init" in path for path, _, _ in Source.range_requests))
        self.assertTrue(any("piece" in path for path, _, _ in Source.range_requests))
        self.assertGreater(result["evidence"]["video_frames"], 0)

    def test_source_bytes_cannot_exceed_configured_limit_for_large_live_media(self):
        if not self.real_decoder:
            self.skipTest("media fixture required")
        decoded = {"video_frames": 1, "audio_frames": 1, "video_stream": True, "audio_stream": True}
        with patch.object(availability, "_decode", return_value=decoded):
            result = self.verify("/large.m3u8", is_live=True)
        self.assertEqual(result["status"], "verified", result)
        self.assertLessEqual(result["downloaded_bytes"], availability.MAX_BYTES)
        self.assertLessEqual(Source.transferred, availability.MAX_BYTES)

    def test_expanded_retry_budget_is_per_call_bounded_and_still_requires_real_frames(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg required")
        report = availability.verify(dict(source=self.base + "/large.m3u8", content_type="live", is_live=True),
                                     max_seconds=999, max_bytes=999 * 1024 * 1024)
        self.assertEqual(report["status"], "verified", report)
        self.assertEqual(report["max_seconds"], 30)
        self.assertEqual(report["max_bytes"], 8 * 1024 * 1024)
        self.assertGreater(report["downloaded_bytes"], availability.MAX_BYTES)
        self.assertLessEqual(report["downloaded_bytes"], report["max_bytes"])
        self.assertGreater(report["evidence"]["video_frames"], 0)
        self.assertGreater(report["evidence"]["audio_frames"], 0)
        default = self.verify("/large.m3u8", content_type="live", is_live=True)
        self.assertEqual(default["max_seconds"], 12)
        self.assertEqual(default["max_bytes"], 4 * 1024 * 1024)
        self.assertLessEqual(default["downloaded_bytes"], default["max_bytes"])

    def test_expanded_budget_preserves_explicit_deadline_and_cancellation(self):
        cancelled = threading.Event()
        cancelled.set()
        for options, error in ((dict(cancel=cancelled), "cancelled"),
                               (dict(deadline=time.monotonic() - 1), "timeout")):
            report = availability.verify(dict(source=self.base + "/movie.mp4"),
                                         max_seconds=30, max_bytes=8 * 1024 * 1024, **options)
            self.assertEqual((report["status"], report["error"], report["requests"]), ("unknown", error, 0))

    def test_local_video_and_audio_decode_without_remote_requests(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        for file, kind in (("movie.mp4", "TV"), ("audio.wav", "MUSIC")):
            for source in (str(self.directory / file), (self.directory / file).as_uri()):
                result = availability.verify({"source": source, "kind": kind, "media": "file"})
                self.assertEqual(result["status"], "verified", result)
                self.assertEqual(result["evidence"]["transport"], "local_file")
                self.assertEqual((result["requests"], result["downloaded_bytes"]), (0, 0))

    def test_radio_stream_needs_audio_frames_without_vod_range_requirement(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg and ffprobe required")
        result = self.verify("/audio-stream.wav", kind="RADIO", content_type="music")
        self.assertEqual(result["status"], "verified", result)
        self.assertGreater(result["evidence"]["audio_frames"], 0)
        self.assertEqual(result["ttl_seconds"], availability.LIVE_TTL_SECONDS)
        self.assertEqual(result["evidence"]["transport"], "live_media_bytes")

    def test_missing_local_file_is_conclusive_and_unc_is_not_opened(self):
        result = availability.verify({"source": str(self.directory / "missing.mp4"), "media": "file"})
        self.assertEqual((result["status"], result["error"]), ("failed", "local_not_found"))
        result = availability.verify({"source": r"\\unknown-host\share\movie.mp4", "media": "file"})
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["requests"], 0)

    def test_conclusive_http_errors_and_transient_failures_are_separate(self):
        expected = {404: ("failed", "http_not_found"), 410: ("failed", "http_not_found"),
                    403: ("failed", "access_denied"), 429: ("unknown", "rate_limited"), 503: ("unknown", "provider_error")}
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
            for code, outcome in expected.items():
                result = self.verify(f"/status/{code}")
                self.assertEqual((result["status"], result["error"]), outcome)
                self.assertNotIn("private", result["error"])
                self.assertFalse(availability.is_fresh_verified(result))

    def test_http_200_html_is_failed_content_not_verified_video(self):
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
            result = self.verify("/html")
        self.assertEqual((result["status"], result["error"]), ("failed", "non_media_response"))

    def test_sample_aes_remains_unknown_and_no_drm_keys_are_fetched(self):
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
            result = self.verify("/encrypted.m3u8", is_live=True)
        self.assertEqual((result["status"], result["error"]), ("unknown", "encrypted_stream"))
        self.assertFalse(any("key" in path for path, _, _ in Source.range_requests))

    def test_public_aes128_hls_decodes_with_explicit_or_media_sequence_iv(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg required")
        for path in ("/aes-sequence.m3u8", "/aes-explicit.m3u8"):
            with self.subTest(path=path):
                result = self.verify(path, content_type="live", is_live=True)
                self.assertEqual(result["status"], "verified", result)
                self.assertTrue(result["evidence"]["public_aes128_hls"])
                self.assertGreater(result["evidence"]["video_frames"], 0)
                self.assertGreater(result["evidence"]["audio_frames"], 0)
                self.assertNotIn(self.test_key.hex(), json.dumps(result))
                self.assertLessEqual(result["downloaded_bytes"], availability.MAX_BYTES)

    def test_larger_manifest_gzip_and_range_rejecting_segment_require_real_frames(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg required")
        for path in ("/larger-valid.m3u8", "/gzip.m3u8", "/range-segment.m3u8"):
            with self.subTest(path=path):
                result = self.verify(path, content_type="live", is_live=True)
                self.assertEqual(result["status"], "verified", result)
                self.assertGreater(result["evidence"]["video_frames"], 0)
                self.assertGreater(result["evidence"]["audio_frames"], 0)
                self.assertLessEqual(result["downloaded_bytes"], availability.MAX_BYTES)

    def test_gzip_expansion_is_bounded_by_the_manifest_limit(self):
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
            result = self.verify("/gzip-bomb.m3u8", content_type="live", is_live=True)
        self.assertEqual((result["status"], result["error"]), ("unknown", "playlist_too_large"))
        self.assertLess(result["downloaded_bytes"], availability.MAX_MANIFEST_BYTES)

    def test_manifest_above_one_mebibyte_is_not_parsed_or_decoded(self):
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}), \
             patch.object(availability, "_decode", side_effect=AssertionError("oversized manifest must not decode")):
            result = self.verify("/too-large.m3u8", content_type="live", is_live=True)
        self.assertEqual((result["status"], result["error"]), ("unknown", "playlist_too_large"))
        self.assertEqual(result["downloaded_bytes"], availability.MAX_MANIFEST_BYTES)

    def test_nonidentity_aes_and_invalid_key_never_gain_a_decoded_proof(self):
        Source.fixtures["/foreign-key.m3u8"] = ("application/vnd.apple.mpegurl", b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,KEYFORMAT="com.apple.streamingkeydelivery",URI="/must-not-fetch.key"\n#EXTINF:3,\n/segment.ts\n')
        try:
            result = self.verify("/foreign-key.m3u8", content_type="live", is_live=True)
            self.assertEqual((result["status"], result["error"]), ("unknown", "encrypted_stream"))
            self.assertFalse(any(path.endswith(".key") for path, _ in Source.requests))
        finally:
            del Source.fixtures["/foreign-key.m3u8"]
        if self.real_decoder:
            original = Source.fixtures["/identity.key"]
            Source.fixtures["/identity.key"] = ("application/octet-stream", bytes(17))
            try:
                result = self.verify("/aes-explicit.m3u8", content_type="live", is_live=True)
                self.assertEqual((result["status"], result["error"]), ("unknown", "invalid_hls_key"))
                self.assertFalse(result["evidence"]["decoded"])
            finally:
                Source.fixtures["/identity.key"] = original

    def test_progressive_faststart_vod_is_playable_without_claiming_range_seek(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg required")
        result = self.verify("/no-range-fast.mp4", content_type="movie")
        self.assertEqual(result["status"], "verified", result)
        self.assertFalse(result["evidence"]["range_verified"])
        self.assertGreater(result["evidence"]["video_frames"], 0)
        self.assertGreater(result["evidence"]["audio_frames"], 0)

    def test_packed_aac_with_id3_timestamp_is_actual_aac_not_mp3(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg required")
        result = self.verify("/packed-master.m3u8", content_type="live", is_live=True)
        self.assertEqual(result["status"], "verified", result)
        self.assertGreater(result["evidence"]["separate_audio_frames"], 0)
        self.assertEqual(result["evidence"]["audio_codec"], "aac")

    def test_published_request_headers_reach_redirect_manifest_segment_and_public_key(self):
        if not self.real_decoder:
            self.skipTest("FFmpeg required")
        self.assertEqual(self.verify("/headers-redirect.m3u8", content_type="live")["status"], "failed")
        Source.headers_seen = []
        result = self.verify("/headers-redirect.m3u8", content_type="live",
                             user_agent="PublishedPlayer/1.0", referrer="https://publisher.invalid/player")
        self.assertEqual(result["status"], "verified", result)
        self.assertGreater(result["evidence"]["video_frames"], 0)
        self.assertGreater(result["evidence"]["audio_frames"], 0)
        self.assertEqual({path for path, _, _ in Source.headers_seen},
                         {"/headers-redirect.m3u8", "/headers.m3u8", "/headers.key", "/headers-encrypted.ts"})
        self.assertTrue(all(ua == "PublishedPlayer/1.0" and ref == "https://publisher.invalid/player"
                            for _, ua, ref in Source.headers_seen))

    def test_valid_empty_manifest_is_indeterminate(self):
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
            result = self.verify("/empty.m3u8", is_live=True)
        self.assertEqual((result["status"], result["error"]), ("unknown", "empty_playlist"))

    def test_decoder_missing_is_never_verified(self):
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": ""}):
            result = self.verify("/master.m3u8")
        self.assertEqual((result["status"], result["error"]), ("unknown", "decoder_missing"))
        self.assertEqual(result["requests"], 0)

    def test_range_ignoring_vod_is_not_claimed_seekable(self):
        if not self.real_decoder:
            self.skipTest("media fixture required")
        result = self.verify("/no-range.mp4")
        self.assertEqual((result["status"], result["error"]), ("unknown", "range_unsupported"))

    def test_initial_cancellation_and_expired_deadline_do_no_network(self):
        cancelled = threading.Event()
        cancelled.set()
        for kwargs, error in (({"cancel": cancelled}, "cancelled"), ({"deadline": time.monotonic() - 1}, "timeout")):
            result = availability.verify({"source": self.base + "/movie.mp4"}, **kwargs)
            self.assertEqual((result["status"], result["error"], result["requests"]), ("unknown", error, 0))

    def test_slow_trickle_response_obeys_shared_deadline(self):
        started = time.monotonic()
        with patch.object(availability, "decoder_tools", return_value={"ffprobe": "present"}):
            result = availability.verify({"source": self.base + "/slow"}, deadline=started + .25)
        self.assertEqual((result["status"], result["error"]), ("unknown", "timeout"))
        self.assertLess(time.monotonic() - started, 1.0)

    def test_only_fresh_reports_with_decoder_evidence_are_eligible(self):
        report = {"status": "verified", "checked_at": 100, "expires_at": 200, "evidence": {"decoded": True}}
        self.assertTrue(availability.is_fresh_verified(report, now=150))
        self.assertFalse(availability.is_fresh_verified(report, now=200))
        self.assertFalse(availability.is_fresh_verified(report, now=99))
        self.assertFalse(availability.is_fresh_verified({**report, "evidence": {"decoded": False}}, now=150))
        self.assertFalse(availability.is_fresh_verified({**report, "status": "unknown"}, now=150))


if __name__ == "__main__":
    unittest.main()
