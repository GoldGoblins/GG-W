"""Boot the complete desktop with a fresh Windows user state and load its views."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


@unittest.skipUnless(os.name == 'nt', 'Windows desktop integration')
class WindowsDesktopTests(unittest.TestCase):
    def test_fresh_startup_loads_workspace_and_core_views(self):
        with tempfile.TemporaryDirectory(prefix='gg desktop åäö ') as temporary:
            state = Path(temporary)
            env = os.environ.copy()
            for name in ('XDG_STATE_HOME', 'GG_DESKTOP_STATE_ROOT', 'GG_DESKTOP_DATA_ROOT',
                         'GG_RUNTIME_DIR', 'GG_WORKSPACE'):
                env.pop(name, None)
            env.update(GG_DATA_HOME=str(state / 'data'), GG_USER_HOME=str(state / 'user'),
                       GG_USER_CODEX_HOME=str(state / 'user/.codex'), CODEX_HOME=str(state / 'user/.codex'),
                       PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                       QT_QPA_PLATFORM=os.environ.get('GG_TEST_QPA_PLATFORM', 'offscreen'),
                       QSG_RHI_BACKEND='d3d11', QSG_RHI_PREFER_SOFTWARE_RENDERER='1')
            env.pop('QT_QUICK_BACKEND', None)
            code = r'''
import json, os, time, faulthandler
faulthandler.enable()
faulthandler.dump_traceback_later(20)
from pathlib import Path
from PySide6.QtCore import QTimer, QUrl, QObject
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication
from backend.application_paths import STATE_ROOT, PROJECT_ROOT
STATE_ROOT.mkdir(parents=True)
(STATE_ROOT / 'settings-v1.json').write_text(json.dumps({'engineTarget':'LOCAL_QWEN'}))
from startup import FirstFrameBootstrap, run_event_loop
from backend.native_webview import initialize_native_webview
initialize_native_webview()
app = QApplication(['GG Windows startup integration'])
engine = QQmlApplicationEngine()
warnings = []
def record_warnings(errors):
    for error in errors:
        message = error.toString()
        warnings.append(message)
engine.warnings.connect(record_warnings)
engine.load(QUrl.fromLocalFile(str(PROJECT_ROOT / 'qml/Main.qml')))
assert engine.rootObjects(), 'Window missing'
window = engine.rootObjects()[0]
bootstrap = FirstFrameBootstrap(window, app, engine)
started = time.monotonic()
checked = []
kinds = ['CODE', 'NODES', 'FLOW', 'RESEARCH', 'KNOWLEDGE', 'TMOG', 'CRYPTO', 'MARKETPLACE', 'MEDIA', 'DRAW', 'EXTERNAL', 'GAME_ENGINE']
next_check = [0.0]
def check():
    from shiboken6 import isValid
    if not isValid(window):
        timer.stop()
        print('WINDOWS_WINDOW_LOST', flush=True)
        app.exit(6);return
    if window.property('startupFailed'):
        print(window.property('shellLoadLog'), flush=True)
        app.exit(2);return
    if time.monotonic() - started > 35:
        print('Startup timed out: ' + str(window.property('shellLoadCurrent')), flush=True)
        app.exit(3);return
    if not window.property('startupReady') or window.property('shellLoading'):
        return
    workspace = window.findChild(QObject, 'workspaceSurface')
    if workspace is None:
        print('Workspace missing after startup', flush=True)
        app.exit(4);return
    if time.monotonic() < next_check[0]:
        return
    if kinds:
        kind = kinds.pop(0)
        print('WINDOWS_VIEW_LOADING=' + kind, flush=True)
        workspace.setHostKind(kind)
        checked.append(kind)
        next_check[0] = time.monotonic() + .15
        return
    faults = [message for message in warnings if any(marker in message for marker in
              ('ReferenceError:', 'TypeError:', 'is not a type', 'is not installed', 'Cannot assign'))]
    print('WINDOWS_VIEWS=' + json.dumps(checked), flush=True)
    if faults:
        print('\n'.join(faults[-12:]), flush=True)
    timer.stop()
    window.close()
    if faults:app.exit(5)
timer = QTimer()
timer.setInterval(50)
timer.timeout.connect(check)
timer.start()
bootstrap.start()
result = run_event_loop(app, engine)
print('WINDOWS_EVENT_LOOP_STOPPED', flush=True)
print('WINDOWS_QML_RELEASED', flush=True)
faulthandler.cancel_dump_traceback_later()
raise SystemExit(result)
'''
            from backend.platform_process import run_bounded
            returncode, out, err, reason = run_bounded(
                [sys.executable, '-X', 'utf8', '-B', '-c', code], cwd=PROJECT,
                env=env, timeout=45, max_output_bytes=128*1024)
            details = (out + b'\n' + err).decode('utf-8', errors='replace')[-10000:]
            if reason != 'NONE' or returncode:
                log = PROJECT / '.runtime/windows-port/desktop-integration.log'
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_bytes(out + b'\n' + err)
            self.assertEqual(reason, 'NONE', details)
            self.assertEqual(returncode, 0, details)
            self.assertIn(b'WINDOWS_VIEWS=', out)
            self.assertIn(b'WINDOWS_QML_RELEASED', out)
            self.assertNotIn(b'Traceback (most recent call last)', err, details)


if __name__ == '__main__':
    unittest.main()
