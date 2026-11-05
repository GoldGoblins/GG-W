"""Protected source2 cache/floor policy, with explicitly mocked SDK results.

Actual cross-peer SDK proofs and submission are exercised separately. The
existing protected factory opens genuine encrypted profiles and listeners.
"""
import base64
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from backend.gg_dag_producer_journal import OwnedSegmentedProducer
from backend.gg_segmented_authority import OwnedSegmentedSession
from backend.gg_segmented_proof_sync import SegmentedProofExchange,validate_request
from tests import test_segmented_authority as fixture


class SegmentedProofPolicyTests(unittest.TestCase):
    cleanup=fixture.SegmentedAuthorityPolicyTests.cleanup
    verified=fixture.SegmentedAuthorityPolicyTests.verified

    def setUp(self):
        fixture.SegmentedAuthorityPolicyTests.setUp(self)
        self.peer=self.peers[0]
        # A source2 cache policy seam only: no legacy engine is manufactured.
        # Actual install/negotiation has separate real-runtime tests.
        self.peer._bundle=deepcopy(self.bundle)
        self.exchange=SegmentedProofExchange(self.peer,lambda:tuple(self.controllers),start=False)
        self.addCleanup(self.exchange.close)
        self.packet=self.control.certified_state()

    def base_packet(self):
        packet=deepcopy(self.packet)
        packet['dag_segmented_base_proof']={'schema':'gg.dag.segmented-base-proof.v1','commitment':deepcopy(self.state['dag_segmented']),
            'height':0,'state_root':self.state['state_root'],'genesis_hash':packet['genesis_hash'],'cut':None,'previous_closed':[]}
        return packet

    def test_real_shared_source2_floor_reopens_context_and_own_journal_without_legacy_engine(self):
        self.exchange._accept_certificate(self.packet)
        context=OwnedSegmentedSession(self.owners[0],self.bundle)
        self.assertEqual(context.anchor(),self.control.anchor)
        producer=OwnedSegmentedProducer.open(self.owners[0],self.bundle,self.base_packet(),binary=self.binary,stamp=self.control._stamp,hot_bytes=0)
        try:
            self.assertEqual(producer.snapshot()['pending_count'],0)
            self.assertIsNone(self.peer._engine)
        finally:producer.close()

    def test_unverified_certificate_never_advances_parent_floor_or_public_cache(self):
        with patch.object(self.exchange.verifier,'verify',side_effect=ValueError('GG_PUBLIC_SDK_REJECTION')):
            with self.assertRaises(ValueError):self.exchange._accept_certificate(self.packet)
        self.assertIsNone(self.owners[0].consensus_observation());self.assertIsNone(self.exchange._certificate)

    def test_failed_durable_floor_publishes_no_verified_view(self):
        with patch.object(self.owners[0],'_commit',side_effect=OSError('public injected disk failure')):
            with self.assertRaises(ValueError):self.exchange._accept_certificate(self.packet)
        self.assertIsNone(self.exchange._certificate);self.assertIsNone(self.exchange._view)
        self.assertFalse(self.exchange.snapshot()['canonical_finality'])

    def test_verified_same_height_conflict_stops_shared_owner_before_more_signing(self):
        self.exchange._accept_certificate(self.packet)
        other=deepcopy(self.packet);other['signed_header']['commit']['block_id']['hash']='c'*64
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):self.exchange._accept_certificate(other)
        self.assertEqual(self.owners[0].consensus_observation()['fault'],'GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        self.assertTrue(self.contexts[0].stopped());self.assertFalse(self.exchange.snapshot()['canonical_finality'])

    def test_evicted_base_context_is_unavailable_without_latest_substitution(self):
        self.exchange._accept_certificate(self.packet)
        result=self.exchange.reply(self.exchange._request('base',999))
        self.assertEqual(result,{'state':'UNAVAILABLE'});self.assertFalse(self.exchange.pending)

    def test_pending_queue_and_cache_bytes_are_bounded(self):
        self.exchange._accept_certificate(self.packet)
        for index in range(32):
            self.assertEqual(self.exchange.reply(self.exchange._request('block',1,format(index,'064x'))),{'state':'WAIT'})
        self.assertEqual(self.exchange.reply(self.exchange._request('block',1,'f'*64)),{'state':'BUSY'})
        self.assertEqual(len(self.exchange.pending),32)
        for index in range(80):self.exchange._cache(('public case',index),{'data':'x'*(200*1024)})
        self.assertLessEqual(len(self.exchange.cache),64);self.assertLessEqual(self.exchange.cache_bytes,8*1024*1024)

    def test_request_types_cursor_and_extra_verified_claim_are_rejected(self):
        valid=self.exchange._request('base',1);validate_request(valid)
        for changed in ({**valid,'height':True},{**valid,'verified':True},{**valid,'selector':0},
                        {**valid,'height':0},self.exchange._request('order',1,4095),self.exchange._request('order',1,True)):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):validate_request(changed)

    def test_caller_verified_flag_cannot_bypass_native_verification(self):
        bad=deepcopy(self.packet);bad['verified']=True
        with self.assertRaisesRegex(ValueError,'PROOF_PACKET'):self.exchange.verifier.verify(bad)

    def test_base_wrapper_checks_strict_core_separately_from_native_verified_proof(self):
        packet=self.base_packet()
        self.assertEqual(self.exchange.verifier.verify(packet,'dag_segmented_base_proof'),(1,'b'*64))
        self.exchange._check_proven_base(packet,self.packet,'dag_segmented_base_proof')
        self.assertEqual(set(self.exchange.certificates[1]),{'schema','genesis','genesis_hash','state','signed_header'})

    def test_empty_active_state_derives_all_accounts_only_from_verified_base_proof(self):
        with patch.object(self.exchange,'_fetch',side_effect=[self.packet,self.base_packet()]) as fetch:
            self.exchange._observe(self.peer.public_key)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(self.exchange.snapshot()['certified_accounts'],self.base['accounts'])
        self.assertEqual(self.exchange.snapshot()['proven_blocks'],[])

    def test_unchanged_DAG_commitment_reuses_original_proofs_without_rebinding_their_height(self):
        with patch.object(self.exchange,'_fetch',side_effect=[self.packet,self.base_packet()]):self.exchange._observe(self.peer.public_key)
        previous=self.exchange._view;new=deepcopy(self.packet)
        new['state'].update(height=1,state_root='d'*64);new['signed_header']['header']['height']='2'
        new['signed_header']['commit']['block_id']['hash']='e'*64
        with patch.object(self.exchange,'_fetch',return_value=new) as fetch:self.exchange._observe(self.peer.public_key)
        self.assertEqual(fetch.call_count,1);self.assertIs(self.exchange._view,previous)
        self.assertEqual(self.exchange.snapshot()['certificate_height'],2)
        self.assertEqual(self.exchange.snapshot()['accounts_certificate_height'],1)
        self.assertEqual(self.exchange._view['base_packet']['state']['height'],0)

    def test_authority_worker_exports_exact_captured_packet_and_selector(self):
        public=self.control.anchor['genesis']['dag_segmented']['accounts'][0]
        with patch.object(self.control,'export_proof',return_value={'public':'fixture'}) as export:
            self.control.export_cached_proof(self.packet,'account',public)
        export.assert_called_once_with(account=public,packet=self.packet)
        with self.assertRaisesRegex(ValueError,'PROOF_KIND'):self.control.export_cached_proof(self.packet,'base',0)

    def test_encoded_batch_uses_actual_certified_active_context_and_never_claims_selection(self):
        raw=b'public original block bytes'
        with patch.object(self.control,'submit',return_value={'state':'MEMPOOL_ACCEPTED','SDK_selected':False}) as submit:
            result=self.control.submit_proposals([raw])
        batch=json.loads(submit.call_args.args[0]);active=self.packet['state']['dag_segmented']['active']
        self.assertEqual(base64.b64decode(batch['blocks'][0]),raw)
        self.assertEqual(batch['previous'],active['manifest_hash']);self.assertEqual(batch['sequence'],active['checkpoint']+1)
        self.assertFalse(result['SDK_selected']);self.assertEqual(self.control.snapshot()['certificate_height'],1)

    def test_oversize_batch_is_refused_before_native_query_or_base64_allocation(self):
        raw=b'x'*(32*1024*1024+1)
        with patch.object(self.control,'certified_state') as query:
            with self.assertRaisesRegex(ValueError,'BATCH_LIMIT'):self.control.submit_proposals([raw])
            query.assert_not_called()

    def test_new_shared_epoch_requires_verified_base_before_signing(self):
        producer=OwnedSegmentedProducer.open(self.owners[0],self.bundle,self.base_packet(),binary=self.binary,stamp=self.control._stamp,hot_bytes=0)
        try:
            # Inject the interleaving boundary: the cache published a newer
            # verified epoch before the producer has recovered that base.
            shared=deepcopy(self.packet);shared['state']['dag_segmented']['epoch']='2'
            self.owners[0]._meta['consensus']={'fault':'','packet':shared}
            with patch.object(producer._engine,'produce_lan_test_block') as signing:
                with self.assertRaisesRegex(ValueError,'LATEST_BASE_REQUIRED'):producer.produce(producer._indices[0],1)
                signing.assert_not_called()
            # The reverse publication order must not make an older observer
            # floor block a producer that has already verified its newer base.
            # Isolate that gate; this injection does not claim a real SDK cut.
            shared['state']['dag_segmented']['epoch']='1'
            producer._state()['packet']['state']['dag_segmented']['epoch']='2'
            with patch.object(producer._engine,'produce_lan_test_block',return_value={'public':'gate-only fixture'}) as signing:
                producer.produce(producer._indices[0],1);signing.assert_called_once()
        finally:producer.close()

    def test_cut_request_is_only_native_admission_not_selected_cut(self):
        proposal={'schema':'public cut fixture'}
        with patch.object(self.control,'_query',return_value=proposal) as query,patch.object(self.control,'submit',return_value={'SDK_selected':False}) as submit:
            result=self.control.request_cut()
        query.assert_called_once_with('/gg/dag/cut-proposal')
        self.assertEqual(json.loads(submit.call_args.args[0]),proposal);self.assertFalse(result['SDK_selected'])


if __name__=='__main__':unittest.main()
