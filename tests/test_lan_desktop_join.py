"""Desktop bootstrap joining and per-user startup state, without live nodes."""
import ast
import contextlib
from copy import deepcopy
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend import gg_lan_dag as lan, lan_dag_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


def bootstrap_fixture():
    identity = lan.Keypair()
    body = {'schema': 'gg.lan-dag.invite.v1', 'label': 'Windows fixture',
            'host': '127.0.0.1', 'port': 16120, 'peer_key': identity.pubkey().hex(),
            'producer_keys': [lan.Keypair().pubkey().hex() for _ in range(2)],
            'nonce': 'a' * 64}
    return {'schema': runtime.BOOTSTRAP_SCHEMA,
            'coordinator_invite': lan._signed(identity, lan._INVITE, body),
            'allowed_cidr': '127.0.0.0/8'}


class LanDesktopJoinTests(unittest.TestCase):
    def test_join_reads_signed_public_file_then_uses_existing_start(self):
        document = bootstrap_fixture()
        manager = runtime.LanDagRuntime()
        with tempfile.TemporaryDirectory(prefix='gg-public-join-') as directory:
            path = Path(directory) / 'gg-lan-bootstrap.json'
            runtime.write_public_document(str(path), document, 'bootstrap')
            options = {'path': path.as_uri(), 'label': 'GG Linux', 'port': 16120,
                       'bind_host': 'auto', 'allow_test_tokens': True}
            with patch.object(manager, 'start', return_value={'state': 'fixture'}) as start:
                self.assertEqual(manager.dispatch('lan.join_file', options), {'state': 'fixture'})
            start.assert_called_once_with(bootstrap=document, label='GG Linux', port=16120,
                                          bind_host='auto', allow_test_tokens=True)

    def test_changed_signature_and_unknown_join_options_fail_before_start(self):
        document = bootstrap_fixture()
        changed = deepcopy(document)
        changed['coordinator_invite']['body']['host'] = '127.0.0.2'
        manager = runtime.LanDagRuntime()
        with tempfile.TemporaryDirectory(prefix='gg-public-join-invalid-') as directory:
            path = Path(directory) / 'changed.json'
            path.write_text(json.dumps(changed), encoding='utf-8')
            with patch.object(manager, 'start') as start, patch.object(runtime.socket, 'socket') as sockets:
                with self.assertRaises(ValueError):
                    manager.dispatch('lan.join_file', {'path': str(path)})
                with patch.object(runtime, 'read_public_document') as read:
                    with self.assertRaisesRegex(ValueError, 'ACTION_ARGUMENTS'):
                        manager.dispatch('lan.join_file', {'path': str(path), 'trusted_coordinator': 'unused'})
                    read.assert_not_called()
                start.assert_not_called()
                sockets.assert_not_called()
        self.assertFalse(manager.active)

    def test_join_obeys_same_local_dag_fence_as_coordinator_start(self):
        from backend import gg_parallel_dag, omni_service
        with patch.object(gg_parallel_dag, 'snapshot', return_value={'state': 'RUNNING'}), \
             patch.object(runtime, 'action') as action:
            with self.assertRaisesRegex(ValueError, 'STOP_LOCAL_DAG_FIRST'):
                omni_service._action('lan_join_file', '{"path":"not-read.json"}')
            action.assert_not_called()

    def test_terminal_join_preserves_local_dag_fence(self):
        from backend.terminal_service import TerminalService
        service = object.__new__(TerminalService)
        service._lock = __import__('threading').RLock()
        service._closed = False
        service._dag_engine = Mock()
        service._dag_engine.snapshot.return_value = {'state': 'RUNNING'}
        service._lan_runtime = None
        with patch.object(service, '_lan') as manager:
            with self.assertRaisesRegex(ValueError, 'STOP_LOCAL_DAG_FIRST'):
                service.dispatch('lan.join_file', {'path': 'not-read.json'})
            manager.assert_not_called()

    def test_foreground_join_polls_same_owned_lan_then_closes_on_interrupt(self):
        from backend import terminal_cli
        service = Mock()
        state = {'lan': {'state': 'PAIRING', 'authenticated_peers': []},
                 'lan_setup': {'invite_count': 1}}
        service.dispatch.return_value = state
        service.dispatch.side_effect = [state, KeyboardInterrupt()]
        with contextlib.redirect_stdout(io.StringIO()), patch.object(terminal_cli.time, 'sleep'):
            code = terminal_cli.main(['--json', '--foreground', '--command',
                                      'lan.join_file label=Linux path=public.json'], lambda: service)
        self.assertEqual(code, 130)
        self.assertEqual(service.dispatch.call_args_list[0].args,
                         ('lan.join_file', {'label': 'Linux', 'path': 'public.json'}))
        self.assertEqual(service.dispatch.call_args_list[1].args, ('lan.status', {}))
        service.close.assert_called_once_with()

    def test_hidden_join_controls_keep_explicit_consent_and_busy_fences(self):
        script = r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
source='import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nLanDagSetupPopup {}'
component.setData(source.encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[row.toString() for row in component.errors()]
root=component.create();assert root is not None
actions=[]
root.actionRequested.connect(lambda name,args:actions.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
def js(code):
    expr=QQmlExpression(qmlContext(root),root,code);value=expr.evaluate()
    assert not expr.hasError(),expr.error().toString()
    return value[0] if isinstance(value,tuple) else value
join=root.findChild(QQuickItem,'lanBootstrapJoin');assert join and join.isEnabled()
assert root.findChild(QQuickItem,'lanLabel').setProperty('text','GG Linux')
js('joinBootstrap("file:///tmp/gg-lan-bootstrap.json")')
assert actions[-1]==('lan_join_file',{'path':'file:///tmp/gg-lan-bootstrap.json','label':'GG Linux','port':16120,'bind_host':'auto','allow_test_tokens':False})
root.findChild(QQuickItem,'lanAllowTestTokens').setProperty('checked',True)
js('joinBootstrap("file:///tmp/gg-lan-bootstrap.json")');assert actions[-1][1]['allow_test_tokens'] is True
for code in ('canAct=false','canAct=true;localRunning=true','localRunning=false;state={lan_setup:{active:true}}'):
    js(code);assert not join.isEnabled();before=len(actions)
    js('joinBootstrap("file:///tmp/ignored.json")');assert len(actions)==before
root.deleteLater();engine.deleteLater();app.processEvents();assert not warnings,warnings
'''
        with tempfile.TemporaryDirectory(prefix='gg-lan-join-ui-') as directory:
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                               QT_QUICK_CONTROLS_STYLE='Basic')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script, directory],
                                    cwd=ROOT, env=environment, capture_output=True, text=True,
                                    encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class StartupCurrentUserStateTests(unittest.TestCase):
    def test_actual_startup_method_uses_current_profile_state_parent(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        bridge = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == 'ChatBridge')
        method = next(item for item in bridge.body if isinstance(item, ast.FunctionDef) and item.name == 'initialize_startup_task_state')
        module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
        for relative in ('another-user/.local/state/goldgoblins/gg-ai-desktop', 'custom-profile/state'):
            with self.subTest(profile=relative), tempfile.TemporaryDirectory(prefix='gg-user-startup-') as directory:
                state = Path(directory) / relative
                runtime_path = Path(directory) / 'runtime'
                ledger = Mock()
                mandate = Mock()
                namespace = {'STATE_ROOT': state, 'private_runtime_root': lambda: runtime_path,
                             'control_contract': SimpleNamespace(TaskLedger=ledger),
                             'task_scoped_action_grant': SimpleNamespace(DEFAULT_MANDATE_ROOT=Path(directory) / 'mandate'),
                             'live_mandate_store': SimpleNamespace(MandateStore=mandate)}
                exec(compile(module, str(ROOT / 'main.py'), 'exec'), namespace)
                probe = SimpleNamespace(_ledger_error='', _recover_selfdev_records=Mock(),
                                        _block_unrecoverable_autonomy_records=Mock())
                namespace['initialize_startup_task_state'](probe)
                self.assertEqual(probe._ledger_error, '')
                ledger.assert_called_once_with(state.parent / 'workbench-control-v2',
                                               legacy_root=runtime_path / 'gg-control-plane-v1')
                self.assertTrue(state.parent.is_dir())
                mandate.return_value.initialize.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
