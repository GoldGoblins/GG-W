"""Local usage reads stay off Qt and cannot cross the active-session boundary."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.model_usage_runtime import ModelUsageRuntime, read_usage


class ModelUsageRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(predicate())

    def test_slow_read_is_coalesced_off_gui_and_old_selection_never_published(self):
        entered, release = threading.Event(), threading.Event()
        calls, delivered = [], []
        main_thread = threading.get_ident()
        def source(session, root):
            calls.append((session, threading.get_ident()))
            if session == 'first':
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('Owned fixture timed out')
            return {'limit_percent': 82, 'selection': session}
        runtime = ModelUsageRuntime(source=source)
        runtime.updated.connect(lambda raw: delivered.append(json.loads(raw)))
        try:
            self.assertIsNone(runtime._worker)
            runtime.refresh('first', '/owned-fixture')
            self.assertTrue(entered.wait(1))
            for _ in range(30):
                runtime.refresh('second', '/owned-fixture')
            release.set()
            self.wait_for(lambda: bool(delivered))
            self.assertEqual([row['selection'] for row in delivered], ['second'])
            self.assertEqual([row[0] for row in calls], ['first', 'second'])
            self.assertTrue(all(thread != main_thread for _, thread in calls))
            runtime.refresh('second', '/owned-fixture')
            self.wait_for(lambda: len(calls) == 3)
            self.app.processEvents()
            self.assertEqual(len(delivered), 1)
        finally:
            release.set()
            runtime.close()
        self.assertFalse(runtime._worker.is_alive())
        runtime.refresh('third', '/owned-fixture')
        self.assertEqual(len(calls), 3)

    def test_missing_active_rollout_does_not_read_latest_unrelated_session(self):
        with patch('backend.codex_wallet.session_path', return_value=None), \
             patch('backend.codex_wallet.snapshot', return_value={'limit_percent': None}) as snapshot:
            self.assertEqual(read_usage('requested-active', '/owned-fixture'), {'limit_percent': None})
        snapshot.assert_called_once_with(session=None, sessions_root=Path('/owned-fixture'), allow_latest=False)

    def test_real_host_timer_delivers_appended_usage_without_manual_refresh(self):
        with tempfile.TemporaryDirectory(prefix='gg-model-usage-host-') as temporary:
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'), GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'),
                GG_USER_CODEX_HOME=str(Path(temporary)/'codex'), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--host', temporary],
                cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, encoding='utf-8', timeout=12)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


def host_fixture(directory):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from backend.chat_surface_host import ChatSurfaceHost
    app = QGuiApplication([])
    root = Path(directory)/'sessions'
    root.mkdir()
    session = '00000000-0000-0000-0000-000000000001'
    path = root/'usage.jsonl'
    path.write_text(json.dumps({'payload': {'id': session}})+'\n'+json.dumps({'payload': {'rate_limits': {
        'primary': {'used_percent': 82, 'resets_at': 1793783760}}}})+'\n', encoding='utf-8')
    host = ChatSurfaceHost()
    for timer in host.findChildren(QTimer):
        if timer is not host._gpt_wallet_timer:
            timer.stop()
    host._gpt_session_id, host._gpt_sessions_root = session, root
    delivered = []
    host.gptWalletChanged.connect(lambda raw: delivered.append(json.loads(raw)))
    def wait_for(value):
        deadline = time.monotonic()+3
        while (not delivered or delivered[-1].get('limit_percent') != value) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.003)
        assert delivered and delivered[-1]['limit_percent'] == value
    try:
        assert host._gpt_wallet_timer.interval() == 1000
        wait_for(82)
        reset = delivered[-1]['limit_reset_label']
        with path.open('a', encoding='utf-8') as target:
            target.write(json.dumps({'payload': {'rate_limits': {'primary': {'used_percent': 86}}}})+'\n')
        wait_for(86)
        assert delivered[-1]['limit_reset_label'] == reset and reset != '—'
        assert not host._sessions
    finally:
        host.shutdown()
    assert not host._model_usage._worker.is_alive()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--host':
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        host_fixture(sys.argv[2])
    else:
        unittest.main()
