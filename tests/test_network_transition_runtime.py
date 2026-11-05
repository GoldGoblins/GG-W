"""Shared stopped-node CLI workflow; genuine signatures, no mocked SDK result."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from backend import gg_node_store as nodes,gg_network_transition as transition,gg_consensus_profile as validators,gg_lan_dag as lan,terminal_cli
from backend.gg_dag_proof_sync import ProofExchange
from tests import test_lan_segmented_runtime as fixture


class NetworkTransitionRuntimeTests(unittest.TestCase):
    cleanup=fixture.SegmentedRuntimeTests.cleanup
    manager=fixture.SegmentedRuntimeTests.manager
    network=fixture.SegmentedRuntimeTests.network

    def setUp(self):
        fixture.SegmentedRuntimeTests.setUp(self)
        self.stack.enter_context(patch.object(ProofExchange,'_serve_work'))
        self.stack.enter_context(patch.object(ProofExchange,'_client_work'))
        self.stack.enter_context(patch.object(lan.LanDagPeer,'_start_gossip'))
        self.owners=self.network(segmented=False);self.root=Path(self.temp.name)
        third=self.owners[2]._peer
        third._engine.produce_lan_test_block(third._local_indices[0],3,third._wire_limit)

    def prepare(self,offline):
        names=['Windows','Linux','Termux'];paths=[];before=[deepcopy(manager._peer._profile._meta) for manager in self.owners]
        if offline:
            for manager in self.owners:manager.stop()
        for index,manager in enumerate(self.owners):
            profiles=[];owner={'owner_profile':names[index]} if offline else {}
            for slot in range(2 if index<2 else 0):
                name='Transition'+names[index]+str(slot);profiles.append(name)
                result=manager.dispatch('lan.validator_transition_create',{'profile':name,**owner})
                self.assertEqual(result['state'],'PREPARED_UNBOUND_VALIDATOR');self.assertFalse(result['native_started'])
            path=self.root/(names[index]+'-next.json');paths.append(str(path))
            result=manager.dispatch('lan.transition_invite',{'profiles':profiles,'path':str(path),**owner})
            self.assertEqual(json.loads(path.read_text()),result['invite']);self.assertFalse(result['old_session_changed'])
        out=self.root/'transition.json'
        result=self.owners[0].dispatch('lan.transition_prepare',{'invite_paths':paths,'path':str(out),**({'owner_profile':'Windows'} if offline else {})})
        self.assertFalse(result['old_session_changed']);self.assertEqual(json.loads(out.read_text()),result['document'])
        for name,previous in zip(names,before):
            if offline:
                profile=nodes.NodeProfile.open(name)
                try:self.assertEqual(profile._meta,previous)
                finally:profile.close()
            else:self.assertEqual(self.owners[names.index(name)]._peer._profile._meta,previous)
        return out,result['document']

    def test_offline_file_workflow_preserves_owner_and_original_then_resumes_v5(self):
        path,document=self.prepare(True)
        for name,manager in zip(('Windows','Linux','Termux'),self.owners):
            result=manager.dispatch('lan.transition_commit',{'profile':name,'path':str(path)})
            self.assertEqual(result['state'],'NETWORK_TRANSITION_COMPLETE');self.assertFalse(result['network_started'])
            self.assertFalse(manager.active)
            status=manager.dispatch('lan.resume',{'profile':name})
            self.assertEqual(manager._peer._bundle,document['body']['bundle']);self.assertIsNone(manager._peer._engine)
            self.assertEqual(status['dag_consensus']['own_running'],0)
        self.assertEqual(result['archived_original_records'],1);self.assertEqual(result['archived_admitted_transactions'],3)

    def test_active_preparation_never_installs_target_or_stops_old_peer(self):
        path,document=self.prepare(False);manager=self.owners[2]
        with self.assertRaisesRegex(ValueError,'STOP_BEFORE_NETWORK_TRANSITION'):
            manager.dispatch('lan.transition_commit',{'profile':'Termux','document':document})
        self.assertTrue(manager.active);self.assertEqual(manager._peer._bundle['body']['schema'],'gg.lan-dag.session.v4')
        with self.assertRaises(ValueError):manager.dispatch('lan.transition_commit',{'profile':'Termux','path':str(path),'force':True})

    def test_foreign_target_owner_cannot_open_or_advertise_another_nodes_prepared_validator(self):
        result=self.owners[0].dispatch('lan.validator_transition_create',{'profile':'PreparedWindows'})
        with self.assertRaisesRegex(ValueError,'NEW_VALIDATOR_IDENTITIES_REQUIRED'):
            self.owners[1].dispatch('lan.transition_invite',{'profiles':['PreparedWindows']})
        profile=validators.ValidatorProfile.open('PreparedWindows')
        try:self.assertEqual(profile.public_invite(),result['invite']);self.assertIsNone(profile.anchor())
        finally:profile.close()

    def test_priority_stop_cancels_owned_transition_and_clears_busy_state(self):
        manager=self.owners[2];manager.stop()
        def execute(name,document,**kwargs):
            self.assertTrue(manager.active);self.assertEqual(manager.snapshot()['lan']['state'],'NETWORK_TRANSITION')
            manager.request_stop();kwargs['check']()
        with patch.object(transition,'transition',side_effect=execute):
            with self.assertRaisesRegex(ValueError,'TRANSITION_CANCELLED'):
                manager.dispatch('lan.transition_commit',{'profile':'Termux','document':{'explicit policy seam':'no SDK evidence'}})
        self.assertFalse(manager.active);self.assertFalse(manager._network_transitioning)

    def test_portable_password_protected_owners_keep_same_ciphertexts_across_offline_transition(self):
        for manager in self.owners:manager.stop()
        with patch.object(nodes,'ROOT',self.root/'portable-owners'),patch.object(validators,'ROOT',self.root/'portable-validators'),\
                patch.object(nodes.vault,'provider',return_value='SCRYPT_AES256_GCM'):
            self.owners=self.network(segmented=False)
            third=self.owners[2]._peer;third._engine.produce_lan_test_block(third._local_indices[0],3,third._wire_limit)
            before=[deepcopy(manager._peer._profile._meta['protected_keys']) for manager in self.owners]
            path,document=self.prepare(True)
            for index,(name,manager) in enumerate(zip(('Windows','Linux','Termux'),self.owners)):
                result=manager.dispatch('lan.transition_commit',{'profile':name,'path':str(path)})
                self.assertTrue(result['protected_owner_keys_preserved'])
                opened=nodes.NodeProfile.open(name)
                try:
                    self.assertEqual(opened.descriptor()['key_storage'],'SCRYPT_AES256_GCM')
                    self.assertEqual(opened._meta['protected_keys'],before[index]);opened.signers()
                finally:opened.close()

    def test_json_offline_CLI_unlock_requires_real_TTY_and_never_serializes_password(self):
        class Service:
            def dispatch(service,command,args):
                service.secret('Public test-only hidden prompt');return {'state':'COMPLETE'}
            def close(service):pass
        arguments=['--json','--command','lan.transition_commit','--args','{"profile":"Termux","path":"public-fixture.json"}']
        for tty in (False,True):
            with self.subTest(tty=tty):
                output=io.StringIO()
                with redirect_stdout(output),patch('sys.stdin.isatty',return_value=tty),patch.object(output,'isatty',return_value=tty),\
                        patch('sys.stderr.isatty',return_value=tty),patch('getpass.getpass',return_value='public fixture passphrase') as prompt:
                    code=terminal_cli.main(arguments,Service)
                self.assertEqual(code,0 if tty else 1)
                self.assertEqual(prompt.call_count,1 if tty else 0)
                self.assertNotIn('public fixture passphrase',output.getvalue())


if __name__=='__main__':unittest.main()
