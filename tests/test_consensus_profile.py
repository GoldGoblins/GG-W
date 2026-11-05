"""Actual encrypted validator ownership, binding and uncertain-write recovery."""
from copy import deepcopy
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_consensus_profile as store,portable_wallet_vault as vault
from backend import gg_node_vault
from tests.test_lan_consensus_anchor import paired_peers


class ValidatorProfileTests(unittest.TestCase):
    def setUp(self):
        self.unlock=vault.session('disposable validator fixture password');self.unlock.__enter__();self.addCleanup(self.unlock.__exit__,None,None,None)
        self.temp=tempfile.TemporaryDirectory(prefix='gg-validator-profile-');self.addCleanup(self.temp.cleanup)
        self.scope=patch.object(store,'ROOT',Path(self.temp.name)/'validators');self.scope.start();self.addCleanup(self.scope.stop)
        self.peers=paired_peers(self);self.profiles=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for profile in reversed(self.profiles):profile.close()

    def profile(self,index=0):
        profile=store.ValidatorProfile.create('Validator'+str(index),self.peers[index%2],label='Owned validator '+str(index),p2p_port=22001+index)
        self.profiles.append(profile);return profile

    def network(self):
        profiles=[self.profile(index) for index in range(4)]
        bundle=self.peers[0].create_session([peer.public_invite() for peer in self.peers],enable_dag_transactions=True,
            consensus_invites=[profile.public_invite() for profile in profiles])
        return profiles,bundle

    def reopen(self,profile):
        name=profile.name;profile.close();opened=store.ValidatorProfile.open(name);self.profiles.append(opened);return opened

    def test_exact_owned_identity_and_immutable_anchor_survive_full_profile_close(self):
        profiles,bundle=self.network();profile=profiles[0];invite=profile.public_invite()
        anchor=profile.bind_anchor(bundle,self.peers[0].public_key)
        keys=[key.pubkey().hex() for key in profile.native_signers()]
        reopened=self.reopen(profile)
        self.assertEqual(reopened.public_invite(),invite);self.assertEqual(reopened.anchor(),anchor)
        self.assertEqual([key.pubkey().hex() for key in reopened.native_signers()],keys)
        self.assertEqual(reopened.bind_anchor(bundle,self.peers[0].public_key),anchor)
        changed=self.peers[0].create_session([peer.public_invite() for peer in self.peers],enable_dag_transactions=True,
            consensus_invites=[item.public_invite() for item in profiles])
        with self.assertRaisesRegex(ValueError,'ALREADY_BOUND'):reopened.bind_anchor(changed,self.peers[0].public_key)
        self.assertEqual(reopened.anchor(),anchor)

    def test_only_member_profile_can_bind_and_only_bound_profile_can_start(self):
        profiles,bundle=self.network();extra=self.profile(4)
        with self.assertRaisesRegex(ValueError,'NOT_A_MEMBER'):extra.bind_anchor(bundle,self.peers[0].public_key)
        with self.assertRaisesRegex(ValueError,'ANCHOR_REQUIRED'):profiles[0].claim_native_start()
        self.assertFalse(extra.snapshot()['native_started'])

    def test_kernel_lease_missing_database_and_recreation_fail_closed(self):
        profile=self.profile()
        with self.assertRaisesRegex(ValueError,'IN_USE'):store.ValidatorProfile.open(profile.name)
        with self.assertRaisesRegex(ValueError,'EXISTS_USE_RESUME'):self.profile()
        profile.close();path=profile.root/'validator.sqlite3';path.unlink()
        with self.assertRaises(ValueError):store.ValidatorProfile.open(profile.name)
        self.assertFalse(path.exists())

    def test_no_plaintext_key_bytes_and_copy_to_different_profile_path_rejected(self):
        profile=self.profile();private=[bytes(key) for key in profile._keys];profile.close()
        for path in profile.root.iterdir():
            if path.is_file():
                raw=path.read_bytes()
                for key in private:self.assertNotIn(key,raw)
        copied=Path(store.ROOT)/'Copied';shutil.copytree(profile.root,copied)
        with self.assertRaises(ValueError):store.ValidatorProfile.open('Copied')

    def test_changed_signed_metadata_never_becomes_a_new_identity(self):
        profile=self.profile();root=profile.root;profile.close()
        db=sqlite3.connect(root/'validator.sqlite3')
        try:
            from backend.gg_node_store import unpack,pack
            envelope=unpack(bytes(db.execute('SELECT record FROM state').fetchone()[0]))
            envelope['body']['native_started']=True
            db.execute('UPDATE state SET record=?',(pack(envelope),));db.commit()
        finally:db.close()
        with self.assertRaises(ValueError):store.ValidatorProfile.open(profile.name)

    def test_lost_startup_reply_requires_history_instead_of_reinitializing(self):
        profiles,bundle=self.network();profile=profiles[0];profile.bind_anchor(bundle,self.peers[0].public_key)
        self.assertTrue(profile.claim_native_start())
        reopened=self.reopen(profile)
        with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):reopened.claim_native_start()
        # A directory alone only selects RESUME. The native runtime must still
        # require its real genesis/database/signing history and reject absence.
        (reopened.root/'native').mkdir()
        self.assertFalse(reopened.claim_native_start())

    def test_failure_before_or_after_commit_latches_and_reopens_exact_anchor(self):
        for after in (False,True):
            with self.subTest(after_commit=after),patch.object(store,'ROOT',Path(self.temp.name)/('fault-'+str(after))):
                # Use separate roots because each profile is deliberately
                # immutable once created, including failed initialization.
                profiles,bundle=self.network()
                profile=profiles[0];commit=profile._commit
                def fail():
                    if after:commit()
                    raise sqlite3.OperationalError('owned injected failure')
                with patch.object(profile,'_commit',side_effect=fail):
                    with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):profile.bind_anchor(bundle,self.peers[0].public_key)
                self.assertEqual(profile.snapshot()['state'],'FAULT')
                with self.assertRaisesRegex(ValueError,'NOT_WRITABLE'):profile.claim_native_start()
                reopened=self.reopen(profile)
                self.assertEqual(reopened.anchor() is not None,after)

    def test_portable_password_protection_reopens_only_under_correct_private_context(self):
        with patch.object(gg_node_vault,'provider',return_value='SCRYPT_AES256_GCM'):
            profile=self.profile();invite=profile.public_invite();profile.close()
            with vault.session('a different disposable fixture password'):
                with self.assertRaises(ValueError):store.ValidatorProfile.open(profile.name)
            reopened=store.ValidatorProfile.open(profile.name);self.profiles.append(reopened)
            self.assertEqual(reopened.public_invite(),invite)

if __name__=='__main__':unittest.main()
