"""Real signed ledger proofs with deterministic delayed control responses."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch
from backend import gg_lan_dag as lan
from tests import test_lan_dag_stress_protocol as fixture


class ConvergenceBudgetTests(unittest.TestCase):
    setUp=fixture.DagStressProtocolTests.setUp
    cleanup=fixture.DagStressProtocolTests.cleanup
    plan=fixture.DagStressProtocolTests.plan

    def coordinate(self,*,duration_ms=1000,status_delay=.15):
        coordinator=self.peers[0];body=self.plan()['body']
        wall=time.time_ns()
        body.update(duration_ms=duration_ms,expires_at_ns=wall+duration_ms*1000000)
        signed=lan._signed(coordinator._identity,lan._DAG_STRESS,body)
        clock=[100.0];stops={};polls=[]
        lookup={p.public_key:p for p in self.peers}
        originals={p.public_key:p._dag_stress_command for p in self.peers}
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
                stops[target]=stops.get(target,0)+1
                clock[0]+=.4 if duration_ms==1000 else .84
            elif kind=='DAG_STRESS_STATUS':
                polls.append(target);clock[0]+=status_delay
            elif duration_ms>1000:clock[0]+=.4
            if deadline is not None and clock[0]>=deadline:
                raise ValueError('GG_LAN_CIRCLE_DEADLINE')
            result=lookup[target]._dag_stress_command(coordinator.public_key,kind,payload)
            if kind=='DAG_STRESS_STOP' and stops[target]==1:
                result=deepcopy(result);result['evidence']['blockset_digest']='0'*64
            return result
        def advance(delay):clock[0]+=max(0,delay);return False
        coordinator._token_rpc=rpc
        with (patch.object(lan.time,'monotonic',side_effect=lambda:clock[0]),
              patch.object(lan.time,'time_ns',return_value=wall)):
            coordinator._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
            plan=coordinator._dag_plan
            if duration_ms==1000:plan['production_deadline']=100.0
            with (patch.object(coordinator._cancel,'wait',side_effect=advance),
                  patch.object(coordinator._dag_cancel,'wait',side_effect=advance)):
                coordinator._dag_coordinate(plan,coordinator._dag_cancel)
            result=coordinator._dag_stress_snapshot()
        return result,polls

    def test_matching_status_before_deadline_is_checked_before_poll_pause(self):
        # Two .4s STOPs and two .075s STATUS replies leave only .05s.
        # Spending that remainder on a poll pause must not discard valid proof.
        result,polls=self.coordinate(status_delay=.075)
        self.assertEqual(len(polls),2)
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertTrue(result['all_peers_synced'])
        self.assertEqual(result['acknowledged_transactions'],2)
        self.assertEqual(result['acknowledgement_basis'],'STOP_AND_STATUS_OBSERVATIONS')

    def test_slow_stop_and_status_fit_within_original_ten_second_budget(self):
        # 1.6s setup, 1.68s STOP and 1s evidence reads: the old fixed 2s
        # drain cannot finish even though the blocks are already identical.
        result,polls=self.coordinate(duration_ms=10000,status_delay=.5)
        self.assertEqual(len(polls),2)
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertTrue(result['all_peers_synced'])
        self.assertEqual(result['acknowledged_transactions'],2)
        self.assertLess(result['elapsed_ms'],11001)

    def test_status_after_original_deadline_cannot_establish_ack(self):
        result,_=self.coordinate(status_delay=.3)
        self.assertEqual(result['state'],'TIME_BUDGET',result)
        self.assertFalse(result['all_peers_synced'])
        self.assertIsNone(result['acknowledged_transactions'])
        self.assertEqual(result['failure_phase'],'CONVERGENCE')


if __name__=='__main__':unittest.main()
