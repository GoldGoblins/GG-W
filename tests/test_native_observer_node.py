"""Observer controller policy; SDK boundaries are mocked, never crypto evidence."""
import base64
from copy import deepcopy
from contextlib import ExitStack
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from backend import gg_observer_node as control,gg_observer_profile as store
from tests import test_native_observer_profile as fixture


class NativeObserverControllerTests(unittest.TestCase):
    cleanup=fixture.NativeObserverProfileTests.cleanup
    profile=fixture.NativeObserverProfileTests.profile
    network=fixture.NativeObserverProfileTests.network
    observer=fixture.NativeObserverProfileTests.observer

    def setUp(self):
        fixture.NativeObserverProfileTests.setUp(self)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.profile_owned=self.observer();self.profile_owned.claim_native_start()
        (self.profile_owned.root/'native').mkdir(mode=0o700)
        self.binary=Path(self.temp.name)/'mocked-boundary-not-executable';self.binary.write_bytes(b'not an SDK')
        info=self.binary.stat()
        self.stack.enter_context(patch.object(control.native,'_installed_binary',return_value=self.binary))
        self.stack.enter_context(patch.object(control.native,'_validate_binary_at',return_value=(info.st_size,info.st_mtime_ns)))
        self.verify=self.stack.enter_context(patch.object(control.native,'_verify_public',return_value={'verified':True}))
        self.node=control.OwnedObserver(self.profile_owned,self.peers[2],tools=self.temp.name);self.addCleanup(self.node.close)
        self.header={'header':{'height':'10'},'commit':{'block_id':{'hash':'b'*64}}}
        self.state={'height':9,'state_root':'a'*64,'dag':{'checkpoint':1}}

    def certificate_boundary(self):
        self.status=self.stack.enter_context(patch.object(self.node,'_status',return_value={'sync_info':{'latest_block_height':'10'}}))
        self.rpc=self.stack.enter_context(patch.object(self.node,'_rpc',return_value={'signed_header':self.header}))
        self.query=self.stack.enter_context(patch.object(self.node,'_query',return_value=deepcopy(self.state)))

    def test_bootstrap_and_readiness_have_no_consensus_secret_or_vote_fields(self):
        self.node.rpc_port=23990;request=self.node._native_bootstrap(False)
        self.assertEqual(set(request),{'schema','genesis','genesis_hash','observer_grant','node_seed','root','rpc_port','expected_fresh'})
        self.assertEqual(request['schema'],'gg.native.observer-bootstrap.v1');self.assertFalse(request['expected_fresh'])
        self.assertEqual(request['node_seed'],bytes(self.profile_owned.native_node_signer())[:32].hex())
        from types import SimpleNamespace
        ready=self.node._native_ready(SimpleNamespace(pid=1234))
        self.assertFalse(ready['consensus_signing']);self.assertFalse(ready['state_sync']);self.assertEqual(ready['pid'],1234)
        self.assertNotIn('validator_index',self.node.snapshot())

    def test_status_requires_actual_observer_public_identity_and_zero_voting_power(self):
        key=self.node.member['node_key']
        expected={'node_info':{'network':self.node.anchor['genesis']['chain_id'],'id':self.node.node_id},
            'validator_info':{'address':hashlib.sha256(bytes.fromhex(key)).digest()[:20].hex(),
                'pub_key':{'type':'tendermint/PubKeyEd25519','value':base64.b64encode(bytes.fromhex(key)).decode('ascii')},'voting_power':'0'}}
        with patch.object(self.node,'_rpc',return_value=expected):self.assertEqual(self.node._status(),expected)
        for field,value in (('voting_power','1'),('address','a'*40),('pub_key',{'type':'anything','value':'anything'})):
            invalid=deepcopy(expected);invalid['validator_info'][field]=value
            with self.subTest(field=field),patch.object(self.node,'_rpc',return_value=invalid),self.assertRaisesRegex(ValueError,'IDENTITY_OR_VOTE'):
                self.node._status()

    def test_observer_rpc_cannot_submit_consensus_transactions(self):
        with patch.object(control.OwnedNativeRPC,'_rpc') as transport:
            with self.assertRaisesRegex(ValueError,'READ_ONLY'):self.node._rpc('broadcast_tx_sync',b'caller bytes')
            transport.assert_not_called()

    def test_verified_local_query_is_saved_before_exposure_and_reopened_as_historical(self):
        self.certificate_boundary();packet=self.node.certified_state()
        self.assertEqual(self.profile_owned.public_certificate(),packet)
        self.assertEqual(self.node.snapshot()['observation_origin'],'OWNED_SDK_QUERY')
        # This policy seam has no running process and cannot claim live local execution.
        self.assertFalse(self.node.snapshot()['local_state_read_from_owned_sdk'])
        self.node.close();profile=store.ObserverProfile.open(self.profile_owned.name);self.profiles.append(profile)
        reopened=control.OwnedObserver(profile,self.peers[2],tools=self.temp.name);self.addCleanup(reopened.close)
        view=reopened.snapshot();self.assertTrue(view['certificate_verified'])
        self.assertEqual(view['observation_origin'],'PERSISTED_CERTIFICATE')
        self.assertFalse(view['local_state_read_from_owned_sdk']);self.assertFalse(view['certificate_is_network_liveness'])

    def test_rewind_cannot_replace_floor_and_unverified_claim_cannot_latch_conflict(self):
        self.certificate_boundary();packet=self.node.certified_state()
        self.status.return_value={'sync_info':{'latest_block_height':'8'}};self.query.reset_mock()
        with self.assertRaisesRegex(ValueError,'NO_FRESH_CERTIFICATE'):self.node.certified_state()
        self.query.assert_not_called();self.assertEqual(self.profile_owned.public_certificate(),packet)
        self.status.return_value={'sync_info':{'latest_block_height':'10'}}
        self.header['commit']['block_id']['hash']='c'*64;self.verify.side_effect=ValueError('mocked SDK rejection')
        with self.assertRaisesRegex(ValueError,'SDK rejection'):self.node.certified_state()
        self.assertEqual(self.node._fault,'');self.assertIsNone(self.profile_owned.public_conflict())

    def test_verified_conflict_halts_and_survives_complete_profile_and_controller_reopen(self):
        self.certificate_boundary();self.node.certified_state();self.header['commit']['block_id']['hash']='c'*64
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):self.node.certified_state()
        self.assertEqual(self.profile_owned.snapshot()['last_error'],'GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        self.assertFalse(self.node.snapshot()['certificate_verified']);self.node.close()
        profile=store.ObserverProfile.open(self.profile_owned.name);self.profiles.append(profile)
        self.verify.reset_mock();reopened=control.OwnedObserver(profile,self.peers[2],tools=self.temp.name);self.addCleanup(reopened.close)
        self.assertEqual(self.verify.call_count,3)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):reopened.start()
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):profile.claim_native_start()

    def test_storage_failure_stops_without_publishing_a_certificate(self):
        self.certificate_boundary()
        with patch.object(self.profile_owned,'_commit',side_effect=OSError('owned injected write boundary')):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):self.node.certified_state()
        self.assertIsNone(self.node._tip);self.assertIsNone(self.node.cached_certificate())
        self.assertFalse(self.node.snapshot()['canonical_finality']);self.assertIsNone(self.profile_owned.public_certificate())

    def test_different_owner_or_closed_lifetime_cannot_start_or_export(self):
        with self.assertRaisesRegex(ValueError,'OWNER_OR_ANCHOR_CHANGED'):
            control.OwnedObserver(self.profile_owned,self.peers[1],tools=self.temp.name)
        self.peers[2].stop()
        with self.assertRaisesRegex(ValueError,'OWNER_STOPPED'):self.node.start()
        self.assertIsNone(self.node.cached_certificate());self.assertFalse(self.node.snapshot()['owned_native_process'])

    def transport_boundary(self,*,catching=False,peers=1):
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=None;self.node._node={'process':process,'_ready':None};self.node._epoch_stopping=False
        self.status=self.stack.enter_context(patch.object(self.node,'_status',return_value={'sync_info':{'latest_block_height':'10','catching_up':catching}}))
        rows=[]
        for member in self.node.anchor['genesis']['membership']['validators'][:peers]:
            rows.append({'node_info':{'id':hashlib.sha256(bytes.fromhex(member['body']['node_key'])).digest()[:20].hex(),
                'network':self.node.anchor['genesis']['chain_id']},
                'connection_status':{'RecvMonitor':{'Bytes':'1234'},'SendMonitor':{'Bytes':'42'}}})
        self.net={'n_peers':str(peers),'peers':rows}
        self.rpc=self.stack.enter_context(patch.object(self.node,'_rpc',return_value=self.net))
        # Stop this policy fixture's fake process without pretending it is SDK evidence.
        self.addCleanup(lambda:self.node._node.update(process=None))

    def test_live_process_and_lan_pairing_alone_cannot_claim_native_contact(self):
        self.transport_boundary()
        self.assertEqual(self.node.snapshot()['native_connection']['state'],'UNOBSERVED')
        self.assertFalse(self.node.snapshot()['native_connection']['connected'])
        self.node.refresh_status();connection=self.node.snapshot()['native_connection']
        self.assertTrue(connection['connected']);self.assertEqual(connection['state'],'CONNECTED')
        self.assertEqual(connection['received_bytes'],'1234');self.assertEqual(connection['sent_bytes'],'42')
        self.assertFalse(self.node.snapshot()['certificate_verified'])

    def test_sync_disconnect_and_expired_observation_are_distinct(self):
        self.transport_boundary(catching=True);self.node.refresh_status()
        self.assertEqual(self.node.snapshot()['native_connection']['state'],'SYNCING')
        self.status.return_value['sync_info']['catching_up']=False
        self.net.update(n_peers='0',peers=[]);self.node.refresh_status()
        self.assertEqual(self.node.snapshot()['native_connection']['state'],'DISCONNECTED')
        observed=self.node._transport_view[1]
        with patch.object(control.time,'monotonic',return_value=observed+6):
            state=self.node.snapshot()['native_connection'];self.assertEqual(state['state'],'STALE');self.assertFalse(state['connected'])

    def test_invalid_peer_and_rpc_failure_invalidate_current_contact_without_clearing_certificate(self):
        self.transport_boundary();self.node.refresh_status()
        self.net['peers'][0]['node_info']['id']='a'*40
        with self.assertRaisesRegex(ValueError,'NATIVE_STATUS_INVALID'):self.node.refresh_status()
        self.assertFalse(self.node.snapshot()['native_connection']['connected'])
        self.rpc.side_effect=OSError('owned injected transport failure')
        with self.assertRaises(OSError):self.node.refresh_status()
        self.assertIsNone(self.node.snapshot()['native_connection']['peer_count'])

    def test_missing_byte_counters_are_unknown_and_unexpected_exit_is_visible(self):
        self.transport_boundary();del self.net['peers'][0]['connection_status'];self.node.refresh_status()
        self.assertIsNone(self.node.snapshot()['native_connection']['received_bytes'])
        self.node._node['process'].poll.return_value=2
        view=self.node.snapshot();self.assertEqual(view['state'],'FAULT')
        self.assertEqual(view['last_error'],'GG_OBSERVER_NATIVE_PROCESS_EXITED');self.assertEqual(view['native_exit_code'],2)
        self.assertFalse(view['native_connection']['connected'])


if __name__=='__main__':unittest.main()
