"""Real signed old/new domains and protected pending-intent recovery."""
from copy import deepcopy
import hashlib
import secrets
import socket
import unittest
from unittest.mock import patch

from backend import gg_network_transition as transition,gg_node_store as nodes,gg_consensus_profile as validators,gg_lan_dag as lan
from backend.gg_consensus_membership import anchor_from_bundle
from backend.gg_dag_segmented_session import make_bundle,validate_bundle
from backend.gg_dag_proof_sync import ProofExchange
from backend.gg_ed25519 import Keypair
from tests import test_lan_segmented_runtime as fixture


class NetworkTransitionContractTests(unittest.TestCase):
    cleanup=fixture.SegmentedRuntimeTests.cleanup
    manager=fixture.SegmentedRuntimeTests.manager
    network=fixture.SegmentedRuntimeTests.network

    def setUp(self):
        fixture.SegmentedRuntimeTests.setUp(self)
        self.stack.enter_context(patch.object(ProofExchange,'_serve_work'))
        self.stack.enter_context(patch.object(ProofExchange,'_client_work'))
        self.stack.enter_context(patch.object(lan.LanDagPeer,'_start_gossip'))
        self.owners=self.network(segmented=False);self.first=self.owners[0]._peer
        self.fresh=[];self.invites=[]
        for index,manager in enumerate(self.owners):
            profiles=[]
            for slot in range(2 if index<2 else 0):
                with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
                profile=validators.ValidatorProfile.create('New'+manager._peer.label+str(slot),manager._peer,label='New '+str(index)+str(slot),p2p_port=port)
                self.addCleanup(profile.close);self.fresh.append(profile);profiles.append(profile)
            self.invites.append(transition.prepare_invite(manager._peer,profiles))
        self.document=transition.prepare(self.first,self.invites)

    def original(self,count=3):
        owner=self.owners[2]._peer
        return owner._engine.produce_lan_test_block(owner._local_indices[0],count,owner._wire_limit)

    def changed_document(self,bundle):
        return lan._signed(self.first._identity,transition.DOMAIN,{'schema':transition.SCHEMA,
            'from_native_genesis_hash':self.document['body']['from_native_genesis_hash'],
            'to_native_genesis_hash':validate_bundle(bundle,self.first.public_key)['anchor']['genesis_hash'],'bundle':bundle})

    def pending(self,profile):
        origin=nodes.unpack(bytes(profile._db.execute("SELECT value FROM metadata WHERE name='head'").fetchone()[0]))
        record={'schema':transition.PENDING,'document':deepcopy(self.document),'origin_head':origin}
        def write():profile._meta['network_transition_pending']=record;profile._put('network_transition_pending',record)
        profile._write(write);return record

    def test_prepare_preserves_all_old_bindings_ads_keys_and_nonempty_originals(self):
        self.original()
        for manager in self.owners:
            profile=manager._peer._profile;old=profile.session();head=deepcopy(profile._head);keys=deepcopy(profile._meta['protected_keys'])
            checked=transition.contract(profile,self.document)
            self.assertEqual(profile.session(),old);self.assertEqual(profile._head,head);self.assertEqual(profile._meta['protected_keys'],keys)
            self.assertEqual(manager._peer.public_invite()['body'].get('consensus_invites',[]),profile.descriptor().get('validator_invites',[]))
            self.assertNotEqual(checked['old_anchor']['genesis']['chain_id'],checked['target']['anchor']['genesis']['chain_id'])
            self.assertEqual(checked['target']['source']['genesis']['producers'],checked['old_anchor']['genesis']['dag']['genesis']['producers'])

    def test_new_native_chain_domain_is_mandatory_even_with_fresh_keys(self):
        body=self.document['body']['bundle']['body'];membership=deepcopy(body['consensus'])
        membership['chain_id']=anchor_from_bundle(self.first._profile.session(),self.first.public_key)['genesis']['chain_id']
        bundle=make_bundle(self.first._identity,self.invites,membership,label='Other',network_nonce=secrets.token_hex(32))
        with self.assertRaisesRegex(ValueError,'DOMAIN'):transition.contract(self.first._profile,self.changed_document(bundle))

    def test_old_validator_signing_identities_cannot_be_reset_into_new_network(self):
        membership=deepcopy(self.first._bundle['body']['consensus']);membership['chain_id']='ggnet:'+secrets.token_hex(12)
        bundle=make_bundle(self.first._identity,self.invites,membership,label='Other',network_nonce=secrets.token_hex(32))
        with self.assertRaisesRegex(ValueError,'NEW_VALIDATOR_IDENTITIES_REQUIRED'):
            transition.contract(self.first._profile,self.changed_document(bundle))
        old=list(self.owners[0]._validator_profiles.values())
        with self.assertRaisesRegex(ValueError,'NEW_VALIDATOR_IDENTITIES_REQUIRED'):transition.prepare_invite(self.first,old)

    def test_coordinator_cannot_change_owner_producer_keys_during_transition(self):
        invites=deepcopy(self.invites);body=invites[2]['body'];body['producer_keys']=[Keypair().pubkey().hex(),Keypair().pubkey().hex()]
        invites[2]=lan._signed(self.owners[2]._peer._identity,lan._INVITE,body)
        membership=self.document['body']['bundle']['body']['consensus']
        bundle=make_bundle(self.first._identity,invites,membership,label='Other',network_nonce=secrets.token_hex(32))
        with self.assertRaisesRegex(ValueError,'OWNER_IDENTITY'):transition.contract(self.first._profile,self.changed_document(bundle))

    def test_wrong_old_source_and_unsigned_documents_are_rejected_without_binding(self):
        profile=self.first._profile;before=deepcopy(profile._meta)
        bad=deepcopy(self.document);bad['body']['from_native_genesis_hash']='0'*64
        with self.assertRaises(ValueError):transition.contract(profile,bad)
        bad=lan._signed(self.first._identity,transition.DOMAIN,bad['body'])
        with self.assertRaisesRegex(ValueError,'SOURCE'):transition.contract(profile,bad)
        self.assertEqual(profile._meta,before)

    def test_pending_intent_survives_reopen_and_blocks_signers_and_old_network_resume(self):
        self.original();manager=self.owners[2];profile=manager._peer._profile;before=deepcopy(profile._head)
        self.pending(profile);transition.validate_pending(profile)
        with self.assertRaisesRegex(ValueError,'TRANSITION_PENDING'):profile.signers()
        manager.stop();opened=nodes.NodeProfile.open('Termux')
        try:
            self.assertEqual(opened._head,before);transition.validate_pending(opened)
            with self.assertRaisesRegex(ValueError,'TRANSITION_PENDING'):opened.signers()
        finally:opened.close()
        with self.assertRaisesRegex(ValueError,'TRANSITION_PENDING'):manager.dispatch('lan.resume',{'profile':'Termux'})
        self.assertFalse(manager.active)

    def test_authentic_pending_seal_cannot_replace_original_head_or_archive_pin(self):
        profile=self.first._profile;record=self.pending(profile)
        for mutate in (lambda row:row['origin_head']['body'].__setitem__('entries',True),lambda row:row.__setitem__('archive_sha256','z'*64)):
            with self.subTest(mutate=mutate):
                bad=deepcopy(record);mutate(bad);profile._meta['network_transition_pending']=bad
                with self.assertRaises(ValueError):transition.validate_pending(profile)
        profile._meta['network_transition_pending']=record

    def test_real_nonempty_five_thousand_history_is_archived_before_atomic_new_binding(self):
        first=self.original(5000);second=self.original(1);manager=self.owners[2];profile=manager._peer._profile
        keys=deepcopy(profile._meta['protected_keys']);owner=profile.descriptor()['public_keys'];head=deepcopy(profile._head)
        manager.stop();result=transition.transition('Termux',self.document)
        self.assertEqual(result['state'],'NETWORK_TRANSITION_COMPLETE');self.assertEqual(result['archived_original_records'],2)
        self.assertEqual(result['archived_admitted_transactions'],5001);self.assertFalse(result['network_started'])
        opened=nodes.NodeProfile.open('Termux')
        try:
            self.assertEqual(opened._meta['protected_keys'],keys);self.assertEqual(opened.descriptor()['public_keys'],owner)
            self.assertEqual(opened.session(),self.document['body']['bundle']);self.assertEqual(opened._head['entries'],0)
            self.assertEqual(opened._meta['network_transition']['origin_head']['body']['digest'],head['digest'])
            self.assertEqual(transition.validate_completed(opened)['original_admitted_transactions'],5001)
            opened.signers()
        finally:opened.close()
        repeated=transition.transition('Termux',self.document);self.assertEqual(repeated['state'],'ALREADY_COMPLETE')
        manager.dispatch('lan.resume',{'profile':'Termux'})
        self.assertEqual(manager._peer._bundle,self.document['body']['bundle']);self.assertIsNone(manager._peer._engine)
        self.assertIn(first['hash'],__import__('json').loads(second['wire'])['body']['parents'])

    def interrupted(self,phase):
        self.original();manager=self.owners[2];manager.stop();visited=[]
        def barrier(current):
            visited.append(current)
            if current==phase:raise ValueError('PUBLIC_INJECTED_INTERRUPTION')
        with self.assertRaises(ValueError):
            transition.transition('Termux',self.document,_barrier=barrier)
        self.assertIn(phase,visited)
        opened=nodes.NodeProfile.open('Termux')
        try:
            if phase=='PREFLIGHT_VERIFIED':self.assertNotIn('network_transition_pending',opened._meta);self.assertEqual(opened._head['entries'],1)
            elif phase=='FINAL_COMMITTED':self.assertIn('network_transition',opened._meta);self.assertEqual(opened._head['entries'],0)
            else:
                self.assertIn('network_transition_pending',opened._meta);self.assertEqual(opened._head['entries'],1)
                with self.assertRaisesRegex(ValueError,'TRANSITION_PENDING'):opened.signers()
        finally:opened.close()
        result=transition.transition('Termux',self.document)
        self.assertIn(result['state'],('NETWORK_TRANSITION_COMPLETE','ALREADY_COMPLETE'))
        self.assertEqual(result['archived_original_records'],1);self.assertEqual(result['archived_admitted_transactions'],3)

    def test_failure_after_preflight_keeps_old_journal_writable(self):self.interrupted('PREFLIGHT_VERIFIED')
    def test_failure_after_intent_resumes_original_journal(self):self.interrupted('INTENT_COMMITTED')
    def test_partial_backup_is_disposable_only_under_protected_intent(self):self.interrupted('BACKUP_PAGE')
    def test_failure_after_backup_sync_resumes_without_changing_source(self):self.interrupted('BACKUP_SYNCED')
    def test_published_archive_before_pin_is_reverified_and_reused(self):self.interrupted('ARCHIVE_PUBLISHED')
    def test_failure_after_archive_verification_rechecks_originals(self):self.interrupted('ARCHIVE_VERIFIED')
    def test_failure_after_pin_keeps_originals_and_resume_context(self):self.interrupted('ARCHIVE_PIN_COMMITTED')
    def test_failure_before_final_commit_rolls_back_atomically(self):self.interrupted('BEFORE_FINAL_COMMIT')
    def test_lost_final_completion_resolves_actual_new_network(self):self.interrupted('FINAL_COMMITTED')

    def test_actual_live_profile_lease_prevents_implicit_stop_or_transition(self):
        before=deepcopy(self.owners[2]._peer._profile._meta)
        with self.assertRaises(ValueError):transition.transition('Termux',self.document)
        self.assertEqual(self.owners[2]._peer._profile._meta,before);self.assertTrue(self.owners[2].active)

    def unknown_commit(self,stage):
        self.original();self.owners[2].stop();commit=nodes.NodeProfile._commit;triggered=[]
        def lost_ack(profile):
            current='FINAL' if 'network_transition' in profile._meta else 'PIN' if 'archive_sha256' in profile._meta.get('network_transition_pending',{}) else 'INTENT'
            commit(profile)
            if current==stage:
                triggered.append(stage);raise OSError('public fixture lost actual SQLite commit acknowledgement')
        with patch.object(nodes.NodeProfile,'_commit',lost_ack):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):transition.transition('Termux',self.document)
        self.assertEqual(triggered,[stage]);result=transition.transition('Termux',self.document)
        self.assertEqual(result['archived_original_records'],1)
        self.assertEqual(result['state'],'ALREADY_COMPLETE' if stage=='FINAL' else 'NETWORK_TRANSITION_COMPLETE')

    def test_unknown_actual_intent_commit_acknowledgement_resumes(self):self.unknown_commit('INTENT')
    def test_unknown_actual_archive_pin_commit_acknowledgement_resumes(self):self.unknown_commit('PIN')
    def test_unknown_actual_final_commit_acknowledgement_resolves_new_binding(self):self.unknown_commit('FINAL')

    def test_pending_target_drift_cannot_replace_signed_document_or_archive(self):
        self.original();second=transition.prepare(self.first,self.invites);self.owners[2].stop()
        def barrier(phase):
            if phase=='INTENT_COMMITTED':raise ValueError('public interrupted intent')
        with self.assertRaises(ValueError):transition.transition('Termux',self.document,_barrier=barrier)
        with self.assertRaisesRegex(ValueError,'TARGET_DRIFT'):transition.transition('Termux',second)
        self.assertEqual(transition.transition('Termux',self.document)['state'],'NETWORK_TRANSITION_COMPLETE')

    def test_corrupt_completed_archive_blocks_resume_without_repair(self):
        self.original();self.owners[2].stop();transition.transition('Termux',self.document)
        path=nodes.profile_path('Termux')/'network-history'/(self.document['body']['from_native_genesis_hash']+'.sqlite3')
        raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        with self.assertRaises(ValueError):nodes.NodeProfile.open('Termux')
        self.assertEqual(path.read_bytes(),bytes(raw))


if __name__=='__main__':unittest.main()
