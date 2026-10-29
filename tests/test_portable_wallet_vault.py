"""Authenticated ciphertext and exact RFC8032 compatibility, fixture keys only."""
import json
from pathlib import Path
import tempfile
import unittest
import ctypes
import os
from unittest.mock import patch

from backend import portable_wallet_vault as vault
from backend.gg_ed25519 import Keypair


class PortableVaultTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows DPAPI ABI cache')
    def test_windows_vault_reuses_ffi_types_during_actual_encrypt_decrypt(self):
        from backend import wallet_vault,omni_assets
        with tempfile.TemporaryDirectory() as temporary,patch.object(omni_assets,'ROOT',Path(temporary)):
            data=bytes(range(64));public='synthetic public fixture'
            encrypted=wallet_vault._crypt(data,public)
            self.assertEqual(wallet_vault._crypt(encrypted,public,True),data)
            before=set(ctypes._pointer_type_cache)
            for _ in range(100):
                encoded=wallet_vault._crypt(data,public)
                self.assertEqual(wallet_vault._crypt(encoded,public,True),data)
            self.assertEqual(set(ctypes._pointer_type_cache),before)
    def test_ed25519_rfc8032_and_existing_sdk_are_identical(self):
        from solders.keypair import Keypair as ExistingKeypair
        seed=bytes(range(32))
        portable=Keypair.from_seed(seed);existing=ExistingKeypair.from_seed(seed)
        self.assertEqual(portable.pubkey(),bytes(existing.pubkey()))
        self.assertEqual(bytes(portable),bytes(existing))
        for message in (b'',b'GG canonical transaction',bytes(range(256))):
            self.assertEqual(portable.sign_message(message),bytes(existing.sign_message(message)))
        self.assertNotIn(seed.hex(),repr(portable))

    def test_ciphertext_authentication_wrong_password_context_and_no_secret_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);pair=Keypair();raw=bytes(pair);public=pair.pubkey().hex()
            with self.assertRaisesRegex(ValueError,'WALLET_UNLOCK_REQUIRED'):vault.crypt(raw,public,root)
            with vault.session('only synthetic password 123'):
                encrypted=vault.crypt(raw,public,root)
                self.assertEqual(vault.crypt(encrypted,public,root,True),raw)
                self.assertNotEqual(vault.crypt(raw,public,root),encrypted)
                for wrong_root,wrong_public in ((root/'elsewhere',public),(root,'0'*64)):
                    with self.assertRaisesRegex(ValueError,'WRONG_PASSWORD'):vault.crypt(encrypted,wrong_public,wrong_root,True)
            self.assertIsNone(vault._password.get())
            self.assertNotIn(raw,encrypted);self.assertNotIn(raw.hex().encode(),encrypted)
            with vault.session('a different synthetic password'):
                with self.assertRaisesRegex(ValueError,'WRONG_PASSWORD'):vault.crypt(encrypted,public,root,True)
            self.assertEqual(list(root.iterdir()),[])

    def test_limits_and_authenticated_tampering(self):
        with vault.session('only synthetic password 456'):
            root=Path.cwd();encoded=vault.crypt(bytes(Keypair()),'public',root)
            changed=json.loads(encoded);changed['tag']='A'*24
            for invalid in (b'x'*4097,b'[]',b'{}',json.dumps(changed).encode(),encoded[:-1]+b',"kdf":"other"}'):
                with self.assertRaisesRegex(ValueError,'VAULT_'):vault.crypt(invalid,'public',root,True)
        for password in ('short',None,'x'*257):
            with self.assertRaisesRegex(ValueError,'PASSWORD_LENGTH'):
                with vault.session(password):pass


if __name__=='__main__':unittest.main()
