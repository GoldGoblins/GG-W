"""Finite worker policy only; no synthetic SDK selection evidence."""
import threading
import time
import unittest
from backend.gg_financial_retry import OwnedFinancialRetry


class FinancialRetryPolicyTests(unittest.TestCase):
    def run_job(self,step,**kwargs):
        worker=OwnedFinancialRetry(step,delay=.001,**kwargs);self.addCleanup(worker.close)
        worker.start(2);worker.worker.join(2)
        self.assertFalse(worker.worker.is_alive());return worker

    def test_queue_ack_never_means_selection_and_exhausts_finitely(self):
        calls=[]
        job=self.run_job(lambda *args:calls.append(args[0]) or {'state':'QUEUED'},attempts=3)
        self.assertEqual(calls,[2,2,2]);view=job.snapshot()
        self.assertEqual(view['state'],'EXHAUSTED');self.assertFalse(view['SDK_selected']);self.assertFalse(view['payments_executed_asserted'])

    def test_selection_only_from_callback_and_no_execution_claim(self):
        states=iter(['BUSY','UNAVAILABLE','SELECTED'])
        job=self.run_job(lambda *args:{'state':next(states),'pending_blocks':0},attempts=4)
        self.assertEqual(job.snapshot()['state'],'SELECTED');self.assertEqual(job.snapshot()['attempts'],3)
        self.assertFalse(job.snapshot()['payments_executed_asserted'])

    def test_no_prior_work_stays_idle_without_selection_claim(self):
        job=self.run_job(lambda *args:{'state':'IDLE'})
        self.assertEqual(job.snapshot()['state'],'IDLE');self.assertFalse(job.snapshot()['SDK_selected'])

    def test_transient_io_or_stale_context_retries_but_fault_stops(self):
        failures=iter([OSError('local IO seam'),ValueError('GG_FINANCIAL_PRODUCER_STALE_CONTEXT'),None])
        def step(*args):
            error=next(failures)
            if error:raise error
            return {'state':'SELECTED'}
        self.assertEqual(self.run_job(step).snapshot()['attempts'],3)
        def broken(*args):raise ValueError('GG_FINANCIAL_JOURNAL_INVALID')
        job=self.run_job(broken);self.assertEqual(job.snapshot()['state'],'FAULT');self.assertEqual(job.snapshot()['attempts'],1)

    def test_stop_interrupts_owned_wait_and_later_start_has_separate_cancel(self):
        entered=threading.Event();events=[]
        def step(index,check,cancel,deadline):
            events.append(cancel);entered.set()
            while not cancel.wait(.005):check()
            check()
        job=OwnedFinancialRetry(step,seconds=1,delay=.001);self.addCleanup(job.close)
        job.start(2);self.assertTrue(entered.wait(1))
        with self.assertRaisesRegex(ValueError,'BUSY'):job.start(2)
        job.close();self.assertEqual(job.snapshot()['state'],'STOPPED');self.assertTrue(events[0].is_set())
        entered.clear();job.start(2);self.assertTrue(entered.wait(1));self.assertIsNot(events[0],events[1]);self.assertTrue(events[0].is_set())
        job.close()

    def test_deadline_interrupts_callback_before_attempt_limit(self):
        def step(index,check,*args):
            while True:time.sleep(.001);check()
        job=self.run_job(step,seconds=.02)
        self.assertEqual(job.snapshot()['state'],'EXHAUSTED');self.assertEqual(job.snapshot()['attempts'],1)

    def test_unexpected_result_and_exception_fail_closed(self):
        self.assertEqual(self.run_job(lambda *args:{'state':'APPLIED'}).snapshot()['state'],'FAULT')
        def broken(*args):raise RuntimeError('private local exception detail')
        self.assertEqual(self.run_job(broken).snapshot()['last_error'],'GG_FINANCIAL_RETRY_FAILED')
        def unstructured(*args):raise ValueError('GG_invalid\nprivate detail')
        self.assertEqual(self.run_job(unstructured).snapshot()['last_error'],'GG_FINANCIAL_RETRY_FAILED')

    def test_bounds_cannot_expand_background_authority(self):
        for options in ({'attempts':17},{'seconds':181},{'delay':9},{'attempts':True}):
            with self.assertRaisesRegex(ValueError,'RETRY_LIMIT'):OwnedFinancialRetry(lambda *args:None,**options)
