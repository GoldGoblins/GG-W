"""Real video decoder -> production clock/seek bridge -> Utilities timeline."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required for the local video fixture")
class VideoUtilityIntegrationTests(unittest.TestCase):
    def test_real_video_clock_pause_drag_seek_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="gg media controls ") as temporary:
            env = os.environ.copy()
            for name in ("XDG_STATE_HOME", "GG_DESKTOP_STATE_ROOT", "GG_DESKTOP_DATA_ROOT", "GG_RUNTIME_DIR"):
                env.pop(name, None)
            env.update(GG_DATA_HOME=temporary, GG_CONTROLS_TEST_ROOT=temporary,
                       QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_QUICK_CONTROLS_STYLE="Basic", QML_DISABLE_DISK_CACHE="1", PYTHONUTF8="1")
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", __file__, "--scenario"],
                cwd=PROJECT, env=env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=25)
            self.assertEqual(result.returncode, 0, (result.stdout + "\n" + result.stderr)[-6000:])
            report = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertGreater(report["decoded_frames"], 20)
            self.assertGreater(report["handle_movement_px"], 20)
            self.assertEqual(report["seek_calls_during_drag"], 0)
            self.assertEqual(report["seek_calls_on_release"], 1)
            self.assertFalse(report["qml_warnings"])


def scenario():
    import time
    sys.path.insert(0, str(PROJECT))
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Signal, Slot, Qt
    from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem, QQuickWindow  # Register typed scene wrappers.
    from PySide6.QtTest import QTest
    from backend import media_host as host
    from backend.chat_surface_host import ChatSurfaceHost

    temporary = Path(os.environ["GG_CONTROLS_TEST_ROOT"])
    video = temporary / "Local timeline test.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "18", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(video)], check=True, timeout=8,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name == "nt":
        fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for name in ("consola.ttf", "consolab.ttf"):
            QFontDatabase.addApplicationFont(str(fonts / name))
        QFont.insertSubstitution("monospace", "Consolas")
        app.setFont(QFont("Consolas"))
    host.load_prefs = lambda: dict(mode="TV", volume=0, last_id="local-timeline")
    host._backend = "qml"
    host._kind = "video"
    host._paused = False
    host._qml_generation = 1
    host._item = dict(id="local-timeline", kind="TV", title="Local timeline video",
        source=video.as_uri(), player="qml", play="video", media="vod", is_live=False)

    class Bridge(QObject):
        mediaStateChanged = Signal()
        mediaSeekChanged = Signal(float)

        def __init__(self):
            super().__init__()
            self.seeks = []

        @Slot(result=str)
        def mediaStatus(self):
            return json.dumps(host.status_payload())

        @Slot(result=str)
        def mediaLiveStatus(self):
            return host.live_status_json()

        @Slot(float, float)
        def mediaReportClock(self, position, duration):
            ChatSurfaceHost.mediaReportClock(self, position, duration)

        @Slot(bool, bool)
        def mediaReportPlayerState(self, playing, buffering):
            ChatSurfaceHost.mediaReportPlayerState(self, playing, buffering)

        @Slot(float, result=str)
        def mediaSeek(self, seconds):
            self.seeks.append(seconds)
            return ChatSurfaceHost.mediaSeek(self, seconds)

        @Slot(result=str)
        def mediaPause(self):
            payload = host.pause()
            host.publish_live(payload)
            self.mediaStateChanged.emit()
            return json.dumps(payload)

        @Slot(result=str)
        def mediaStop(self):
            payload = host.stop()
            host.publish_live(payload)
            self.mediaStateChanged.emit()
            return json.dumps(payload)

    bridge = Bridge()
    host.publish_live()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.rootContext().setContextProperty("controlsHost", bridge)
    base = (PROJECT / "qml/components").as_uri()
    engine.loadData(('import QtQuick\nimport "' + base + '"\n'
        'Window {width:1100;height:780;visible:true;'
        'MediaSurface {anchors.left:parent.left;anchors.right:parent.right;anchors.top:parent.top;'
        'anchors.bottom:utility.top;anchors.bottomMargin:10;surfaceHost:controlsHost}'
        'UtilitySurface {id:utility;anchors.left:parent.left;anchors.right:parent.right;'
        'anchors.bottom:parent.bottom;height:112;surfaceHost:controlsHost}}').encode())
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    media = window.findChild(QObject, "workspaceMediaPane")
    utility = window.findChild(QObject, "utilitySurface")
    player = media.findChild(QMediaPlayer, "mediaVideoPlayer")
    player.audioOutput().setMuted(True)
    frames = []
    player.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame.isValid()))
    handle = utility.findChild(QObject, "utilityTimelineHandle")
    timeline = utility.findChild(QObject, "utilityTimeline")
    assert handle is not None and timeline is not None
    media.refresh()

    def until(predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        raise AssertionError(dict(player=player.playbackState().name, status=player.mediaStatus().name,
            pos=player.position(), utility=utility.property("position"), warnings=warnings))

    until(lambda: utility.property("position") > .25 and utility.property("duration") > 17)
    start_x = handle.property("x")
    until(lambda: utility.property("position") > 1.3)
    movement = handle.property("x") - start_x
    assert movement > 20, movement
    # Utilities remain visible on other workspace tabs and still own transport.
    media.setProperty("visible", False)
    utility.playPause()
    until(lambda: player.playbackState() == QMediaPlayer.PausedState)
    paused = utility.property("position")
    QTest.qWait(450)
    assert abs(utility.property("position") - paused) < .25

    # Drag on the real QML MouseArea. No decoder seek until release.
    start = timeline.mapToScene(QPoint(round(timeline.width() * .25), 5)).toPoint()
    end = timeline.mapToScene(QPoint(round(timeline.width() * .65), 5)).toPoint()
    before = len(bridge.seeks)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(window, end, 30)
    QTest.qWait(40)
    during = len(bridge.seeks) - before
    assert during == 0, bridge.seeks
    assert utility.property("progress") > .6, utility.property("progress")
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
    until(lambda: player.position() > 11000 and utility.property("position") > 11)
    release = len(bridge.seeks) - before
    assert release == 1, bridge.seeks
    # Seeking while paused must stay there, even after a cached status poll.
    QTest.qWait(450)
    assert utility.property("position") > 11
    bridge.mediaSeek(0)
    until(lambda: player.position() < 200 and utility.property("position") < .2)
    utility.playPause()
    until(lambda: player.position() > 700 and utility.property("position") > .6)
    media.setProperty("visible", True)
    bridge.mediaSeek(17.4)
    until(lambda: player.mediaStatus() == QMediaPlayer.EndOfMedia)
    until(lambda: abs(utility.property("position") - utility.property("duration")) < .1
          and not utility.property("playing"))
    media.setProperty("visible", False)
    utility.stop()
    until(lambda: player.playbackState() == QMediaPlayer.StoppedState
          and not utility.property("seekable") and utility.property("position") == 0)
    assert not warnings, warnings
    window.close()
    engine.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print(json.dumps(dict(decoded_frames=sum(frames), handle_movement_px=round(movement, 2),
        seek_calls_during_drag=during, seek_calls_on_release=release, qml_warnings=warnings)))


if __name__ == "__main__":
    if "--scenario" in sys.argv:
        scenario()
    else:
        unittest.main()
