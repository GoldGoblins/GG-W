"""Real Qt Research forms, failure recovery and asynchronous UI contracts."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class ResearchUiTests(unittest.TestCase):
    def test_forms_jobs_and_all_nine_sections(self):
        with tempfile.TemporaryDirectory(prefix="gg-research-ui-") as raw:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_QUICK_CONTROLS_STYLE="Basic", PYTHONDONTWRITEBYTECODE="1",
                       GG_DESKTOP_STATE_ROOT=str(Path(raw) / "state"),
                       GG_DESKTOP_DATA_ROOT=str(Path(raw) / "data"),
                       GG_RESEARCH_DESK_ROOT=str(Path(raw) / "desk"),
                       GG_RESEARCH_JOBS_ROOT=str(Path(raw) / "jobs"),
                       GG_UI_TEST_ROOT=raw)
            code = r'''
import json, os, sys, time
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, Qt, QUrl, Slot
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from backend import research_desk, research_lab, qip_lab
from backend.chat_surface_host import ChatSurfaceHost
sys.path.insert(0, str(Path('tests').resolve()))
from test_qip_lab import minimal_qip_module

class Bridge(QObject):
    def __init__(self):
        super().__init__()
        self.fail_op = ''
        self.malformed_op = ''
        self.calls = []
        self.job = 'a' * 32
        self.replies = {}
        self.qip_calls = []
        self.qip_malformed = False
    @Slot(str, result=str)
    def researchCommand(self, raw):
        value = json.loads(raw); op = value['op']; self.calls.append(op)
        if op == self.fail_op: return json.dumps({'status':'ERROR','reason':'Fixture storage unavailable'})
        if op == self.malformed_op: return 'invalid reply'
        if op in self.replies: return json.dumps(self.replies[op])
        return ChatSurfaceHost.researchCommand(self, raw)
    @Slot(str, result=str)
    def qipInspect(self, path): return json.dumps(qip_lab.inspect_file(path))
    @Slot(str, str, result=str)
    def qipStart(self, path, text):
        if self.qip_malformed: return 'invalid reply'
        self.qip_calls.append(('start', text)); return json.dumps({'state':'RUNNING','job_id':self.job})
    @Slot(str, result=str)
    def qipStatus(self, job):
        self.qip_calls.append(('status', job)); return json.dumps({'state':'DONE','output_text':'OK','output_bytes':2,'deterministic':True})
    @Slot(str, result=str)
    def qipCancel(self, job):
        self.qip_calls.append(('cancel', job)); return json.dumps({'state':'CANCELLED'})
    @Slot(str, str, result=str)
    def qipRun(self, path, text): raise AssertionError('Async-capable bridge used synchronous QIP execution')

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
if os.name == 'nt':
    for name in ('consola.ttf','consolab.ttf','consolai.ttf','consolaz.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace','Consolas')
    app.setFont(QFont('Consolas'))
bridge = Bridge(); engine = QQmlApplicationEngine(); warnings = []
engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
engine.rootContext().setContextProperty('testBridge', bridge)
directory = (Path('qml/components').resolve()).as_uri()
qml = 'import QtQuick\nimport QtQuick.Window\nimport "' + directory + '" as GG\nWindow {width:1100;height:760;visible:true; GG.ResearchSurface {anchors.fill:parent;surfaceHost:testBridge}}'
engine.loadData(qml.encode(), QUrl.fromLocalFile(str(Path('qml/research-ui-test.qml').resolve())))
assert engine.rootObjects(), 'Research window did not load'
window = engine.rootObjects()[0]
QTest.qWait(40)
pane = window.findChild(QQuickItem, 'workspaceResearchPane')
reverse = window.findChild(QQuickItem, 'workspaceReversePane')
games = window.findChild(QQuickItem, 'workspaceGameWorkflowsPane')
qip = window.findChild(QQuickItem, 'workspaceQipPane')
assert all(item is not None for item in (pane, reverse, games, qip))

def invoke(item, method, *args):
    function = engine.evaluate('(function(item) { return item.' + method + '(' + ','.join(json.dumps(arg) for arg in args) + '); })')
    result = function.call([engine.newQObject(item)])
    assert not result.isError(), result.toString()
    return result

def visual_items(item):
    for child in item.childItems():
        yield child
        yield from visual_items(child)

def click(name):
    button = next((item for item in visual_items(window.contentItem()) if item.objectName() == name), None)
    assert button and button.isVisible(), 'Missing or hidden button ' + name
    center = button.mapToScene(QPointF(button.width()/2, button.height()/2))
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center.toPoint())
    QTest.qWait(10)

for page in ('BACKLOG','EVIDENCE','MEMORY','WEB SKILLS','SQL','EVALS','WASM LAB','REVERSE','GAMES'):
    click('researchTab_' + page.replace(' ','_'))
    assert pane.property('page') == page
click('researchTab_BACKLOG')
pane.setProperty('taskTitle','Retain this draft'); pane.setProperty('taskBody','Acceptance notes')
bridge.fail_op = 'add_task'; click('researchAddTask')
assert pane.property('taskTitle') == 'Retain this draft' and pane.property('taskBody') == 'Acceptance notes'
assert 'unavailable' in pane.property('notice')
bridge.fail_op = ''; click('researchAddTask')
assert pane.property('taskTitle') == '' and len(research_desk.snapshot()['tasks']) == 1
assert pane.property('notice') == 'TASK_CREATED', 'Snapshot refresh hid the actual save outcome'
snapshot = pane.property('statusJson'); bridge.malformed_op = 'snapshot'; invoke(pane, 'refresh')
assert pane.property('statusJson') == snapshot and 'Invalid response' in pane.property('notice')
bridge.malformed_op = ''

click('researchTab_EVIDENCE'); pane.setProperty('evidenceTitle','Known observation'); pane.setProperty('evidenceClaim','Fixture contains a symbol')
bridge.fail_op = 'add_evidence'; click('researchAddEvidence')
assert pane.property('evidenceTitle') == 'Known observation' and pane.property('evidenceClaim') == 'Fixture contains a symbol'
bridge.fail_op = ''
click('researchAddEvidence'); assert len(research_desk.snapshot()['evidence']) == 1
click('researchTab_MEMORY'); pane.setProperty('sourceTitle','Fixture source'); pane.setProperty('sourceText','A bounded research source note.')
bridge.fail_op = 'ingest_source'; click('researchAddSource')
assert pane.property('sourceTitle') == 'Fixture source' and pane.property('sourceText') == 'A bounded research source note.'
bridge.fail_op = ''
click('researchAddSource'); assert len(research_desk.snapshot()['sources']) == 1
assert window.findChild(QQuickItem,'researchSources').property('count') == 1
pane.setProperty('methodName','Inspect then verify'); pane.setProperty('methodSteps','Inspect locations\nCompare independently')
bridge.fail_op = 'add_method'; click('researchAddMethod')
assert pane.property('methodName') == 'Inspect then verify' and pane.property('methodSteps') == 'Inspect locations\nCompare independently'
bridge.fail_op = ''
click('researchAddMethod'); assert research_desk.snapshot()['methods'][0]['status'] == 'PROPOSED'
click('researchTab_WEB_SKILLS'); pane.setProperty('skillName','Evidence draft'); pane.setProperty('skillTemplate','Capture evidence')
pane.setProperty('skillScript',"await page.goto('https://example.invalid'); // evidence")
bridge.fail_op = 'add_web_skill'; click('researchAddSkill')
assert pane.property('skillName') == 'Evidence draft' and 'page.goto' in pane.property('skillScript')
bridge.fail_op = ''
click('researchAddSkill'); assert research_desk.snapshot()['skills'][0]['status'] == 'DRAFT'
click('researchTab_SQL'); click('researchSqlPreview')
assert json.loads(pane.property('sqlResult'))['executed'] is False
click('researchTab_EVALS'); click('researchEvalStart'); assert pane.property('activeRunId')
assert not invoke(pane,'startEvaluation').toBool() and len(research_desk.snapshot()['runs']) == 1
pane.setProperty('eventNote','Observed fixture result'); click('researchEvalEvent')
assert research_desk.snapshot()['observability']['events'] == 1
pane.setProperty('evalScore','wrong'); click('researchEvalPass')
assert research_desk.snapshot()['runs'][0]['status'] == 'RUNNING'
pane.setProperty('evalScore','0.75'); click('researchEvalPass')
assert research_desk.snapshot()['runs'][0]['status'] == 'PASS' and not pane.property('activeRunId')

root = Path(os.environ['GG_UI_TEST_ROOT']); target = root / 'source åäö.js'; target.write_text('export const observed = 7;', encoding='utf-8')
click('researchTab_REVERSE'); assert invoke(reverse, 'inspectArtifact', target.as_uri()).toBool()
previous = reverse.property('reportJson')
assert not invoke(reverse,'inspectArtifact',str(root/'missing')).toBool()
assert reverse.property('reportJson') == previous, 'Failed inspection discarded the last report'
bridge.replies['lab_start'] = {'status':'QUEUED','job_id':bridge.job}
bridge.replies['lab_cancel'] = {'status':'CANCELLED','reason':'USER_CANCELLED'}
click('reverseAnalyze'); assert reverse.property('busy')
assert not invoke(reverse,'inspectArtifact',str(root/'missing')).toBool()
click('reverseCancelAnalysis'); assert reverse.property('jobState') == 'CANCELLED'
bridge.replies['lab_start'] = {'status':'ERROR','reason':'Engine not installed'}
click('reverseAnalyze'); assert not reverse.property('jobId') and not reverse.property('busy')
assert 'Engine not installed' in reverse.property('notice')
bridge.replies['lab_start'] = {'status':'QUEUED'}
click('reverseAnalyze'); assert not reverse.property('busy') and 'did not return a job' in reverse.property('notice')

click('researchTab_GAMES'); bridge.replies['game_start'] = {'status':'QUEUED','job_id':bridge.job}
bridge.replies['game_cancel'] = {'status':'CANCELLED'}
invoke(games,'run','scout_search',{'query':'fixture'}); assert games.property('busy')
click('gameCancelWorkflow'); assert not games.property('busy')
bridge.replies['game_start'] = {'status':'ERROR','reason':'Invalid selection'}
invoke(games,'run','scout_search',{'query':'fixture'}); assert not games.property('jobId')
assert games.property('notice') == 'Invalid selection'
bridge.replies['game_start'] = {'status':'QUEUED'}
invoke(games,'run','scout_search',{'query':'fixture'}); assert not games.property('busy')

click('researchTab_WASM_LAB'); module = root / 'render åäö.wasm'; module.write_bytes(minimal_qip_module())
assert invoke(qip,'inspectFile',module.as_uri()).toBool()
input_area = window.findChild(QQuickItem,'qipInput'); input_area.setProperty('text','Preserve input')
began = time.monotonic(); click('qipRunRender'); assert time.monotonic() - began < .5 and qip.property('running')
assert bridge.qip_calls[0] == ('start','Preserve input')
invoke(qip,'pollModule'); assert qip.property('jobState') == 'DONE'
assert json.loads(qip.property('reportJson'))['output_text'] == 'OK'
assert input_area.property('text') == 'Preserve input'
click('qipRunRender'); click('qipCancelRender'); assert qip.property('jobState') == 'CANCELLED'
assert input_area.property('text') == 'Preserve input'
bridge.qip_malformed = True; click('qipRunRender')
assert qip.property('jobState') == 'ERROR' and not qip.property('running')
assert input_area.property('text') == 'Preserve input' and qip.property('ready')
assert 'Invalid response' in qip.property('notice')
window.setWidth(480); QTest.qWait(30)
viewport = window.findChild(QQuickItem,'researchViewport')
assert viewport.property('contentWidth') >= 760 > viewport.width()
viewport.setProperty('contentX', 100); assert viewport.property('contentX') == 100
preview = os.environ.get('GG_RESEARCH_UI_PREVIEW')
if preview:
    folder = Path(preview); folder.mkdir(parents=True, exist_ok=True)
    for width, page in ((1100,'MEMORY'),(1100,'EVALS'),(480,'WASM LAB')):
        window.setWidth(width); pane.setProperty('page',page); viewport.setProperty('contentX',0); QTest.qWait(50)
        assert window.grabWindow().save(str(folder / (page.replace(' ','_') + '.png')))

faults = [message for message in warnings if any(token in message for token in
          ('ReferenceError:', 'TypeError:', 'Cannot assign', 'Unable to assign', 'is not a type', 'Binding loop'))]
assert not faults, '\n'.join(faults)
window.close(); delete(engine)
print('WINDOWS_RESEARCH_UI=PASS')
'''
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", code],
                                    cwd=PROJECT, env=env, capture_output=True, text=True,
                                    encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("WINDOWS_RESEARCH_UI=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
