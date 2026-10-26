"""Published playback hints reach manifests, keys, media and the real Qt player."""
from pathlib import Path
import http.server
import os
import sys
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import test_media_availability as fixtures
from backend.media_request import public_headers
from backend.media_contract import parse_m3u_text
from backend.media_stream_proxy import MediaStreamProxy
from backend.media_stream_proxy import _Redirects
from backend.media_hls import HlsVariantResolver
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink


class PublicHeaderSource(fixtures.Source):
    hints = []
    trickle_started = threading.Event()

    def do_GET(self):
        type(self).hints.append((self.path, self.headers.get("User-Agent"), self.headers.get("Referer")))
        if self.headers.get("User-Agent") != "PublishedPlayer/1.0" or self.headers.get("Referer") != "https://publisher.invalid/":
            self.send_error(403)
            return
        if self.path == "/trickle.m3u8":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Content-Length", "10000")
            self.end_headers()
            type(self).trickle_started.set()
            try:
                for _ in range(10000):
                    self.wfile.write(b"#")
                    self.wfile.flush()
                    time.sleep(.01)
            except OSError:
                pass
            return
        super().do_GET()


class StreamProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.AvailabilityTests.setUpClass()
        fixtures.Source.fixtures["/qt-aes.m3u8"] = ("application/vnd.apple.mpegurl",
            b'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXT-X-KEY:METHOD=AES-128,URI="/identity.key",IV=0x00000000000000000000000000000012\n#EXTINF:6,\n/encrypted.ts\n#EXT-X-ENDLIST\n')
        fixtures.Source.fixtures["/qt-range.m3u8"] = ("application/vnd.apple.mpegurl",
            b'#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\n/range-reject.ts\n#EXT-X-ENDLIST\n')
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), PublicHeaderSource)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)
        fixtures.AvailabilityTests.tearDownClass()

    def setUp(self):
        PublicHeaderSource.hints = []
        self.proxies = []
        PublicHeaderSource.trickle_started.clear()

    def tearDown(self):
        for proxy in self.proxies:
            proxy.close()

    def row(self, path):
        return dict(source=self.base + path, user_agent="PublishedPlayer/1.0", referrer="https://publisher.invalid/")

    def proxy(self, path):
        proxy = MediaStreamProxy(self.row(path))
        self.proxies.append(proxy)
        return proxy

    def test_only_public_hints_are_accepted(self):
        self.assertEqual(set(public_headers(dict(Cookie="do-not-forward", Authorization="do-not-forward"))), {"User-Agent"})
        for row in (dict(user_agent="player\r\nCookie: bad"), dict(referrer="https://user:password@example.invalid/"),
                    dict(referrer="file:///private")):
            with self.assertRaises(ValueError):
                public_headers(row)

    def test_m3u_public_hints_remain_attached_only_to_their_channel(self):
        rows = parse_m3u_text('#EXTM3U\n#EXTINF:-1 tvg-id="Example",Example\n'
            '#EXTVLCOPT:http-user-agent=PublishedPlayer/1.0\n'
            '#EXTVLCOPT:http-referrer=https://publisher.invalid/\n'
            'https://example.invalid/live.m3u8\n#EXTINF:-1,Other\nhttps://example.invalid/other.m3u8\n', "TV")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["user_agent"], "PublishedPlayer/1.0")
        self.assertEqual(rows[0]["referrer"], "https://publisher.invalid/")
        self.assertNotIn("referrer", rows[1])
        self.assertNotIn("user_agent", rows[1])

    def test_hints_reach_nested_manifest_key_and_media_with_opaque_routes(self):
        with self.assertRaises(HTTPError) as denied:
            urlopen(self.base + "/aes-explicit.m3u8", timeout=2)
        self.assertEqual(denied.exception.code, 403)
        proxy = self.proxy("/aes-explicit.m3u8")
        with urlopen(proxy.url, timeout=3) as response:
            text = response.read().decode()
        self.assertNotIn(self.base, text)
        import re
        key = re.search(r'URI="([^"]+)"', text)[1]
        segment = next(line for line in text.splitlines() if line.startswith("http"))
        with urlopen(key, timeout=3) as response:
            self.assertEqual(response.read(), fixtures.AvailabilityTests.test_key)
        with urlopen(segment, timeout=3) as response:
            self.assertGreater(len(response.read()), 1000)
        self.assertTrue(all(ua == "PublishedPlayer/1.0" and ref == "https://publisher.invalid/"
                            for path, ua, ref in PublicHeaderSource.hints[1:]))
        before = len(PublicHeaderSource.hints)
        with self.assertRaises(HTTPError) as denied:
            urlopen(proxy.url.rsplit("/", 1)[0] + "/unknown", timeout=2)
        self.assertEqual(denied.exception.code, 404)
        self.assertEqual(len(PublicHeaderSource.hints), before)

    def test_vod_ranges_and_gzip_manifests_survive_the_proxy(self):
        proxy = self.proxy("/movie.mp4")
        with urlopen(Request(proxy.url, headers={"Range": "bytes=10-41"}), timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertTrue(response.headers["Content-Range"].startswith("bytes 10-41/"))
            self.assertEqual(response.read(), fixtures.AvailabilityTests.mp4[10:42])
        proxy = self.proxy("/gzip.m3u8")
        with urlopen(proxy.url, timeout=3) as response:
            self.assertTrue(response.read().startswith(b"#EXTM3U"))

    def test_redirect_closes_body_without_draining_it(self):
        class Body:
            closed = False
            def close(self):
                self.closed = True
            def read(self, *args):
                raise AssertionError("Redirect body must never be read")
        class Opener:
            def open(self, request, **kwargs):
                return request
        body, redirects = Body(), _Redirects()
        redirects.parent = Opener()
        request = redirects.http_error_302(Request("https://publisher.invalid/start"), body, 302, "", {"Location": "/video"})
        self.assertTrue(body.closed)
        self.assertEqual(request.full_url, "https://publisher.invalid/video")

    def test_close_interrupts_a_trickling_manifest_and_does_not_leave_upstream_running(self):
        proxy = self.proxy("/trickle.m3u8")
        finished = threading.Event()
        def client():
            try:
                with urlopen(proxy.url, timeout=3) as response:
                    response.read()
            except (OSError, ValueError):
                pass
            finally:
                finished.set()
        thread = threading.Thread(target=client, daemon=True)
        thread.start()
        self.assertTrue(PublicHeaderSource.trickle_started.wait(2))
        started = time.monotonic()
        proxy.close()
        self.assertLess(time.monotonic() - started, .4)
        self.assertTrue(finished.wait(.5))
        self.assertFalse(proxy._responses)

    def qt_frames(self, path):
        if not fixtures.AvailabilityTests.real_decoder:
            self.skipTest("FFmpeg fixture required")
        resolver = HlsVariantResolver()
        results = []
        resolver.sourceReady.connect(lambda *values: results.append(values))
        source = self.base + path
        resolver.resolve(source, 0, 17, row=self.row(path))
        end = time.monotonic() + 4
        while not results and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(results)
        self.assertEqual(results[0][:2], (17, source))
        self.assertNotEqual(results[0][2], source)
        player, sink, audio = QMediaPlayer(), QVideoSink(), QAudioOutput()
        audio.setVolume(0)
        player.setAudioOutput(audio)
        player.setVideoSink(sink)
        frames = []
        sink.videoFrameChanged.connect(lambda frame: frames.append(time.monotonic()) if frame.isValid() else None)
        player.setSource(QUrl(results[0][2]))
        player.play()
        end = time.monotonic() + 6
        while len(frames) < 5 and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.005)
        error = player.error().name
        status = player.mediaStatus().name
        player.stop()
        player.setSource(QUrl())
        resolver.cancel()
        self.assertGreaterEqual(len(frames), 5, (error, status, [path for path, _, _ in PublicHeaderSource.hints]))

    def test_actual_qt_player_decodes_public_encrypted_hls_with_required_headers(self):
        self.qt_frames("/qt-aes.m3u8")
        self.assertTrue(any(path == "/identity.key" for path, _, _ in PublicHeaderSource.hints))

    def test_actual_qt_player_decodes_range_rejecting_hls_and_progressive_200(self):
        self.qt_frames("/qt-range.m3u8")
        self.qt_frames("/range-segment.m3u8")  # Derives the omitted target duration.
        self.qt_frames("/no-range-fast.mp4")


if __name__ == "__main__":
    unittest.main()
