"""Fullscreen hover-zone, shared volume and actual-decoder transport checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtCore import QObject, QPoint, QPointF, Signal, Slot, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from test_media_library_ui import LibraryBridge, MediaScene
import test_media_library_ui as library_ui


def until(app, predicate, message, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError(message)


def point(item, fraction=.5, y=None):
    return item.mapToScene(QPointF(item.width() * fraction,
        item.height() / 2 if y is None else y)).toPoint()


def fake_scenario(mode):
    class Bridge(LibraryBridge):
        mediaSeekChanged = Signal(float)

        def __init__(self):
            super().__init__()
            self.master_available = mode == "master"
            self.master = 42
            self.polls = 0
            self.previews, self.commits, self.media_volumes, self.seeks = [], [], [], []
            self.payload.update(backend="qml", paused=True, playing=False, buffering=False,
                volume=70, duration=100, position=20,
                now=dict(id="fullscreen-local", source="file:///fixture-fullscreen.mp4", kind="TV",
                    media="vod", is_live=False, title="Fullscreen fixture"))

        @Slot(result=str)
        def appAudioStatus(self):
            self.polls += 1
            return json.dumps(dict(available=self.master_available, volume=self.master))

        @Slot(int)
        def appPreviewAudioVolume(self, value):
            self.previews.append(value)
            self.master = value

        @Slot(int, result=str)
        def appSetAudioVolume(self, value):
            self.commits.append(value)
            self.master = value
            return json.dumps(dict(available=self.master_available, volume=value))

        @Slot(int, result=str)
        def mediaSetVolume(self, value):
            self.media_volumes.append(value)
            self.payload["volume"] = value
            return self.raw()

        @Slot(float, result=str)
        def mediaSeek(self, seconds):
            self.seeks.append(seconds)
            self.payload["position"] = seconds
            self.mediaSeekChanged.emit(seconds)
            return self.raw()

    player_source = library_ui.FAKE_PLAYER.replace("property int duration: 0",
        "property int duration: 0\n                        property bool seekable: true")
    with patch.object(library_ui, "FAKE_PLAYER", player_source):
        scene = MediaScene(PROJECT / "qml/components")
    bridge = Bridge()
    scene.root.setProperty("surfaceHost", bridge)
    scene.root.applyStatus(bridge.raw())
    player = scene.find("mediaVideoPlayer")
    player.setProperty("duration", 100000)
    player.setProperty("position", 20000)
    player.setProperty("mediaStatus", QMediaPlayer.BufferedMedia.value)
    QTest.qWait(40)
    loads = player.property("sourceLoads")
    expected_loads = loads
    polls = bridge.polls
    QTest.qWait(300)
    assert bridge.polls == polls, "Normal view polled fullscreen master volume"
    scene.root.toggleFullscreen()
    fullscreen = scene.find("mediaVideoFullscreenWindow")
    controls = scene.find("mediaFullscreenControls")
    timeline = scene.find("mediaFullscreenTimeline")
    volume = scene.find("mediaFullscreenVolume")
    until(scene.app, lambda: fullscreen.isVisible() and fullscreen.width() > 300, "Fullscreen window did not open")
    assert player.property("sourceLoads") == loads, "Fullscreen reloaded the decoder source"
    QTest.mouseMove(fullscreen, QPoint(fullscreen.width() // 2, fullscreen.height() // 2))
    QTest.qWait(200)
    assert not controls.property("revealed") and controls.property("opacity") < .05
    # The whole single row is only 34px, leaving 10px on either side of its
    # 14px handles. Hovering that padding reveals both compact controls.
    border = controls.mapToScene(QPointF(controls.width() / 2, controls.height() - 3)).toPoint()
    QTest.mouseMove(fullscreen, border)
    until(scene.app, lambda: controls.property("opacity") > .95, "Padded bottom hover zone did not reveal controls")
    assert controls.height() == 34 and timeline.height() == 34 and volume.height() == 34
    for name in ("mediaFullscreenTimelineHandle", "mediaFullscreenVolumeHandle"):
        handle = scene.find(name)
        assert handle.height() == 14
        assert handle.y() == 10 and handle.parentItem().height() - handle.y() - handle.height() == 10
    if mode == "master":
        until(scene.app, lambda: controls.property("volumeValue") == 42, "Fullscreen did not read shared master volume")
        assert abs(player.property("audioOutput").property("volume") - .7) < .01
        assert controls.property("seekEnabled")
        handle = scene.find("mediaFullscreenTimelineHandle")
        before = handle.property("x")
        player.setProperty("position", 30000)
        QTest.qWait(20)
        assert handle.property("x") > before, "Fullscreen handle did not follow the decoder clock"
        start = point(timeline, .3, timeline.height() - 3)
        end = point(timeline, .7, -30)
        before_seeks = len(bridge.seeks)
        QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(fullscreen, end, 30)
        QTest.qWait(180)
        assert len(bridge.seeks) == before_seeks, "Drag preview sought the decoder repeatedly"
        assert controls.property("revealed") and controls.property("opacity") > .95, "Dragging outside hid controls"
        QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, end)
        until(scene.app, lambda: len(bridge.seeks) == before_seeks + 1, "Seek was not committed once on release")
        assert 65 < bridge.seeks[-1] < 75, bridge.seeks
        assert player.property("position") > 65000
        assert player.property("playbackState") == QMediaPlayer.PausedState.value
        assert player.property("sourceLoads") == loads, "Fullscreen seeking reloaded the source"
        # Switching programme during a held drag must not seek the new source.
        QTest.mouseMove(fullscreen, border)
        QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, .2))
        QTest.mouseMove(fullscreen, point(timeline, .8), 20)
        before_seeks = len(bridge.seeks)
        bridge.payload["playback_generation"] += 1
        bridge.payload["now"] = dict(bridge.payload["now"], id="new-fullscreen-local")
        scene.root.applyStatus(bridge.raw())
        QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, .8))
        QTest.qWait(30)
        assert len(bridge.seeks) == before_seeks, "Old drag sought a new programme"
        expected_loads = player.property("sourceLoads")
        # Master audio previews and persists through the same hooks as Utilities.
        QTest.mouseMove(fullscreen, border)
        start = point(volume, .5)
        outside = point(volume, -.2, -30)
        QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(fullscreen, outside, 20)
        QTest.qWait(180)
        assert bridge.previews and bridge.previews[-1] == 0
        assert not bridge.commits, "Master volume persisted before release"
        assert controls.property("revealed"), "Volume drag outside hid the control zone"
        QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, outside)
        until(scene.app, lambda: bridge.commits == [0], "Shared master volume zero was not committed once")
        assert not bridge.media_volumes, "Master slider also multiplied the player's internal gain"
        assert abs(player.property("audioOutput").property("volume") - .7) < .01
        # Leaving fullscreen while a volume gesture is held must save the last
        # audible preview once, then ignore the eventual release outside it.
        QTest.mouseMove(fullscreen, border)
        QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(volume, .5))
        QTest.qWait(20)
        pending_volume = bridge.previews[-1]
        before_commits = len(bridge.commits)
        before_seeks = len(bridge.seeks)
        scene.root.setProperty("videoFullscreen", False)
        QTest.mouseRelease(scene.window, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
        QTest.qWait(30)
        assert bridge.commits[before_commits:] == [pending_volume], "Fullscreen close lost or duplicated volume commit"
        assert len(bridge.seeks) == before_seeks
        assert controls.property("volumePreview") == -1
        scene.root.toggleFullscreen()
        until(scene.app, lambda: fullscreen.isVisible(), "Fullscreen did not reopen after a held gesture")
    else:
        until(scene.app, lambda: controls.property("volumeValue") == 70, "Unavailable master did not use media fallback")
        # Live broadcasts have volume, but cannot expose an invented seek range.
        player.setProperty("seekable", False)
        player.setProperty("duration", 0)
        bridge.payload["now"].update(media="stream", is_live=True,
            source="https://example.invalid/fullscreen-live.m3u8")
        scene.root.applyStatus(bridge.raw())
        assert not controls.property("seekEnabled")
        until(scene.app, lambda: scene.find("mediaFullscreenTimeLabel").property("text") == "LIVE",
            "Live stream did not display its live timeline label")
        expected_loads = player.property("sourceLoads")
        before_seeks = len(bridge.seeks)
        QTest.mouseClick(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, .5))
        QTest.qWait(30)
        assert len(bridge.seeks) == before_seeks
        QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(volume, .5))
        QTest.mouseMove(fullscreen, point(volume, -.2), 20)
        QTest.qWait(30)
        assert player.property("audioOutput").property("volume") == 0, "Fallback volume preview did not reach actual output"
        assert not bridge.media_volumes, "Fallback volume persisted repeatedly during drag"
        QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, point(volume, -.2))
        until(scene.app, lambda: bridge.media_volumes == [0], "Fallback zero was not committed once")
        assert not bridge.previews and not bridge.commits
        exit_button = scene.find("mediaFullscreenExitButton")
        QTest.mouseMove(fullscreen, point(exit_button))
        until(scene.app, lambda: exit_button.property("opacity") > .95, "Existing fullscreen exit hover stopped working")
        QTest.mouseClick(fullscreen, Qt.LeftButton, Qt.NoModifier, point(exit_button))
        until(scene.app, lambda: not scene.root.property("videoFullscreen"), "Existing exit button did not close fullscreen")
        scene.root.toggleFullscreen()
        until(scene.app, lambda: fullscreen.isVisible(), "Fullscreen did not reopen after exit-button click")
    # Losing a real Qt mouse grab must commit the last audible preview once
    # and clear both preview states, so hidden controls cannot keep polling.
    QTest.mouseMove(fullscreen, border)
    committed = bridge.commits if mode == "master" else bridge.media_volumes
    before_cancel = len(committed)
    QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(volume, .5))
    QTest.mouseMove(fullscreen, point(volume, .85), 20)
    pending = controls.property("shownVolume")
    assert scene.root.property("fullscreenVolumePreview") == pending
    volume.ungrabMouse()
    QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier,
        QPoint(fullscreen.width() // 2, fullscreen.height() // 2))
    until(scene.app, lambda: len(committed) == before_cancel + 1, "Cancelled grab did not commit volume once")
    assert committed[before_cancel:] == [pending], "Cancelled grab duplicated or lost the audible volume"
    assert scene.root.property("fullscreenVolumePreview") == -1
    assert controls.property("volumePreview") == -1
    # Moving off the whole zone hides the chrome again, with no source restart.
    QTest.mouseMove(fullscreen, QPoint(fullscreen.width() // 2, fullscreen.height() // 2))
    QTest.qWait(220)
    assert not controls.property("revealed") and controls.property("opacity") < .05
    hidden_polls = bridge.polls
    QTest.qWait(350)
    assert bridge.polls == hidden_polls, "A cancelled volume preview kept the hidden poller alive"
    polls = bridge.polls
    QTest.keyClick(fullscreen, Qt.Key_Escape)
    until(scene.app, lambda: not scene.root.property("videoFullscreen"), "Escape did not leave fullscreen")
    assert not fullscreen.isVisible()
    loads_after = player.property("sourceLoads")
    # An intentional generation change is independent of fullscreen transport;
    # entering, closing during a gesture, reopening and exiting never reload it.
    assert loads_after == expected_loads, (loads, expected_loads, loads_after)
    QTest.qWait(350)
    assert bridge.polls == polls, "Closed fullscreen kept polling audio status"
    assert not scene.warnings, scene.warnings
    scene.close()
    print(json.dumps(dict(mode=mode, padded_hover=True, one_seek_commit=True,
        shared_volume=True, no_exit_reload=True, qml_warnings=[])))


def real_scenario():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickItem, QQuickWindow  # Register wrappers.
    from backend import media_host as host
    from backend.chat_surface_host import ChatSurfaceHost

    temporary = Path(os.environ["GG_FULLSCREEN_TEST_ROOT"])
    video = temporary / "fullscreen transport.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "14", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(video)], check=True, timeout=8,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    prefs = dict(mode="TV", volume=0, last_id="fullscreen-real")
    host.load_prefs = lambda: dict(prefs)
    host._backend, host._kind, host._paused, host._qml_generation = "qml", "video", False, 1
    host._item = dict(id="fullscreen-real", kind="TV", title="Fullscreen transport",
        source=video.as_uri(), player="qml", play="video", media="vod", is_live=False)

    class Bridge(QObject):
        mediaStateChanged = Signal()
        mediaSeekChanged = Signal(float)

        def __init__(self):
            super().__init__()
            self.seeks, self.volumes = [], []

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

        @Slot(int, result=str)
        def mediaSetVolume(self, value):
            self.volumes.append(value)
            prefs["volume"] = value
            payload = host.status_payload()
            host.publish_live(payload)
            self.mediaStateChanged.emit()
            return json.dumps(payload)

    bridge = Bridge()
    host.publish_live()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    engine.rootContext().setContextProperty("fullscreenHost", bridge)
    base = (PROJECT / "qml/components").as_uri()
    engine.loadData(('import QtQuick\nimport "' + base + '"\n'
        'Window {width:1100;height:780;visible:true;'
        'MediaSurface {anchors.fill:parent;surfaceHost:fullscreenHost}}').encode())
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    media = window.findChild(QObject, "workspaceMediaPane")
    player = media.findChild(QMediaPlayer, "mediaVideoPlayer")
    player.audioOutput().setMuted(True)
    sources = []
    player.sourceChanged.connect(lambda: sources.append(str(player.source())))
    media.refresh()
    until(app, lambda: player.position() > 400 and player.duration() > 13000,
        "Real local video did not decode", timeout=7)
    bridge.mediaPause()
    until(app, lambda: player.playbackState() == QMediaPlayer.PausedState, "Could not pause real video")
    source_changes = len(sources)
    media.toggleFullscreen()
    fullscreen = media.findChild(QQuickWindow, "mediaVideoFullscreenWindow")
    controls = media.findChild(QQuickItem, "mediaFullscreenControls")
    timeline = media.findChild(QQuickItem, "mediaFullscreenTimeline")
    volume = media.findChild(QQuickItem, "mediaFullscreenVolume")
    until(app, lambda: fullscreen.isVisible() and controls.property("seekEnabled"), "Fullscreen lost seekability")
    QTest.mouseMove(fullscreen, controls.mapToScene(QPointF(controls.width() / 2, controls.height() - 3)).toPoint())
    until(app, lambda: controls.property("opacity") > .95, "Real fullscreen controls did not reveal")
    QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, .2, timeline.height() - 3))
    QTest.mouseMove(fullscreen, point(timeline, .7), 30)
    assert not bridge.seeks
    QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, .7))
    until(app, lambda: player.position() > 8500, "Fullscreen seek did not reach real decoder")
    assert len(bridge.seeks) == 1
    assert player.playbackState() == QMediaPlayer.PausedState
    # A second real drag to the left clamps to a real seek to exactly zero.
    QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, .7))
    QTest.mouseMove(fullscreen, point(timeline, -.05), 20)
    QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, point(timeline, -.05))
    until(app, lambda: player.position() < 150, "Fullscreen seek zero did not update real decoder")
    assert bridge.seeks[-1] == 0 and len(bridge.seeks) == 2
    QTest.mousePress(fullscreen, Qt.LeftButton, Qt.NoModifier, point(volume, .5))
    QTest.mouseMove(fullscreen, point(volume, -.2), 20)
    QTest.mouseRelease(fullscreen, Qt.LeftButton, Qt.NoModifier, point(volume, -.2))
    until(app, lambda: bridge.volumes == [0], "Real fullscreen volume zero not committed")
    assert player.audioOutput().volume() == 0
    QTest.keyClick(fullscreen, Qt.Key_Escape)
    until(app, lambda: not fullscreen.isVisible(), "Real fullscreen did not close")
    assert len(sources) == source_changes, "Fullscreen source was restarted during transport/exit"
    assert not warnings, warnings
    media.setProperty("statusJson", "{}")
    media.setProperty("surfaceHost", None)
    window.close()
    engine.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print(json.dumps(dict(real_decoder=True, paused_seek=True, seek_zero=True,
        shared_volume_zero=True, fullscreen_source_restarts=0, qml_warnings=[])))


class FullscreenControlsTests(unittest.TestCase):
    def run_case(self, mode):
        with tempfile.TemporaryDirectory(prefix="gg-fullscreen-controls-") as temporary:
            env = os.environ.copy()
            env.update(GG_DESKTOP_STATE_ROOT=str(Path(temporary) / "state"),
                GG_DESKTOP_DATA_ROOT=str(Path(temporary) / "data"),
                GG_FULLSCREEN_TEST_ROOT=temporary, PYTHONUTF8="1")
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--scenario", mode],
                cwd=PROJECT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, (result.stdout + "\n" + result.stderr)[-7000:])

    def test_padded_hover_zone_paused_seek_master_volume_and_escape(self):
        self.run_case("master")

    def test_live_volume_fallback_without_fictitious_seek_range(self):
        self.run_case("fallback")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for local decoder fixture")
    def test_real_local_decoder_fullscreen_paused_seek_zero_volume_and_exit(self):
        self.run_case("real")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--scenario":
        real_scenario() if sys.argv[2] == "real" else fake_scenario(sys.argv[2])
    else:
        unittest.main()
