"""Actual protected pairing/install/resume; no SDK quorum is mocked as real.

Background proof workers are disabled in these lifecycle tests. Actual signed
TCP installs use real listeners and real encrypted key/profile stores.
"""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import lan_dag_runtime as runtime,gg_node_store as nodes,gg_consensus_profile as validators
from backend import portable_wallet_vault as vault,terminal_cli as cli
from backend.gg_segmented_proof_sync import SegmentedProofExchange


class SegmentedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-segmented-runtime-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('public protected source2 runtime fixture'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.workers=self.stack.enter_context(patch.object(SegmentedProofExchange,'start'))
        self.managers=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for manager in reversed(self.managers):manager.stop()

    def manager(self,label,bootstrap=None,role='producer'):
        manager=runtime.LanDagRuntime();self.managers.append(manager)
        args={'label':label,'bind_host':'127.0.0.1','port':0,'allowed_cidr':'127.0.0.0/8',
            'allow_dag_transactions':True,'profile':label,'node_role':role}
        if bootstrap is not None:args['bootstrap']=bootstrap
        manager.dispatch('lan.start',args);return manager

    def network(self,*,segmented=True,third_role='producer'):
        first=self.manager('Windows');bootstrap=first.dispatch('lan.bootstrap')
        second=self.manager('Linux',bootstrap);third=self.manager('Termux',bootstrap,role=third_role)
        for manager in (first,second):
            for slot in range(2):manager.dispatch('lan.validator_create',{'profile':manager._peer.label+str(slot)})
        second.dispatch('lan.announce');third.dispatch('lan.announce')
        first.dispatch('lan.session_create',{'enable_consensus':True,'enable_dag_transactions':True,'enable_segmented':segmented,'distribute':True})
        return first,second,third

    def test_actual_signed_install_reaches_all_three_protected_profiles_without_legacy_engine(self):
        managers=self.network();bundle=managers[0]._bundle
        self.assertEqual(bundle['body']['schema'],'gg.lan-dag.session.v5')
        for manager in managers:
            peer=manager._peer
            self.assertEqual(peer._bundle,bundle);self.assertEqual(peer._profile.session(),bundle)
            self.assertIsNone(peer._engine);self.assertIsInstance(peer._proof_service,SegmentedProofExchange)
            self.assertEqual(len(peer._roster),3);self.assertEqual(manager.snapshot()['lan']['state'],'READY')
        self.assertEqual(managers[0]._distribution,[{'label':row['label'],'state':'READY'} for key,row in managers[0]._peer._roster.items() if key!=managers[0]._peer.public_key])

    def test_status_preserves_actual_role_and_owner_labels_without_claiming_replay_or_activity(self):
        managers=self.network()
        for manager in managers:
            status=manager.snapshot();labels={row['node_label'] for row in status['producers']}
            self.assertEqual(labels,{'Windows','Linux','Termux'})
            self.assertEqual(status['lan']['participation']['role'],'producer')
            self.assertFalse(status['lan']['participation']['light_client']);self.assertFalse(status['local_full_history_replayed'])
            self.assertFalse(status['dag_proofs']['canonical_finality']);self.assertIsNone(status['certified_transactions'])
            self.assertEqual(status['block_graph']['edges'],[]);self.assertFalse(status['block_graph']['causal_edges_verified'])
            self.assertEqual(status['lan']['authenticated_exchanges'],0)

    def test_resume_reopens_original_keys_endpoint_bundle_and_real_source2_service(self):
        managers=self.network();first=managers[0];before=first._peer._profile.descriptor();bundle=deepcopy(first._peer._bundle)
        first.stop();first.dispatch('lan.resume',{'profile':'Windows'})
        self.assertEqual(first._peer._profile.descriptor(),before);self.assertEqual(first._peer._bundle,bundle)
        self.assertIsInstance(first._peer._proof_service,SegmentedProofExchange);self.assertIsNone(first._peer._engine)
        self.assertEqual(first.snapshot()['lan']['state'],'READY')

    def test_declared_replica_with_only_sparse_proofs_does_not_claim_full_payload_replay(self):
        _,_,third=self.network(third_role='replica');status=third.snapshot()
        self.assertEqual(status['lan']['participation']['role'],'replica')
        self.assertFalse(status['lan']['participation']['replica']);self.assertTrue(status['lan']['participation']['observer'])
        self.assertFalse(status['local_full_history_replayed']);self.assertFalse(status['dag_production']['enabled'])

    def test_nonempty_or_bound_legacy_network_is_not_cleared_or_rebound(self):
        managers=self.network(segmented=False);first=managers[0];profile=first._peer._profile
        old=deepcopy(profile.session());keys=list(profile.descriptor()['public_keys'])
        with self.assertRaisesRegex(ValueError,'LEGACY_HISTORY_TRANSITION_REQUIRED'):
            first.dispatch('lan.session_create',{'enable_consensus':True,'enable_dag_transactions':True,'enable_segmented':True})
        self.assertEqual(profile.session(),old);self.assertEqual(profile.descriptor()['public_keys'],keys)
        self.assertIsNotNone(first._peer._engine)

    def test_foreign_new_network_cannot_silently_replace_original_v5_binding(self):
        managers=self.network();first=managers[0];old=deepcopy(first._peer._bundle)
        with self.assertRaisesRegex(ValueError,'NETWORK_ALREADY_BOUND'):
            first.dispatch('lan.session_create',{'enable_consensus':True,'enable_dag_transactions':True,'enable_segmented':True})
        self.assertEqual(first._peer._bundle,old);self.assertEqual(first._peer._profile.session(),old)

    def test_current_network_pin_cannot_change_after_source2_binding(self):
        managers=self.network();first=managers[0];old=first._peer._trusted
        with self.assertRaisesRegex(ValueError,'TRUST_ALREADY_BOUND'):first.dispatch('lan.pin',{'public_key':managers[1]._peer.public_key})
        self.assertEqual(first._peer._trusted,old)

    def test_segmented_option_requires_explicit_DAG_consensus_and_remains_off_by_default(self):
        manager=self.manager('Windows')
        for args in ({'enable_segmented':True},{'enable_segmented':True,'enable_dag_transactions':True},
                     {'enable_segmented':True,'enable_dag_transactions':True,'enable_consensus':True,'enable_test_tokens':True},
                     {'enable_segmented':'true'}):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):manager.dispatch('lan.session_create',args)
        self.assertIsNone(manager._peer._profile.session());self.assertIsNone(manager._peer._bundle)

    def test_terminal_boolean_options_are_typed_before_runtime_dispatch(self):
        command,args=cli.parse_command('lan.session_create enable_dag_transactions=true enable_consensus=true enable_segmented=true distribute=false')
        self.assertEqual(command,'lan.session_create')
        self.assertEqual(args,{'enable_dag_transactions':True,'enable_consensus':True,'enable_segmented':True,'distribute':False})


if __name__=='__main__':unittest.main()
