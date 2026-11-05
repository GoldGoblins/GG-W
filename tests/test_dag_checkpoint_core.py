"""Source policy is taken from the actual installed LAN, not visual labels."""
from copy import deepcopy
import time
import unittest
from unittest.mock import patch

from backend import gg_dag_checkpoint as core,gg_consensus as native,gg_consensus_web as web
from backend.gg_ed25519 import Keypair,SIGNATURE_PROFILE
from backend.gg_parallel_dag import make_public_genesis,digest
from backend.gg_lan_dag import LanDagPeer


def public_source():
    public=make_public_genesis([Keypair().pubkey().hex() for _ in range(6)],enable_dag_transactions=True)
    return {'schema':core.SOURCE_SCHEMA,'signature_profile':SIGNATURE_PROFILE,'network_id':'b'*64,
        'accounts':public['accounts'],'allowed_producers':list(range(6)),'genesis':public['genesis'],
        'genesis_hash':public['genesis_hash'],'started_at_ns':str(public['started_at_ns'])}


class PublicDagSourceTests(unittest.TestCase):
    def test_strict_public_policy_rejects_ambiguous_roles_roots_and_time(self):
        original=public_source()
        for case in ('bool_role','duplicate_role','unknown_role','null_roles','root','time_float','time_number','overflow','schema','unknown'):
            with self.subTest(case=case):
                source=deepcopy(original)
                if case=='bool_role':source['allowed_producers']=[False,1]
                elif case=='duplicate_role':source['allowed_producers']=[0,0]
                elif case=='unknown_role':source['allowed_producers']=[6]
                elif case=='null_roles':source['allowed_producers']=None
                elif case=='root':
                    source['genesis']['precheck_root']='0'*64
                    source['genesis_hash']=digest(source['genesis'])
                elif case=='time_float':source['started_at_ns']='1700000000.0'
                elif case=='time_number':source['started_at_ns']=int(source['started_at_ns'])
                elif case=='overflow':source['started_at_ns']=str(2**63)
                elif case=='schema':source['genesis']['schema']='gg.parallel-dag.genesis.v1'
                elif case=='unknown':source['validators']=[]
                with self.assertRaisesRegex(ValueError,'SOURCE_INVALID'):core.validate_source(source)
        copied=core.validate_source(original)
        copied['allowed_producers'].clear()
        self.assertEqual(len(original['allowed_producers']),6)

    def test_empty_producer_policy_remains_empty_and_owned_by_result(self):
        source=public_source();source['allowed_producers']=[]
        self.assertEqual(core.validate_source(source)['allowed_producers'],[])

    def test_v2_light_pin_binds_source_and_preserves_large_nanosecond_string(self):
        source=public_source()
        genesis={'schema':'gg.native.genesis.v2','chain_id':'ggnet:'+'c'*24,'dag':source,'decimals':6,
            'genesis_time_unix':int(time.time()),'supply_atomic':'1000000000000','symbol':'GG-NET-TEST',
            'accounts':[Keypair().pubkey().hex() for _ in range(4)],'validators':[Keypair().pubkey().hex() for _ in range(4)]}
        trust={'genesis':genesis,'genesis_hash':native._digest(genesis)}
        self.assertEqual(web._pin(trust),trust)
        self.assertGreater(int(web._pin(trust)['genesis']['dag']['started_at_ns']),2**53)
        for case in ('source_role','shared_validator','future_time'):
            with self.subTest(case=case):
                changed=deepcopy(trust)
                if case=='source_role':changed['genesis']['dag']['allowed_producers']=[True]
                elif case=='shared_validator':changed['genesis']['validators'][0]=source['genesis']['producers'][0]
                else:changed['genesis']['dag']['started_at_ns']=str((genesis['genesis_time_unix']+6)*10**9)
                changed['genesis_hash']=native._digest(changed['genesis'])
                with self.assertRaisesRegex(ValueError,'TRUST_INVALID'):web._pin(changed)

    def test_an_active_committee_cannot_silently_change_its_dag_source(self):
        source=public_source()
        with patch.object(native,'_genesis',{'dag':source}),patch.object(native,'_closed',False),patch.object(native,'_launch') as launch:
            changed=deepcopy(source);changed['network_id']='d'*64
            with self.assertRaisesRegex(ValueError,'ALREADY_BOUND'):native.start(dag_source=changed)
            launch.assert_not_called()


class OwnedLanSourceTests(unittest.TestCase):
    def test_source_uses_signed_roster_and_excludes_full_replica_slots(self):
        peers=[]
        try:
            for index,role in enumerate(('producer','producer','replica')):
                peer=LanDagPeer(('Windows','Linux','Termux')[index],allow_dag_transactions=True,node_role=role)
                peers.append(peer);peer.start_pairing()
            coordinator=peers[0]
            for peer in peers:peer.pin_coordinator(coordinator.public_key)
            bundle=coordinator.create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True)
            for peer in peers:peer.install_session(bundle,_start_gossip=False)
            sources=[core.source_from_owned_peer(peer) for peer in peers]
            self.assertTrue(all(source==sources[0] for source in sources))
            self.assertEqual(len(sources[0]['allowed_producers']),4)
            reserved=peers[2]._roster[peers[2].public_key]['producer_indices']
            self.assertTrue(set(reserved).isdisjoint(sources[0]['allowed_producers']))
            self.assertEqual(sources[0]['network_id'],peers[0]._network)
            peers[0]._bundle['body']['label']='changed after signed installation'
            with self.assertRaisesRegex(ValueError,'SESSION_CHANGED'):core.source_from_owned_peer(peers[0])
        finally:
            for peer in reversed(peers):peer.stop()

    def test_uninstalled_or_unowned_state_cannot_supply_a_consensus_source(self):
        with self.assertRaisesRegex(ValueError,'OWNED_PEER_REQUIRED'):core.source_from_owned_peer({})
        peer=LanDagPeer('Uninstalled',allow_dag_transactions=True)
        try:
            with self.assertRaisesRegex(ValueError,'ACTIVE_SESSION_REQUIRED'):core.source_from_owned_peer(peer)
        finally:peer.stop()


if __name__=='__main__':unittest.main()
