"""Certified-base codec/adapter tests; mocked projection is not SDK evidence.

The distributed vectors use native application state and valid test signatures.
Actual four-process SDK, native and WASM acceptance run in a separate gate.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backend import gg_consensus as native, gg_dag_segmented as segmented


def vectors():
    value=json.loads((Path(__file__).parent/'data/dag_segmented_base_vectors.json').read_text(encoding='utf-8'))
    assert value['schema']=='gg.public.segmented-base-test-vectors.v1'
    return value


def pin(packet):return {key:deepcopy(packet[key]) for key in ('genesis','genesis_hash')}


def reply(data,name):
    """A projection seam, not a substitute for invoking the SDK verifier."""
    return {'dag_segmented_base_proof_verified':True,'dag_segmented_base_scope':segmented.BASE_SCOPE,
            'dag_history_replay_verified':False,'dag_segmented_commitment':deepcopy(data['packets'][name]['state']['dag_segmented']),
            'dag_segmented_epoch_base':deepcopy(data['bases'][name])}


class SegmentedBaseAdapterTests(unittest.TestCase):
    def test_public_vectors_cover_genesis_active_epochs_and_two_cuts(self):
        data=vectors()
        self.assertEqual(set(data['packets']),{'genesis','before_cut','after_cut','second_cut','after_next'})
        for name,packet in data['packets'].items():
            with self.subTest(name=name):
                source=segmented.validate_source(packet['genesis']['dag_segmented'])
                base=data['bases'][name]
                segmented.validate_state(base['commitment'],source,packet['genesis_hash'])
                segmented._archive_accounts(base['accounts'],base['commitment'],source)
                self.assertEqual(base['commitment']['active']['blocks'],0)
                self.assertEqual(base['commitment']['epoch'],packet['state']['dag_segmented']['epoch'])
        self.assertEqual(data['bases']['after_next']['commitment']['transactions'],'5003')
        self.assertEqual(data['packets']['after_next']['state']['dag_segmented']['transactions'],'5004')

    def test_projection_invokes_pinned_native_and_returns_owned_derived_base(self):
        data=vectors();packet=data['packets']['after_next'];result=reply(data,'after_next')
        with patch.object(native,'_verify_public',return_value=result) as verify:
            view=segmented.verify_epoch_base(packet,pin(packet),binary=Path('owned-native'),stamp=(12,34))
        verify.assert_called_once_with(packet,Path('owned-native'),(12,34))
        self.assertEqual(view['base'],data['bases']['after_next'])
        self.assertEqual(view['verification_scope'],segmented.BASE_SCOPE)
        self.assertFalse(view['history_replayed']);self.assertTrue(view['producer_owned_nonfinancial'])
        result['dag_segmented_epoch_base']['accounts'][0]['nonce']=0
        self.assertNotEqual(view['base'],result['dag_segmented_epoch_base'])

    def test_native_rejection_cannot_be_replaced_by_a_caller_verified_flag(self):
        packet=vectors()['packets']['after_next'];packet['verified']=True
        packet['dag_segmented_base_proof_verified']=True
        with patch.object(native,'_verify_public',side_effect=ValueError('REAL_NATIVE_REJECTION')) as verify:
            with self.assertRaisesRegex(ValueError,'GG_DAG_SEGMENTED_BASE_INVALID'):
                segmented.verify_epoch_base(packet,pin(packet),binary=Path('owned-native'))
            self.assertEqual(verify.call_count,1)

    def test_missing_base_or_wrong_pin_fails_before_native_execution(self):
        data=vectors();packet=data['packets']['after_next']
        for kind in ('missing','null','wrong_pin','extra_producer'):
            bad=deepcopy(packet);trust=pin(packet)
            if kind=='missing':del bad['dag_segmented_base_proof']
            elif kind=='null':bad['dag_segmented_base_proof']=None
            elif kind=='wrong_pin':trust['genesis_hash']='0'*64
            else:bad['state']['dag_segmented']['authors'].append(deepcopy(bad['state']['dag_segmented']['authors'][0]))
            with self.subTest(kind=kind),patch.object(native,'_verify_public') as verify:
                with self.assertRaises(ValueError):segmented.verify_epoch_base(bad,trust,binary=Path('owned-native'))
                verify.assert_not_called()

    def test_incomplete_or_mislabelled_native_result_cannot_publish_a_base(self):
        data=vectors();packet=data['packets']['after_next']
        for kind in ('unverified','scope','history','context','absent','extra','not_empty','wrong_epoch','wrong_cut','wrong_closed','block_offset','bad_account'):
            result=reply(data,'after_next')
            if kind=='unverified':result['dag_segmented_base_proof_verified']=False
            elif kind=='scope':result['dag_segmented_base_scope']='FULL_HISTORY'
            elif kind=='history':result['dag_history_replay_verified']=True
            elif kind=='context':result['dag_segmented_commitment']['transactions']='5005'
            elif kind=='absent':del result['dag_segmented_epoch_base']
            elif kind=='extra':result['dag_segmented_epoch_base']['trusted_snapshot']=True
            elif kind=='bad_account':result['dag_segmented_epoch_base']['accounts'][0]['nonce']+=1
            else:
                state=result['dag_segmented_epoch_base']['commitment']
                if kind=='not_empty':state['active']['blocks']=1
                elif kind=='wrong_epoch':state['epoch']='4'
                elif kind=='wrong_cut':state['last_cut']='0'*64
                elif kind=='wrong_closed':state['closed_root']='0'*64
                elif kind=='block_offset':state['blocks']='1'
            with self.subTest(kind=kind),patch.object(native,'_verify_public',return_value=result):
                with self.assertRaisesRegex(ValueError,'GG_DAG_SEGMENTED_BASE_INVALID'):
                    segmented.verify_epoch_base(packet,pin(packet),binary=Path('owned-native'))

    def test_default_binary_must_be_validated_before_native_proof_execution(self):
        data=vectors();packet=data['packets']['genesis']
        with patch.object(native,'BINARY',Path('owned-default')),patch.object(native,'_validate_binary',return_value=(1,2)) as validate,\
                patch.object(native,'_verify_public',return_value=reply(data,'genesis')) as verify:
            segmented.verify_epoch_base(packet,pin(packet))
        validate.assert_called_once_with();verify.assert_called_once_with(packet,Path('owned-default'),(1,2))

    def test_export_uses_owned_sdk_exact_certificate_and_proof_height(self):
        packet=vectors()['packets']['after_next'];height=packet['state']['height']
        with patch.object(native,'_genesis',packet['genesis']),patch.object(native,'_genesis_hash',packet['genesis_hash']),\
                patch.object(native,'_verified_state',return_value=(2,packet['state'],{'certificate_height':height+1})),\
                patch.object(native,'_rpc',return_value={'signed_header':packet['signed_header']}) as rpc,\
                patch.object(native,'_query',return_value=packet['dag_segmented_base_proof']) as query,\
                patch.object(segmented,'verify_epoch_base',return_value={}) as verify:
            exported=native.export_dag_base_proof()
        rpc.assert_called_once_with(2,'commit',{'height':str(height+1)})
        query.assert_called_once_with(2,'/gg/dag/base-proof',height,None)
        self.assertEqual(exported['dag_segmented_base_proof'],packet['dag_segmented_base_proof'])
        self.assertNotIn('dag_account_proof',exported);verify.assert_called_once()
        self.assertEqual(verify.call_args.args[1],pin(packet))

    def test_export_fails_closed_for_old_network_and_for_rejected_base(self):
        packet=vectors()['packets']['after_next']
        for genesis in (None,{'schema':'gg.native.genesis.v3','dag':{}}):
            with patch.object(native,'_genesis',genesis),patch.object(native,'_verified_state') as state:
                with self.assertRaisesRegex(ValueError,'NOT_CONFIGURED'):native.export_dag_base_proof()
                state.assert_not_called()
        with patch.object(native,'_genesis',packet['genesis']),patch.object(native,'_genesis_hash',packet['genesis_hash']),\
                patch.object(native,'_verified_state',return_value=(0,packet['state'],{'certificate_height':packet['state']['height']+1})),\
                patch.object(native,'_rpc',return_value={'signed_header':packet['signed_header']}),\
                patch.object(native,'_query',return_value=packet['dag_segmented_base_proof']),\
                patch.object(segmented,'verify_epoch_base',side_effect=ValueError('BASE_INVALID')):
            with self.assertRaisesRegex(ValueError,'BASE_INVALID'):native.export_dag_base_proof()


if __name__=='__main__':unittest.main()
