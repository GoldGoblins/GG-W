"""Light is a signed, nonvoting role with no payload gossip or admission work."""
import unittest
from unittest.mock import patch
from backend.gg_lan_dag import LanDagPeer,validate_invite
from backend.gg_consensus_membership import anchor_from_owned_peer,make_invite
from backend.gg_ed25519 import Keypair
from tests.test_lan_consensus_anchor import member_invites


class LightRoleTests(unittest.TestCase):
    def peers(self):
        peers=[LanDagPeer(label,allow_dag_transactions=True,node_role=role) for label,role in
               (('Windows','producer'),('Linux','producer'),('Termux','light'))]
        for peer in peers:self.addCleanup(peer.stop);peer.start_pairing()
        for peer in peers[1:]:peer.pin_coordinator(peers[0].public_key)
        return peers

    def test_light_requires_explicit_dag_consensus_and_starts_no_payload_gossip(self):
        for options in ({'node_role':'light'},{'node_role':'light','allow_dag_transactions':True,'auto_produce':True},
                        {'node_role':'light','allow_dag_transactions':True,'allow_test_tokens':True}):
            with self.assertRaises(ValueError):LanDagPeer('Invalid',**options)
        peers=self.peers();light=peers[2]
        self.assertEqual(validate_invite(light.public_invite())['schema'],'gg.lan-dag.invite.v6')
        with self.assertRaisesRegex(ValueError,'LIGHT_REQUIRES_DAG_CONSENSUS'):
            peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True)
        bundle=peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=member_invites(peers))
        for peer in peers:peer.install_session(bundle,_start_gossip=False)
        with patch.object(light,'_gossip_loop',side_effect=AssertionError('global payload download')):light._start_gossip()
        self.assertIsNone(light._gossip);self.assertEqual(light._local_indices,[])
        self.assertEqual(len(light._engine._records),1)
        participation=light.snapshot()['lan']['participation']
        self.assertTrue(participation['light_client']);self.assertFalse(participation['replica']);self.assertFalse(participation['producer'])
        self.assertFalse(participation['consensus_validator'])
        self.assertEqual(len(anchor_from_owned_peer(light)['genesis']['dag']['allowed_producers']),4)
        with self.assertRaisesRegex(ValueError,'READ_ONLY'):light.start_producing()

    def test_coordinator_cannot_register_a_light_owner_as_a_mandatory_validator(self):
        peers=self.peers();invites=member_invites(peers);light=peers[2]
        invites[0]=make_invite(Keypair(),Keypair(),Keypair(),light._identity,label='Forbidden voter',host=light.host,p2p_port=23001,nonce='a'*64)
        with self.assertRaisesRegex(ValueError,'MEMBERSHIP_INVALID'):
            peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=invites)


if __name__=='__main__':unittest.main()
