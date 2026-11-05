"""One signed LAN bootstrap deterministically pins one explicit committee."""
from copy import deepcopy
import hashlib
import unittest

from backend import gg_consensus_membership as member,gg_consensus_web as web
from backend.gg_ed25519 import Keypair
from backend.gg_lan_dag import LanDagPeer,_signed,_BUNDLE
from backend.gg_parallel_dag import pack


def paired_peers(test):
    peers=[]
    for label,role in (('Windows','producer'),('Linux','producer'),('Termux','replica')):
        peer=LanDagPeer(label,allow_dag_transactions=True,node_role=role)
        peers.append(peer);test.addCleanup(peer.stop);peer.start_pairing()
    for peer in peers[1:]:peer.pin_coordinator(peers[0].public_key)
    return peers


def member_invites(peers):
    invites=[]
    for index in range(4):
        owner=peers[index%2]
        keys=[Keypair() for _ in range(3)]
        invites.append(member.make_invite(*keys,owner._identity,label='Göteborg · nod '+str(index),host=owner.host,
            p2p_port=21001+index,nonce=hashlib.sha256(('public invite '+str(index)).encode()).hexdigest()))
    return invites


class LanConsensusAnchorTests(unittest.TestCase):
    def test_every_peer_derives_same_anchor_and_keeps_replica_out_of_voting(self):
        peers=paired_peers(self);invites=member_invites(peers)
        bundle=peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=invites)
        for peer in peers:peer.install_session(bundle,_start_gossip=False)
        anchors=[member.anchor_from_owned_peer(peer) for peer in peers]
        self.assertTrue(all(anchor==anchors[0] for anchor in anchors))
        self.assertEqual(bundle['body']['schema'],'gg.lan-dag.session.v4')
        genesis=anchors[0]['genesis']
        self.assertEqual(anchors[0]['genesis_hash'],hashlib.sha256(pack(genesis)).hexdigest())
        self.assertEqual(genesis['schema'],'gg.native.genesis.v3')
        self.assertEqual(len(genesis['dag']['allowed_producers']),4)
        self.assertNotIn(peers[2].public_key,{invite['body']['owner_peer_key'] for invite in genesis['membership']['validators']})
        self.assertEqual(web._pin(anchors[0]),anchors[0])
        self.assertTrue(member.public_label(genesis['membership']['validators'][0]['body']).startswith('Göteborg'))
        # An authenticated coordinator can propose a NEW session, but cannot
        # replace an already installed network/anchor in an existing owner.
        replacement=peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=invites)
        with self.assertRaisesRegex(ValueError,'NETWORK_ALREADY_BOUND'):peers[1].install_session(replacement,_start_gossip=False)
        self.assertEqual(member.anchor_from_owned_peer(peers[1]),anchors[0])

    def test_each_key_role_must_prove_possession_and_domain(self):
        peers=paired_peers(self);invite=member_invites(peers)[0]
        for role in ('validator','node','account','owner'):
            with self.subTest(role=role):
                changed=deepcopy(invite);changed[role+'_signature']='0'*128
                with self.assertRaisesRegex(ValueError,'MEMBER_INVITE'):member.validate_invite(changed)
        changed=deepcopy(invite);changed['body']['nonce']='f'*64
        with self.assertRaisesRegex(ValueError,'MEMBER_INVITE'):member.validate_invite(changed)

    def test_unregistered_owner_mismatched_endpoint_duplicate_member_and_public_host_rejected(self):
        peers=paired_peers(self);invites=member_invites(peers)
        for case in ('unregistered','endpoint','duplicate'):
            with self.subTest(case=case):
                changed=deepcopy(invites)
                if case=='duplicate':changed[1]=deepcopy(changed[0])
                else:
                    owner=Keypair() if case=='unregistered' else peers[0]._identity
                    changed[0]=member.make_invite(Keypair(),Keypair(),Keypair(),owner,label='Changed',host='10.1.2.3' if case=='endpoint' else peers[0].host,
                        p2p_port=21001,nonce='a'*64)
                with self.assertRaisesRegex(ValueError,'MEMBERSHIP_INVALID'):
                    peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=changed)
        with self.assertRaisesRegex(ValueError,'MEMBER_ENDPOINT'):
            member.make_invite(Keypair(),Keypair(),Keypair(),peers[0]._identity,label='Public',host='8.8.8.8',p2p_port=21001,nonce='a'*64)

    def test_member_tampering_is_rejected_even_when_coordinator_resigns(self):
        peers=paired_peers(self)
        bundle=peers[0].create_session([peer.public_invite() for peer in peers],enable_dag_transactions=True,consensus_invites=member_invites(peers))
        for case in ('signature','account','schema','producer'):
            with self.subTest(case=case):
                body=deepcopy(bundle['body'])
                if case=='signature':body['consensus']['validators'][0]['owner_signature']='0'*128
                elif case=='account':body['consensus']['validators'][0]['body']['account_key']=Keypair().pubkey().hex()
                elif case=='schema':body['consensus']['scope']='MAINNET'
                else:body['roster'][0]['producer_indices']=[False,1]
                changed=_signed(peers[0]._identity,_BUNDLE,body)
                with self.assertRaises(ValueError):member.anchor_from_bundle(changed,peers[0].public_key)
                with self.assertRaises(ValueError):peers[1].install_session(changed,_start_gossip=False)
                self.assertIsNone(peers[1]._engine)


if __name__=='__main__':unittest.main()
