"""Real mandate-store/grant flow, temporary fixture state, no keys or network."""
import json
from contextvars import ContextVar
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend import terminal_approval as terminal
from backend import wallet_approval as wallet, omni_assets as assets
from backend import live_mandate_store as mandates, task_scoped_action_grant as grants


class TerminalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-terminal-approval-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for module, name, value in ((terminal, 'STATE_ROOT', self.root), (assets, 'ROOT', self.root/'omni')):
            replaced = patch.object(module, name, value); replaced.start(); self.addCleanup(replaced.stop)
        self.addCleanup(wallet.cancel_all)

    def records(self):
        return [json.loads(path.read_text(encoding='utf-8')) for path in sorted(self.root.glob('terminal-approvals/*/objects/*/*.json'))]

    def test_real_confirmation_publishes_exact_grant_and_consumes_it_once(self):
        args = {'label': 'Fixture wallet', 'password': 'RAM-only-password-never-durable'}
        summaries = []; tokens = []
        def action():
            token = wallet.require_operation('create_wallet', args, 'credentials.write')
            tokens.append(token); return {'public_result': True}
        result = terminal.execute('create_wallet', args, action, lambda summary: summaries.append(summary) or True)
        self.assertEqual(result, {'public_result': True})
        self.assertEqual(len(tokens), 1); self.assertEqual(tokens[0]['effect'], 'credentials.write')
        self.assertIn('Fixture wallet', summaries[0])
        self.assertNotIn('sha256', summaries[0]); self.assertNotIn(args['password'], summaries[0])
        records = self.records(); self.assertEqual([row['status'] for row in records], ['PENDING', 'APPROVED', 'CONSUMED'])
        self.assertEqual(records[-1]['target_object_id'], tokens[0]['target_object_id'])
        self.assertFalse(wallet._tickets)
        store = next(self.root.glob('terminal-approvals/*'))
        self.assertIsNone(grants.runtime_authorize_effect('credentials.write', store_root=store))
        for path in self.root.rglob('*'):
            if path.is_file(): self.assertNotIn(args['password'].encode(), path.read_bytes())

    def test_denial_nonboolean_and_missing_prompt_never_invoke_callback(self):
        action = Mock()
        for answer in (False, None, 'ja', 1):
            with self.assertRaisesRegex(ValueError, 'APPROVAL_REJECTED'):
                terminal.execute('create_wallet', {'label': 'Fixture'}, action, lambda _summary: answer)
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
            terminal.execute('create_wallet', {}, action, None)
        action.assert_not_called(); self.assertFalse(wallet._tickets)
        self.assertNotIn('APPROVED', [row['status'] for row in self.records()])

    def test_prompt_exception_rejects_pending_and_erases_ticket(self):
        action = Mock()
        with self.assertRaises(EOFError):
            terminal.execute('create_wallet', {'label': 'Fixture'}, action, Mock(side_effect=EOFError()))
        action.assert_not_called(); self.assertFalse(wallet._tickets)
        self.assertEqual([row['status'] for row in self.records()], ['PENDING', 'REJECTED'])

    def test_target_drift_during_confirmation_never_binds_grant(self):
        source = self.root/'fixture.ggwallet'; source.write_bytes(b'public synthetic ciphertext')
        action = Mock()
        def changed(_summary): source.write_bytes(b'changed synthetic ciphertext'); return True
        with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
            terminal.execute('restore_wallet', {'path': source, 'label': 'Fixture', 'password': 'RAM-only'}, action, changed)
        action.assert_not_called(); self.assertFalse(wallet._tickets)
        self.assertNotIn('APPROVED', [row['status'] for row in self.records()])

    def test_callback_cannot_reuse_approval_for_changed_operation(self):
        with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
            terminal.execute('create_wallet', {'label': 'Approved'},
                lambda: wallet.require_operation('create_wallet', {'label': 'Changed'}, 'credentials.write'), lambda _summary: True)
        self.assertEqual(self.records()[-1]['status'], 'CONSUMED')
        self.assertFalse(wallet._tickets)

    def test_callback_failure_consumes_and_desktop_pointer_is_untouched(self):
        desktop = self.root/'mandate-store'; desktop.mkdir(); pointer = desktop/grants.RUNTIME_NAME
        pointer.write_bytes(b'fixture desktop task must remain unchanged')
        with self.assertRaisesRegex(ValueError, 'FIXTURE_CALLBACK_FAILURE'):
            terminal.execute('create_wallet', {'label': 'Fixture'}, Mock(side_effect=ValueError('FIXTURE_CALLBACK_FAILURE')), lambda _summary: True)
        self.assertEqual(pointer.read_bytes(), b'fixture desktop task must remain unchanged')
        self.assertEqual(self.records()[-1]['status'], 'CONSUMED')

    def test_separate_operations_never_share_grants_and_strip_terminal_controls(self):
        for index in range(2):
            summaries = []
            terminal.execute('create_wallet', {'label': 'Fixture\x1b[31m'},
                lambda: wallet.require_operation('create_wallet', {'label': 'Fixture\x1b[31m'}, 'credentials.write'),
                lambda summary: summaries.append(summary) or True)
            self.assertNotIn('\x1b', summaries[0])
        rows = [row for row in self.records() if row['status'] == 'CONSUMED']
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['task_id'], rows[1]['task_id'])
        self.assertNotEqual(rows[0]['target_object_id'], rows[1]['target_object_id'])

    def test_contextvars_survive_and_bind_failure_consumes_approval(self):
        session = ContextVar('fixture_unlocked_session', default=None)
        token = session.set('fixture RAM session')
        try:
            result = terminal.execute('create_wallet', {'label': 'Fixture'}, lambda: session.get(), lambda _summary: True)
            self.assertEqual(result, 'fixture RAM session')
        finally:
            session.reset(token)
        callback = Mock()
        with patch.object(wallet, 'bind_approval', side_effect=ValueError('FIXTURE_BIND_FAILURE')):
            with self.assertRaisesRegex(ValueError, 'FIXTURE_BIND_FAILURE'):
                terminal.execute('create_wallet', {'label': 'Fixture'}, callback, lambda _summary: True)
        callback.assert_not_called(); self.assertFalse(wallet._tickets)
        self.assertEqual(len([row for row in self.records() if row['status'] == 'CONSUMED']), 2)


if __name__ == '__main__': unittest.main()
