"""General-account client boundaries; signatures are real, SDK proofs separate.

All identities here are reproducible public test data. No user vault, runtime
node, network, balances, issuance or public readiness is created by this suite.
"""
from copy import deepcopy
from contextlib import ExitStack
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_financial_dag as financial,gg_financial_session as session,gg_financial_wire as wire
from backend import gg_consensus_membership as membership
from backend.gg_dag_segmented import validate_native_pin
from backend.gg_ed25519 import Keypair
from backend.gg_lan_dag import _BUNDLE,_signed
from backend.gg_parallel_dag import pack
from tests.test_financial_dag import public_financial_pin
from tests.test_lan_segmented_session import public_fixture


def public_key(index):
    return Keypair.from_seed(hashlib.sha256(('PUBLIC general client account '+str(index)).encode()).digest())


def allocation():
    return {'schema':'gg.financial.account-genesis.v1','max_accounts':'4294967296',
            'allocations':sorted([{'address':public_key(i).pubkey().hex(),'balance_atomic':'500000000000'} for i in range(2)],key=lambda row:row['address'])}


def repin(pin):
    pin['genesis_hash']=hashlib.sha256(pack(pin['genesis'])).hexdigest();return pin


def public_general_pin():
    pin=public_financial_pin();genesis=pin['genesis']
    genesis.update(schema='gg.native.genesis.v6',accounts=None,financial_accounts=allocation())
    genesis['financial_dag'].update(schema=financial.GENERAL_SOURCE_SCHEMA,network_id='b'*64,policy=financial.policy(financial.GENERAL_SOURCE_SCHEMA))
    return repin(pin)


def general_bundle(fixture,**options):
    fields={'label':'Public general-account test','network_nonce':'b'*64,
            'source_schema':financial.GENERAL_SOURCE_SCHEMA,'financial_accounts':allocation()};fields.update(options)
    return session.make_bundle(fixture['owners'][0],fixture['invites'],fixture['membership'],**fields)


def signed_payment(pin,sender=None,recipient=None,**changes):
    signer=public_key(0) if sender is None else sender
    body={'version':1,'chain_id':pin['genesis']['chain_id'],'genesis_hash':pin['genesis_hash'],
          'sender':signer.pubkey().hex(),'recipient':public_key(50).pubkey().hex() if recipient is None else recipient,
          'amount_atomic':'3','nonce':0};body.update(changes)
    return {'body':body,'signature':signer.sign_message(pack(body)).hex()}


class GeneralAccountClientTests(unittest.TestCase):
    def test_general_pin_is_explicit_and_allocations_are_independent(self):
        pin=public_general_pin();checked=validate_native_pin(pin)
        self.assertEqual(checked,pin);self.assertIsNone(checked['genesis']['accounts'])
        pin['genesis']['financial_accounts']['allocations'][0]['balance_atomic']='1'
        self.assertNotEqual(checked,pin)

    def test_invalid_allocations_cannot_be_rehashed_into_valid_pins(self):
        cases={
            'zero':lambda p:p['allocations'][0].__setitem__('balance_atomic','0'),
            'sum':lambda p:p['allocations'][0].__setitem__('balance_atomic','499999999999'),
            'numeric':lambda p:p['allocations'][0].__setitem__('balance_atomic',500000000000),
            'leading_zero':lambda p:p['allocations'][0].__setitem__('balance_atomic','0500000000000'),
            'negative':lambda p:p['allocations'][0].__setitem__('balance_atomic','-1'),
            'point':lambda p:p['allocations'][0].__setitem__('address','0'*64),
            'uppercase':lambda p:p['allocations'][0].__setitem__('address',p['allocations'][0]['address'].upper()),
            'unsorted':lambda p:p['allocations'].reverse(),
            'duplicate':lambda p:p['allocations'].__setitem__(1,deepcopy(p['allocations'][0])),
            'empty':lambda p:p.__setitem__('allocations',[]),
            'capacity':lambda p:p.__setitem__('max_accounts','1'),
            'overflow':lambda p:p.__setitem__('max_accounts','4294967297'),
            'cap_type':lambda p:p.__setitem__('max_accounts',4294967296),
            'cap_bool':lambda p:p.__setitem__('max_accounts',True),
            'schema':lambda p:p.__setitem__('schema','gg.financial.account-genesis.v0'),
            'extra':lambda p:p.__setitem__('fees','1')}
        for name,mutate in cases.items():
            with self.subTest(case=name):
                pin=public_general_pin();mutate(pin['genesis']['financial_accounts'])
                with self.assertRaises(ValueError):validate_native_pin(repin(pin))

    def test_general_shape_cannot_be_silently_upgraded_or_downgraded(self):
        for kind in ('schema','source','policy','accounts','missing','extra'):
            pin=public_general_pin();genesis=pin['genesis']
            if kind=='schema':genesis['schema']='gg.native.genesis.v5'
            elif kind=='source':genesis['financial_dag'].update(schema=financial.LINEAGE_SOURCE_SCHEMA,policy=financial.policy(financial.LINEAGE_SOURCE_SCHEMA))
            elif kind=='policy':genesis['financial_dag']['policy']['schema']='gg.financial-dag.policy.v2'
            elif kind=='accounts':genesis['accounts']=[]
            elif kind=='missing':del genesis['financial_accounts']
            else:genesis['dag_segmented']={}
            with self.subTest(case=kind),self.assertRaises(ValueError):validate_native_pin(repin(pin))

    def test_more_than_128_allocations_are_rejected_and_128_are_valid(self):
        pin=public_general_pin();policy=pin['genesis']['financial_accounts']
        rows=[{'address':public_key(i+100).pubkey().hex(),'balance_atomic':'1'} for i in range(128)]
        rows[0]['balance_atomic']=str(10**12-127);policy['allocations']=sorted(rows,key=lambda row:row['address'])
        self.assertEqual(validate_native_pin(repin(pin)),pin)
        policy['allocations'].append({'address':public_key(999).pubkey().hex(),'balance_atomic':'1'})
        with self.assertRaises(ValueError):validate_native_pin(repin(pin))

    def test_all_reserved_roles_are_rejected_but_member_accounts_are_allowed(self):
        fixture=public_fixture();bundle=general_bundle(fixture);pin=membership.anchor_from_bundle(bundle,bundle['body']['coordinator'])
        rows=[invite['body'] for invite in fixture['membership']['validators']]
        reserved=financial.reserved_account_keys(pin['genesis'])
        self.assertTrue({row[key] for row in rows for key in ('validator_key','node_key','owner_peer_key')}<=reserved)
        for address in sorted(reserved):
            changed=deepcopy(pin);changed['genesis']['financial_accounts']['allocations']=[{'address':address,'balance_atomic':'1000000000000'}]
            with self.subTest(role_key=address),self.assertRaises(ValueError):validate_native_pin(repin(changed))
        changed=deepcopy(pin);changed['genesis']['financial_accounts']['allocations']=[{'address':rows[0]['account_key'],'balance_atomic':'1000000000000'}]
        self.assertEqual(validate_native_pin(repin(changed)),changed)

    def test_general_session_preserves_real_roles_and_binds_account_policy(self):
        fixture=public_fixture();bundle=general_bundle(fixture);coordinator=bundle['body']['coordinator']
        view=session.validate_bundle(bundle,coordinator)
        self.assertEqual(bundle['body']['schema'],session.GENERAL_SCHEMA)
        self.assertEqual(view['anchor'],membership.anchor_from_bundle(bundle,coordinator))
        self.assertEqual(view['source']['allowed_producers'],[0,1,2,3])
        self.assertEqual(len(view['anchor']['genesis']['validators']),4)
        member_accounts={row['body']['account_key'] for row in fixture['membership']['validators']}
        self.assertFalse(member_accounts&{row['address'] for row in allocation()['allocations']})
        other=allocation();other['max_accounts']='1000'
        changed=general_bundle(fixture,financial_accounts=other)
        second=session.validate_bundle(changed,coordinator)
        self.assertNotEqual(view['network_id'],second['network_id'])
        self.assertNotEqual(view['anchor']['genesis_hash'],second['anchor']['genesis_hash'])
        self.assertEqual(bundle,general_bundle({**fixture,'invites':list(reversed(fixture['invites']))}))

    def test_resigning_policy_without_rederiving_namespace_is_rejected(self):
        fixture=public_fixture();bundle=general_bundle(fixture)
        for kind in ('cap','allocations','mode','schema','null'):
            body=deepcopy(bundle['body'])
            if kind=='cap':body['financial_accounts']['max_accounts']='1000'
            elif kind=='allocations':body['financial_accounts']['allocations'][0]['balance_atomic']='1'
            elif kind=='mode':body['dag_test_mode']=session.MODE
            elif kind=='schema':body['schema']=session.SCHEMA
            else:body['financial_accounts']=None
            with self.subTest(case=kind),self.assertRaises(ValueError):session.validate_bundle(_signed(fixture['owners'][0],_BUNDLE,body),body['coordinator'])

    def test_default_stays_legacy_and_general_requires_explicit_policy(self):
        fixture=public_fixture();options={'label':'Public legacy boundary','network_nonce':'b'*64}
        legacy=session.make_bundle(fixture['owners'][0],fixture['invites'],fixture['membership'],**options)
        self.assertEqual(legacy['body']['schema'],session.SCHEMA)
        self.assertNotIn('financial_accounts',legacy['body'])
        for source,policy in ((financial.GENERAL_SOURCE_SCHEMA,None),(financial.LINEAGE_SOURCE_SCHEMA,allocation())):
            with self.assertRaises(ValueError):session.make_bundle(fixture['owners'][0],fixture['invites'],fixture['membership'],**options,source_schema=source,financial_accounts=policy)

    def test_general_signed_payment_may_fund_new_account_or_use_unknown_sender(self):
        pin=public_general_pin()
        for sender in (public_key(0),public_key(999)):
            payment=signed_payment(pin,sender=sender,nonce=2**64-1)
            self.assertEqual(wire.check_payment(payment,pin['genesis'],pin['genesis_hash']),payment)
        # Signature admission does not assert funds, nonce acceptance or creation.
        self.assertIsNone(pin['genesis']['accounts'])

    def test_payment_roles_points_domains_and_account_signature_are_enforced(self):
        pin=public_general_pin();reserved=financial.reserved_account_keys(pin['genesis'])
        for recipient in [*reserved,'0'*64,'01'+'00'*31,public_key(0).pubkey().hex(),public_key(1).pubkey().hex().upper()]:
            with self.subTest(recipient=recipient),self.assertRaises(ValueError):wire.check_payment(signed_payment(pin,recipient=recipient),pin['genesis'],pin['genesis_hash'])
        for changes in ({'nonce':True},{'nonce':2**64},{'amount_atomic':'0'},{'amount_atomic':'1000000000001'},
                        {'genesis_hash':'0'*64},{'chain_id':'ggnet:'+'f'*24}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):wire.check_payment(signed_payment(pin,**changes),pin['genesis'],pin['genesis_hash'])
        payment=signed_payment(pin);payment['body']['amount_atomic']='4'
        with self.assertRaises(ValueError):wire.check_payment(payment,pin['genesis'],pin['genesis_hash'])
        producer=public_fixture()['producers'][0][0];payment=signed_payment(pin)
        payment['signature']=producer.sign_message(pack(payment['body'])).hex()
        with self.assertRaises(ValueError):wire.check_payment(payment,pin['genesis'],pin['genesis_hash'])

    def test_legacy_payment_whitelist_is_preserved(self):
        pin=public_financial_pin();payment=signed_payment(pin)
        with self.assertRaises(ValueError):wire.check_payment(payment,pin['genesis'],pin['genesis_hash'])

    def test_reserved_signer_cannot_send_as_account_even_with_its_real_signature(self):
        pin=public_general_pin()
        for index in (4,8):
            signer=Keypair.from_seed(hashlib.sha256(('public financial codec '+str(index)).encode()).digest())
            self.assertIn(signer.pubkey().hex(),financial.reserved_account_keys(pin['genesis']))
            with self.assertRaises(ValueError):wire.check_payment(signed_payment(pin,sender=signer),pin['genesis'],pin['genesis_hash'])

    def test_general_block_preserves_original_signature_across_lineage_epochs(self):
        pin=public_general_pin();source=pin['genesis']['financial_dag'];signer=Keypair.from_seed(hashlib.sha256(b'public financial codec 8').digest())
        payment=signed_payment(pin)
        context={'producer_index':0,'epoch':'1','sequence':'1','parent':'a'*64,'parent_rank':'0'}
        raw=wire._context_block_wire(context,pin,signer,[payment],int(source['started_at_ns']))
        self.assertEqual(wire.decode_block(raw,source,pin['genesis_hash'],1)['payments'],1)
        record=wire.decode_block(raw,source,pin['genesis_hash'],3,allow_previous_epoch=True)
        self.assertEqual(record['body']['payments'],[payment]);self.assertEqual(record['body']['epoch'],'1')
        with self.assertRaises(ValueError):wire.decode_block(raw,source,pin['genesis_hash'],3)
        with self.assertRaises(ValueError):wire.decode_block(raw,source,pin['genesis_hash'],0,allow_previous_epoch=True)

    def test_provider_cannot_choose_requested_account_or_pinned_genesis(self):
        pin=public_general_pin();requested=public_key(0).pubkey().hex();other=public_key(50).pubkey().hex()
        packet={**deepcopy(pin),'expected_financial_account':requested,'financial_account':{'proof':{'address':requested}}}
        for kind in ('request','proof','both','missing','genesis','pin','bad_address'):
            changed=deepcopy(packet);trust=deepcopy(pin);address=requested
            if kind in ('request','both'):changed['expected_financial_account']=other
            if kind in ('proof','both'):changed['financial_account']['proof']['address']=other
            if kind=='missing':del changed['expected_financial_account']
            if kind=='genesis':changed['genesis']['chain_id']='ggnet:'+'f'*24
            if kind=='pin':trust['genesis_hash']='0'*64
            if kind=='bad_address':address='0'*64
            with self.subTest(case=kind),patch('backend.gg_consensus._verify_public',side_effect=AssertionError('untrusted request reached verifier')):
                with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_ACCOUNT_INVALID'):financial.verify_account(changed,trust,address)


class GeneralAccountProofServiceTests(unittest.TestCase):
    def setUp(self):
        from backend import gg_node_store as nodes,gg_consensus_profile as validators,portable_wallet_vault as vault
        from tests.test_financial_authority import protected_financial_network
        self.temp=tempfile.TemporaryDirectory(prefix='gg-general-client-proof-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(vault.session('PUBLIC general account fixture vault'))
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temp.name)/'owners'))
        self.stack.enter_context(patch.object(validators,'ROOT',Path(self.temp.name)/'validators'))
        self.owners,self.peers,self.profiles,self.bundle,self.contexts=protected_financial_network(
            source_schema=financial.GENERAL_SOURCE_SCHEMA,financial_accounts=allocation())
        self.addCleanup(self.cleanup)
        for peer in self.peers:peer.install_session(self.bundle,_start_gossip=False)

    def cleanup(self):
        for profile in self.profiles:profile.close()
        for peer in self.peers:peer.stop()
        for profile in self.owners:profile.close()

    def test_new_session_uses_financial_read_only_views_without_minting_or_production(self):
        for peer in self.peers:
            view=peer.snapshot();service=peer._proof_service
            self.assertIsNone(peer._engine);self.assertEqual(service.anchor['genesis']['schema'],'gg.native.genesis.v6')
            self.assertEqual(view['mode'],'FINANCIAL_SDK_CERTIFIED_VIEW')
            self.assertEqual(view['financial_accounts'],[]);self.assertEqual(view['own_financial_accounts'],[])
            self.assertIsNone(view['dag_proofs']['account_tree']);self.assertFalse(view['dag_proofs']['canonical_finality'])
            self.assertFalse(service.server.is_alive());self.assertFalse(service.client.is_alive())
            self.assertEqual({row['node_label'] for row in view['producers']},{'Windows','Linux','Termux'})
            with self.assertRaises(ValueError):peer.start_dag_production(1000,5000,0)

    def test_account_requests_require_prime_point_exact_network_height_and_safe_selector(self):
        from backend import gg_financial_proof_sync as proofs
        service=self.peers[0]._proof_service;address=public_key(50).pubkey().hex()
        request=service._request('account',1,address)
        self.assertEqual(proofs.validate_request(request),request)
        for change in ({'height':0},{'selector':'0'*64},{'selector':True},{'selector':{'address':address}},
                       {'selector':address.upper()},{'kind':'account-sign'}):
            with self.subTest(change=change),self.assertRaises(ValueError):proofs.validate_request({**request,**change})
        with self.assertRaisesRegex(ValueError,'GG_PROOF_ANCHOR'):service.reply({**request,'genesis_hash':'0'*64})
        self.assertEqual(service.reply(request),{'state':'UNAVAILABLE'})

    def test_only_current_certificate_account_rows_are_published_and_absence_is_explicit(self):
        # Projection policy seam only. No row below is claimed to be SDK verified;
        # real certificates/proofs exercise the writer separately.
        service=self.peers[0]._proof_service;own=next(row['body']['account_key'] for row in service.anchor['genesis']['membership']['validators'] if row['body']['owner_peer_key']==self.peers[0].public_key)
        state={'height':5,'state_root':'a'*64,'accounts':None,'financial_dag':{},'account_tree':{'count':'2'}}
        service._certificate_info=({'state':state},(6,'b'*64),None)
        service._account_views[own]={'address':own,'exists':False,'balance_atomic':'0','nonce':'0','state_height':5,'certificate_height':6,'state_root':'a'*64}
        service._account_views[public_key(50).pubkey().hex()]={'address':public_key(50).pubkey().hex(),'exists':True,'balance_atomic':'999','nonce':'3','state_height':4,'certificate_height':5,'state_root':'c'*64}
        snapshot=service.snapshot()
        self.assertEqual(snapshot['certified_accounts'],snapshot['own_accounts'])
        self.assertEqual(len(snapshot['own_accounts']),1);self.assertIs(snapshot['own_accounts'][0]['exists'],False)
        selected=public_key(50).pubkey().hex();service.select_owned_account(selected)
        self.assertEqual(service.snapshot()['own_accounts'],[])
        service._account_views[selected]={'address':selected,'exists':True,'balance_atomic':'1','nonce':'0',
            'state_height':5,'certificate_height':6,'state_root':'a'*64}
        self.assertEqual([row['address'] for row in service.snapshot()['own_accounts']],[selected])
        service._account_views.pop(selected)
        state['state_root']='d'*64
        self.assertEqual(service.snapshot()['certified_accounts'],[])
        state['state_root']='a'*64;service._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
        self.assertEqual(service.snapshot()['certified_accounts'],[]);self.assertIsNone(service.snapshot()['account_tree'])


if __name__=='__main__':unittest.main()
