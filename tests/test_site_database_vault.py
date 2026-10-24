"""Vault behavior uses constant errors and one isolated real Windows record."""
from __future__ import annotations

import ctypes
import hmac
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import site_database_vault as vault


class FakeAPI:
    def __init__(self):
        self.records = {}
        self.buffers = []
        self.fail = ''
        self.freed = 0
        self.last_blob = None

    def CredWriteW(self, pointer, flags):
        if self.fail == 'write':
            ctypes.set_last_error(5)
            return 0
        row = ctypes.cast(pointer, ctypes.POINTER(vault._CREDENTIALW)).contents
        self.last_blob = row.CredentialBlob
        self.records[row.TargetName] = (ctypes.string_at(row.CredentialBlob, row.CredentialBlobSize), row.UserName, row.Persist)
        return 1

    def CredReadW(self, target, kind, flags, output):
        if self.fail == 'read' or target not in self.records:
            ctypes.set_last_error(5 if self.fail == 'read' else 1168)
            return 0
        data, user, persist = self.records[target]
        blob = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        row = vault._CREDENTIALW()
        row.Type = kind
        row.TargetName = target
        row.UserName = user
        row.Persist = persist
        row.CredentialBlobSize = len(data)
        row.CredentialBlob = ctypes.cast(blob, vault._LPBYTE)
        self.buffers.append((blob, row))
        result = ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(vault._CREDENTIALW)))
        result[0] = ctypes.pointer(row)
        return 1

    def CredFree(self, pointer):
        self.freed += 1

    def CredDeleteW(self, target, kind, flags):
        if self.fail == 'delete':
            ctypes.set_last_error(5)
            return 0
        if target not in self.records:
            ctypes.set_last_error(1168)
            return 0
        del self.records[target]
        return 1


@unittest.skipUnless(os.name == 'nt', 'Windows Credential Manager API')
class SiteDatabaseVaultTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='gg-db-vault-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_real_current_user_round_trip_update_and_delete(self):
        # No real application target is read or modified. Values remain only
        # in RAM and the Windows vault and never appear in assertion messages.
        secret = secrets.token_urlsafe(48)
        replacement = secrets.token_urlsafe(48)
        self.assertIsNone(vault.get_secret(self.root))
        try:
            vault.put_secret(self.root, secret)
            observed = vault.get_secret(self.root)
            self.assertTrue(isinstance(observed, str) and hmac.compare_digest(observed, secret))
            vault.put_secret(self.root, replacement)
            observed = vault.get_secret(self.root)
            self.assertTrue(isinstance(observed, str) and hmac.compare_digest(observed, replacement))
        finally:
            vault.delete_secret(self.root)
        self.assertIsNone(vault.get_secret(self.root))
        vault.delete_secret(self.root)
        self.assertFalse(list(self.root.iterdir()))

    def test_instance_binding_and_local_machine_persistence(self):
        api = FakeAPI()
        another = self.root / 'another'
        secret = secrets.token_urlsafe(48)
        with patch.object(vault, '_api', return_value=api):
            vault.put_secret(self.root, secret)
            self.assertIsNone(vault.get_secret(another))
            observed = vault.get_secret(self.root)
            self.assertTrue(isinstance(observed, str) and hmac.compare_digest(observed, secret))
            self.assertEqual(next(iter(api.records.values()))[2], 2)
            self.assertEqual(api.freed, 1)
            self.assertTrue(all(value == 0 for value in api.buffers[-1][0]))

    def test_failed_win32_calls_return_constant_codes_without_values(self):
        secret = secrets.token_urlsafe(48)
        api = FakeAPI()
        with patch.object(vault, '_api', return_value=api):
            for mode, function, args, expected in (
                ('write', vault.put_secret, (self.root, secret), 'SITE_DATABASE_VAULT_WRITE_FAILED'),
                ('read', vault.get_secret, (self.root,), 'SITE_DATABASE_VAULT_READ_FAILED'),
                ('delete', vault.delete_secret, (self.root,), 'SITE_DATABASE_VAULT_DELETE_FAILED')):
                api.fail = mode
                with self.subTest(operation=mode), self.assertRaises(RuntimeError) as caught:
                    function(*args)
                self.assertEqual(str(caught.exception), expected)

    def test_invalid_blob_is_freed_and_cannot_be_returned(self):
        api = FakeAPI()
        target = vault._target(self.root)
        api.records[target] = (b'not-a-supported-record', 'root', 2)
        with patch.object(vault, '_api', return_value=api), self.assertRaisesRegex(RuntimeError, '^SITE_DATABASE_VAULT_RECORD_INVALID$'):
            vault.get_secret(self.root)
        self.assertEqual(api.freed, 1)
        self.assertTrue(all(value == 0 for value in api.buffers[-1][0]))

    def test_invalid_secret_is_rejected_before_any_api_call(self):
        with patch.object(vault, '_api') as api:
            for secret in ('', '\0', '\ud800', 'x' * vault._MAX_BLOB, None):
                with self.subTest(invalid_type=type(secret).__name__), self.assertRaisesRegex(ValueError, '^SITE_DATABASE_VAULT_SECRET_INVALID$'):
                    vault.put_secret(self.root, secret)
            api.assert_not_called()

    def test_linked_remote_relative_and_file_targets_are_rejected(self):
        ordinary_file = self.root / 'file'
        ordinary_file.write_text('owned fixture', encoding='utf-8')
        with patch.object(vault, '_api') as api:
            for target in ('relative', '\\\\remote.invalid\\share\\db', ordinary_file):
                with self.subTest(kind=type(target).__name__), self.assertRaisesRegex(ValueError, '^SITE_DATABASE_VAULT_TARGET_INVALID$'):
                    vault.get_secret(target)
            with patch.object(vault, 'is_link', side_effect=lambda path: path == self.root):
                with self.assertRaisesRegex(ValueError, '^SITE_DATABASE_VAULT_TARGET_INVALID$'):
                    vault.put_secret(self.root, secrets.token_urlsafe(48))
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
