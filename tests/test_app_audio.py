"""Real application-session isolation, PCM capture and shared Utilities controls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

import numpy as np
from backend.app_audio import AppAudio


TONE_PROCESS = r'''
import sys,time
import numpy as np
from PySide6.QtCore import QBuffer,QByteArray,QIODevice
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioFormat,QAudioSink,QMediaDevices
app=QGuiApplication([])
fmt=QAudioFormat();fmt.setSampleRate(48000);fmt.setChannelCount(2);fmt.setSampleFormat(QAudioFormat.Float)
data=(.001*np.sin(2*np.pi*float(sys.argv[1])*np.arange(48000*15)/48000)).astype(np.float32)
pcm=np.column_stack((data,data)).tobytes()
buffer=QBuffer();buffer.setData(QByteArray(pcm));buffer.open(QIODevice.ReadOnly)
sink=QAudioSink(QMediaDevices.defaultAudioOutput(),fmt);sink.setBufferSize(48000*8//5)
sink.start(buffer)
print('READY',flush=True)
start=time.monotonic()
while time.monotonic()-start<15:app.processEvents();time.sleep(.01)
sink.stop()
'''


def until(predicate, *, timeout=5, process_events=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process_events:
            process_events()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Audio condition timed out")


@unittest.skipUnless(os.name == "nt", "Windows application audio sessions")
class NativeAppAudioTests(unittest.TestCase):
    def test_helper_process_descendants_are_captured_and_controlled(self):
        # Model WebView2: the audio renderer is a child of an owned helper.
        launcher = r'''
import subprocess,sys,time,os
from pathlib import Path
child=subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],'440'],stdout=subprocess.PIPE,
    stderr=sys.stderr,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
if child.stdout.readline().strip()!='READY':raise RuntimeError('Audio renderer failed to start')
print('READY:'+str(os.getpid()),flush=True)
try:
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and not Path(sys.argv[2]).exists() and child.poll() is None:time.sleep(.02)
finally:
    if child.poll() is None:child.terminate()
    child.wait(timeout=5)
'''
        with tempfile.TemporaryDirectory(prefix="gg audio helpers ") as temporary:
            stop_file = Path(temporary) / "stop"
            process = subprocess.Popen([sys.executable, "-B", "-c", launcher, TONE_PROCESS, str(stop_file)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=os.environ.copy(), creationflags=subprocess.CREATE_NO_WINDOW)
            bus = None
            try:
                ready = process.stdout.readline().strip()
                self.assertTrue(ready.startswith("READY:"), ready)
                target_pid = int(ready.split(":")[1])
                bus = AppAudio(preference_path=Path(temporary) / "master.json", process_id=target_pid)
                try:
                    until(lambda: bus.status()["active"])
                except AssertionError:
                    import psutil
                    state = dict(bus.status());state.pop("spectrum", None)
                    raise AssertionError(dict(state=state, native_error=bus.library.gga_error(bus.handle),
                        matched_sessions=bus.library.gga_sessions(bus.handle),
                        sequence=bus._sequence.value, rms=float(np.std(bus._samples)),
                        process_running=process.poll() is None,
                        descendants=[child.name() for child in psutil.Process(process.pid).children(recursive=True)]))
                self.assertLess(np.argmax(bus.status()["spectrum"]), 65)
                bus.set_volume(23, persist=False)
                until(lambda: abs(bus.library.gga_observed_gain(bus.handle) - .23) < .001)
                self.assertGreaterEqual(bus.library.gga_sessions(bus.handle), 1)
            finally:
                if bus is not None:
                    bus.close()
                stop_file.touch()
                _, diagnostic = process.communicate(timeout=5)
                self.assertFalse(diagnostic, diagnostic)

    def test_process_capture_gain_and_other_process_isolation(self):
        children = []
        buses = []
        with tempfile.TemporaryDirectory(prefix="gg application audio ") as temporary:
            try:
                for frequency in (440, 6000):
                    process = subprocess.Popen([sys.executable, "-B", "-c", TONE_PROCESS, str(frequency)],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                        env=os.environ.copy(), creationflags=subprocess.CREATE_NO_WINDOW)
                    children.append(process)
                    self.assertEqual(process.stdout.readline().strip(), "READY")
                    bus = AppAudio(preference_path=Path(temporary) / f"master-{frequency}.json",
                                   process_id=process.pid)
                    buses.append(bus)
                low, high = buses
                until(lambda: low.status()["active"] and high.status()["active"])
                self.assertLess(np.argmax(low.status()["spectrum"]), 65)
                self.assertGreater(np.argmax(high.status()["spectrum"]), 90)
                before = np.std(high._samples)
                self.assertGreater(before, .0001)
                low.set_volume(0)
                until(lambda: low.library.gga_observed_gain(low.handle) == 0)
                self.assertFalse(low.status()["active"])
                self.assertFalse(low.status()["spectrum"])
                until(lambda: high.status()["active"])
                self.assertGreater(np.std(high._samples), before * .5)
                self.assertAlmostEqual(high.library.gga_observed_gain(high.handle), 1, places=4)
                low.set_volume(37)
                until(lambda: abs(low.library.gga_observed_gain(low.handle) - .37) < .001)
                self.assertEqual(low.status()["volume"], 37)
            finally:
                for bus in buses:
                    bus.close()
                for process in children:
                    process.terminate()
                    process.wait(timeout=5)
                    process.stdout.close()

    def test_preview_is_volatile_and_committed_volume_survives_restart(self):
        with tempfile.TemporaryDirectory(prefix="gg audio preference ") as temporary:
            path = Path(temporary) / "master.json"
            bus = AppAudio(preference_path=path)
            try:
                bus.set_volume(0, persist=False)
                self.assertFalse(path.exists())
                bus.set_volume(42)
                self.assertEqual(json.loads(path.read_text()), {"volume": 42})
            finally:
                bus.close()
            restored = AppAudio(preference_path=path)
            try:
                self.assertEqual(restored.volume, 42)
            finally:
                restored.close()


class UtilityAudioControlTests(unittest.TestCase):
    def test_slider_below_eq_controls_global_audio_and_meter_without_media(self):
        # Isolated Qt process: does not touch Windows sessions or real preferences.
        code = r'''
import json,time,os
from pathlib import Path
from PySide6.QtCore import QObject,Slot,Qt,QPoint,QPointF,QCoreApplication,QEvent
from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
app=QGuiApplication([])
if os.name=='nt':
    fonts=Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'
    for name in ('consola.ttf','consolab.ttf'):QFontDatabase.addApplicationFont(str(fonts/name))
    QFont.insertSubstitution('monospace','Consolas');app.setFont(QFont('Consolas'))
class Host(QObject):
    def __init__(self):super().__init__();self.volume=70;self.previews=[];self.commits=[]
    @Slot(result=str)
    def mediaLiveStatus(self):return '{}'
    @Slot(result=str)
    def appAudioStatus(self):
        return json.dumps(dict(available=True,meter_available=True,volume=self.volume,active=self.volume>0,
            spectrum=[(.2+(i%17)/25) if self.volume else 0 for i in range(120)]))
    @Slot(int)
    def appPreviewAudioVolume(self,value):self.volume=value;self.previews.append(value)
    @Slot(int,result=str)
    def appSetAudioVolume(self,value):self.volume=value;self.commits.append(value);return self.appAudioStatus()
host=Host();engine=QQmlApplicationEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
engine.rootContext().setContextProperty('audioHost',host)
base=(Path.cwd()/'qml/components').as_uri()
engine.loadData(('import QtQuick\nimport "'+base+'"\nWindow {width:1100;height:112;visible:true;UtilitySurface {anchors.fill:parent;surfaceHost:audioHost}}').encode())
assert engine.rootObjects(),warnings
window=engine.rootObjects()[0];panel=window.findChild(QObject,'utilitySurface')
slider=window.findChild(QQuickItem,'utilityMasterVolumeSlider')
eq=window.findChild(QQuickItem,'utilityEq');meter=window.findChild(QObject,'utilitySpectrum')
QTest.qWait(150)
assert panel.property('appAudioActive') and not panel.property('playing')
assert max(meter.property('levels').toVariant())>.5
position=slider.mapToScene(QPointF(0,0));eq_end=eq.mapToScene(QPointF(0,eq.height()))
assert position.y()>=eq_end.y(),(position,eq_end)
assert position.y()+slider.height()<=window.height(),(position,slider.height(),window.height())
point=slider.mapToScene(QPointF(slider.width()*.5,slider.height()/2)).toPoint()
QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point)
slider.forceActiveFocus()
for _ in range(100):QTest.keyClick(window,Qt.Key_Left)
QTest.qWait(200)
assert host.previews[-1]==0 and host.commits[-1]==0,(host.previews,host.commits)
assert panel.property('volume')==0
assert window.findChild(QObject,'utilityMasterVolumeValue').property('text')=='0%'
for _ in range(100):QTest.keyClick(window,Qt.Key_Right)
QTest.qWait(200)
assert host.commits[-1]==100 and panel.property('volume')==100
assert max(meter.property('levels').toVariant())>.5
preview=Path.cwd()/'.runtime/app-audio/utilities-volume.png'
preview.parent.mkdir(parents=True,exist_ok=True)
assert window.grabWindow().save(str(preview))
assert not warnings,warnings
window.close();engine.deleteLater();app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
print('Global volume drag/keyboard, zero, restore, meter without radio, layout and render PASS')
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=PROJECT,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        self.assertEqual(result.returncode, 0, (result.stdout + "\n" + result.stderr)[-4000:])


if __name__ == "__main__":
    unittest.main()
