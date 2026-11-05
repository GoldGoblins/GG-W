"""Real legacy originals and read-only replay; SDK seams are explicit."""
from copy import deepcopy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from backend import gg_network_archive as archive,gg_node_store as nodes,gg_node_vault as vault,gg_consensus as native,gg_lan_dag as lan
from backend.gg_dag_proof_sync import ProofExchange
from backend.gg_ed25519 import Keypair
from backend.platform_files import set_private_mode
from tests import test_lan_segmented_runtime as runtime_fixture,test_lan_proof_sync as proof_fixture


class NetworkArchiveTests(unittest.TestCase):
    cleanup=runtime_fixture.SegmentedRuntimeTests.cleanup
    manager=runtime_fixture.SegmentedRuntimeTests.manager
    network=runtime_fixture.SegmentedRuntimeTests.network

    def setUp(self):
        runtime_fixture.SegmentedRuntimeTests.setUp(self)
        self.stack.enter_context(patch.object(ProofExchange,'_serve_work'))
        self.stack.enter_context(patch.object(ProofExchange,'_client_work'))
        self.stack.enter_context(patch.object(lan.LanDagPeer,'_start_gossip'))
        self.managers3=self.network(segmented=False);self.owner=self.managers3[2]._peer
        self.directory=Path(self.temp.name)/'archives';self.directory.mkdir(mode=0o700);set_private_mode(self.directory,0o700)

    def original(self,count=3):
        return self.owner._engine.produce_lan_test_block(self.owner._local_indices[0],count,self.owner._wire_limit)

    def backup(self,name='original'):
        path=self.directory/(name+'.sqlite3')
        with closing(sqlite3.connect(path)) as target:self.owner._profile._db.backup(target)
        set_private_mode(path,0o600)
        return path

    def inspect(self,path,**kwargs):
        return archive.inspect(path,self.owner.public_key,hashlib.sha256(path.read_bytes()).hexdigest(),**kwargs)

    def reseal(self,path,change):
        with closing(sqlite3.connect(path)) as database, database:
            encoded={name:bytes(value) for name,value in database.execute('SELECT name,value FROM metadata')}
            envelope=nodes.unpack(encoded['head']);change(database,encoded,envelope)
            envelope['body']['binding']=nodes._raw_metadata_binding(encoded)
            envelope['signature']=self.owner._identity.sign_message(nodes.HEAD_DOMAIN+nodes.pack(envelope['body'])).hex()
            for name,value in encoded.items():
                if name!='head':database.execute('UPDATE metadata SET value=? WHERE name=?',(value,name))
            database.execute("UPDATE metadata SET value=? WHERE name='head'",(nodes.pack(envelope),))

    def test_real_five_thousand_originals_and_parent_replay_without_keys_or_writes(self):
        first=self.original(5000);second=self.original(1)
        self.assertIn(first['hash'],json.loads(second['wire'])['body']['parents'])
        path=self.backup();before=path.read_bytes()
        with patch.object(vault,'crypt',side_effect=AssertionError('archive reader must not decrypt keys')):
            result=self.inspect(path)
        self.assertEqual(result['original_records'],2);self.assertEqual(result['original_admitted_transactions'],5001)
        self.assertEqual(result['stored_SDK_certificates_verified'],0)
        self.assertTrue(result['original_DAG_admission_replayed'])
        for field in ('complete_canonical_history_replayed','native_transfer_history_replayed','network_freshness_asserted','signers_opened','writes_performed'):
            self.assertFalse(result[field])
        self.assertEqual(path.read_bytes(),before)

    def test_empty_legacy_profile_is_read_only_and_cannot_claim_certificates(self):
        result=self.inspect(self.backup())
        self.assertEqual(result['original_records'],0);self.assertEqual(result['original_admitted_transactions'],0)
        self.assertEqual(result['stored_SDK_certificates_verified'],0)

    def test_wrong_owner_and_file_pin_are_rejected(self):
        self.original();path=self.backup();pin=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'OWNER'):archive.inspect(path,Keypair().pubkey().hex(),pin)
        with self.assertRaisesRegex(ValueError,'HASH'):archive.inspect(path,self.owner.public_key,'0'*64)

    def test_hardlinked_file_and_linked_parent_are_rejected_before_sqlite(self):
        path=self.backup();other=self.directory/'second-link';os.link(path,other)
        with self.assertRaises(ValueError):self.inspect(path)
        other.unlink()
        with patch.object(archive,'is_link',side_effect=lambda value:Path(value)==self.directory),patch.object(archive.sqlite3,'connect') as connect:
            with self.assertRaisesRegex(ValueError,'PATH'):self.inspect(path)
            connect.assert_not_called()

    def test_cancellation_before_hash_and_during_replay_preserves_original(self):
        self.original();path=self.backup();before=path.read_bytes();calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls>=5:raise ValueError('PUBLIC_FIXTURE_CANCELLED')
        with self.assertRaisesRegex(ValueError,'CANCELLED'):self.inspect(path,check=check)
        self.assertEqual(path.read_bytes(),before)

    def test_authentic_storage_seal_cannot_substitute_for_original_signature_validation(self):
        block=self.original();invalid=json.loads(block['wire']);invalid['body']['created_at_ns']+=1
        self.owner._profile.append('dag',[nodes.pack(invalid)])
        with self.assertRaises(ValueError):self.inspect(self.backup())

    def test_signed_invalid_head_counter_types_and_metadata_are_rejected(self):
        self.original()
        for number,(field,value) in enumerate((('entries',True),('bytes',False),('counts',{'dag':True,'token':0}),('digest','z'*64))):
            with self.subTest(field=field):
                path=self.backup('bad'+str(number))
                self.reseal(path,lambda database,encoded,envelope:envelope['body'].__setitem__(field,value))
                with self.assertRaises(ValueError):self.inspect(path)
        path=self.backup('bad-controls')
        self.reseal(path,lambda database,encoded,envelope:encoded.__setitem__('controls',nodes.pack({'dag':['a'*64,'a'*64],'circle':[]})))
        with self.assertRaises(ValueError):self.inspect(path)

    def test_unbound_order_rows_and_unknown_metadata_cannot_hide_in_signed_container(self):
        self.original();path=self.backup()
        with closing(sqlite3.connect(path)) as database, database:database.execute('INSERT INTO orders VALUES(?,?,?)',(1,b'{}','a'*64))
        with self.assertRaises(ValueError):self.inspect(path)
        path=self.backup('unknown')
        with closing(sqlite3.connect(path)) as database, database:database.execute('INSERT INTO metadata VALUES(?,?)',('caller_verified',b'true'))
        with self.assertRaises(ValueError):self.inspect(path)

    def test_structural_cached_floor_must_pass_separate_native_SDK_verifier(self):
        self.original();packet=proof_fixture.ProofFloorTests.packet(self,self.owner)
        self.owner._profile.save_consensus_certificate(packet);path=self.backup()
        with patch.object(native,'_installed_binary',return_value=Path('public-test-only')),patch.object(native,'_validate_binary_at',return_value=None),\
                patch.object(native,'_verify_public',side_effect=ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')) as verifier:
            with self.assertRaisesRegex(ValueError,'CERTIFICATE_INVALID'):self.inspect(path)
        verifier.assert_called_once();self.assertEqual(verifier.call_args.args[0],packet)


if __name__=='__main__':unittest.main()
