"""Protected session/controller policy; SDK verification is a mocked seam.

Real owned processes, certificates and durable SDK restart run separately.
Pairing below uses actual isolated listeners and protected profiles; no fake
active legacy DAG engine is installed to make the source2 controller work.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from backend import gg_node_store as nodes,gg_consensus_profile as validators,gg_consensus as native
from backend import gg_segmented_authority as authority,gg_dag_segmented as segmented,portable_wallet_vault as vault
from backend.gg_lan_dag import LanDagPeer
from backend.gg_consensus_membership import make_membership
from backend.gg_dag_segmented_session import make_bundle
from backend.gg_dag_producer_journal import OwnedSegmentedProducer


def protected_network(*,roles=('producer','producer','replica')):
    owners=[];peers=[];profiles=[];reserved=[]
    try:
        for index in range(3):
            role=roles[index]
            profile=nodes.NodeProfile.create('Owner'+str(index),{'label':('Windows','Linux','Termux')[index],
                'host':'127.0.0.1','port':0,'allowed_cidr':'127.0.0.0/8','trusted_coordinator':None,
                'allow_test_tokens':False,'allow_dag_transactions':True,'node_role':role})
            owners.append(profile)
            peer=LanDagPeer(profile.descriptor()['label'],node_profile=profile,node_role=role,allow_dag_transactions=True)
            peers.append(peer);peer.start_pairing()
        for peer in peers[1:]:peer.pin_coordinator(peers[0].public_key)
        for index in range(4):
            reserve=socket.socket();reserve.bind(('127.0.0.1',0));reserved.append(reserve)
            profiles.append(validators.ValidatorProfile.create('Validator'+str(index),peers[index%2],
                label='Protected SDK validator '+str(index),p2p_port=reserve.getsockname()[1]))
        invites=[peer.public_invite() for peer in peers];bodies=[invite['body'] for invite in invites]
        membership=make_membership([profile.public_invite() for profile in profiles],owners={row['peer_key']:row for row in bodies},
            forbidden_keys=[key for row in bodies for key in (row['peer_key'],*row['producer_keys'])])
        bundle=make_bundle(peers[0]._identity,invites,membership,label='Protected signed SDK session',network_nonce=hashlib.sha256(b'public authority fixture session').hexdigest())
        contexts=[authority.OwnedSegmentedSession(profile,bundle) for profile in owners]
        for profile in profiles:profile.bind_anchor(bundle,peers[0].public_key)
        return owners,peers,profiles,bundle,contexts
    except BaseException:
        for profile in profiles:profile.close()
        for peer in peers:peer.stop()
        for profile in owners:profile.close()
        raise
    finally:
        for reserve in reserved:reserve.close()


class SegmentedAuthorityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-segmented-authority-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('public protected authority fixture'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.owners,self.peers,self.profiles,self.bundle,self.contexts=protected_network();self.controllers=[];self.addCleanup(self.cleanup)
        self.binary=Path(self.temp.name)/'owned-sdk-fixture';self.binary.write_bytes(b'public test binary seam')
        self.stack.enter_context(patch.object(native,'_installed_binary',return_value=self.binary))
        self.stack.enter_context(patch.object(native,'_validate_binary_at',return_value=(self.binary.stat().st_size,self.binary.stat().st_mtime_ns)))
        self.verify=self.stack.enter_context(patch.object(native,'_verify_public',side_effect=self.verified))
        self.control=authority.OwnedSegmentedAuthority(self.profiles[0],self.contexts[0],tools=Path(self.temp.name));self.controllers.append(self.control)
        self.profiles[0].claim_native_start();(self.profiles[0].root/'native').mkdir()
        self.base=segmented.initial_context(self.control.anchor['genesis']['dag_segmented'],self.control.anchor['genesis_hash'])
        self.state={'height':0,'state_root':'a'*64,'dag_segmented':deepcopy(self.base['commitment'])}
        self.header={'header':{'height':'1'},'commit':{'block_id':{'hash':'b'*64}}}
        self.stack.enter_context(patch.object(self.control,'_status',return_value={'sync_info':{'latest_block_height':'1'}}))
        self.stack.enter_context(patch.object(self.control,'_rpc',return_value={'signed_header':self.header}))
        self.stack.enter_context(patch.object(self.control,'_query',return_value=self.state))

    def cleanup(self):
        for controller in reversed(self.controllers):controller.close()
        for profile in reversed(self.profiles):profile.close()
        for peer in self.peers:peer.stop()
        for profile in self.owners:profile.close()

    def verified(self,packet,*args):
        state=packet['state']['dag_segmented'];source=packet['genesis']['dag_segmented'];base=segmented.initial_context(source,packet['genesis_hash'])
        result={'verified':True,'certificate_height':packet['state']['height']+1,'dag_segmented_commitment':deepcopy(state),'dag_history_replay_verified':False,
            'dag_segmented_base_proof_verified':'dag_segmented_base_proof' in packet,'dag_segmented_epoch_base':base,
            'dag_segmented_base_scope':segmented.BASE_SCOPE,'dag_segmented_membership_scope':'CERTIFIED_ACTIVE_SEGMENT_MEMBERSHIP_NOT_FULL_HISTORY_REPLAY'}
        for name in ('dag_segmented_account_proof','dag_segmented_block_proof','dag_segmented_order_page'):result[name+'_verified']=name in packet
        return result

    def test_real_owned_context_binds_without_an_active_legacy_engine(self):
        self.assertTrue(all(peer._engine is None for peer in self.peers))
        self.assertEqual(self.owners[0].session(),self.bundle)
        self.assertEqual(self.contexts[0].anchor(),self.profiles[0].anchor())
        self.assertFalse(self.control.snapshot()['owned_native_process'])
        self.assertFalse(self.control.snapshot()['certificate_verified'])

    def test_certificate_is_persisted_before_view_and_rechecked_after_close(self):
        packet=self.control.certified_state();self.assertEqual(self.profiles[0].public_certificate(),packet)
        self.control.close();profile=validators.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        self.verify.reset_mock();controller=authority.OwnedSegmentedAuthority(profile,self.contexts[0],tools=Path(self.temp.name));self.controllers.append(controller)
        self.verify.assert_called_once();self.assertEqual(controller.snapshot()['observation_origin'],'PERSISTED_CERTIFICATE')
        self.assertFalse(controller.snapshot()['certificate_is_network_liveness'])

    def test_failed_certificate_write_publishes_no_verified_observation(self):
        with patch.object(self.profiles[0],'_commit',side_effect=OSError('public injected disk failure')):
            with self.assertRaises(ValueError):self.control.certified_state()
        self.assertIsNone(self.control._view);self.assertIsNone(self.control.cached_certificate())
        self.assertEqual(self.control.snapshot()['last_error'],'GG_VALIDATOR_CERTIFICATE_SAVE_FAILED')

    def test_unverified_rpc_state_cannot_change_the_durable_floor(self):
        with patch.object(native,'_verify_public',side_effect=ValueError('public SDK rejection')):
            with self.assertRaises(ValueError):self.control.certified_state()
        self.assertIsNone(self.profiles[0].public_certificate());self.assertEqual(self.control._fault,'')

    def test_owner_close_stops_authority_access_and_never_substitutes_a_new_owner(self):
        self.control.certified_state();self.owners[0].close()
        self.assertTrue(self.control._owner_stopped());self.assertIsNone(self.control.cached_certificate())
        self.assertEqual(self.control.snapshot()['state'],'CLOSED')
        with self.assertRaisesRegex(ValueError,'OWNER_CLOSED'):self.control.start()

    def test_profile_target_drift_is_latched_before_start_or_signer_release(self):
        self.owners[0]._meta['session']=deepcopy(self.bundle);self.owners[0]._meta['session']['body']['label']='Changed without owned rebinding'
        with self.assertRaisesRegex(ValueError,'SESSION_CHANGED'):self.control.start()
        self.assertTrue(self.owners[0]._failed)

    def test_wrong_member_owner_and_unbound_validator_profile_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'VALIDATOR_OWNER'):
            authority.OwnedSegmentedAuthority(self.profiles[0],self.contexts[1],tools=Path(self.temp.name))
        profile=validators.ValidatorProfile.create('Unbound',self.peers[0],label='Unbound fixture',p2p_port=29123);self.profiles.append(profile)
        with self.assertRaisesRegex(ValueError,'ANCHOR_REQUIRED'):authority.OwnedSegmentedAuthority(profile,self.contexts[0],tools=Path(self.temp.name))

    def test_captured_base_query_does_not_wait_on_the_controller_work_lock(self):
        self.control.certified_state();packet=self.control.cached_certificate();epoch=(self.control._node,29125)
        packet['state']['height']=1;packet['signed_header']['header']['height']='2'
        proof={'schema':'gg.dag.segmented-base-proof.v1','commitment':deepcopy(self.state['dag_segmented']),'height':1,'genesis_hash':packet['genesis_hash'],
            'state_root':self.state['state_root'],'cut':None,'previous_closed':[]}
        done=threading.Event();result=[];errors=[]
        def query():
            try:result.append(self.control.export_proof(packet=packet))
            except BaseException as error:errors.append(type(error).__name__)
            finally:done.set()
        with patch.object(self.control,'_check_proof_epoch',return_value=epoch),patch.object(self.control,'_public_query',return_value=proof) as read:
            with self.control._lock:
                thread=threading.Thread(target=query);thread.start();self.assertTrue(done.wait(2),'public base proof waited on signing work lock')
            thread.join(2)
        self.assertFalse(errors);self.assertEqual(result[0]['dag_segmented_base_proof'],proof)
        read.assert_called_once_with(epoch,'/gg/dag/base-proof',1,b'')

    def test_evicted_context_or_changed_process_never_returns_a_latest_substitute(self):
        self.control.certified_state();packet=self.control.cached_certificate();epoch=(self.control._node,29125)
        stored=deepcopy(packet)
        packet['state']['height']=1;packet['signed_header']['header']['height']='2'
        with patch.object(self.control,'_check_proof_epoch',return_value=epoch),patch.object(self.control,'_public_query',side_effect=ValueError('GG_CONTEXT_EVICTED')):
            with self.assertRaisesRegex(ValueError,'CONTEXT_EVICTED'):self.control.export_proof(packet=packet)
        self.assertEqual(self.control.cached_certificate(),stored)

    def test_initial_certificate_never_queries_height_zero_as_a_pinned_snapshot(self):
        self.control.certified_state();packet=self.control.cached_certificate();epoch=(self.control._node,29125)
        with patch.object(self.control,'_check_proof_epoch',return_value=epoch),patch.object(self.control,'_public_query') as read:
            with self.assertRaisesRegex(ValueError,'PROOF_INITIAL_WAIT'):self.control.export_proof(packet=packet)
        read.assert_not_called();self.assertEqual(self.control.cached_certificate(),packet)

    def test_verified_conflict_persists_in_owner_and_validator_before_restart(self):
        first=self.control.certified_state();other=deepcopy(first);other['signed_header']['commit']['block_id']['hash']='c'*64
        evidence=authority.make_conflict_evidence(first,other,self.control.anchor)
        self.control.observe_conflict(evidence)
        self.assertEqual(self.owners[0].consensus_observation()['evidence'],evidence)
        self.assertEqual(self.profiles[0].public_conflict(),evidence)
        self.assertTrue(self.contexts[0].stopped());self.assertFalse(self.control.snapshot()['certificate_verified'])
        self.control.close();profile=validators.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        controller=authority.OwnedSegmentedAuthority(profile,self.contexts[0],tools=Path(self.temp.name));self.controllers.append(controller)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):controller.start()

    def test_unverified_accusation_cannot_persist_a_shared_owner_fault(self):
        first=self.control.certified_state();other=deepcopy(first);other['signed_header']['commit']['block_id']['hash']='c'*64
        evidence=authority.make_conflict_evidence(first,other,self.control.anchor)
        with patch.object(native,'_verify_public',side_effect=[self.verified(first),ValueError('public second SDK rejection')]):
            with self.assertRaises(ValueError):self.control.observe_conflict(evidence)
        self.assertIsNone(self.owners[0].consensus_observation());self.assertEqual(self.control._fault,'')

    def test_shared_verified_fault_blocks_own_producer_and_other_validator_after_profile_reopen(self):
        first=self.control.certified_state();packet=deepcopy(first)
        packet['dag_segmented_base_proof']={'schema':'gg.dag.segmented-base-proof.v1','commitment':deepcopy(self.state['dag_segmented']),
            'height':0,'state_root':self.state['state_root'],'genesis_hash':packet['genesis_hash'],'cut':None,'previous_closed':[]}
        producer=OwnedSegmentedProducer.open(self.owners[0],self.bundle,packet,binary=self.binary,stamp=self.control._stamp,hot_bytes=0)
        self.addCleanup(producer.close)
        other=deepcopy(first);other['signed_header']['commit']['block_id']['hash']='c'*64
        self.control.observe_conflict(authority.make_conflict_evidence(first,other,self.control.anchor))
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):producer.produce(producer._indices[0],1)
        second=authority.OwnedSegmentedAuthority(self.profiles[2],self.contexts[0],tools=Path(self.temp.name));self.controllers.append(second)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):second.start()
        self.assertFalse(self.profiles[2].snapshot()['native_started'])
        producer.close();self.peers[0].stop();restored=nodes.NodeProfile.open('Owner0');self.owners.append(restored)
        self.assertEqual(restored.consensus_observation()['fault'],'GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):
            OwnedSegmentedProducer.open(restored,self.bundle,packet,binary=self.binary,stamp=self.control._stamp,hot_bytes=0)

    def test_mempool_acceptance_or_unknown_reply_never_claims_selection(self):
        raw=b'public checkpoint bytes';identifier=hashlib.sha256(raw).hexdigest()
        with patch.object(self.control,'_rpc',return_value={'code':0,'hash':identifier.upper()}):
            self.assertEqual(self.control.submit(raw),{'state':'MEMPOOL_ACCEPTED','hash':identifier,'SDK_selected':False})
        with patch.object(self.control,'_rpc',side_effect=OSError('public lost reply')):
            self.assertEqual(self.control.submit(raw)['state'],'BROADCAST_UNKNOWN')
        self.assertIsNone(self.control._view)


    def test_unexpected_process_exit_retains_historical_certificate_without_claiming_contact(self):
        from backend import gg_process_termination as termination
        self.control.certified_state();process=Mock();process.poll.return_value=73
        self.control._node={'process':process,'_ready':None};self.control._epoch_stopping=False
        real_wait=termination.wait_process_terminal;real_terminal=termination.process_terminal
        with patch.object(termination,'wait_process_terminal',side_effect=lambda child,timeout:73 if child is process else real_wait(child,timeout)), \
                patch.object(termination,'process_terminal',side_effect=lambda child:True if child is process else real_terminal(child)):
            try:
                view=self.control.snapshot()
                self.assertEqual(view['state'],'FAULT');self.assertEqual(view['last_error'],'GG_VALIDATOR_NATIVE_PROCESS_EXITED')
                self.assertEqual(view['native_exit_code'],73);self.assertFalse(view['owned_native_process'])
                self.assertTrue(view['certificate_verified']);self.assertFalse(view['certificate_is_network_liveness'])
                self.control._epoch_stopping=True;view=self.control.snapshot()
                self.assertEqual(view['state'],'STOPPED');self.assertEqual(view['last_error'],'');self.assertIsNone(view['native_exit_code'])
            finally:self.control.close()


if __name__=='__main__':unittest.main()
