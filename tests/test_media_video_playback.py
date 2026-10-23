"""Real Qt video/HLS playback and recovery against a local fault-injection server."""
from __future__ import annotations

import functools
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from test_media_video import Bridge  # Also configures headless Qt before import.

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtQml import QQmlApplicationEngine
from backend.media_hls import HlsVariantResolver


class HlsBridge(Bridge):
    mediaVideoSourceReady = Signal(int, str, str)

    def __init__(self):
        super().__init__()
        self.resolver = HlsVariantResolver(self)
        self.resolver.sourceReady.connect(self.mediaVideoSourceReady.emit)

    @Slot(str, int, int)
    def mediaResolveVideoSource(self, source, attempt, ticket):
        self.resolver.resolve(source, attempt, ticket)

    @Slot()
    def mediaCancelVideoSource(self):
        self.resolver.cancel()


class VideoScene:
    def __init__(self, source, *, live=True):
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.bridge = HlsBridge()
        self.bridge.payload["now"].update(source=source, media="stream" if live else "file")
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(e.toString() for e in errors))
        self.engine.rootContext().setContextProperty("testVideoHost", self.bridge)
        base = (PROJECT / "qml/components").as_uri()
        self.engine.loadData(('import QtQuick\nimport "' + base + '"\n'
            'Window {width:800;height:600;visible:true;'
            'MediaSurface {anchors.fill:parent;surfaceHost:testVideoHost}}').encode())
        if not self.engine.rootObjects():
            raise AssertionError(self.warnings)
        self.window = self.engine.rootObjects()[0]
        self.root = self.window.findChild(QObject, "workspaceMediaPane")
        self.player = self.root.findChild(QMediaPlayer, "mediaVideoPlayer")
        self.frames = 0
        self.last_frame = 0
        self.max_frame_gap = 0
        self.sink = None
        self.player.videoOutputChanged.connect(self.bind_sink)
        self.bind_sink()
        self.player.audioOutput().setMuted(True)
        self.root.refresh()

    def bind_sink(self):
        if self.sink is not None:
            self.sink.videoFrameChanged.disconnect(self.on_frame)
        self.sink = self.player.videoSink()
        if self.sink is not None:
            self.sink.videoFrameChanged.connect(self.on_frame)

    def on_frame(self, frame):
        if not frame.isValid():
            return
        now = time.monotonic()
        if self.last_frame:
            self.max_frame_gap = max(self.max_frame_gap, now - self.last_frame)
        self.last_frame = now
        self.frames += 1

    def until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError({"frames": self.frames,
                              "retries": self.root.property("playerRetryCount"),
                              "status": self.player.mediaStatus().name,
                              "error": self.player.error().name,
                              "warnings": self.warnings})

    def sync(self, **changes):
        self.bridge.payload.update(changes)
        self.root.setProperty("statusJson", self.bridge.mediaStatus())
        self.app.processEvents()

    def close(self):
        self.sync(backend="", now={})
        self.window.close()
        self.engine.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class HlsServer(http.server.SimpleHTTPRequestHandler):
    started_at = 0
    failing = False
    failed_requests = 0
    fail_high = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        if type(self).failing or (type(self).fail_high and self.path.startswith("/high/")):
            type(self).failed_requests += 1
            self.send_error(503)
            return
        if self.path == "/master.m3u8":
            payload = (b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=6000000,RESOLUTION=1920x1080\n"
                       b"/high/live.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n"
                       b"/low/live.m3u8\n")
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.endswith("/live.m3u8"):
            # A sliding live playlist over continuous, prerecorded TS segments.
            # No EndList: EOF is an interruption, not a completed local film.
            end = min(59, 5 + int((time.monotonic() - type(self).started_at) // 2))
            start = max(0, end - 5)
            prefix = self.path.rsplit("/", 1)[0]
            payload = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
                       f"#EXT-X-MEDIA-SEQUENCE:{start}\n" + "".join(
                           f"#EXTINF:2.0,\n{prefix}/segment{seq:03d}.ts\n"
                           for seq in range(start, end + 1))).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        for prefix in ("/high/", "/low/"):
            if self.path.startswith(prefix):
                self.path = "/" + self.path[len(prefix):]
                break
        super().do_GET()


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for the video fixture")
class RealVideoPlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.temporary = tempfile.TemporaryDirectory(prefix="gg tv playback ")
        cls.directory = Path(cls.temporary.name)
        subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                        "-t", "120", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", "-g", "50", "-sc_threshold", "0",
                        "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
                        "-hls_segment_filename", str(cls.directory / "segment%03d.ts"),
                        str(cls.directory / "vod.m3u8")], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
            functools.partial(HlsServer, directory=str(cls.directory)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    def setUp(self):
        HlsServer.started_at = time.monotonic()
        HlsServer.failing = False
        HlsServer.failed_requests = 0
        HlsServer.fail_high = False
        self.scene = VideoScene(f"http://127.0.0.1:{self.server.server_port}/live.m3u8")

    def tearDown(self):
        self.scene.close()
        self.assertFalse(self.scene.warnings, self.scene.warnings)

    def test_actual_decoder_frames_fullscreen_pause_mute_and_stop(self):
        scene = self.scene
        scene.until(lambda: scene.frames >= 25 and scene.bridge.payload["playing"])
        self.assertGreater(scene.root.property("playerLastFrameAt"), 0)
        if hasattr(scene.player, "playbackOptions"):
            self.assertEqual(scene.player.playbackOptions().networkTimeout(), 15000)
        before = scene.frames
        scene.root.setProperty("videoFullscreen", True)
        scene.until(lambda: scene.frames >= before + 25)
        scene.root.setProperty("videoFullscreen", False)
        scene.sync(paused=True)
        scene.until(lambda: scene.player.playbackState() == QMediaPlayer.PausedState)
        self.assertFalse(scene.bridge.payload["playing"])
        scene.sync(volume=0, paused=False)
        scene.until(lambda: scene.bridge.payload["playing"] and scene.frames >= before + 50)
        self.assertEqual(scene.player.audioOutput().volume(), 0)
        self.assertEqual(scene.root.property("playerRetryCount"), 0)
        scene.sync(backend="", now={})
        self.assertEqual(scene.player.playbackState(), QMediaPlayer.StoppedState)

    def test_live_hls_recovers_after_server_outage(self):
        scene = self.scene
        scene.until(lambda: scene.frames >= 25)
        HlsServer.failing = True
        scene.until(lambda: HlsServer.failed_requests > 0, timeout=15)
        scene.until(lambda: scene.root.property("playerRetryCount") >= 1, timeout=40)
        HlsServer.failing = False
        before = scene.frames
        scene.until(lambda: scene.frames >= before + 50 and scene.bridge.payload["playing"], timeout=35)
        self.assertFalse(scene.root.property("playerRetryExhausted"))
        self.assertEqual(scene.root.property("playerError"), "")

    def test_master_selects_high_quality_and_falls_back_after_interruption(self):
        scene = self.scene
        source = f"http://127.0.0.1:{self.server.server_port}/master.m3u8"
        scene.sync(now={"source": source, "media": "stream"}, playback_generation=2)
        scene.until(lambda: scene.frames >= 25 and scene.player.source().path() == "/high/live.m3u8")
        self.assertEqual(scene.root.property("lastPlayUrl"), source)
        HlsServer.fail_high = True
        scene.until(lambda: HlsServer.failed_requests > 0, timeout=15)
        scene.until(lambda: scene.player.source().path() == "/low/live.m3u8", timeout=40)
        before = scene.frames
        scene.until(lambda: scene.frames >= before + 50 and scene.bridge.payload["playing"])
        self.assertFalse(scene.root.property("playerRetryExhausted"))


if __name__ == "__main__":
    unittest.main()
