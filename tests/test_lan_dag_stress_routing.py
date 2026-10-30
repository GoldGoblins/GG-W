"""Desktop/CLI boundaries for the explicitly opted-in DAG transaction mode."""
import ipaddress
import unittest
from unittest.mock import Mock, patch

from backend import lan_dag_runtime as runtime
from backend import gg_lan_dag as lan
from backend.terminal_cli import foreground_summary, parse_command


def fixture_peer():
    peer = Mock()
    peer.public_key = '1' * 64
    peer.allowed = ipaddress.ip_network('127.0.0.0/8')
    peer.start_pairing.return_value = {
        'body': {'peer_key': peer.public_key, 'label': 'Owned test peer',
                 'host': '127.0.0.1', 'port': 16120,
                 'producer_keys': ['2' * 64, '3' * 64],
                 'allow_dag_transactions': True},
        'signature': '4' * 128,
    }
    peer.candidate_invites.return_value = []
    peer.snapshot.return_value = {'lan': {'state': 'READY'},
                                  'dag_stress': {'state': 'IDLE'}}
    return peer


class DagStressRoutingTests(unittest.TestCase):
    def setUp(self):
        self.manager = runtime.LanDagRuntime()
        self.peer = fixture_peer()
        self.addCleanup(self.manager.stop)

    def start(self, **options):
        api = Mock()
        api.LanDagPeer.return_value = self.peer
        with patch.object(runtime, '_api', return_value=api):
            result = self.manager.start(bind_host='127.0.0.1', port=16120, **options)
        return api, result

    def test_cli_opt_in_is_typed_and_independent_of_receipt_tokens(self):
        name, args = parse_command('lan.start label=Termux allow_dag_transactions=true auto_produce=false')
        self.assertEqual(name, 'lan.start')
        self.assertIs(args['allow_dag_transactions'], True)
        self.assertIs(args['auto_produce'], False)
        self.assertNotIn('allow_test_tokens', args)
        _, args = parse_command('lan.session_create enable_dag_transactions=false')
        self.assertIs(args['enable_dag_transactions'], False)

    def test_stopped_status_advertises_opt_in_capability_without_starting_anything(self):
        with patch.object(runtime.socket, 'socket') as socket_factory, \
             patch.object(lan, 'Keypair') as key_factory:
            body = self.manager.dispatch('lan.status')
        self.assertEqual(body['lan']['state'], 'STOPPED')
        self.assertIs(body['dag_stress']['supported'], True)
        self.assertIs(body['dag_stress']['enabled'], False)
        self.assertIs(body['dag_stress']['can_start'], False)
        self.assertEqual(body['dag_stress']['limits'], lan.dag_stress_capabilities()['limits'])
        socket_factory.assert_not_called()
        key_factory.assert_not_called()

    def test_explicit_opt_in_reaches_owned_peer_and_public_setup(self):
        api, result = self.start(allow_dag_transactions=True)
        self.assertIs(api.LanDagPeer.call_args.kwargs['allow_dag_transactions'], True)
        self.assertIs(result['lan_setup']['allow_dag_transactions'], True)
        self.assertIs(result['lan_setup']['invites'][0]['allow_dag_transactions'], True)

    def test_default_does_not_silently_enable_new_protocol(self):
        api, result = self.start()
        self.assertNotIn('allow_dag_transactions', api.LanDagPeer.call_args.kwargs)
        self.assertIs(result['lan_setup']['allow_dag_transactions'], False)
        self.manager.dispatch('lan.session_create')
        self.assertNotIn('enable_dag_transactions', self.peer.create_session.call_args.kwargs)

    def test_non_boolean_opt_in_cannot_create_peer(self):
        api = Mock()
        with patch.object(runtime, '_api', return_value=api):
            for value in ('true', 1, None):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'GG_LAN_OPTION'):
                    self.manager.start(bind_host='127.0.0.1', allow_dag_transactions=value)
        api.LanDagPeer.assert_not_called()

    def test_session_creation_keeps_dag_and_receipt_modes_explicit(self):
        self.start(allow_dag_transactions=True)
        self.manager.dispatch('lan.session_create', {'enable_dag_transactions': True})
        options = self.peer.create_session.call_args.kwargs
        self.assertIs(options['enable_dag_transactions'], True)
        self.assertIs(options['enable_test_tokens'], False)

    def test_stress_targets_owned_roster_and_rejects_external_target_arguments(self):
        self.start(allow_dag_transactions=True)
        name, args = parse_command('lan.dag_stress_start duration_ms=10000 transactions_per_block=16 interval_ms=100')
        self.manager.dispatch(name, args)
        self.peer.start_dag_stress.assert_called_once_with(
            duration_ms=10000, transactions_per_block=16, interval_ms=100, remote=True)
        for invalid in ({'host': '127.0.0.9'}, {'remote': False}, {'duration_ms': 1000, 'seed': 'fixture'}):
            with self.subTest(arguments=invalid), self.assertRaisesRegex(ValueError, 'ACTION_ARGUMENTS'):
                self.manager.dispatch('lan.dag_stress_start', invalid)
        self.assertEqual(self.peer.start_dag_stress.call_count, 1)
        self.manager.dispatch('lan.dag_stress_stop')
        self.peer.stop_dag_stress.assert_called_once_with()
        self.peer.stop.assert_not_called()

    def test_foreground_reports_dag_work_without_converting_receipts_to_dag_tx(self):
        summary = foreground_summary('lan.start', {
            'lan': {'state': 'READY', 'transactions_enabled': True}, 'blocks_admitted': 8, 'transactions_validated': 128,
            'test_tokens': {'sequence': 999},
            'dag_stress': {'enabled': True, 'state': 'RUNNING', 'blocks': 8,
                           'transactions': 128, 'all_peers_synced': False,
                           'acknowledged_tps': None, 'block_set_digest': 'public fixture'},
        })
        self.assertEqual(summary['proposals'], 8)
        self.assertEqual(summary['validated_dag_transactions'], 128)
        self.assertIs(summary['dag_test_transactions_enabled'], True)
        self.assertIs(summary['dag_stress']['acknowledged_tps'], None)
        self.assertNotIn('block_set_digest', summary['dag_stress'])
        self.assertIs(summary['physical_hosts_verified'], False)
        self.assertIs(summary['transactions_enabled'], True)
        self.assertIs(summary['financial_transactions_enabled'], False)


if __name__ == '__main__':
    unittest.main()
