"""Controller policy uses a mock SDK boundary; real crypto/processes run separately."""
from contextlib import ExitStack
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock,patch

from backend import gg_consensus_node as control,gg_consensus_profile as store
from tests import test_consensus_profile as fixture


class ValidatorControllerPolicyTests(unittest.TestCase):
    cleanup=fixture.ValidatorProfileTests.cleanup
    profile=fixture.ValidatorProfileTests.profile
    network=fixture.ValidatorProfileTests.network
    reopen=fixture.ValidatorProfileTests.reopen

    def setUp(self):
        fixture.ValidatorProfileTests.setUp(self)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        profiles,bundle=self.network()
        for peer in self.peers:peer.install_session(bundle,_start_gossip=False)
        profile=profiles[0];self.anchor=profile.bind_anchor(bundle,self.peers[0].public_key)
        profile.claim_native_start();(profile.root/'native').mkdir()
        self.binary=Path(self.temp.name)/'fixture-receipt-bound-binary.exe';self.binary.write_bytes(b'not an executable; SDK boundary is mocked')
        stat=self.binary.stat()
        self.stack.enter_context(patch.object(control.native,'_installed_binary',return_value=self.binary))
        self.stack.enter_context(patch.object(control.native,'_validate_binary_at',return_value=(stat.st_size,stat.st_mtime_ns)))
        self.verify=self.stack.enter_context(patch.object(control.native,'_verify_public',return_value={
            'verified':True,'certificate_height':10,'state_height':9,'state_root':'a'*64,'dag_commitment':{'checkpoint':1}}))
        self.node=control.OwnedValidator(profile,self.peers[0],tools=Path(self.temp.name));self.addCleanup(self.node.close)
        self.status=self.stack.enter_context(patch.object(self.node,'_status',return_value={'sync_info':{'latest_block_height':'10'}}))
        self.header={'header':{'height':'10'},'commit':{'block_id':{'hash':'b'*64}}}
        self.rpc=self.stack.enter_context(patch.object(self.node,'_rpc',return_value={'signed_header':self.header}))
        self.query=self.stack.enter_context(patch.object(self.node,'_query',return_value={'height':9,'state_root':'a'*64,'dag':{'checkpoint':1}}))

    def test_certificate_commits_before_view_and_is_reverified_on_controller_reopen(self):
        packet=self.node.certified_state()
        self.assertEqual(self.node.profile.public_certificate(),packet)
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        self.verify.reset_mock()
        reopened=control.OwnedValidator(profile,self.peers[0],tools=Path(self.temp.name));self.addCleanup(reopened.close)
        self.verify.assert_called_once()
        self.assertEqual(reopened._tip,(10,'b'*64))

    def test_reachable_old_state_cannot_rewind_durable_certified_floor(self):
        packet=self.node.certified_state();self.verify.reset_mock();self.query.reset_mock()
        self.status.return_value={'sync_info':{'latest_block_height':'8'}}
        with self.assertRaisesRegex(ValueError,'NO_FRESH_CERTIFICATE'):self.node.certified_state()
        self.verify.assert_not_called();self.query.assert_not_called()
        self.assertEqual(self.node.profile.public_certificate(),packet)

    def test_hex_case_of_same_signed_block_is_not_a_conflicting_certificate(self):
        self.node.certified_state()
        self.header['commit']['block_id']['hash']='B'*64
        self.node.certified_state()
        self.assertEqual(self.node._tip,(10,'b'*64));self.assertEqual(self.node._fault,'')

    def test_unverified_rpc_claim_cannot_latch_fault_or_change_saved_certificate(self):
        packet=self.node.certified_state();self.header['commit']['block_id']['hash']='c'*64
        self.verify.side_effect=ValueError('owned injected SDK rejection')
        with self.assertRaises(ValueError):self.node.certified_state()
        self.assertEqual(self.node._fault,'');self.assertEqual(self.node.profile.public_certificate(),packet)

    def test_verified_conflict_halts_and_persists_fault_across_full_profile_reopen(self):
        self.node.certified_state();self.header['commit']['block_id']['hash']='c'*64
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):self.node.certified_state()
        self.assertFalse(self.node.snapshot()['canonical_finality'])
        self.assertEqual(self.node.profile.snapshot()['last_error'],'GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):profile.claim_native_start()

    def test_failed_metadata_commit_does_not_publish_new_certificate(self):
        with patch.object(self.node.profile,'_commit',side_effect=OSError('owned injected storage failure')):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):self.node.certified_state()
        self.assertIsNone(self.node._tip);self.assertIsNone(self.node._last);self.assertIsNone(self.node.profile.public_certificate())
        self.assertEqual(self.node._fault,'GG_VALIDATOR_CERTIFICATE_SAVE_FAILED')
        self.assertFalse(self.node.snapshot()['canonical_finality'])

    def conflict(self):
        from backend.gg_dag_checkpoint import make_conflict_evidence
        packet=self.node.certified_state();other=deepcopy(packet)
        other['signed_header']['commit']['block_id']['hash']='c'*64
        return make_conflict_evidence(packet,other,self.anchor)

    def test_second_unverified_conflict_certificate_cannot_halt_or_write(self):
        evidence=self.conflict();previous=self.node.profile.public_certificate()
        self.verify.side_effect=[{'verified':True},ValueError('owned SDK rejection')]
        with patch.object(self.node,'stop') as stop:
            with self.assertRaisesRegex(ValueError,'SDK rejection'):self.node.observe_conflict(evidence)
        stop.assert_not_called();self.assertEqual(self.node._fault,'')
        self.assertEqual(self.node.profile.public_certificate(),previous);self.assertIsNone(self.node.profile.public_conflict())

    def test_observed_conflict_persists_both_packets_and_sdk_rechecks_both_on_reopen(self):
        evidence=self.conflict();self.node.observe_conflict(evidence)
        self.assertEqual(self.node.cached_conflict(),evidence);self.assertIsNone(self.node.cached_certificate())
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        self.assertEqual(profile.public_conflict(),evidence)
        self.verify.reset_mock()
        reopened=control.OwnedValidator(profile,self.peers[0],tools=Path(self.temp.name));self.addCleanup(reopened.close)
        self.assertGreaterEqual(self.verify.call_count,3)
        self.assertEqual(reopened.cached_conflict(),evidence);self.assertFalse(reopened.snapshot()['canonical_finality'])

    def test_new_unstarted_validator_cannot_bypass_valid_owned_peer_conflict(self):
        evidence=self.conflict()
        # The real SDK boundary is mocked in this controller policy suite.
        peer_profile=Mock();peer_profile.consensus_observation.return_value={
            'packet':evidence['certificates'][0],'fault':'GG_CONSENSUS_CONFLICTING_CERTIFICATE','evidence':evidence}
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        # The invariant applies before a native child has ever been started.
        profile._write({'native_started':False,'certificate':None,'fault':''})
        with patch.object(self.peers[0],'_profile',peer_profile):
            reopened=control.OwnedValidator(profile,self.peers[0],tools=Path(self.temp.name));self.addCleanup(reopened.close)
            self.assertEqual(reopened.cached_conflict(),evidence)
            with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):reopened.start()
        self.assertFalse(profile.snapshot()['native_started'])
        reopened.close();restored=store.ValidatorProfile.open('Validator0');self.profiles.append(restored)
        self.assertEqual(restored.public_conflict(),evidence)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):restored.claim_native_start()

    def test_conflict_store_unknown_outcome_always_stops_and_reopens_exact_evidence(self):
        # Each subcase owns a fresh independent profile root in the fixture.
        evidence=self.conflict();commit=self.node.profile._commit
        def failed_return():commit();raise OSError('owned lost conflict commit return')
        with patch.object(self.node.profile,'_commit',side_effect=failed_return),patch.object(self.node,'stop',wraps=self.node.stop) as stop:
            with self.assertRaisesRegex(ValueError,'SAVE_FAILED'):self.node.observe_conflict(evidence)
        stop.assert_called_once();self.assertIsNone(self.node.cached_conflict())
        self.assertFalse(self.node.snapshot()['canonical_finality'])
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        self.assertEqual(profile.public_conflict(),evidence)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_CERTIFICATE'):profile.claim_native_start()

    def test_lost_commit_return_recovers_durable_certificate_without_prior_ack(self):
        commit=self.node.profile._commit
        def failed_return():
            commit();raise OSError('owned lost commit return')
        with patch.object(self.node.profile,'_commit',side_effect=failed_return):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):self.node.certified_state()
        self.assertIsNone(self.node._tip)
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        reopened=control.OwnedValidator(profile,self.peers[0],tools=Path(self.temp.name));self.addCleanup(reopened.close)
        self.assertEqual(reopened._tip,(10,'b'*64))

    def checkpoint_fixture(self):
        from backend.gg_parallel_dag import _tree
        state={'height':9,'state_root':'a'*64,'dag':{'blocks':0,'transactions':0,'checkpoint':0,'manifest_hash':'f'*64}}
        state['dag'].update(account_root=self.anchor['genesis']['dag']['genesis']['precheck_root'],
            order_root=_tree([],b'GG-DAG-FINALIZED-ORDER-v1\0')[-1][0])
        self.query.side_effect=lambda path,*args:deepcopy(state) if path=='/gg/state' else {
            'start':0,'complete':True,'items':[]}
        self.verify.return_value={'verified':True,'certificate_height':10,'dag_order_page_verified':True}
        return state

    def test_complete_order_never_publishes_a_partial_or_wrong_cursor_page(self):
        state=self.checkpoint_fixture();state['dag'].update(blocks=1,transactions=1)
        self.query.side_effect=lambda path,*args:deepcopy(state) if path=='/gg/state' else {'start':32,'complete':True,'items':[]}
        with self.assertRaisesRegex(ValueError,'ORDER_PROOF_REQUIRED'):self.node.certified_order()
        self.assertIsNone(self.node.canonical_membership())
        self.query.side_effect=lambda path,*args:deepcopy(state) if path=='/gg/state' else {'start':0,'complete':True,'items':[]}
        with self.assertRaisesRegex(ValueError,'ORDER_INCONSISTENT'):self.node.certified_order()
        self.assertIsNone(self.node.canonical_membership())

    def test_durable_order_cache_requires_fresh_sdk_verification_before_fetch_authority(self):
        self.checkpoint_fixture();packet=self.node.certified_state();bad=deepcopy(packet)
        bad['state']['height']=2;bad['signed_header']['header']['height']='3'
        source=Mock();source.verified_order.return_value={'packet':bad,'order':[]}
        def verified(value,*args):return {'verified':value['state']['height']!=2,'dag_order_page_verified':True}
        self.verify.side_effect=verified
        with patch.object(self.node.peer,'_profile',source):
            with self.assertRaisesRegex(ValueError,'ORDER_CACHE_CERTIFICATE'):self.node.certified_order()
        self.assertIsNone(self.node._payload_view);self.assertIsNone(self.node.canonical_membership())
        self.assertFalse(self.node._order_loaded)

    def test_checkpoint_is_durable_before_broadcast_and_mempool_does_not_finalize(self):
        state=self.checkpoint_fixture();peer=self.peers[0]
        block=peer._engine.produce_lan_test_block(peer._local_indices[0],2,65536)
        submitted=[]
        def submit(wire):
            pending=self.node.profile.pending_checkpoint()
            self.assertEqual(hashlib.sha256(wire).hexdigest(),pending['hash'])
            submitted.append(wire);return {'state':'MEMPOOL_ACCEPTED','hash':pending['hash']}
        with patch.object(self.node,'submit',side_effect=submit):
            self.node.maintain_checkpoint();self.node.maintain_checkpoint()
        self.assertEqual(len(submitted),1)
        self.assertEqual(self.node.profile.pending_checkpoint()['state'],'MEMPOOL_ACCEPTED')
        self.assertEqual(self.node.canonical_membership()[1],{})
        pending=self.node.profile.pending_checkpoint()
        self.node.close();profile=store.ValidatorProfile.open('Validator0');self.profiles.append(profile)
        self.assertEqual(profile.pending_checkpoint(),pending)
        self.assertNotIn('block_ids',str(profile.snapshot()))

    def test_checkpoint_save_failure_never_broadcasts(self):
        self.checkpoint_fixture();self.node.certified_order()
        peer=self.peers[0];peer._engine.produce_lan_test_block(peer._local_indices[0],1,65536)
        with patch.object(self.node.profile,'_commit',side_effect=OSError('owned checkpoint write failure')),patch.object(self.node,'submit') as submit:
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):self.node.maintain_checkpoint()
        submit.assert_not_called();self.assertFalse(self.node.snapshot()['canonical_finality'])

    def test_status_does_not_wait_for_sdk_rpc_or_durable_work_lock(self):
        self.node.certified_state()
        entered=threading.Event();release=threading.Event()
        def busy():
            with self.node._lock:entered.set();release.wait(3)
        worker=threading.Thread(target=busy);worker.start()
        try:
            self.assertTrue(entered.wait(1));started=time.monotonic()
            value=self.node.snapshot()
            self.assertLess(time.monotonic()-started,.25)
            self.assertEqual(value['certificate_height'],10)
            self.assertTrue(value['canonical_finality'])
        finally:release.set();worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_public_proof_rpc_and_sdk_work_never_hold_consensus_controller_lock(self):
        packet=self.node.certified_state()
        self.verify.return_value={'verified':True,'dag_order_page_verified':True}
        for blocked_stage in ('rpc','sdk'):
            with self.subTest(stage=blocked_stage):
                entered=threading.Event();release=threading.Event();result=[]
                def blocked(*args):
                    entered.set()
                    if not release.wait(3):raise AssertionError('owned test release timed out')
                    return {} if blocked_stage=='rpc' else {'verified':True,'dag_order_page_verified':True}
                def worker():
                    try:result.append(self.node.export_cached_proof(packet,'order',0))
                    except BaseException as error:result.append(error)
                with patch.object(self.node,'_public_query',side_effect=blocked if blocked_stage=='rpc' else None,return_value={}),patch.object(
                        control.native,'_verify_public',side_effect=blocked if blocked_stage=='sdk' else None,return_value={'verified':True,'dag_order_page_verified':True}):
                    thread=threading.Thread(target=worker);thread.start()
                    try:
                        self.assertTrue(entered.wait(1))
                        acquired=self.node._lock.acquire(timeout=.25)
                        self.assertTrue(acquired,'public proof held consensus work lock')
                        if acquired:self.node._lock.release()
                    finally:release.set();thread.join(2)
                self.assertFalse(thread.is_alive());self.assertEqual(len(result),1)
                if isinstance(result[0],BaseException):raise result[0]
                self.assertIn('dag_order_page',result[0])

    def test_public_proof_cannot_publish_across_native_process_replacement(self):
        packet=self.node.certified_state();saved=self.node.profile.public_certificate()
        self.verify.return_value={'verified':True,'dag_order_page_verified':True}
        entered=threading.Event();release=threading.Event();errors=[]
        def blocked(*args):entered.set();release.wait(3);return {}
        def worker():
            try:self.node.export_cached_proof(packet,'order',0)
            except ValueError as error:errors.append(str(error))
        with patch.object(self.node,'_public_query',side_effect=blocked):
            thread=threading.Thread(target=worker);thread.start()
            try:
                self.assertTrue(entered.wait(1))
                with self.node._lock:self.node._node={'process':None,'_ready':None}
            finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['GG_VALIDATOR_PROOF_PROCESS_CHANGED'])
        self.assertEqual(self.node.profile.public_certificate(),saved)

    def test_public_query_has_a_separate_bounded_connection_and_preserves_work_socket(self):
        self.node.rpc_port=45123;epoch=(self.node._node,self.node.rpc_port)
        work_socket=object();self.node._connection=work_socket
        self.addCleanup(setattr,self.node,'_connection',None)
        response=Mock(status=200)
        response.read.return_value=json.dumps({'result':{'response':{'code':0,'value':base64.b64encode(b'{"start":0}').decode()}}}).encode()
        connection=Mock();connection.getresponse.return_value=response
        self.rpc.reset_mock()
        with patch.object(self.node,'_owned_endpoint',return_value=True) as owner,patch.object(control.http.client,'HTTPConnection',return_value=connection) as factory:
            self.assertEqual(self.node._public_query(epoch,'/gg/dag/order-page',9,b'{"start":0}'),{'start':0})
        factory.assert_called_once_with('127.0.0.1',45123,timeout=3)
        owner.assert_called_once_with(*epoch);response.read.assert_called_once_with(512*1024+1)
        connection.close.assert_called_once();self.rpc.assert_not_called()
        self.assertIs(self.node._connection,work_socket)

    def test_public_query_closes_its_connection_on_rejected_response(self):
        self.node.rpc_port=45123;epoch=(self.node._node,self.node.rpc_port)
        response=Mock(status=200);response.read.return_value=b'x'*(512*1024+1)
        connection=Mock();connection.getresponse.return_value=response
        with patch.object(self.node,'_owned_endpoint',return_value=True),patch.object(control.http.client,'HTTPConnection',return_value=connection):
            with self.assertRaisesRegex(ValueError,'RPC_RESPONSE'):self.node._public_query(epoch,'/gg/dag/order-page',9,b'{"start":0}')
        connection.close.assert_called_once()

    def payload_fixture(self):
        import base64
        packet=self.node.certified_state();packet['state']['dag']['blocks']=1
        chunk={'schema':'gg.dag.payload-chunk.v1','genesis_hash':packet['genesis_hash'],'hash':'c'*64,'height':9,'index':1,
            'offset':0,'state_root':packet['state']['state_root'],'total':3,'wire_hash':hashlib.sha256(b'abc').hexdigest(),
            'data':base64.b64encode(b'abc').decode('ascii')}
        return packet,chunk

    def test_payload_chunk_pins_context_and_rejects_shape_type_and_length_mutations(self):
        packet,chunk=self.payload_fixture()
        with patch.object(self.node,'_public_query',return_value=chunk):
            self.assertEqual(self.node.export_payload_chunk(packet,'c'*64,1,0)['data'],b'abc')
        for change in ({'offset':True},{'index':True},{'total':0},{'height':10},{'state_root':'f'*64},{'hash':'d'*64},
                       {'data':'!!!!'},{'data':'YWI='},{'wire_hash':'x'},{'schema':'other'}):
            with patch.object(self.node,'_public_query',return_value={**chunk,**change}),self.assertRaisesRegex(ValueError,'PAYLOAD_CHUNK'):
                self.node.export_payload_chunk(packet,'c'*64,1,0)

    def test_public_payload_epoch_check_does_not_wait_on_signing_work_lock(self):
        packet,chunk=self.payload_fixture();entered=threading.Event();release=threading.Event()
        def held():
            with self.node._lock:entered.set();release.wait(3)
        thread=threading.Thread(target=held);thread.start()
        try:
            self.assertTrue(entered.wait(1));started=time.monotonic()
            with patch.object(self.node,'_public_query',return_value=chunk):self.node.export_payload_chunk(packet,'c'*64,1,0)
            self.assertLess(time.monotonic()-started,.25)
        finally:release.set();thread.join(2)

    def test_payload_cannot_publish_after_owned_process_epoch_changes(self):
        packet,chunk=self.payload_fixture()
        def changed(*args):self.node._node={'process':None,'_ready':None};return chunk
        with patch.object(self.node,'_public_query',side_effect=changed),self.assertRaisesRegex(ValueError,'PROCESS_CHANGED'):
            self.node.export_payload_chunk(packet,'c'*64,1,0)

    def test_public_proof_rejects_malformed_selectors_before_rpc_or_sdk(self):
        packet=self.node.certified_state();self.verify.reset_mock()
        with patch.object(self.node,'_public_query') as query:
            for kind,selector in (('order',True),('order',-32),('order',1),('order',4096),('account','x'*64),('block','0'*65)):
                with self.subTest(kind=kind,selector=selector),self.assertRaises(ValueError):self.node.export_cached_proof(packet,kind,selector)
        query.assert_not_called();self.verify.assert_not_called()

    def test_unknown_broadcast_preserves_exact_transaction_hash_without_retry(self):
        self.rpc.side_effect=OSError('owned injected response loss')
        raw=b'public transport outcome fixture'
        result=self.node.submit(raw)
        self.assertEqual(result,{'state':'BROADCAST_UNKNOWN','canonical_finality':False,'hash':hashlib.sha256(raw).hexdigest()})
        self.rpc.assert_called_once();self.assertIsNone(self.node._tip)


    def test_unexpected_process_exit_is_distinct_from_historical_certificate_and_intentional_stop(self):
        from backend import gg_process_termination as termination
        self.node.certified_state();process=Mock();process.poll.return_value=73
        self.node._node={'process':process,'_ready':None};self.node._epoch_stopping=False
        real_wait=termination.wait_process_terminal;real_terminal=termination.process_terminal
        # Only this declared process double is adapted; a real child always
        # keeps its OS-terminal check, including when cleanup runs on failure.
        with patch.object(termination,'wait_process_terminal',side_effect=lambda child,timeout:73 if child is process else real_wait(child,timeout)), \
                patch.object(termination,'process_terminal',side_effect=lambda child:True if child is process else real_terminal(child)):
            try:
                view=self.node.snapshot()
                self.assertEqual(view['state'],'FAULT');self.assertEqual(view['last_error'],'GG_VALIDATOR_NATIVE_PROCESS_EXITED')
                self.assertEqual(view['native_exit_code'],73);self.assertFalse(view['owned_native_process'])
                self.assertTrue(view['canonical_finality']);self.assertFalse(view['certificate_is_network_liveness'])
                self.node._epoch_stopping=True;view=self.node.snapshot()
                self.assertEqual(view['state'],'STOPPED');self.assertEqual(view['last_error'],'');self.assertIsNone(view['native_exit_code'])
            finally:self.node.close()


if __name__=='__main__':unittest.main()
