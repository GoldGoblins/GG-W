"""Roster-bound node names and expiring authenticated contact observations."""
from copy import deepcopy
import unittest
from unittest.mock import Mock,patch

from backend import gg_lan_dag as lan


class NodeIdentityTests(unittest.TestCase):
    def peer(self):
        peer=lan.LanDagPeer('Windows',allow_dag_transactions=True)
        self.addCleanup(peer.stop)
        peer._roster={peer.public_key:{'label':'Windows','producer_indices':[2,3]},
                      'a'*64:{'label':'Linux','producer_indices':[4,5]},
                      'b'*64:{'label':'Termux','producer_indices':[0,1]}}
        return peer

    def test_identity_is_bound_to_roster_indices_on_each_machine(self):
        peer=self.peer();rows=peer._producer_identities()
        self.assertEqual([r['display_name'] for r in rows],
                         ['Termux · 1','Termux · 2','Windows · 1','Windows · 2','Linux · 1','Linux · 2'])
        self.assertEqual([r['index'] for r in rows if r['local']],[2,3])
        self.assertTrue(all(r['identity_basis']=='SIGNED_SESSION_ROSTER' for r in rows))

    def test_authentication_history_expires_and_wall_clock_changes_do_not_refresh_contact(self):
        peer=self.peer()
        with patch.object(lan.time,'monotonic',return_value=100):peer._mark_seen('a'*64)
        with patch.object(lan.time,'monotonic',return_value=101):
            row=next(r for r in peer._peer_observations() if r['label']=='Linux')
            self.assertEqual(row['state'],'CONNECTED');self.assertTrue(row['authenticated_recently'])
        with patch.object(lan.time,'monotonic',return_value=116),patch.object(lan.time,'time',return_value=0):
            row=next(r for r in peer._peer_observations() if r['label']=='Linux')
            self.assertEqual(row['state'],'STALE');self.assertFalse(row['authenticated_recently'])
        with patch.object(lan.time,'monotonic',return_value=146):
            row=next(r for r in peer._peer_observations() if r['label']=='Linux')
            self.assertEqual(row['state'],'DISCONNECTED')

    def test_failed_exchange_is_degraded_until_a_later_verified_success(self):
        peer=self.peer()
        with patch.object(lan.time,'monotonic',return_value=100):peer._mark_seen('a'*64)
        with patch.object(lan.time,'monotonic',return_value=101):
            peer._error(ConnectionRefusedError(),'PAGE','CONNECT','a'*64)
            self.assertEqual(peer._peer_observations()[0]['state'],'DEGRADED')
        with patch.object(lan.time,'monotonic',return_value=102):
            peer._mark_seen('a'*64)
            self.assertEqual(peer._peer_observations()[0]['state'],'CONNECTED')
            self.assertEqual(peer._peer_observations()[0]['last_error'],'')
        self.assertEqual(peer._transport_counts['failures'],1)

    def test_expected_stop_and_unverified_auth_failures_do_not_forge_contact(self):
        peer=self.peer();peer._error(ValueError('GG_LAN_HANDSHAKE'),'INCOMING','AUTH')
        self.assertTrue(all(r['state']=='UNOBSERVED' for r in peer._peer_observations()))
        self.assertFalse(peer._seen_monotonic)

    def test_exhausted_transport_never_claims_a_working_connection(self):
        peer=self.peer();peer._mark_seen('a'*64);peer._transport_exhausted='SESSION'
        result=peer.snapshot()['lan']
        self.assertEqual(result['connection_state'],'EXHAUSTED')
        self.assertEqual(result['authenticated_peers'],[])
        self.assertTrue(all(r['state']=='EXHAUSTED' and not r['authenticated_recently'] for r in result['peer_status']))

    def test_snapshot_annotates_actual_graph_and_producer_statistics_without_recounting(self):
        peer=self.peer()
        state={'state':'RUNNING','producers':[{'index':4,'proposals':7,'transactions':56}],
               'blocks_admitted':7,'transactions_validated':56,
               'block_graph':{'blocks':[{'proposer_index':4,'state':'ADMITTED_UNFINALIZED','transaction_count':8},
                                        {'proposer_index':-1,'state':'GENESIS'}]}}
        engine=Mock();engine.stored_wire_bytes.return_value=0
        engine.snapshot.side_effect=lambda:deepcopy(state);peer._engine=engine
        self.addCleanup(setattr,peer,'_engine',None)
        peer._dag_enabled=False
        result=peer.snapshot()
        self.assertEqual(result['producers'][0]['display_name'],'Linux · 1')
        self.assertEqual(result['producers'][0]['transactions'],56)
        self.assertEqual(result['block_graph']['blocks'][0]['node_label'],'Linux')
        self.assertNotIn('node_label',result['block_graph']['blocks'][1])
        self.assertEqual(result['lan']['verified_dag_transactions'],56)
        self.assertEqual(result['lan']['connection_state'],'DISCONNECTED')
        peer._engine=None


if __name__=='__main__':unittest.main()
