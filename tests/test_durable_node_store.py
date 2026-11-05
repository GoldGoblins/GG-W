"""Protected owned profiles; temporary files only, never operator keys/state."""
import base64
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_node_store as store,gg_node_vault as vault,portable_wallet_vault as portable


def configuration():
    return {'label':'Owned node fixture','host':'127.0.0.1','port':0,'allowed_cidr':'127.0.0.0/8',
        'trusted_coordinator':None,'allow_test_tokens':False,'allow_dag_transactions':True}


class DurableStoreTests(unittest.TestCase):
    def setUp(self):
        self.unlock=portable.session('public node fixture passphrase');self.unlock.__enter__();self.addCleanup(self.unlock.__exit__,None,None,None)
        self.temp=tempfile.TemporaryDirectory(prefix='gg-durable-node-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)/'nodes';self.patch=patch.object(store,'ROOT',self.base);self.patch.start();self.addCleanup(self.patch.stop)
        self.profiles=[];self.addCleanup(self.close_profiles)

    def close_profiles(self):
        for profile in reversed(self.profiles):profile.close()

    def create(self,name='Fixture'):
        profile=store.NodeProfile.create(name,configuration());self.profiles.append(profile);return profile

    def reopen(self,name='Fixture'):
        profile=store.NodeProfile.open(name);self.profiles.append(profile);return profile

    def test_construction_has_no_keys_directories_or_network(self):
        with patch.object(store,'Keypair',side_effect=AssertionError('unexpected keys')):
            profile=store.NodeProfile('ReadOnly');profile.close()
        self.assertFalse(self.base.exists())
        for name in ('../escape','a/b','','1profile','x'*33):
            with self.assertRaisesRegex(ValueError,'PROFILE_NAME'):store.NodeProfile(name)

    def test_os_data_anchor_alias_is_canonical_but_private_profile_links_stay_forbidden(self):
        real=Path(self.temp.name)/'real-data';real.mkdir();alias=Path(self.temp.name)/'data-alias'
        def link(source,target):
            if store.os.name=='nt':
                result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(source),str(target)],
                    capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=5)
                self.assertEqual(result.returncode,0,'Owned NTFS junction fixture could not be created')
            else:source.symlink_to(target,target_is_directory=True)
        link(alias,real)
        self.assertEqual(store.default_root(alias),store.default_root(real))
        with patch.object(store,'ROOT',store.default_root(alias)):
            profile=self.create();public=profile.descriptor()['public_keys'];profile.close()
            resumed=self.reopen();self.assertEqual(resumed.descriptor()['public_keys'],public);resumed.close()
            link(store.ROOT/'Linked',store.ROOT/'Fixture')
            with self.assertRaisesRegex(ValueError,'MISSING_OR_LINK'):self.reopen('Linked')

    def test_encrypted_keys_keep_identity_and_binding_without_plaintext_files(self):
        profile=self.create();public=profile.descriptor()['public_keys'];seeds=[bytes(key) for key in profile.signers()[1]]
        profile.configure_pairing(port=16120)
        profile.close();resumed=self.reopen()
        self.assertEqual(resumed.descriptor()['public_keys'],public)
        self.assertEqual(resumed.descriptor()['port'],16120)
        self.assertTrue(resumed.snapshot()['restored']);self.assertFalse(resumed.snapshot()['canonical_finality'])
        resumed.close()
        for path in resumed.root.iterdir():
            if not path.is_file():continue
            raw=path.read_bytes()
            for private in seeds:
                self.assertFalse(private in raw,'Plaintext signing bytes reached a file')
                self.assertFalse(private.hex().encode() in raw,'Hex private bytes reached a file')
                self.assertFalse(base64.b64encode(private) in raw,'Base64 private bytes reached a file')

    def test_second_owner_and_accidental_recreation_are_rejected(self):
        profile=self.create()
        with self.assertRaisesRegex(ValueError,'PROFILE_IN_USE'):store.NodeProfile.open('Fixture')
        with self.assertRaisesRegex(ValueError,'EXISTS_USE_RESUME'):store.NodeProfile.create('Fixture',configuration())
        profile.close();self.reopen()

    def test_database_keeps_exclusive_ownership_between_commits(self):
        profile=self.create();profile.bind_session({'public_test_session':True})
        # Even a connection bypassing our friendly owner.lock cannot read or
        # become a second writer while the first profile owns the database.
        with closing(sqlite3.connect(profile.root/'node.sqlite3',timeout=0)) as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('SELECT value FROM metadata').fetchone()
        profile.close();self.reopen()

    def test_public_journal_and_signed_head_are_committed_together(self):
        profile=self.create();profile.bind_session({'public_test_session':True})
        profile.append('dag',[b'public-dag-record']);profile.append('token',[b'public-token-record1',b'public-token-record2'])
        profile.save_cursor('a'*64,1)
        expected=profile.snapshot();profile.close();resumed=self.reopen()
        self.assertEqual(list(resumed.records()),[('dag',b'public-dag-record'),('token',b'public-token-record1'),('token',b'public-token-record2')])
        self.assertEqual(resumed.snapshot()['counts'],{'dag':1,'token':2});self.assertEqual(resumed.snapshot()['bytes'],expected['bytes'])
        self.assertEqual(resumed.cursors(),{'a'*64:1})
        with self.assertRaisesRegex(ValueError,'NETWORK_ALREADY_BOUND'):resumed.bind_session({'different':True})
        with self.assertRaisesRegex(ValueError,'PROFILE_ALREADY_BOUND'):resumed.configure_pairing(port=16121)

    def test_corrupt_payload_or_deleted_tail_is_not_truncated_or_repaired(self):
        for action in ('modify','delete'):
            name=action.capitalize();profile=self.create(name);profile.bind_session({'public_test_session':True});profile.append('dag',[b'public-record'])
            root=profile.root;profile.close()
            with closing(sqlite3.connect(root/'node.sqlite3')) as db,db:
                if action=='modify':db.execute('UPDATE entries SET wire=? WHERE position=1',(b'tampered-record',))
                else:db.execute('DELETE FROM entries')
            before=(root/'node.sqlite3').read_bytes()
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'RECORD_HASH|HISTORY_MISMATCH'):self.reopen(name)
            self.assertTrue((root/'node.sqlite3').read_bytes()==before,'Invalid data was silently repaired')

    def test_missing_database_or_lease_does_not_recreate_an_identity(self):
        for filename in ('node.sqlite3','owner.lock'):
            name='Database' if filename.startswith('node') else 'Lease';profile=self.create(name);root=profile.root;profile.close()
            (root/filename).unlink()
            with self.assertRaisesRegex(ValueError,'MISSING'):self.reopen(name)
            self.assertFalse((root/filename).exists())

    def test_storage_failure_never_changes_the_committed_prefix_and_latches_writer(self):
        profile=self.create();profile.bind_session({'public_test_session':True})
        with patch.object(profile,'_commit',side_effect=OSError('synthetic storage failure')):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):profile.append('dag',[b'not-committed'])
        self.assertEqual(list(profile.records()),[]);self.assertEqual(profile.snapshot()['state'],'FAULT')
        with self.assertRaisesRegex(ValueError,'NOT_WRITABLE'):profile.append('dag',[b'not-published'])
        profile.close();self.assertEqual(list(self.reopen().records()),[])

    def test_unknown_commit_outcome_recovers_durable_data_without_republishing_an_old_nonce(self):
        profile=self.create();profile.bind_session({'public_test_session':True});commit=profile._commit
        def committed_then_failed():commit();raise OSError('synthetic lost completion')
        with patch.object(profile,'_commit',side_effect=committed_then_failed),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
            profile.append('dag',[b'durable-before-exposure'])
        profile.close();resumed=self.reopen()
        self.assertEqual(list(resumed.records()),[('dag',b'durable-before-exposure')])

    def test_protocol_fault_survives_restart(self):
        profile=self.create();profile.bind_session({'public_test_session':True});profile.latch_fault('GG_DAG_PRODUCER_EQUIVOCATION')
        profile.close();self.assertEqual(self.reopen().fault(),'GG_DAG_PRODUCER_EQUIVOCATION')

    def test_consumed_remote_plans_are_not_authorized_again_after_restart(self):
        profile=self.create();profile.claim_control('dag','a'*64);profile.claim_control('circle','b'*64)
        profile.close();resumed=self.reopen()
        self.assertEqual(resumed.used_controls(),{'dag':['a'*64],'circle':['b'*64]})
        with self.assertRaisesRegex(ValueError,'CONTROL_REPLAY'):resumed.claim_control('dag','a'*64)

    def test_unexpected_database_schema_and_tampered_head_are_rejected(self):
        for action in ('schema','head'):
            profile=self.create(action.capitalize());root=profile.root;profile.close()
            with closing(sqlite3.connect(root/'node.sqlite3')) as db,db:
                if action=='schema':db.execute('CREATE TABLE unexpected(data BLOB)')
                else:
                    raw=db.execute("SELECT value FROM metadata WHERE name='head'").fetchone()[0];value=store.unpack(raw)
                    value['body']['entries']=1;db.execute("UPDATE metadata SET value=? WHERE name='head'",(store.pack(value),))
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'SCHEMA|HEAD'):self.reopen(action.capitalize())

    def test_profile_cannot_be_cloned_to_a_different_path_and_unlocked(self):
        profile=self.create();root=profile.root;profile.close();shutil.copytree(root,self.base/'Copied')
        with self.assertRaisesRegex(ValueError,'VAULT_INVALID'):self.reopen('Copied')

    def test_posix_password_crypto_uses_existing_private_context_and_rejects_wrong_password(self):
        # Public fixture password, not an operator credential. Exercise the
        # portable provider on this host without pretending it ran on Android.
        with patch.object(vault,'provider',return_value='SCRYPT_AES256_GCM'):
            with portable.session('public node fixture passphrase'):profile=self.create('Portable')
            public=profile.descriptor()['public_keys'];profile.close()
            token=portable._password.set(None)
            try:
                with self.assertRaisesRegex(ValueError,'UNLOCK_REQUIRED'):self.reopen('Portable')
            finally:portable._password.reset(token)
            with portable.session('different public test passphrase'),self.assertRaisesRegex(ValueError,'WRONG_PASSWORD'):self.reopen('Portable')
            with portable.session('public node fixture passphrase'):resumed=self.reopen('Portable')
            self.assertEqual(resumed.descriptor()['public_keys'],public)


if __name__=='__main__':unittest.main()
