"""Codec/projection unit checks; real SDK/WASM cases have a separate gate.

The distributed vectors contain public native-application state and actual
valid SDK test signatures, not a claim of four physical devices or history
replay by a light client. No private key or network is required by this suite.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_consensus as native, gg_consensus_web as web, gg_dag_checkpoint as checkpoint, gg_dag_segmented as segmented
from backend.gg_parallel_dag import pack

VECTORS=Path(__file__).parent/'data/dag_segmented_membership_vectors.json'

def packets():
    data=json.loads(VECTORS.read_text(encoding='utf-8'))
    assert data['schema']=='gg.public.segmented-membership-test-vectors.v1'
    return data['packets']

def trusted(packet):return {key:deepcopy(packet[key]) for key in ('genesis','genesis_hash')}

def reply(packet):
    """Projection seam only; this fixture is not SDK verification evidence."""
    state=packet['state']['dag_segmented']
    return {'verified':True,'schema':'gg.consensus.proof-result.v1','dag_segmented_commitment':state,
        'dag_history_replay_verified':False,'dag_segmented_membership_scope':'CERTIFIED_ACTIVE_SEGMENT_MEMBERSHIP_NOT_FULL_HISTORY_REPLAY',
        **{name+'_verified':packet.get(name) is not None for name in ('dag_segmented_account_proof','dag_segmented_block_proof','dag_segmented_order_page')}}

class SegmentedPublicCodecTests(unittest.TestCase):
    def test_native_public_vectors_have_identical_source_state_and_pin_shape(self):
        for name,packet in packets().items():
            with self.subTest(name=name):
                source=packet['genesis']['dag_segmented']
                self.assertEqual(segmented.validate_source(source),source)
                self.assertEqual(checkpoint.validate_source(source),source)
                self.assertEqual(segmented.validate_state(packet['state']['dag_segmented'],source,packet['genesis_hash']),packet['state']['dag_segmented'])
                self.assertEqual(web._pin(trusted(packet)),trusted(packet))

    def test_source_policy_rehashed_mutations_never_create_a_silent_upgrade(self):
        source=packets()['after_next']['genesis']['dag_segmented']
        for field in segmented.history_policy():
            with self.subTest(field=field):
                bad=deepcopy(source);bad['genesis']['history_policy'][field]+='.changed'
                bad['genesis']['chain_id']=segmented.chain_id(bad)
                bad['genesis_hash']=hashlib.sha256(b'GG-DAG-DATA-v1\0'+pack(bad['genesis'])).hexdigest()
                with self.assertRaisesRegex(ValueError,'SEGMENTED_SOURCE'):segmented.validate_source(bad)
        old=deepcopy(source);old['schema']='gg.dag.consensus.source.v1'
        with self.assertRaises(ValueError):checkpoint.validate_source(old)

    def test_owned_source_and_pin_copies_do_not_alias_the_caller(self):
        packet=packets()['after_next'];source=packet['genesis']['dag_segmented']
        owned=segmented.validate_source(source);pin=web._pin(trusted(packet))
        source['genesis']['producers'][0]='0'*64;source['allowed_producers'].clear()
        self.assertNotEqual(owned,source)
        self.assertEqual(pin['genesis']['dag_segmented'],owned)

    def test_public_state_rejects_counter_aliases_wrong_owners_and_extra_claims(self):
        packet=packets()['after_next'];source=packet['genesis']['dag_segmented'];anchor=packet['genesis_hash']
        for kind in ('epoch_bool','blocks_float','nonce_leading_zero','wrong_owner','uncreated_head','source_hash','active_count','time','fake_replay'):
            with self.subTest(kind=kind):
                state=deepcopy(packet['state']['dag_segmented'])
                if kind=='epoch_bool':state['epoch']=True
                elif kind=='blocks_float':state['blocks']=3.0
                elif kind=='nonce_leading_zero':state['authors'][0]['nonce']='05001'
                elif kind=='wrong_owner':state['authors'][0]['key']=state['authors'][1]['key']
                elif kind=='uncreated_head':state['authors'][5]['head']='0'*64
                elif kind=='source_hash':state['source_hash']='0'*64
                elif kind=='active_count':state['active']['blocks']=True
                elif kind=='time':state['active']['time_ns']='01'
                else:state['full_history_verified']=True
                with self.assertRaisesRegex(ValueError,'SEGMENTED_STATE'):segmented.validate_state(state,source,anchor)

    def test_new_pin_never_accepts_both_dag_modes_or_old_native_version(self):
        packet=packets()['after_next']
        for kind in ('both','old','null_membership'):
            pin=trusted(packet)
            if kind=='both':pin['genesis']['dag']=deepcopy(pin['genesis']['dag_segmented'])
            elif kind=='old':pin['genesis']['schema']='gg.native.genesis.v3'
            else:pin['genesis']['membership']=None
            pin['genesis_hash']=hashlib.sha256(pack(pin['genesis'])).hexdigest()
            with self.assertRaises(ValueError):web._pin(pin)

    def test_projection_invokes_native_and_preserves_verified_creator_and_scope(self):
        packet=packets()['after_next']
        with patch.object(native,'_verify_public',return_value=reply(packet)) as run:
            result=segmented.verify_membership(packet,trusted(packet),binary=Path('owned-tool'),stamp=(1,2))
        run.assert_called_once_with(packet,Path('owned-tool'),(1,2))
        self.assertEqual(result['account']['nonce'],5001)
        self.assertEqual(result['block']['creator_key'],packet['genesis']['dag_segmented']['genesis']['producers'][0])
        self.assertEqual((result['block']['index'],result['block']['global_index'],result['block']['sequence']),(1,'3','2'))
        self.assertFalse(result['history_replayed']);self.assertTrue(result['producer_owned_nonfinancial'])

    def test_native_failure_wrong_result_and_wrong_pin_never_publish_observation(self):
        packet=packets()['after_next']
        with patch.object(native,'_verify_public',side_effect=ValueError('SDK rejection')):
            with self.assertRaisesRegex(ValueError,'OBSERVATION_INVALID'):segmented.verify_membership(packet,trusted(packet),binary=Path('owned'))
        bad=reply(packet);bad['dag_history_replay_verified']=True
        with patch.object(native,'_verify_public',return_value=bad):
            with self.assertRaisesRegex(ValueError,'OBSERVATION_INVALID'):segmented.verify_membership(packet,trusted(packet),binary=Path('owned'))
        pin=trusted(packet);pin['genesis_hash']='0'*64
        with patch.object(native,'_verify_public') as run:
            with self.assertRaises(ValueError):segmented.verify_membership(packet,pin,binary=Path('owned'))
            run.assert_not_called()

    def test_native_export_routes_new_proofs_without_legacy_flags_or_duplicate_verification(self):
        packet=packets()['after_next'];account=packet['genesis']['dag_segmented']['genesis']['producers'][0]
        block=packet['dag_segmented_block_proof']['leaf']['hash']
        def query(index,path,height,data):
            return packet['dag_segmented_account_proof' if path.endswith('account-proof') else 'dag_segmented_block_proof']
        with patch.object(native,'_genesis',packet['genesis']),patch.object(native,'_genesis_hash',packet['genesis_hash']),\
                patch.object(native,'_verified_state',return_value=(0,packet['state'],{'certificate_height':packet['state']['height']+1})),\
                patch.object(native,'_rpc',return_value={'signed_header':packet['signed_header']}),patch.object(native,'_query',side_effect=query),\
                patch.object(native,'_verify') as old_verify,patch.object(segmented,'verify_membership',return_value={}) as verify:
            exported=native.export_dag_proof(account,block)
        self.assertEqual(exported['dag_segmented_block_proof'],packet['dag_segmented_block_proof'])
        self.assertNotIn('dag_account_proof',exported);old_verify.assert_not_called();verify.assert_called_once()

    def test_bound_new_source_resume_is_idempotent_and_cannot_switch_genesis(self):
        packet=packets()['after_next'];source=packet['genesis']['dag_segmented']
        with patch.object(native,'_closed',False),patch.object(native,'_genesis',packet['genesis']),patch.object(native,'_alive',return_value=True),\
                patch.object(native,'snapshot',return_value={'state':'RUNNING'}),patch.object(native,'_launch') as launch:
            self.assertEqual(native.start(dag_source=source),{'state':'RUNNING'})
            launch.assert_not_called()
            other=deepcopy(source);other['network_id']='a'*64
            other['genesis']['chain_id']=segmented.chain_id(other)
            other['genesis_hash']=hashlib.sha256(b'GG-DAG-DATA-v1\0'+pack(other['genesis'])).hexdigest()
            with self.assertRaisesRegex(ValueError,'ALREADY_BOUND'):native.start(dag_source=other)

class SegmentedArchiveBoundaryTests(unittest.TestCase):
    def test_legacy_or_partial_file_never_invokes_sdk_or_produces_a_receipt(self):
        from backend import gg_dag_archive as archive
        pin=trusted(packets()['after_next'])
        with tempfile.TemporaryDirectory() as directory,patch.object(archive,'_native_verify') as run:
            path=Path(directory)/'bad.ggdag'
            for raw in (b'',b'GGDAGAR1',b'GGDAGAR'):
                path.write_bytes(raw)
                with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'ARCHIVE_INVALID'):segmented.verify_archive(path,pin)
            run.assert_not_called()

    def test_sdk_failure_and_cancellation_cannot_be_replaced_by_file_or_boolean(self):
        from backend import gg_dag_archive as archive
        pin=trusted(packets()['after_next'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.ggdag';path.write_bytes(b'GGDAGAR2')
            with patch.object(archive,'_native_verify',side_effect=ValueError('REAL_VERIFIER_FAILED')) as run:
                with self.assertRaisesRegex(ValueError,'ARCHIVE_INVALID'):segmented.verify_archive(path,pin)
                self.assertEqual(run.call_count,1)
            def cancel():raise ValueError('CANCELLED')
            with patch.object(archive,'_native_verify') as run:
                with self.assertRaisesRegex(ValueError,'ARCHIVE_INVALID'):segmented.verify_archive(path,pin,check=cancel)
                run.assert_not_called()

    def test_bad_pin_paths_and_certificate_floor_are_rejected_before_execution(self):
        from backend import gg_dag_archive as archive
        pin=trusted(packets()['after_next'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'history.ggdag';path.write_bytes(b'GGDAGAR2')
            with patch.object(archive,'_native_verify') as run:
                for options in ({'floor':(True,'a'*64)},{'floor':(0,'a'*64)},{'floor':(1,'x')},
                                {'work_root':path},{'timeout':False},{'timeout':float('nan')}):
                    with self.subTest(options=options),self.assertRaises(ValueError):segmented.verify_archive(path,pin,**options)
                bad=deepcopy(pin);bad['genesis_hash']='0'*64
                with self.assertRaises(ValueError):segmented.verify_archive(path,bad)
                with self.assertRaises(ValueError):segmented.verify_archive(Path('relative.ggdag'),pin)
                run.assert_not_called()

if __name__=='__main__':unittest.main()
