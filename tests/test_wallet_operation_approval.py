"""Exact operation approval and encrypted backup publication, fixture state only."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

from backend import omni_assets as store, wallet_approval as approval, wallet_vault as vault
from backend import live_mandate_store as mandates, task_scoped_action_grant as grants
from tests.test_live_mandate_store import _pending, _receipt


class OperationApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-wallet-operation-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(store, 'ROOT', self.root / 'state')
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.addCleanup(approval.cancel_all)
        store.bootstrap()
        self.mandates = mandates.MandateStore(self.root / 'mandates')
        self.mandates.initialize()

    def approve(self, identifier, *, publish=True):
        context = approval.context(identifier)
        capture = hashlib.sha256((identifier + 'capture').encode()).hexdigest()
        scope = hashlib.sha256((identifier + 'scope').encode()).hexdigest()
        pending = _pending(capture=capture, scope=scope, risk='RED')
        pending['action_intent'].update(target_object_id=context['object_id'],
            target_source_revision=context['sha256'])
        mandates.put_pending(self.mandates, pending)
        record = mandates.approve(self.mandates, request_capture_sha256=capture,
            approval_scope_revision=scope, approver_id='human:fixture',
            mandate_assertion_sha256='e' * 64, evaluation_receipt=_receipt(capture, scope, 'e' * 64))
        if publish:
            grants.publish_runtime_scope(grants.issue_from_approved_record(record),
                store_root=self.mandates.root, allowed_hosts=approval.request(identifier)['allowed_hosts'])
        approval.bind_approval(identifier, record, store_root=self.mandates.root)
        return record

    def test_no_active_ticket_rejects_generic_approval_before_key_generation(self):
        with patch.object(grants, 'runtime_authorize_effect', return_value={'fixture': True}), \
                patch('solders.keypair.Keypair') as key:
            with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
                vault.create('fixture')
            key.assert_not_called()
        self.assertFalse((store.ROOT / 'wallet-vault').exists())

    def test_replaced_task_cannot_authorize_operation_or_consume_other_task(self):
        callback = Mock()
        identifier = approval.stage('create_wallet', {'label': 'fixture'}, callback)
        original = self.approve(identifier)
        other = approval.stage('create_wallet', {'label': 'another fixture'}, Mock())
        replacement = self.approve(other)
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
            approval.execute(identifier)
        callback.assert_not_called()
        self.assertEqual(self.mandates.get(original['request_capture_sha256'])['status'], 'CONSUMED')
        self.assertEqual(self.mandates.get(replacement['request_capture_sha256'])['status'], 'APPROVED')
        self.assertNotIn(identifier, approval._tickets)

    def test_changed_operation_arguments_and_state_root_fail_closed(self):
        args = {'label': 'fixture'}
        identifier = approval.stage('create_wallet', args,
            lambda: approval.require_operation('create_wallet', {'label': 'changed'}, 'credentials.write'))
        self.approve(identifier)
        with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
            approval.execute(identifier)
        callback = Mock()
        identifier = approval.stage('create_wallet', args, callback)
        self.approve(identifier)
        with patch.object(store, 'ROOT', self.root / 'different-state'):
            with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
                approval.execute(identifier)
        callback.assert_not_called()

    def test_restore_contents_path_and_secret_are_bound_without_persisting_secret(self):
        source = self.root / 'fixture.ggwallet'
        source.write_bytes(b'public fixture ciphertext')
        secret = 'fixture-password-never-in-approval'
        args = {'path': source, 'password': secret, 'label': 'fixture'}
        callback = Mock()
        identifier = approval.stage('restore_wallet', args, callback)
        self.approve(identifier)
        self.assertNotIn(secret, json.dumps(approval.request(identifier)))
        for file in self.mandates.root.rglob('*'):
            if file.is_file():
                self.assertNotIn(secret.encode(), file.read_bytes())
        source.write_bytes(b'changed public fixture ciphertext')
        with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
            approval.execute(identifier)
        callback.assert_not_called()
        self.assertNotIn(identifier, approval._tickets)

    def test_send_binds_endpoint_host_and_reviewed_transaction(self):
        from backend import solana_transfers
        body = {'expires_at': time.time() + 90, 'amount': '1', 'symbol': 'FIXTURE',
            'to': 'fixture public recipient', 'cost_sol': '0.000005', 'message': 'fixture unsigned message'}
        args = {'id': 'fixture', 'review_digest': 'fixture-digest'}
        endpoint = {'endpoint': 'https://approved.example/rpc'}
        callback = Mock()
        with patch.object(solana_transfers, 'snapshot', side_effect=lambda *_: {'body': dict(body)}), \
                patch.object(store, 'network', side_effect=lambda *_: dict(endpoint)):
            identifier = approval.stage('send_transfer', args, callback)
            self.approve(identifier)
            endpoint['endpoint'] = 'https://changed.example/rpc'
            with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
                approval.execute(identifier)
            callback.assert_not_called()
            endpoint['endpoint'] = 'https://approved.example/rpc'
            identifier = approval.stage('send_transfer', args,
                lambda: approval.require_operation('send_transfer', args, 'crypto.solana.transfer', host='changed.example'))
            self.approve(identifier)
            with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
                approval.execute(identifier)
            identifier = approval.stage('send_transfer', args, callback)
            self.approve(identifier)
            body['message'] = 'different unsigned transaction'
            with self.assertRaisesRegex(ValueError, 'OPERATION_CHANGED'):
                approval.execute(identifier)

    def test_revocation_rejection_and_expiry_clear_callbacks_and_secrets(self):
        args = {'label': 'fixture', 'password': 'fixture secret retained only in RAM'}
        callback = Mock()
        identifier = approval.stage('create_wallet', args, callback)
        record = self.approve(identifier)
        ticket = approval._tickets[identifier]
        mandates.revoke(self.mandates, request_capture_sha256=record['request_capture_sha256'],
            approval_scope_revision=record['approval_scope_revision'])
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
            approval.execute(identifier)
        self.assertIsNone(ticket.callback); self.assertEqual(ticket.args, {})
        for expire in (False, True):
            identifier = approval.stage('create_wallet', args, callback)
            ticket = approval._tickets[identifier]
            if expire:
                with patch.object(approval.time, 'time', return_value=ticket.expires_at + 1):
                    approval.expire(identifier)
            else:
                approval.cancel(identifier)
            self.assertIsNone(ticket.callback); self.assertEqual(ticket.args, {})
        callback.assert_not_called()

    def test_network_backup_paths_reject_before_any_filesystem_probe(self):
        with patch.object(approval, 'is_link', side_effect=AssertionError('must not probe SMB')):
            with self.assertRaisesRegex(ValueError, 'BACKUP_PATH'):
                approval.local_path(r'\\untrusted.example\share\wallet.ggwallet')

    @unittest.skipUnless(os.name == 'nt', 'Current-user Windows DPAPI fixture')
    def test_approved_callback_creates_only_one_fixture_key_and_is_consumed(self):
        identifier = approval.stage('create_wallet', {'label': 'fixture'}, lambda: vault.create('fixture'))
        record = self.approve(identifier)
        result = approval.execute(identifier)
        self.assertEqual(len(vault.status()), 1)
        self.assertTrue(vault._path(result['pubkey']).is_file())
        self.assertEqual(self.mandates.get(record['request_capture_sha256'])['status'], 'CONSUMED')
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
            approval.execute(identifier)
        self.assertEqual(len(vault.status()), 1)

    def test_publish_never_overwrites_an_existing_backup_even_with_concurrent_writers(self):
        target = self.root / 'same.ggwallet'
        barrier = threading.Barrier(2)
        def write(value):
            barrier.wait(timeout=5)
            try:
                vault._write(target, value, overwrite=False)
                return 'written'
            except FileExistsError:
                return 'exists'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, (b'first ciphertext', b'second ciphertext')))
        self.assertEqual(sorted(results), ['exists', 'written'])
        self.assertIn(target.read_bytes(), (b'first ciphertext', b'second ciphertext'))

    @unittest.skipUnless(os.name == 'nt', 'Current-user Windows DPAPI fixture')
    def test_approved_encrypted_backup_and_restore_validate_persisted_ciphertext(self):
        identifier = approval.stage('create_wallet', {'label': 'fixture'}, lambda: vault.create('fixture'))
        self.approve(identifier)
        public = approval.execute(identifier)
        output = self.root / 'fixture.ggwallet'
        secret = 'fixture-password-never-in-chat'
        args = {'pubkey': public['pubkey'], 'path': output, 'password': secret}
        identifier = approval.stage('backup_wallet', args, lambda: vault.export_backup(**args))
        self.approve(identifier); approval.execute(identifier)
        self.assertTrue(vault.status()[0]['backed_up'])
        self.assertNotIn(secret.encode(), output.read_bytes())
        args = {'path': output, 'password': secret, 'label': 'restored fixture'}
        identifier = approval.stage('restore_wallet', args, lambda: vault.restore_backup(**args))
        self.approve(identifier)
        self.assertEqual(approval.execute(identifier)['pubkey'], public['pubkey'])

    def test_actual_signed_spl_round_trip_through_real_operation_gate(self):
        from backend import omni_rpc, solana_transfers
        from tests.test_crypto_solana_wallet import TransferTests
        require = approval.require_operation
        fixture = TransferTests('test_actual_signed_spl_round_trip_with_ata_creation_and_real_svm')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        def rpc(url, payload=None, **kwargs):
            if payload['method'] == 'getGenesisHash':
                return {'jsonrpc': '2.0', 'id': 1, 'result': solana_transfers.MAINNET_GENESIS}
            return fixture.rpc(url, payload, **kwargs)
        with patch.object(approval, 'require_operation', new=require), patch.object(omni_rpc, '_json', side_effect=rpc):
            forward = fixture.prepare()
            args = {'id': forward['id'], 'review_digest': forward['body']['review_digest']}
            identifier = approval.stage('send_transfer', args, lambda: solana_transfers.send(**{'identifier': args['id'], 'review_digest': args['review_digest']}))
            record = self.approve(identifier)
            self.assertEqual(approval.execute(identifier)['state'], 'SUBMITTED')
            self.assertEqual(self.mandates.get(record['request_capture_sha256'])['status'], 'CONSUMED')
            self.assertEqual(solana_transfers.check(forward['id'])['state'], 'CONFIRMED')
            fixture.bank.airdrop(fixture.recipient.pubkey(), 10**7); fixture.bank.expire_blockhash()
            back = solana_transfers.prepare(fixture.recipient_id, fixture.asset['id'], str(fixture.source.pubkey()), '0.234567')
            args = {'id': back['id'], 'review_digest': back['body']['review_digest']}
            identifier = approval.stage('send_transfer', args,
                lambda: solana_transfers.send(args['id'], args['review_digest']))
            self.approve(identifier)
            self.assertEqual(approval.execute(identifier)['state'], 'SUBMITTED')
            self.assertEqual(fixture.tokens(fixture.recipient_ata), 1000000)
            self.assertEqual(len(fixture.sent), 2)

    def test_revocation_during_rebuild_prevents_key_read_and_broadcast(self):
        from backend import omni_rpc, solana_transfers
        from tests.test_crypto_solana_wallet import TransferTests
        require = approval.require_operation
        fixture = TransferTests('test_actual_signed_spl_round_trip_with_ata_creation_and_real_svm')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        def rpc(url, payload=None, **kwargs):
            if payload['method'] == 'getGenesisHash':
                return {'jsonrpc': '2.0', 'id': 1, 'result': solana_transfers.MAINNET_GENESIS}
            return fixture.rpc(url, payload, **kwargs)
        with patch.object(approval, 'require_operation', new=require), patch.object(omni_rpc, '_json', side_effect=rpc):
            draft = fixture.prepare()
            args = {'id': draft['id'], 'review_digest': draft['body']['review_digest']}
            identifier = approval.stage('send_transfer', args, lambda: solana_transfers.send(args['id'], args['review_digest']))
            record = self.approve(identifier)
            build = solana_transfers._build
            def revoke_during_rebuild(*positional):
                result = build(*positional)
                mandates.revoke(self.mandates, request_capture_sha256=record['request_capture_sha256'],
                    approval_scope_revision=record['approval_scope_revision'])
                return result
            with patch.object(solana_transfers, '_build', side_effect=revoke_during_rebuild), \
                    patch.object(vault, '_keypair', side_effect=AssertionError('revoked approval must not read signer')):
                with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
                    approval.execute(identifier)
            self.assertFalse(fixture.sent)
            self.assertEqual(solana_transfers.snapshot(draft['id'])['state'], 'FAILED')


class ChatGateTests(unittest.TestCase):
    def setUp(self):
        OperationApprovalTests.setUp(self)
        from PySide6.QtCore import QCoreApplication
        from backend.chat_surface_host import ChatSurfaceHost
        from backend.crypto_ui_runtime import CryptoUiRuntime
        import main as workbench
        self.app = QCoreApplication.instance() or QCoreApplication([])
        self.runtime = CryptoUiRuntime(snapshot=lambda: {'assets': [], 'wallet_overview': {}}, ttl=60)
        self.addCleanup(self.runtime.close)
        self.host = SimpleNamespace(_omni_runtime=lambda: self.runtime,
            _wallet_action_approval_handler=None)
        for name in ('omniAction', '_wallet_operation_notice', 'resume_wallet_operation', '_expire_wallet_operation'):
            setattr(self.host, name, getattr(ChatSurfaceHost, name).__get__(self.host))
        self.bridge = SimpleNamespace(_pending_mandates={}, _mandate_session_id='fixture-session',
            _live_mandate_store=self.mandates, _task_ledger=object(),
            _tui_chat_context=lambda: ('@current', 'ws.file.context-composer'),
            _shutdown_resident_idle_for_task=lambda: None, _append=Mock(),
            _resident_chat=SimpleNamespace(_surface_host=self.host, submit=Mock()))
        for name in ('_capture_wallet_operation', '_capture_chat_native_mandate', '_build_chat_native_mandate',
                '_capture_pending_mandate', '_supersede_older_chat_native_mandates', '_waiting_chat_native_mandates',
                '_submit_bare_chat_approval', '_submit_mandate', '_approve_chat_native_mandate'):
            setattr(self.bridge, name, getattr(workbench.ChatBridge, name).__get__(self.bridge))
        for name in ('capture_action_task', 'record_action_approval', 'record_action_dispatch'):
            item = patch.object(workbench.action_task_continuity, name)
            item.start(); self.addCleanup(item.stop)

    def test_missing_callback_reports_nonrunning_approval_required_without_creating_key(self):
        result = json.loads(self.host.omniAction('create_wallet', '{"label":"fixture"}'))
        self.assertEqual(result['ui_operation']['state'], 'approval_required')
        self.assertEqual(result['ui_operation']['error'], 'WALLET_APPROVAL_REQUIRED')
        self.assertFalse(self.runtime._active)
        self.assertFalse(approval._tickets)
        self.assertFalse((store.ROOT / 'wallet-vault').exists())

    @unittest.skipUnless(os.name == 'nt', 'Current-user Windows DPAPI fixture')
    def test_plain_chat_ja_executes_exact_callback_once_without_model_dispatch(self):
        self.host._wallet_action_approval_handler = self.bridge._capture_wallet_operation
        result = json.loads(self.host.omniAction('create_wallet', '{"label":"fixture"}'))
        self.assertEqual(result['ui_operation']['state'], 'approval_required')
        self.assertFalse((store.ROOT / 'wallet-vault').exists())
        pending = next(iter(self.bridge._pending_mandates.values()))
        self.assertTrue(self.bridge._submit_bare_chat_approval('APPROVE', '@current', 'ws.tui.gpt'))
        deadline = time.monotonic() + 5
        while self.runtime._running and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.01)
        self.assertFalse(self.runtime._running)
        self.assertEqual(json.loads(self.runtime.snapshot())['ui_operation']['state'], 'done')
        self.assertEqual(len(vault.status()), 1)
        self.assertEqual(self.mandates.get(pending['request_capture_sha256'])['status'], 'CONSUMED')
        self.bridge._resident_chat.submit.assert_not_called()
        self.assertFalse(self.bridge._submit_bare_chat_approval('APPROVE', '@current', 'ws.tui.gpt'))
        self.assertFalse(approval._tickets)

    def test_plain_chat_nej_clears_secret_callback_and_never_dispatches(self):
        source = self.root / 'fixture.ggwallet'; source.write_bytes(b'public fixture ciphertext')
        secret = 'fixture-password-must-never-reach-chat'
        self.host._wallet_action_approval_handler = self.bridge._capture_wallet_operation
        self.host.omniAction('restore_wallet', json.dumps({'path': str(source), 'password': secret}))
        pending = next(iter(self.bridge._pending_mandates.values()))
        ticket = approval._tickets[pending['wallet_operation']]
        source.write_bytes(b'changed ciphertext still permits human rejection')
        self.assertTrue(self.bridge._submit_bare_chat_approval('REJECT', '@current', 'ws.tui.gpt'))
        self.assertEqual(self.mandates.get(pending['request_capture_sha256'])['status'], 'REJECTED')
        self.assertFalse(approval._tickets); self.assertIsNone(ticket.callback); self.assertEqual(ticket.args, {})
        self.bridge._resident_chat.submit.assert_not_called()
        self.assertNotIn(secret, repr(self.bridge._append.call_args_list))

    def test_expired_request_clears_secret_and_stops_waiting_for_chat_approval(self):
        source = self.root / 'fixture.ggwallet'; source.write_bytes(b'public fixture ciphertext')
        self.host._wallet_action_approval_handler = self.bridge._capture_wallet_operation
        self.host.omniAction('restore_wallet', json.dumps({'path': str(source), 'password': 'fixture-secret-in-ram'}))
        pending = next(iter(self.bridge._pending_mandates.values()))
        ticket = approval._tickets[pending['wallet_operation']]
        with patch.object(approval.time, 'time', return_value=ticket.expires_at + 1):
            self.host._expire_wallet_operation(ticket.identifier, ticket.name)
        self.assertEqual(json.loads(self.runtime.snapshot())['ui_operation']['state'], 'expired')
        self.assertFalse(self.bridge._submit_bare_chat_approval('APPROVE', '@current', 'ws.tui.gpt'))
        self.assertEqual(pending['status'], 'EXPIRED')
        self.assertIsNone(ticket.callback); self.assertEqual(ticket.args, {})
        self.bridge._resident_chat.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
