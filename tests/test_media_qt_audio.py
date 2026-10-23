"""Actual PCM/Qt playback and live utility-panel regressions, without internet."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend.media_spectrum import PcmSpectrum


def tone(frequency, channels=1, rate=48000):
    wave = .5 * np.sin(2 * np.pi * frequency * np.arange(PcmSpectrum.FRAMES) / rate)
    return np.repeat(wave[:, None], channels, axis=1)


class SpectrumTests(unittest.TestCase):
    def test_automatic_reconnect_is_enabled_only_for_radio(self):
        from backend import media_host as host, media_qt_audio as audio
        with patch.multiple(host, _item=None, _kind='audio', _backend='', _paused=False), \
             patch.object(host, '_halt_audio'), \
             patch.object(host, 'save_prefs', return_value={'volume':70}), \
             patch.object(host, 'status_payload', return_value={}), \
             patch.object(audio, 'play') as play:
            for kind in ('RADIO','MUSIC','FETCH'):
                item={'id':'test','kind':kind,'source':'https://example.invalid/audio'}
                host._play_qt_audio(item)
                self.assertEqual(play.call_args.kwargs['live'], kind=='RADIO')

    def test_bass_and_treble_peak_in_different_frequency_bands(self):
        spectrum = PcmSpectrum()
        spectrum.push(tone(200), 48000)
        low = spectrum.levels()
        spectrum.push(tone(6000), 48000)
        high = spectrum.levels()
        self.assertEqual(len(low), 120)
        self.assertLess(np.argmax(low), 45)
        self.assertGreater(np.argmax(high), 90)
        self.assertGreater(max(low), .7)
        self.assertGreater(max(high), .7)

    def test_silence_volume_and_opposite_phase_stereo(self):
        spectrum = PcmSpectrum()
        stereo = tone(1000, channels=2)
        stereo[:, 1] *= -1
        spectrum.push(stereo, 48000)
        loud = max(spectrum.levels())
        self.assertGreater(loud, .7)
        self.assertLess(max(spectrum.levels(.1)), loud - .2)
        self.assertEqual(max(spectrum.levels(0)), 0)
        spectrum.push(np.zeros((PcmSpectrum.FRAMES, 2)), 48000)
        self.assertEqual(max(spectrum.levels()), 0)

    def test_storage_is_bounded_and_format_changes_discard_previous_samples(self):
        spectrum = PcmSpectrum()
        for _ in range(30):
            spectrum.push(tone(200), 48000)
        self.assertEqual(spectrum._samples.shape, (PcmSpectrum.FRAMES, 1))
        spectrum.push(np.zeros((PcmSpectrum.FRAMES, 2)), 44100)
        self.assertEqual(max(spectrum.levels()), 0)
        spectrum.reset()
        self.assertEqual(max(spectrum.levels()), 0)

    def test_qt_integer_unsigned_and_float_pcm_are_decoded(self):
        from PySide6.QtMultimedia import QAudioBuffer, QAudioFormat
        from backend import media_qt_audio as audio
        for kind, dtype, scale, offset in (
            (QAudioFormat.UInt8, np.uint8, 127, 128),
            (QAudioFormat.Int16, np.int16, 32767, 0),
            (QAudioFormat.Int32, np.int32, 2147483647, 0),
            (QAudioFormat.Float, np.float32, 1, 0),
        ):
            with self.subTest(format=kind):
                fmt = QAudioFormat()
                fmt.setSampleRate(48000)
                fmt.setChannelCount(1)
                fmt.setSampleFormat(kind)
                audio._clear_spectrum()
                pcm = (tone(1000) * scale + offset).astype(dtype).tobytes()
                audio._receive_buffer(QAudioBuffer(pcm, fmt))
                levels = audio._spectrum.levels()
                self.assertGreater(max(levels), .7)
                self.assertTrue(60 <= np.argmax(levels) <= 70)

    def test_live_status_refreshes_qt_instead_of_returning_cached_buffering(self):
        from backend import media_host as host, media_qt_audio as audio
        prefs = {'mode':'RADIO', 'volume':70, 'last_id':'test-radio'}
        current = {'playing':True, 'buffering':False, 'position':12, 'duration':0,
                   'error':'', 'spectrum':[.8] * 120}
        with patch.multiple(host, _backend='qt_audio', _paused=False,
                            _item={'id':'test-radio','title':'Test','stream':True},
                            _live_payload={},
                            _live_json='{"buffering":true,"position":0}'), \
             patch.object(host,'load_prefs',return_value=prefs), \
             patch.object(host,'_cached_rf',return_value={}), \
             patch.object(audio,'status',return_value=current):
            result = json.loads(host.live_status_json())
            self.assertTrue(result['playing'])
            self.assertFalse(result['buffering'])
            self.assertEqual(result['position'],12)
            self.assertEqual(result['spectrum'],[.8]*120)
            current.update(playing=False, buffering=False, error='Cannot open stream', spectrum=[])
            failed = json.loads(host.live_status_json())
            self.assertFalse(failed['buffering'])
            self.assertEqual(failed['error'],'Cannot open stream')
            self.assertFalse(failed['spectrum'])

    def test_real_player_updates_qml_meters_pause_seek_mute_and_stop(self):
        with tempfile.TemporaryDirectory(prefix='gg media ') as temporary:
            env = os.environ.copy()
            for name in ('XDG_STATE_HOME','GG_DESKTOP_STATE_ROOT','GG_DESKTOP_DATA_ROOT','GG_RUNTIME_DIR'):
                env.pop(name,None)
            env.update(GG_DATA_HOME=temporary, GG_MEDIA_TEST_ROOT=temporary,
                       QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
            code = r'''
import json, os, time, wave
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, Slot, QUrl
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from backend import media_host as host, media_qt_audio as audio
root=Path(os.environ['GG_MEDIA_TEST_ROOT'])
rate=48000
low=.5*np.sin(2*np.pi*200*np.arange(rate*3)/rate)
high=.5*np.sin(2*np.pi*6000*np.arange(rate*3)/rate)
source=root/'bass then treble.wav'
with wave.open(str(source),'wb') as stream:
    stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate)
    stream.writeframes((np.concatenate((low,high))*32767).astype(np.int16).tobytes())
app=QGuiApplication([])
if os.name=='nt':
    fonts=Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'
    for name in ('consola.ttf','consolab.ttf'):
        QFontDatabase.addApplicationFont(str(fonts/name))
    QFont.insertSubstitution('monospace','Consolas')
    app.setFont(QFont('Consolas'))
audio._ensure().setAudioOutput(None)  # Decode normally; no test tones on the user's speakers.
host.load_prefs=lambda:{'mode':'RADIO','volume':70,'last_id':'test-radio'}
host._cached_rf=lambda:{}
host._backend='qt_audio';host._paused=False
host._item={'id':'test-radio','title':'Frequency test','stream':True}
host.publish_live({'backend':'qt_audio','buffering':True,'playing':False,'position':0})
class Bridge(QObject):
    @Slot(result=str)
    def mediaLiveStatus(self):return host.live_status_json()
bridge=Bridge()
engine=QQmlApplicationEngine()
warnings=[]
engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
engine.rootContext().setContextProperty('testMediaHost',bridge)
base=(Path.cwd()/'qml/components').as_uri()
engine.loadData(('import QtQuick\nimport "'+base+'"\nWindow {width:1000;height:180;visible:true;UtilitySurface {anchors.fill:parent;surfaceHost:testMediaHost}}').encode())
assert engine.rootObjects(),warnings
window=engine.rootObjects()[0]
panel=window.findChild(QObject,'utilitySurface')
audio.play(str(source),70)
def until(predicate):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
        if predicate():return
    raise AssertionError('Timed out: '+str(audio.status())+' '+str(warnings))
until(lambda:audio.status()['playing'] and audio.status()['position']>.2 and max(audio.status()['spectrum'] or [0])>.5)
until(lambda:panel.property('playing') and not panel.property('buffering'))
bands=audio.status()['spectrum']
assert len(bands)==120 and np.argmax(bands)<45,bands
canvas=window.findChild(QObject,'utilitySpectrum')
drawn=canvas.property('levels').toVariant()
assert len(drawn)==120 and max(drawn)>.5,drawn
now=window.findChild(QObject,'utilityNow')
assert 'buffer' not in now.property('text')
image=window.grabWindow()
assert not image.isNull()
preview=Path.cwd()/'.runtime/windows-port/media-spectrum-preview.png'
preview.parent.mkdir(parents=True,exist_ok=True)
assert image.save(str(preview))
audio.pause(True);until(lambda:not audio.status()['playing'])
assert not audio.status()['spectrum']
audio.seek(3.2);audio.pause(False)
until(lambda:audio.status()['position']>3.3 and np.argmax(audio.status()['spectrum'] or [0])>90)
audio._output.setMuted(True)
assert max(audio.status()['spectrum'] or [0])==0
audio._output.setMuted(False)
audio.stop()
assert not audio.status()['playing'] and not audio.status()['buffering'] and not audio.status()['spectrum']
until(lambda:not panel.property('playing') and not panel.property('buffering'))
from shiboken6 import delete
delete(engine)
assert not warnings,warnings
print('Real Qt playback, frequency change, live QML meters and transport PASS')
'''
            result = subprocess.run([sys.executable,'-X','utf8','-B','-c',code],
                                    cwd=PROJECT,env=env,capture_output=True,text=True,
                                    encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(result.returncode,0,(result.stdout+'\n'+result.stderr)[-4000:])


if __name__ == '__main__':
    unittest.main()
