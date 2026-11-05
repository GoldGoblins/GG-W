"""Owned history observation boundaries; reports never become SDK proofs."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_local_history_status as history
from backend.gg_protocol_node import OwnedProtocolNode

GENESIS = hashlib.sha256(b'local-history-test').hexdigest()


def report():
    return {'schema': history.SCHEMA, 'scope': history.SCOPE,
        'genesis_hash': GENESIS, 'mode': 'FULL_REPLAY', 'state': 'READY',
        'verified_through': '9007199254740993', 'retained_through': '9007199254740995',
        'originals_first_height': '1', 'active_original_first_height': '9007199254740995',
        'active_original_last_height': '9007199254740995', 'active_original_count': '1',
        'active_bytes': '9007199254740997', 'archive_segments': '4',
        'archive_bytes': '9007199254740999', 'archived_original_count': '9007199254740994',
        'missing_archive_ranges': [], 'archive_fault': None, 'disk_reserve_bytes': '8388608',
        'full_replay_required_on_cold_start': True, 'checkpoint_trusted': False}


class LocalHistoryStatus(unittest.TestCase):
    def test_exact_large_heights_stay_strings_and_never_grant_proof_or_contact(self):
        source = report()
        value = history.observation(source, GENESIS, 'VALIDATOR', running=True, observed_at=10, now=12)
        self.assertEqual(value['state'], 'READY')
        self.assertEqual(value['report']['verified_through'], '9007199254740993')
        self.assertEqual(value['report']['retained_through'], '9007199254740995')
        self.assertFalse(value['is_sdk_certificate'])
        self.assertFalse(value['is_peer_contact'])
        value['report']['active_bytes'] = '0'
        self.assertEqual(source['active_bytes'], '9007199254740997')
        source['archive_bytes'] = str(2**64 - 1)
        self.assertEqual(history.validate_report(source, GENESIS)['archive_bytes'], str(2**64 - 1))

    def test_foreign_and_malformed_history_fail_closed_without_leaking_values(self):
        invalid = [
            ('genesis_hash', 'f' * 64), ('scope', 'SDK_CERTIFICATE'),
            ('verified_through', '9007199254740996'), ('active_original_count', '2'),
            ('active_original_first_height', '1'), ('active_original_last_height', '0'),
            ('originals_first_height', '0'), ('retained_through', 9007199254740995),
            ('active_bytes', '01'), ('archive_bytes', str(2**64)),
            ('checkpoint_trusted', True), ('full_replay_required_on_cold_start', False),
            ('state', 'COMPLETE'), ('missing_archive_ranges', [{'path': '/private/profile'}]),
            ('archive_fault', '/private/profile'), ('extra', 'private-local-path')]
        for key, replacement in invalid:
            with self.subTest(key=key):
                value = report(); value[key] = replacement
                observed = history.observation(value, GENESIS, 'REPLICA', running=True, observed_at=10, now=12)
                self.assertEqual(observed['state'], 'UNAVAILABLE')
                self.assertIsNone(observed['report'])
                self.assertNotIn('private', repr(observed))

    def test_light_stopped_stale_and_clock_rewind_cannot_claim_current_local_audit(self):
        for role, running, now, expected in (
                ('LIGHT', True, 12, 'NOT_APPLICABLE'), ('VALIDATOR', False, 12, 'UNAVAILABLE'),
                ('REPLICA', True, 16, 'STALE'), ('REPLICA', True, 9, 'UNAVAILABLE')):
            with self.subTest(role=role, running=running, now=now):
                value = history.observation(report(), GENESIS, role, running=running, observed_at=10, now=now)
                self.assertEqual(value['state'], expected)
                if expected not in ('READY', 'STALE'):
                    self.assertIsNone(value['report'])

    def test_empty_genesis_and_unavailable_known_fault_are_distinct(self):
        value = report()
        for key in history.COUNTERS:
            value[key] = '0'
        value['disk_reserve_bytes'] = '8388608'
        self.assertEqual(history.validate_report(value, GENESIS), value)
        value.update(state='UNAVAILABLE', archive_fault='GG_FINANCIAL_HISTORY_UNAVAILABLE')
        observed = history.observation(value, GENESIS, 'REPLICA', running=True, observed_at=10, now=12)
        self.assertEqual(observed['state'], 'UNAVAILABLE')
        self.assertEqual(observed['last_error'], 'GG_FINANCIAL_HISTORY_UNAVAILABLE')
        self.assertEqual(history.observation(value, GENESIS, 'REPLICA',
            running=True, observed_at=10, now=16)['state'], 'UNAVAILABLE')

    def test_json_boundary_rechecks_genesis_role_schema_and_never_upgrades_stale(self):
        value = history.observation(report(), GENESIS, 'REPLICA', running=True, observed_at=10, now=12)
        self.assertEqual(history.normalize_observation(value, GENESIS, 'REPLICA', running=True, now=12), value)
        for field, replacement in (('schema', 'FOREIGN'), ('is_sdk_certificate', True), ('last_error', 'GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE'), ('observed_at', 10**1000), ('report', {**report(), 'genesis_hash': 'f' * 64})):
            with self.subTest(field=field):
                changed = deepcopy(value); changed[field] = replacement
                checked = history.normalize_observation(changed, GENESIS, 'REPLICA', running=True, now=12)
                self.assertEqual(checked['state'], 'UNAVAILABLE')
                self.assertIsNone(checked['report'])
        light = history.normalize_observation(value, GENESIS, 'LIGHT', running=True, now=12)
        self.assertEqual(light['state'], 'NOT_APPLICABLE')
        self.assertIsNone(light['report'])
        value['state'] = 'STALE'
        self.assertEqual(history.normalize_observation(value, GENESIS, 'REPLICA', running=True, now=12)['state'], 'STALE')
        self.assertEqual(history.normalize_observation(value, GENESIS, 'REPLICA', running=False, now=12)['state'], 'UNAVAILABLE')

    def test_owned_query_failure_clears_previous_report_and_restart_binds_exact_process(self):
        node = object.__new__(OwnedProtocolNode)
        process = object()
        node.role = 'VALIDATOR'; node.anchor = {'genesis_hash': GENESIS}
        node._node = {'process': process}; node._alive = lambda: True
        node._query = Mock(return_value=report())
        node._refresh_local_history()
        node._query.assert_called_once_with('/gg/protocol/local-history-status')
        self.assertIs(node._local_history_record[0], process)
        self.assertEqual(node._local_history_record[1]['verified_through'], '9007199254740993')
        node._query.side_effect = OSError('/private/native/path')
        node._refresh_local_history()
        self.assertEqual(node._local_history_record[1:], (None,None,True))
        def changed_process(*args):
            node._node = {'process': object()}
            return report()
        node._query.side_effect = changed_process
        node._refresh_local_history()
        self.assertEqual(node._local_history_record[1:], (None,None,True))

    def test_nonblocking_snapshot_expires_and_rejects_a_previous_process_epoch(self):
        node = object.__new__(OwnedProtocolNode)
        process = object()
        node.role = 'REPLICA'; node.anchor = {'genesis_hash': GENESIS}
        node._node = {'process': process}; node._alive = lambda: True
        node._closed=False;node._fault='';node._epoch_stopping=False;node.rpc_port=1
        node.profile=SimpleNamespace(_closed=False,_failed=False)
        node._owner_stopped=lambda:False
        node._local_history_record = (process,report(),10,False)
        with patch.object(history.time,'time',return_value=12):
            self.assertEqual(node.local_history_observation()['state'], 'READY')
        with patch.object(history.time,'time',return_value=16):
            self.assertEqual(node.local_history_observation()['state'], 'STALE')
        node._node = {'process': object()}
        with patch.object(history.time,'time',return_value=12):
            view=node.local_history_observation()
        self.assertEqual(view['state'],'UNOBSERVED')
        self.assertIsNone(view['report'])
        # A light transport process is never a local SDK, even if the old
        # native record has the same object and a valid server report.
        node.role='LIGHT';node._node={'process':process}
        with patch.object(history.time,'time',return_value=12):
            view=node.local_history_observation()
        self.assertEqual(view['state'],'NOT_APPLICABLE')
        self.assertIsNone(view['report'])

    def test_live_same_process_loses_ready_immediately_when_its_controller_or_owner_stops(self):
        node=object.__new__(OwnedProtocolNode);process=object()
        node.role='VALIDATOR';node.anchor={'genesis_hash':GENESIS};node.rpc_port=1
        node._node={'process':process};node._alive=lambda:True
        node._local_history_record=(process,report(),10,False)
        node._lock=Mock(side_effect=AssertionError('work lock must not be used'))
        for stopped in ('controller','stop_pending','owner','profile','fault','profile_pending_close'):
            with self.subTest(stopped=stopped),patch.object(history.time,'time',return_value=12):
                node._closed=stopped=='controller';node._epoch_stopping=stopped=='stop_pending'
                node._fault='GG_PROTOCOL_FAULT' if stopped=='fault' else ''
                node._owner_stopped=lambda:stopped=='owner'
                node.profile=SimpleNamespace(_closed=stopped=='profile',_failed=False,
                    _native_pipe_closing=stopped=='profile_pending_close')
                value=node.local_history_observation()
                self.assertEqual(value['state'],'UNAVAILABLE')
                self.assertIsNone(value['report'])
                self.assertIs(node._node['process'],process)


if __name__ == '__main__':
    unittest.main()
