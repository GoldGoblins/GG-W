"""Real protected own journals/signatures; SDK result boundary is MOCKED.

These local measurements never establish a selected network transaction.
"""
import threading
import time
import unittest
from unittest.mock import patch

from backend.gg_dag_producer_journal import OwnedSegmentedProducer
from tests import test_segmented_proof_sync as fixture


class SegmentedProductionTests(unittest.TestCase):
    cleanup=fixture.SegmentedProofPolicyTests.cleanup
    verified=fixture.SegmentedProofPolicyTests.verified
    base_packet=fixture.SegmentedProofPolicyTests.base_packet

    def setUp(self):
        fixture.SegmentedProofPolicyTests.setUp(self)
        self.peer.install_session(self.bundle,_start_gossip=False)
        self.exchange=self.peer._proof_service;self.addCleanup(self.exchange.close)
        with patch.object(self.exchange,'_fetch',side_effect=[self.packet,self.base_packet()]):self.exchange._observe(self.peer.public_key)
        self.job=self.exchange.production
        self.stack.enter_context(patch.object(self.exchange.submissions,'_sources',return_value=(self.control,)))

    def wait(self,condition,timeout=4):
        deadline=time.monotonic()+timeout
        while not condition():
            if time.monotonic()>=deadline:self.fail('bounded production condition timed out')
            time.sleep(.01)

    def test_finite_job_commits_originals_and_never_calls_queue_receipts_selected(self):
        before=list(self.owners[0].descriptor()['public_keys'])
        self.peer.start_dag_production(1000,1,60000);self.wait(lambda:not self.job.snapshot()['worker_active'])
        state=self.job.snapshot();self.assertEqual(state['state'],'COMPLETE');self.assertEqual(state['production']['blocks'],1)
        self.assertFalse(state['production']['SDK_selection_asserted'])
        self.assertEqual(self.owners[0]._db.execute('SELECT count(*) FROM own_proposals').fetchone()[0],1)
        self.assertEqual(self.owners[0].descriptor()['public_keys'],before)
        self.assertEqual(self.exchange.snapshot()['dag_segmented_commitment']['transactions'],'0')

    def test_resume_preserves_pending_original_and_advances_exact_owned_sequence(self):
        self.peer.start_dag_production(1000,1,60000);self.wait(lambda:not self.job.snapshot()['worker_active'])
        old=bytes(self.owners[0]._db.execute('SELECT wire FROM own_proposals WHERE position=1').fetchone()[0])
        self.peer.start_dag_production(1000,1,60000);self.wait(lambda:not self.job.snapshot()['worker_active'])
        self.assertEqual(self.job.snapshot()['state'],'COMPLETE')
        rows=list(self.owners[0]._db.execute('SELECT sequence,wire FROM own_proposals ORDER BY position'))
        self.assertEqual([row[0] for row in rows],[1,2]);self.assertEqual(bytes(rows[0][1]),old)
        self.assertIsNone(self.owners[0]._segmented_writer)

    def test_cancel_after_real_journal_open_before_signing_closes_owned_handle_without_nonce_use(self):
        opened=threading.Event();release=threading.Event();original=OwnedSegmentedProducer.open
        def held(*args,**kwargs):
            writer=original(*args,**kwargs);opened.set();release.wait(3);return writer
        with patch.object(OwnedSegmentedProducer,'open',side_effect=held):
            self.peer.start_dag_production(60000,5000,0)
            try:
                self.assertTrue(opened.wait(3));self.peer.stop_dag_production()
            finally:release.set()
            self.wait(lambda:not self.job.snapshot()['worker_active'])
        self.assertEqual(self.job.snapshot()['state'],'STOPPED');self.assertIsNone(self.owners[0]._segmented_writer)
        self.assertEqual(self.owners[0]._db.execute('SELECT count(*) FROM own_proposals').fetchone()[0],0)

    def test_status_remains_readable_while_real_owner_lock_is_held_by_signing_work(self):
        entered=threading.Event();release=threading.Event()
        def held(writer,*args,**kwargs):
            with writer.profile._lock:entered.set();release.wait(3);raise ValueError('GG_LAN_NODE_CANCELLED')
        with patch.object(OwnedSegmentedProducer,'produce',autospec=True,side_effect=held):
            self.peer.start_dag_production(60000,1,0)
            try:
                self.assertTrue(entered.wait(3));snapshot=self.job.snapshot()
                self.assertTrue(snapshot['worker_active']);self.assertFalse(snapshot['SDK_selection_asserted'])
            finally:self.job.request_stop();release.set()
            self.wait(lambda:not self.job.snapshot()['worker_active'])
        self.assertIsNone(self.owners[0]._segmented_writer)

    def test_replica_cannot_start_owned_signing_even_with_a_real_paired_profile(self):
        peer=self.peers[2];peer.install_session(self.bundle,_start_gossip=False)
        with self.assertRaisesRegex(ValueError,'REPLICA_READ_ONLY'):peer.start_dag_production(1000,1,0)
        self.assertIsNone(self.owners[2]._segmented_writer)

    def test_invalid_cut_policy_is_rejected_before_owned_rpc(self):
        with patch.object(self.control,'certified_state') as query:
            for args in ({'cut_blocks':True},{'cut_raw_bytes':0},{'cut_blocks':4096}):
                with self.assertRaisesRegex(ValueError,'CUT_POLICY'):self.control.maintain_segmented(**args)
            query.assert_not_called()

    def test_unexpected_worker_failure_reports_error_and_releases_the_real_owned_journal(self):
        with patch.object(OwnedSegmentedProducer,'produce',side_effect=AttributeError('public injected provider failure')):
            self.peer.start_dag_production(1000,1,0);self.wait(lambda:not self.job.snapshot()['worker_active'])
        self.assertEqual(self.job.snapshot()['state'],'ERROR')
        self.assertEqual(self.job.snapshot()['last_error'],'GG_LAN_NODE_PRODUCTION_FAILED')
        self.assertIsNone(self.owners[0]._segmented_writer)
        self.assertFalse(self.job.snapshot()['production']['SDK_selection_asserted'])

    def test_shared_verified_conflict_masks_current_counters_and_disables_owned_production(self):
        from copy import deepcopy
        from backend.gg_dag_checkpoint import make_conflict_evidence
        other=deepcopy(self.packet);other['signed_header']['commit']['block_id']['hash']='c'*64
        self.exchange._accept_conflict(make_conflict_evidence(self.packet,other,self.exchange.anchor))
        status=self.peer.snapshot()
        self.assertEqual(status['dag_proofs']['state'],'FAULT')
        self.assertIsNone(status['certified_transactions']);self.assertIsNone(status['certified_blocks'])
        self.assertFalse(status['dag_proofs']['canonical_finality'])
        self.assertFalse(status['dag_production']['can_start']);self.assertEqual(status['certified_test_accounts'],[])


class SegmentedProductionFailoverTests(unittest.TestCase):
    cleanup=fixture.SegmentedProofPolicyTests.cleanup
    verified=fixture.SegmentedProofPolicyTests.verified
    base_packet=fixture.SegmentedProofPolicyTests.base_packet

    def setUp(self):
        from tests import test_segmented_authority as authority_fixture
        original=authority_fixture.protected_network
        with patch.object(authority_fixture,'protected_network',side_effect=lambda:original(roles=('producer','producer','producer'))):
            fixture.SegmentedProofPolicyTests.setUp(self)
        self.peer=self.peers[2];self.peer.install_session(self.bundle,_start_gossip=False)
        self.exchange=self.peer._proof_service;self.addCleanup(self.exchange.close)
        with patch.object(self.exchange,'_fetch',side_effect=[self.packet,self.base_packet()]):self.exchange._observe(self.peer.public_key)

    def test_failed_first_validator_owner_rotates_to_other_owner_without_resigning_original(self):
        attempts=[];owners=sorted({row['body']['owner_peer_key'] for row in self.exchange.anchor['genesis']['membership']['validators']})
        def send(owner,raw,**kwargs):
            attempts.append((owner,raw))
            if owner==owners[0]:raise ConnectionRefusedError('public injected unavailable LAN owner')
            return {'state':'QUEUED','SDK_selected':False}
        with patch.object(self.exchange.submissions,'send',side_effect=send):
            self.peer.start_dag_production(3000,1,60000);worker=self.exchange.production.worker;worker.join(5)
        self.assertFalse(worker.is_alive());self.assertGreaterEqual(len(attempts),2)
        self.assertEqual([row[0] for row in attempts[:2]],owners)
        self.assertEqual(attempts[0][1],attempts[1][1])
        self.assertEqual(self.peer._profile._db.execute('SELECT count(*) FROM own_proposals').fetchone()[0],1)
        self.assertEqual(self.exchange.production.snapshot()['state'],'COMPLETE')
        self.assertEqual(self.exchange.snapshot()['dag_segmented_commitment']['transactions'],'0')


if __name__=='__main__':unittest.main()
