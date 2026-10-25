"""Real offscreen QML: current audio data in the background, paint only changes."""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]

PROBE = r"""
from pathlib import Path
import json,time
from PySide6.QtCore import QObject,QTimer,QUrl,Signal,Slot,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication,QWindow
from PySide6.QtQml import QQmlApplicationEngine

class Host(QObject):
    mediaStateChanged=Signal()
    def __init__(self):
        super().__init__()
        self.calls=0;self.audio_calls=0;self.playing=True;self.paused=False
        self.active=True;self.fixed_level=None;self.last_level=0
        self.volume=70;self.title='Visible';self.freq=0;self.clock='00:00'
        self.commands=[]
    @Slot(result=str)
    def mediaLiveStatus(self):
        self.calls+=1
        self.clock='tick:'+str(self.calls)
        return json.dumps({'mode':'MUSIC','playing':self.playing,'paused':self.paused,
            'volume':self.volume,'now':{'title':self.title},'clock':self.clock,
            'length':'03:00','freq_mhz':self.freq,'spectrum':[]})
    @Slot(result=str)
    def appAudioStatus(self):
        self.audio_calls+=1
        self.last_level=self.fixed_level if self.fixed_level is not None else (.2 if self.audio_calls%2 else .7)
        return json.dumps({'available':True,'meter_available':True,'active':self.active,
            'volume':self.volume,'spectrum':[self.last_level]*120 if self.active else []})
    @Slot(result=str)
    def mediaPause(self):
        self.commands.append('pause')
        self.paused=not self.paused;self.playing=not self.paused;self.active=self.playing
        return self.mediaLiveStatus()
    @Slot(result=str)
    def mediaStop(self):
        self.commands.append('stop')
        self.paused=False;self.playing=False;self.active=False
        return self.mediaLiveStatus()

app=QGuiApplication([]);app.setQuitOnLastWindowClosed(False)
host=Host();engine=QQmlApplicationEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(r.toString() for r in rows))
engine.rootContext().setContextProperty('fixtureHost',host)
qml='''import QtQuick
import QtQuick.Window
import "'''+str((Path.cwd()/'qml/components').resolve().as_uri())+'''"
Window { width:1100;height:160;visible:true
    UtilitySurface { objectName:"fixtureUtility";anchors.fill:parent;surfaceHost:fixtureHost }
}'''
engine.loadData(qml.encode(),QUrl('file:///gg-utility-idle-fixture.qml'))
assert engine.rootObjects(),warnings
window=engine.rootObjects()[0]
utility=window.findChild(QObject,'fixtureUtility')
spectrum=window.findChild(QObject,'utilitySpectrum')
frequency=window.findChild(QObject,'utilityFreqBand')
volume=window.findChild(QObject,'utilityMasterVolumeSlider')
counts={'spectrum':0,'frequency':0,'level_changes':0}
spectrum.paint.connect(lambda *_:counts.__setitem__('spectrum',counts['spectrum']+1))
frequency.paint.connect(lambda *_:counts.__setitem__('frequency',counts['frequency']+1))
spectrum.levelsChanged.connect(lambda *_:counts.__setitem__('level_changes',counts['level_changes']+1))
baseline={};records=[];control_results={}
# This window exists solely on the offscreen Qt platform. It covers the whole
# fixture and deactivates it without native input or activation requests.
cover=QWindow();cover.resize(window.width(),window.height())
def value_array(name):
    rows=spectrum.property(name)
    return rows.toVariant() if hasattr(rows,'toVariant') else rows
def mark(name):
    now={'time':time.monotonic(),'cpu':time.process_time(),'calls':host.calls,
         'audio_calls':host.audio_calls,**counts}
    if baseline:
        records.append({'stage':name,'seconds':round(now['time']-baseline['time'],3),
            'cpu_seconds':round(now['cpu']-baseline['cpu'],4),
            'shown_max':max(value_array('shown') or [0]),
            'peak_max':max(value_array('peaks') or [0]),
            'level_max':max(value_array('levels') or [0]),'source_level':host.last_level,
            'window_active':window.isActive(),'visual_active':utility.property('visualActive'),
            'window_visible':window.isVisible(),'utility_visible':utility.property('visible'),
            'clock_current':utility.property('meterClock')==host.clock,
            'title':utility.property('nowTitle'),'volume':utility.property('volume'),
            'freq':utility.property('liveFreq'),'controls_enabled':volume.property('enabled'),
            **{k:now[k]-baseline[k] for k in ('calls','audio_calls',*counts)}})
    baseline.clear();baseline.update(now)
def pause():
    host.paused=True;host.playing=False;host.active=False
    host.mediaStateChanged.emit()
def active():
    mark('paused_silent');host.paused=False;host.playing=True;host.active=True
    host.mediaStateChanged.emit()
def hold_high():
    mark('active_visible');host.fixed_level=.8
    host.mediaStateChanged.emit()
def drop_low():
    mark('high_warmup');host.fixed_level=.2
    host.mediaStateChanged.emit()
def background():
    mark('nonzero_release');host.fixed_level=None;host.title='Covered'
    cover.setPosition(window.position());cover.show()
def static_background():
    mark('background_dynamic');host.fixed_level=.35
def minimize():
    mark('background_static');host.fixed_level=None;host.title='Minimized'
    host.volume=41;host.freq=91.3;window.showMinimized()
def hide_window():
    mark('minimized_dynamic');host.title='Window hidden';host.volume=42;host.freq=92.4
    window.hide()
def hide_utility():
    mark('window_hidden_dynamic');utility.setProperty('visible',False)
    host.title='Utility hidden';host.volume=43;host.freq=93.5;window.showNormal()
def restore():
    mark('utility_hidden_dynamic');host.fixed_level=.35;host.title='Restored'
    utility.setProperty('visible',True)
def finish():
    mark('restored_static');utility.setProperty('visible',False)
    # Commands remain usable while the surface is hidden. Both methods forward
    # to the real fixture host and immediately reflect its returned state.
    control_results['pause_invoked']=QMetaObject.invokeMethod(utility,'playPause',Qt.DirectConnection)
    control_results['pause_current']=utility.property('paused') and not utility.property('playing')
    control_results['stop_invoked']=QMetaObject.invokeMethod(utility,'stop',Qt.DirectConnection)
    control_results['stop_current']=not utility.property('paused') and not utility.property('playing')
    control_results['commands']=host.commands
    control_results['enabled']=volume.property('enabled')
    app.quit()
QTimer.singleShot(150,pause)
QTimer.singleShot(500,lambda:mark('warmup'))
QTimer.singleShot(1500,active)
QTimer.singleShot(1900,lambda:mark('active_warmup'))
QTimer.singleShot(2900,hold_high)
QTimer.singleShot(3100,drop_low)
QTimer.singleShot(3900,background)
QTimer.singleShot(4300,lambda:mark('background_warmup'))
QTimer.singleShot(5300,static_background)
QTimer.singleShot(5900,lambda:mark('static_warmup'))
QTimer.singleShot(6900,minimize)
QTimer.singleShot(7200,lambda:mark('minimized_warmup'))
QTimer.singleShot(8200,hide_window)
QTimer.singleShot(8500,lambda:mark('window_hidden_warmup'))
QTimer.singleShot(9500,hide_utility)
QTimer.singleShot(9800,lambda:mark('utility_hidden_warmup'))
QTimer.singleShot(10800,restore)
QTimer.singleShot(11200,lambda:mark('restore_warmup'))
QTimer.singleShot(12200,finish)
app.exec()
print(json.dumps({'records':records,'warnings':warnings,'controls':control_results}))
cover.close();window.close()
"""


def run_probe():
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
               QT_QUICK_CONTROLS_STYLE='Basic', QML_DISABLE_DISK_CACHE='1')
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    result = subprocess.run([sys.executable, '-B', '-c', PROBE], cwd=PROJECT, env=env,
                            capture_output=True, text=True, timeout=25, **options)
    if result.returncode:
        raise AssertionError('Synthetic utility fixture failed: ' + result.stderr[-1500:])
    return json.loads(result.stdout.strip().splitlines()[-1])


class UtilityIdleLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_probe()
        cls.rows = {row['stage']: row for row in cls.report['records']}
        print(json.dumps(cls.report))

    def test_real_audio_stays_live_when_unfocused_and_covered(self):
        self.assertEqual(self.report['warnings'], [])
        background = self.rows['background_dynamic']
        self.assertFalse(background['window_active'], background)
        self.assertTrue(background['visual_active'], background)
        self.assertEqual(background['title'], 'Covered', background)
        for stage in ('active_visible', 'background_dynamic'):
            row = self.rows[stage]
            self.assertGreaterEqual(row['spectrum'], 30, row)
            self.assertGreaterEqual(row['audio_calls'], 30, row)
            self.assertGreaterEqual(row['level_changes'], 30, row)
            self.assertLessEqual(row['frequency'], 2, row)
            self.assertEqual(row['level_max'], row['source_level'], row)
            self.assertTrue(row['clock_current'], row)

    def test_silent_or_unchanged_audio_does_not_repaint(self):
        paused = self.rows['paused_silent']
        self.assertLessEqual(paused['spectrum'], 2, paused)
        self.assertLessEqual(paused['frequency'], 2, paused)
        self.assertLessEqual(paused['calls'], 5, paused)
        self.assertEqual(paused['shown_max'], 0, paused)
        self.assertEqual(paused['peak_max'], 0, paused)
        release = self.rows['nonzero_release']
        self.assertAlmostEqual(release['shown_max'], .2, places=8, msg=release)
        self.assertAlmostEqual(release['peak_max'], .2, places=8, msg=release)
        self.assertLessEqual(release['spectrum'], 30, release)
        for stage in ('background_static', 'restored_static'):
            row = self.rows[stage]
            self.assertGreaterEqual(row['audio_calls'], 30, row)
            self.assertEqual(row['level_changes'], 0, row)
            self.assertEqual(row['spectrum'], 0, row)
            self.assertEqual(row['frequency'], 0, row)
            self.assertAlmostEqual(row['shown_max'], .35, places=8, msg=row)

    def test_hidden_data_and_controls_stay_current_without_painting(self):
        for stage, title, volume, freq in (
            ('minimized_dynamic', 'Minimized', 41, 91.3),
            ('window_hidden_dynamic', 'Window hidden', 42, 92.4),
            ('utility_hidden_dynamic', 'Utility hidden', 43, 93.5),
        ):
            row = self.rows[stage]
            self.assertFalse(row['visual_active'], row)
            self.assertEqual(row['spectrum'], 0, row)
            self.assertEqual(row['frequency'], 0, row)
            self.assertGreaterEqual(row['calls'], 30, row)
            self.assertGreaterEqual(row['audio_calls'], 30, row)
            self.assertGreaterEqual(row['level_changes'], 30, row)
            self.assertTrue(row['clock_current'], row)
            self.assertEqual(row['level_max'], row['source_level'], row)
            self.assertEqual(row['title'], title, row)
            self.assertEqual(row['volume'], volume, row)
            self.assertAlmostEqual(row['freq'], freq, places=8, msg=row)
            self.assertTrue(row['controls_enabled'], row)
        self.assertEqual(self.report['controls'], {
            'pause_invoked': True, 'pause_current': True, 'stop_invoked': True,
            'stop_current': True, 'commands': ['pause', 'stop'], 'enabled': True,
        })


if __name__ == '__main__':
    unittest.main(argv=[__file__])
