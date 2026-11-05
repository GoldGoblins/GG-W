"""Actual signed payloads and encrypted disposable journals; no operator state.

Checkpoint selection below uses structural genesis metadata, not a simulated
quorum/finality claim. The four-SDK process suite verifies real certificates.
"""
from copy import deepcopy
import json
import threading
import time
import unittest
from unittest.mock import patch

from backend.gg_dag_checkpoint import select_checkpoint,restore_checkpoint,source_from_owned_peer
from backend.gg_parallel_dag import HOT_PAYLOAD_BYTES,HOT_PAYLOAD_RECORDS,pack
from tests import test_durable_lan_node as fixtures


class PayloadArchiveTests(unittest.TestCase):
    setUp=fixtures.DurableLanNodeTests.setUp
    cleanup=fixtures.DurableLanNodeTests.cleanup
    peer=fixtures.DurableLanNodeTests.peer
    network=fixtures.DurableLanNodeTests.network
    resume=fixtures.DurableLanNodeTests.resume
    block=fixtures.DurableLanNodeTests.block

    def cold(self,node):
        node._engine._hot_payload_limit=0
        result=self.block(node)
        self.assertIsNone(node._engine._records[result['hash']]['wire'])
        self.assertIsNone(node._engine._records[result['hash']]['body'])
        return result

    def test_real_35000_tx_cross_byte_cache_boundary_and_reopen_exact_history(self):
        owner=self.network()[0];engine=owner._engine
        first=None
        for _ in range(7):
            block=self.block(owner,5000)
            if first is None:first=block
        self.assertGreater(engine.stored_wire_bytes(),HOT_PAYLOAD_BYTES)
        self.assertLessEqual(engine._hot_payload_bytes,HOT_PAYLOAD_BYTES)
        self.assertLessEqual(len(engine._hot_payloads),HOT_PAYLOAD_RECORDS)
        self.assertIsNone(engine._records[first['hash']]['wire'])
        self.assertTrue(all(row['body'] is None for row in engine._records.values() if row['rank']))
        self.assertEqual(engine.public_proposal(first['hash']),first['wire'])
        self.assertEqual(engine.lan_evidence()['transactions'],35000)
        self.assertEqual(engine.snapshot()['admission']['stored_bytes'],engine.stored_wire_bytes())
        evidence=engine.lan_evidence();accounts=deepcopy(engine._preview_state)
        resumed=self.resume(owner);engine=resumed._engine
        self.assertEqual(engine.lan_evidence(),evidence)
        self.assertEqual(engine._preview_state,accounts)
        self.assertEqual(engine.public_proposal(first['hash']),first['wire'])
        self.assertIsNone(engine._records[first['hash']]['wire'])
        self.assertEqual(json.loads(self.block(resumed,1)['wire'])['body']['transactions'][0]['body']['nonce'],35000)

    def test_record_cache_boundary_bounded_page_and_authenticated_old_payload_relay(self):
        owner,receiver,_=self.network()
        first=self.block(owner,1)
        for _ in range(HOT_PAYLOAD_RECORDS):self.block(owner,0)
        self.assertEqual(len(owner._engine._hot_payloads),HOT_PAYLOAD_RECORDS)
        self.assertIsNone(owner._engine._records[first['hash']]['wire'])
        page=owner._engine.public_proposals(0,8)
        self.assertEqual(page['records'][0]['wire'],first['wire'])
        self.assertEqual(page['cursor'],8)
        receiver._pull(owner.public_key,'GET',{'hashes':[first['hash']]},deadline=time.monotonic()+5)
        self.assertEqual(receiver._engine.public_proposal(first['hash']),first['wire'])
        self.assertEqual(receiver._engine.lan_evidence()['transactions'],1)

    def test_large_page_materializes_at_most_one_large_block(self):
        owner,receiver,_=self.network();owner._engine._hot_payload_limit=0
        blocks=[self.block(owner,5000) for _ in range(2)]
        with patch.object(owner._profile,'read_dag',wraps=owner._profile.read_dag) as read:
            # Replace only the stored public reader, never a signer or journal.
            owner._engine._payload_reader=read
            page=owner._engine.public_proposals(0,8)
        self.assertEqual([row['hash'] for row in page['records']],[blocks[0]['hash']])
        self.assertEqual(read.call_count,1)
        self.assertEqual(page['tip'],2)
        with patch.object(owner._engine,'_payload_reader',wraps=owner._profile.read_dag) as read:
            receiver._pull(owner.public_key,'GET',{'hashes':[block['hash'] for block in blocks]},deadline=time.monotonic()+5)
        self.assertEqual(read.call_count,1)
        self.assertTrue(receiver._engine.has_proposal(blocks[0]['hash']))
        self.assertFalse(receiver._engine.has_proposal(blocks[1]['hash']))

    def test_cold_checkpoint_selection_restoration_and_fork_preserve_exact_wire(self):
        owner=self.network()[0];block=self.cold(owner)
        anchor={'genesis':{'dag':source_from_owned_peer(owner)},'genesis_hash':'a'*64}
        view={'certificate':{'genesis_hash':'a'*64,'state':{'dag':{
            'blocks':0,'transactions':0,'manifest_hash':'f'*64,'checkpoint':0}}},'order':[]}
        selected=select_checkpoint(owner,anchor,view)
        self.assertEqual(selected['descriptor']['block_ids'],[block['hash']])
        self.assertEqual(restore_checkpoint(owner,selected['descriptor']),selected['wire'])
        fork=owner._engine.fork_verifier();self.addCleanup(fork.stop)
        self.assertEqual(fork.public_proposal(block['hash']),block['wire'])
        self.assertIsNone(fork._durable_sink)
        self.assertFalse(fork._can_produce)

    def test_archive_read_does_not_hold_engine_lock_and_has_two_reader_limit(self):
        owner=self.network()[0];block=self.cold(owner);engine=owner._engine
        entered=[threading.Event(),threading.Event()];release=threading.Event();errors=[];results=[]
        read=engine._payload_reader;counter=iter(range(2))
        def paused(identifier):
            entered[next(counter)].set()
            if not release.wait(4):raise AssertionError('bounded archive fixture timeout')
            return read(identifier)
        engine._payload_reader=paused
        def run():
            try:results.append(engine.public_proposal(block['hash']))
            except Exception as error:errors.append(error)
        threads=[]
        try:
            for event in entered:
                thread=threading.Thread(target=run);threads.append(thread);thread.start()
                self.assertTrue(event.wait(2))
            with self.assertRaisesRegex(ValueError,'ARCHIVE_READ_BUSY'):engine.public_proposal(block['hash'])
            self.assertTrue(engine._lock.acquire(timeout=.25))
            engine._lock.release()
            self.assertEqual(engine.snapshot()['blocks_admitted'],1)
            self.assertLess(engine.memory_basis_bytes(),engine.stored_wire_bytes())
        finally:
            release.set()
            for thread in threads:thread.join(4)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(errors)
        self.assertEqual(results,[block['wire'],block['wire']])

    def test_changed_missing_closed_or_replaced_archive_cannot_publish_false_payload(self):
        owner=self.network()[0];block=self.cold(owner);engine=owner._engine;read=engine._payload_reader
        for raw in (None,b'',block['wire'][:-1],b'X'+block['wire'][1:]):
            engine._payload_reader=lambda identifier,value=raw:value
            with self.assertRaisesRegex(ValueError,'ARCHIVE_PAYLOAD_CHANGED'):engine.public_proposal(block['hash'])
        def replaced(identifier):
            engine._payload_reader=read
            return block['wire']
        engine._payload_reader=replaced
        with self.assertRaisesRegex(ValueError,'NOT_RUNNING'):engine.public_proposal(block['hash'])
        self.assertEqual(engine.public_proposal(block['hash']),block['wire'])
        owner._profile.close()
        with self.assertRaisesRegex(ValueError,'NOT_READABLE'):engine.public_proposal(block['hash'])

    def test_indexed_read_rejects_same_size_corruption_and_no_new_admission_is_claimed(self):
        owner=self.network()[0];block=self.cold(owner);engine=owner._engine;before=engine.lan_evidence()
        position=owner._profile._dag_index[block['hash']][0]
        owner._profile._db.execute('UPDATE entries SET wire=? WHERE position=?',(b'X'+block['wire'][1:],position))
        with self.assertRaisesRegex(ValueError,'RECORD_HASH'):engine.public_proposal(block['hash'])
        self.assertEqual(engine.lan_evidence(),before)

    def test_authenticated_reads_reserve_memory_before_materializing_cold_payload(self):
        owner,receiver,_=self.network();block=self.cold(owner)
        governor=owner.resources.governor()
        for operation,payload in (('PAGE',{'after':0}),('GET',{'hashes':[block['hash']]})):
            with patch.object(owner._engine,'_payload_reader',wraps=owner._profile.read_dag) as read,\
                    patch.object(governor,'reserve_memory',side_effect=ValueError('GG_DAG_RESOURCE_MEMORY')):
                with self.assertRaises((ValueError,OSError)):
                    receiver._pull(owner.public_key,operation,payload,deadline=time.monotonic()+3)
                read.assert_not_called()
            self.assertFalse(receiver._engine.has_proposal(block['hash']))
        receiver._pull(owner.public_key,'GET',{'hashes':[block['hash']]},deadline=time.monotonic()+3)
        self.assertTrue(receiver._engine.has_proposal(block['hash']))

    def test_cold_duplicates_branch_quarantine_and_next_honest_nonce_survive_replay(self):
        owner=self.network()[0];first=self.cold(owner)
        with patch.object(owner._engine,'_payload_reader',side_effect=AssertionError('duplicate must not read disk')):
            self.assertEqual(owner._engine.admit_relayed(first['wire'],0)['state'],'DUPLICATE')
        competing=json.loads(first['wire']);competing['body']['created_at_ns']+=1
        competing['signature']=owner._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(competing['body'])).hex()
        other=owner._engine.admit_relayed(pack(competing),0)
        self.assertIsNone(owner._engine._records[other['hash']]['wire'])
        with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.block(owner)
        sibling=owner._engine.produce_lan_test_block(owner._local_indices[1],1,owner._wire_limit)
        resumed=self.resume(owner)
        self.assertEqual(resumed._engine.public_proposal(first['hash']),first['wire'])
        self.assertEqual(resumed._engine.public_proposal(other['hash']),pack(competing))
        with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.block(resumed)
        next_block=resumed._engine.produce_lan_test_block(resumed._local_indices[1],1,resumed._wire_limit)
        self.assertEqual(json.loads(next_block['wire'])['body']['sequence'],2)
        self.assertEqual(json.loads(next_block['wire'])['body']['transactions'][0]['body']['nonce'],1)


if __name__=='__main__':unittest.main()
