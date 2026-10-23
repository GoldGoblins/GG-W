"""HLS quality selection preserves audio and stays inside HTTP media URLs."""
from pathlib import Path
import http.server
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.media_hls import HlsVariantResolver, MAX_MANIFEST_BYTES, video_variant
from PySide6.QtCore import QCoreApplication, QEvent


class HlsVariantTests(unittest.TestCase):
    source = "https://example.invalid/tv/master.m3u8?session=test"
    master = '''#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=640x360,CODECS="avc1.64001e,mp4a.40.2"
low/video.m3u8?query=keep
#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080
/high/video.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000,RESOLUTION=1280x720
//cdn.example.invalid/mid.m3u8
'''

    def test_highest_quality_first_then_lower_bitrate_rungs(self):
        self.assertEqual(video_variant(self.source, self.master, 0), "https://example.invalid/high/video.m3u8")
        self.assertEqual(video_variant(self.source, self.master, 1), "https://cdn.example.invalid/mid.m3u8")
        self.assertEqual(video_variant(self.source, self.master, 2), "https://example.invalid/tv/low/video.m3u8?query=keep")
        self.assertEqual(video_variant(self.source, self.master, 99), video_variant(self.source, self.master, 2))

    def test_separate_audio_keeps_master(self):
        master = self.master + '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",URI="audio.m3u8"\n'
        self.assertEqual(video_variant(self.source, master, 2), self.source)

    def test_embedded_audio_group_does_not_prevent_selection(self):
        master = self.master + '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Swedish"\n'
        self.assertNotEqual(video_variant(self.source, master), self.source)

    def test_invalid_local_credential_and_audio_only_variants_are_ignored(self):
        master = '''#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=9000000,RESOLUTION=1920x1080
file:///private.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=8000000,RESOLUTION=1920x1080
https://user:password@example.invalid/live.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=10000000,CODECS="mp4a.40.2"
audio.m3u8
'''
        self.assertEqual(video_variant(self.source, master), self.source)

    def test_media_playlist_or_malformed_response_keeps_source(self):
        for body in ("#EXTM3U\n#EXTINF:6,\nsegment.ts\n", "<html>Unavailable</html>",
                     "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=bad\nvideo.m3u8"):
            self.assertEqual(video_variant(self.source, body), self.source)

    def test_duplicate_variants_do_not_consume_fallback_rungs(self):
        self.assertEqual(video_variant(self.source, self.master + self.master, 1),
                         "https://cdn.example.invalid/mid.m3u8")


class ManifestServer(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect.m3u8":
            self.send_response(302)
            self.send_header("Location", "/channel/master.m3u8")
            self.end_headers()
            return
        if self.path == "/slow.m3u8":
            time.sleep(.3)
        if self.path == "/huge.m3u8":
            data = b"#EXTM3U\n" + b" " * MAX_MANIFEST_BYTES
        else:
            data = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080\nhigh.m3u8\n"
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class AsyncHlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ManifestServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.resolver = HlsVariantResolver()
        self.results = []
        self.resolver.sourceReady.connect(lambda *args: self.results.append(args))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.resolver.cancel()
        self.resolver.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def pump(self, duration=.5):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)

    def test_redirect_uses_final_url_for_relative_variant(self):
        source = self.base + "/redirect.m3u8"
        self.resolver.resolve(source, 0, 1)
        self.pump()
        self.assertEqual(self.results, [(1, source, self.base + "/channel/high.m3u8")])

    def test_slow_manifest_falls_back_within_deadline(self):
        source = self.base + "/slow.m3u8"
        with patch("backend.media_hls.MANIFEST_TIMEOUT_MS", 60):
            self.resolver.resolve(source, 0, 1)
            self.pump()
        self.assertEqual(self.results, [(1, source, source)])

    def test_oversized_response_falls_back(self):
        source = self.base + "/huge.m3u8"
        self.resolver.resolve(source, 0, 1)
        self.pump()
        self.assertEqual(self.results, [(1, source, source)])

    def test_cancel_and_replacement_discard_late_results(self):
        self.resolver.resolve(self.base + "/slow.m3u8", 0, 1)
        self.resolver.cancel()
        self.resolver.resolve(self.base + "/channel/master.m3u8", 0, 2)
        self.pump()
        self.assertEqual(self.results, [(2, self.base + "/channel/master.m3u8",
                                         self.base + "/channel/high.m3u8")])

    def test_non_hls_source_does_not_need_a_manifest_fetch(self):
        source = self.base + "/video.ts"
        self.resolver.resolve(source, 0, 1)
        self.assertEqual(self.results, [(1, source, source)])


if __name__ == "__main__":
    unittest.main()
