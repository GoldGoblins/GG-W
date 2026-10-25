"""Interruption and bounded-history regressions using a separate state directory."""
from pathlib import Path
import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import crypto_contract as contract
from backend.crypto_keys import b58encode
from backend.platform_files import mode_matches


class CryptoStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gg-crypto-state-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.object(contract, 'STATE_DIR', self.root)
        override.start(); self.addCleanup(override.stop)

    def test_base58_addresses_must_decode_to_exactly_32_bytes(self):
        valid = ['1' * 32, b58encode(bytes([255]) * 32), b58encode(bytes(range(32)))]
        for address in valid:
            self.assertEqual(contract.validate_pubkey(address), address)
        for address in ['2' * 32, 'z' * 44, '1' * 33, '0' * 32]:
            with self.subTest(address_length=len(address)):
                with self.assertRaisesRegex(ValueError, '^CRYPTO_PUBKEY_INVALID$'):
                    contract.validate_pubkey(address)

    def test_interrupted_network_write_retains_previous_private_record(self):
        contract.save_network('testnet')
        path = self.root / 'network.json'
        previous = path.read_bytes()
        with patch.object(contract, 'atomic_replace', side_effect=PermissionError('synthetic publish fault')):
            with self.assertRaises(PermissionError):
                contract.save_network('mainnet')
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(contract.load_network(), 'testnet')
        self.assertTrue(mode_matches(path, 0o600))
        self.assertEqual(list(self.root.glob('*.new')), [])

    def test_interrupted_wallet_write_retains_active_wallet(self):
        key = '1' * 32
        contract.save_wallet(key, 17, 'testnet')
        with patch.object(contract, 'atomic_replace', side_effect=PermissionError('synthetic publish fault')):
            with self.assertRaises(PermissionError):
                contract.save_wallet(key, 19, 'mainnet')
        self.assertEqual(contract.load_wallet()['balance_lamports'], 17)
        self.assertEqual(contract.load_wallet()['network'], 'testnet')

    def test_nonfinite_serialization_never_replaces_wallet(self):
        contract.save_wallet('1' * 32, 17, 'testnet')
        with self.assertRaises(ValueError):
            contract.save_wallet('1' * 32, float('nan'), 'mainnet')
        self.assertEqual(contract.load_wallet()['balance_lamports'], 17)

    def test_disconnect_failure_is_visible_and_preserves_the_active_wallet(self):
        contract.save_wallet('1' * 32, 17, 'testnet')
        previous = contract.wallet_path().read_bytes()
        with patch.object(Path, 'unlink', side_effect=PermissionError('synthetic sharing fault')):
            with self.assertRaises(PermissionError):
                contract.clear_wallet()
        self.assertEqual(contract.wallet_path().read_bytes(), previous)

    def test_concurrent_account_publication_retains_each_address(self):
        addresses = [b58encode(bytes([index]) * 32) for index in range(1, 13)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(contract.remember_account, addresses))
        self.assertEqual({item['pubkey'] for item in contract.load_accounts()}, set(addresses))
        self.assertTrue(mode_matches(self.root / 'accounts.json', 0o600))

    def test_ledger_reads_bounded_tail_and_ignores_incomplete_or_bad_utf8(self):
        path = contract.ledger_path()
        path.write_bytes(b'{"old":"' + b'x' * (contract._LEDGER_READ_BYTES + 100) + b'"}\n'
                         + b'{"sequence":1}\n\xff\n{"sequence":2}\n{"partial":')
        # A whole-file text read was the previous unbounded status-path behavior.
        with patch.object(Path, 'read_text', side_effect=AssertionError('Unbounded ledger read')):
            self.assertEqual(contract.read_ledger(4), [{'sequence': 1}, {'sequence': 2}])

    def test_proof_publish_fault_preserves_previous_complete_state(self):
        contract.mark_proven('lab')
        previous = contract.proven_path().read_bytes()
        with patch.object(contract, 'atomic_replace', side_effect=PermissionError('synthetic publish fault')):
            with self.assertRaises(PermissionError):
                contract.mark_proven('airdrop')
        self.assertEqual(contract.proven_path().read_bytes(), previous)
        self.assertTrue(contract.load_proven()['lab'])
        self.assertFalse(contract.load_proven()['airdrop'])


if __name__ == '__main__':
    unittest.main(argv=[__file__], verbosity=2)
