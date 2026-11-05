"""Protected account CLI dispatch with explicit SDK/transport policy seams.

Keys, signatures, original storage and file limits are real. The synthetic
account-view fixture is never presented to native verification or a live SDK.
"""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from backend import gg_financial_account as accounts,gg_financial_dag as financial,gg_financial_wire as wire
from backend import lan_dag_runtime as runtime,portable_wallet_vault as portable
from backend.gg_parallel_dag import pack
from tests.test_financial_account import account_policy,policy_packet
from tests import test_financial_general_clients as client_fixture
from tests.test_financial_general_clients import public_key


class FinancialAccountRuntimeTests(client_fixture.GeneralAccountProofServiceTests):
    # Do not inherit the parent class's test methods as duplicate evidence.
    test_new_session_uses_financial_read_only_views_without_minting_or_production=None
    test_account_requests_require_prime_point_exact_network_height_and_safe_selector=None
    test_only_current_certificate_account_rows_are_published_and_absence_is_explicit=None

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(accounts,'ROOT',Path(self.temp.name)/'accounts'))
        self.stack.enter_context(patch.object(financial,'verify_account',side_effect=account_policy))
        self.manager=runtime.LanDagRuntime();self.addCleanup(self.manager.stop)
        self.manager._peer=self.peers[0];self.manager._bundle=self.bundle
        self.manager._allowed=str(self.peers[0].allowed);self.manager._trusted=self.peers[0]._trusted
        self.service=self.peers[0]._proof_service;self.height=1;self.nonce=0
        self.stack.enter_context(patch.object(self.service,'requested_proof',side_effect=self.packet))

    def packet(self,kind,address,**options):
        if kind!='account':raise AssertionError('unexpected source query')
        return policy_packet(self.service.anchor,address,nonce=self.nonce,height=self.height)

    def create(self,name='Alice'):
        self.manager.dispatch('lan.account_create',{'profile':name})
        return self.manager._account_profiles[name]

    def outputs(self,count=3):return [{'recipient':public_key(800).pubkey().hex(),'amount_atomic':'1'} for _ in range(count)]

    def test_review_sign_and_submit_use_same_durable_account_envelopes_without_execution_claim(self):
        profile=self.create();review=self.manager.dispatch('lan.account_review',{'payments':self.outputs()})
        self.assertEqual(review['state'],'REVIEWED');self.assertEqual(profile.snapshot()['signed_batches'],0)
        signed=self.manager.dispatch('lan.account_sign',{});self.assertEqual(signed['state'],'SIGNED_DURABLY')
        original=profile.original()
        with patch.object(self.service,'submit_signed',return_value={'state':'QUEUED','SDK_selected':False}) as submit:
            result=self.manager.dispatch('lan.account_submit',{'transactions_per_block':2})
        self.assertFalse(result['payments_executed_asserted']);self.assertFalse(result['SDK_selected'])
        self.assertTrue(result['account_originals_durable'])
        values=submit.call_args.args[0];self.assertEqual(values.rows(),json.loads(original)['payments'])
        self.assertEqual(submit.call_args.kwargs,{'transactions_per_block':2})
        self.assertEqual(profile.original(),original)
        self.assertEqual(self.service._selected_account,profile.public_address())

    def test_sign_requires_an_explicit_review_and_nonce_changes_are_not_ignored(self):
        profile=self.create()
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):self.manager.dispatch('lan.account_sign',{})
        self.manager.dispatch('lan.account_review',{'payments':self.outputs()})
        self.nonce=1;self.height=2
        with self.assertRaisesRegex(ValueError,'UNEXPECTED_NONCE'):self.manager.dispatch('lan.account_sign',{})
        self.assertEqual(profile.snapshot()['signed_batches'],0)

    def test_large_intent_uses_bounded_public_file_and_export_never_overwrites(self):
        profile=self.create();path=Path(self.temp.name)/'intent.json'
        document={'schema':'gg.financial.payment-intent.v1','genesis_hash':self.service.anchor['genesis_hash'],
                  'sender':profile.public_address(),'payments':self.outputs(5000)}
        raw=pack(document);self.assertGreater(len(raw),16384);path.write_bytes(raw)
        reviewed=self.manager.dispatch('lan.account_review',{'path':str(path)})
        self.assertEqual(reviewed['payments'],5000);self.manager.dispatch('lan.account_sign',{})
        destination=Path(self.temp.name)/'signed-public-payments.json'
        result=self.manager.dispatch('lan.account_export',{'path':str(destination)})
        self.assertFalse(result['private_keys_exported']);self.assertEqual(destination.read_bytes(),profile.original())
        self.assertEqual(len(wire.decode_payment_document(destination.read_bytes(),self.service.anchor)),5000)
        with self.assertRaisesRegex(ValueError,'EXPORT_EXISTS'):self.manager.dispatch('lan.account_export',{'path':str(destination)})
        with self.assertRaisesRegex(ValueError,'EXPORT_DESTINATION'):self.manager.dispatch('lan.account_export',{'path':str(profile.root/'misplaced.json')})

    def test_intent_file_cannot_choose_sender_network_secret_fields_or_noncanonical_bytes(self):
        profile=self.create();path=Path(self.temp.name)/'intent.json'
        document={'schema':'gg.financial.payment-intent.v1','genesis_hash':self.service.anchor['genesis_hash'],
                  'sender':profile.public_address(),'payments':self.outputs()}
        for change in ({'sender':public_key(800).pubkey().hex()},{'genesis_hash':'0'*64},{'private_key':'PUBLIC forbidden marker'}):
            path.write_bytes(pack({**document,**change}))
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'INTENT_FILE_INVALID'):self.manager.dispatch('lan.account_review',{'path':str(path)})
        path.write_bytes(pack(document)+b'\n')
        with self.assertRaises(ValueError):self.manager.dispatch('lan.account_review',{'path':str(path)})
        self.assertEqual(profile.snapshot()['signed_batches'],0)

    def test_selected_profile_is_public_and_does_not_start_production_or_gain_voter_keys(self):
        self.create('Alice');bob=self.create('Bob');self.manager.dispatch('lan.account_select',{'profile':'Bob'})
        view=self.manager.snapshot();owned=view['financial_account_profiles']
        self.assertEqual(owned['selected_profile'],'Bob');self.assertEqual(self.service._selected_account,bob.public_address())
        self.assertEqual({row['role'] for row in owned['profiles']},{'account'})
        self.assertEqual(self.manager._validator_profiles,{})
        self.assertFalse(self.service._retry.snapshot()['worker_active'])
        self.assertNotIn('protected_key',pack(owned).decode());self.assertNotIn('signer',owned)

    def test_submit_failure_preserves_signed_original_and_does_not_claim_sent_or_applied(self):
        profile=self.create();self.manager.dispatch('lan.account_review',{'payments':self.outputs()});self.manager.dispatch('lan.account_sign',{})
        original=profile.original()
        with patch.object(self.service,'submit_signed',side_effect=ValueError('GG_FINANCIAL_SUBMISSION_UNAVAILABLE')):
            with self.assertRaisesRegex(ValueError,'SUBMISSION_UNAVAILABLE'):self.manager.dispatch('lan.account_submit',{})
        self.assertEqual(profile.original(),original);self.assertFalse(profile.snapshot()['payments_executed_asserted'])

    def test_closing_account_drops_signer_and_selection_without_stopping_owned_node(self):
        profile=self.create();peer=self.manager._peer
        self.manager.dispatch('lan.account_close',{})
        self.assertIsNone(profile._key);self.assertTrue(profile._closed)
        self.assertIs(self.manager._peer,peer);self.assertFalse(peer._cancel.is_set())
        self.assertIsNone(self.service._selected_account)
        self.manager.dispatch('lan.account_open',{'profile':'Alice'})
        self.assertEqual(self.manager._account_profiles['Alice'].public_address(),profile.public_address())
        self.assertEqual(self.manager._account_profiles['Alice'].snapshot()['signed_batches'],0)

    def test_account_status_separates_persisted_signer_proof_from_current_node_view_without_io(self):
        profile=self.create();address=profile.public_address();state={'height':4,'state_root':'b'*64,'accounts':None,
            'financial_dag':{},'account_tree':{'count':'2'}}
        self.service._certificate_info=({'state':state},(5,'c'*64),None)
        self.addCleanup(setattr,self.service,'_certificate_info',None)
        row={'address':address,'exists':True,'balance_atomic':'3','nonce':'7','state_height':4,'certificate_height':5,
             'state_root':'b'*64,'verification_scope':'SDK_CERTIFIED_ACCOUNT_MEMBERSHIP_OR_ABSENCE_NOT_FULL_HISTORY_REPLAY'}
        self.service._account_views[address]=row;changes=profile._db.total_changes
        result=self.manager.dispatch('lan.account_status',{})
        self.assertIsNone(result['account']);self.assertEqual(result['account_basis'],'LAST_PERSISTED_SIGNER_ACCOUNT_PROOF')
        self.assertEqual(result['observed_account']['state'],'CERTIFIED');self.assertEqual(result['observed_account']['value'],row)
        self.assertEqual(profile._db.total_changes,changes);self.assertIsNone(profile.anchor())
        self.service.requested_proof.assert_not_called()
        self.service._account_views.pop(address)
        result=self.manager.dispatch('lan.account_status',{})
        self.assertEqual(result['observed_account']['state'],'WAITING_FOR_ACCOUNT_PROOF');self.assertIsNone(result['observed_account']['value'])

    def test_public_account_export_cannot_write_into_node_or_validator_key_directories(self):
        from backend import gg_node_store as nodes,gg_consensus_profile as validators,gg_observer_profile as observers
        self.stack.enter_context(patch.object(observers,'ROOT',Path(self.temp.name)/'observers'))
        profile=self.create()
        self.manager.dispatch('lan.account_review',{'payments':self.outputs()});self.manager.dispatch('lan.account_sign',{})
        for root in (nodes.ROOT,validators.ROOT,observers.ROOT,accounts.ROOT):
            target=root/'misplaced-public-document.json'
            with self.subTest(root=str(root)),self.assertRaisesRegex(ValueError,'EXPORT_DESTINATION'):
                self.manager.dispatch('lan.account_export',{'path':str(target)})
            self.assertFalse(target.exists())


class OfflineAccountRuntimeTests(unittest.TestCase):
    def test_offline_profile_create_open_and_stop_do_not_need_or_create_a_node(self):
        with tempfile.TemporaryDirectory(prefix='gg-offline-account-runtime-') as directory,patch.object(accounts,'ROOT',Path(directory)/'accounts'),portable.session('PUBLIC offline account profile fixture'):
            manager=runtime.LanDagRuntime()
            try:
                view=manager.dispatch('lan.account_create',{'profile':'Alice'})
                address=view['financial_account_profiles']['profiles'][0]['public_key']
                self.assertIsNone(manager._peer);self.assertFalse(manager.active)
                self.assertEqual(manager.dispatch('lan.account_status',{})['state'],'UNBOUND')
                manager.stop();view=manager.dispatch('lan.account_open',{'profile':'Alice'})
                self.assertEqual(view['financial_account_profiles']['profiles'][0]['public_key'],address)
                self.assertIsNone(manager._peer);self.assertEqual(manager.dispatch('lan.account_status',{})['signed_batches'],0)
            finally:manager.stop()


if __name__=='__main__':unittest.main()
