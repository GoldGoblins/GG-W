"""Controller view monotonicity; SDK cryptography is covered by real Go/WASM tests."""
from contextlib import ExitStack
import unittest
from unittest.mock import Mock,patch
from backend import gg_consensus as node


class CertifiedViewTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.genesis={'chain_id':'ggnet:'+'a'*24,'accounts':['b'*64]*4}
        for name,value in {'_genesis':self.genesis,'_genesis_hash':'c'*64,'_certificate_cache':{},
                           '_certified_tip':(10,'d'*64),'_last_state':{'height':9},'_last_proof':{},
                           '_safety_fault':'','_review':{'pending':True}}.items():
            self.stack.enter_context(patch.object(node,name,value))
        self.stack.enter_context(patch.object(node,'_alive',side_effect=lambda index:index==0))
        self.status=self.stack.enter_context(patch.object(node,'_status',return_value={'sync_info':{'latest_block_height':'10'}}))
        self.rpc=self.stack.enter_context(patch.object(node,'_rpc',return_value={'signed_header':{'commit':{'block_id':{'hash':'d'*64}}}}))
        self.stack.enter_context(patch.object(node,'_read_state_at',side_effect=lambda index,height:{'height':height,'chain_id':self.genesis['chain_id'],'genesis_hash':'c'*64}))
        self.stack.enter_context(patch.object(node,'_query',return_value={}))
        self.verify=self.stack.enter_context(patch.object(node,'_verify',return_value={'certificate_height':10}))

    def test_reachable_old_validator_cannot_rewind_certified_account_view(self):
        self.status.return_value={'sync_info':{'latest_block_height':'8'}}
        with self.assertRaisesRegex(ValueError,'NO_CERTIFIED_STATE'):node._verified_state()
        self.rpc.assert_not_called();self.verify.assert_not_called()
        self.assertEqual(node._last_state,{'height':9});self.assertEqual(node._certified_tip,(10,'d'*64))

    def test_same_tip_and_later_certificate_are_accepted(self):
        self.assertEqual(node._verified_state()[1]['height'],9)
        self.status.return_value={'sync_info':{'latest_block_height':'11'}}
        self.verify.return_value={'certificate_height':11}
        self.rpc.return_value={'signed_header':{'commit':{'block_id':{'hash':'e'*64}}}}
        self.assertEqual(node._verified_state()[1]['height'],10)
        self.assertEqual(node._certified_tip,(11,'e'*64))

    def test_conflicting_sdk_verified_certificate_latches_and_blocks_new_spending(self):
        self.rpc.return_value={'signed_header':{'commit':{'block_id':{'hash':'e'*64}}}}
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):node._verified_state()
        self.assertIsNone(node._review)
        self.assertEqual(node._last_state,{'height':9})
        self.rpc.return_value={'signed_header':{'commit':{'block_id':{'hash':'d'*64}}}}
        for operation in (node._verified_state,lambda:node.prepare(0,'b'*64,'1'),lambda:node.send('old-review','old-review')):
            with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):operation()

    def test_unverified_conflicting_header_never_latches_a_consensus_fault(self):
        self.rpc.return_value={'signed_header':{'commit':{'block_id':{'hash':'e'*64}}}}
        self.verify.side_effect=ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')
        with self.assertRaisesRegex(ValueError,'NO_CERTIFIED_STATE'):node._verified_state()
        self.assertEqual(node._safety_fault,'');self.assertEqual(node._certified_tip,(10,'d'*64))


if __name__=='__main__':unittest.main()
