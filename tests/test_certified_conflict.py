"""Conflict policy/durability/real LAN transport; SDK boundary mocked here.

The stage's separate native/WASM process runner verifies real quorum signatures.
"""
from copy import deepcopy
import threading
import time
import unittest
from unittest.mock import Mock,patch

from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence,validate_conflict_evidence,CONFLICT,MAX_CONFLICT_BYTES
from backend.gg_dag_proof_sync import ProofExchange,PublicVerifier
from backend.gg_parallel_dag import pack
from tests import test_lan_validator_runtime as fixture
from tests import test_lan_proof_sync as proof_fixture

SERVER_LOOP=ProofExchange._serve_work
CLIENT_LOOP=ProofExchange._client_work


class CertifiedConflictTests(unittest.TestCase):
    cleanup=fixture.ValidatorRuntimeTests.cleanup
    manager=fixture.ValidatorRuntimeTests.manager
    packet=proof_fixture.ProofFloorTests.packet

    def setUp(self):
        fixture.ValidatorRuntimeTests.setUp(self)
        for name in ('_client_work','_serve_work'):
            scope=patch.object(ProofExchange,name,return_value=None);scope.start();self.addCleanup(scope.stop)

    def network(self,role='replica'):
        first=self.manager('Windows');second=self.manager('Linux',bootstrap=first.dispatch('lan.bootstrap'))
        phone=self.manager('Termux',bootstrap=first.dispatch('lan.bootstrap'),node_role=role)
        for manager,prefix in ((first,'Win'),(second,'Lin')):
            for index in (1,2):manager.dispatch('lan.validator_create',{'profile':prefix+str(index)})
        second.dispatch('lan.announce')
        first.dispatch('lan.session_create',{'enable_dag_transactions':True,'enable_consensus':True,'distribute':True})
        return first,second,phone

    def evidence(self,peer,height=2):
        return make_conflict_evidence(self.packet(peer,height,'b'*64),self.packet(peer,height,'c'*64),peer._proof_service.anchor)

    def sdk_boundary(self,exchange):
        scope=patch.object(exchange.verifier,'verify',side_effect=lambda packet,field=None:certificate_tip({key:value for key,value in packet.items() if key in ('schema','genesis','genesis_hash','state','signed_header')},exchange.anchor))
        scope.start();self.addCleanup(scope.stop);return scope

    def test_evidence_is_versioned_bounded_pinned_and_exactly_two_conflicting_blocks(self):
        _,_,phone=self.network();peer=phone._peer;evidence=self.evidence(peer);anchor=peer._proof_service.anchor
        self.assertLess(len(pack(evidence)),MAX_CONFLICT_BYTES)
        self.assertEqual(validate_conflict_evidence(evidence,anchor),evidence)
        bad=[]
        value=deepcopy(evidence);value['certificates'][1]=deepcopy(value['certificates'][0]);bad.append(value)
        value=deepcopy(evidence);value['certificates'].reverse();bad.append(value)
        value=deepcopy(evidence);value['height']+=1;bad.append(value)
        value=deepcopy(evidence);value['genesis_hash']='f'*64;bad.append(value)
        value=deepcopy(evidence);value['certificates'].pop();bad.append(value)
        value=deepcopy(evidence);value['url']='https://example.invalid';bad.append(value)
        value=deepcopy(evidence);value['certificates'][0]['state']['padding']='x'*MAX_CONFLICT_BYTES;bad.append(value)
        for value in bad:
            with self.assertRaisesRegex(ValueError,'CONFLICT_EVIDENCE'):validate_conflict_evidence(value,anchor)

    def test_second_invalid_sdk_certificate_cannot_poison_floor_or_halt_sources(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;evidence=self.evidence(peer)
        source=Mock();exchange.sources=lambda:(source,)
        with patch.object(exchange.verifier,'verify',side_effect=[(2,'b'*64),ValueError('GG_FIXTURE_SDK_REJECTED')]) as verifier:
            with self.assertRaisesRegex(ValueError,'SDK_REJECTED'):exchange._accept_conflict(evidence)
        self.assertEqual(verifier.call_count,2);self.assertEqual(exchange._fault,'')
        self.assertIsNone(exchange.cached_conflict());self.assertIsNone(peer._profile.consensus_observation())
        source.observe_conflict.assert_not_called()

    def test_cache_never_silently_overwrites_same_height_conflict(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;self.sdk_boundary(exchange)
        first=self.packet(peer);exchange._remember(first)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):exchange._remember(self.packet(peer,2,'c'*64))
        self.assertEqual(exchange.certificates[2],first)
        self.assertEqual(exchange.snapshot()['state'],'FAULT');self.assertFalse(exchange.snapshot()['canonical_finality'])
        self.assertEqual(peer._profile.consensus_observation()['evidence'],exchange.cached_conflict())

    def test_older_certified_conflict_preserves_newer_durable_floor_and_identity(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;self.sdk_boundary(exchange)
        exchange._accept_certificate(self.packet(peer,2));latest=self.packet(peer,7)
        exchange._accept_certificate(latest);invite=peer.public_invite()
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):exchange._accept_certificate(self.packet(peer,2,'c'*64))
        record=peer._profile.consensus_observation();self.assertEqual(record['packet'],latest)
        self.assertEqual(record['evidence']['height'],2);self.assertEqual(record['schema'],'gg.dag.replica-floor.v2')
        phone.stop();phone.dispatch('lan.resume',{'profile':'Termux'})
        self.assertEqual(phone._peer.public_invite(),invite);self.assertEqual(phone._peer._profile.consensus_observation(),record)

    def test_same_block_with_different_valid_commit_signature_sets_is_not_a_conflict(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;self.sdk_boundary(exchange)
        packet=self.packet(peer);exchange._accept_certificate(packet)
        variant=deepcopy(packet);variant['signed_header']['commit']['signatures']=['different SDK-approved fixture representation']
        exchange._accept_certificate(variant)
        proven={**variant,'dag_order_page':{}}
        exchange._check_proven_base(proven,packet,'dag_order_page')
        self.assertEqual(exchange._fault,'');self.assertIsNone(exchange.cached_conflict())
        self.assertEqual(peer._profile.consensus_observation()['packet'],packet)

    def assert_authenticated_fault(self,role):
        first,_,phone=self.network(role);provider=first._peer._proof_service;observer=phone._peer._proof_service
        self.sdk_boundary(provider);self.sdk_boundary(observer)
        evidence=self.evidence(first._peer);provider._accept_conflict(evidence)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):
            observer._fetch(first._peer.public_key,observer._request('certificate'),time.monotonic()+3)
        self.assertEqual(observer.cached_conflict(),evidence)
        self.assertEqual(phone._peer._profile.consensus_observation()['fault'],CONFLICT)
        self.assertEqual(len(phone._peer._engine._records),1);self.assertIsNone(observer.canonical_membership())

    def test_authenticated_fault_evidence_reaches_replica_without_payload_admission(self):self.assert_authenticated_fault('replica')

    def test_authenticated_fault_evidence_reaches_light_without_payload_admission(self):self.assert_authenticated_fault('light')

    def test_naked_or_unverified_remote_accusation_does_not_latch_fault(self):
        first,_,phone=self.network();provider=first._peer._proof_service;observer=phone._peer._proof_service
        request=observer._request('certificate')
        with patch.object(provider,'reply',return_value={'state':'FAULT'}):
            with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):observer._fetch(first._peer.public_key,request,time.monotonic()+3)
        self.assertEqual(observer._fault,'');self.assertIsNone(phone._peer._profile.consensus_observation())
        evidence=self.evidence(first._peer)
        with patch.object(provider,'reply',return_value={'state':'FAULT','evidence':evidence}),patch.object(observer.verifier,'verify',side_effect=ValueError('GG_FIXTURE_SDK_REJECTED')):
            with self.assertRaisesRegex(ValueError,'SDK_REJECTED'):observer._fetch(first._peer.public_key,request,time.monotonic()+3)
        self.assertEqual(observer._fault,'');self.assertIsNone(phone._peer._profile.consensus_observation())

    def test_two_local_controllers_trigger_durable_stop_and_keep_handlers_responsive(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;self.sdk_boundary(exchange)
        sources=[Mock(),Mock()]
        for index,source in enumerate(sources):
            source.snapshot.return_value={'owned_native_process':True};source.cached_conflict.return_value=None
            source.cached_certificate.return_value=self.packet(peer,2,('b' if index==0 else 'c')*64)
        exchange.sources=lambda:tuple(sources)
        worker=threading.Thread(target=SERVER_LOOP,args=(exchange,));worker.start()
        try:
            deadline=time.monotonic()+2
            while (not exchange._fault or any(not source.observe_conflict.called for source in sources)) and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(exchange._fault,CONFLICT)
            for source in sources:source.observe_conflict.assert_called_once_with(exchange.cached_conflict())
            started=time.monotonic();reply=exchange.reply(exchange._request('certificate'))
            self.assertLess(time.monotonic()-started,.1);self.assertEqual(reply['state'],'FAULT')
            self.assertEqual(reply['evidence'],peer._profile.consensus_observation()['evidence'])
        finally:exchange.request_stop();worker.join(2)
        self.assertFalse(worker.is_alive())

    def assert_failed_floor_write(self,after):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;self.sdk_boundary(exchange)
        evidence=self.evidence(peer);profile=peer._profile;commit=profile._commit;invite=peer.public_invite()
        def failed():
            if after:commit()
            raise OSError('owned injected evidence commit outcome')
        with patch.object(profile,'_commit',side_effect=failed):
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):exchange._accept_conflict(evidence)
        self.assertIsNone(exchange.cached_conflict());self.assertFalse(exchange.snapshot()['canonical_finality'])
        phone.stop();phone.dispatch('lan.resume',{'profile':'Termux'})
        self.assertEqual(phone._peer.public_invite(),invite)
        restored=phone._peer._profile.consensus_observation()
        if after:self.assertEqual(restored['evidence'],evidence)
        else:self.assertIsNone(restored)

    def test_fault_write_failure_before_commit_does_not_invent_durable_ack(self):self.assert_failed_floor_write(False)

    def test_lost_fault_write_return_recovers_exact_durable_evidence(self):self.assert_failed_floor_write(True)

    def test_reload_independently_sdk_verifies_both_stored_certificates_before_advertising(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;evidence=self.evidence(peer)
        peer._profile.save_consensus_conflict(evidence)
        with patch.object(exchange.verifier,'verify',side_effect=lambda packet,field=None:certificate_tip(packet,exchange.anchor)) as verifier:
            CLIENT_LOOP(exchange)
        self.assertEqual(verifier.call_count,3);self.assertEqual(exchange.cached_conflict(),evidence)
        self.assertEqual(exchange.reply(exchange._request('certificate')),{'state':'FAULT','evidence':evidence})

    def test_reload_cannot_advertise_saved_evidence_rejected_by_sdk(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;evidence=self.evidence(peer)
        peer._profile.save_consensus_conflict(evidence)
        with patch.object(exchange.verifier,'verify',side_effect=[(2,'b'*64),(2,'b'*64),ValueError('GG_FIXTURE_SDK_REJECTED')]):
            CLIENT_LOOP(exchange)
        self.assertIsNone(exchange.cached_conflict());self.assertFalse(exchange.snapshot()['canonical_finality'])
        self.assertEqual(exchange.reply(exchange._request('certificate')),{'state':'FAULT'})

    def test_first_durable_evidence_is_reverified_and_advertised_exactly_after_a_new_pair(self):
        _,_,phone=self.network();peer=phone._peer;exchange=peer._proof_service;self.sdk_boundary(exchange)
        first=self.evidence(peer);peer._profile.save_consensus_conflict(first)
        newer=make_conflict_evidence(self.packet(peer,3,'d'*64),self.packet(peer,3,'e'*64),exchange.anchor)
        exchange._accept_conflict(newer)
        self.assertEqual(exchange.cached_conflict(),first)
        self.assertEqual(exchange.reply(exchange._request('certificate'))['evidence'],peer._profile.consensus_observation()['evidence'])


if __name__=='__main__':unittest.main()
