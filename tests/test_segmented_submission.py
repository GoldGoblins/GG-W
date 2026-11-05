"""Real signed TCP fragmentation/ownership with MOCKED SDK admission only.

No transport receipt in these tests establishes real selected transactions.
The actual SDK/LAN experiment is separate from these injected policy seams.
"""
import hashlib
import threading
import time
import unittest
from unittest.mock import MagicMock,Mock,patch

from backend import gg_segmented_submission as protocol
from tests import test_lan_segmented_runtime as fixture


class SegmentedSubmissionTests(unittest.TestCase):
    cleanup=fixture.SegmentedRuntimeTests.cleanup
    manager=fixture.SegmentedRuntimeTests.manager
    network=fixture.SegmentedRuntimeTests.network

    def setUp(self):
        fixture.SegmentedRuntimeTests.setUp(self)
        self.first,self.second,self.third=self.network()
        self.receiver=self.first._peer._proof_service.submissions
        self.sender=self.third._peer._proof_service.submissions
        self.sdk=Mock();self.sdk.submit_proposals.return_value={'state':'MEMPOOL_ACCEPTED','SDK_selected':False}
        self.stack.enter_context(patch.object(self.receiver,'_sources',return_value=(self.sdk,)))

    def wait(self,condition,timeout=4):
        deadline=time.monotonic()+timeout
        while not condition():
            if time.monotonic()>=deadline:self.fail('bounded private submission condition timed out')
            time.sleep(.01)

    def test_actual_signed_fragment_transfer_only_queues_until_owned_worker_admission(self):
        raw=bytes(range(256))*512
        receipt=self.sender.send(self.first._peer.public_key,raw)
        self.assertEqual(receipt,{'state':'QUEUED','hash':hashlib.sha256(raw).hexdigest(),'SDK_selected':False})
        self.sdk.submit_proposals.assert_not_called()
        self.assertEqual(self.receiver.snapshot()['retained_raw_bytes'],len(raw))
        self.receiver.start();self.wait(lambda:self.receiver.snapshot()['queued_or_working']==0)
        self.sdk.submit_proposals.assert_called_once_with([raw])
        self.assertEqual(self.receiver.snapshot()['retained_raw_bytes'],0)

    def test_unavailable_validator_refuses_before_any_large_receive_reservation(self):
        with patch.object(self.receiver,'_sources',return_value=()):
            receipt=self.sender.send(self.first._peer.public_key,b'public signed transfer fixture')
        self.assertEqual(receipt['state'],'UNAVAILABLE');self.assertFalse(receipt['SDK_selected'])
        self.assertEqual(self.receiver.snapshot()['receiving_raw_bytes'],0);self.sdk.submit_proposals.assert_not_called()

    def test_resource_pause_refuses_new_original_and_preserves_existing_queue_until_resume(self):
        peer=self.first._peer;budget=peer.resources.budget.public();paused={**budget,'overall':0}
        peer.resources.configure(paused)
        result=self.sender.send(peer.public_key,b'public original retained by its caller')
        self.assertEqual(result['state'],'BUSY');self.assertEqual(self.receiver.snapshot()['receiving_raw_bytes'],0)
        self.sdk.submit_proposals.assert_not_called()
        peer.resources.configure(budget)
        result=self.sender.send(peer.public_key,b'public queued original')
        self.assertEqual(result['state'],'QUEUED')
        peer.resources.configure(paused);self.receiver.start()
        self.assertTrue(self.receiver.snapshot()['resource_paused']);self.assertEqual(self.receiver.snapshot()['queued_or_working'],1)
        self.sdk.submit_proposals.assert_not_called()
        peer.resources.configure(budget);self.wait(lambda:self.receiver.snapshot()['queued_or_working']==0)
        self.sdk.submit_proposals.assert_called_once_with([b'public queued original'])

    def test_one_actor_has_one_queued_original_and_total_two_actors_are_bounded(self):
        governor=self.first._peer.resources.governor();before=governor.memory_committed();leases=[]
        raw=b'public bounded raw fixture';identifier=hashlib.sha256(raw).hexdigest()
        def enqueue(actor):
            lease=governor.reserve_memory(len(raw)*16);lease.__enter__()
            result=self.receiver.enqueue(actor,raw,identifier,lease)
            if result['state']!='QUEUED':lease.__exit__(None,None,None)
            return result
        self.assertEqual(enqueue(self.third._peer.public_key)['state'],'QUEUED')
        self.assertEqual(enqueue(self.third._peer.public_key)['state'],'BUSY')
        self.assertEqual(enqueue(self.second._peer.public_key)['state'],'QUEUED')
        self.assertEqual(enqueue(self.first._peer.public_key)['state'],'BUSY')
        self.assertEqual(self.receiver.snapshot()['queued_or_working'],2)
        self.receiver.request_stop();self.assertEqual(governor.memory_committed(),before)
        self.assertEqual(self.receiver.snapshot()['retained_raw_bytes'],0)

    def test_cancellation_during_fragment_transfer_releases_all_receive_credit_without_admission(self):
        raw=b'x'*(128*1024);released=threading.Event();ready=threading.Event();errors=[]
        original=protocol.record_frames;governor=self.first._peer.resources.governor();before=governor.memory_committed()
        def frames(*args,**kwargs):
            stream=original(*args,**kwargs);yield next(stream);ready.set();released.wait(3)
            yield from stream
        def send():
            try:self.sender.send(self.first._peer.public_key,raw)
            except (OSError,ValueError) as error:errors.append(type(error).__name__)
        with patch.object(protocol,'record_frames',side_effect=frames):
            thread=threading.Thread(target=send);thread.start()
            try:
                self.assertTrue(ready.wait(3));self.wait(lambda:self.receiver.snapshot()['receiving']==1)
                self.receiver.request_stop();released.set();thread.join(4)
            finally:released.set();thread.join(4)
        self.assertFalse(thread.is_alive());self.assertTrue(errors)
        self.wait(lambda:self.receiver.snapshot()['receiving']==0)
        self.assertEqual(governor.memory_committed(),before);self.sdk.submit_proposals.assert_not_called()

    def test_signed_ack_cannot_claim_SDK_selection(self):
        with patch.object(self.receiver,'_receipt',side_effect=lambda state,key:{'state':state,'hash':key,'SDK_selected':True}):
            with self.assertRaisesRegex(ValueError,'SUBMISSION_ACK'):self.sender.send(self.first._peer.public_key,b'public raw')
        self.wait(lambda:self.receiver.snapshot()['receiving']==0);self.sdk.submit_proposals.assert_not_called()

    def test_signed_chunk_record_cannot_replace_the_declared_original_identity(self):
        original=protocol.record_frames
        def frames(record,**kwargs):return original({**record,'hash':'0'*64},**kwargs)
        with patch.object(protocol,'record_frames',side_effect=frames):
            with self.assertRaises((ValueError,OSError)):self.sender.send(self.first._peer.public_key,b'x'*(128*1024))
        self.wait(lambda:self.receiver.snapshot()['receiving']==0);self.sdk.submit_proposals.assert_not_called()
        self.assertEqual(self.receiver.snapshot()['queued_or_working'],0)

    def test_invalid_declarations_are_rejected_before_allocation_or_native_query(self):
        valid={'hash':'a'*64,'size':1}
        for bad in ({**valid,'size':True},{**valid,'size':0},{**valid,'size':protocol.MAX_RAW+1},
                    {**valid,'verified':True},{**valid,'hash':'A'*64}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):self.receiver.receive(None,self.third._peer.public_key,'unused',bad)
        self.assertEqual(self.receiver.snapshot()['receiving_raw_bytes'],0);self.sdk.submit_proposals.assert_not_called()

    def test_bad_original_digest_does_not_enter_worker_queue(self):
        raw=b'public wire';lease=MagicMock()
        with self.assertRaisesRegex(ValueError,'SUBMISSION_INTEGRITY'):
            self.receiver.enqueue(self.third._peer.public_key,raw,'0'*64,lease)
        lease.__exit__.assert_not_called();self.sdk.submit_proposals.assert_not_called()

    def test_unexpected_owned_provider_error_does_not_kill_worker_or_leak_queued_memory(self):
        self.sdk.submit_proposals.side_effect=[KeyError('public injected provider failure'),{'state':'MEMPOOL_ACCEPTED','SDK_selected':False}]
        self.receiver.start()
        self.assertEqual(self.sender.send(self.first._peer.public_key,b'first public original')['state'],'QUEUED')
        self.wait(lambda:self.receiver.snapshot()['queued_or_working']==0)
        self.assertEqual(self.receiver.snapshot()['last_error'],'GG_SDK_SUBMISSION_UNAVAILABLE')
        self.assertTrue(self.receiver.worker.is_alive());self.assertEqual(self.receiver.snapshot()['retained_raw_bytes'],0)
        self.assertEqual(self.sender.send(self.first._peer.public_key,b'next public original')['state'],'QUEUED')
        self.wait(lambda:self.receiver.snapshot()['queued_or_working']==0)
        self.assertEqual(self.sdk.submit_proposals.call_count,2);self.assertTrue(self.receiver.worker.is_alive())


class SegmentedReplicaIngressTests(unittest.TestCase):
    setUp=fixture.SegmentedRuntimeTests.setUp
    cleanup=fixture.SegmentedRuntimeTests.cleanup
    manager=fixture.SegmentedRuntimeTests.manager
    network=fixture.SegmentedRuntimeTests.network

    def test_real_paired_replica_transport_key_does_not_grant_submission_role(self):
        first,_,third=self.network(third_role='replica');receiver=first._peer._proof_service.submissions;sdk=Mock()
        with patch.object(receiver,'_sources',return_value=(sdk,)):
            with self.assertRaises((ValueError,OSError)):
                third._peer._proof_service.submissions.send(first._peer.public_key,b'public raw fixture')
        self.assertEqual(receiver.snapshot()['receiving_raw_bytes'],0);sdk.submit_proposals.assert_not_called()
        self.assertFalse(first._peer._profile._failed)


if __name__=='__main__':unittest.main()
