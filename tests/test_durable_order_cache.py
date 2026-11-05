"""Real disposable profiles, signed blocks and Sync failures. Certificates here
test structural storage binding only; SDK verification remains REQUIRED in
the caller and is exercised with real SDK processes by private acceptance.
"""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from backend import gg_node_store as store
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_parallel_dag import _tree,pack
from tests import test_lan_validator_runtime as fixtures


class DurableOrderCacheTests(unittest.TestCase):
    setUp=fixtures.ValidatorRuntimeTests.setUp
    cleanup=fixtures.ValidatorRuntimeTests.cleanup
    manager=fixtures.ValidatorRuntimeTests.manager
    network=fixtures.ValidatorRuntimeTests.network

    def prepare(self,count=35):
        first,second,phone,_=self.network();owner=first._peer;observer=phone._peer;order=[]
        for _ in range(count):
            block=owner._engine.produce_lan_test_block(owner._local_indices[0],1,owner._wire_limit);body=json.loads(block['wire'])['body']
            order.append({'hash':block['hash'],'index':len(order)+1,'producer_index':body['producer_index'],'sequence':body['sequence'],'transactions':1})
        return owner,observer,order

    def packet(self,peer,order):
        anchor=anchor_from_owned_peer(peer);height=len(order)
        state={'height':height,'state_root':'a'*64,'dag':{'blocks':height,'transactions':height,'order_root':_tree(order,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0]}}
        return {'schema':'gg.consensus.proof.v1',**anchor,'state':state,'signed_header':{'header':{'height':str(height+1)},'commit':{'block_id':{'hash':'b'*64}}}}

    def test_cache_is_append_only_atomic_detached_and_not_payload_admission_or_finality(self):
        owner,observer,order=self.prepare();profile=observer._profile;identity=profile.descriptor()['public_keys']
        packet=self.packet(owner,order[:32]);profile.save_verified_order(packet,order[:32])
        packet=self.packet(owner,order);self.assertTrue(profile.save_verified_order(packet,order))
        self.assertFalse(profile.save_verified_order(self.packet(owner,order[:32]),order[:32]))
        self.assertFalse(profile.save_verified_order(packet,order))
        self.assertEqual(profile._db.execute('SELECT count(*) FROM orders').fetchone()[0],35)
        self.assertEqual(profile.snapshot()['counts']['dag'],0);self.assertEqual(observer._engine.lan_evidence()['transactions'],0)
        self.assertIsNone(observer._proof_service._members);self.assertEqual(observer.snapshot()['canonical_finalized'],0)
        value=profile.verified_order();value['order'][0]['hash']='e'*64;self.assertEqual(profile.verified_order()['order'],order)
        name=profile.name;observer.stop();reopened=store.NodeProfile.open(name);self.addCleanup(reopened.close)
        self.assertEqual(reopened.descriptor()['public_keys'],identity);self.assertEqual(reopened.verified_order()['order'],order)
        self.assertEqual(reopened.verified_order()['packet'],packet)

    def test_unknown_sync_completion_has_old_or_new_exact_cache_without_false_publication(self):
        for after in (False,True):
            scope=Path(self.temp.name)/str(after)
            with patch.object(store,'ROOT',scope/'nodes'),patch.object(fixtures.validators,'ROOT',scope/'validators'):
                owner,observer,order=self.prepare(2);profile=observer._profile
                profile.save_verified_order(self.packet(owner,order[:1]),order[:1]);commit=profile._commit
                def failed():
                    if after:commit()
                    raise OSError('owned order cache completion loss')
                with patch.object(profile,'_commit',side_effect=failed),self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
                    profile.save_verified_order(self.packet(owner,order),order)
                with self.assertRaisesRegex(ValueError,'NOT_READABLE'):profile.verified_order()
                name=profile.name;observer.stop();reopened=store.NodeProfile.open(name);self.addCleanup(reopened.close)
                self.assertEqual(reopened.verified_order()['order'],order if after else order[:1]);reopened.close()
                for manager in self.managers:manager.stop()
                self.managers.clear()

    def test_changed_leaf_or_missing_row_is_not_repaired_and_bad_extension_cannot_commit(self):
        owner,observer,order=self.prepare(2);profile=observer._profile;profile.save_verified_order(self.packet(owner,order[:1]),order[:1])
        wrong=deepcopy(order);wrong[0]['hash']='e'*64
        with self.assertRaisesRegex(ValueError,'REWRITE'):profile.save_verified_order(self.packet(owner,wrong),wrong)
        packet=self.packet(owner,order);packet['state']['dag']['order_root']='e'*64
        with self.assertRaises(ValueError):profile.save_verified_order(packet,order)
        self.assertEqual(profile.verified_order()['order'],order[:1])
        name=profile.name;path=profile.root/'node.sqlite3';observer.stop()
        with closing(sqlite3.connect(path)) as db,db:db.execute('DELETE FROM orders')
        with self.assertRaises(ValueError):store.NodeProfile.open(name)

    def test_v2_schema_migration_preserves_identity_and_creates_no_verified_history(self):
        owner,observer,order=self.prepare(1);profile=observer._profile;name=profile.name;path=profile.root/'node.sqlite3';identity=profile.descriptor()['public_keys']
        observer.stop()
        with closing(sqlite3.connect(path)) as db,db:db.execute('DROP TABLE orders');db.execute('PRAGMA user_version=2')
        reopened=store.NodeProfile.open(name);self.addCleanup(reopened.close)
        self.assertEqual(reopened._schema_version,3);self.assertEqual(reopened.descriptor()['public_keys'],identity)
        self.assertIsNone(reopened.verified_order());self.assertEqual(reopened.snapshot()['counts']['dag'],0)

    def test_light_profile_guard_refuses_global_order_cache_before_any_write(self):
        owner,observer,order=self.prepare(1);profile=observer._profile
        with patch.dict(profile._meta['descriptor'],{'node_role':'light'}):
            with self.assertRaisesRegex(ValueError,'LIGHT_GLOBAL_HISTORY_FORBIDDEN'):
                profile.save_verified_order(self.packet(owner,order),order)
        self.assertEqual(profile._db.execute('SELECT count(*) FROM orders').fetchone()[0],0)
        self.assertIsNone(profile.verified_order())


if __name__=='__main__':unittest.main()
