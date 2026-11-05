"""Actual encrypted, leased observer ownership and authenticated public grants."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch

from backend import gg_observer_profile as store,gg_native_observer as grants
from backend import gg_node_vault
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import pack
from backend.gg_node_store import unpack
from tests import test_consensus_profile as fixture


class NativeObserverProfileTests(unittest.TestCase):
    cleanup=fixture.ValidatorProfileTests.cleanup
    profile=fixture.ValidatorProfileTests.profile
    network=fixture.ValidatorProfileTests.network

    def setUp(self):
        fixture.ValidatorProfileTests.setUp(self)
        self.observer_root=Path(self.temp.name)/'observers'
        scope=patch.object(store,'ROOT',self.observer_root);scope.start();self.addCleanup(scope.stop)
        self.validators,self.bundle=self.network()
        for peer in self.peers:peer.install_session(self.bundle,_start_gossip=False)

    def observer(self,index=0,peer=None,slot=0):
        profile=store.ObserverProfile.create('Observer'+str(index),peer or self.peers[2],
            label='Termux full observer '+str(index),p2p_port=23001+index,producer_slot=slot)
        self.profiles.append(profile);return profile

    def reopen_observer(self,profile):
        profile.close();opened=store.ObserverProfile.open(profile.name);self.profiles.append(opened);return opened

    def test_only_one_protected_p2p_key_and_no_validator_or_account_signer(self):
        profile=self.observer();key=profile.native_node_signer();grant=profile.public_grant()
        self.assertNotIsInstance(profile,ValidatorProfile)
        self.assertFalse(hasattr(profile,'native_signers'));self.assertFalse(hasattr(profile,'index'))
        self.assertEqual(set(profile._body['protected_key']),{'public','ciphertext'})
        self.assertEqual(key.pubkey().hex(),grant['body']['node_key'])
        self.assertEqual(profile.snapshot()['voting_power'],0);self.assertFalse(profile.snapshot()['consensus_signing'])
        self.assertNotIn(grant['body']['node_key'],profile.anchor()['genesis']['validators'])
        reopened=self.reopen_observer(profile)
        self.assertEqual(reopened.public_grant(),grant);self.assertEqual(bytes(reopened.native_node_signer()),bytes(key))
        self.assertEqual(reopened.anchor()['genesis']['membership'],self.bundle['body']['consensus'])

    def test_kernel_lease_exclusive_and_absent_database_not_recreated(self):
        profile=self.observer()
        with self.assertRaisesRegex(ValueError,'IN_USE'):store.ObserverProfile.open(profile.name)
        with self.assertRaisesRegex(ValueError,'EXISTS_USE_RESUME'):self.observer()
        profile.close();path=profile.root/'observer.sqlite3';path.unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):store.ObserverProfile.open(profile.name)
        self.assertFalse(path.exists())

    def test_invalid_endpoint_and_slot_have_no_disk_effect(self):
        peer=self.peers[2]
        for options in ({'p2p_port':peer.port},{'p2p_port':22001},{'p2p_port':23009,'producer_slot':True}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                store.ObserverProfile.create('Invalid',peer,label='invalid',**options)
        self.assertFalse(self.observer_root.exists())

    def test_registered_producer_must_belong_to_the_signed_transport_owner(self):
        peer=self.peers[2]
        with self.assertRaisesRegex(ValueError,'GRANT_INVALID'):
            grants.make_grant(Keypair(),peer._identity,self.peers[0]._local_keys[0],self.bundle,self.peers[0].public_key,
                label='mismatched valid signatures',host=peer.host,p2p_port=23010)

    def test_owner_address_and_node_roles_are_pinned_even_with_new_signatures(self):
        profile=self.observer();original=profile.public_grant();peer=self.peers[2]
        for change in ({'host':'127.0.0.2'},{'node_key':self.validators[0].public_invite()['body']['node_key']},
                {'producer_key':self.peers[0]._local_keys[0].pubkey().hex()},{'genesis_hash':'a'*64}):
            grant=deepcopy(original);grant['body'].update(change)
            for role,key in zip(('node','owner','producer'),(profile.native_node_signer(),peer._identity,peer._local_keys[0])):
                grant[role+'_signature']=key.sign_message(grants.DOMAINS[role]+pack(grant['body'])).hex()
            with self.subTest(fields=tuple(change)),self.assertRaises(ValueError):
                grants.validate_grant(grant,self.bundle,self.peers[0].public_key)
        self.assertEqual(profile.public_grant(),original)

    def test_each_signature_and_domain_is_required(self):
        original=self.observer().public_grant()
        for role in ('node','owner','producer'):
            for replacement in ('00'*64,original[('owner' if role=='node' else 'node')+'_signature']):
                grant=deepcopy(original);grant[role+'_signature']=replacement
                with self.subTest(role=role),self.assertRaises(ValueError):
                    grants.validate_grant(grant,self.bundle,self.peers[0].public_key)

    def test_capability_document_bounded_and_duplicate_delegations_reject(self):
        first=self.observer().public_grant();second=self.observer(1,slot=1).public_grant()
        document=grants.admission_document([second,first],self.bundle,self.peers[0].public_key)
        self.assertEqual(document['grants'],sorted([first,second],key=lambda row:row['body']['producer_key']))
        before=deepcopy(self.bundle)
        for candidates in ([first,first],[first]*7):
            with self.assertRaises(ValueError):grants.admission_document(candidates,self.bundle,self.peers[0].public_key)
        duplicate=self.observer(2).public_grant()
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):
            grants.admission_document([first,duplicate],self.bundle,self.peers[0].public_key)
        self.assertEqual(self.bundle,before);self.assertEqual(len(self.observer(3,peer=self.peers[0]).anchor()['genesis']['validators']),4)

    def test_native_start_intent_commits_and_missing_history_never_becomes_fresh(self):
        profile=self.observer();self.assertTrue(profile.claim_native_start());profile=self.reopen_observer(profile)
        with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):profile.claim_native_start()
        (profile.root/'native').mkdir();self.assertFalse(profile.claim_native_start())

    def test_write_failure_before_and_after_commit_latches_and_reopen_is_deterministic(self):
        for after in (False,True):
            profile=self.observer(1 if after else 0);commit=profile._commit
            def fail():
                if after:commit()
                raise sqlite3.OperationalError('owned injected storage boundary')
            with patch.object(profile,'_commit',side_effect=fail):
                with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):profile.claim_native_start()
            self.assertEqual(profile.snapshot()['state'],'FAULT')
            with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):profile.native_node_signer()
            with self.assertRaisesRegex(ValueError,'NOT_WRITABLE'):profile.claim_native_start()
            reopened=self.reopen_observer(profile);self.assertEqual(reopened.snapshot()['native_started'],after)

    def test_no_plaintext_private_bytes_or_cross_path_copy(self):
        profile=self.observer();private=bytes(profile.native_node_signer());profile.close()
        for path in profile.root.iterdir():
            if path.is_file():self.assertNotIn(private,path.read_bytes())
        shutil.copytree(profile.root,self.observer_root/'Copied')
        with self.assertRaises(ValueError):store.ObserverProfile.open('Copied')

    def test_changed_signed_metadata_is_never_resealed_or_adopted(self):
        profile=self.observer();profile.close()
        with closing(sqlite3.connect(profile.root/'observer.sqlite3')) as database:
            envelope=unpack(bytes(database.execute('SELECT record FROM state').fetchone()[0]))
            envelope['body']['native_started']=True
            database.execute('UPDATE state SET record=?',(pack(envelope),))
            database.commit()
        with self.assertRaises(ValueError):store.ObserverProfile.open(profile.name)

    def test_real_portable_vault_requires_the_original_password_and_role(self):
        from backend import portable_wallet_vault
        with patch.object(gg_node_vault,'provider',return_value='SCRYPT_AES256_GCM'):
            profile=self.observer();grant=profile.public_grant();profile.close()
            with portable_wallet_vault.session('another disposable test password'):
                with self.assertRaises(ValueError):store.ObserverProfile.open(profile.name)
            reopened=self.reopen_observer(profile);self.assertEqual(reopened.public_grant(),grant)
            protected=reopened._body['protected_key']
            import base64
            with self.assertRaises(ValueError):gg_node_vault.crypt(base64.b64decode(protected['ciphertext']),
                protected['public'],'consensus_node',reopened.root,decrypt=True,storage='SCRYPT_AES256_GCM')

    def native_validator_root(self,profile):
        profile.bind_anchor(self.bundle,self.peers[0].public_key);profile.claim_native_start()
        root=profile.root/'native';root.mkdir(mode=0o700)
        from backend.platform_files import set_private_mode
        set_private_mode(root,0o700)
        (root/'gg-public-genesis.json').write_bytes(pack(profile.anchor()['genesis']))
        return root

    def test_validator_admission_persists_before_publication_and_keeps_quorum_unchanged(self):
        validator=self.validators[0];validator.bind_anchor(self.bundle,self.peers[0].public_key)
        grant=self.observer().public_grant();anchor=validator.anchor()
        document=validator.admit_observer(grant)
        self.assertFalse((validator.root/'native').exists())
        self.assertEqual(validator.admit_observer(grant),document)
        root=self.native_validator_root(validator);sentinel=root/'signer-state-fixture';sentinel.write_bytes(b'unchanged public fixture')
        validator.publish_native_admissions()
        self.assertEqual((root/'gg-observer-admissions.json').read_bytes(),pack(document))
        self.assertEqual(validator.anchor(),anchor);self.assertEqual(len(anchor['genesis']['validators']),4)
        self.assertEqual(sentinel.read_bytes(),b'unchanged public fixture')
        name=validator.name;validator.close();opened=ValidatorProfile.open(name);self.profiles.append(opened)
        self.assertEqual(opened._body['admitted_observers'],[grant]);opened.publish_native_admissions()

    def test_failed_publication_reopens_exact_committed_grant_and_repairs_only_public_cache(self):
        validator=self.validators[0];root=self.native_validator_root(validator);grant=self.observer().public_grant()
        with patch.object(grants,'publish_admissions',side_effect=OSError('owned injected cache failure')):
            with self.assertRaises(OSError):validator.admit_observer(grant)
        self.assertEqual(validator._body['admitted_observers'],[grant]);self.assertFalse((root/'gg-observer-admissions.json').exists())
        name=validator.name;validator.close();opened=ValidatorProfile.open(name);self.profiles.append(opened)
        opened.publish_native_admissions();self.assertEqual(unpack((root/'gg-observer-admissions.json').read_bytes())['grants'],[grant])

    def test_publication_rejects_wrong_native_root_without_touching_it(self):
        validator=self.validators[0];root=self.native_validator_root(validator);grant=self.observer().public_grant()
        marker=root/'gg-public-genesis.json';marker.write_bytes(b'wrong root')
        with self.assertRaisesRegex(ValueError,'NATIVE_ROOT'):validator.admit_observer(grant)
        self.assertEqual(marker.read_bytes(),b'wrong root');self.assertFalse((root/'gg-observer-admissions.json').exists())

    def test_duplicate_producer_grant_never_replaces_the_first_durable_admission(self):
        validator=self.validators[0];validator.bind_anchor(self.bundle,self.peers[0].public_key)
        first=self.observer().public_grant();duplicate=self.observer(1).public_grant()
        validator.admit_observer(first)
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):validator.admit_observer(duplicate)
        self.assertEqual(validator._body['admitted_observers'],[first])


if __name__=='__main__':unittest.main()
