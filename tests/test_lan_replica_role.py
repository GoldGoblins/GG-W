"""Signed full-replica policy is enforced at admission, not merely by controls."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from backend import gg_lan_dag as lan,lan_dag_runtime as runtime,gg_node_store as store
from backend.gg_parallel_dag import ParallelDag
from tests import test_durable_lan_node as fixture


class ReplicaRoleTests(unittest.TestCase):
    setUp=fixture.DurableLanNodeTests.setUp
    cleanup=fixture.DurableLanNodeTests.cleanup
    peer=fixture.DurableLanNodeTests.peer
    network=fixture.DurableLanNodeTests.network
    resume=fixture.DurableLanNodeTests.resume
    block=fixture.DurableLanNodeTests.block

    def forbidden_block(self,replica):
        # An adversarial local caller deliberately bypasses replica controls
        # and signs with the actual reserved key. Honest admissions must refuse.
        index=replica._roster[replica.public_key]['producer_indices'][0]
        attacker=ParallelDag.from_public_genesis(replica._bundle['body']['public_genesis'])
        self.addCleanup(attacker.stop);attacker.attach_local_producers({index:replica._local_keys[0]})
        return attacker.produce_lan_test_block(index,1)['wire']

    def test_replica_verifies_real_transactions_but_has_no_attached_producer_or_start_authority(self):
        a,b,replica=self.network(replica_index=2)
        for node in (a,b):replica._engine.admit_relayed(self.block(node)['wire'],0)
        status=replica.snapshot();part=status['lan']['participation']
        self.assertFalse(part['producer']);self.assertTrue(part['replica']);self.assertFalse(part['consensus_validator']);self.assertFalse(part['light_client'])
        self.assertEqual(part['eligible_network_producers'],4);self.assertEqual(part['local_producer_count'],0)
        self.assertFalse(any(replica._engine._producer_keys));self.assertEqual(status['transactions_validated'],4)
        self.assertFalse(status['dag_production']['can_start']);self.assertFalse(status['dag_stress']['can_start'])
        for start in (replica.start_dag_production,replica.start_producing,replica.start_dag_stress):
            with self.assertRaisesRegex(ValueError,'REPLICA_READ_ONLY'):start()
        with self.assertRaisesRegex(ValueError,'PRODUCER_ROSTER_REQUIRED'):a.start_dag_stress()

    def test_valid_signature_from_a_replica_slot_is_rejected_by_small_large_and_forked_verifiers(self):
        a,_,replica=self.network(replica_index=2);raw=self.forbidden_block(replica)
        for node in (a,replica):
            with self.assertRaisesRegex(ValueError,'ROLE_FORBIDDEN'):node._engine.admit_relayed(raw,0)
            with self.assertRaisesRegex(ValueError,'ROLE_FORBIDDEN'):node._engine.inspect_empty_proposal(raw)
        fork=a._engine.fork_verifier();self.addCleanup(fork.stop)
        with self.assertRaisesRegex(ValueError,'ROLE_FORBIDDEN'):fork.admit_relayed(raw,0)
        # The same signed-roster authorization also guards the original small
        # parser path, not only the large-block optimization.
        small=ParallelDag.from_public_genesis(a._bundle['body']['public_genesis']);self.addCleanup(small.stop)
        small.configure_lan_roles(list(a._engine._producer_policy))
        with self.assertRaisesRegex(ValueError,'ROLE_FORBIDDEN'):small.admit_relayed(raw,0)
        self.assertEqual(a._engine.lan_evidence()['blocks'],0)

    def test_role_is_signed_and_cannot_be_promoted_by_mutating_an_invite(self):
        _,_,replica=self.network(replica_index=2);invite=replica.public_invite()
        self.assertEqual(lan.validate_invite(invite)['node_role'],'replica')
        forged=deepcopy(invite);forged['body']['node_role']='producer'
        with self.assertRaises(ValueError):lan.validate_invite(forged)

    def test_replica_role_and_history_survive_restart_without_attaching_signers(self):
        producer,_,replica=self.network(replica_index=2)
        replica._engine.admit_relayed(self.block(producer)['wire'],0)
        before=replica._engine.lan_evidence();resumed=self.resume(replica)
        self.assertEqual(resumed._engine.lan_evidence(),before)
        self.assertEqual(resumed.node_role,'replica');self.assertFalse(any(resumed._engine._producer_keys))
        with self.assertRaisesRegex(ValueError,'REPLICA_READ_ONLY'):resumed.start_dag_production()

    def test_replay_rejects_forbidden_role_even_with_a_valid_local_storage_head(self):
        _,_,replica=self.network(replica_index=2);replica._profile.append('dag',[self.forbidden_block(replica)])
        name=replica._profile.name;replica.stop();owned=store.NodeProfile.open(name);self.addCleanup(owned.close)
        resumed=self.peer(owned)
        with patch.object(lan.socket,'socket') as listener:
            with self.assertRaisesRegex(ValueError,'ROLE_FORBIDDEN'):resumed.start_pairing()
            listener.assert_not_called()

    def test_invalid_roles_and_incompatible_signing_options_create_no_profile(self):
        for options in ({'node_role':'light'},{'node_role':'validator'},{'node_role':'replica','auto_produce':True},
                        {'node_role':'replica','allow_test_tokens':True}):
            manager=runtime.LanDagRuntime();self.addCleanup(manager.stop)
            with self.assertRaises(ValueError):manager.start(profile='Invalid',bind_host='127.0.0.1',port=0,**options)
            self.assertFalse(manager.active)
        self.assertFalse(store.ROOT.exists())


if __name__=='__main__':unittest.main()
