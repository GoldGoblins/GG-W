"""Exercise the Windows paths that formerly stopped approved desktop tasks."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows runtime integration')
class WindowsRuntimeTests(unittest.TestCase):
    def run_isolated(self, code, timeout=25):
        with tempfile.TemporaryDirectory(prefix='gg windows åäö ') as directory:
            env = os.environ.copy()
            for name in ('XDG_STATE_HOME', 'GG_DESKTOP_STATE_ROOT', 'GG_RUNTIME_DIR'):
                env.pop(name, None)
            env.update(GG_DATA_HOME=directory, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                       QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', code],
                                    cwd=PROJECT, env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=timeout)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            return result.stdout

    def test_gptui_uses_yolo_for_new_and_resumed_chats(self):
        self.run_isolated('''
import os
from pathlib import Path
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication
from backend import chat_surface_host as chat
app = QCoreApplication([])
home = Path(os.environ['GG_DATA_HOME']) / 'codex'
sessions = home / 'sessions'
sessions.mkdir(parents=True)
host = chat.ChatSurfaceHost()
with patch('backend.platform_support.windows_codex_binary', return_value='codex.exe'), \\
     patch.object(chat, 'DESKTOP_CODEX_HOME', home), \\
     patch.object(chat, 'DESKTOP_CODEX_SESSIONS', sessions), \\
     patch.object(chat, 'start_codex_image_guard', return_value=Mock(poll=lambda: None)), \\
     patch.object(chat, 'codex_session_path', return_value=sessions / 'resume.jsonl'), \\
     patch.object(chat, 'prepare_codex_resume', return_value={'status': 'unchanged'}), \\
     patch.object(host, '_ensure_gpt_codex_home', return_value=True), \\
     patch.object(host, '_gpt_session_location', return_value=(home, sessions)), \\
     patch.object(host, '_gptui_developer_instructions', return_value='shared instructions'), \\
     patch.object(host, '_watch_pty'), \\
     patch.object(chat, '_terminal_process', return_value=(Mock(), None)) as launch:
    for session_id in ('', '00000000-0000-0000-0000-000000000001'):
        host._gpt_session_id = session_id
        assert host._start_gpt_tui()
        argv = launch.call_args.args[0]
        assert argv.count('--dangerously-bypass-approvals-and-sandbox') == 1, argv
        assert '--sandbox' not in argv and '--ask-for-approval' not in argv, argv
        assert 'developer_instructions="shared instructions"' in argv
        assert ('resume' in argv) == bool(session_id)
        if session_id:
            assert argv[argv.index('resume') + 1] == session_id
''')

    def test_private_records_use_real_owner_and_private_acl(self):
        self.run_isolated('''
import os
from pathlib import Path
from backend.platform_files import secure_open, mode_matches, owned_by_current_user, set_private_mode
from backend.platform_support import private_runtime_root
root = private_runtime_root()
path = root / 'private approval åäö.json'
fd = secure_open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
assert owned_by_current_user(fd)
os.write(fd, b'{}')
os.close(fd)
assert mode_matches(path, 0o600)
result = __import__('subprocess').run(['icacls', str(path), '/grant', '*S-1-1-0:R'], capture_output=True)
assert result.returncode == 0
assert not mode_matches(path, 0o600), 'broad read access accepted as private'
set_private_mode(path, 0o600)
assert mode_matches(path, 0o600)
assert path.read_bytes() == b'{}'
''')

    def test_nullable_qml_object_slot_does_not_crash_the_desktop(self):
        self.run_isolated('''
from PySide6.QtCore import QObject, Slot, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent
app = QGuiApplication([])
class Host(QObject):
    @Slot(result=QObject)
    def missing(self):return None
host = Host()
engine = QQmlEngine()
engine.rootContext().setContextProperty('host', host)
component = QQmlComponent(engine)
component.setData(b'import QtQuick; Item { property var value: host.missing() }', QUrl())
item = component.create()
assert item is not None and item.property('value') is None
''')

    def test_task_ledger_persists_and_reopens_on_windows(self):
        self.run_isolated('''
from backend.application_paths import STATE_ROOT
from backend.platform_files import mode_matches
from backend.control_plane_contract import TaskLedger
STATE_ROOT.mkdir(parents=True)
root = STATE_ROOT / 'ledger'
ledger = TaskLedger(root)
digest = ledger.put_object({'message': 'Windows åäö'})
assert ledger.get_object(digest) == {'message': 'Windows åäö'}
assert TaskLedger(root).get_object(digest) == {'message': 'Windows åäö'}
assert mode_matches(root, 0o700)
''')

    def test_chat_initializes_ledger_and_approval_store_together(self):
        self.run_isolated('''
from types import SimpleNamespace
from backend import task_scoped_action_grant
import main
probe = SimpleNamespace(_ledger_error='',
    _recover_selfdev_records=lambda runtime: None,
    _block_unrecoverable_autonomy_records=lambda: None)
main.ChatBridge.initialize_startup_task_state(probe)
assert not probe._ledger_error, probe._ledger_error
assert probe._task_ledger is not None
assert probe._live_mandate_store.root == task_scoped_action_grant.DEFAULT_MANDATE_ROOT
assert probe._live_mandate_store.root.is_dir()
''')

    def test_worker_modules_import_without_linux_user_apis(self):
        self.run_isolated('''
import importlib
for name in ('autonomy_candidate_runner', 'autonomy_controller', 'autonomy_model_runner',
             'control_plane_runner', 'local_ai_model_runner', 'local_ai_chat_runner',
             'safe_tool_runner', 'write_runner', 'resident_chat_runner'):
    importlib.import_module('backend.' + name)
''')

    def test_explicit_host_environment_preserves_windows_but_excludes_secrets(self):
        self.run_isolated('''
import os, subprocess, sys
from backend.platform_support import host_environment
os.environ['GG_TEST_SECRET_VALUE'] = 'must not be inherited'
env = host_environment({'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
assert env['SystemRoot'] == os.environ['SystemRoot']
assert env['PATH'] == os.environ['PATH']
assert 'GG_TEST_SECRET_VALUE' not in env
child = subprocess.run([sys.executable, '-c', "import os; assert 'SystemRoot' in os.environ; assert 'GG_TEST_SECRET_VALUE' not in os.environ; print('åäö')"], env=env, capture_output=True)
assert child.returncode == 0, child.stderr
assert child.stdout.decode('utf-8').strip() == 'åäö'
''')

    def test_both_pipes_output_limits_and_timeout_are_enforced(self):
        self.run_isolated('''
import sys, time
from backend.platform_process import run_bounded
command = [sys.executable, '-c', "import sys; sys.stdout.buffer.write(b'out'); sys.stderr.buffer.write(b'err')"]
code, out, err, reason = run_bounded(command, timeout=5, max_output_bytes=32)
assert (code, out, err, reason) == (0, b'out', b'err', 'NONE')
command = [sys.executable, '-c', "import sys; sys.stdout.buffer.write(b'x'*1000000); sys.stdout.flush()"]
code, out, err, reason = run_bounded(command, timeout=5, max_output_bytes=1024)
assert reason == 'OUTPUT_LIMIT' and len(out) + len(err) <= 1024
began = time.monotonic()
code, out, err, reason = run_bounded([sys.executable, '-c', 'import time;time.sleep(20)'], timeout=.2)
assert reason == 'TIMEOUT' and time.monotonic() - began < 5
''')

    def test_real_windows_job_object_reports_enforced_limits(self):
        self.run_isolated('''
from backend.platform_process import apply_windows_worker_limits
limits = apply_windows_worker_limits(memory_bytes=512*1024*1024, cpu_seconds=5)
assert limits['memory_bytes'] == 512*1024*1024
assert limits['cpu_seconds'] == 5
assert limits['kill_children_on_exit']
''')

    def test_game_workflow_completes_in_a_real_windows_worker(self):
        self.run_isolated('''
import os, time
from pathlib import Path
from backend import game_workflow_jobs as jobs, game_workflow_common as common
root = Path(os.environ['GG_DATA_HOME'])
common.ROOT = root / 'workflows'
assets = root / 'assets'
assets.mkdir()
(assets / 'example.obj').write_text('v 0 0 0\\nv 1 0 0\\nv 0 1 0\\nf 1 2 3\\n')
state = jobs.start('scout_index', {'path': str(assets), 'game':'Windows test'})
assert state['status'] == 'QUEUED', state
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    state = jobs.status(state['job_id'])
    if state['status'] not in jobs.BUSY:
        break
    time.sleep(.05)
assert state['status'] == 'COMPLETE', state
assert state['result']['indexed'] == 1, state
''')

    def test_windows_audio_uses_qt_and_plays_silent_local_wave(self):
        self.run_isolated('''
import time, wave
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from backend import media_host, media_contract, media_qt_audio
app = QCoreApplication([])
root = media_contract.STATE_DIR / 'library'
root.mkdir(parents=True)
path = root / 'silence.wav'
with wave.open(str(path), 'wb') as stream:
    stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
    stream.writeframes(b'\\0' * 16000)
media_host._extra_items = [{'id':'windows-audio', 'kind':'MUSIC', 'title':'Silent test',
                            'source':str(path), 'media':'file'}]
result = media_host.play_item('windows-audio')
assert result['backend'] == 'qt_audio', result
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    app.processEvents()
    if media_qt_audio.status()['duration'] > 0:
        break
    time.sleep(.02)
assert media_qt_audio.status()['duration'] > 0, media_qt_audio.status()
media_host.set_volume(37)
assert abs(media_qt_audio._output.volume() - .37) < .01
media_host.pause(); app.processEvents()
assert media_host.status_payload()['paused']
media_host.seek(.2)
media_host.stop(); app.processEvents()
assert not media_qt_audio.status()['playing']
''')


if __name__ == '__main__':
    unittest.main()
