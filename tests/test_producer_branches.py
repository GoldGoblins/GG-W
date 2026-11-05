"""Real signed candidate branches: no fabricated certificate or network rate."""
import json
import unittest
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag,make_public_genesis,pack,_tree


class ProducerBranchTests(unittest.TestCase):
    def setUp(self):
        self.keys=[Keypair() for _ in range(6)]
        self.public=make_public_genesis([key.pubkey().hex() for key in self.keys],enable_dag_transactions=True)
        self.owner=self.engine({0:self.keys[0],1:self.keys[1]})
        self.fork=self.engine({0:self.keys[0]})

    def engine(self,signers=None):
        node=ParallelDag.from_public_genesis(self.public);self.addCleanup(node.stop)
        if signers:node.attach_local_producers(signers)
        return node

    def test_unrelated_owned_producer_continues_after_second_fully_valid_branch(self):
        first=self.owner.produce_lan_test_block(0,1)
        second=self.fork.produce_lan_test_block(0,2)
        self.owner.admit_relayed(second['wire'],0);self.owner.reconcile()
        self.assertTrue(self.owner.has_proposal(first['hash']));self.assertTrue(self.owner.has_proposal(second['hash']))
        self.assertEqual(self.owner.lan_evidence()['protocol_fault'],'')
        with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.owner.produce_lan_test_block(0,1)
        honest=self.owner.produce_lan_test_block(1,1)
        self.assertEqual(self.owner._lan_counts[0],2)
        self.assertNotIn(first['hash'],json.loads(honest['wire'])['body']['parents'])
        self.assertNotIn(second['hash'],json.loads(honest['wire'])['body']['parents'])
        self.assertEqual(sum(int(row['balance_atomic']) for row in self.owner._preview_state.values()),6*10**9)

    def test_bad_transaction_inside_signed_fork_cannot_quarantine_producer(self):
        first=self.owner.produce_lan_test_block(0,1)
        second=self.fork.produce_lan_test_block(0,2);value=json.loads(second['wire'])
        value['body']['transactions'][1]['signature']='0'*128
        value['body']['payload_root']=_tree(value['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        value['signature']=self.keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        with self.assertRaises(ValueError):self.owner.admit_relayed(pack(value),0)
        self.owner.produce_lan_test_block(0,1)
        self.assertEqual(len(self.owner._records),3)

    def source(self):
        return {'schema':'gg.dag.consensus.source.v1','signature_profile':'GG-Ed25519-PrimeOrder-v1',
            'accounts':self.public['accounts'],'allowed_producers':list(range(6)),'genesis':self.public['genesis'],
            'genesis_hash':self.public['genesis_hash'],'network_id':'b'*64,'started_at_ns':str(self.public['started_at_ns'])}

    def view(self,blocks):
        # Independently execute actual transaction bodies, not cached deltas.
        accounts={address:{'balance_atomic':'1000000000','nonce':0} for address in self.public['accounts']};order=[];total=0
        for index,block in enumerate(blocks):
            body=json.loads(block['wire'])['body']
            for signed in body['transactions']:
                tx=signed['body'];sender=accounts[tx['from']];recipient=accounts[tx['to']]
                self.assertEqual(sender['nonce'],tx['nonce']);sender['nonce']+=1
                sender['balance_atomic']=str(int(sender['balance_atomic'])-1);recipient['balance_atomic']=str(int(recipient['balance_atomic'])+1);total+=1
            order.append({'hash':block['hash'],'index':index+1,'producer_index':body['producer_index'],'sequence':body['sequence'],'transactions':len(body['transactions'])})
        leaves=[{'address':address,**accounts[address]} for address in sorted(accounts)]
        state={'dag':{'blocks':len(order),'transactions':total,'account_root':_tree(leaves,b'GG-DAG-ACCOUNT-v1\0')[-1][0],
            'order_root':_tree(order,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0]}}
        return state,order,accounts

    def test_missing_selected_branch_is_not_claimed_then_actual_payload_execution_pins_it(self):
        first=self.owner.produce_lan_test_block(0,1);second=self.fork.produce_lan_test_block(0,2)
        state,order,accounts=self.view([second]);before=self.owner._preview_root
        with self.assertRaisesRegex(ValueError,'PAYLOAD_PENDING'):self.owner.apply_certified_order(state,order,self.source())
        self.assertEqual(self.owner._certified_order,());self.assertEqual(self.owner._preview_root,before)
        self.owner.admit_relayed(second['wire'],0)
        result=self.owner.apply_certified_order(state,order,self.source())
        self.assertTrue(result['locally_executed']);self.assertEqual(self.owner._preview_state,accounts)
        self.assertEqual(self.owner._certified_order,(second['hash'],));self.assertNotIn(first['hash'],self.owner._preview_selected)
        with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.owner.produce_lan_test_block(0,1)
        honest=self.owner.produce_lan_test_block(1,1)
        self.assertIn(second['hash'],json.loads(honest['wire'])['body']['parents'])
        newer,rows,expected=self.view([second,honest]);self.owner.apply_certified_order(newer,rows,self.source())
        self.owner.apply_certified_order(state,order,self.source()) # An older valid prefix cannot rewind the adopted one.
        self.assertEqual(self.owner._certified_order,(second['hash'],honest['hash']));self.assertEqual(self.owner._preview_state,expected)
        wrong,wrong_rows,_=self.view([first])
        with self.assertRaisesRegex(ValueError,'REWRITE'):self.owner.apply_certified_order(wrong,wrong_rows,self.source())
        self.assertEqual(self.owner._preview_state,expected)

    def test_account_or_order_root_mutation_never_adopts_membership(self):
        block=self.owner.produce_lan_test_block(0,2)
        state,order,_=self.view([block])
        for root in ('account_root','order_root'):
            changed={'dag':{**state['dag'],root:'f'*64}}
            with self.assertRaisesRegex(ValueError,'EXECUTION_ROOT'):self.owner.apply_certified_order(changed,order,self.source())
            self.assertEqual(self.owner._certified_order,())

    def test_two_incompatible_parent_histories_are_not_an_executable_candidate(self):
        first=self.owner.produce_lan_test_block(0,1);second=self.fork.produce_lan_test_block(0,2)
        self.owner.admit_relayed(second['wire'],0)
        other=self.engine({1:self.keys[1]}).produce_lan_test_block(1,1);value=json.loads(other['wire'])
        value['body']['parents']=[first['hash'],second['hash']];value['body']['rank']=2
        value['signature']=self.keys[1].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        with self.assertRaisesRegex(ValueError,'PARENT_CONFLICT'):self.owner.admit_relayed(pack(value),0)
        self.assertNotIn(1,self.owner._lan_quarantine)

    def test_causal_arrival_permutations_preserve_both_branches_and_monotonic_allowance(self):
        import itertools
        a=self.owner.produce_lan_test_block(0,1);a2=self.owner.produce_lan_test_block(0,1)
        b=self.fork.produce_lan_test_block(0,2);b2=self.fork.produce_lan_test_block(0,2)
        roots=set()
        for permutation in itertools.permutations(range(4)):
            if permutation.index(0)>permutation.index(1) or permutation.index(2)>permutation.index(3):continue
            node=self.engine()
            for index in permutation:node.admit_relayed((a,a2,b,b2)[index]['wire'],0)
            node.reconcile();roots.add(node._preview_root)
            self.assertEqual(node._lan_counts[0],4);self.assertEqual(node.lan_evidence()['transactions'],4)
            self.assertEqual(len(node._records),5);self.assertEqual(node._preview_counts['accepted'],0)
        self.assertEqual(len(roots),1)

    def test_extra_fork_variants_cannot_fill_storage_but_sdk_selected_payload_can_recover(self):
        self.owner.produce_lan_test_block(0,1);second=self.fork.produce_lan_test_block(0,2)
        self.owner.admit_relayed(second['wire'],0)
        value=json.loads(second['wire']);value['body']['created_at_ns']+=1
        value['signature']=self.keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        raw=pack(value)
        with self.assertRaisesRegex(ValueError,'QUARANTINE_CREDIT'):self.owner.admit_relayed(raw,0)
        from backend.gg_parallel_dag import digest
        third={'wire':raw,'hash':digest(value['body'],b'GG-DAG-BLOCK-v1\0')}
        state,order,accounts=self.view([third])
        with self.assertRaisesRegex(ValueError,'PAYLOAD_PENDING'):self.owner.apply_certified_order(state,order,self.source())
        self.assertEqual(self.owner._certified_order,())
        self.owner.admit_relayed(raw,0);self.owner.apply_certified_order(state,order,self.source())
        self.assertEqual(self.owner._preview_state,accounts);self.assertEqual(len(self.owner._records),4)
        replay=self.engine();replay.begin_history_replay()
        for row in self.owner._records.values():
            if row['rank']:replay.admit_relayed(row['wire'],0)
        replay.finish_history_replay()
        self.assertEqual(len(replay._lan_author_slots[(0,1)]),3)
        self.assertFalse(replay._replaying_history)
        replay.apply_certified_order(state,order,self.source());self.assertEqual(replay._preview_state,accounts)

    def test_quarantined_author_descendant_budget_preserves_room_for_other_authors(self):
        from backend.gg_parallel_dag import MAX_QUARANTINE_CANDIDATES
        first=self.owner.produce_lan_test_block(0,1);other=self.fork.produce_lan_test_block(0,2)
        self.owner.admit_relayed(other['wire'],0)
        for _ in range(MAX_QUARANTINE_CANDIDATES-2):
            child=self.fork.produce_lan_test_block(0,1);self.owner.admit_relayed(child['wire'],0)
        child=self.fork.produce_lan_test_block(0,1)
        with self.assertRaisesRegex(ValueError,'QUARANTINE_CREDIT'):self.owner.admit_relayed(child['wire'],0)
        self.owner.reconcile();self.owner.produce_lan_test_block(1,1)
        self.assertEqual(self.owner._next_sequences[1],1)

    def test_author_ancestry_queries_cover_deep_chains_without_crossing_forks(self):
        chain=[self.owner.produce_lan_test_block(0,0) for _ in range(257)]
        for older,newer in ((0,256),(128,256),(32,129),(200,201),(256,256)):
            self.assertTrue(self.owner._author_ancestor(chain[older]['hash'],chain[newer]['hash']))
            if older!=newer:self.assertFalse(self.owner._author_ancestor(chain[newer]['hash'],chain[older]['hash']))
        fork=self.fork.produce_lan_test_block(0,0);self.owner.admit_relayed(fork['wire'],0)
        self.assertFalse(self.owner._author_ancestor(fork['hash'],chain[-1]['hash']))

    def test_old_unfinalized_cross_dependency_pauses_signing_until_that_branch_is_certified(self):
        a=self.owner.produce_lan_test_block(0,1)
        legacy=self.engine({1:self.keys[1]}).produce_lan_test_block(1,1);value=json.loads(legacy['wire'])
        value['body']['parents']=[a['hash']];value['body']['rank']=2
        value['signature']=self.keys[1].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        self.owner.admit_relayed(pack(value),0);self.owner.reconcile()
        b=self.fork.produce_lan_test_block(0,2);self.owner.admit_relayed(b['wire'],0);self.owner.reconcile()
        with self.assertRaisesRegex(ValueError,'PARENT_PENDING'):self.owner.produce_lan_test_block(1,1)
        self.assertEqual(self.owner._lan_counts[1],1)
        state,order,_=self.view([a]);self.owner.apply_certified_order(state,order,self.source())
        resumed=self.owner.produce_lan_test_block(1,1)
        self.assertEqual(json.loads(resumed['wire'])['body']['transactions'][0]['body']['nonce'],1)


if __name__=='__main__':unittest.main()
