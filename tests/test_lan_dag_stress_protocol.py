"""Finite in-memory control/fault tests, not physical-network benchmarks."""
import json
import time
import unittest
from copy import deepcopy
from unittest.mock import patch
from backend import gg_lan_dag as lan
from backend.gg_parallel_dag import ParallelDag,make_public_genesis,pack,_tree


class DagStressProtocolTests(unittest.TestCase):
    def setUp(self):
        self.peers=[lan.LanDagPeer(label,allow_dag_transactions=True) for label in ('Windows','Linux','Termux')]
        coordinator=self.peers[0]
        public=[key.pubkey().hex() for peer in self.peers for key in peer._local_keys]
        bundle=make_public_genesis(public,enable_dag_transactions=True)
        roster={peer.public_key:{'label':peer.label,'allow_dag_transactions':True,'credit_index':index,
            'producer_indices':[2*index,2*index+1]} for index,peer in enumerate(self.peers)}
        for index,peer in enumerate(self.peers):
            peer._trusted=coordinator.public_key;peer._network='f'*64;peer._roster=roster;peer._dag_enabled=True
            peer._engine=ParallelDag.from_public_genesis(bundle);peer._local_indices=[2*index,2*index+1]
            peer._engine.attach_local_producers(dict(zip(peer._local_indices,peer._local_keys)))
        lookup={peer.public_key:peer for peer in self.peers}
        for source in self.peers:
            def rpc(target,kind,payload,*,cancel=None,deadline=None,source=source):
                if deadline is not None and time.monotonic()>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
                if cancel is not None and cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
                return lookup[target]._dag_stress_command(source.public_key,kind,payload)
            source._token_rpc=rpc
            original=source._engine.produce_lan_test_block
            def produce(*args,source=source,original=original,**kwargs):
                result=original(*args,**kwargs)
                for target in self.peers:
                    if target is not source:target._ingest(result['wire'],source.public_key)
                return result
            source._engine.produce_lan_test_block=produce
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for peer in self.peers:peer._dag_cancel.set()
        for peer in self.peers:
            for worker in (peer._dag_worker,peer._dag_controller):
                if worker:worker.join(2)

    def plan(self):
        peer=self.peers[0]
        body={'schema':'gg.lan-dag.stress.v1','network_id':peer._network,'run_id':'a'*64,'duration_ms':1000,
            'transactions_per_block':2,'interval_ms':100,'remote':True,'expires_at_ns':time.time_ns()+10**9,
            'baseline':peer._engine.lan_evidence()}
        return lan._signed(peer._identity,lan._DAG_STRESS,body)

    def finish(self):
        coordinator=self.peers[0];coordinator._dag_controller.join(3)
        self.assertFalse(coordinator._dag_controller.is_alive())
        return coordinator._dag_stress_snapshot()

    def test_signed_three_peer_run_contains_actual_dag_tx_and_ack_proofs(self):
        self.peers[0].start_dag_stress(1000,2,100)
        result=self.finish()
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertTrue(result['all_peers_synced'],result)
        self.assertEqual(result['acknowledged_transactions'],result['transactions'])
        self.assertGreater(result['transactions'],0)
        self.assertEqual(len({row['blockset_digest'] for row in result['participants']}),1)
        self.assertEqual(len({row['state_root'] for row in result['participants']}),1)
        self.assertTrue(all(not peer._dag_worker.is_alive() for peer in self.peers))

    def test_prepare_begin_idempotence_closed_replay_and_wrong_authority(self):
        coordinator,peer,_=self.peers;plan=self.plan();run_id=plan['body']['run_id']
        with self.assertRaisesRegex(ValueError,'COORDINATOR_REQUIRED'):
            peer._dag_stress_command(peer.public_key,'DAG_STRESS_PREPARE',{'plan':plan})
        for _ in range(2):peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':plan})
        peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id});worker=peer._dag_worker
        peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id})
        self.assertIs(peer._dag_worker,worker)
        peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_STOP',{'run_id':run_id})
        with self.assertRaisesRegex(ValueError,'REPLAY'):peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':plan})
        with self.assertRaisesRegex(ValueError,'REPLAY'):peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id})

    def test_lost_begin_ack_rolls_back_every_attempted_run(self):
        coordinator=self.peers[0];original=coordinator._token_rpc;failed=[False]
        def lost(target,kind,payload,**kwargs):
            result=original(target,kind,payload,**kwargs)
            if kind=='DAG_STRESS_BEGIN' and not failed[0]:failed[0]=True;raise TimeoutError()
            return result
        coordinator._token_rpc=lost
        coordinator.start_dag_stress(1000,1,100)
        result=self.finish()
        self.assertEqual(result['state'],'ERROR',result)
        self.assertFalse(result['all_peers_synced']);self.assertIsNone(result['acknowledged_tps'])
        for peer in self.peers:
            self.assertTrue(peer._dag_worker is None or not peer._dag_worker.is_alive())
            self.assertIn(coordinator._dag_plan['body']['run_id'],peer._dag_closed)

    def test_fault_on_remote_peer_prevents_ack_even_when_blocks_match(self):
        coordinator=self.peers[0];original=coordinator._token_rpc
        def fault(target,kind,payload,**kwargs):
            result=original(target,kind,payload,**kwargs)
            if kind in ('DAG_STRESS_STOP','DAG_STRESS_STATUS'):result['evidence']['protocol_fault']='GG_DAG_PRODUCER_EQUIVOCATION'
            return result
        coordinator._token_rpc=fault;coordinator.start_dag_stress(1000,1,100)
        result=self.finish()
        self.assertEqual(result['state'],'ERROR',result);self.assertFalse(result['all_peers_synced'])
        self.assertIsNone(result['acknowledged_transactions']);self.assertIn('EQUIVOCATION',result['last_error'])
        self.assertFalse(lan.LanDagPeer._dag_same_evidence({},{}))

    def coordinate_near_deadline(self,*,mismatch=False,status_late=True,late_block=None):
        """Real signed ledger evidence with a deterministic slow-control clock.

        STOP consumes most of the budget. Any unnecessary STATUS request would
        cross the original deadline. Worker creation is excluded from this
        control-phase test; independent real-worker tests above cover that path.
        """
        coordinator=self.peers[0];signed=self.plan()
        coordinator._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
        plan=coordinator._dag_plan;clock=[100.0];polls=[];stop_counts={};injected=[False]
        lookup={peer.public_key:peer for peer in self.peers};originals={peer.public_key:peer._dag_stress_command for peer in self.peers}
        for peer in self.peers:
            def command(source,kind,payload,peer=peer):
                if kind=='DAG_STRESS_BEGIN':
                    peer._dag_plan['begun']=True;peer._dag_stress['state']='RUNNING'
                    if peer is coordinator:peer._engine.produce_lan_test_block(0,2)
                    return peer._dag_status()
                return originals[peer.public_key](source,kind,payload)
            peer._dag_stress_command=command
        def rpc(target,kind,payload,*,cancel=None,deadline=None):
            if kind=='DAG_STRESS_STOP':
                stop_counts[target]=stop_counts.get(target,0)+1;clock[0]+=.4
                if late_block is not None and sum(stop_counts.values())==3 and not injected[0]:
                    coordinator._ingest(late_block,self.peers[1].public_key);injected[0]=True
            elif kind=='DAG_STRESS_STATUS':
                polls.append(target);clock[0]+=.3 if status_late else .01
            else:clock[0]+=.01
            if deadline is not None and clock[0]>=deadline:
                error=ValueError('GG_LAN_CIRCLE_DEADLINE')
                error._gg_lan_details={'operation':kind,'stage':'RECEIVE'}
                raise error
            result=lookup[target]._dag_stress_command(coordinator.public_key,kind,payload)
            if mismatch and target==self.peers[1].public_key and kind=='DAG_STRESS_STOP' and stop_counts[target]==1:
                result=deepcopy(result);result['evidence']['blockset_digest']='0'*64
            return result
        coordinator._token_rpc=rpc
        with patch.object(lan.time,'monotonic',side_effect=lambda:clock[0]):
            plan.update(started=100.0,deadline=101.0,production_deadline=100.0)
            coordinator._dag_coordinate(plan,coordinator._dag_cancel)
            result=coordinator._dag_stress_snapshot()
        return result,polls

    def test_matching_stop_observations_complete_without_status_near_deadline(self):
        result,polls=self.coordinate_near_deadline()
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertTrue(result['all_peers_synced']);self.assertEqual(result['acknowledged_transactions'],2)
        self.assertEqual(polls,[]);self.assertEqual(result['status_polls'],0)
        self.assertEqual(result['acknowledgement_basis'],'STOP_OBSERVATIONS')
        self.assertEqual(next(row['state'] for row in result['participants'] if row['local']),result['state'])
        self.assertGreater(result['phase_ms']['STOP'],0)

    def test_mismatched_stop_observation_cannot_ack_after_status_exceeds_deadline(self):
        result,polls=self.coordinate_near_deadline(mismatch=True)
        self.assertEqual(result['state'],'TIME_BUDGET',result);self.assertFalse(result['all_peers_synced'])
        self.assertIsNone(result['acknowledged_transactions']);self.assertIsNone(result['acknowledged_tps'])
        self.assertEqual(polls,[self.peers[1].public_key]);self.assertEqual(result['failure_phase'],'CONVERGENCE')
        self.assertEqual(result['last_error_details'],{'operation':'DAG_STRESS_STATUS','stage':'RECEIVE','error_class':'ValueError'})

    def test_only_mismatched_peer_is_polled_and_fresh_matching_observation_can_ack(self):
        result,polls=self.coordinate_near_deadline(mismatch=True,status_late=False)
        self.assertEqual(result['state'],'COMPLETE',result);self.assertTrue(result['all_peers_synced'])
        self.assertEqual(polls,[self.peers[1].public_key]);self.assertEqual(result['status_polls'],1)
        self.assertEqual(result['acknowledgement_basis'],'STOP_AND_STATUS_OBSERVATIONS')

    def test_late_valid_block_invalidates_pre_cleanup_matching_observations(self):
        source=self.peers[1]
        isolated=ParallelDag.from_public_genesis(source._engine.export_public_genesis())
        isolated.attach_local_producers({2:source._local_keys[0]})
        late=isolated.produce_lan_test_block(2,1)['wire']
        result,polls=self.coordinate_near_deadline(late_block=late)
        self.assertEqual(polls,[]);self.assertEqual(result['state'],'TIME_BUDGET',result)
        self.assertEqual(result['last_error'],'GG_LAN_DAG_FINAL_EVIDENCE_CHANGED')
        self.assertFalse(result['all_peers_synced']);self.assertIsNone(result['acknowledged_tps'])

    def test_limits_optin_unrelated_production_and_capability_query(self):
        coordinator=self.peers[0]
        with self.assertRaises(ValueError):coordinator.start_dag_stress(999,1,100)
        with self.assertRaises(ValueError):coordinator.start_dag_stress(1000,65,100)
        with self.assertRaises(ValueError):coordinator.start_dag_stress(1000,1,99)
        coordinator._engine._live['enabled']=True
        with self.assertRaisesRegex(ValueError,'UNRELATED'):coordinator.start_dag_stress(1000,1,100)
        self.assertTrue(coordinator._engine._live['enabled'])
        coordinator._engine._live['enabled']=False
        with self.assertRaisesRegex(ValueError,'USE_FINITE_STRESS'):coordinator.start_producing()
        coordinator.stop_producing()
        with patch.object(lan,'Keypair',side_effect=AssertionError('key created')),patch.object(lan.socket,'socket',side_effect=AssertionError('socket created')):
            self.assertEqual(lan.dag_stress_capabilities()['limits']['max_tx_per_block'],64)

    def test_stop_during_run_and_repeated_stop_clear_signers_without_new_proof(self):
        coordinator=self.peers[0];coordinator.start_dag_stress(1000,1,100)
        result=coordinator.stop()
        self.assertEqual(result['lan']['state'],'STOPPED')
        self.assertFalse(result['dag_stress']['enabled'])
        self.assertFalse(result['dag_stress']['worker_active'])
        self.assertFalse(result['dag_stress']['can_start'])
        self.assertIsNone(coordinator._identity);self.assertEqual(coordinator._local_keys,[])
        self.assertEqual(coordinator._engine._producer_keys,[])
        self.assertEqual(coordinator.stop()['lan']['state'],'STOPPED')

    def test_software_credit_failure_is_reported_as_limit(self):
        coordinator=self.peers[0]
        def limit(*args,**kwargs):raise ValueError('GG_DAG_PEER_CREDIT')
        coordinator._engine.produce_lan_test_block=limit
        coordinator.start_dag_stress(1000,1,100)
        result=self.finish()
        self.assertEqual(result['state'],'LIMIT_REACHED',result)
        self.assertEqual(result['stop_reason'],'SOFTWARE_PROFILE_LIMIT')
        self.assertFalse(result['all_peers_synced']);self.assertIsNone(result['acknowledged_tps'])

    def test_malformed_signed_orphan_does_not_poison_valid_parent(self):
        source,receiver,_=self.peers
        first=ParallelDag.produce_lan_test_block(source._engine,0,1)
        child=ParallelDag.produce_lan_test_block(source._engine,0,1)
        value=json.loads(child['wire']);tx=value['body']['transactions'][0]
        tx['body']['to']=[]
        tx['signature']=source._local_keys[0].sign_message(b'GG-DAG-LAN-TEST-TX-SIGN-v2\0'+pack(tx['body'])).hex()
        value['body']['payload_root']=_tree(value['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        value['signature']=source._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        self.assertEqual(receiver._ingest(pack(value),source.public_key),'PENDING_PARENTS')
        self.assertEqual(receiver._ingest(first['wire'],source.public_key),'ADMITTED_UNFINALIZED')
        evidence=receiver._engine.lan_evidence()
        self.assertEqual(evidence['blocks'],1);self.assertEqual(evidence['transactions'],1)
        self.assertEqual(receiver._engine._lan_counts[0],1);self.assertEqual(evidence['protocol_fault'],'')
        self.assertEqual(len(receiver._orphans),0);self.assertEqual(receiver._last_error,'GG_DAG_TX_ACCOUNT')


    def _duplicate_fixture(self):
        source,receiver,_=self.peers
        first=ParallelDag.produce_lan_test_block(source._engine,0,16,lan.MAX_WIRE)
        second=ParallelDag.produce_lan_test_block(source._engine,0,32,lan.MAX_WIRE)
        return source,receiver,first,second

    def _duplicate_state(self,peer):
        engine=peer._engine
        return deepcopy({'evidence':engine.lan_evidence(),'stats':engine._stats,
            'peer_bytes':engine._peer_bytes,'stored_bytes':engine._stored_bytes,
            'traffic':peer._traffic,'raw_received':peer._raw_received,'total_bytes':peer._total_bytes,
            'rejected':peer._rejected,'orphans':peer._orphans,'orphan_bytes':peer._orphan_bytes,'sync_gap':peer._sync_gap})

    def test_exact_admitted_16_32tx_duplicates_skip_inspection_without_accounting_changes(self):
        source,receiver,first,second=self._duplicate_fixture()
        for item in (first,second):
            self.assertEqual(len(json.loads(item['wire'])['body']['transactions']),item['transactions'])
            self.assertEqual(receiver._ingest(item['wire'],source.public_key,item['hash']),'ADMITTED_UNFINALIZED')
        before=self._duplicate_state(receiver)
        with (patch.object(receiver._engine,'inspect_empty_proposal',side_effect=AssertionError('duplicate inspected')),
              patch.object(receiver._engine,'admit_relayed',side_effect=AssertionError('duplicate admitted')),
              patch.object(receiver._engine,'reconcile',side_effect=AssertionError('duplicate reconciled')),
              patch.object(receiver,'_drain_orphans',side_effect=AssertionError('duplicate drained orphans'))):
            for item in (first,second):
                self.assertEqual(receiver._ingest(item['wire'],source.public_key,item['hash']),'DUPLICATE')
        self.assertEqual(before,self._duplicate_state(receiver))
        self.assertEqual(before['evidence'],source._engine.lan_evidence())
        self.assertEqual((before['evidence']['blocks'],before['evidence']['transactions']),(2,48))

    def test_first_arrival_with_valid_unknown_claim_keeps_full_validation_and_credit(self):
        source,receiver,first,_=self._duplicate_fixture()
        with (patch.object(receiver._engine,'inspect_empty_proposal',wraps=receiver._engine.inspect_empty_proposal) as inspect,
              patch.object(receiver._engine,'admit_relayed',wraps=receiver._engine.admit_relayed) as admit,
              patch.object(receiver._engine,'reconcile',wraps=receiver._engine.reconcile) as reconcile,
              patch.object(receiver,'_drain_orphans',wraps=receiver._drain_orphans) as drain):
            self.assertEqual(receiver._ingest(first['wire'],source.public_key,first['hash']),'ADMITTED_UNFINALIZED')
            self.assertEqual([call.call_count for call in (inspect,admit,reconcile,drain)],[1,1,1,1])
        stats=receiver._engine._stats
        self.assertEqual((stats['attempts'],stats['signature_checks'],stats['transactions_validated']),(1,17,16))
        self.assertEqual(stats['charged_bytes'],len(first['wire']))

    def test_duplicate_absent_unknown_invalid_and_false_claims_keep_existing_validation(self):
        source,receiver,first,second=self._duplicate_fixture()
        receiver._ingest(first['wire'],source.public_key,first['hash'])
        cases=[(first['wire'],None),(first['wire'],'0'*64),(first['wire'],''),
            (first['wire'],'A'*64),(first['wire'],[]),(first['wire'],{}),
            (first['wire'],False),(first['wire'],b'0'*64),(second['wire'],first['hash'])]
        for raw,claim in cases:
            with self.subTest(claim_type=type(claim).__name__,missing=claim is None):
                before=self._duplicate_state(receiver)
                with patch.object(receiver._engine,'inspect_empty_proposal',wraps=receiver._engine.inspect_empty_proposal) as inspect:
                    if claim is None:self.assertEqual(receiver._ingest(raw,source.public_key,claim),'DUPLICATE')
                    else:
                        with self.assertRaisesRegex(ValueError,'^GG_LAN_PROPOSAL_HASH$'):
                            receiver._ingest(raw,source.public_key,claim)
                    self.assertEqual(inspect.call_count,1)
                self.assertEqual(before,self._duplicate_state(receiver))

    def test_mutated_duplicate_bytes_and_proposal_signature_still_fail_validation(self):
        source,receiver,first,_=self._duplicate_fixture()
        receiver._ingest(first['wire'],source.public_key,first['hash'])
        altered=json.loads(first['wire']);altered['body']['created_at_ns']+=1
        bad_signature=json.loads(first['wire']);bad_signature['signature']='0'*128
        cases=[(pack(altered),'GG_DAG_SIGNATURE'),(pack(bad_signature),'GG_DAG_SIGNATURE'),
            (first['wire']+b'\n','GG_DAG_WIRE_CANONICAL')]
        altered['signature']=source._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(altered['body'])).hex()
        cases.append((pack(altered),'GG_LAN_PROPOSAL_HASH'))
        for raw,code in cases:
            with self.subTest(code=code):
                before=self._duplicate_state(receiver)
                with patch.object(receiver._engine,'inspect_empty_proposal',wraps=receiver._engine.inspect_empty_proposal) as inspect:
                    with self.assertRaisesRegex(ValueError,'^'+code+'$'):
                        receiver._ingest(raw,source.public_key,first['hash'])
                    self.assertEqual(inspect.call_count,1)
                self.assertEqual(before,self._duplicate_state(receiver))

    def test_bad_transaction_signature_with_valid_new_claim_reaches_full_admission(self):
        source,receiver,first,_=self._duplicate_fixture()
        value=json.loads(first['wire']);value['body']['transactions'][0]['signature']='0'*128
        value['body']['payload_root']=_tree(value['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        value['signature']=source._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        claimed=lan.digest(value['body'],b'GG-DAG-BLOCK-v1\0');before=receiver._engine.lan_evidence()
        with (patch.object(receiver._engine,'inspect_empty_proposal',wraps=receiver._engine.inspect_empty_proposal) as inspect,
              patch.object(receiver._engine,'admit_relayed',wraps=receiver._engine.admit_relayed) as admit):
            with self.assertRaisesRegex(ValueError,'^GG_DAG_SIGNATURE$'):
                receiver._ingest(pack(value),source.public_key,claimed)
            self.assertEqual((inspect.call_count,admit.call_count),(1,1))
        self.assertEqual(before,receiver._engine.lan_evidence())
        stats=receiver._engine._stats
        self.assertEqual((stats['attempts'],stats['accepted'],stats['rejected'],stats['signature_checks']),(1,0,1,2))
        self.assertEqual(stats['charged_bytes'],len(pack(value)))

    def test_duplicate_peer_and_wire_guards_precede_lookup(self):
        source,receiver,first,_=self._duplicate_fixture()
        receiver._ingest(first['wire'],source.public_key,first['hash'])
        cases=[(first['wire'],'0'*64,'GG_LAN_UNKNOWN_PEER'),
            (first['wire'],receiver.public_key,'GG_LAN_UNKNOWN_PEER'),
            (b'',source.public_key,'GG_LAN_WIRE_SIZE'),
            (bytearray(first['wire']),source.public_key,'GG_LAN_WIRE_SIZE'),
            (b'x'*(lan.MAX_WIRE+1),source.public_key,'GG_LAN_WIRE_SIZE')]
        before=self._duplicate_state(receiver)
        with (patch.object(receiver._engine,'public_proposal',side_effect=AssertionError('guard bypassed')),
              patch.object(receiver._engine,'inspect_empty_proposal',side_effect=AssertionError('guard bypassed'))):
            for raw,peer,code in cases:
                with self.subTest(code=code):
                    with self.assertRaisesRegex(ValueError,'^'+code+'$'):
                        receiver._ingest(raw,peer,first['hash'])
        self.assertEqual(before,self._duplicate_state(receiver))

    def test_unadmitted_orphan_duplicates_still_inspect_then_drain_after_parent(self):
        source,receiver,first,second=self._duplicate_fixture()
        self.assertEqual(receiver._ingest(second['wire'],source.public_key,second['hash']),'PENDING_PARENTS')
        before=self._duplicate_state(receiver)
        with (patch.object(receiver._engine,'inspect_empty_proposal',wraps=receiver._engine.inspect_empty_proposal) as inspect,
              patch.object(receiver._engine,'admit_relayed',side_effect=AssertionError('orphan admitted')),
              patch.object(receiver._engine,'reconcile',side_effect=AssertionError('orphan reconciled'))):
            self.assertEqual(receiver._ingest(second['wire'],source.public_key,second['hash']),'PENDING_PARENTS')
            self.assertEqual(inspect.call_count,1)
        self.assertEqual(before,self._duplicate_state(receiver))
        self.assertEqual((len(receiver._orphans),receiver._orphan_bytes),(1,len(second['wire'])))
        self.assertEqual(receiver._ingest(first['wire'],source.public_key,first['hash']),'ADMITTED_UNFINALIZED')
        self.assertEqual((len(receiver._orphans),receiver._orphan_bytes),(0,0))
        self.assertEqual(receiver._engine.lan_evidence(),source._engine.lan_evidence())
        self.assertEqual(receiver._engine._stats['transactions_validated'],48)


if __name__=='__main__':unittest.main()
