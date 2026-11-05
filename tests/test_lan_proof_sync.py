"""Transport integrity and policy tests; these do not fake SDK quorum evidence."""
from copy import deepcopy
import hashlib
import threading
import time
import unittest
from unittest.mock import Mock,patch
from backend.gg_dag_proof_sync import PublicVerifier,ProofExchange,validate_request
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_parallel_dag import pack
from backend.lan_dag_runtime import LanDagRuntime
from tests.test_lan_consensus_anchor import paired_peers,member_invites
from tests import test_lan_validator_runtime as fixture


class ProofTransportTests(unittest.TestCase):
    def test_finished_proof_wakes_telemetry_even_when_transport_is_unchanged(self):
        manager=LanDagRuntime();peer=Mock();peer.telemetry_revision.return_value=('unchanged transport',)
        exchange=Mock();peer._proof_service=exchange;manager._peer=peer
        exchange.telemetry_revision.return_value=('SDK_PROOFS',2,None)
        before=manager.telemetry_revision()
        exchange.telemetry_revision.return_value=('SDK_PROOFS',2,2)
        self.assertNotEqual(manager.telemetry_revision(),before)
        exchange.snapshot.assert_not_called()

    def test_actual_authenticated_fragments_carry_bounded_public_data_without_dag_admission(self):
        peers=paired_peers(self);bundle=peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=member_invites(peers))
        for peer in peers:peer.install_session(bundle,_start_gossip=False)
        anchor=anchor_from_owned_peer(peers[0]);expected={'state':'READY','packet':{'transport_only_fixture':'x'*90000}}
        provider=Mock();provider.reply.return_value=expected;peers[0]._proof_service=provider
        provider.request_stop=Mock();provider.close=Mock()
        request={'kind':'certificate','genesis_hash':anchor['genesis_hash'],'height':0,'selector':''}
        received=peers[2].public_consensus_proof(peers[0].public_key,request)
        self.assertEqual(received,expected);self.assertEqual(len(peers[2]._engine._records),1)
        provider.reply.assert_called_once_with(request)

    def test_requests_are_strict_bounded_and_cannot_smuggle_packets_or_targets(self):
        valid={'kind':'certificate','genesis_hash':'a'*64,'height':0,'selector':''}
        for mutation in ({'height':True},{'height':1},{'kind':'wallet_sign'},{'genesis_hash':'x'},
                         {'selector':{'packet':'anything'}},{'url':'https://example.invalid'}):
            with self.assertRaisesRegex(ValueError,'PROOF_REQUEST'):validate_request({**valid,**mutation})
        for selector in (True,-1,1,4096,'0'):
            with self.assertRaises(ValueError):validate_request({**valid,'kind':'order','height':1,'selector':selector})


class ProofFloorTests(unittest.TestCase):
    setUp=fixture.ValidatorRuntimeTests.setUp
    cleanup=fixture.ValidatorRuntimeTests.cleanup
    manager=fixture.ValidatorRuntimeTests.manager
    network=fixture.ValidatorRuntimeTests.network

    def packet(self,peer,height=2,identifier='b'*64):
        anchor=anchor_from_owned_peer(peer)
        return {'schema':'gg.consensus.proof.v1',**anchor,'state':{'height':height-1,'state_root':'a'*64,'dag':{'blocks':0,'transactions':0}},
                'signed_header':{'header':{'height':str(height)},'commit':{'block_id':{'hash':identifier}}}}

    def test_structural_floor_persists_and_rewind_or_same_height_conflict_cannot_replace_it(self):
        first,second,phone,_=self.network();peer=phone._peer;packet=self.packet(peer)
        peer._profile.save_consensus_certificate(packet)
        with self.assertRaisesRegex(ValueError,'REWIND'):peer._profile.save_consensus_certificate(self.packet(peer,1))
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):peer._profile.save_consensus_certificate(self.packet(peer,2,'c'*64))
        self.assertEqual(peer._profile.consensus_observation()['packet'],packet)
        phone.stop();phone.dispatch('lan.resume',{'profile':'Termux'})
        self.assertEqual(phone._peer._profile.consensus_observation()['fault'],'GG_CONSENSUS_CONFLICTING_CERTIFICATE')

    def test_invalid_sdk_proof_cannot_poison_durable_floor_or_publish_accounts(self):
        first,second,phone,_=self.network();exchange=phone._peer._proof_service
        with patch.object(exchange.verifier,'verify',side_effect=ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')):
            with self.assertRaisesRegex(ValueError,'CERTIFICATE_INVALID'):exchange._accept_certificate(self.packet(phone._peer))
        self.assertIsNone(phone._peer._profile.consensus_observation())
        self.assertEqual(exchange.snapshot()['certified_accounts'],[])

    def test_failed_floor_commit_precedes_publication(self):
        _,_,phone,_=self.network();exchange=phone._peer._proof_service;packet=self.packet(phone._peer)
        with patch.object(exchange.verifier,'verify',return_value=(2,'b'*64)),patch.object(phone._peer._profile,'_commit',side_effect=OSError('owned floor write failure')):
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):exchange._accept_certificate(packet)
        self.assertIsNone(exchange._certificate);self.assertIsNone(phone._peer._profile.consensus_observation())

    def test_snapshot_publishes_one_coherent_certificate_pair_during_a_floor_change(self):
        _,_,phone,_=self.network();exchange=phone._peer._proof_service;packet=self.packet(phone._peer)
        with patch.object(exchange.verifier,'verify',return_value=(2,'b'*64)):exchange._accept_certificate(packet)
        exchange._floor=(3,'c'*64) # An internal advance before the next public pair is ready.
        value=exchange.snapshot()
        self.assertEqual(value['certificate_height'],2);self.assertEqual(value['certificate_id'],'b'*64)
        self.assertEqual(value['dag_commitment'],packet['state']['dag'])

    def test_blocked_native_query_does_not_block_handler_and_pending_queue_is_bounded(self):
        _,_,phone,_=self.network();peer=phone._peer;packet=self.packet(peer)
        entered=threading.Event();release=threading.Event();source=Mock()
        source.snapshot.return_value={'owned_native_process':True};source.cached_certificate.return_value=packet
        def blocked(*args):entered.set();release.wait(3);raise ValueError('GG_PUBLIC_QUEUE_FIXTURE')
        source.export_cached_proof.side_effect=blocked
        with patch.object(ProofExchange,'_client_work',return_value=None):exchange=ProofExchange(peer,lambda:(source,))
        try:
            deadline=time.monotonic()+1
            while exchange.latest_local is None and time.monotonic()<deadline:time.sleep(.01)
            first={'kind':'block','genesis_hash':packet['genesis_hash'],'height':2,'selector':'0'*64}
            self.assertEqual(exchange.reply(first),{'state':'WAIT'});self.assertTrue(entered.wait(1))
            started=time.monotonic()
            for index in range(32):
                result=exchange.reply({**first,'selector':hashlib.sha256(str(index).encode()).hexdigest()})
                self.assertEqual(result,{'state':'WAIT'})
            self.assertEqual(exchange.reply({**first,'selector':'f'*64}),{'state':'BUSY'})
            self.assertLess(time.monotonic()-started,.2);self.assertEqual(len(exchange.pending),32)
        finally:release.set();exchange.close()


if __name__=='__main__':unittest.main()
