"""Validator identity/availability policy; never starts or probes a real lab."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import crypto_lab as lab
from backend.crypto_contract import write_state_json


class CryptoLabOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gg-crypto-lab-policy-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        names = {'STATE_DIR': self.root, 'VALIDATOR_BIN': self.root / 'solana-test-validator.exe',
                 'LEDGER_DIR': self.root / 'local-ledger', 'PID_PATH': self.root / 'local-validator.pid',
                 'OWNER_PATH': self.root / 'local-validator-owner.json',
                 'LOG_PATH': self.root / 'local-validator.log'}
        for name, value in names.items():
            override = patch.object(lab, name, value)
            override.start(); self.addCleanup(override.stop)
        override = patch.object(lab, 'ensure_state_dir', return_value=self.root)
        override.start(); self.addCleanup(override.stop)
        lab.VALIDATOR_BIN.write_bytes(b'SYNTHETIC_NOT_EXECUTABLE')

    def owner(self, pid=4242, created=123.5):
        write_state_json(lab.OWNER_PATH, {'schema': 1, 'ledger': lab._canonical(lab.LEDGER_DIR),
            'validator': lab._canonical(lab.VALIDATOR_BIN), 'pid': pid, 'created': created})
        lab.PID_PATH.write_text(str(pid), encoding='utf-8')

    def args(self):
        return [str(lab.VALIDATOR_BIN), '--ledger', str(lab.LEDGER_DIR),
                '--rpc-port', '8899', '--bind-address', '127.0.0.1']

    def test_owned_identity_requires_configured_executable_ledger_port_and_creation(self):
        self.owner()
        with patch.object(lab, 'process_arguments', return_value=self.args()), patch.object(lab, '_creation_time', return_value=123.5):
            self.assertEqual(lab.running_pid(), 4242)
        mutations = []
        for index, value in [(0, str(self.root/'another-validator.exe')),
                             (2, str(self.root/'other-ledger')), (4, '8898'), (6, '0.0.0.0')]:
            args = self.args(); args[index] = value; mutations.append(args)
        mutations.append(self.args() + ['--ledger', str(lab.LEDGER_DIR)])
        for args in mutations:
            with patch.object(lab, 'process_arguments', return_value=args), patch.object(lab, '_creation_time', return_value=123.5):
                self.assertIsNone(lab.running_pid())
        with patch.object(lab, 'process_arguments', return_value=self.args()), patch.object(lab, '_creation_time', return_value=999.5):
            self.assertIsNone(lab.running_pid())

    def test_unmarked_matching_process_is_not_owned(self):
        lab.PID_PATH.write_text('4242', encoding='utf-8')
        with patch.object(lab, 'process_arguments', return_value=self.args()), patch.object(lab, '_creation_time', return_value=123.5):
            self.assertIsNone(lab.running_pid())

    def test_receipt_preserves_ownership_after_pid_file_publication_interruption(self):
        self.owner()
        lab.PID_PATH.unlink()
        with patch.object(lab, 'process_arguments', return_value=self.args()), patch.object(lab, '_creation_time', return_value=123.5):
            self.assertEqual(lab.running_pid(), 4242)
            with patch.object(lab, 'rpc_healthy', return_value=False):
                with self.assertRaisesRegex(RuntimeError, '^CRYPTO_LAB_LEDGER_REQUIRES_REVIEW$'):
                    lab.reset_ledger()

    def test_external_healthy_rpc_is_visible_without_claiming_lab_ownership(self):
        with patch.object(lab, 'rpc_healthy', return_value=True):
            status = lab.lab_status()
        self.assertEqual(status['label'], 'EXTERNAL RPC')
        self.assertFalse(status['running'])
        self.assertFalse(status['healthy'])
        self.assertFalse(status['owned'])
        self.assertTrue(status['rpc_healthy'])
        self.assertEqual(status['diagnostic'], 'CRYPTO_LAB_FOREIGN_RPC')

    def test_unavailable_binary_is_reported_explicitly(self):
        lab.VALIDATOR_BIN.unlink()
        with patch.object(lab, 'rpc_healthy', return_value=False), patch.object(lab.crypto_svm,'available',return_value=False):
            status = lab.lab_status()
        self.assertFalse(status['available'])
        self.assertEqual(status['label'], 'LAB UNAVAILABLE')
        self.assertEqual(status['diagnostic'], 'CRYPTO_VALIDATOR_MISSING')

    def test_start_never_takes_over_external_rpc(self):
        with patch.object(lab, 'rpc_healthy', return_value=True), patch.object(lab, '_spawn_validator', side_effect=AssertionError('Foreign port must not be reused')):
            self.assertEqual(lab.start_lab()['diagnostic'], 'CRYPTO_LAB_FOREIGN_RPC')

    def test_frozen_owned_lab_is_preserved_instead_of_automatic_reset(self):
        with patch.object(lab, 'running_pid', return_value=4242), patch.object(lab, 'wait_ready', return_value={'healthy': True}), patch.object(lab, 'current_slot', return_value=20), patch.object(lab, 'is_frozen', return_value=True), patch.object(lab, 'stop_lab', side_effect=AssertionError('No automatic stop')), patch.object(lab, 'reset_ledger', side_effect=AssertionError('No automatic ledger reset')):
            self.assertEqual(lab.start_lab()['diagnostic'], 'CRYPTO_LAB_FROZEN_REQUIRES_REVIEW')

    def test_stop_never_terminates_unowned_process_or_unit(self):
        lab.PID_PATH.write_text('4242', encoding='utf-8')
        with patch.object(lab, 'rpc_healthy', return_value=False), patch.object(lab, '_stop_systemd_unit', side_effect=AssertionError('Foreign unit')), patch.object(lab, 'terminate_process_tree', side_effect=AssertionError('Foreign process')):
            lab.stop_lab()
        self.assertEqual(lab.PID_PATH.read_text(encoding='utf-8'), '4242')

    def test_existing_unmarked_ledger_is_not_spawned_reset_or_changed(self):
        lab.LEDGER_DIR.mkdir()
        existing = lab.LEDGER_DIR / 'owned-fixture.dat'
        existing.write_bytes(b'PRESERVE')
        with patch.object(lab, '_spawn_systemd', side_effect=AssertionError('Do not spawn')), patch.object(lab, '_spawn_popen', side_effect=AssertionError('Do not spawn')):
            with self.assertRaisesRegex(RuntimeError, '^CRYPTO_LAB_LEDGER_REQUIRES_REVIEW$'):
                lab._spawn_validator()
        with patch.object(lab, 'rpc_healthy', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '^CRYPTO_LAB_LEDGER_REQUIRES_REVIEW$'):
                lab.reset_ledger()
        self.assertEqual(existing.read_bytes(), b'PRESERVE')


if __name__ == '__main__':
    unittest.main(argv=[__file__], verbosity=2)
