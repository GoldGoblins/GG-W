"""Python context/order regressions; real SDK recovery is a separate gate.

The large-counter case is an explicit shape/serialization vector, not a replay
of quadrillions of blocks. No mocked boolean is evidence of SDK verification.
"""
from copy import deepcopy
import hashlib
import json
import time
import unittest

from backend import gg_dag_segmented as segmented
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag,_tree,digest,pack,MAX_RECORDS

ANCHOR='a'*64


def keys():return [Keypair.from_seed(hashlib.sha256(('public Python segmented engine '+str(i)).encode()).digest()) for i in range(6)]


def fixture(allowed=None):
    owned=keys();source=segmented.make_source([key.pubkey().hex() for key in owned],list(range(6)) if allowed is None else allowed,'b'*64)
    return ParallelDag.from_segmented_source(source,ANCHOR),source,owned


def selected_state(node,source,raw):
    """Actual payload-derived order consistency; deliberately no SDK signature."""
    body=json.loads(raw)['body'];identifier=digest(body,b'GG-DAG-BLOCK-v1\0');count=len(body['transactions'])
    base=deepcopy(node._segment['base']['commitment']);state=deepcopy(base)
    internal=[{'hash':identifier,'index':1,'producer_index':body['producer_index'],'sequence':body['sequence'],'transactions':count}]
    producer=body['producer_index']
    state.update(blocks=str(int(base['blocks'])+1),transactions=str(int(base['transactions'])+count),
        last_rank=str(body['rank']),raw_bytes=str(int(base['raw_bytes'])+len(raw)))
    state['authors'][producer].update(head=identifier,sequence=str(body['sequence']),nonce=str(int(base['authors'][producer]['nonce'])+count))
    manifest={'blocks':[hashlib.sha256(raw).hexdigest()],'checkpoint':1,'genesis_hash':ANCHOR,'previous':base['active']['manifest_hash'],
        'schema':'gg.dag.execution.manifest.v1','source_hash':base['source_hash'],'time_ns':str(time.time_ns())}
    state['active'].update(blocks=1,checkpoint=1,transactions=int(state['transactions']),account_root=node._preview_root,
        order_root=_tree(internal,b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0],manifest_hash=digest(manifest,b'GG-DAG-CHECKPOINT-MANIFEST-v1\0'),
        previous=manifest['previous'],time_ns=manifest['time_ns'])
    order=[{**internal[0],'sequence':str(body['sequence']),'creator_key':source['genesis']['producers'][producer],'global_index':state['blocks']}]
    return state,order


def precision_context(source):
    base=segmented.initial_context(source,ANCHOR);state=base['commitment'];large=2**53+1
    state.update(epoch='2',blocks=str(large),last_rank=str(large),raw_bytes=str(large*700),last_cut='c'*64,closed_root='d'*64)
    state['authors'][0].update(sequence=str(large),head='e'*64)
    manifest={'blocks':[],'checkpoint':0,'genesis_hash':ANCHOR,'previous':state['last_cut'],
        'schema':'gg.dag.execution.manifest.v1','source_hash':state['source_hash'],'time_ns':str(time.time_ns())}
    state['active'].update(previous=manifest['previous'],time_ns=manifest['time_ns'],manifest_hash=digest(manifest,b'GG-DAG-CHECKPOINT-MANIFEST-v1\0'))
    return base


class SegmentedEngineTests(unittest.TestCase):
    def test_foreign_signed_transactions_cannot_be_wrapped_in_a_valid_new_network_block(self):
        first,source,owned=fixture();self.addCleanup(first.stop);first.attach_local_producers({0:owned[0]})
        old=json.loads(first.produce_lan_test_block(0,3,32*1024*1024)['wire'])
        other_source=segmented.make_source(source['genesis']['producers'],source['allowed_producers'],'c'*64,started_at_ns=int(source['started_at_ns']))
        second=ParallelDag.from_segmented_source(other_source,'d'*64);self.addCleanup(second.stop);second.attach_local_producers({0:owned[0]})
        wrapped=json.loads(second.produce_lan_test_block(0,3,32*1024*1024)['wire'])
        wrapped['body']['transactions']=old['body']['transactions'];wrapped['body']['payload_root']=_tree(old['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        wrapped['signature']=owned[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(wrapped['body'])).hex()
        recipient=ParallelDag.from_segmented_source(other_source,'d'*64);self.addCleanup(recipient.stop)
        with self.assertRaisesRegex(ValueError,'TX_DOMAIN'):recipient.admit_relayed(pack(wrapped),0)

    def test_old_unbound_source_is_rejected_without_silent_identity_upgrade(self):
        node,source,owned=fixture();self.addCleanup(node.stop)
        normalized=deepcopy(source);normalized['network_id']='';normalized['genesis_hash']='';normalized['genesis']['chain_id']=''
        source['genesis']['chain_id']='ggdag:'+digest(normalized,b'GG-DAG-SEGMENTED-CHAIN-ID-v1\0')[:24]
        source['genesis_hash']=digest(source['genesis'])
        with self.assertRaises(ValueError):ParallelDag.from_segmented_source(source,ANCHOR)

    def test_distinct_network_cannot_replay_a_signed_initial_block(self):
        first,source,owned=fixture();self.addCleanup(first.stop);first.attach_local_producers({0:owned[0]})
        wire=first.produce_lan_test_block(0,3,32*1024*1024)['wire']
        other_source=segmented.make_source(source['genesis']['producers'],source['allowed_producers'],'c'*64,started_at_ns=int(source['started_at_ns']))
        second=ParallelDag.from_segmented_source(other_source,'d'*64);self.addCleanup(second.stop)
        with self.assertRaises(ValueError):second.admit_relayed(wire,0)

    def test_explicit_source_has_derived_chain_and_legacy_import_never_upgrades(self):
        node,source,owned=fixture();self.addCleanup(node.stop)
        self.assertEqual(source['genesis']['chain_id'],segmented.chain_id(source))
        self.assertEqual(len(source['genesis']['chain_id']),70)
        public=node.export_public_genesis();self.assertEqual(public,segmented.public_genesis(source))
        self.assertEqual(public['schema'],'gg.parallel-dag.public-genesis.v4')
        with self.assertRaisesRegex(ValueError,'PUBLIC_GENESIS'):ParallelDag.from_public_genesis(public)
        self.assertFalse(node._can_produce);self.assertFalse(node.snapshot()['segment']['full_archive_history_replayed'])
        public['genesis']['producers'].clear();source['allowed_producers'].clear()
        self.assertEqual(len(node.export_public_genesis()['genesis']['producers']),6)
        self.assertEqual(len(node._segment['source']['allowed_producers']),6)

    def test_source_identity_binds_roles_time_keys_and_network_namespace(self):
        node,source,owned=fixture();self.addCleanup(node.stop)
        other=deepcopy(source);other['network_id']='c'*64
        self.assertNotEqual(segmented.chain_id(other),segmented.chain_id(source))
        with self.assertRaises(ValueError):segmented.validate_source(other)
        for kind in ('roles','start','key'):
            changed=deepcopy(source)
            if kind=='roles':changed['allowed_producers']=[0]
            elif kind=='start':changed['started_at_ns']=str(int(changed['started_at_ns'])+1)
            else:changed['genesis']['producers'][0]=Keypair().pubkey().hex()
            self.assertNotEqual(segmented.chain_id(changed),segmented.chain_id(source))
            with self.assertRaises(ValueError):segmented.validate_source(changed)

    def test_first_real_five_thousand_signed_transactions_use_original_identity_and_context(self):
        node,source,owned=fixture();self.addCleanup(node.stop);node.attach_local_producers({0:owned[0]})
        item=node.produce_lan_test_block(0,5000,32*1024*1024);body=json.loads(item['wire'])['body']
        self.assertEqual((body['sequence'],body['rank'],body['parents']),(1,1,[source['genesis_hash']]))
        self.assertEqual(body['precheck_root'],source['genesis']['precheck_root'])
        self.assertEqual([tx['body']['nonce'] for tx in body['transactions']],list(range(5000)))
        self.assertEqual(node._stats['signature_checks'],5001)
        self.assertEqual(node._preview_state[source['genesis']['producers'][0]]['nonce'],5000)
        self.assertFalse(node.snapshot()['preview']['canonical']);self.assertEqual(node.snapshot()['segment']['global_certified_blocks'],'0')

    def test_pinned_replica_roles_cannot_attach_or_create_producer_signatures(self):
        node,source,owned=fixture([1,3]);self.addCleanup(node.stop)
        with self.assertRaisesRegex(ValueError,'ROLE_FORBIDDEN'):node.attach_local_producers({0:owned[0]})
        node.attach_local_producers({1:owned[1]})
        item=node.produce_lan_test_block(1,2,32*1024*1024)
        self.assertEqual(json.loads(item['wire'])['body']['producer_index'],1)
        self.assertEqual(node._segment['source']['allowed_producers'],[1,3])

    def test_complete_local_execution_keeps_creator_global_order_and_account_roots(self):
        node,source,owned=fixture();self.addCleanup(node.stop);node.attach_local_producers({0:owned[0]})
        item=node.produce_lan_test_block(0,3,32*1024*1024);state,order=selected_state(node,source,item['wire'])
        checked,internal=segmented.check_order(state,order,source,node._segment['base'])
        self.assertEqual(internal[0]['sequence'],1);self.assertEqual(order[0]['sequence'],'1')
        result=node.apply_certified_order({'dag_segmented':state},order,source)
        self.assertTrue(result['locally_executed']);self.assertEqual(result['global_blocks'],'1')
        self.assertEqual(node._certified_order,(item['hash'],));self.assertEqual(node.snapshot()['segment']['global_certified_transactions'],'3')

    def test_order_mutations_cannot_relabel_creator_index_epoch_or_sequence(self):
        node,source,owned=fixture();self.addCleanup(node.stop);node.attach_local_producers({0:owned[0]})
        item=node.produce_lan_test_block(0,2,32*1024*1024);state,order=selected_state(node,source,item['wire'])
        for kind in ('creator','global_index','sequence_type','sequence_gap','local_index','omission','duplicate','epoch','source','root'):
            value=deepcopy(state);bad=deepcopy(order)
            if kind=='creator':bad[0]['creator_key']=source['genesis']['producers'][1]
            elif kind=='global_index':bad[0]['global_index']='2'
            elif kind=='sequence_type':bad[0]['sequence']=1
            elif kind=='sequence_gap':bad[0]['sequence']='2'
            elif kind=='local_index':bad[0]['index']=True
            elif kind=='omission':bad=[]
            elif kind=='duplicate':bad*=2
            elif kind=='epoch':value['epoch']='2'
            elif kind=='source':value['source_hash']='f'*64
            else:value['active']['order_root']='f'*64
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'ORDER_INVALID'):segmented.check_order(value,bad,source,node._segment['base'])

    def test_selected_payload_bytes_and_execution_are_required_beyond_valid_order_shape(self):
        node,source,owned=fixture();self.addCleanup(node.stop);node.attach_local_producers({0:owned[0]})
        item=node.produce_lan_test_block(0,2,32*1024*1024);state,order=selected_state(node,source,item['wire'])
        for field in ('raw_bytes','last_rank','account_root'):
            bad=deepcopy(state)
            if field=='account_root':bad['active']['account_root']=source['genesis']['precheck_root']
            else:bad[field]=str(int(bad[field])+1)
            with self.subTest(field=field),self.assertRaises(ValueError):node.apply_certified_order({'dag_segmented':bad},order,source)
        self.assertEqual(node._certified_order,())
        empty=ParallelDag.from_segmented_source(source,ANCHOR);self.addCleanup(empty.stop)
        with self.assertRaisesRegex(ValueError,'PAYLOAD_PENDING'):empty.apply_certified_order({'dag_segmented':state},order,source)

    def test_shape_only_large_counter_vector_keeps_exact_wire_and_small_graph_coordinates(self):
        node,source,owned=fixture();self.addCleanup(node.stop);base=precision_context(source)
        node._install_segment_base(base);node.attach_local_producers({0:owned[0]})
        item=node.produce_lan_test_block(0,1,32*1024*1024);body=json.loads(item['wire'])['body'];large=2**53+1
        self.assertEqual((body['sequence'],body['rank']),(large+1,large+1));self.assertEqual(body['parents'],[base['commitment']['last_cut']])
        graph=node.snapshot()['block_graph'];self.assertEqual(graph['tip_height'],1)
        self.assertEqual(graph['blocks'][-1]['global_rank'],str(large+1));self.assertEqual(graph['blocks'][-1]['producer_sequence'],str(large+1))
        self.assertEqual(graph['blocks'][0]['state'],'SEGMENT_BOUNDARY')
        self.assertFalse(node.snapshot()['segment']['full_archive_history_replayed'])
        self.assertIsNone(node.public_proposal(base['commitment']['last_cut']));self.assertIsNone(node.proposal_wire_size(base['commitment']['last_cut']))

    def test_first_author_in_later_epoch_requires_direct_boundary_parent(self):
        node,source,owned=fixture();self.addCleanup(node.stop);base=precision_context(source);node._install_segment_base(base)
        node.attach_local_producers({0:owned[0],1:owned[1]});first=node.produce_lan_test_block(0,0,32*1024*1024)
        body={'producer_index':1,'sequence':1,'parents':[first['hash']]}
        with self.assertRaisesRegex(ValueError,'OWN_PARENT'):node._branch_context(body)
        valid=node.produce_lan_test_block(1,1,32*1024*1024)
        self.assertIn(base['commitment']['last_cut'],json.loads(valid['wire'])['body']['parents'])

    def test_base_install_cannot_erase_existing_signers_admissions_or_payload_attachment(self):
        for kind in ('signer','admission','payload'):
            node,source,owned=fixture();self.addCleanup(node.stop)
            if kind=='signer':node.attach_local_producers({0:owned[0]})
            elif kind=='admission':
                other=node.fork_verifier();self.addCleanup(other.stop);other.attach_local_producers({0:owned[0]})
                node.admit_relayed(other.produce_lan_test_block(0,0,32*1024*1024)['wire'],0)
            else:node.configure_payload_archive(lambda identifier:b'',hot_bytes=0)
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'BASE_ATTACH_ORDER'):node._install_segment_base(segmented.initial_context(source,ANCHOR))

    def test_keyless_fork_preserves_context_without_aliasing_or_producing(self):
        node,source,owned=fixture();self.addCleanup(node.stop);node._install_segment_base(precision_context(source))
        fork=node.fork_verifier();self.addCleanup(fork.stop)
        self.assertFalse(fork._can_produce);self.assertEqual(fork.export_public_genesis(),node.export_public_genesis())
        fork._segment['base']['commitment']['authors'][0]['nonce']='1'
        self.assertEqual(node._segment['base']['commitment']['authors'][0]['nonce'],'0')

    def test_read_only_archive_gate_cannot_attach_signers_or_publish_fresh_payload(self):
        node,source,owned=fixture();self.addCleanup(node.stop);other=node.fork_verifier();self.addCleanup(other.stop)
        other.attach_local_producers({0:owned[0]});wire=other.produce_lan_test_block(0,1,32*1024*1024)['wire']
        node._segment['read_only_archive']=True
        with self.assertRaisesRegex(ValueError,'DURABLE_RESUME_REQUIRED'):node.attach_local_producers({0:owned[0]})
        with self.assertRaisesRegex(ValueError,'DURABLE_RESUME_REQUIRED'):node.admit_relayed(wire,0)
        self.assertEqual(len(node._records),1);self.assertEqual(node._stats['accepted'],0)


if __name__=='__main__':unittest.main()
