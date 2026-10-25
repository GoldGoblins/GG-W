"""Installed-tool and isolated signing checks; no user's wallet is opened."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from backend import crypto_contract, crypto_keys as keys
from backend.platform_files import mode_matches

# Published RFC 8032 section 7.1, TEST 2 (not a private user credential).
SEED = bytes.fromhex('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb')
PUBLIC = bytes.fromhex('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c')
SIGNATURE = bytes.fromhex('92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
                          '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')


class CryptoKeysTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gg-crypto-keys-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = patch.object(crypto_contract, 'STATE_DIR', self.root / 'state')
        override.start(); self.addCleanup(override.stop)

    def native_openssl(self):
        try:
            return keys.openssl_binary()
        except RuntimeError:
            self.skipTest('Optional installed OpenSSL is absent')

    @unittest.skipUnless(os.name == 'nt', 'Windows installed-tool discovery')
    def test_git_openssl_is_found_when_path_does_not_contain_it(self):
        with patch.dict(os.environ, {'PATH': ''}, clear=False):
            os.environ.pop('GG_OPENSSL_BINARY', None)
            found = keys.openssl_binary()
            self.assertTrue(Path(found).is_file())
            self.assertEqual(Path(found).name.lower(), 'openssl.exe')
            self.assertTrue(keys._run_openssl('version').startswith(b'OpenSSL '))

    def test_rfc8032_known_answer_survives_native_save_import_and_sign(self):
        self.native_openssl()
        pem = keys._pem_from_seed(SEED)
        pubkey = keys.save_test_keypair(SEED, PUBLIC, pem)
        self.assertEqual(pubkey, keys.b58encode(PUBLIC))
        self.assertTrue(mode_matches(keys.keypair_path(), 0o600))
        self.assertTrue(mode_matches(keys.pem_path(), 0o600))
        self.assertEqual(keys.sign_message(b'\x72'), SIGNATURE)
        imported = keys.import_solana_keypair(str(keys.keypair_path()))
        self.assertEqual(imported, pubkey)
        self.assertTrue(mode_matches(keys.live_keypair_path(), 0o600))
        self.assertEqual(keys.sign_message(b'\x72'), SIGNATURE)

    def test_malformed_keypairs_never_replace_a_previous_signer(self):
        destination = keys.live_keypair_path()
        destination.write_bytes(b'previous-owned-fixture')
        source = self.root / 'input.json'
        invalid = [list(range(63)), list(range(65)), [True] + list(range(1,64)),
                   [-1] + list(range(1,64)), [256] + list(range(1,64)),
                   ['0'] + list(range(1,64)), [0.0] + list(range(1,64))]
        for value in invalid:
            with self.subTest(kind=type(value[0]).__name__, length=len(value)):
                source.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '^CRYPTO_KEYPAIR_JSON$'):
                    keys.import_solana_keypair(str(source))
                self.assertEqual(destination.read_bytes(), b'previous-owned-fixture')

    def test_mismatched_seed_and_public_key_are_rejected(self):
        self.native_openssl()
        source = self.root / 'input.json'
        source.write_text(json.dumps(list(SEED + bytes(32))), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '^CRYPTO_KEYPAIR_JSON$'):
            keys.import_solana_keypair(str(source))
        self.assertFalse(keys.live_keypair_path().exists())

    def test_selected_watch_account_cannot_use_another_accounts_signer(self):
        self.native_openssl()
        signer = keys.save_test_keypair(SEED, PUBLIC, keys._pem_from_seed(SEED))
        other = keys.b58encode(bytes([7]) * 32)
        self.assertTrue(keys.signer_for(signer))
        self.assertFalse(keys.signer_for(other))
        self.assertFalse(keys.signer_for('invalid'))
        from backend import crypto_tx
        with patch.object(crypto_tx, 'load_test_pubkey', return_value=signer), patch.object(crypto_tx, 'sign_message', side_effect=AssertionError('Must not sign')):
            def forbidden_rpc(*args, **kwargs):
                raise AssertionError('Must not contact RPC')
            with self.assertRaisesRegex(RuntimeError, '^CRYPTO_SIGNER_MISMATCH$'):
                crypto_tx.send_self_transfer(forbidden_rpc, 1, expected_pubkey=other)

    def test_oversized_and_corrupt_stored_keypair_stay_unavailable(self):
        for content in (b' ' * (keys._KEYPAIR_LIMIT + 1), b'[]', b'\xff'):
            keys.keypair_path().write_bytes(content)
            self.assertEqual(keys.load_test_pubkey(), '')
            with self.assertRaisesRegex(ValueError, '^CRYPTO_KEYPAIR_JSON$'):
                keys.ensure_test_wallet()
            self.assertEqual(keys.keypair_path().read_bytes(), content)

    def test_failed_atomic_replacement_keeps_existing_key_and_removes_staging(self):
        target = keys.keypair_path()
        target.write_bytes(b'owned-previous')
        with patch.object(keys, 'atomic_replace', side_effect=PermissionError('synthetic')):
            with self.assertRaises(PermissionError):
                keys._write_private(target, b'owned-new')
        self.assertEqual(target.read_bytes(), b'owned-previous')
        self.assertEqual(list(target.parent.glob('*.new')), [])

    def test_openssl_timeout_has_no_child_output_or_environment_leak(self):
        tool = str(self.root / 'synthetic-openssl.exe')
        with patch.object(keys, 'openssl_binary', return_value=tool), patch.object(keys.subprocess, 'run',
                side_effect=subprocess.TimeoutExpired('owned', 5, output=b'synthetic-private-value')) as run:
            with patch.dict(os.environ, {'GG_TEST_PROVIDER_SECRET': 'synthetic-provider-value',
                                        'OPENSSL_CONF': 'untrusted-config'}):
                with self.assertRaisesRegex(RuntimeError, '^CRYPTO_OPENSSL_TIMEOUT$'):
                    keys._run_openssl('version')
        self.assertEqual(run.call_args.kwargs['timeout'], 5)
        self.assertNotIn('GG_TEST_PROVIDER_SECRET', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['env']['OPENSSL_CONF'], os.devnull)


if __name__ == '__main__':
    unittest.main(argv=[__file__], verbosity=2)
