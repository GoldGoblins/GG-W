"""Real protocol replay over disposable encrypted profiles and owned listeners."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend import gg_lan_dag as lan,gg_node_store as store,portable_wallet_vault as vault
from backend.gg_parallel_dag import pack


class DurableLanNodeTests(unittest.TestCase):
    def setUp(self):
        self.unlock=vault.session('disposable node fixture password');self.unlock.__enter__();self.addCleanup(self.unlock.__exit__,None,None,None)
        self.temp=tempfile.TemporaryDirectory(prefix='gg-durable-protocol-');self.addCleanup(self.temp.cleanup)
        self.scope=patch.object(store,'ROOT',Path(self.temp.name)/'nodes');self.scope.start();self.addCleanup(self.scope.stop)
        self.peers=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for peer in reversed(self.peers):peer.stop()

    def peer(self,profile):
        config=profile.descriptor()
        peer=lan.LanDagPeer(config['label'],config['host'],config['port'],config['trusted_coordinator'],False,
            allowed_cidr=config['allowed_cidr'],allow_test_tokens=config['allow_test_tokens'],
            allow_dag_transactions=config['allow_dag_transactions'],node_profile=profile,node_role=config.get('node_role','producer'))
        # These cases exercise persistence in isolation from background pulls.
        peer._start_gossip=Mock();self.peers.append(peer)
        return peer

    def network(self,tokens=False,replica_index=None):
        nodes=[]
        for index in range(3):
            profile=store.NodeProfile.create('Node'+str(index),{'label':'Owned '+str(index),'host':'127.0.0.1',
                'port':0,'allowed_cidr':'127.0.0.0/8','trusted_coordinator':None,
                'allow_test_tokens':tokens,'allow_dag_transactions':not tokens,'node_role':'replica' if index==replica_index else 'producer'})
            peer=self.peer(profile);peer.start_pairing();nodes.append(peer)
        for peer in nodes[1:]:peer.pin_coordinator(nodes[0].public_key)
        bundle=nodes[0].create_session([peer.public_invite() for peer in nodes],
            enable_test_tokens=tokens,enable_dag_transactions=not tokens)
        for peer in nodes:peer.install_session(bundle)
        return nodes

    def resume(self,peer):
        name=peer._profile.name;peer.stop()
        owned=store.NodeProfile.open(name);self.addCleanup(owned.close)
        resumed=self.peer(owned);resumed.start_pairing();return resumed

    def block(self,peer,count=2):
        return peer._engine.produce_lan_test_block(peer._local_indices[0],count,peer._wire_limit)

    def test_exact_identity_history_account_state_and_next_sequence_survive_restart(self):
        nodes=self.network();owner=nodes[1];first=self.block(owner)
        other=self.block(nodes[0],3)
        owner._engine.admit_relayed(other['wire'],0);second=self.block(owner,1)
        before=owner._engine.lan_evidence();invite=owner.public_invite();accounts=deepcopy(owner._engine._preview_state)
        resumed=self.resume(owner)
        self.assertEqual(resumed.public_invite(),invite)
        self.assertEqual(resumed._engine.lan_evidence(),before)
        self.assertEqual(resumed._engine._preview_state,accounts)
        self.assertEqual(resumed._profile.snapshot()['counts'],{'dag':3,'token':0})
        self.assertEqual(list(resumed._engine._rate_samples),[])
        self.assertEqual(resumed.snapshot()['measurements'],[])
        self.assertEqual(resumed._node_snapshot()['state'],'IDLE')
        third=self.block(resumed,1);body=json.loads(third['wire'])['body']
        self.assertEqual(body['sequence'],json.loads(second['wire'])['body']['sequence']+1)
        self.assertIn(second['hash'],body['parents']);self.assertEqual(resumed.snapshot()['canonical_finalized'],0)

    def test_failed_commit_is_not_exposed_and_cannot_be_followed_by_more_work(self):
        owner=self.network()[0];before=owner._engine.lan_evidence()
        with patch.object(owner._profile,'_commit',side_effect=OSError('owned injected storage failure')):
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):self.block(owner)
        self.assertEqual(owner._engine.lan_evidence()['blocks'],before['blocks'])
        self.assertEqual(owner._profile.snapshot()['records'],0)
        with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):self.block(owner)
        resumed=self.resume(owner);self.assertEqual(resumed._engine.lan_evidence()['blocks'],0)
        self.assertEqual(json.loads(self.block(resumed)['wire'])['body']['sequence'],1)

    def test_successful_commit_with_lost_completion_recovers_before_signing_next_sequence(self):
        owner=self.network()[0];commit=owner._profile._commit
        def lost_completion():commit();raise OSError('injected completion loss')
        with patch.object(owner._profile,'_commit',side_effect=lost_completion):
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):self.block(owner)
        self.assertEqual(owner._engine.lan_evidence()['blocks'],0)
        resumed=self.resume(owner);self.assertEqual(resumed._engine.lan_evidence()['blocks'],1)
        self.assertEqual(json.loads(self.block(resumed)['wire'])['body']['sequence'],2)

    def test_container_integrity_does_not_replace_protocol_validation(self):
        owner=self.network()[0];valid=self.block(owner)
        invalid=json.loads(valid['wire']);invalid['body']['created_at_ns']+=1
        # Test-only valid storage transaction containing a bad protocol record.
        owner._profile.append('dag',[pack(invalid)]);name=owner._profile.name;owner.stop()
        owned=store.NodeProfile.open(name);self.addCleanup(owned.close);resumed=self.peer(owned)
        with patch.object(lan.socket,'socket') as listener:
            with self.assertRaisesRegex(ValueError,'SIGNATURE'):resumed.start_pairing()
            listener.assert_not_called()
        self.assertIsNone(resumed._engine);self.assertEqual(owned.snapshot()['records'],2)

    def test_fully_verified_branch_quarantine_and_both_payloads_are_durable(self):
        owner=self.network()[0];block=self.block(owner);competing=json.loads(block['wire'])
        competing['body']['created_at_ns']+=1
        competing['signature']=owner._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(competing['body'])).hex()
        owner._engine.admit_relayed(pack(competing),0)
        resumed=self.resume(owner)
        with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.block(resumed)
        self.assertEqual(resumed._profile.snapshot()['records'],2)
        self.assertEqual(resumed._profile.fault(),'')
        resumed._engine.produce_lan_test_block(resumed._local_indices[1],1)

    def test_legacy_global_fault_without_both_payloads_is_never_silently_cleared(self):
        owner=self.network()[0];self.block(owner)
        owner._profile.latch_fault('GG_DAG_PRODUCER_EQUIVOCATION')
        resumed=self.resume(owner)
        with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):self.block(resumed)
        self.assertEqual(resumed._profile.snapshot()['records'],1)

    def assert_branch_write_outcome(self,after):
        owner=self.network()[0];first=self.block(owner);competing=json.loads(first['wire'])
        competing['body']['created_at_ns']+=1
        competing['signature']=owner._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(competing['body'])).hex()
        commit=owner._profile._commit
        def failed():
            if after:commit()
            raise OSError('owned branch commit outcome fixture')
        with patch.object(owner._profile,'_commit',side_effect=failed):
            with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):owner._engine.admit_relayed(pack(competing),0)
        self.assertEqual(owner._engine._lan_quarantine,{})
        self.assertEqual(owner._engine.lan_evidence()['blocks'],1)
        resumed=self.resume(owner)
        self.assertEqual(resumed._profile.snapshot()['records'],2 if after else 1)
        if after:
            with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.block(resumed)
        else:self.block(resumed)
        resumed._engine.produce_lan_test_block(resumed._local_indices[1],1)

    def test_branch_before_commit_failure_never_publishes_quarantine(self):self.assert_branch_write_outcome(False)

    def test_branch_lost_commit_return_recovers_both_signed_records_and_quarantine(self):self.assert_branch_write_outcome(True)

    def test_publication_failure_after_durable_branch_commit_requires_replay_before_more_work(self):
        owner=self.network()[0];first=self.block(owner);competing=json.loads(first['wire'])
        competing['body']['created_at_ns']+=1
        competing['signature']=owner._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(competing['body'])).hex()
        with patch.object(owner._engine,'_publish_branch',side_effect=RuntimeError('owned publication failure')):
            with self.assertRaisesRegex(RuntimeError,'publication failure'):owner._engine.admit_relayed(pack(competing),0)
        with self.assertRaisesRegex(ValueError,'PUBLICATION_FAILED'):owner._engine.admit_relayed(first['wire'],0)
        with self.assertRaisesRegex(ValueError,'PUBLICATION_FAILED'):self.block(owner)
        resumed=self.resume(owner)
        self.assertEqual(resumed._profile.snapshot()['records'],2)
        with self.assertRaisesRegex(ValueError,'QUARANTINED'):self.block(resumed)
        resumed._engine.produce_lan_test_block(resumed._local_indices[1],1)

    def test_legacy_test_receipts_restore_balances_and_nonce_without_reminting(self):
        nodes=self.network(tokens=True);coordinator=nodes[0];owner=nodes[1]
        receipts=coordinator._tokens.commit_batch(owner._tokens.sign_batch(nodes[2].public_key,'17',3))
        for peer in nodes[1:]:peer._tokens.apply_receipts(receipts)
        before=owner._tokens.snapshot();resumed=self.resume(owner)
        self.assertEqual(resumed._tokens.snapshot(),before)
        self.assertEqual(resumed._profile.snapshot()['counts'],{'dag':0,'token':3})
        resumed._tokens.apply_receipts(receipts)
        self.assertEqual(resumed._profile.snapshot()['records'],3)
        transaction=resumed._tokens.sign_batch(nodes[2].public_key,'1')[0]
        self.assertEqual(transaction['body']['nonce'],3)

    def test_old_signed_remote_work_plan_cannot_be_prepared_after_restart(self):
        import secrets,time
        coordinator,owner,_=self.network()
        body={'schema':'gg.lan-dag.stress.v1','network_id':coordinator._network,'run_id':secrets.token_hex(32),
            'duration_ms':60000,'transactions_per_block':1,'interval_ms':1000,'remote':True,
            'expires_at_ns':time.time_ns()+60000*1000000,'baseline':coordinator._engine.lan_evidence()}
        signed=lan._signed(coordinator._identity,lan._DAG_STRESS,body)
        owner._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
        # Identical preparation is idempotent only within that live owner.
        owner._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
        resumed=self.resume(owner)
        with self.assertRaisesRegex(ValueError,'REPLAY'):
            resumed._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})


if __name__=='__main__':unittest.main()
