"""Exercise the actual TV QML with a controllable decoder, without a network."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal, Slot, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem  # Register the QQuickItem wrapper.


class Bridge(QObject):
    mediaStateChanged = Signal()

    def __init__(self):
        super().__init__()
        self.payload = {
            "backend": "qml", "mode": "TV", "volume": 70,
            "paused": False, "playing": False, "buffering": True,
            "playback_generation": 1,
            "now": {"id": "test-tv", "source": "https://example.invalid/live.m3u8",
                    "media": "stream", "title": "Test TV"},
            "items": [],
        }
        self.reports = []

    @Slot(result=str)
    def mediaStatus(self):
        return json.dumps(self.payload)

    @Slot(result=str)
    def mediaLiveStatus(self):
        return self.mediaStatus()

    @Slot(bool, bool)
    def mediaReportPlayerState(self, playing, buffering):
        self.reports.append((playing, buffering))
        changed = (playing, buffering) != (
            self.payload["playing"], self.payload["buffering"])
        self.payload.update(playing=playing, buffering=buffering)
        if changed:
            self.mediaStateChanged.emit()

    @Slot(float, float)
    def mediaReportClock(self, position, duration):
        pass


class DelayedBridge(Bridge):
    mediaVideoSourceReady = Signal(int, str, str)

    def __init__(self):
        super().__init__()
        self.requests = []
        self.cancels = 0

    @Slot(str, int, int)
    def mediaResolveVideoSource(self, source, attempt, ticket):
        self.requests.append((source, attempt, ticket))

    @Slot()
    def mediaCancelVideoSource(self):
        self.cancels += 1


# Substitute only the decoder, retaining all production QML functions,
# signal handlers, timers, video sinks, UI and the synchronous host callback.
FAKE_PLAYER = """QtObject {
                        property int error: MediaPlayer.NoError
                        property int mediaStatus: MediaPlayer.NoMedia
                        property int playbackState: MediaPlayer.StoppedState
                        property int position: 0
                        property int duration: 0
                        property url source
                        property var videoOutput
                        property var audioOutput
                        property var playbackOptions: ({networkTimeoutMs: 0})
                        property int sourceLoads: 0
                        property int playCalls: 0
                        signal errorOccurred(int error, string errorString)
                        function stop() { playbackState = MediaPlayer.StoppedState }
                        function pause() { playbackState = MediaPlayer.PausedState }
                        function play() {
                            playCalls += 1
                            playbackState = MediaPlayer.PlayingState
                        }
                        onSourceChanged: {
                            error = MediaPlayer.NoError
                            mediaStatus = String(source) ? MediaPlayer.LoadingMedia : MediaPlayer.NoMedia
                            if (String(source)) sourceLoads += 1
                        }
"""


class VideoRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.source = (PROJECT / "qml/components/MediaSurface.qml").read_text(encoding="utf-8")
        assert cls.source.count("MediaPlayer {") == 1

    def setUp(self):
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(e.toString() for e in errors))
        self.component = QQmlComponent(self.engine)
        source = self.source.replace("MediaPlayer {", FAKE_PLAYER, 1)
        self.component.setData(source.encode(), QUrl.fromLocalFile(str(PROJECT / "qml/components/MediaSurface.qml")))
        self.assertFalse(self.component.isError(), self.component.errors())
        self.root = self.component.create()
        self.assertIsNotNone(self.root, self.component.errors())
        self.bridge = Bridge()
        self.root.setProperty("surfaceHost", self.bridge)
        self.player = self.root.findChild(QObject, "mediaVideoPlayer")
        self.retry = self.root.findChild(QObject, "mediaVideoRetryTimer")
        self.watchdog = self.root.findChild(QObject, "mediaVideoWatchdogTimer")
        self.sync()

    def tearDown(self):
        self.root.setProperty("statusJson", "{}")
        self.root.setProperty("surfaceHost", None)
        self.root.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.root = self.component = None
        self.engine.deleteLater()
        self.bridge.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(self.warnings, self.warnings)

    def sync(self, **changes):
        self.bridge.payload.update(changes)
        self.root.setProperty("statusJson", self.bridge.mediaStatus())
        self.app.processEvents()

    def loaded(self):
        self.player.setProperty("mediaStatus", QMediaPlayer.LoadedMedia.value)

    def frame(self):
        self.loaded()
        self.player.setProperty("mediaStatus", QMediaPlayer.BufferedMedia.value)
        self.root.noteVideoFrame()

    def fail(self):
        self.player.setProperty("error", QMediaPlayer.NetworkError.value)
        self.player.errorOccurred.emit(QMediaPlayer.NetworkError.value, "private decoder detail")
        self.player.setProperty("mediaStatus", QMediaPlayer.InvalidMedia.value)

    def restart(self):
        self.retry.stop()
        self.root.retryPlayer()

    def test_short_buffer_stall_does_not_restart(self):
        self.frame()
        self.player.setProperty("mediaStatus", QMediaPlayer.StalledMedia.value)
        self.root.watchPlayer()
        self.assertFalse(self.retry.property("running"))
        self.frame()
        self.assertEqual(self.root.property("playerRetryCount"), 0)
        self.assertEqual(self.player.property("sourceLoads"), 1)

    def test_refilling_buffer_with_frames_reports_playing(self):
        self.frame()
        self.player.setProperty("mediaStatus", QMediaPlayer.BufferingMedia.value)
        self.root.noteVideoFrame()
        self.root.reportPlayerState()
        self.assertEqual(self.bridge.reports[-1], (True, False))

    def test_recovered_video_cancels_pending_restart(self):
        self.fail()
        self.assertTrue(self.retry.property("running"))
        self.player.setProperty("error", QMediaPlayer.NoError.value)
        self.frame()
        self.assertFalse(self.retry.property("running"))
        self.root.retryPlayer()  # Even an already queued callback is harmless.
        self.assertEqual(self.player.property("sourceLoads"), 1)

    def test_internal_stop_does_not_schedule_another_retry(self):
        self.frame()
        self.fail()
        self.restart()
        self.assertEqual(self.player.property("sourceLoads"), 2)
        self.assertEqual(self.root.property("playerRetryCount"), 1)
        self.assertFalse(self.retry.property("running"))
        self.loaded()
        self.assertEqual(self.root.property("playerRetryCount"), 1)

    def test_permanent_failure_exhausts_budget_despite_brief_video(self):
        for attempt in range(5):
            self.fail()
            self.assertEqual(self.retry.property("interval"), min(10000, 1000 * 2 ** attempt))
            self.restart()
            self.frame()  # A few frames must not reset the attempt count.
            self.assertEqual(self.root.property("playerRetryCount"), attempt + 1)
        self.fail()
        self.assertFalse(self.retry.property("running"))
        self.assertTrue(self.root.property("playerRetryExhausted"))
        self.assertFalse(self.root.property("playerWantsPlay"))
        self.assertEqual(self.bridge.reports[-1], (False, False))
        self.sync(position=20)
        self.root.watchPlayer()
        self.assertEqual(self.player.property("sourceLoads"), 6)
        self.assertNotIn("private decoder detail", self.root.property("playerError"))

    def test_budget_resets_only_after_sustained_video(self):
        self.frame()
        self.root.setProperty("playerRetryCount", 4)
        self.root.setProperty("playerStableSince", time.time() * 1000 - 31000)
        self.root.noteVideoFrame()
        self.assertEqual(self.root.property("playerRetryCount"), 0)

    def test_frozen_zero_clock_stream_recovers(self):
        self.loaded()
        self.assertEqual(self.player.property("position"), 0)
        self.assertEqual(self.player.property("duration"), 0)
        self.root.setProperty("playerStartedAt", time.time() * 1000 - 16000)
        self.root.watchPlayer()
        self.assertTrue(self.retry.property("running"))

    def test_moving_clock_does_not_hide_frozen_video(self):
        self.frame()
        self.root.setProperty("playerLastFrameAt", time.time() * 1000 - 16000)
        self.player.setProperty("position", 60000)
        self.root.watchPlayer()
        self.assertTrue(self.retry.property("running"))

    def test_loading_gets_grace_but_cannot_hang_forever(self):
        self.root.setProperty("playerStartedAt", time.time() * 1000 - 29000)
        self.root.watchPlayer()
        self.assertFalse(self.retry.property("running"))
        self.root.setProperty("playerStartedAt", time.time() * 1000 - 31000)
        self.root.watchPlayer()
        self.assertTrue(self.retry.property("running"))

    def test_pause_cancels_retry_and_resume_can_recover(self):
        self.fail()
        self.sync(paused=True)
        self.assertFalse(self.retry.property("running"))
        self.restart()
        self.assertEqual(self.player.property("sourceLoads"), 1)
        self.sync(paused=False)
        self.root.watchPlayer()
        self.assertTrue(self.retry.property("running"))

    def test_same_channel_manual_play_resets_exhausted_decoder(self):
        self.root.setProperty("playerRetryCount", 5)
        self.fail()
        self.sync(playback_generation=2)
        self.assertFalse(self.root.property("playerRetryExhausted"))
        self.assertEqual(self.root.property("playerRetryCount"), 0)
        self.assertEqual(self.player.property("sourceLoads"), 2)
        self.sync(position=1)
        self.assertEqual(self.player.property("sourceLoads"), 2)

    def test_channel_switch_and_stop_cancel_old_retries(self):
        self.fail()
        self.sync(now={"source": "https://example.invalid/other.m3u8", "media": "stream"})
        self.assertFalse(self.retry.property("running"))
        self.assertEqual(self.root.property("playerRetryCount"), 0)
        self.fail()
        self.sync(backend="", now={})
        self.assertFalse(self.retry.property("running"))
        self.assertFalse(self.watchdog.property("running"))
        self.restart()
        self.assertEqual(str(self.player.property("source")), "PySide6.QtCore.QUrl('')")

    def test_local_video_ends_without_reconnect_or_autoplay(self):
        self.sync(now={"source": "file:///sample.mp4", "media": "file"})
        self.frame()
        self.player.setProperty("mediaStatus", QMediaPlayer.EndOfMedia.value)
        self.player.setProperty("playbackState", QMediaPlayer.StoppedState.value)
        self.sync(position=10)
        self.assertFalse(self.retry.property("running"))
        self.assertFalse(self.root.property("playerWantsPlay"))
        self.assertTrue(self.root.property("playerEnded"))

    def test_zero_volume_and_background_watchdog(self):
        self.sync(volume=0)
        self.assertEqual(self.player.property("audioOutput").property("volume"), 0)
        self.root.setProperty("visible", False)
        self.assertTrue(self.watchdog.property("running"))

    def delayed_bridge(self):
        bridge = DelayedBridge()
        bridge.payload = dict(self.bridge.payload)
        self.bridge = bridge
        self.root.setProperty("surfaceHost", bridge)
        return bridge

    def test_selected_variant_survives_clock_updates(self):
        bridge = self.delayed_bridge()
        self.sync(playback_generation=2)
        source, attempt, ticket = bridge.requests[-1]
        variant = "https://example.invalid/high/video.m3u8"
        bridge.mediaVideoSourceReady.emit(ticket, source, variant)
        self.assertEqual(self.player.property("source").toString(), variant)
        self.assertEqual(self.root.property("lastPlayUrl"), source)
        self.sync(position=5)
        self.assertEqual(self.player.property("source").toString(), variant)

    def test_old_manifest_response_cannot_replace_new_channel(self):
        bridge = self.delayed_bridge()
        self.sync(playback_generation=2)
        old_source, _, old_ticket = bridge.requests[-1]
        self.sync(now={"source": "https://example.invalid/new.m3u8", "media": "stream"})
        source, _, ticket = bridge.requests[-1]
        bridge.mediaVideoSourceReady.emit(old_ticket, old_source, "https://example.invalid/old.m3u8")
        self.assertTrue(self.root.property("playerResolving"))
        self.assertTrue(self.player.property("source").isEmpty())
        bridge.mediaVideoSourceReady.emit(ticket, source, "https://example.invalid/new/high.m3u8")
        self.assertEqual(self.player.property("source").toString(), "https://example.invalid/new/high.m3u8")

    def test_pause_during_manifest_resolution_cancels_and_resume_restarts(self):
        bridge = self.delayed_bridge()
        self.sync(playback_generation=2)
        source, _, ticket = bridge.requests[-1]
        self.sync(paused=True)
        bridge.mediaVideoSourceReady.emit(ticket, source, source)
        self.assertTrue(self.player.property("source").isEmpty())
        self.assertFalse(self.root.property("playerResolving"))
        self.sync(paused=False)
        self.assertEqual(len(bridge.requests), 2)
        source, _, ticket = bridge.requests[-1]
        bridge.mediaVideoSourceReady.emit(ticket, source, source)
        self.frame()
        self.assertEqual(self.bridge.reports[-1], (True, False))

    def test_opening_paused_channel_defers_manifest_until_resume(self):
        bridge = self.delayed_bridge()
        self.sync(playback_generation=2, paused=True)
        self.assertEqual(bridge.requests, [])
        self.assertFalse(self.root.property("playerResolving"))
        self.sync(paused=False)
        self.assertEqual(len(bridge.requests), 1)

    def test_old_channel_frames_cannot_cancel_new_manifest(self):
        self.frame()
        bridge = self.delayed_bridge()
        self.sync(playback_generation=2)
        self.root.noteVideoFrame()
        self.assertTrue(self.root.property("playerResolving"))
        self.assertEqual(self.player.property("playbackState"), QMediaPlayer.StoppedState.value)

    def test_recovery_while_resolving_cancels_quality_switch(self):
        self.frame()
        bridge = self.delayed_bridge()
        self.fail()
        self.restart()
        source, _, ticket = bridge.requests[-1]
        self.player.setProperty("error", QMediaPlayer.NoError.value)
        self.frame()
        self.assertFalse(self.root.property("playerResolving"))
        self.assertEqual(bridge.cancels, 1)
        bridge.mediaVideoSourceReady.emit(ticket, source, "https://example.invalid/low/video.m3u8")
        self.assertEqual(self.player.property("sourceLoads"), 1)


class VideoHostTests(unittest.TestCase):
    def test_explicit_play_increments_generation_and_state_reports_do_not(self):
        from backend import media_host as host
        item = {"id": "test-tv", "kind": "TV"}
        with patch.object(host, "_halt_audio"), patch.object(host, "save_prefs"), \
                patch.object(host, "status_payload", return_value={}), \
                patch.object(host, "publish_live") as publish, \
                patch.multiple(host, _backend="", _item=None, _paused=False,
                               _kind="audio", _qml_generation=0,
                               _qml_position=0.0, _qml_duration=0.0,
                               _qml_playing=False, _qml_buffering=False):
            host._play_qml(item)
            self.assertEqual(host._qml_generation, 1)
            self.assertTrue(host.report_player_state(True, False))
            self.assertFalse(host.report_player_state(True, False))
            publish.assert_called_once()
            self.assertEqual(host._qml_generation, 1)
            host._play_qml(item)
            self.assertEqual(host._qml_generation, 2)


if __name__ == "__main__":
    unittest.main()
