"""Owned transition policies with explicit native-process/result seams.

Actual compiled native transitions and real SDK restart/catchup are separate
evidence. These tests use real protected profiles, without claiming SDK crypto
for their deliberately mocked child receipts.
"""
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_segmented_index_transition as maintenance,terminal_cli
from backend.gg_parallel_dag import pack
from tests import test_segmented_authority as authority_fixture,test_lan_segmented_runtime as runtime_fixture


class Child:
    def __init__(self,output):
        self.output=output;self.returncode=None;self.stdin=io.BytesIO();self.stdout=io.BytesIO();self.calls=[];self.killed=0;self.timeout_once=False
    def communicate(self,input=None,timeout=None):
        self.calls.append(input)
        if self.timeout_once and len(self.calls)==1:raise subprocess.TimeoutExpired('public fixture child',timeout)
        self.returncode=0;return self.output,None
    def poll(self):return self.returncode
    def kill(self):self.killed+=1;self.returncode=-9
    def wait(self,timeout=None):return self.returncode


class OwnedIndexTransitionPolicyTests(unittest.TestCase):
    setUp=authority_fixture.SegmentedAuthorityPolicyTests.setUp
    cleanup=authority_fixture.SegmentedAuthorityPolicyTests.cleanup
    verified=authority_fixture.SegmentedAuthorityPolicyTests.verified

    def test_local_request_preserves_unicode_and_matches_Go_string_escaping(self):
        request={'schema':'public fixture','root':'C:\\nöd & <node>\u2028\u2029'}
        wire=maintenance._request_bytes(request)
        self.assertEqual(json.loads(wire),request)
        self.assertIn('nöd'.encode('utf-8'),wire)
        for escaped in (b'\\u0026',b'\\u003c',b'\\u003e',b'\\u2028',b'\\u2029'):
            self.assertIn(escaped,wire)
        self.assertNotIn(b'\\u00f6',wire)
        self.assertEqual(maintenance._request_bytes({'z':1,'a':'ASCII'}),pack({'z':1,'a':'ASCII'}))

    def receipt(self):
        return {'schema':'gg.dag.index-transition-result.v1','state':'INDEX_TRANSITION_COMPLETE','verified':True,
            'verification_scope':maintenance.SCOPE,'genesis_hash':self.control.anchor['genesis_hash'],
            'source_hash':self.state['dag_segmented']['source_hash'],'commitment':deepcopy(self.state['dag_segmented']),
            'indexed_epochs':'0','history_sha256':'a'*64,'native_state_height':0,'native_state_root':'b'*64,
            'original_history_replayed':True,'native_transfer_history_replayed':False,'signers_opened':False,'consensus_started':False,'network_started':False}

    def launch(self,value=None):
        process=Child(pack(self.receipt() if value is None else value));lease=SimpleNamespace(close=Mock())
        self.stack.enter_context(patch.object(maintenance.subprocess,'Popen',return_value=process))
        self.stack.enter_context(patch.object(maintenance,'contain',return_value=lease));return process,lease

    def test_only_public_pin_and_owned_root_reach_child_without_signer_or_startup_intent(self):
        process,lease=self.launch();profile=self.profiles[0];before=deepcopy(profile._body)
        with patch.object(profile,'native_signers',side_effect=AssertionError('signer must remain unopened')) as signing,\
             patch.object(profile,'claim_native_start',side_effect=AssertionError('start intent must remain unchanged')) as claim:
            result=maintenance.transition(profile,self.contexts[0],tools=Path(self.temp.name))
        request=json.loads(process.calls[0]);self.assertEqual(set(request),{'schema','genesis','genesis_hash','root'})
        self.assertEqual(request['root'],str(profile.root/'native'));self.assertEqual(request['genesis_hash'],self.control.anchor['genesis_hash'])
        self.assertFalse(result['network_started']);self.assertFalse(result['signers_opened']);self.assertEqual(profile._body,before)
        signing.assert_not_called();claim.assert_not_called();lease.close.assert_called_once();self.assertTrue(process.stdin.closed and process.stdout.closed)

    def test_receipt_cannot_claim_network_signing_money_replay_or_unknown_scope(self):
        for field,value in (('network_started',True),('signers_opened',True),('consensus_started',True),('native_transfer_history_replayed',True),
                            ('verification_scope','OTHER'),('verified',False),('indexed_epochs','1'),('native_state_height',True),('caller_verified',True)):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):maintenance._receipt({**self.receipt(),field:value},self.control.anchor)

    def test_stopped_owner_and_unstarted_history_are_refused_before_child(self):
        with patch.object(maintenance.subprocess,'Popen') as launch,patch.object(self.contexts[0],'stopped',return_value=True):
            with self.assertRaises(ValueError):maintenance.transition(self.profiles[0],self.contexts[0])
            launch.assert_not_called()
        profile=self.profiles[0];profile._body['native_started']=False
        try:
            with patch.object(maintenance.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(ValueError,'NATIVE_HISTORY_REQUIRED'):maintenance.transition(profile,self.contexts[0])
                launch.assert_not_called()
        finally:profile._body['native_started']=True

    def test_wrong_session_owner_or_unbound_pin_cannot_select_another_root(self):
        with patch.object(maintenance.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(ValueError,'SESSION_PIN'):maintenance.transition(self.profiles[0],self.contexts[1])
            with patch.object(self.profiles[0],'anchor',return_value=None):
                with self.assertRaisesRegex(ValueError,'SESSION_PIN'):maintenance.transition(self.profiles[0],self.contexts[0])
            launch.assert_not_called()

    def test_cancellation_during_child_wait_kills_only_owned_child_and_closes_lease(self):
        process,lease=self.launch();process.timeout_once=True;calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls>=3:raise ValueError('GG_PUBLIC_TEST_CANCEL')
        with self.assertRaisesRegex(ValueError,'PUBLIC_TEST_CANCEL'):maintenance.transition(self.profiles[0],self.contexts[0],check=check)
        self.assertEqual(process.killed,1);lease.close.assert_called_once();self.assertTrue(process.stdout.closed)

    def test_changed_binary_is_detected_after_child_completion_without_publishing_receipt(self):
        process,lease=self.launch();communicate=process.communicate
        def changed(**kwargs):
            result=communicate(**kwargs);self.binary.write_bytes(b'changed public fixture executable');return result
        process.communicate=changed
        with self.assertRaisesRegex(ValueError,'BINARY_CHANGED'):maintenance.transition(self.profiles[0],self.contexts[0])
        lease.close.assert_called_once()

    def test_timeout_bounds_and_malformed_receipts_fail_without_signing(self):
        for timeout in (True,0,1801,'60',float('nan')):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(ValueError,'TIMEOUT'):maintenance.transition(self.profiles[0],self.contexts[0],timeout=timeout)
        process,lease=self.launch();process.output=b'not public JSON'
        with self.assertRaisesRegex(ValueError,'RECEIPT'):maintenance.transition(self.profiles[0],self.contexts[0])
        lease.close.assert_called_once()


class RuntimeIndexTransitionPolicyTests(unittest.TestCase):
    setUp=runtime_fixture.SegmentedRuntimeTests.setUp
    cleanup=runtime_fixture.SegmentedRuntimeTests.cleanup
    manager=runtime_fixture.SegmentedRuntimeTests.manager
    network=runtime_fixture.SegmentedRuntimeTests.network

    def test_real_runtime_routes_only_stopped_profile_and_reports_storage_work_without_validator_start(self):
        first,_,_=self.network();receipt={'public':'explicit mocked transition result'}
        def run(profile,session,**kwargs):
            state=first.snapshot()['dag_consensus'];self.assertEqual(state['storage_transition_profiles'],['Windows0']);self.assertEqual(state['own_running'],0)
            self.assertEqual(next(row for row in state['profiles'] if row['profile']=='Windows0')['state'],'INDEX_TRANSITION')
            with self.assertRaisesRegex(ValueError,'OPERATION_BUSY'):first._start_validator('Windows0')
            kwargs['check']();return receipt
        with patch.object(maintenance,'transition',side_effect=run) as transition:
            result=first.dispatch('lan.validator_index_transition',{'profile':'Windows0','timeout':60})
        self.assertEqual(result,{'profile':'Windows0','storage_transition':receipt});self.assertEqual(first._validator_transitioning,set());self.assertEqual(transition.call_count,1)

    def test_running_validator_is_never_stopped_implicitly_for_transition(self):
        first,_,_=self.network();node=SimpleNamespace(_alive=lambda:True)
        first._validator_nodes['Windows0']=node
        try:
            with patch.object(maintenance,'transition') as transition:
                with self.assertRaisesRegex(ValueError,'STOP_VALIDATOR_FIRST'):first.dispatch('lan.validator_index_transition',{'profile':'Windows0'})
                transition.assert_not_called()
        finally:first._validator_nodes.pop('Windows0')

    def test_runtime_stop_or_resource_pause_cancels_maintenance_and_clears_busy_state(self):
        first,_,_=self.network()
        def run(profile,session,**kwargs):
            first._stop_requested.set();kwargs['check']()
        try:
            with patch.object(maintenance,'transition',side_effect=run):
                with self.assertRaisesRegex(ValueError,'LAN_STOPPED'):first.dispatch('lan.validator_index_transition',{'profile':'Windows0'})
            self.assertEqual(first._validator_transitioning,set())
        finally:first._stop_requested.clear()

    def test_cli_timeout_is_typed_and_unknown_force_flag_is_not_an_approval_bypass(self):
        command,args=terminal_cli.parse_command('lan.validator_index_transition profile=Windows0 timeout=60')
        self.assertEqual(command,'lan.validator_index_transition');self.assertEqual(args,{'profile':'Windows0','timeout':60})
        first,_,_=self.network()
        with self.assertRaises(ValueError):first.dispatch(command,{**args,'force':True})


if __name__=='__main__':unittest.main()
