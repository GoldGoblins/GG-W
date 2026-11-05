"""Real admitted payloads; synthetic certified metadata tests only the selector.

SDK/quorum and native/WASM page verification run independently of these tests.
"""
from copy import deepcopy
import base64
import unittest
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_dag_checkpoint import select_checkpoint,restore_checkpoint,check_complete_order
from backend.gg_parallel_dag import pack
from tests.test_lan_consensus_anchor import paired_peers,member_invites


class CheckpointSelectionTests(unittest.TestCase):
    def setUp(self):
        self.peers=paired_peers(self);self.peer=self.peers[0]
        bundle=self.peer.create_session([peer.public_invite() for peer in self.peers],enable_dag_transactions=True,consensus_invites=member_invites(self.peers))
        for peer in self.peers:peer.install_session(bundle,_start_gossip=False)
        self.peer._engine.configure_lan_capacity(block_bytes=32*1024*1024,session_bytes=512*1024*1024)
        self.anchor=anchor_from_owned_peer(self.peer)

    def view(self,rows=()):
        order=[{'hash':row['hash'],'index':index+1,'producer_index':row['producer_index'],
                'sequence':row['producer_sequence'],'transactions':row['transaction_count']} for index,row in enumerate(rows)]
        return {'certificate':{'genesis_hash':self.anchor['genesis_hash'],'state':{'dag':{
            'blocks':len(order),'transactions':sum(row['transactions'] for row in order),'manifest_hash':'f'*64,'checkpoint':1 if rows else 0}}},'order':order}

    def produce(self,count=1):
        return self.peer._engine.produce_lan_test_block(self.peer._local_indices[0],count,32*1024*1024)

    def test_causal_candidates_exclude_proven_members_and_restore_exact_signed_bytes(self):
        first=self.produce(2);second=self.produce(3)
        view=self.view([self.peer._engine._records[first['hash']]])
        selected=select_checkpoint(self.peer,self.anchor,view)
        self.assertEqual(selected['descriptor']['block_ids'],[second['hash']])
        self.assertEqual(restore_checkpoint(self.peer,selected['descriptor']),selected['wire'])
        import json
        batch=json.loads(selected['wire'])
        self.assertEqual(base64.b64decode(batch['blocks'][0]),second['wire'])
        self.assertEqual(batch['previous'],'f'*64)
        self.assertIsNone(select_checkpoint(self.peer,self.anchor,self.view([self.peer._engine._records[first['hash']],self.peer._engine._records[second['hash']]])))

    def test_batch_has_finite_record_limit_and_preserves_own_sequence(self):
        for _ in range(129):self.produce()
        selected=select_checkpoint(self.peer,self.anchor,self.view())
        self.assertEqual(len(selected['descriptor']['block_ids']),128)
        import json
        sequences=[json.loads(base64.b64decode(raw))['body']['sequence'] for raw in json.loads(selected['wire'])['blocks']]
        self.assertEqual(sequences,list(range(1,129)))

    def test_unavailable_ancestor_and_noncanonical_own_head_cannot_be_selected(self):
        first=self.produce();self.produce()
        stored=self.peer._engine._records.pop(first['hash'])
        try:self.assertIsNone(select_checkpoint(self.peer,self.anchor,self.view()))
        finally:self.peer._engine._records[first['hash']]=stored
        view=self.view([stored]);view['order'][0]['hash']='e'*64
        self.assertIsNone(select_checkpoint(self.peer,self.anchor,view))

    def test_pending_request_cannot_silently_change_or_lose_payload(self):
        block=self.produce();selected=select_checkpoint(self.peer,self.anchor,self.view())
        changed=deepcopy(selected['descriptor']);changed['hash']='d'*64
        with self.assertRaisesRegex(ValueError,'PAYLOAD_CHANGED'):restore_checkpoint(self.peer,changed)
        self.peer._engine._records.pop(block['hash'])
        with self.assertRaisesRegex(ValueError,'PAYLOAD_MISSING'):restore_checkpoint(self.peer,selected['descriptor'])

    def test_complete_order_rejects_duplicate_hash_wrong_sequence_and_false_tx_total(self):
        first=self.produce();second=self.produce();view=self.view([self.peer._engine._records[first['hash']],self.peer._engine._records[second['hash']]])
        for mutation in ('hash','sequence','total','missing'):
            changed=deepcopy(view)
            if mutation=='hash':changed['order'][1]['hash']=changed['order'][0]['hash']
            elif mutation=='sequence':changed['order'][1]['sequence']=1
            elif mutation=='total':changed['certificate']['state']['dag']['transactions']+=1
            else:changed['order'].pop()
            with self.assertRaisesRegex(ValueError,'ORDER_INCONSISTENT'):
                check_complete_order(changed['certificate']['state'],changed['order'],self.anchor['genesis']['dag'])


if __name__=='__main__':unittest.main()
