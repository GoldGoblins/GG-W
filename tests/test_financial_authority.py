"""Real protected profiles and pairing; constructor policy, no SDK process claim.

The binary freshness seam is mocked only for controllers that never start.
Actual owned native processes and financial certificates run separately.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_node_store as nodes,gg_consensus_profile as validators,gg_consensus as native,portable_wallet_vault as vault
from backend import gg_financial_authority as authority,gg_financial_session as session
from backend.gg_lan_dag import LanDagPeer
from backend.gg_consensus_membership import make_membership


def protected_financial_network(*,roles=('producer','producer','replica'),source_schema='gg.financial-dag.source.v2',financial_accounts=None):
    owners=[];peers=[];profiles=[];reserved=[]
    try:
        for index,role in enumerate(roles):
            profile=nodes.NodeProfile.create('FinancialOwner'+str(index),{'label':('Windows','Linux','Termux')[index],
                'host':'127.0.0.1','port':0,'allowed_cidr':'127.0.0.0/8','trusted_coordinator':None,
                'allow_test_tokens':False,'allow_dag_transactions':True,'node_role':role})
            owners.append(profile);peer=LanDagPeer(profile.descriptor()['label'],node_profile=profile,node_role=role,allow_dag_transactions=True)
            peers.append(peer);peer.start_pairing()
        for peer in peers[1:]:peer.pin_coordinator(peers[0].public_key)
        for index in range(4):
            reserve=socket.socket();reserve.bind(('127.0.0.1',0));reserved.append(reserve)
            profiles.append(validators.ValidatorProfile.create('FinancialValidator'+str(index),peers[index%2],
                label='Protected financial validator '+str(index),p2p_port=reserve.getsockname()[1]))
        invites=[peer.public_invite() for peer in peers];bodies=[invite['body'] for invite in invites]
        membership=make_membership([profile.public_invite() for profile in profiles],owners={row['peer_key']:row for row in bodies},
            forbidden_keys=[key for row in bodies for key in (row['peer_key'],*row['producer_keys'])])
        bundle=session.make_bundle(peers[0]._identity,invites,membership,label='Protected signed financial session',network_nonce=hashlib.sha256(b'public financial authority fixture').hexdigest(),source_schema=source_schema,financial_accounts=financial_accounts)
        contexts=[authority.OwnedFinancialSession(profile,bundle) for profile in owners]
        for profile in profiles:profile.bind_anchor(bundle,peers[0].public_key)
        return owners,peers,profiles,bundle,contexts
    except BaseException:
        for profile in profiles:profile.close()
        for peer in peers:peer.stop()
        for profile in owners:profile.close()
        raise
    finally:
        for reserve in reserved:reserve.close()


class FinancialAuthorityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-financial-authority-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('public financial authority test vault'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.owners,self.peers,self.profiles,self.bundle,self.contexts=protected_financial_network();self.controllers=[];self.addCleanup(self.cleanup)
        self.binary=Path(self.temp.name)/'never-executed-binary-seam';self.binary.write_bytes(b'public constructor seam')
        self.stack.enter_context(patch.object(native,'_installed_binary',return_value=self.binary))
        self.stack.enter_context(patch.object(native,'_validate_binary_at',return_value=(self.binary.stat().st_size,self.binary.stat().st_mtime_ns)))

    def cleanup(self):
        for controller in self.controllers:controller.close()
        for profile in self.profiles:profile.close()
        for peer in self.peers:peer.stop()
        for owner in self.owners:owner.close()

    def context_for(self,profile):
        key=profile.public_invite()['body']['owner_peer_key']
        return next(context for context in self.contexts if context.public_key==key)

    def controller(self,index=0):
        profile=self.profiles[index];controller=authority.OwnedFinancialAuthority(profile,self.context_for(profile));self.controllers.append(controller);return controller

    def test_real_owner_and_validator_profiles_bind_only_financial_signed_source(self):
        controller=self.controller();snapshot=controller.snapshot()
        self.assertTrue(all(peer._engine is None for peer in self.peers))
        self.assertEqual(controller.anchor,self.context_for(self.profiles[0]).anchor())
        self.assertEqual(controller.anchor['genesis']['financial_dag']['schema'],'gg.financial-dag.source.v2')
        self.assertFalse(snapshot['owned_native_process']);self.assertFalse(snapshot['native_rpc_contact_fresh'])
        self.assertFalse(snapshot['certificate_verified']);self.assertIsNone(snapshot['own_account'])
        self.assertFalse(snapshot['certificate_is_network_liveness'])

    def test_unowned_or_different_owner_context_cannot_control_a_validator(self):
        with self.assertRaises(ValueError):authority.OwnedFinancialAuthority(object(),self.contexts[0])
        with self.assertRaises(ValueError):authority.OwnedFinancialSession(object(),self.bundle)
        own=self.context_for(self.profiles[0]);other=next(context for context in self.contexts if context.public_key!=own.public_key)
        with self.assertRaisesRegex(ValueError,'GG_SDK_VALIDATOR_OWNER'):authority.OwnedFinancialAuthority(self.profiles[0],other)

    def test_signed_source_and_descriptor_are_immutable_after_binding(self):
        context=self.contexts[0];copy=context.bundle();copy['body']['label']='caller edit'
        self.assertNotEqual(copy,context.bundle())
        descriptor=deepcopy(context.owner._meta['descriptor']);descriptor['pair_nonce']='0'*64
        context.owner._meta['descriptor']=descriptor
        with self.assertRaisesRegex(ValueError,'GG_SDK_SESSION_CHANGED'):context.check()
        self.assertTrue(context.owner._failed)

    def test_closed_owner_prevents_native_start_and_does_not_create_child(self):
        controller=self.controller();controller.session.owner.close()
        with self.assertRaises(ValueError):controller.start()
        self.assertFalse(controller.snapshot()['owned_native_process'])
        self.assertFalse(controller.snapshot()['native_rpc_contact_fresh'])

    def test_submission_keeps_actor_binding_and_only_rebroadcasts_unselected_exact_prefix(self):
        # SDK/RPC are explicit policy seams. Producer/account signatures and
        # the signed session's owner mapping are genuine protected fixtures.
        from tests.test_financial_producer import structural_context
        from backend import gg_financial_wire as wire,gg_financial_dag as financial
        from backend.gg_parallel_dag import pack
        import base64
        controller=self.controller();context=controller.session
        own=next(row for row in context._contract['roster'] if row['invite']['body']['peer_key']==context.public_key)
        index=own['producer_indices'][0];packet=structural_context(context,index)
        sender=self.profiles[0].public_invite()['body']['account_key'];recipient=next(key for key in controller.anchor['genesis']['accounts'] if key!=sender)
        payments=[]
        for nonce in range(3):
            body={'amount_atomic':'1','chain_id':controller.anchor['genesis']['chain_id'],'genesis_hash':controller.anchor['genesis_hash'],
                'nonce':nonce,'recipient':recipient,'sender':sender,'version':1}
            payments.append({'body':body,'signature':self.profiles[0]._keys[2].sign_message(pack(body)).hex()})
        signer=context.owner.signers()[1][own['producer_indices'].index(index)]
        with patch.object(financial,'verify_producer',return_value={'SDK_policy_seam':True}):
            originals=wire._signed_chain(packet,controller.anchor,signer,payments,1)
        core={key:packet[key] for key in ('schema','genesis','genesis_hash','state','signed_header')}
        core['state']['financial_dag']['authors'][index]['sequence']='1'
        sent=[]
        def broadcast(method,raw,**options):
            self.assertEqual(method,'broadcast_tx_sync');sent.append(raw)
            return {'code':0,'hash':hashlib.sha256(raw).hexdigest()}
        with patch.object(controller,'certified_state',return_value=core),patch.object(controller,'_rpc',side_effect=broadcast):
            result=controller.submit_proposals(context.public_key,originals)
        self.assertEqual([base64.b64decode(raw) for raw in wire.unpack(sent[0])['blocks']],originals[1:])
        self.assertFalse(result['SDK_selected']);self.assertFalse(result['payments_executed_asserted'])
        core['state']['financial_dag']['authors'][index]['sequence']='3'
        with patch.object(controller,'certified_state',return_value=core),patch.object(controller,'_rpc') as rpc:
            result=controller.submit_proposals(context.public_key,originals)
            rpc.assert_not_called()
        self.assertEqual(result['state'],'CREATOR_SEQUENCE_ADVANCED');self.assertFalse(result['SDK_selected'])
        foreign=next(peer.public_key for peer in self.peers if peer.public_key!=context.public_key and peer.node_role=='producer')
        with patch.object(controller,'certified_state',return_value=core),patch.object(controller,'_rpc') as rpc:
            with self.assertRaisesRegex(ValueError,'SUBMISSION_OWNER'):controller.submit_proposals(foreign,originals)
            rpc.assert_not_called()


if __name__=='__main__':unittest.main()
