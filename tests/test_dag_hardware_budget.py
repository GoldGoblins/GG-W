"""Budget arithmetic is tested independently of benchmarks and live nodes."""
import math
import unittest

from backend.gg_dag_hardware import ResourceBudget, bottleneck_plan


class HardwareBudgetTests(unittest.TestCase):
    def test_every_individual_slider_can_limit_every_other_resource_in_both_directions(self):
        names = ('cpu', 'gpu', 'ram', 'network')
        capacities = dict(zip(names, (6000, 12000, 24000, 10000)))
        for limiting in names:
            previous = None
            # All four components become the sole bottleneck, at several
            # positions, then return to their original position.
            for target in (100, 250, 500, 250, 100):
                with self.subTest(limiting=limiting, target=target):
                    selected = target/capacities[limiting]*100
                    plan = bottleneck_plan(capacities, ResourceBudget(**{limiting: selected}),
                        active=names, transactions_per_block=5000)
                    self.assertAlmostEqual(plan['estimated_tps'], target)
                    self.assertEqual(plan['bottlenecks'], [limiting])
                    for other in names:
                        self.assertAlmostEqual(plan['resources'][other]['relative_percent'], target/capacities[other]*100)
                        self.assertAlmostEqual(plan['resources'][other]['relative_tps'], target)
                    if previous is not None and target != previous['estimated_tps']:
                        for other in names:
                            self.assertNotEqual(plan['resources'][other]['relative_percent'], previous['resources'][other]['relative_percent'])
                    previous = plan

    def test_bottleneck_handover_between_every_pair_and_ties(self):
        names = ('cpu', 'gpu', 'ram', 'network')
        capacities = dict.fromkeys(names, 10000)
        for first in names:
            for second in names:
                if first == second:continue
                with self.subTest(first=first, second=second):
                    for percent, expected in ((10, [second]), (20, [first, second]), (40, [first])):
                        plan = bottleneck_plan(capacities, ResourceBudget(**{first: 20, second: percent}), active=names)
                        self.assertEqual(set(plan['bottlenecks']), set(expected))
                        self.assertEqual(plan['estimated_tps'], min(20, percent)*100)
                        self.assertTrue(all(row['relative_percent'] <= row['selected_percent'] for row in plan['resources'].values()))

    def test_overall_slider_scales_all_resources_for_each_possible_bottleneck(self):
        names = ('cpu', 'gpu', 'ram', 'network')
        for limiting in names:
            for overall in (0, 1, 10, 50, 100):
                with self.subTest(limiting=limiting, overall=overall):
                    plan = bottleneck_plan(dict.fromkeys(names, 10000),
                        ResourceBudget(overall=overall, **{limiting: 10}), active=names)
                    self.assertEqual(plan['estimated_tps'], overall*10)
                    self.assertTrue(all(row['relative_percent'] == overall/10 for row in plan['resources'].values()))

    def test_each_zero_slider_pauses_all_active_resources(self):
        names = ('cpu', 'gpu', 'ram', 'network')
        for limiting in names:
            with self.subTest(limiting=limiting):
                plan = bottleneck_plan(dict.fromkeys(names, 1000), ResourceBudget(**{limiting: 0}), active=names)
                self.assertEqual(plan['state'], 'PAUSED')
                self.assertTrue(all(row['relative_percent'] == 0 for row in plan['resources'].values()))

    def test_network_ceiling_scales_other_resources_to_same_workload(self):
        p = bottleneck_plan({'cpu': 6000, 'gpu': 12000, 'ram': 24000, 'network': 10000},
                            ResourceBudget(network=10), active=('cpu', 'gpu', 'ram', 'network'),
                            transactions_per_block=5000)
        self.assertEqual(p['estimated_tps'], 1000)
        self.assertEqual(p['estimated_blocks_per_second'], .2)
        self.assertEqual(p['bottlenecks'], ['network'])
        self.assertAlmostEqual(p['resources']['cpu']['relative_percent'], 100/6)
        self.assertAlmostEqual(p['resources']['gpu']['relative_percent'], 100/12)
        self.assertAlmostEqual(p['resources']['ram']['relative_percent'], 100/24)

    def test_capacity_is_normalized_not_the_smallest_raw_percent(self):
        p = bottleneck_plan({'cpu': 100, 'network': 100000}, ResourceBudget(network=10), active=('cpu', 'network'))
        self.assertEqual(p['estimated_tps'], 100)
        self.assertEqual(p['bottlenecks'], ['cpu'])
        self.assertAlmostEqual(p['resources']['network']['relative_percent'], .1)

    def test_individual_ceiling_and_overall_fraction_are_both_enforced(self):
        p = bottleneck_plan({'cpu': 6000, 'network': 10000}, ResourceBudget(overall=50, cpu=10, network=10), active=('cpu', 'network'))
        self.assertEqual(p['estimated_tps'], 300)
        self.assertEqual(p['resources']['cpu']['relative_percent'], 5)
        self.assertEqual(p['resources']['network']['relative_percent'], 3)

    def test_unused_gpu_is_not_an_artificial_zero_capacity_bottleneck(self):
        p = bottleneck_plan({'cpu': 1000, 'gpu': 0}, active=('cpu',))
        self.assertEqual(p['estimated_tps'], 1000)
        self.assertFalse(p['resources']['gpu']['active'])
        self.assertIsNone(p['resources']['gpu']['relative_percent'])

    def test_unknown_active_capacity_requires_measurement(self):
        p = bottleneck_plan({'cpu': 1000}, active=('cpu', 'network'))
        self.assertEqual(p['state'], 'NEEDS_BENCHMARK')
        self.assertIsNone(p['estimated_tps'])
        self.assertEqual(p['unknown_resources'], ['network'])

    def test_memory_space_is_a_separate_block_fit_constraint(self):
        p = bottleneck_plan({'cpu': 1000, 'ram': 10000}, ResourceBudget(ram=25),
                            active=('cpu', 'ram'), memory_required_bytes=300,
                            memory_available_bytes=1000, transactions_per_block=5000)
        self.assertEqual(p['state'], 'MEMORY_LIMIT')
        self.assertEqual(p['estimated_tps'], 0)
        self.assertEqual(p['bottlenecks'], ['ram'])

    def test_zero_budget_pauses_work_and_invalid_values_are_rejected(self):
        self.assertEqual(bottleneck_plan({'cpu': 1000}, ResourceBudget(cpu=0), active=('cpu',))['state'], 'PAUSED')
        for value in (True, -1, 101, math.inf, math.nan, '50'):
            with self.subTest(value=value), self.assertRaises(ValueError):ResourceBudget(cpu=value)
        for value in (True, -1, math.inf, math.nan, 'fast'):
            with self.subTest(value=value), self.assertRaises(ValueError):bottleneck_plan({'cpu': value}, active=('cpu',))


if __name__ == '__main__':
    unittest.main()
