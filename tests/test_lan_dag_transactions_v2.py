"""Disposable DAG-payload TX tests; no physical hosts or finality assertion."""
import json
import unittest
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag,make_public_genesis,pack


class ProducerOwnedDagTests(unittest.TestCase):
    def setUp(self):
        self.keys=[Keypair() for _ in range(6)]
        self.bundle=make_public_genesis([key.pubkey().hex() for key in self.keys],enable_dag_transactions=True)
        self.nodes=[ParallelDag.from_public_genesis(self.bundle) for _ in range(3)]
        for index,node in enumerate(self.nodes):node.attach_local_producers({i:self.keys[i] for i in (index*2,index*2+1)})

    def resign(self,value,producer):
        value['signature']=self.keys[producer].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        return pack(value)

    def test_independent_keys_actual_payload_causal_parent_and_order_independent_state(self):
        raws=[]
        for index,node in enumerate(self.nodes):
            first=node.produce_lan_test_block(index*2,3,44*1024)
            second=node.produce_lan_test_block(index*2,2,44*1024)
            self.assertIn(first['hash'],json.loads(second['wire'])['body']['parents'])
            timing=node.snapshot()['last_wave']
            self.assertEqual(timing['transactions'],2);self.assertEqual(timing['workers_used'],1)
            self.assertGreater(timing['producer_ms'],0);self.assertGreater(timing['validation_ms'],0)
            raws.extend([first['wire'],second['wire']])
            with self.assertRaisesRegex(ValueError,'NOT_OWNED'):node.produce_lan_test_block((index*2+2)%6,1)
        for node in self.nodes:
            for raw in raws:node.admit_relayed(raw,0)
            node.reconcile()
        self.assertEqual(len({node.lan_evidence()['blockset_digest'] for node in self.nodes}),1)
        self.assertEqual(len({node.lan_evidence()['state_root'] for node in self.nodes}),1)
        for node in self.nodes:
            self.assertEqual(node.lan_evidence()['transactions'],15)
            self.assertEqual(sum(int(value['balance_atomic']) for value in node._preview_state.values()),6*10**9)
            self.assertEqual(node.snapshot()['canonical_finalized'],0)

    def test_verified_equivocation_is_sticky_and_bad_signature_is_not_a_fault(self):
        node=self.nodes[0];raw=node.produce_lan_test_block(0,2)['wire'];value=json.loads(raw)
        value['body']['created_at_ns']+=1
        invalid=pack(value)
        with self.assertRaisesRegex(ValueError,'GG_DAG_SIGNATURE'):node.admit_relayed(invalid,0)
        self.assertEqual(node.lan_evidence()['protocol_fault'],'')
        competing=self.resign(value,0)
        with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):node.admit_relayed(competing,0)
        with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):node.produce_lan_test_block(0,1)
        self.assertEqual(node.lan_evidence()['transactions'],2)

    def test_own_parent_and_sequential_nonce_required_without_reset(self):
        node=self.nodes[0];first=node.produce_lan_test_block(0,1)
        other=self.nodes[1].produce_lan_test_block(2,1)
        node.admit_relayed(other['wire'],1)
        raw=node.produce_lan_test_block(0,1)['wire'];value=json.loads(raw)
        # A verifier with the first proposal cannot accept the next sequence
        # unless its real preceding own proposal is an explicit parent.
        verifier=ParallelDag.from_public_genesis(self.bundle)
        verifier.admit_relayed(first['wire'],0);verifier.admit_relayed(other['wire'],1)
        value['body']['parents']=[other['hash']]
        value['body']['rank']=2
        with self.assertRaisesRegex(ValueError,'OWN_PARENT'):verifier.admit_relayed(self.resign(value,0),0)
        self.assertEqual(verifier.lan_evidence()['transactions'],2)

    def test_profile_preflight_and_empty_mode_compatibility(self):
        self.assertLessEqual(self.nodes[0].preflight_lan_test_block(64,44*1024),44*1024)
        with self.assertRaisesRegex(ValueError,'WIRE_PROFILE_LIMIT'):self.nodes[0].preflight_lan_test_block(128,44*1024)
        legacy=ParallelDag.from_public_genesis(make_public_genesis([key.pubkey().hex() for key in self.keys]))
        raw=self.nodes[0].produce_lan_test_block(0,1)['wire']
        with self.assertRaises(ValueError):legacy.inspect_empty_proposal(raw)

    def test_competing_branches_and_descendants_never_reset_author_allowance(self):
        left=self.nodes[0]
        fork=ParallelDag.from_public_genesis(self.bundle);fork.attach_local_producers({0:self.keys[0]})
        left_first=left.produce_lan_test_block(0,1);left_child=left.produce_lan_test_block(0,1)
        fork_first=fork.produce_lan_test_block(0,2);fork_child=fork.produce_lan_test_block(0,2)
        before_left=left.lan_evidence();before_fork=fork.lan_evidence()
        for node,opposite,descendant in ((left,fork_first,fork_child),(fork,left_first,left_child)):
            with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):node.admit_relayed(opposite['wire'],0)
            with self.assertRaises(ValueError):node.admit_relayed(descendant['wire'],0)
            with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):node.produce_lan_test_block(0,1)
            self.assertIn('EQUIVOCATION',node.lan_evidence()['protocol_fault'])
        self.assertEqual(left._lan_counts[0],2);self.assertEqual(fork._lan_counts[0],4)
        self.assertEqual(left.lan_evidence()['state_root'],before_left['state_root'])
        self.assertEqual(fork.lan_evidence()['state_root'],before_fork['state_root'])


if __name__=='__main__':unittest.main()
