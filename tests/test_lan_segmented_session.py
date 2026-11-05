"""Signed-session/domain tests, not a claim of a running SDK quorum."""
from copy import deepcopy
import hashlib
import unittest

from backend import gg_consensus_membership as member,gg_dag_segmented_session as session
from backend.gg_ed25519 import Keypair
from backend.gg_lan_dag import _signed,_BUNDLE,_INVITE,LanDagPeer
from backend.gg_parallel_dag import ParallelDag,pack


def public_fixture(*,owner_ports=None,p2p_ports=None,roles=('producer','producer','replica')):
    """Public deterministic test identities; never user keys or credentials."""
    def seed(name):return hashlib.sha256(('public-segmented-session-fixture-'+name).encode()).digest()
    def key(name):return Keypair.from_seed(seed(name))
    owners=[key('owner-'+str(i)) for i in range(3)]
    producers=[[key('producer-'+str(i)+'-'+str(j)) for j in range(2)] for i in range(3)]
    owner_ports=owner_ports or [18001,18002,18003];p2p_ports=p2p_ports or [21001,21002,21003,21004]
    invites=[]
    for i,(owner,role) in enumerate(zip(owners,roles)):
        body={'schema':'gg.lan-dag.invite.v6' if role=='light' else 'gg.lan-dag.invite.v4','label':('Windows','Linux','Termux')[i],
            'host':'127.0.0.1','port':owner_ports[i],'peer_key':owner.pubkey().hex(),'producer_keys':[value.pubkey().hex() for value in producers[i]],
            'nonce':hashlib.sha256(('public LAN owner '+str(i)).encode()).hexdigest(),'allow_test_tokens':False,'allow_dag_transactions':True,'node_role':role}
        invites.append(_signed(owner,_INVITE,body))
    validator_invites=[];validator_seeds={};node_seeds={}
    for i in range(4):
        validator,node,account=key('validator-'+str(i)),key('node-'+str(i)),key('account-'+str(i))
        validator_seeds[validator.pubkey().hex()]=seed('validator-'+str(i));node_seeds[validator.pubkey().hex()]=seed('node-'+str(i))
        validator_invites.append(member.make_invite(validator,node,account,owners[i%2],label='Public v5 validator '+str(i),
            host='127.0.0.1',p2p_port=p2p_ports[i],nonce=hashlib.sha256(('public v5 validator '+str(i)).encode()).hexdigest()))
    forbidden=[value.pubkey().hex() for pair in producers for value in pair]+[value.pubkey().hex() for value in owners]
    membership=member.make_membership(validator_invites,owners={invite['body']['peer_key']:invite['body'] for invite in invites},
        forbidden_keys=forbidden,chain_id='ggnet:'+hashlib.sha256(b'public segmented session SDK').hexdigest()[:24],genesis_time_unix=1700000000)
    return {'owners':owners,'producers':producers,'invites':invites,'membership':membership,
            'validator_seeds':validator_seeds,'node_seeds':node_seeds}


def bundle(fixture,**changes):
    options={'label':'Public segmented LAN','network_nonce':'b'*64};options.update(changes)
    return session.make_bundle(fixture['owners'][0],fixture['invites'],fixture['membership'],**options)


class SegmentedLanSessionTests(unittest.TestCase):
    def test_same_inputs_and_reordered_invites_derive_identical_signed_geneses(self):
        fixture=public_fixture();first=bundle(fixture)
        reversed_fixture={**fixture,'invites':list(reversed(fixture['invites']))}
        self.assertEqual(first,bundle(reversed_fixture))
        view=session.validate_bundle(first,fixture['owners'][0].pubkey().hex())
        self.assertEqual(view['anchor'],member.anchor_from_bundle(first,first['body']['coordinator']))
        self.assertEqual(view['source']['network_id'],view['network_id'])
        self.assertEqual(len(view['source']['genesis']['chain_id']),70)
        self.assertEqual(view['anchor']['genesis']['schema'],'gg.native.genesis.v4')
        self.assertNotIn('dag',view['anchor']['genesis'])

    def test_roles_come_from_signed_owners_and_all_six_identities_remain_distinct(self):
        fixture=public_fixture();wire=bundle(fixture);view=session.validate_bundle(wire,wire['body']['coordinator'])
        source=view['source'];self.assertEqual(len(source['allowed_producers']),4)
        self.assertEqual(len(set(source['genesis']['producers'])),6)
        for entry in view['roster']:
            row=entry['invite']['body']
            self.assertEqual([source['genesis']['producers'][i] for i in entry['producer_indices']],row['producer_keys'])
            self.assertEqual(all(i in source['allowed_producers'] for i in entry['producer_indices']),row['node_role']=='producer')
        self.assertNotIn(fixture['owners'][2].pubkey().hex(),{invite['body']['owner_peer_key'] for invite in wire['body']['consensus']['validators']})

    def test_nonce_label_time_role_and_committee_each_change_the_signing_domain(self):
        fixture=public_fixture();first=bundle(fixture);coordinator=first['body']['coordinator']
        variants=[bundle(fixture,network_nonce='c'*64),bundle(fixture,label='A distinct public LAN'),
                  bundle(fixture,started_at_ns=1700000000000000001),bundle(public_fixture(roles=('producer','producer','producer')))]
        other=deepcopy(fixture['membership']);other['chain_id']='ggnet:'+'d'*24
        variants.append(bundle({**fixture,'membership':other}))
        original=session.validate_bundle(first,coordinator)
        for wire in variants:
            with self.subTest(label=wire['body']['label'],nonce=wire['body']['network_nonce']):
                view=session.validate_bundle(wire,coordinator)
                self.assertNotEqual(view['network_id'],original['network_id'])
                self.assertNotEqual(view['source']['genesis']['chain_id'],original['source']['genesis']['chain_id'])
                self.assertNotEqual(view['anchor']['genesis_hash'],original['anchor']['genesis_hash'])

    def test_resigning_context_changes_cannot_keep_the_old_public_genesis(self):
        fixture=public_fixture();wire=bundle(fixture);coordinator=wire['body']['coordinator']
        for kind in ('nonce','label','committee','time','role','producer_index','source_policy','extra','schema'):
            body=deepcopy(wire['body'])
            if kind=='nonce':body['network_nonce']='c'*64
            elif kind=='label':body['label']='Changed public LAN'
            elif kind=='committee':body['consensus']['chain_id']='ggnet:'+'d'*24
            elif kind=='time':body['public_genesis']['started_at_ns']+=1
            elif kind=='role':
                for entry in body['roster']:
                    if entry['invite']['body']['peer_key']==fixture['owners'][2].pubkey().hex():
                        entry['invite']['body']['node_role']='producer';entry['invite']=_signed(fixture['owners'][2],_INVITE,entry['invite']['body'])
            elif kind=='producer_index':body['roster'][0]['producer_indices']=[False,1]
            elif kind=='source_policy':body['public_genesis']['genesis']['execution_policy']['max_block_transactions']=1
            elif kind=='extra':body['history_replayed']=True
            elif kind=='schema':body['schema']='gg.lan-dag.session.v4'
            changed=_signed(fixture['owners'][0],_BUNDLE,body)
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'SESSION_INVALID'):session.validate_bundle(changed,coordinator)

    def test_foreign_signed_initial_block_is_rejected_in_the_new_session(self):
        fixture=public_fixture();wire_a=bundle(fixture);wire_b=bundle(fixture,network_nonce='c'*64)
        a=session.validate_bundle(wire_a,wire_a['body']['coordinator']);b=session.validate_bundle(wire_b,wire_b['body']['coordinator'])
        engines=[ParallelDag.from_segmented_source(view['source'],view['anchor']['genesis_hash']) for view in (a,b)]
        try:
            producer=a['source']['allowed_producers'][0]
            keys={value.pubkey().hex():value for pair in fixture['producers'] for value in pair}
            engines[0].attach_local_producers({producer:keys[a['source']['genesis']['producers'][producer]]})
            block=engines[0].produce_lan_test_block(producer,1,1024*1024)
            with self.assertRaises(ValueError):engines[1].admit_relayed(block['wire'],0)
            self.assertEqual(engines[1].snapshot()['segment']['active_admitted_blocks'],0)
        finally:
            for engine in engines:engine.stop()

    def test_unpinned_coordinator_unsigned_edit_and_owner_signature_are_rejected(self):
        fixture=public_fixture();wire=bundle(fixture);coordinator=wire['body']['coordinator']
        for kind in ('pin','outer_signature','owner_signature','unsigned_edit'):
            bad=deepcopy(wire);pin=coordinator
            if kind=='pin':pin=fixture['owners'][1].pubkey().hex()
            elif kind=='outer_signature':bad['signature']='0'*128
            elif kind=='owner_signature':
                bad['body']['roster'][0]['invite']['signature']='0'*128;bad=_signed(fixture['owners'][0],_BUNDLE,bad['body'])
            else:bad['body']['network_nonce']='c'*64
            with self.subTest(kind=kind),self.assertRaises(ValueError):session.validate_bundle(bad,pin)

    def test_explicit_validator_ownership_is_separate_from_dag_production(self):
        fixture=public_fixture();membership=deepcopy(fixture['membership'])
        membership['validators'][0]=member.make_invite(Keypair(),Keypair(),Keypair(),fixture['owners'][2],
            label='Explicit replica-owned validator',host='127.0.0.1',p2p_port=22001,nonce='e'*64)
        membership['validators'].sort(key=lambda value:value['body']['validator_key'])
        wire=bundle({**fixture,'membership':membership});view=session.validate_bundle(wire,wire['body']['coordinator'])
        replica=next(entry for entry in view['roster'] if entry['invite']['body']['peer_key']==fixture['owners'][2].pubkey().hex())
        self.assertTrue(all(i not in view['source']['allowed_producers'] for i in replica['producer_indices']))
        self.assertIn(fixture['owners'][2].pubkey().hex(),{invite['body']['owner_peer_key'] for invite in membership['validators']})

    def test_light_or_unregistered_owner_cannot_enter_the_committee(self):
        fixture=public_fixture()
        for kind in ('light','unregistered'):
            candidate=public_fixture(roles=('producer','producer','light')) if kind=='light' else fixture
            owner=Keypair() if kind=='unregistered' else candidate['owners'][2]
            changed=member.make_invite(Keypair(),Keypair(),Keypair(),owner,label='Changed member',host='127.0.0.1',p2p_port=22001,nonce='e'*64)
            membership=deepcopy(candidate['membership']);membership['validators'][0]=changed
            membership['validators'].sort(key=lambda value:value['body']['validator_key'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):bundle({**candidate,'membership':membership})

    def test_duplicate_owners_producers_endpoints_or_noncanonical_roster_are_rejected(self):
        fixture=public_fixture();wire=bundle(fixture);coordinator=wire['body']['coordinator']
        for kind in ('owner','producer','endpoint','order'):
            body=deepcopy(wire['body'])
            if kind=='owner':body['roster'][1]['invite']=deepcopy(body['roster'][0]['invite'])
            elif kind=='order':body['roster'].reverse()
            else:
                row=body['roster'][1]['invite']['body'];first=body['roster'][0]['invite']['body']
                if kind=='producer':row['producer_keys']=deepcopy(first['producer_keys'])
                else:row['port']=first['port']
                key=next(value for value in fixture['owners'] if value.pubkey().hex()==row['peer_key'])
                body['roster'][1]['invite']=_signed(key,_INVITE,row)
            with self.subTest(kind=kind),self.assertRaises(ValueError):session.validate_bundle(_signed(fixture['owners'][0],_BUNDLE,body),coordinator)

    def test_new_contract_does_not_activate_the_legacy_runtime(self):
        fixture=public_fixture();wire=bundle(fixture)
        peer=LanDagPeer('Unstarted isolated legacy peer',trusted_coordinator=wire['body']['coordinator'],allow_dag_transactions=True)
        try:
            with self.assertRaisesRegex(ValueError,'GG_SDK_OWNED_NODE_PROFILE_REQUIRED'):peer.install_session(wire,_start_gossip=False)
            self.assertIsNone(peer._engine);self.assertIsNone(peer._listener)
        finally:peer.stop()

    def test_bounds_and_owned_results_prevent_ambiguous_contracts(self):
        fixture=public_fixture()
        for options in ({'network_nonce':''},{'network_nonce':'B'*64},{'started_at_ns':True},{'started_at_ns':1700000005000000001},{'label':'\x7f'}):
            with self.subTest(options=options),self.assertRaises(ValueError):bundle(fixture,**options)
        wire=bundle(fixture);view=session.validate_bundle(wire,wire['body']['coordinator']);before=pack(view)
        wire['body']['public_genesis']['accounts'].clear();wire['body']['roster'].clear()
        self.assertEqual(pack(view),before)


if __name__=='__main__':unittest.main()
