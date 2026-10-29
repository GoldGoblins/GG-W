"""Small headless public-bootstrap and owned LAN-manager checks.

Only the final fixture binds three loopback listeners; it starts no producer.
No physical interface, GUI, wallet material or external service is used.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from backend import gg_lan_dag as lan
from backend import lan_dag_runtime as runtime


def public_invite():
    identity=lan.Keypair()
    body={'schema':'gg.lan-dag.invite.v1','label':'public fixture',
          'host':'127.0.0.1','port':16120,'peer_key':identity.pubkey().hex(),
          'producer_keys':[lan.Keypair().pubkey().hex() for _ in range(2)],
          'nonce':'a'*64}
    return lan._signed(identity,lan._INVITE,body)


def public_bootstrap():
    return {'schema':runtime.BOOTSTRAP_SCHEMA,
            'coordinator_invite':public_invite(),'allowed_cidr':'127.0.0.0/8'}


class LanDagRuntimeTests(unittest.TestCase):
    def test_construction_status_and_unknown_arguments_do_not_make_keys_or_io(self):
        with patch.object(runtime.socket,'socket') as socket_factory, \
             patch.object(lan,'Keypair') as key_factory:
            manager=runtime.LanDagRuntime()
            state=manager.dispatch('lan.status')
            self.assertFalse(manager.active)
            self.assertEqual(state['lan']['state'],'STOPPED')
            self.assertFalse(state['lan']['physical_hosts_verified'])
            self.assertFalse(state['lan']['transactions_enabled'])
            self.assertEqual(state['canonical_finalized'],0)
            with self.assertRaisesRegex(ValueError,'ACTION_ARGUMENTS'):
                manager.dispatch('lan.start',{'private_key':'unused fixture'})
            with self.assertRaisesRegex(ValueError,'ACTION_ARGUMENTS'):
                manager.dispatch('lan.status',{'host':'127.0.0.1'})
            socket_factory.assert_not_called();key_factory.assert_not_called()

    def test_auto_address_uses_only_kernel_route_selection_and_rejects_public_host(self):
        route=('192.168.9.2',16120)
        for target in (None,route):
            with self.subTest(target=target):
                probe=MagicMock();probe.__enter__.return_value=probe
                probe.getsockname.return_value=('192.168.9.4',49152)
                with patch.object(runtime.socket,'socket',return_value=probe):
                    self.assertEqual(runtime.auto_bind_host(target),'192.168.9.4')
                probe.connect.assert_called_once_with(target or ('192.0.2.1',9))
                probe.send.assert_not_called();probe.sendall.assert_not_called();probe.sendto.assert_not_called()
        probe.getsockname.return_value=('203.0.113.4',49152)
        with patch.object(runtime.socket,'socket',return_value=probe):
            with self.assertRaisesRegex(ValueError,'AUTO_ADDRESS_UNAVAILABLE'):
                runtime.auto_bind_host()

    def test_bootstrap_requires_exact_public_schema_signature_and_matching_subnet(self):
        value=public_bootstrap()
        self.assertEqual(runtime.validate_bootstrap(value),value)
        variants=[]
        extra=deepcopy(value);extra['seed']='unused fixture';variants.append(extra)
        changed=deepcopy(value);changed['coordinator_invite']['body']['label']='changed';variants.append(changed)
        for cidr in ('0.0.0.0/0','203.0.113.0/24','192.168.9.0/24','::1/128'):
            changed=deepcopy(value);changed['allowed_cidr']=cidr;variants.append(changed)
        oversized=deepcopy(value);oversized['padding']='x'*runtime.MAX_BOOTSTRAP;variants.append(oversized)
        for candidate in variants:
            with self.subTest(fields=tuple(candidate)):
                with self.assertRaises(ValueError):runtime.validate_bootstrap(candidate)

    def test_public_file_exports_roundtrip_and_never_overwrite_existing_file(self):
        bootstrap=public_bootstrap()
        with tempfile.TemporaryDirectory(prefix='gg-lan-public-test-') as directory:
            for kind,value in (('bootstrap',bootstrap),('invite',bootstrap['coordinator_invite'])):
                path=Path(directory)/(kind+'.json')
                result=runtime.write_public_document(str(path),value,kind)
                original=path.read_bytes()
                self.assertTrue(result['public_only'])
                self.assertFalse(result['ephemeral_private_keys_exported'])
                self.assertEqual(json.loads(original),value)
                self.assertEqual(runtime.read_public_document(path.as_uri(),kind),value)
                with self.assertRaisesRegex(ValueError,'FILE_EXISTS'):
                    runtime.write_public_document(str(path),value,kind)
                self.assertEqual(path.read_bytes(),original)
            large=Path(directory)/'oversized.json'
            large.write_bytes(b' '* (runtime.MAX_BOOTSTRAP+1))
            with self.assertRaisesRegex(ValueError,'DOCUMENT_SIZE'):
                runtime.read_public_document(str(large),'bootstrap')
        for path in ('file://remote/share/invite.json',r'\\server\share\invite.json',
                     'file:///tmp/invite.json?query=yes','file:///tmp/invite.json#fragment'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError,'FILE_PATH'):runtime._local_path(path)

    def test_stop_signal_bypasses_manager_control_lock(self):
        manager=runtime.LanDagRuntime();peer=Mock()
        manager._peer=peer
        entered=threading.Event();release=threading.Event()
        def hold():
            with manager._control:entered.set();release.wait(2)
        holder=threading.Thread(target=hold);holder.start()
        try:
            self.assertTrue(entered.wait(1))
            began=time.monotonic();manager.request_stop();elapsed=time.monotonic()-began
            self.assertLess(elapsed,.1)
            self.assertTrue(manager._stop_requested.is_set())
            peer.request_stop.assert_called_once_with()
        finally:
            release.set();holder.join(1)
        self.assertFalse(holder.is_alive())

    def test_bootstrap_mismatch_is_rejected_before_listener_creation(self):
        bootstrap=public_bootstrap()
        manager=runtime.LanDagRuntime()
        with patch.object(runtime.socket,'socket') as socket_factory, \
             patch.object(lan,'Keypair') as key_factory:
            with self.assertRaisesRegex(ValueError,'COORDINATOR_MISMATCH'):
                manager.start(bootstrap=bootstrap,trusted_coordinator='b'*64,bind_host='127.0.0.1')
            with self.assertRaisesRegex(ValueError,'BOOTSTRAP_SUBNET'):
                manager.start(bootstrap=bootstrap,allowed_cidr='192.168.9.0/24',bind_host='127.0.0.1')
            socket_factory.assert_not_called();key_factory.assert_not_called()
        self.assertFalse(manager.active)
        self.assertFalse(manager.snapshot()['lan_setup']['starting'])

    def test_bootstrap_join_defaults_to_paused_producers_and_honors_explicit_opt_in_without_io(self):
        coordinator={'peer_key':'b'*64,'host':'127.0.0.1','port':16120}
        bootstrap={'schema':runtime.BOOTSTRAP_SCHEMA,'coordinator_invite':{'body':coordinator},
                   'allowed_cidr':'127.0.0.0/8'}
        own={'body':{'peer_key':'a'*64,'label':'mock joiner','host':'127.0.0.1','port':16121,
                     'producer_keys':['c'*64,'d'*64]}}
        for override,expected in (({},False),({'auto_produce':True},True)):
            with self.subTest(override=override):
                peer=Mock(spec_set=['public_key','allowed','start_pairing','announce_invite','snapshot'])
                peer.public_key=own['body']['peer_key'];peer.allowed=runtime._cidr('127.0.0.0/8')
                peer.start_pairing.return_value=own
                peer.snapshot.side_effect=lambda:{'lan':{'state':'PAIRING'}}
                api=Mock(spec_set=['validate_invite','LanDagPeer'])
                api.validate_invite.return_value=coordinator;api.LanDagPeer.return_value=peer
                with patch.object(runtime,'_api',return_value=api), \
                     patch.object(runtime.socket,'socket',side_effect=AssertionError('No socket expected')) as socket_factory, \
                     patch.object(lan,'Keypair',side_effect=AssertionError('No key creation expected')) as key_factory:
                    manager=runtime.LanDagRuntime()
                    joined=manager.start(label='mock joiner',bind_host='127.0.0.1',port=16121,
                                         bootstrap=bootstrap,**override)
                api.LanDagPeer.assert_called_once_with('mock joiner','127.0.0.1',16121,'b'*64,expected,
                    allowed_cidr='127.0.0.0/8',allow_test_tokens=False)
                self.assertIs(joined['lan_setup']['auto_produce'],expected)
                peer.start_pairing.assert_called_once_with()
                peer.announce_invite.assert_called_once_with(bootstrap['coordinator_invite'])
                socket_factory.assert_not_called();key_factory.assert_not_called()

    def test_three_loopback_managers_return_candidates_before_explicit_session(self):
        managers=[runtime.LanDagRuntime() for _ in range(3)]
        for manager in managers:self.addCleanup(manager.stop)
        coordinator=managers[0]
        started=coordinator.start(label='manager coordinator',bind_host='127.0.0.1',port=0,auto_produce=False)
        self.assertFalse(started['lan_setup']['starting'])
        bootstrap=coordinator.dispatch('lan.bootstrap')
        for index,manager in enumerate(managers[1:],1):
            joined=manager.start(label='manager peer '+str(index),bind_host='127.0.0.1',port=0,
                                 bootstrap=bootstrap,auto_produce=False)
            self.assertEqual(joined['lan_setup']['announcement_error'],'')
            self.assertEqual(joined['lan']['state'],'PAIRING')
        paired=coordinator.snapshot()
        self.assertEqual(paired['lan_setup']['invite_count'],3)
        self.assertFalse(paired['lan_setup']['bundle_available'])
        self.assertEqual(paired['lan']['configured_peers'],0)
        installed=coordinator.dispatch('lan.session_create',{'distribute':True})
        self.assertEqual([row['state'] for row in installed['lan_setup']['distribution']],['READY','READY'])
        for manager in managers:
            body=manager.snapshot()
            self.assertEqual(body['lan']['state'],'READY')
            self.assertEqual(body['producer_count'],6)
            self.assertEqual(body['worker_count'],0)
            self.assertEqual(body['blocks_admitted'],0)
            self.assertEqual(body['canonical_finalized'],0)
            self.assertFalse(body['lan']['physical_hosts_verified'])
            self.assertFalse(body['lan']['transactions_enabled'])
            self.assertEqual(sum(key is not None for key in manager._peer._engine._producer_keys),2)
            self.assertEqual(manager._peer._engine._account_keys,{})
        for manager in managers:
            stopped=manager.stop()
            self.assertEqual(stopped['lan']['state'],'STOPPED')
            self.assertFalse(manager.active)


if __name__=='__main__':unittest.main()
