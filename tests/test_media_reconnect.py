"""Radio faults recover within a fixed budget and obey the user's controls."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QCoreApplication, QObject, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from backend.media_reconnect import RadioReconnect


class Player(QObject):
    errorOccurred = Signal(object, str)
    mediaStatusChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.err = QMediaPlayer.NoError
        self.state = QMediaPlayer.LoadedMedia
        self.sources = []
        self.plays = 0

    def error(self):
        return self.err

    def mediaStatus(self):
        return self.state

    def stop(self):
        pass

    def setSource(self, url):
        self.sources.append(url.toString())
        self.err = QMediaPlayer.NoError
        self.state = QMediaPlayer.LoadedMedia

    def play(self):
        self.plays += 1

    def fail(self):
        self.err = QMediaPlayer.FormatError
        self.errorOccurred.emit(self.err, "Demuxing failed")


class RadioReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.player = Player()
        self.recovery = RadioReconnect(self.player)
        self.url = QUrl("https://example.invalid/radio")
        self.recovery.start(self.url, live=True)

    def tearDown(self):
        self.recovery.stop()
        self.player.deleteLater()
        self.app.processEvents()

    def retry_now(self):
        self.recovery.timer.stop()
        self.recovery._restart()

    def test_demux_error_and_invalid_media_schedule_one_retry(self):
        self.player.fail()
        self.player.state = QMediaPlayer.InvalidMedia
        self.player.mediaStatusChanged.emit(self.player.state)
        self.assertTrue(self.recovery.recovering)
        self.assertEqual(self.recovery.attempts, 1)
        self.assertEqual(self.recovery.timer.interval(), 1000)
        self.retry_now()
        self.assertEqual(self.player.sources, ["", self.url.toString()])
        self.assertEqual(self.player.plays, 1)
        self.assertTrue(self.recovery.recovering)
        self.recovery.audio_received()
        self.assertFalse(self.recovery.recovering)

    def test_failed_stream_stops_after_three_retries_even_after_brief_audio(self):
        for delay in (1000, 2000, 4000):
            self.player.fail()
            self.assertEqual(self.recovery.timer.interval(), delay)
            self.retry_now()
            self.recovery.audio_received()
        self.player.fail()
        self.assertTrue(self.recovery.exhausted)
        self.assertFalse(self.recovery.timer.isActive())
        self.assertFalse(self.recovery.recovering)
        self.assertEqual(self.player.plays, 3)
        self.assertEqual(self.recovery.last_error, "Demuxing failed")

    def test_stop_cancels_pending_retry_and_late_timeout(self):
        self.player.fail()
        self.recovery.stop()
        self.recovery._restart()
        self.assertFalse(self.recovery.timer.isActive())
        self.assertEqual(self.player.plays, 0)

    def test_pause_cancels_and_manual_resume_can_retry(self):
        self.player.fail()
        self.recovery.pause(True)
        self.recovery._restart()
        self.assertEqual(self.player.plays, 0)
        self.assertFalse(self.recovery.recovering)
        self.recovery.pause(False)
        self.assertTrue(self.recovery.recovering)
        self.assertEqual(self.recovery.attempts, 1)

    def test_new_station_cancels_the_old_stations_retry(self):
        self.player.fail()
        other = QUrl("https://example.invalid/other")
        self.recovery.start(other, live=True)
        self.assertFalse(self.recovery.timer.isActive())
        self.assertFalse(self.recovery.recovering)
        self.assertEqual(self.recovery.attempts, 0)
        self.assertEqual(self.recovery.source, other)

    def test_local_files_and_non_radio_streams_do_not_retry(self):
        for source, live in ((QUrl.fromLocalFile("C:/music.wav"), True), (self.url, False)):
            self.recovery.start(source, live=live)
            self.player.fail()
            self.assertFalse(self.recovery.timer.isActive())

    def test_live_eof_retries_but_delayed_old_pcm_does_not_cancel_it(self):
        self.player.state = QMediaPlayer.EndOfMedia
        self.player.mediaStatusChanged.emit(self.player.state)
        self.recovery.audio_received()
        self.assertTrue(self.recovery.recovering)
        self.assertTrue(self.recovery.timer.isActive())
        self.assertIn("avbröts", self.recovery.last_error)

    def test_real_decoder_recovers_after_http_fault_and_cancels_its_retry(self):
        # The fake station is bounded to this child process. Decode in silence;
        # no live app state, external network, screenshot or speaker is used.
        code = r'''
import io, json, math, struct, threading, time, wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QCoreApplication
from backend import media_qt_audio as audio
app=QCoreApplication([])
player=audio._ensure()
player.setAudioOutput(None)
audio._reconnect.DELAYS_MS=(30,60,90)
stream=io.BytesIO()
with wave.open(stream,'wb') as wav:
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
    wav.writeframes(b''.join(struct.pack('<h',int(12000*math.sin(2*math.pi*440*i/16000))) for i in range(16000*12)))
body=stream.getvalue()
requests=[]
class Station(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        requests.append(self.path)
        if self.path=='/fail' or (self.path=='/radio' and requests.count('/radio')==1):
            self.send_error(503);return
        self.send_response(200);self.send_header('Content-Type','audio/wav')
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        try:
            if self.path=='/cut' and requests.count('/cut')==1:
                self.wfile.write(body[:44+16000*2*6]);self.wfile.flush()
                time.sleep(1.5)  # Supply enough PCM for FFmpeg's initial probe before dropping.
            else:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Station)
threading.Thread(target=server.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(server.server_port)
def until(predicate,timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
        if predicate():return
    raise AssertionError(str(audio.status())+' requests='+str(requests))
try:
    audio.play(base+'/radio',0,live=True)
    until(lambda:audio.status()['playing'] and audio.status()['position']>.1 and bool(audio.status()['spectrum']))
    assert len(requests)==2,requests
    assert audio._reconnect.attempts==1
    assert not audio.status()['reconnecting']
    audio.stop()
    assert player.source().isEmpty()
    audio.play(base+'/cut',0,live=True)
    until(lambda:requests.count('/cut')==1 and audio.status()['playing'] and audio.status()['position']>.1)
    until(lambda:requests.count('/cut')==2 and audio.status()['playing'] and audio.status()['position']>.1)
    assert audio._reconnect.attempts==1
    assert not audio.status()['reconnecting']
    audio.stop()
    audio.play(base+'/fail',0,live=True)
    until(lambda:audio._reconnect.exhausted)
    assert requests.count('/fail')==4,requests
    failed=audio.status()
    assert not failed['buffering'] and failed['error'] and not failed['playing'],failed
    audio.stop()
    assert not audio._reconnect.timer.isActive()
    assert player.source().isEmpty()
    assert not audio.status()['reconnecting']
    print(json.dumps({'recovered_after_http_fault':True,'recovered_after_connection_cut':True,'decoded_pcm':True,'retry_limit':3,'stop_cancels':True}))
finally:
    audio.stop();server.shutdown();server.server_close()
'''
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        from backend.platform_process import run_bounded
        result, stdout, stderr, trigger = run_bounded(
            [sys.executable, "-X", "utf8", "-B", "-c", code], cwd=PROJECT,
            env=env, timeout=18, max_output_bytes=16000)
        self.assertEqual(trigger, "NONE", (stdout + stderr).decode("utf-8", "replace")[-3000:])
        self.assertEqual(result, 0, (stdout + stderr).decode("utf-8", "replace")[-3000:])
        self.assertIn(b'"decoded_pcm": true', stdout)

    def test_qml_shows_reconnecting_then_terminal_error(self):
        code = r'''
import json
from pathlib import Path
from PySide6.QtCore import QObject,QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent,QQmlEngine
app=QGuiApplication([])
engine=QQmlEngine()
component=QQmlComponent(engine,QUrl.fromLocalFile(str(Path('qml/components/UtilitySurface.qml').resolve())))
root=component.create()
assert root is not None,[e.toString() for e in component.errors()]
engine.globalObject().setProperty('panel',engine.newQObject(root))
result=engine.evaluate('panel.applyChrome({mode:"RADIO",reconnecting:true,retry_attempt:1,retry_limit:3,buffering:true,error:"Demuxing failed"})')
assert not result.isError(),result.toString()
label=root.findChild(QObject,'utilityNow')
assert label.property('text')=='Återansluter · 1/3',label.property('text')
result=engine.evaluate('panel.applyChrome({mode:"RADIO",reconnecting:false,retry_attempt:3,retry_limit:3,buffering:false,error:"Demuxing failed"})')
assert label.property('text')=='Demuxing failed',label.property('text')
media=QQmlComponent(engine,QUrl.fromLocalFile(str(Path('qml/components/MediaSurface.qml').resolve())))
assert not media.isError(),[e.toString() for e in media.errors()]
print('QML_RECONNECT_STATUS_PASS')
root.deleteLater();app.processEvents()
'''
        env = os.environ.copy()
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                   QML_DISABLE_DISK_CACHE="1", PYTHONDONTWRITEBYTECODE="1")
        from backend.platform_process import run_bounded
        result, stdout, stderr, trigger = run_bounded(
            [sys.executable,"-X","utf8","-B","-c",code], cwd=PROJECT,
            env=env, timeout=8, max_output_bytes=5000)
        self.assertEqual((trigger,result), ("NONE",0), (stdout+stderr).decode("utf-8","replace"))


if __name__ == "__main__":
    unittest.main()
