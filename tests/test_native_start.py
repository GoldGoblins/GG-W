"""Actual protected profiles and exact child handles; no SDK/crypto proof claim."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.gg_native_start import NativeStartReservation
from backend import gg_native_start as start_policy
from backend import gg_testnet_process as limits
from tests import test_native_observer_profile as fixture


class NativeStartReservationTests(unittest.TestCase):
    cleanup=fixture.NativeObserverProfileTests.cleanup
    profile=fixture.NativeObserverProfileTests.profile
    network=fixture.NativeObserverProfileTests.network
    observer=fixture.NativeObserverProfileTests.observer

    def setUp(self):fixture.NativeObserverProfileTests.setUp(self)

    def cases(self):
        validator=self.validators[0];validator.bind_anchor(self.bundle,self.peers[0].public_key)
        return (validator,self.observer())

    def child(self):
        process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c','import time;time.sleep(30)'],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.addCleanup(self.finish,process);lease=limits.contain(process);self.addCleanup(lease.close)
        return process

    def finish(self,process):
        limits._stop_owned(process)
        if process.stdin is not None:process.stdin.close()

    def stop(self,process):process.kill();process.wait(timeout=5)

    def reopen(self,profile):
        profile.close();value=type(profile).open(profile.name);self.profiles.append(value);return value

    def test_same_lease_proven_no_input_abort_releases_only_fresh_intent_and_keeps_keys(self):
        for profile in self.cases():
            with self.subTest(role=profile.snapshot()['role']):
                before=deepcopy(profile._body);process=self.child()
                with self.assertRaisesRegex(ValueError,'FIXTURE_CANCELLED'):
                    with NativeStartReservation(profile,process) as intent:
                        self.assertTrue(intent.fresh);self.assertTrue(profile.snapshot()['native_started'])
                        self.stop(process);raise ValueError('GG_FIXTURE_CANCELLED')
                self.assertEqual(profile._body,before);self.assertFalse((profile.root/'native').exists())
                reopened=self.reopen(profile);self.assertEqual(reopened._body,before)

    def test_alive_child_cannot_prove_abort_even_without_input_marker(self):
        for profile in self.cases():
            process=self.child()
            with self.assertRaisesRegex(ValueError,'ABORT_NOT_PROVEN'):
                with NativeStartReservation(profile,process):raise ValueError('GG_FIXTURE_CANCELLED')
            self.assertTrue(profile.snapshot()['native_started']);self.stop(process)
            reopened=self.reopen(profile)
            with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):reopened.claim_native_start()

    def test_possible_first_write_never_releases_even_when_no_native_root_exists(self):
        for profile in self.cases():
            process=self.child();reservation=NativeStartReservation(profile,process)
            with self.assertRaisesRegex(OSError,'unknown pipe outcome'):
                with reservation as intent:
                    intent.mark_input_started();self.stop(process);raise OSError('public fixture unknown pipe outcome')
            self.assertTrue(profile.snapshot()['native_started'])
            with self.assertRaisesRegex(ValueError,'REUSED'):reservation.__enter__()
            with self.assertRaisesRegex(ValueError,'INACTIVE'):reservation.mark_input_started()
            reopened=self.reopen(profile)
            with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):reopened.claim_native_start()

    def test_native_root_created_during_attempt_is_preserved_and_prevents_release(self):
        for profile in self.cases():
            process=self.child();root=profile.root/'native'
            with self.assertRaisesRegex(ValueError,'ABORT_NOT_PROVEN'):
                with NativeStartReservation(profile,process):
                    root.mkdir();(root/'public-fixture-history').write_bytes(b'existing bytes')
                    self.stop(process);raise ValueError('GG_FIXTURE_CANCELLED')
            self.assertEqual((root/'public-fixture-history').read_bytes(),b'existing bytes')
            self.assertTrue(profile.snapshot()['native_started'])

    def test_existing_start_intent_and_cold_reopen_cannot_be_released(self):
        for profile in self.cases():
            profile.claim_native_start();profile=self.reopen(profile);before=deepcopy(profile._body);process=self.child()
            with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):
                with NativeStartReservation(profile,process):self.fail('old intent admitted')
            self.assertEqual(profile._body,before)

    def test_existing_history_abort_never_changes_metadata_or_signing_history(self):
        for profile in self.cases():
            profile.claim_native_start();root=profile.root/'native';root.mkdir();history=root/'public-fixture-history';history.write_bytes(b'preserve')
            before=deepcopy(profile._body);process=self.child()
            with self.assertRaisesRegex(ValueError,'FIXTURE_CANCELLED'):
                with NativeStartReservation(profile,process) as intent:
                    self.assertFalse(intent.fresh);self.stop(process);raise ValueError('GG_FIXTURE_CANCELLED')
            self.assertEqual(profile._body,before);self.assertEqual(history.read_bytes(),b'preserve')

    def test_unknown_claim_commit_outcome_cannot_compensate_or_reenter(self):
        for profile in self.cases():
            process=self.child();commit=profile._commit
            def lost_return():commit();raise OSError('public fixture lost commit acknowledgement')
            reservation=NativeStartReservation(profile,process)
            with patch.object(profile,'_commit',side_effect=lost_return) as calls:
                with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
                    with reservation:self.fail('unknown commit admitted')
            self.assertEqual(calls.call_count,1);self.assertTrue(profile._failed)
            self.stop(process);reopened=self.reopen(profile);self.assertTrue(reopened.snapshot()['native_started'])
            with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):reopened.claim_native_start()

    def test_unknown_abort_commit_requires_cold_revalidation_and_preserves_identity(self):
        for profile in self.cases():
            process=self.child();commit=profile._commit;before=deepcopy(profile._body);count=[0]
            def lost_abort():
                count[0]+=1;commit()
                if count[0]==2:raise OSError('public fixture lost abort acknowledgement')
            with patch.object(profile,'_commit',side_effect=lost_abort):
                with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
                    with NativeStartReservation(profile,process):
                        self.stop(process);raise ValueError('GG_FIXTURE_CANCELLED')
            self.assertTrue(profile._failed);reopened=self.reopen(profile)
            self.assertEqual(reopened._body,before);self.assertFalse(reopened.snapshot()['native_started'])

    def test_abort_failure_before_commit_keeps_start_intent_and_requires_cold_revalidation(self):
        for profile in self.cases():
            process=self.child();commit=profile._commit;calls=[0]
            def fail_abort():
                calls[0]+=1
                if calls[0]==2:raise OSError('public fixture abort not committed')
                commit()
            with patch.object(profile,'_commit',side_effect=fail_abort):
                with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
                    with NativeStartReservation(profile,process):
                        self.stop(process);raise ValueError('GG_FIXTURE_CANCELLED')
            self.assertTrue(profile._failed);reopened=self.reopen(profile)
            self.assertTrue(reopened.snapshot()['native_started'])
            with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):reopened.claim_native_start()

    def test_claim_failure_before_commit_takes_no_compensating_write(self):
        for profile in self.cases():
            process=self.child();before=deepcopy(profile._body)
            with patch.object(profile,'_commit',side_effect=OSError('public fixture claim not committed')) as calls:
                with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):
                    with NativeStartReservation(profile,process):self.fail('failed claim admitted')
            self.assertEqual(calls.call_count,1);self.assertTrue(profile._failed);self.stop(process)
            reopened=self.reopen(profile);self.assertEqual(reopened._body,before)

    def test_unopened_context_dead_child_and_success_without_handoff_are_refused(self):
        profile=self.cases()[0];process=self.child()
        with self.assertRaisesRegex(ValueError,'OWNED_CONTEXT'):NativeStartReservation(object(),process)
        self.stop(process)
        with self.assertRaisesRegex(ValueError,'CHILD_NOT_RUNNING'):
            with NativeStartReservation(profile,process):pass
        self.assertFalse(profile.snapshot()['native_started'])
        process=self.child()
        with self.assertRaisesRegex(ValueError,'HANDOFF_REQUIRED'):
            with NativeStartReservation(profile,process):self.stop(process)
        self.assertFalse(profile.snapshot()['native_started'])


class NativeStartBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-native-budget-')
        self.root=Path(self.temp.name)
        self.assertEqual(self.root.resolve().parent,Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)

    def test_missing_and_small_stores_keep_original_deadline_without_creating_state(self):
        missing=self.root/'native'
        value=start_policy.native_start_budget(missing)
        self.assertEqual(value['seconds'],12);self.assertFalse(missing.exists())
        missing.mkdir();(missing/'public').write_bytes(b'public')
        self.assertEqual(start_policy.native_start_budget(missing,base_seconds=.3)['seconds'],.3)

    def test_large_original_store_adds_finite_budget_from_actual_file_sizes(self):
        native=self.root/'native';(native/'data').mkdir(parents=True)
        with (native/'data'/'public-history').open('wb') as stream:stream.truncate(24*1024**2)
        value=start_policy.native_start_budget(native)
        self.assertEqual(value['observed_native_file_bytes'],24*1024**2)
        self.assertEqual(value['files'],1);self.assertEqual(value['seconds'],14)
        self.assertIn('NOT_VERIFICATION',value['basis'])
        self.assertEqual((native/'data'/'public-history').stat().st_size,24*1024**2)

    def test_budget_has_absolute_ceiling_and_rejects_invalid_base_or_oversized_inventory(self):
        (self.root/'public').write_bytes(b'x'*1024)
        with patch.object(start_policy,'START_BASE_STORE_BYTES',0),patch.object(start_policy,'START_REPLAY_BYTES_PER_SECOND',1):
            self.assertEqual(start_policy.native_start_budget(self.root)['seconds'],180)
        for value in (True,0,-1,float('inf'),float('nan'),181):
            with self.subTest(base=value),self.assertRaisesRegex(ValueError,'START_BUDGET'):start_policy.native_start_budget(self.root,base_seconds=value)
        (self.root/'second').write_bytes(b'public')
        with patch.object(start_policy,'START_INVENTORY_MAX_ENTRIES',1),self.assertRaisesRegex(ValueError,'INVENTORY_LIMIT'):
            start_policy.native_start_budget(self.root)

    def test_linked_root_is_refused_before_directory_traversal(self):
        original=start_policy.is_link
        with patch.object(start_policy,'is_link',side_effect=lambda path:Path(path)==self.root or original(path)),patch.object(start_policy.os,'scandir') as scan:
            with self.assertRaisesRegex(ValueError,'NATIVE_PATH'):start_policy.native_start_budget(self.root)
            scan.assert_not_called()


if __name__=='__main__':unittest.main()
