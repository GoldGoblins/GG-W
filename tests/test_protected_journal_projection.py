"""Exact own-journal references and cached display; no network/native claims."""
from copy import deepcopy
import threading
import unittest

from backend import gg_protected_journal as journals,terminal_cli
from tests import test_financial_account as account_fixtures
from tests import test_protected_journal_rotation as rotation_fixtures


class ExactProtectedJournalProjectionTests(unittest.TestCase):
    setUp=account_fixtures.ProtectedFinancialAccountTests.setUp
    close_profiles=account_fixtures.ProtectedFinancialAccountTests.close_profiles
    create=account_fixtures.ProtectedFinancialAccountTests.create
    open=account_fixtures.ProtectedFinancialAccountTests.open
    bound=account_fixtures.ProtectedFinancialAccountTests.bound
    packet=account_fixtures.ProtectedFinancialAccountTests.packet
    outputs=account_fixtures.ProtectedFinancialAccountTests.outputs
    signed=rotation_fixtures.ProtectedJournalRotationTests.signed

    def test_global_selector_is_exact_decimal_and_foreign_reference_never_rebinds_wallet(self):
        profile=self.bound();raw=self.signed(profile,0);reference=profile.next_batch_reference()
        self.assertEqual(reference['number'],'2')
        for value in ('9007199254740993','9223372036854775807'):
            self.assertEqual(str(journals.number(value)),value)
            with self.assertRaisesRegex(ValueError,'BATCH_SELECTOR'):profile.original(value)
        with self.assertRaisesRegex(ValueError,'USE_DECIMAL'):profile.original(9007199254740993)
        for value in (True,1.0,'01','-1','9223372036854775808'):
            with self.subTest(value_type=type(value).__name__),self.assertRaises(ValueError):journals.number(value)
        selected=profile.next_batch_reference();selected['number']='1';selected['previous_head']=rotation_fixtures.accounts._empty(profile.public_address())
        self.assertEqual(profile.original(selected),raw)
        for field,value in (('account_key','f'*64),('genesis_hash','a'*64),('previous_head','0'*64),('number',1)):
            bad=deepcopy(selected);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):profile.original(bad)
        self.assertEqual(profile.original('1'),raw);self.assertEqual(profile.snapshot()['next_signing_nonce'],'1')

    def test_cached_journal_observation_does_not_wait_for_the_real_signer_lock(self):
        profile=self.bound();self.signed(profile,0);entered=threading.Event();release=threading.Event();done=threading.Event();result=[]
        def hold():
            with profile._lock:entered.set();release.wait(2)
        def observe():
            try:result.append(profile.journal_observation())
            finally:done.set()
        writer=threading.Thread(target=hold,name='owned-journal-test-held-writer');reader=threading.Thread(target=observe,name='owned-journal-test-observer')
        writer.start()
        try:
            self.assertTrue(entered.wait(1));reader.start();completed_while_locked=done.wait(.5)
        finally:
            release.set();writer.join(2)
            if reader.ident is not None:reader.join(2)
        self.assertFalse(writer.is_alive());self.assertFalse(reader.is_alive())
        self.assertTrue(completed_while_locked,'observation waited on signer/archive I/O lock')
        self.assertEqual(result[0]['signed_batches_exact'],'1')
        self.assertFalse(result[0]['journal']['native_global_state_authority'])

    def test_foreground_keeps_large_own_counts_separate_from_native_applied_and_finality(self):
        # Pure presentation fixture; these large numbers do not fabricate a
        # protected journal, SDK certificate, account balance or execution run.
        exact='9007199254740993'
        journal=journals.journal_status('ACCOUNT_ORIGINALS',journals.empty('ACCOUNT_ORIGINALS','a'*64),0,0,0)
        journal.update(total_records=exact,archived_records=exact,archive_segments='9007199254740992')
        own={'schema':'gg.protected.journal-sources.v1','accounts':[{'profile':'Alice','address':'b'*64,
              'signed_batches_exact':exact,'journal':journal}]}
        pools=[{'name':'Pool','retained_events':None,'retained_events_exact':exact,'own_journal':dict(journal,kind='POOL_EVENTS'),'money_from_shares_asserted':False}]
        body={'state':'WAITING_FOR_CERTIFICATE','protocol_network':{'own_journals':own,'pools':pools},'certified_transactions':None,'certified_blocks':None}
        result=terminal_cli.foreground_summary('protocol.light_start',body)
        self.assertEqual(result['own_journals'],own);self.assertEqual(result['pools'],pools)
        self.assertEqual(result['own_journals']['accounts'][0]['signed_batches_exact'],exact)
        self.assertIsNone(result['applied_payments']);self.assertFalse(result['payments_executed_from_transport_ack'])
        self.assertFalse(result['certificate_is_network_liveness'])
        self.assertIsNone(journals.public_number(int(exact)))

    def test_partial_pool_cold_context_cannot_sign_or_report_ready(self):
        # A partial internal verifier is not a transport-supplied trusted flag.
        with self.assertRaisesRegex(ValueError,'COLD_AUDIT_REQUIRED'):
            rotation_fixtures.pools._PoolColdAudit(None,lambda:None)
        with self.assertRaisesRegex(ValueError,'READBACK_REQUIRED'):
            journals._PublishedSegment(None,'a'*64,b'',{},(),())
