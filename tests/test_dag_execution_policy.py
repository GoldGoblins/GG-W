"""Genesis policy binding; neither a new archive nor a monetary protocol."""
from copy import deepcopy
import json
import unittest

from backend import gg_dag_execution_policy as rules,gg_dag_checkpoint as checkpoint
from backend.gg_ed25519 import Keypair,SIGNATURE_PROFILE
from backend.gg_parallel_dag import ParallelDag,make_public_genesis,pack,digest


def bundle():
    return make_public_genesis([Keypair().pubkey().hex() for _ in range(6)],enable_dag_transactions=True)


def legacy(public):
    value=deepcopy(public);value['schema']='gg.parallel-dag.public-genesis.v2'
    value['genesis']['schema']='gg.parallel-dag.genesis.v2';value['genesis'].pop('execution_policy')
    value['genesis_hash']=digest(value['genesis'])
    return value


def source(public):
    return {'schema':checkpoint.SOURCE_SCHEMA,'signature_profile':SIGNATURE_PROFILE,
            'accounts':public['accounts'],'allowed_producers':list(range(6)),
            'genesis':public['genesis'],'genesis_hash':public['genesis_hash'],
            'network_id':'b'*64,'started_at_ns':str(public['started_at_ns'])}


class GenesisExecutionPolicyTests(unittest.TestCase):
    def test_new_nonfinancial_genesis_binds_exact_finite_rules(self):
        public=bundle()
        self.assertEqual(public['schema'],rules.PUBLIC_GENESIS_SCHEMA)
        self.assertEqual(public['genesis']['schema'],rules.GENESIS_SCHEMA)
        self.assertEqual(public['genesis']['execution_policy'],rules.execution_policy())
        self.assertEqual(public['genesis_hash'],digest(public['genesis']))
        self.assertEqual(rules.MAX_HISTORY_BLOCKS,4095)
        self.assertEqual(rules.MAX_HISTORY_RAW_BYTES,512*1024*1024)
        self.assertEqual(checkpoint.validate_source(source(public)),source(public))

    def test_descriptor_and_imported_sources_do_not_share_mutable_policy(self):
        public=bundle();expected=deepcopy(public)
        first=rules.execution_policy();first['history_max_blocks']+=1
        self.assertEqual(rules.execution_policy()['history_max_blocks'],4095)
        checked=checkpoint.validate_source(source(public));checked['genesis']['execution_policy']['history_max_blocks']+=1
        self.assertEqual(public,expected)
        node=ParallelDag.from_public_genesis(public)
        try:
            public['genesis']['execution_policy']['profile']='mutated caller'
            self.assertEqual(node.export_public_genesis(),expected)
        finally:node.stop()

    def test_legacy_v2_import_export_preserves_exact_original_bytes_and_hash(self):
        public=legacy(bundle());before=pack(public)
        node=ParallelDag.from_public_genesis(json.loads(before))
        try:
            self.assertEqual(pack(node.export_public_genesis()),before)
            self.assertNotIn('execution_policy',node.export_public_genesis()['genesis'])
            self.assertEqual(checkpoint.validate_source(source(public)),source(public))
        finally:node.stop()

    def test_new_genesis_import_export_preserves_exact_policy_and_hash(self):
        public=bundle();before=pack(public)
        node=ParallelDag.from_public_genesis(json.loads(before))
        try:self.assertEqual(pack(node.export_public_genesis()),before)
        finally:node.stop()

    def test_policy_mutations_still_reject_after_attacker_recomputes_genesis_hash(self):
        public=bundle()
        for key,item in rules.execution_policy().items():
            with self.subTest(key=key):
                changed=deepcopy(public)
                changed['genesis']['execution_policy'][key]=item+1 if type(item) is int else item+'-other'
                changed['genesis_hash']=digest(changed['genesis'])
                with self.assertRaises(ValueError):ParallelDag.from_public_genesis(changed)
                with self.assertRaisesRegex(ValueError,'SOURCE_INVALID'):checkpoint.validate_source(source(changed))

    def test_policy_rejects_integer_coercion_bool_float_and_string(self):
        for key,item in rules.execution_policy().items():
            if type(item) is not int:continue
            for replacement in (True,float(item),str(item)):
                with self.subTest(key=key,type=type(replacement).__name__):
                    changed=rules.execution_policy();changed[key]=replacement
                    with self.assertRaisesRegex(ValueError,'POLICY_UNSUPPORTED'):rules.require_execution_policy(changed)

    def test_new_policy_rejects_missing_extra_null_empty_or_unknown_descriptor(self):
        replacements=[None,{},[],False]
        missing=rules.execution_policy();missing.pop('history_verification');replacements.append(missing)
        extra=rules.execution_policy();extra['pruning_enabled']=True;replacements.append(extra)
        for replacement in replacements:
            with self.subTest(value=replacement):
                changed=bundle();changed['genesis']['execution_policy']=replacement
                changed['genesis_hash']=digest(changed['genesis'])
                with self.assertRaises(ValueError):ParallelDag.from_public_genesis(changed)
                with self.assertRaisesRegex(ValueError,'SOURCE_INVALID'):checkpoint.validate_source(source(changed))
        changed=bundle();changed['genesis'].pop('execution_policy');changed['genesis_hash']=digest(changed['genesis'])
        with self.assertRaises(ValueError):ParallelDag.from_public_genesis(changed)

    def test_old_genesis_cannot_carry_an_added_or_null_policy(self):
        for replacement in (rules.execution_policy(),None):
            changed=legacy(bundle());changed['genesis']['execution_policy']=replacement
            changed['genesis_hash']=digest(changed['genesis'])
            with self.assertRaises(ValueError):ParallelDag.from_public_genesis(changed)
            with self.assertRaisesRegex(ValueError,'SOURCE_INVALID'):checkpoint.validate_source(source(changed))

    def test_public_wrapper_and_nested_genesis_versions_must_match(self):
        for old in (False,True):
            changed=legacy(bundle()) if old else bundle()
            changed['schema']=rules.PUBLIC_GENESIS_SCHEMA if old else 'gg.parallel-dag.public-genesis.v2'
            with self.assertRaises(ValueError):ParallelDag.from_public_genesis(changed)

    def test_unknown_genesis_version_cannot_fall_back_to_current_rules(self):
        changed=bundle();changed['genesis']['schema']='gg.parallel-dag.genesis.v999'
        changed['genesis_hash']=digest(changed['genesis'])
        with self.assertRaises(ValueError):ParallelDag.from_public_genesis(changed)
        with self.assertRaisesRegex(ValueError,'SOURCE_INVALID'):checkpoint.validate_source(source(changed))

    def test_bound_genesis_produces_and_replays_real_signed_TX_without_nonce_or_owner_drift(self):
        keys=[Keypair() for _ in range(6)]
        public=make_public_genesis([key.pubkey().hex() for key in keys],enable_dag_transactions=True)
        producer=ParallelDag.from_public_genesis(public);replica=ParallelDag.from_public_genesis(public)
        try:
            producer.attach_local_producers({0:keys[0]})
            first=producer.produce_lan_test_block(0,3);second=producer.produce_lan_test_block(0,2)
            replica.admit_relayed(first['wire'],0);replica.admit_relayed(second['wire'],0)
            replica.reconcile();producer.reconcile()
            self.assertEqual(replica._preview_state,producer._preview_state)
            self.assertEqual(replica._preview_state[keys[0].pubkey().hex()]['nonce'],5)
            self.assertEqual(json.loads(second['wire'])['body']['producer_index'],0)
            self.assertEqual(replica.export_public_genesis(),public)
            self.assertEqual(replica.lan_evidence()['transactions'],5)
            self.assertEqual(replica.snapshot()['canonical_finalized'],0)
        finally:replica.stop();producer.stop()

    def test_empty_manual_genesis_remains_its_original_v1_format(self):
        public=make_public_genesis([Keypair().pubkey().hex() for _ in range(6)])
        self.assertEqual(public['schema'],'gg.parallel-dag.public-genesis.v1')
        self.assertEqual(public['genesis']['schema'],'gg.parallel-dag.genesis.v1')
        self.assertNotIn('execution_policy',public['genesis'])
        node=ParallelDag.from_public_genesis(public)
        try:self.assertEqual(node.export_public_genesis(),public)
        finally:node.stop()

    def test_legacy_encrypted_profile_reopens_same_genesis_identity_and_next_nonce(self):
        from unittest.mock import patch
        from backend import gg_lan_dag as lan
        from tests import test_durable_lan_node as fixtures
        case=fixtures.DurableLanNodeTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        def old_make(*args,**kwargs):
            value=make_public_genesis(*args,**kwargs)
            return legacy(value) if kwargs.get('enable_dag_transactions') else value
        with patch.object(lan,'make_public_genesis',side_effect=old_make):nodes=case.network()
        owner=nodes[0];before=owner._engine.export_public_genesis();invite=owner.public_invite()
        first=case.block(owner,3);resumed=case.resume(owner)
        self.assertEqual(resumed.public_invite(),invite)
        self.assertEqual(resumed._engine.export_public_genesis(),before)
        self.assertEqual(before['schema'],'gg.parallel-dag.public-genesis.v2')
        self.assertEqual(resumed._profile.snapshot()['counts']['dag'],1)
        next_block=case.block(resumed,1);body=json.loads(next_block['wire'])['body']
        self.assertEqual(body['sequence'],2);self.assertEqual(body['transactions'][0]['body']['nonce'],3)
        self.assertIn(first['hash'],body['parents'])

    def test_signed_coordinator_bootstrap_cannot_override_unknown_execution_rules(self):
        from backend import gg_consensus_membership as member,gg_lan_dag as lan
        from tests import test_lan_consensus_anchor as fixtures
        peers=fixtures.paired_peers(self);owner=peers[0]
        original=owner.create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,
                                      consensus_invites=fixtures.member_invites(peers))
        changed=deepcopy(original['body']);public=changed['public_genesis']
        public['genesis']['execution_policy']['history_max_raw_bytes']*=2
        public['genesis_hash']=digest(public['genesis'])
        signed=lan._signed(key=owner._identity,domain=lan._BUNDLE,body=changed)
        with self.assertRaisesRegex(ValueError,'ANCHOR_INVALID'):member.anchor_from_bundle(signed,owner.public_key)
        with self.assertRaises(ValueError):peers[1].install_session(signed,_start_gossip=False)
        self.assertIsNone(peers[1]._engine)

    def test_legacy_signed_committee_bootstrap_preserves_its_original_policy(self):
        from backend import gg_consensus_membership as member,gg_lan_dag as lan
        from tests import test_lan_consensus_anchor as fixtures
        peers=fixtures.paired_peers(self);owner=peers[0]
        original=owner.create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,
                                      consensus_invites=fixtures.member_invites(peers))
        changed=deepcopy(original['body']);changed['public_genesis']=legacy(changed['public_genesis'])
        signed=lan._signed(key=owner._identity,domain=lan._BUNDLE,body=changed)
        pinned=member.anchor_from_bundle(signed,owner.public_key)
        for peer in peers:peer.install_session(signed,_start_gossip=False)
        self.assertTrue(all(checkpoint.source_from_owned_peer(peer)==pinned['genesis']['dag'] for peer in peers))
        self.assertNotIn('execution_policy',pinned['genesis']['dag']['genesis'])
        self.assertEqual(pinned['genesis']['dag']['genesis_hash'],changed['public_genesis']['genesis_hash'])


if __name__=='__main__':unittest.main()
