"""Real signed block leaves; page/quorum verification is a caller prerequisite.

These cases test append consistency and frontier state, not fabricated finality.
The separate owned four-SDK suite exercises actual certificates and LAN pages.
"""
from copy import deepcopy
import hashlib
import json
import unittest

from backend.gg_dag_order_history import OrderHistory
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag,make_public_genesis,_tree


class OrderHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keys=[Keypair() for _ in range(6)];public=make_public_genesis([key.pubkey().hex() for key in keys],enable_dag_transactions=True)
        engine=ParallelDag.from_public_genesis(public);engine.attach_local_producers({0:keys[0]})
        cls.source={'allowed_producers':list(range(6))};cls.leaves=[]
        try:
            for _ in range(129):
                result=engine.produce_lan_test_block(0,1);body=json.loads(result['wire'])['body']
                cls.leaves.append({'hash':result['hash'],'index':len(cls.leaves)+1,'producer_index':0,'sequence':body['sequence'],'transactions':1})
        finally:engine.stop()

    def state(self,order):
        return {'dag':{'blocks':len(order),'transactions':sum(leaf['transactions'] for leaf in order),
            'order_root':_tree(order,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0]}}

    def pages(self,order,cursors):
        def fetch(cursor):
            cursors.append(cursor);items=order[cursor:cursor+32]
            return {'start':cursor,'complete':cursor+len(items)==len(order),'items':[{'leaf':deepcopy(leaf)} for leaf in items]}
        return fetch

    def test_every_prefix_matches_independent_original_merkle_root_and_is_detached(self):
        history=OrderHistory(self.source)
        for count in range(130):
            previous=history;order=deepcopy(self.leaves[:count]);history=history.extend(self.state(order),order)
            self.assertEqual(history.order(),order)
            self.assertEqual(len(previous),max(0,count-1))
            if order:order[-1]['hash']='e'*64;self.assertNotEqual(history.order(),order)

    def test_full_page_boundary_partial_overlap_and_skipped_checkpoints_fetch_only_suffix(self):
        history=OrderHistory.restore(self.source,self.state(self.leaves[:64]),deepcopy(self.leaves[:64]))
        cursors=[];history=history.fetch(self.state(self.leaves[:65]),self.pages(self.leaves[:65],cursors),lambda:None)
        self.assertEqual(cursors,[64])
        cursors=[];history=history.fetch(self.state(self.leaves),self.pages(self.leaves,cursors),lambda:None)
        self.assertEqual(cursors,[64,96,128]);self.assertEqual(history.order(),self.leaves)
        cursors=[];same=history.fetch(self.state(self.leaves),self.pages(self.leaves,cursors),lambda:None)
        self.assertEqual(cursors,[]);self.assertEqual(same.order(),history.order())

    def test_rewritten_old_nonoverlap_prefix_cannot_hide_behind_valid_new_suffix(self):
        history=OrderHistory.restore(self.source,self.state(self.leaves[:64]),deepcopy(self.leaves[:64]))
        changed=deepcopy(self.leaves[:65]);changed[0]['hash']='e'*64;cursors=[]
        with self.assertRaisesRegex(ValueError,'ORDER_INCONSISTENT'):
            history.fetch(self.state(changed),self.pages(changed,cursors),lambda:None)
        self.assertEqual(cursors,[64]);self.assertEqual(history.order(),self.leaves[:64])

    def test_overlap_rewrite_rewind_wrong_total_and_page_shape_never_poison_cache(self):
        history=OrderHistory.restore(self.source,self.state(self.leaves[:65]),deepcopy(self.leaves[:65]))
        changed=deepcopy(self.leaves[:66]);changed[64]['hash']='e'*64
        with self.assertRaisesRegex(ValueError,'ORDER_REWRITE'):history.fetch(self.state(changed),self.pages(changed,[]),lambda:None)
        with self.assertRaisesRegex(ValueError,'ORDER_REWRITE'):history.fetch(self.state(self.leaves[:64]),self.pages(self.leaves[:64],[]),lambda:None)
        for mutation in ({'transactions':True},{'transactions':10},{'blocks':True},{'order_root':'a'*64}):
            state=self.state(self.leaves[:66]);state['dag'].update(mutation)
            with self.assertRaises(ValueError):history.fetch(state,self.pages(self.leaves[:66],[]),lambda:None)
        for page in ({'start':64,'complete':True,'items':[]},{'start':0,'complete':True,'items':[]},
                     {'start':64,'complete':1,'items':[]},{'start':True,'complete':True,'items':[]}):
            with self.assertRaises(ValueError):history.fetch(self.state(self.leaves[:66]),lambda cursor:page,lambda:None)
        self.assertEqual(history.order(),self.leaves[:65])

    def test_invalid_new_leaf_duplicate_hash_sequence_and_cancellation_leave_prefix_usable(self):
        history=OrderHistory.restore(self.source,self.state(self.leaves[:64]),deepcopy(self.leaves[:64]))
        for mutation in ({'index':True},{'hash':self.leaves[0]['hash']},{'sequence':True},{'sequence':1},{'transactions':-1},{'producer_index':True}):
            changed=deepcopy(self.leaves[:65]);changed[-1].update(mutation)
            with self.assertRaises(ValueError):history.fetch(self.state(changed),self.pages(changed,[]),lambda:None)
        def cancelled():raise ValueError('GG_TEST_CANCELLED')
        with self.assertRaisesRegex(ValueError,'CANCELLED'):history.fetch(self.state(self.leaves[:65]),self.pages(self.leaves[:65],[]),cancelled)
        self.assertEqual(history.fetch(self.state(self.leaves[:65]),self.pages(self.leaves[:65],[]),lambda:None).order(),self.leaves[:65])


if __name__=='__main__':unittest.main()
