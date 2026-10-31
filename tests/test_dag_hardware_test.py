"""Bounded real disposable calibration and owned node configuration."""
import threading
import time
import unittest

from backend.gg_dag_hardware import HardwareTest
from backend.gg_lan_dag import LanDagPeer
from backend.lan_dag_runtime import LanDagRuntime
from backend.terminal_cli import parse_command


def info():
    return {'logical_cpus':2,'memory_total_bytes':2**30,'memory_available_bytes':2**29,
        'network_link_bytes_per_second':1000000,
        'network_basis':'OS_REPORTED_LINK_SPEED_NOT_MEASURED_THROUGHPUT',
        'gpu_compute_supported':False}


class HardwareTestContractTests(unittest.TestCase):
    def test_real_signing_and_validation_produce_measured_profile_without_shared_ack(self):
        test=HardwareTest(info_provider=info)
        self.assertEqual(test.snapshot()['state'],'UNMEASURED')
        self.assertEqual(test.start(duration_ms=1000,max_transactions_per_block=8)['state'],'RUNNING')
        self.assertTrue(test.join(3))
        result=test.snapshot();profile=result['profile']
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertEqual(profile['largest_measured_transactions_per_block'],8)
        self.assertGreater(profile['capacities_tps']['cpu'],0)
        self.assertGreater(profile['capacities_tps']['ram'],0)
        self.assertIsNone(profile['capacities_tps']['gpu'])
        self.assertFalse(profile['physical_shared_ack'])
        self.assertEqual(profile['canonical_finalized'],0)
        self.assertEqual(profile['network_basis'],'OS_REPORTED_LINK_SPEED_NOT_MEASURED_THROUGHPUT')
        self.assertNotIn('wire',result['samples'][0])

    def test_measured_owned_link_and_failed_link_are_not_replaced_with_os_guess(self):
        for failure in (False,True):
            calls=[]
            def link(deadline,cancel):
                calls.append((deadline,cancel))
                if failure:raise OSError('arbitrary private failure detail')
                return {'bytes_per_second':123456}
            test=HardwareTest(info_provider=info)
            test.start(duration_ms=1000,max_transactions_per_block=8,network_probe=link)
            self.assertTrue(test.join(3))
            result=test.snapshot();profile=result['profile']
            self.assertEqual(len(calls),1)
            if failure:
                self.assertEqual(result['state'],'PARTIAL')
                self.assertIsNone(profile['capacities_tps']['network'])
                self.assertEqual(profile['network_basis'],'MEASUREMENT_FAILED')
                self.assertEqual(profile['network_error'],'GG_DAG_HARDWARE_LINK_FAILED')
            else:
                self.assertEqual(result['state'],'COMPLETE')
                self.assertEqual(profile['network_bytes_per_second'],123456)
                self.assertEqual(profile['network_basis'],'MEASURED_AUTHENTICATED_LAN_PROBE')

    def test_cancellation_joins_owned_work_and_is_not_a_protocol_failure(self):
        test=HardwareTest(info_provider=info)
        test.start(duration_ms=60000,max_transactions_per_block=50000)
        self.addCleanup(lambda:(test.stop(),test.join(2)))
        deadline=time.monotonic()+2
        while not test.snapshot()['samples'] and time.monotonic()<deadline:time.sleep(.005)
        test.stop()
        self.assertTrue(test.join(2))
        self.assertEqual(test.snapshot()['state'],'STOPPED')
        self.assertEqual(test.snapshot()['last_error'],'')

    def test_owned_runtime_updates_all_node_budgets_and_validates_before_mutation(self):
        manager=LanDagRuntime();peer=LanDagPeer('Resource fixture')
        manager._peer=peer
        self.addCleanup(manager.stop)
        for resource in ('overall','cpu','gpu','ram','network'):
            body=manager.dispatch('lan.resources',{'budget':{resource:25}})
            self.assertEqual(body['dag_resources']['budget'][resource],25)
            self.assertEqual(peer.resources.budget.public()[resource],25)
        before=peer.resources.budget.public()
        for bad in ({'cpu':101},{'other':50},{'ram':True},'50'):
            with self.assertRaises(ValueError):manager.dispatch('lan.resources',{'budget':bad})
            self.assertEqual(peer.resources.budget.public(),before)
        name,args=parse_command('lan.hardware_test_start max_transactions_per_block=50000 duration_ms=1000')
        self.assertEqual(args,{'max_transactions_per_block':50000,'duration_ms':1000})
        self.assertEqual(name,'lan.hardware_test_start')
        _,args=parse_command('lan.resources {"budget":{"cpu":10,"network":25}}')
        self.assertEqual(args['budget'],{'cpu':10,'network':25})


if __name__=='__main__':unittest.main()
