"""Exact test-token commands through three owned loopback managers, no GUI."""
import time
import unittest
from backend.lan_dag_runtime import LanDagRuntime
from backend.terminal_cli import parse_command


class LanTokenRuntimeTests(unittest.TestCase):
    def test_cli_keeps_exact_amounts_and_explicit_boolean_opt_in(self):
        command,args=parse_command('lan.start port=16120 allow_test_tokens=true')
        self.assertEqual(command,'lan.start')
        self.assertEqual(args,{'port':16120,'allow_test_tokens':True})
        command,args=parse_command('lan.circle_start duration_ms=10000 batch=16 amount_atomic=1000000')
        self.assertEqual(command,'lan.circle_start')
        self.assertEqual(args,{'duration_ms':10000,'batch':16,'amount_atomic':'1000000'})

    def test_three_managers_route_real_signed_transfers_and_converge(self):
        peers=[LanDagRuntime() for _ in range(3)]
        for peer in peers:self.addCleanup(peer.stop)
        coordinator=peers[0]
        coordinator.dispatch('lan.start',{'label':'Windows fixture','bind_host':'127.0.0.1','port':0,
            'auto_produce':False,'allow_test_tokens':True})
        bootstrap=coordinator.dispatch('lan.bootstrap')
        for index,peer in enumerate(peers[1:],1):
            peer.dispatch('lan.start',{'label':'Peer '+str(index),'bind_host':'127.0.0.1','port':0,
                'auto_produce':False,'allow_test_tokens':True,'bootstrap':bootstrap})
        installed=coordinator.dispatch('lan.session_create',{'distribute':True,'enable_test_tokens':True})
        self.assertTrue(installed['test_tokens']['enabled'])
        keys=[peer.snapshot()['lan']['public_key'] for peer in peers]
        for index,peer in enumerate(peers):
            peer.dispatch('lan.token_send',{'recipient_peer_key':keys[(index+1)%3],'amount_atomic':'1000000'})
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            states=[peer.snapshot() for peer in peers]
            if all(state['test_tokens']['sequence']==3 for state in states):break
            time.sleep(.015)
        self.assertTrue(all(state['test_tokens']['sequence']==3 for state in states))
        self.assertEqual(len({state['test_tokens']['head'] for state in states}),1)
        self.assertEqual(len({state['test_tokens']['state_root'] for state in states}),1)
        for state in states:
            self.assertFalse(state['lan']['physical_hosts_verified'])
            self.assertEqual(state['canonical_finalized'],0)
            self.assertFalse(state['lan']['transactions_enabled'])
            self.assertEqual({row['nonce'] for row in state['test_tokens']['accounts']},{1})
            self.assertEqual({row['balance_atomic'] for row in state['test_tokens']['accounts']},{'1000000000'})


if __name__=='__main__':unittest.main()
