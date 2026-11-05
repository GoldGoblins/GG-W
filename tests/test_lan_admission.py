import unittest
from backend.gg_lan_admission import RefillBudget


class RefillBudgetTests(unittest.TestCase):
    def test_bad_lane_cannot_exhaust_good_lane_or_grow_actor_table(self):
        now=[10.0];budget=RefillBudget(100,4,maximum_actors=2,clock=lambda:now[0])
        self.assertTrue(budget.take('bad',100));self.assertFalse(budget.take('bad',1))
        for _ in range(100):self.assertFalse(budget.take('bad',1))
        self.assertTrue(budget.take('good',100));self.assertFalse(budget.take('third',1))
        self.assertEqual(budget.snapshot()['actors'],2)
        now[0]+=.5;self.assertTrue(budget.take('bad',50));self.assertFalse(budget.take('bad',1))

    def test_reconfiguration_and_backward_clock_never_refill_spent_credit(self):
        now=[10.0];budget=RefillBudget(100,4,maximum_actors=2,clock=lambda:now[0])
        self.assertTrue(budget.take('peer',100,4));budget.set_limits(100,4)
        now[0]=9.0;self.assertFalse(budget.take('peer',1));now[0]=10.0;self.assertFalse(budget.take('peer',1))
        now[0]=11.0;self.assertTrue(budget.take('peer',100,4))

    def test_work_limit_is_independent_of_byte_limit(self):
        budget=RefillBudget(1000,2,maximum_actors=1,clock=lambda:1.0)
        self.assertTrue(budget.take('a',0));self.assertTrue(budget.take('a',0));self.assertFalse(budget.take('a',0))

    def test_expired_anonymous_slots_are_reusable_but_active_slots_stay_bounded(self):
        now=[0.0];budget=RefillBudget(10,1,maximum_actors=2,clock=lambda:now[0])
        self.assertTrue(budget.take('a'));self.assertTrue(budget.take('b'));self.assertFalse(budget.take('c'))
        now[0]=1.0;self.assertTrue(budget.take('c'));self.assertEqual(budget.snapshot()['actors'],2)

    def test_raising_a_limit_cannot_retroactively_refill_at_the_new_rate(self):
        now=[0.0];budget=RefillBudget(100,1,maximum_actors=1,clock=lambda:now[0])
        self.assertTrue(budget.take('a',100));now[0]=.5;budget.set_limits(1000,10)
        self.assertFalse(budget.take('a',51,0));self.assertEqual(budget.actors['a'][0],0)
