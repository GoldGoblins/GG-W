import unittest

from backend.gg_dag_hardware import ResourceBudget, WorkGovernor, ResourceController


class Clock:
    def __init__(self):self.now=0.;self.cpu=0.;self.cancelled=False
    def is_set(self):return self.cancelled
    def wait(self,delay):self.now+=delay;return self.cancelled
    def monotonic(self):return self.now
    def thread_time(self):return self.cpu


class ResourceGovernorTests(unittest.TestCase):
    def governor(self,budget=None,profile=None):
        clock=Clock()
        governor=WorkGovernor(budget,profile,info={'logical_cpus':1,'memory_total_bytes':1000000,
            'memory_available_bytes':800000,'network_link_bytes_per_second':10000},cancel=clock,
            monotonic=clock.monotonic,thread_clock=clock.thread_time)
        return governor,clock

    def test_cpu_excess_waits_and_zero_or_cancelled_budget_does_not_spin(self):
        g,c=self.governor(ResourceBudget(cpu=10));g.check_cpu();c.cpu=.1;g.check_cpu()
        self.assertGreaterEqual(c.now,.97)
        g,c=self.governor(ResourceBudget(cpu=0))
        with self.assertRaisesRegex(ValueError,'PAUSED'):g.check_cpu()
        g,c=self.governor();c.cancelled=True
        with self.assertRaisesRegex(ValueError,'CANCELLED'):g.check_cpu()

    def test_network_budget_is_aggregate_and_preserves_deadline(self):
        g,c=self.governor(ResourceBudget(network=10));g.wait_network(1000)
        self.assertAlmostEqual(c.now,1)
        g.wait_network(1000);self.assertAlmostEqual(c.now,2)
        with self.assertRaisesRegex(ValueError,'DEADLINE'):g.wait_network(1000,deadline=2.5)
        self.assertLessEqual(c.now,2.5)

    def test_bottleneck_reduces_compute_as_well_as_network(self):
        p={'capacities_tps':{'cpu':1000,'network':1000},'active_resources':['cpu','network'],
           'network_bytes_per_second':10000,'network_bytes_per_transaction':10}
        g,c=self.governor(ResourceBudget(network=10),p)
        self.assertEqual(g.plan['estimated_tps'],100)
        g.check_cpu();c.cpu=.1;g.check_cpu();self.assertGreaterEqual(c.now,.97)

    def test_every_active_resource_limits_real_cpu_accounting_and_network_budget(self):
        names=('cpu','gpu','ram','network')
        profile={'capacities_tps':dict.fromkeys(names,1000),'active_resources':names,
            'network_bytes_per_second':10000,'network_bytes_per_transaction':10}
        for limiting in names:
            for percent in (5,10,50):
                with self.subTest(limiting=limiting,percent=percent):
                    g,c=self.governor(ResourceBudget(**{limiting:percent}),profile)
                    self.assertEqual(g.plan['bottlenecks'],[limiting])
                    g.check_cpu();c.cpu=.1;g.check_cpu()
                    self.assertGreaterEqual(c.now,.1/(percent/100)-.026)
                    before=c.now;g.wait_network(1000)
                    self.assertAlmostEqual(c.now-before,1000/(percent*100))

    def test_live_node_settings_recalculate_shared_governor_for_each_slider(self):
        names=('cpu','gpu','ram','network')
        controller=ResourceController(info_provider=lambda:{'logical_cpus':1,
            'memory_total_bytes':1000000,'memory_available_bytes':800000})
        controller.test._status={'state':'COMPLETE','profile':{'measured_at':1,
            'capacities_tps':dict.fromkeys(names,10000),'active_resources':names,
            'network_bytes_per_second':100000,'network_bytes_per_transaction':10}}
        for limiting in names:
            controller.configure(dict.fromkeys(('overall',*names),100))
            previous=controller.governor()
            result=controller.configure({limiting:10})
            self.assertIsNot(controller.governor(),previous)
            self.assertEqual(result['plan']['estimated_tps'],1000)
            self.assertEqual(result['plan']['bottlenecks'],[limiting])
            self.assertEqual(controller.governor().plan,result['plan'])
            self.assertTrue(all(row['relative_percent']==10 for row in result['plan']['resources'].values()))

    def test_memory_reservations_are_shared_bounded_and_released(self):
        g,_=self.governor(ResourceBudget(ram=10))
        with g.reserve_memory(70000):
            with self.assertRaisesRegex(ValueError,'MEMORY'):
                with g.reserve_memory(40000):pass
            self.assertEqual(g.memory_headroom(),30000)
        self.assertEqual(g.memory_headroom(),100000)

    def test_changing_slider_does_not_erase_in_flight_memory_reservations(self):
        controller=ResourceController(info_provider=lambda:{'logical_cpus':1,
            'memory_total_bytes':1000000,'memory_available_bytes':800000})
        original=controller.governor()
        with original.reserve_memory(70000):
            controller.configure({'ram':10})
            replacement=controller.governor()
            self.assertEqual(replacement.memory_headroom(),30000)
            with self.assertRaisesRegex(ValueError,'MEMORY'):
                with replacement.reserve_memory(40000):pass
        self.assertEqual(replacement.memory_headroom(),100000)

    def test_ram_budget_compares_block_memory_fit_as_well_as_normalized_tps(self):
        controller=ResourceController(info_provider=lambda:{'logical_cpus':1,
            'memory_total_bytes':10000000,'memory_available_bytes':10000000})
        controller.test._status={'state':'COMPLETE','profile':{'measured_at':1,
            'active_resources':['cpu','ram','network'],'wire_bytes_per_transaction':100,
            'capacities_tps':{'cpu':1000,'ram':100000,'network':10000}}}
        self.assertEqual(controller.snapshot(1000)['plan']['estimated_tps'],1000)
        controller.configure({'ram':10})
        plan=controller.snapshot(1000)['plan']
        self.assertEqual(plan['state'],'MEMORY_LIMIT')
        self.assertEqual(plan['estimated_tps'],0)
        self.assertEqual(plan['bottlenecks'],['ram'])
        self.assertEqual(plan['resources']['cpu']['relative_percent'],0)
        controller.configure({'ram':50})
        self.assertEqual(controller.snapshot(1000)['plan']['estimated_tps'],1000)


if __name__=='__main__':unittest.main()
