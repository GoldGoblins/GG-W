"""Real Qt button -> background PHP source review -> retained evidence."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PHPSourceUITests(unittest.TestCase):
    def test_php_project_review_keeps_ui_live_and_saves_evidence(self):
        with tempfile.TemporaryDirectory(prefix='gg-php-ui-') as directory:
            env = os.environ.copy()
            for key in ('GG_DESKTOP_STATE_ROOT', 'GG_DESKTOP_DATA_ROOT', 'GG_RESEARCH_JOBS_ROOT', 'GG_RESEARCH_DESK_ROOT', 'GG_RESEARCH_TOOLS_ROOT'):
                env[key] = str(Path(directory) / key.lower())
            env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QT_QUICK_CONTROLS_STYLE='Basic', QML_DISABLE_DISK_CACHE='1', GG_PHP_UI_ROOT=directory)
            code = r'''
import faulthandler, json, os, time
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, QTimer, QUrl, Slot, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from shiboken6 import delete
from backend.chat_surface_host import ChatSurfaceHost
from backend import research_desk, research_jobs, research_lab
faulthandler.dump_traceback_later(20, exit=True)
class Bridge(QObject):
    @Slot(str, result=str)
    def researchCommand(self, raw): return ChatSurfaceHost.researchCommand(self, raw)
app=QGuiApplication([]); bridge=Bridge(); engine=QQmlApplicationEngine()
engine.rootContext().setContextProperty('bridge', bridge)
root=Path(os.environ['GG_PHP_UI_ROOT']); project=root/'project'; project.mkdir()
(project/'page.php').write_text('<?php function page() { return 7; } page();',encoding='utf-8')
qml='import QtQuick\nimport QtQuick.Window\nimport "'+(Path('qml/components').resolve().as_uri())+'" as GG\nWindow { width:1100; height:760; visible:true; GG.ResearchSurface { objectName:"researchPane"; anchors.fill:parent; surfaceHost:bridge } }'
view=root/'view.qml';view.write_text(qml,encoding='utf-8');engine.load(QUrl.fromLocalFile(str(view)))
assert engine.rootObjects()
window=engine.rootObjects()[0]; research=window.findChild(QObject,'researchPane')
research.setProperty('page','REVERSE');pane=research.findChild(QObject,'workspaceReversePane')
pane.setProperty('targetPath',project.as_uri())
picker=pane.findChild(QObject,'reverseOperation');picker.setProperty('currentIndex',5)
button=pane.findChild(QQuickItem,'reverseAnalyze')
for _ in range(15): app.processEvents();time.sleep(.005)
assert button.property('enabled')
ticks=[]; timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
point=button.mapToItem(window.contentItem(),QPointF(button.width()/2,button.height()/2))
assert button.property('visible') and 0<=point.x()<window.width() and 0<=point.y()<window.height(), (button.property('visible'),point.x(),point.y(),window.width(),window.height(),research.property('page'),pane.width(),picker.width(),pane.findChild(QQuickItem,'reverseQuery').width(),button.parentItem().width())
QTest.mouseClick(window,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point.toPoint())
deadline=time.monotonic()+10
while time.monotonic()<deadline:
    app.processEvents();time.sleep(.01)
    if pane.property('jobState') in ('COMPLETE','ERROR','CANCELLED'):break
assert pane.property('jobState')=='COMPLETE',pane.property('notice')
assert len(ticks)>=3
history=research_jobs.history()['jobs']; report=research_jobs.load_report(history[0]['job_id'])
assert report['engine']=='PHP source review' and report['content']['functions'][0]['name']=='page'
summary=pane.findChild(QObject,'phpReviewSummary')
assert summary.property('visible') and 'page.php:1' in summary.property('text')
pane.findChild(QObject,'reverseFindingTitle').setProperty('text','PHP structure')
pane.findChild(QObject,'reverseFindingText').setProperty('text','page is declared in selected PHP source')
# Persist through the surface's existing save action, without executing PHP.
result=engine.evaluate('(function(p) { return p.saveFinding(); })').call([engine.newQObject(pane)])
assert not result.isError(), result.toString()
snapshot=research_desk.snapshot();assert len(snapshot['evidence'])==1
assert research_desk.finding_snapshot(snapshot['evidence'][0]['id'])['engine']=='PHP source review'
assert research.property('page')=='EVIDENCE'
research_lab._REPORTS.clear()
reopened=engine.evaluate('(function(p,id) { return p.openSavedFinding(id); })').call([engine.newQObject(research),snapshot['evidence'][0]['id']])
assert not reopened.isError() and reopened.toBool(),reopened.toString()
assert research.property('page')=='REVERSE' and pane.property('phpReview')
assert len(research_jobs.history()['jobs'])==1
timer.stop();window.close();delete(window);delete(engine);app.processEvents()
faulthandler.cancel_dump_traceback_later()
print('PHP_SOURCE_UI=PASS')
'''
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).resolve().parents[1],
                env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PHP_SOURCE_UI=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
