"""Real protected keys/SQLite/signatures; SDK account lookup is a policy seam.

No synthetic certificate is submitted to the native verifier. Separate owned
integration checks must exercise this profile with actual SDK account proofs.
"""
from contextlib import ExitStack,closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_financial_account as accounts,gg_financial_dag as financial,gg_financial_wire as wire
from backend import portable_wallet_vault as portable,gg_node_vault as vault
from backend.gg_parallel_dag import pack
from tests.test_financial_general_clients import public_general_pin,public_key,repin


def policy_packet(anchor,address,*,nonce=0,balance=100000,exists=True,height=1,identifier='a'*64):
    # Deliberately incomplete SDK fixture. Only the explicit lookup seam below
    # consumes this; no cryptographic verifier or live peer receives it.
    return {'schema':'gg.consensus.proof.v1',**deepcopy(anchor),
        'state':{'height':height,'state_root':hashlib.sha256(('PUBLIC policy root '+str(height)).encode()).hexdigest()},
        'signed_header':{'header':{'height':str(height+1)},'commit':{'block_id':{'hash':identifier}}},
        'expected_financial_account':address,
        'financial_account':{'test_policy_account':{'address':address,'nonce':str(nonce),'balance_atomic':str(balance)} if exists else None,
                             'test_policy_requested_address':address}}


def account_policy(packet,trust,address,**options):
    if (packet['genesis']!=trust['genesis'] or packet['genesis_hash']!=trust['genesis_hash']
            or packet['expected_financial_account']!=address or packet['financial_account']['test_policy_requested_address']!=address):raise ValueError('PUBLIC_POLICY_REQUEST_MISMATCH')
    row=packet['financial_account']['test_policy_account']
    return {'financial_account_verified':True,'financial_account_address':address,'financial_account_exists':row is not None,
            'financial_account':deepcopy(row),'financial_account_scope':'EXPLICIT_TEST_SDK_LOOKUP_POLICY_SEAM_NOT_CRYPTOGRAPHY'}


class ProtectedFinancialAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-independent-account-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(accounts,'ROOT',Path(self.temp.name)/'accounts'))
        self.stack.enter_context(portable.session('PUBLIC independent account vault fixture'))
        self.stack.enter_context(patch.object(financial,'verify_account',side_effect=account_policy))
        self.profiles=[];self.addCleanup(self.close_profiles);self.anchor=public_general_pin()

    def close_profiles(self):
        for profile in self.profiles:profile.close()

    def create(self,name='Alice'):
        profile=accounts.AccountProfile.create(name,label='Public account fixture');self.profiles.append(profile);return profile

    def open(self,name='Alice'):
        profile=accounts.AccountProfile.open(name);self.profiles.append(profile);return profile

    def bound(self,name='Alice'):
        profile=self.create(name);profile.bind(self.anchor);return profile

    def packet(self,profile,**options):return policy_packet(self.anchor,profile.public_address(),**options)

    def outputs(self,count=1):return [{'recipient':public_key(900).pubkey().hex(),'amount_atomic':'1'} for _ in range(count)]

    def test_independent_key_is_protected_and_grants_no_node_or_money(self):
        profile=self.create();view=profile.snapshot();secret=bytes(profile._key)
        self.assertEqual(view['role'],'account');self.assertEqual(view['state'],'UNBOUND')
        self.assertIsNone(view['account_exists']);self.assertEqual(view['signed_batches'],0)
        self.assertFalse(view['hardware_signer']);self.assertFalse(view['whole_disk_rollback_protection'])
        self.assertNotIn('validator',view);self.assertNotIn('protected_key',view)
        raw=(profile.root/'account.sqlite3').read_bytes()
        self.assertNotIn(secret,raw);self.assertNotIn(secret[:32],raw)
        self.assertNotIn(secret[:32].hex().encode(),raw)
        self.assertNotIn(profile.public_address(),financial.reserved_account_keys(self.anchor['genesis']))

    def test_exclusive_cold_open_keeps_same_key_and_network(self):
        profile=self.bound();address=profile.public_address()
        with self.assertRaisesRegex(ValueError,'PROFILE_IN_USE'):accounts.AccountProfile.open('Alice')
        profile.close();resumed=self.open()
        self.assertEqual(resumed.public_address(),address);self.assertEqual(resumed.anchor(),self.anchor)
        self.assertEqual(resumed.snapshot()['signed_batches'],0)

    def test_binding_is_immutable_and_rejects_legacy_or_wrong_pin(self):
        profile=self.bound();other=deepcopy(self.anchor);other['genesis']['chain_id']='ggnet:'+'f'*24
        other['genesis']['financial_dag']['native_chain_id']=other['genesis']['chain_id'];repin(other)
        with self.assertRaisesRegex(ValueError,'NETWORK_ALREADY_BOUND'):profile.bind(other)
        changed=deepcopy(self.anchor);changed['genesis_hash']='0'*64
        with self.assertRaises(ValueError):profile.bind(changed)
        value=profile.anchor();value['genesis']['symbol']='changed'
        self.assertEqual(profile.anchor(),self.anchor)

    def test_signs_5000_actual_payments_after_durable_commit_and_reopens_exactly(self):
        profile=self.bound();packet=self.packet(profile);outputs=self.outputs(5000)
        review=profile.review(outputs,packet);self.assertFalse(review.summary()['signatures_created'])
        raw=profile.sign(review);values=wire.decode_payment_document(raw,self.anchor)
        self.assertEqual(len(values),5000);self.assertEqual([row['body']['nonce'] for row in values],list(range(5000)))
        self.assertEqual({row['body']['sender'] for row in values},{profile.public_address()})
        self.assertEqual(profile.original(),raw);self.assertEqual(profile.snapshot()['next_signing_nonce'],'5000')
        profile.close();resumed=self.open()
        self.assertEqual(resumed.original(),raw);self.assertEqual(resumed.pending(packet),raw)
        with patch.object(resumed._key,'sign_message',side_effect=AssertionError('pending original was resigned')):
            self.assertEqual(resumed.pending(packet),raw)
        self.assertFalse(resumed.snapshot()['payments_executed_asserted'])

    def test_review_is_immutable_foreign_and_stale_reviews_cannot_sign(self):
        profile=self.bound();review=profile.review(self.outputs(),self.packet(profile))
        with self.assertRaises(AttributeError):review._start=100
        other=self.bound('Bob')
        with self.assertRaises(ValueError):other.sign(review)
        with self.assertRaises(ValueError):profile.sign({'verified':True,'outputs':self.outputs()})
        profile.remember_account(self.packet(profile,height=2,balance=100001))
        with self.assertRaisesRegex(ValueError,'REVIEW_STALE'):profile.sign(review)
        with self.assertRaises(ValueError):accounts._AccountReview(None,None,None,None,0,[])
        self.assertEqual(profile.snapshot()['signed_batches'],0)

    def test_newer_certificate_with_identical_own_account_keeps_explicit_review_valid(self):
        profile=self.bound();review=profile.review(self.outputs(),self.packet(profile))
        profile.remember_account(self.packet(profile,height=2))
        raw=profile.sign(review)
        self.assertEqual(len(wire.decode_payment_document(raw,self.anchor)),1)

    def test_funds_types_roles_and_point_checks_precede_any_signature(self):
        profile=self.bound();packet=self.packet(profile,balance=5)
        cases=[[],self.outputs(6),[{'recipient':profile.public_address(),'amount_atomic':'1'}],
               [{'recipient':'0'*64,'amount_atomic':'1'}],[{'recipient':self.anchor['genesis']['validators'][0],'amount_atomic':'1'}],
               [{'recipient':public_key(900).pubkey().hex(),'amount_atomic':1}],
               [{'recipient':public_key(900).pubkey().hex(),'amount_atomic':'01'}],
               [{'recipient':public_key(900).pubkey().hex(),'amount_atomic':'0'}],
               [{'recipient':public_key(900).pubkey().hex(),'amount_atomic':'1','fee':'0'}]]
        for outputs in cases:
            with self.subTest(outputs=outputs),self.assertRaises(ValueError):profile.review(outputs,packet)
        self.assertEqual(profile.snapshot()['signed_batches'],0)

    def test_unfunded_account_and_pending_nonce_cannot_create_new_intent(self):
        profile=self.bound()
        with self.assertRaisesRegex(ValueError,'UNFUNDED'):profile.review(self.outputs(),self.packet(profile,exists=False))
        review=profile.review(self.outputs(3),self.packet(profile,height=2));profile.sign(review)
        with self.assertRaisesRegex(ValueError,'PENDING_ORIGINAL'):profile.review(self.outputs(),self.packet(profile,nonce=1,height=3))

    def test_pending_suffix_preserves_account_envelopes_and_keeps_old_documents(self):
        profile=self.bound();raw=profile.sign(profile.review(self.outputs(3),self.packet(profile)))
        original=json.loads(raw)['payments'];packet=self.packet(profile,nonce=1,height=2)
        remaining=json.loads(profile.pending(packet))['payments']
        self.assertEqual([pack(row) for row in remaining],[pack(row) for row in original[1:]])
        consumed=self.packet(profile,nonce=3,height=3)
        self.assertIsNone(profile.pending(consumed))
        self.assertEqual(profile.snapshot()['payment_state'],'NONCE_CONSUMED_OUTCOME_UNRESOLVED')
        self.assertFalse(profile.snapshot()['payments_executed_asserted'])
        next_raw=profile.sign(profile.review(self.outputs(),consumed))
        self.assertEqual(json.loads(next_raw)['payments'][0]['body']['nonce'],3)
        self.assertEqual(profile.original(1),raw)
        profile.close();resumed=self.open();self.assertEqual(resumed.original(1),raw);self.assertEqual(resumed.original(2),next_raw)

    def test_unknown_commit_reopens_actual_boundary_without_exposing_or_resigning(self):
        for committed in (False,True):
            with self.subTest(committed=committed):
                profile=self.bound('Commit'+str(committed));packet=self.packet(profile);review=profile.review(self.outputs(3),packet)
                # This fault belongs to the original's own COMMIT. Migration
                # has a distinct durable boundary tested immediately below.
                profile._prepare_journal()
                self.assertEqual(profile._db.execute('PRAGMA user_version').fetchone(),(2,))
                commit=profile._commit;exposed=[]
                def failure():
                    if committed:commit()
                    raise OSError('PUBLIC injected commit response loss')
                with patch.object(profile,'_commit',side_effect=failure):
                    with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):exposed.append(profile.sign(review))
                self.assertEqual(exposed,[])
                with self.assertRaises(ValueError):profile.sign(review)
                profile.close();resumed=self.open('Commit'+str(committed))
                self.assertEqual(resumed.snapshot()['signed_batches'],int(committed))
                if committed:
                    raw=resumed.original()
                    with patch.object(resumed._key,'sign_message',side_effect=AssertionError('unknown commit resigned')):self.assertEqual(resumed.pending(packet),raw)
                else:self.assertEqual(resumed.snapshot()['next_signing_nonce'],'0')

    def test_unknown_migration_commit_and_rollback_reply_never_sign_a_new_intent(self):
        for committed,rollback_lost in ((False,False),(True,False),(False,True)):
            with self.subTest(committed=committed,rollback_lost=rollback_lost):
                name='Migrate'+str(committed)+str(rollback_lost);profile=self.bound(name)
                with patch.object(profile,'_prepare_journal',lambda **options:None):
                    raw=profile.sign(profile.review(self.outputs(),self.packet(profile)))
                before=(profile.public_address(),profile._body['batch_head'],profile._body['next_nonce'],profile.batch_count(),
                        profile._body['protected_key'])
                review=profile.review(self.outputs(3),self.packet(profile,nonce=1,height=2))
                connection=profile._db;commit=profile._commit;sign=profile._key.sign_message;messages=[];exposed=[]
                class RollbackOutcome:
                    def __getattr__(self,attribute):return getattr(connection,attribute)
                    def execute(self,sql,*args):
                        result=connection.execute(sql,*args)
                        if sql=='ROLLBACK' and rollback_lost:raise OSError('PUBLIC lost rollback reply')
                        return result
                profile._db=RollbackOutcome()
                def failure():
                    if committed:commit()
                    raise OSError('PUBLIC lost migration commit reply')
                def observed(message):messages.append(message);return sign(message)
                with patch.object(profile,'_commit',side_effect=failure),patch.object(profile._key,'sign_message',side_effect=observed):
                    with self.assertRaisesRegex(ValueError,'STORE_WRITE_FAILED'):exposed.append(profile.sign(review))
                self.assertEqual(exposed,[]);self.assertTrue(profile._failed);self.assertTrue(messages)
                self.assertTrue(all(message.startswith(accounts.DOMAIN+b'HEAD\0') for message in messages),
                                'migration fault reached a new intent signature')
                self.assertEqual((profile.public_address(),profile._body['batch_head'],profile._body['next_nonce'],
                                  profile._body['batch_count'],profile._body['protected_key']),before)
                with self.assertRaises(ValueError):profile.sign(review)
                profile.close();resumed=self.open(name)
                self.assertEqual(resumed._db.execute('PRAGMA user_version').fetchone(),(2 if committed else 1,))
                self.assertEqual((resumed.public_address(),resumed._body['batch_head'],resumed._body['next_nonce'],
                                  resumed.batch_count(),resumed._body['protected_key']),before)
                with patch.object(resumed._key,'sign_message',side_effect=AssertionError('migration recovery resigned')):
                    self.assertEqual(resumed.original('1'),raw)
                following=resumed.sign(resumed.review(self.outputs(),self.packet(resumed,nonce=1,height=3)))
                self.assertEqual(resumed.snapshot()['next_signing_nonce'],'2');self.assertEqual(resumed.original('2'),following)

    def test_cold_replay_rejects_missing_changed_extra_or_wrong_original_metadata(self):
        for kind in ('missing','changed','extra','nonce','link'):
            with self.subTest(kind=kind):
                profile=self.bound('Corrupt'+kind);profile.sign(profile.review(self.outputs(2),self.packet(profile)));path=profile.root/'account.sqlite3';profile.close()
                with closing(sqlite3.connect(path)) as db,db:
                    if kind=='missing':db.execute('DELETE FROM batches')
                    elif kind=='changed':db.execute('UPDATE batches SET document=?',(b'{}',))
                    elif kind=='nonce':db.execute("UPDATE batches SET end_nonce='3'")
                    elif kind=='link':db.execute('UPDATE batches SET hash=?',('0'*64,))
                    else:
                        row=db.execute('SELECT hash,document FROM batches').fetchone()
                        db.execute('INSERT INTO batches VALUES(?,?,?,?,?,?)',(2,'2','4',row[0],'0'*64,row[1]))
                with self.assertRaisesRegex(ValueError,'PROFILE_INVALID'):accounts.AccountProfile.open('Corrupt'+kind)

    def test_external_warm_database_mutation_blocks_new_signatures(self):
        profile=self.bound();review=profile.review(self.outputs(),self.packet(profile))
        profile._db.execute('UPDATE state SET record=record')
        with self.assertRaisesRegex(ValueError,'STORE_CHANGED'):profile.sign(review)

    def test_verified_rewind_conflict_and_unknown_nonce_do_not_allow_spending(self):
        for kind in ('rewind','conflict','nonce'):
            with self.subTest(kind=kind):
                profile=self.bound('Floor'+kind);profile.remember_account(self.packet(profile,height=3))
                packet=self.packet(profile,height=2 if kind=='rewind' else 3,nonce=1 if kind=='nonce' else 0,
                                   identifier='b'*64 if kind=='conflict' else 'a'*64)
                with self.assertRaises(ValueError):profile.remember_account(packet)
                if kind!='rewind':
                    self.assertEqual(profile.snapshot()['state'],'FAULT');profile.close();resumed=self.open('Floor'+kind)
                    with self.assertRaises(ValueError):resumed.review(self.outputs(),self.packet(resumed,height=4))

    def test_vault_role_and_root_cannot_be_substituted(self):
        profile=self.create();cipher=__import__('base64').b64decode(profile._body['protected_key'])
        for role,root in (('consensus_account',profile.root),('financial_account',profile.root/'another')):
            with self.subTest(role=role,root=str(root)),self.assertRaises(ValueError):vault.crypt(cipher,profile.public_address(),role,root,decrypt=True,storage=profile._body['key_storage'])

    def test_hardlinked_database_and_invalid_names_are_rejected(self):
        for name in ('../Escape','A/B','A\\B','', '1Name'):
            with self.subTest(name=name),self.assertRaises(ValueError):accounts.AccountProfile.create(name,label='Public fixture')
        profile=self.create();path=profile.root/'account.sqlite3';profile.close();os.link(path,profile.root/'extra-link')
        with self.assertRaisesRegex(ValueError,'PROFILE_INVALID'):accounts.AccountProfile.open('Alice')


if __name__=='__main__':unittest.main()
