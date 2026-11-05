"""Actual leased storage and signed LAN frames; no SDK/finality claim here."""
from copy import deepcopy
import threading
import time
import unittest
from unittest.mock import patch

from backend.gg_observer_enrollment import EnrollmentInbox,validate_ack
from backend.gg_consensus_profile import ValidatorProfile
from tests import test_native_observer_profile as fixture


class ObserverEnrollmentTests(unittest.TestCase):
    cleanup=fixture.NativeObserverProfileTests.cleanup
    profile=fixture.NativeObserverProfileTests.profile
    network=fixture.NativeObserverProfileTests.network
    observer=fixture.NativeObserverProfileTests.observer

    def setUp(self):
        fixture.NativeObserverProfileTests.setUp(self)
        for profile in self.validators:profile.bind_anchor(self.bundle,self.peers[0].public_key)
        self.targets=[self.validators[0],self.validators[2]]
        self.inbox=EnrollmentInbox(self.peers[0],lambda:tuple(self.targets));self.addCleanup(self.inbox.request_stop)
        self.peers[0]._observer_admissions=self.inbox
        self.grant=self.observer().public_grant();self.owner=self.peers[2].public_key
        self.anchor=self.validators[0].anchor()

    def offer(self):return self.inbox.offer(self.owner,self.grant)

    def test_offer_has_no_disk_effect_and_ack_only_names_committed_owned_validators(self):
        before=deepcopy(self.anchor);first=self.offer();self.assertEqual(first['state'],'WAIT')
        self.assertTrue(all('admitted_observers' not in profile._body for profile in self.validators))
        self.assertTrue(self.inbox.serve_one());ready=self.offer()
        keys=sorted(profile.public_invite()['body']['validator_key'] for profile in self.targets)
        self.assertEqual(ready['state'],'READY');self.assertEqual(ready['admitted_validator_keys'],keys)
        self.assertEqual(validate_ack(ready,self.grant,self.anchor,self.peers[0].public_key),ready)
        for profile in self.targets:self.assertEqual(profile._body['admitted_observers'],[self.grant])
        for profile in (self.validators[1],self.validators[3]):self.assertNotIn('admitted_observers',profile._body)
        self.assertEqual(self.validators[0].anchor(),before);self.assertEqual(len(before['genesis']['validators']),4)
        self.assertFalse(self.inbox.snapshot()['receipt_is_native_connectivity'])

    def test_unknown_or_wrong_authenticated_owner_cannot_queue_a_valid_foreign_grant(self):
        for owner in (self.peers[1].public_key,'a'*64):
            with self.subTest(owner_known=owner==self.peers[1].public_key),self.assertRaisesRegex(ValueError,'AUTH_OWNER'):
                self.inbox.offer(owner,self.grant)
        self.assertEqual(self.inbox.snapshot()['grants'],0)
        self.assertTrue(all('admitted_observers' not in profile._body for profile in self.validators))

    def test_invalid_signature_and_unrequested_fields_are_rejected_without_write(self):
        bad=deepcopy(self.grant);bad['owner_signature']='00'*64
        for grant in (bad,{**self.grant,'verified':True}):
            with self.assertRaises(ValueError):self.inbox.offer(self.owner,grant)
        self.assertEqual(self.inbox.snapshot()['grants'],0)

    def test_no_owned_validator_is_unavailable_without_opening_or_unlocking_any_profile(self):
        self.targets.clear()
        with patch.object(ValidatorProfile,'open',side_effect=AssertionError('must not open')):
            self.assertEqual(self.offer()['state'],'UNAVAILABLE');self.assertFalse(self.inbox.serve_one())
        self.assertEqual(self.inbox.snapshot()['grants'],0)

    def test_closed_and_foreign_owned_profiles_are_never_writers(self):
        first=self.targets[0];first.close();self.targets=[first,self.validators[1]]
        self.assertEqual(self.offer()['state'],'UNAVAILABLE');self.assertFalse(self.inbox.serve_one())
        self.assertNotIn('admitted_observers',self.validators[1]._body)

    def test_blocked_disk_work_does_not_hold_offer_or_status_lock(self):
        self.offer();entered=threading.Event();release=threading.Event();original=self.targets[0].admit_observer
        errors=[]
        def blocked(grant):
            entered.set()
            if not release.wait(3):raise AssertionError('owned test gate timeout')
            return original(grant)
        def run():
            try:self.inbox.serve_one()
            except BaseException as error:errors.append(error)
        with patch.object(self.targets[0],'admit_observer',side_effect=blocked):
            worker=threading.Thread(target=run);worker.start()
            try:
                self.assertTrue(entered.wait(1));start=time.monotonic()
                self.assertEqual(self.offer()['state'],'WAIT');self.inbox.snapshot()
                self.assertLess(time.monotonic()-start,.2)
                self.assertFalse(self.inbox.serve_one())
            finally:release.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertEqual(self.offer()['state'],'READY')

    def test_stop_cancels_queued_writes_and_future_offers(self):
        self.offer();self.peers[0].request_stop()
        self.assertFalse(self.inbox.serve_one())
        with self.assertRaisesRegex(ValueError,'STOPPED'):self.offer()
        self.assertEqual(self.inbox.snapshot()['state'],'STOPPED')
        self.assertTrue(all('admitted_observers' not in profile._body for profile in self.validators))

    def test_indeterminate_commit_does_not_ack_that_validator_and_explicit_reopen_recovers(self):
        self.offer();profile=self.targets[0];commit=profile._commit
        def uncertain():commit();raise OSError('owned injected lost commit acknowledgment')
        with patch.object(profile,'_commit',side_effect=uncertain):self.inbox.serve_one()
        ready=self.offer();self.assertEqual(ready['admitted_validator_keys'],[self.targets[1].public_invite()['body']['validator_key']])
        self.assertTrue(profile._failed);name=profile.name;profile.close()
        reopened=ValidatorProfile.open(name);self.profiles.append(reopened);self.targets[0]=reopened
        self.assertEqual(reopened._body['admitted_observers'],[self.grant])
        self.offer();self.inbox.serve_one();self.assertEqual(len(self.offer()['admitted_validator_keys']),2)

    def test_ack_cannot_claim_membership_liveness_or_a_foreign_validator(self):
        self.offer();self.inbox.serve_one();ready=self.offer()
        changes=({'verified':True},{'genesis_hash':'a'*64},{'grant_hash':'b'*64},{'state':'WAIT'},
            {'admitted_validator_keys':[]},{'admitted_validator_keys':[self.validators[1].public_invite()['body']['validator_key']]})
        for change in changes:
            with self.subTest(fields=tuple(change)),self.assertRaises(ValueError):
                validate_ack({**ready,**change},self.grant,self.anchor,self.peers[0].public_key)

    def test_different_grant_for_same_producer_cannot_replace_queued_identity(self):
        self.offer();other=self.observer(1).public_grant()
        with self.assertRaisesRegex(ValueError,'DELEGATION_EXISTS'):self.inbox.offer(self.owner,other)
        self.assertEqual(self.inbox.snapshot()['grants'],1);self.inbox.serve_one()
        self.assertEqual(self.targets[0]._body['admitted_observers'],[self.grant])

    def test_signed_tcp_offer_waits_then_receives_actual_owned_commit_ack(self):
        sender=self.peers[2];receiver=self.peers[0]
        first=sender.native_observer_admit(receiver.public_key,self.grant)
        self.assertEqual(first['state'],'WAIT');self.assertEqual(self.inbox.snapshot()['grants'],1)
        self.inbox.serve_one()
        ready=sender.native_observer_admit(receiver.public_key,self.grant)
        self.assertEqual(ready['state'],'READY');self.assertEqual(len(ready['admitted_validator_keys']),2)
        self.assertGreater(receiver._raw_received,0);self.assertGreater(sender._raw_received,0)
        with self.assertRaisesRegex(ValueError,'AUTH_OWNER'):
            self.peers[1].native_observer_admit(receiver.public_key,self.grant)

    def test_cancelled_sender_opens_no_connection_and_target_must_be_committee_owner(self):
        cancel=threading.Event();cancel.set();sender=self.peers[2]
        with patch.object(sender,'_connection',side_effect=AssertionError('must not connect')):
            with self.assertRaisesRegex(ValueError,'STOPPED'):sender.native_observer_admit(self.peers[0].public_key,self.grant,cancel=cancel)
            with self.assertRaisesRegex(ValueError,'TARGET'):sender.native_observer_admit(sender.public_key,self.grant)
        self.assertEqual(self.inbox.snapshot()['grants'],0)

    def test_server_rejects_foreign_grant_on_a_real_authenticated_other_owner_channel(self):
        from backend.gg_lan_dag import _send,MAX_FRAME
        sender=self.peers[1];receiver=self.peers[0];deadline=time.monotonic()+3
        with sender._connection(receiver.public_key,deadline=deadline) as sock:
            session=sender._client_auth(sock,receiver.public_key,deadline)
            _send(sock,sender._frame(session,0,'OBSERVER_ADMIT',{'grant':self.grant}),MAX_FRAME,deadline=deadline)
            with self.assertRaises((OSError,ValueError,EOFError)):
                sender._read(sock,MAX_FRAME,deadline=deadline)
        self.assertEqual(self.inbox.snapshot()['grants'],0)
        self.assertTrue(all('admitted_observers' not in profile._body for profile in self.validators))

    def test_all_six_registered_slots_remain_bounded_and_are_served_without_starvation(self):
        offered=[]
        for owner_index,peer in enumerate(self.peers):
            for slot in (0,1):
                number=2*owner_index+slot
                grant=self.grant if number==4 else self.observer(number+1,peer=peer,slot=slot).public_grant()
                self.inbox.offer(peer.public_key,grant);offered.append((peer.public_key,grant))
        self.assertEqual(self.inbox.snapshot()['grants'],6)
        for _ in range(6):self.assertTrue(self.inbox.serve_one())
        self.assertFalse(self.inbox.serve_one())
        self.assertTrue(all(self.inbox.offer(owner,grant)['state']=='READY' for owner,grant in offered))
        self.assertEqual(len(self.targets[0]._body['admitted_observers']),6)
        self.assertEqual(len(self.validators[0].anchor()['genesis']['validators']),4)

    def test_exact_pending_ack_polling_cannot_starve_its_own_signature_credit(self):
        self.assertEqual(self.offer()['state'],'WAIT')
        with patch('backend.gg_observer_enrollment.validate_grant',side_effect=AssertionError('already verified exact grant')):
            for _ in range(24):self.assertEqual(self.offer()['state'],'WAIT')
        self.inbox.serve_one();self.assertEqual(self.offer()['state'],'READY')
        changed=deepcopy(self.grant);changed['owner_signature']='00'*64
        with self.assertRaisesRegex(ValueError,'GRANT_INVALID'):self.inbox.offer(self.owner,changed)

    def test_bound_session_mutation_is_rejected_before_ack_or_any_disk_write(self):
        self.offer();original=self.peers[0]._bundle
        changed=deepcopy(original);changed['body']['label']='Changed in place without rebinding'
        self.peers[0]._bundle=changed
        try:
            with self.assertRaisesRegex(ValueError,'SESSION_CHANGED'):self.offer()
            with self.assertRaisesRegex(ValueError,'SESSION_CHANGED'):self.inbox.serve_one()
        finally:self.peers[0]._bundle=original
        self.assertTrue(all('admitted_observers' not in profile._body for profile in self.validators))


if __name__=='__main__':unittest.main()
