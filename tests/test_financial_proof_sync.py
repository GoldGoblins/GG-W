"""Signed financial LAN installation and bounded proof/transport policy.

No mocked packet is presented as a verified certificate. Native SDK execution
and cross-peer proof verification run in the owned integration harness.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend import gg_node_store as nodes,gg_consensus_profile as validators,portable_wallet_vault as vault
from backend import gg_financial_proof_sync as proofs
from tests.test_financial_authority import protected_financial_network


class FinancialProofPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-financial-proof-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('public financial proof test vault'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.owners,self.peers,self.profiles,self.bundle,self.contexts=protected_financial_network();self.addCleanup(self.cleanup)
        for peer in self.peers:peer.install_session(self.bundle,_start_gossip=False)

    def cleanup(self):
        for profile in self.profiles:profile.close()
        for peer in self.peers:peer.stop()
        for owner in self.owners:owner.close()

    def test_install_uses_real_identity_and_never_installs_nonfinancial_engine(self):
        for peer in self.peers:
            snapshot=peer.snapshot()
            self.assertIsNone(peer._engine)
            self.assertEqual(snapshot['mode'],'FINANCIAL_SDK_CERTIFIED_VIEW')
            self.assertEqual(snapshot['state'],'WAITING_FOR_CERTIFICATE')
            self.assertEqual(snapshot['financial_accounts'],[])
            self.assertFalse(snapshot['dag_proofs']['canonical_finality'])
            self.assertFalse(snapshot['dag_proofs']['certificate_is_network_liveness'])
            self.assertEqual(len(snapshot['producers']),6)
            self.assertEqual(snapshot['lan']['producer_count'],4)
            self.assertEqual(snapshot['lan']['participation']['eligible_network_producers'],4)
            self.assertEqual(sum(row['producer_enabled'] for row in snapshot['producers']),4)
            self.assertEqual({row['node_label'] for row in snapshot['producers']},{'Windows','Linux','Termux'})
            self.assertTrue(all(row['proposals'] is None and row['transactions'] is None for row in snapshot['producers']))
            self.assertEqual(snapshot['block_graph']['edges'],[])

    def test_counter_only_production_is_disabled_for_financial_session(self):
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_ACCOUNT_SIGNED_PAYMENTS_REQUIRED'):self.peers[0].start_dag_production(1000,5000,0)
        self.assertFalse(self.peers[0].snapshot()['dag_stress']['can_start'])
        with self.assertRaisesRegex(ValueError,'GG_LAN_REPLICA_READ_ONLY'):self.peers[2]._proof_service.submit_signed([],0)
        with self.assertRaisesRegex(ValueError,'GG_LAN_REPLICA_READ_ONLY'):self.peers[2]._proof_service.resume_signed()
        with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_OWN_PRODUCER_REQUIRED'):self.peers[0]._proof_service.resume_signed((self.peers[0]._local_indices[0]+2)%6)

    def test_proof_request_shape_and_selector_cannot_choose_another_network(self):
        peer=self.peers[0];request={'kind':'producer','genesis_hash':peer._proof_service.anchor['genesis_hash'],'height':1,'selector':0}
        self.assertEqual(proofs.validate_request(request),request)
        for change in ({'selector':True},{'selector':6},{'height':0},{'kind':'wallet-sign'},{'verified':True}):
            value={**request,**change}
            with self.assertRaises(ValueError):proofs.validate_request(value)
        foreign={**request,'genesis_hash':'0'*64}
        with self.assertRaisesRegex(ValueError,'GG_PROOF_ANCHOR'):peer._proof_service.reply(foreign)
        self.assertEqual(proofs.parse_receipt_selector('a'*64+':49999'),('a'*64,49999))
        for value in ('a'*64+':50000','a'*64+':01','a'*64+':-1'):
            with self.assertRaises(ValueError):proofs.parse_receipt_selector(value)

    def test_sender_identity_reaches_native_financial_submission_unchanged(self):
        service=self.peers[0]._proof_service;node=Mock();node.submit_proposals.return_value={'SDK_selected':False}
        actor=self.peers[1].public_key;raw=b'public transport bytes'
        self.assertEqual(service.submissions._submit(node,actor,raw),{'SDK_selected':False})
        node.submit_proposals.assert_called_once_with(actor,[raw])

    def owned_input(self):
        # SDK lookup and queue are policy seams. Actual transport/consensus
        # runs separately; all profile, account and producer signatures here
        # are real and no synthetic certificate enters the public view.
        from tests.test_financial_producer import structural_context
        from backend import gg_financial_dag as financial
        from backend.gg_parallel_dag import pack
        peer=self.peers[0];service=peer._proof_service;index=peer._local_indices[0]
        context=next(item for item in self.contexts if item.public_key==peer.public_key)
        packet=structural_context(context,index)
        member=next(profile for profile in self.profiles if profile.public_invite()['body']['owner_peer_key']==peer.public_key)
        sender=member.public_invite()['body']['account_key'];recipient=next(key for key in service.anchor['genesis']['accounts'] if key!=sender)
        body={'version':1,'amount_atomic':'1','chain_id':service.anchor['genesis']['chain_id'],'genesis_hash':service.anchor['genesis_hash'],
            'sender':sender,'recipient':recipient,'nonce':0}
        payment={'body':body,'signature':member._keys[2].sign_message(pack(body)).hex()}
        return service,index,payment,packet

    def test_warm_owned_pipeline_reuses_writer_and_preserves_original_prefix(self):
        from backend import gg_financial_dag as financial
        service,index,payment,packet=self.owned_input()
        opened=proofs.OwnedFinancialProducer.open
        with patch.object(service,'requested_proof',return_value=packet),patch.object(financial,'verify_producer',return_value={'SDK_policy_seam':True}), \
                patch.object(proofs.OwnedFinancialProducer,'open',wraps=opened) as opening,patch.object(service._retry,'start'), \
                patch.object(service.submissions,'_sources',return_value=(object(),)),patch.object(service.submissions,'local',return_value={'state':'QUEUED'}):
            first=service.submit_signed([payment],index,transactions_per_block=1)
            second=service.submit_signed([payment]*3,index,transactions_per_block=1)
        self.assertEqual(opening.call_count,1);self.assertEqual(second['blocks'][0],first['blocks'][0])
        self.assertEqual(len(second['blocks']),3);self.assertEqual(service._writer.snapshot()['originals'],3)
        self.assertFalse(second['SDK_selected']);self.assertFalse(second['payments_executed_asserted'])
        self.assertFalse(service.snapshot()['canonical_finality'])

    def test_initial_transport_timeout_or_resource_pause_keeps_durable_automatic_retry(self):
        from backend import gg_financial_dag as financial
        service,index,payment,packet=self.owned_input()
        with patch.object(service,'requested_proof',return_value=packet) as request,patch.object(financial,'verify_producer',return_value={'SDK_policy_seam':True}),patch.object(service._retry,'start') as retry:
            for error in (OSError('owned IO seam'),ValueError('GG_SDK_SUBMISSION_DEADLINE'),ValueError('GG_DAG_RESOURCE_PAUSED')):
                with patch.object(service,'_send_originals',side_effect=error):
                    result=service.submit_signed([payment],index,transactions_per_block=1)
                self.assertEqual(result['state'],'UNAVAILABLE');self.assertTrue(result['original_durable']);self.assertTrue(result['automatic_retry'])
                self.assertFalse(result['SDK_selected']);self.assertEqual(service._writer.snapshot()['originals'],1)
                self.assertIs(request.call_args.kwargs['cancel'],service._producer_cancel)
            self.assertEqual(retry.call_count,3)

    def test_retry_status_changes_telemetry_without_new_certificate(self):
        service=self.peers[0]._proof_service;first=service.telemetry_revision()
        with patch.object(service._retry,'snapshot',return_value={'state':'EXHAUSTED','worker_active':False,'attempts':16,'last_error':''}):
            self.assertNotEqual(first,service.telemetry_revision());self.assertEqual(service.snapshot()['production']['state'],'EXHAUSTED')

    def test_transport_fails_over_unavailable_busy_or_io_owner_with_exact_same_raw(self):
        # Routing policy seam only; arbitrary test bytes are not SDK evidence.
        import time
        service=self.peers[2]._proof_service;raw=b'public routing policy seam';owners=sorted({item['body']['owner_peer_key'] for item in service.anchor['genesis']['membership']['validators']})
        with patch.object(service.submissions,'_sources',return_value=()):
            for first in ({'state':'UNAVAILABLE'},{'state':'BUSY'},OSError('owned transport seam')):
                service._submission_turn=0
                with patch.object(service.submissions,'send',side_effect=[first,{'state':'QUEUED','SDK_selected':False}]) as send:
                    result=service._send_originals([{'wire':raw}],lambda:None,service._producer_cancel,time.monotonic()+20)
                self.assertEqual(result['state'],'QUEUED');self.assertEqual([call.args[0] for call in send.call_args_list],owners)
                self.assertTrue(all(call.args[1]==raw for call in send.call_args_list))

    def test_transport_rotates_after_a_full_deadline_and_never_masks_stop(self):
        service=self.peers[2]._proof_service;clock=[0];calls=[]
        owners=sorted({item['body']['owner_peer_key'] for item in service.anchor['genesis']['membership']['validators']})
        def send(owner,*args,**kwargs):
            calls.append(owner)
            if len(calls)==1:clock[0]=20;raise ValueError('GG_SDK_SUBMISSION_DEADLINE')
            return {'state':'QUEUED','SDK_selected':False}
        with patch.object(service.submissions,'_sources',return_value=()),patch.object(service.submissions,'send',side_effect=send),patch.object(proofs.time,'monotonic',side_effect=lambda:clock[0]):
            self.assertEqual(service._send_originals([{'wire':b'public routing seam'}],lambda:None,service._producer_cancel,20)['state'],'UNAVAILABLE')
            self.assertEqual(service._send_originals([{'wire':b'public routing seam'}],lambda:None,service._producer_cancel,40)['state'],'QUEUED')
        self.assertEqual(calls,owners)
        with patch.object(service.submissions,'_sources',return_value=()),patch.object(service.submissions,'send',side_effect=ValueError('GG_LAN_STOPPED')) as stopped:
            with self.assertRaisesRegex(ValueError,'GG_LAN_STOPPED'):service._send_originals([{'wire':b'public routing seam'}],lambda:None,service._producer_cancel,float('inf'))
        self.assertEqual(stopped.call_count,1)

    def test_install_does_not_start_workers_until_requested(self):
        for peer in self.peers:
            service=peer._proof_service
            self.assertIsNone(service.server.ident);self.assertIsNone(service.client.ident);self.assertIsNone(service.submissions.worker.ident)
        changed=deepcopy(self.bundle);changed['body']['label']='not coordinator signed'
        with self.assertRaises(ValueError):self.peers[0].install_session(changed,_start_gossip=False)

    def test_error_observation_keeps_real_text_and_transport_counters(self):
        peer=self.peers[0];peer._last_error='GG_PUBLIC_FIXTURE_ERROR'
        view=peer.snapshot()['lan']
        self.assertEqual(view['last_error'],'GG_PUBLIC_FIXTURE_ERROR')
        self.assertEqual(view['traffic_bytes_basis'],'APPLICATION_TCP_READ_BYTES')


if __name__=='__main__':unittest.main()
