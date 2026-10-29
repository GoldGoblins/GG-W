"""Private reveal bridge: approval gate, cancellation races and no public words."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

from PySide6.QtCore import QCoreApplication,QObject,Signal,QEvent
from PySide6.QtTest import QSignalSpy

from backend import wallet_recovery_ui as ui,wallet_approval as approval,wallet_mnemonic as mnemonic
from backend import sensitive_ui_guard as guard,omni_assets as store
from backend import live_mandate_store as mandates,task_scoped_action_grant as grants
from tests.test_live_mandate_store import _pending,_receipt

PUBLIC='11111111111111111111111111111111'
PASSWORD='public-fixture-password-only'
WORDS=['abandon']*11+['about']


class Host(QObject):
    walletMnemonicSecretReady=Signal(str)
    def __init__(self):
        super().__init__();self.requests=[];self.notices=[];self._shutdown_in_progress=False
        self._wallet_action_approval_handler=self.requests.append
        self.runtime=type('Runtime',(),{'_lock':threading.RLock(),'_closed':False,'_pending':None,'_active':''})()
    def _omni_runtime(self):return self.runtime
    def _wallet_operation_notice(self,*args):self.notices.append(args);return '{"public":true}'


def secret():
    return {'words':list(WORDS),'pubkey':PUBLIC,'address':PUBLIC,'word_count':12,
            'chain_id':mnemonic.SOL,'derivation_path':"m/44'/501'/0'/0'"}


class RecoveryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.host=Host();self.spy=QSignalSpy(self.host.walletMnemonicSecretReady)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store_patch=patch.object(store,'ROOT',self.root/'state');self.store_patch.start();self.addCleanup(self.store_patch.stop)
        self.descriptor_patch=patch.object(approval,'_descriptor',side_effect=self.descriptor);self.descriptor_patch.start();self.addCleanup(self.descriptor_patch.stop)
        self.addCleanup(approval.cancel_all)
        self.entered=set()
        self.enter_patch=patch.object(guard,'enter',side_effect=self.entered.add);self.enter_patch.start();self.addCleanup(self.enter_patch.stop)
        self.leave_patch=patch.object(guard,'leave',side_effect=self.entered.discard);self.leave_patch.start();self.addCleanup(self.leave_patch.stop)
        self.mandates=mandates.MandateStore(self.root/'mandates');self.mandates.initialize()
    def tearDown(self):
        ui.cancel_all(self.host)
        self.app.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    def descriptor(self,name,args):
        self.assertEqual(name,'reveal_mnemonic')
        return {'schema':'gg.wallet-operation.v1','operation':name,'chain_id':mnemonic.SOL,
                'state_root':str(store.ROOT.resolve()),'pubkey':args['pubkey'],
                'path':str(self.root/'ciphertext-only.ggmnemonic'),'ciphertext_sha256':'a'*64}
    def request(self):
        result=json.loads(ui.request(self.host,PUBLIC,PASSWORD))
        self.assertEqual(result['state'],'approval_required');self.assertTrue(result['request_id'])
        self.assertEqual(len(self.host.requests),1)
        return result,self.host.requests[0]
    def approve(self,identifier):
        context=approval.context(identifier)
        capture=hashlib.sha256((identifier+'fixture-capture').encode()).hexdigest()
        scope=hashlib.sha256((identifier+'fixture-scope').encode()).hexdigest()
        pending=_pending(capture=capture,scope=scope,risk='RED')
        pending['action_intent'].update(target_object_id=context['object_id'],target_source_revision=context['sha256'])
        mandates.put_pending(self.mandates,pending)
        record=mandates.approve(self.mandates,request_capture_sha256=capture,approval_scope_revision=scope,
            approver_id='human:fixture',mandate_assertion_sha256='e'*64,evaluation_receipt=_receipt(capture,scope,'e'*64))
        grants.publish_runtime_scope(grants.issue_from_approved_record(record),store_root=self.mandates.root,allowed_hosts=[])
        approval.bind_approval(identifier,record,store_root=self.mandates.root)

    def test_no_handler_invalid_input_and_shutdown_do_not_request_or_decrypt(self):
        with patch.object(mnemonic,'reveal') as reveal:
            self.host._wallet_action_approval_handler=None
            self.assertEqual(json.loads(ui.request(self.host,PUBLIC,PASSWORD))['error'],'WALLET_APPROVAL_REQUIRED')
            self.host._wallet_action_approval_handler=self.host.requests.append
            self.assertEqual(json.loads(ui.request(self.host,PUBLIC,'short'))['state'],'ERROR')
            self.assertEqual(json.loads(ui.request(self.host,'not-public-key',PASSWORD))['state'],'ERROR')
            self.host._shutdown_in_progress=True
            self.assertEqual(json.loads(ui.request(self.host,PUBLIC,PASSWORD))['error'],'WALLET_RECOVERY_CLOSED')
        reveal.assert_not_called();self.assertEqual(self.host.requests,[])

    def test_fresh_approval_required_and_public_metadata_has_no_password_or_words(self):
        with patch.object(mnemonic,'reveal') as reveal:
            result,identifier=self.request()
            with self.assertRaisesRegex(ValueError,'APPROVAL_REQUIRED'):approval.execute(identifier)
            reveal.assert_not_called();self.assertEqual(self.spy.count(),0)
            public=json.dumps({'response':result,'notice':self.host.notices,'operation':approval.request(identifier),
                               'host_attributes':{k:str(v) for k,v in vars(self.host).items() if k not in ('walletMnemonicSecretReady',)}})
            self.assertNotIn(PASSWORD,public);self.assertNotIn('abandon',public)
            for path in self.root.rglob('*'):
                if path.is_file():self.assertNotIn(PASSWORD.encode(),path.read_bytes())
        self.assertFalse(self.entered)

    def test_approved_callback_returns_none_and_only_private_signal_contains_words(self):
        result,identifier=self.request();self.approve(identifier)
        ordering=[]
        self.host.walletMnemonicSecretReady.connect(lambda raw:ordering.append('wallet-recovery:'+result['request_id'] in self.entered))
        with patch.object(mnemonic,'reveal',side_effect=lambda *_:secret()) as reveal:
            returned=approval.execute(identifier)
        self.assertIsNone(returned);reveal.assert_called_once_with(PUBLIC,PASSWORD)
        self.assertEqual(self.spy.count(),1)
        body=json.loads(self.spy.at(0)[0]);self.assertEqual(body['request_id'],result['request_id'])
        self.assertEqual(body['words'],WORDS);self.assertEqual(body['state'],'REVEALED')
        self.assertEqual(ordering,[True],'capture interlock must precede the words')
        self.assertEqual(self.entered,{'wallet-recovery:'+result['request_id']})
        self.assertNotIn(identifier,approval._tickets)
        self.assertNotIn(PASSWORD,json.dumps(self.host.notices))
        self.assertEqual(json.loads(ui.cancel(self.host,result['request_id']))['state'],'CANCELLED')
        self.assertFalse(self.entered)

    def test_cancellation_during_decrypt_never_emits_and_invalidates_before_authority_cancel(self):
        result,identifier=self.request();self.approve(identifier)
        began=threading.Event();finish=threading.Event();record=ui._records[self.host]
        def decrypt(*_):began.set();finish.wait(3);return secret()
        original=approval.cancel
        def checked_cancel(ticket):
            self.assertFalse(record.active)
            return original(ticket)
        with patch.object(mnemonic,'reveal',side_effect=decrypt),patch.object(approval,'cancel',side_effect=checked_cancel):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(approval.execute,identifier)
                self.assertTrue(began.wait(2))
                ui.cancel(self.host,result['request_id']);finish.set()
                self.assertIsNone(future.result(3))
        self.app.processEvents();self.assertEqual(self.spy.count(),0);self.assertFalse(self.entered)

    def test_capture_enter_failure_and_password_error_are_fixed_private_codes(self):
        for failure in ('decrypt','capture'):
            self.host.requests.clear();result,identifier=self.request();self.approve(identifier)
            reveal_error=ValueError(PASSWORD+' /private/fixture/path')
            with patch.object(mnemonic,'reveal',side_effect=reveal_error if failure=='decrypt' else lambda *_:secret()),\
                 patch.object(guard,'enter',side_effect=RuntimeError(PASSWORD) if failure=='capture' else self.entered.add):
                self.assertIsNone(approval.execute(identifier))
            body=json.loads(self.spy.at(self.spy.count()-1)[0])
            self.assertEqual(body['state'],'ERROR');self.assertEqual(body['error'],'WALLET_MNEMONIC_REVEAL_FAILED')
            self.assertNotIn('words',body);self.assertNotIn(PASSWORD,json.dumps(body));self.assertFalse(self.entered)

    def test_one_request_per_host_wrong_cancel_and_expiry_cleanup(self):
        result,identifier=self.request()
        second=json.loads(ui.request(self.host,PUBLIC,PASSWORD))
        self.assertEqual(second['error'],'WALLET_RECOVERY_BUSY');self.assertEqual(len(self.host.requests),1)
        ui.cancel(self.host,'wrong-id');self.assertTrue(ui._records[self.host].active)
        record=ui._records[self.host];ui._expired(record)
        self.assertFalse(record.active);self.assertNotIn(identifier,approval._tickets)
        self.assertNotIn(self.host,ui._records);self.assertFalse(self.entered)

    def test_shutdown_during_decrypt_suppresses_secret_and_cancel_all_releases_guard(self):
        result,identifier=self.request();self.approve(identifier)
        began=threading.Event();finish=threading.Event()
        def decrypt(*_):began.set();finish.wait(3);return secret()
        with patch.object(mnemonic,'reveal',side_effect=decrypt):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(approval.execute,identifier);self.assertTrue(began.wait(2))
                self.host._shutdown_in_progress=True;ui.cancel_all(self.host);finish.set()
                self.assertIsNone(future.result(3))
        self.app.processEvents();self.assertEqual(self.spy.count(),0);self.assertFalse(self.entered)

    def test_cancellation_while_capture_enters_cannot_emit_or_leave_late_guard(self):
        result,identifier=self.request();self.approve(identifier)
        began=threading.Event();finish=threading.Event()
        def enter(owner):self.entered.add(owner);began.set();finish.wait(3)
        with patch.object(mnemonic,'reveal',side_effect=lambda *_:secret()),patch.object(guard,'enter',side_effect=enter):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(approval.execute,identifier);self.assertTrue(began.wait(2))
                ui.cancel(self.host,result['request_id']);finish.set()
                self.assertIsNone(future.result(3))
        self.app.processEvents();self.assertEqual(self.spy.count(),0);self.assertFalse(self.entered)

    def test_actual_crypto_runtime_never_receives_words_as_an_action_result(self):
        from backend.crypto_ui_runtime import CryptoUiRuntime
        runtime=CryptoUiRuntime(self.host,snapshot=lambda:{'wallet':{},'lab':{},'chart':{},'assets':[]},ttl=100)
        self.host.runtime=runtime
        try:
            result,identifier=self.request();self.approve(identifier)
            with patch.object(mnemonic,'reveal',side_effect=lambda *_:secret()):
                public=runtime.submit('reveal_mnemonic',lambda:approval.execute(identifier))
                deadline=time.monotonic()+3
                while runtime._running and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.005)
                self.app.processEvents()
                self.assertFalse(runtime._running);self.assertEqual(self.spy.count(),1)
                public+='\n'+runtime.snapshot()
            self.assertNotIn('abandon',public);self.assertNotIn(PASSWORD,public)
            self.assertNotIn('"words"',public)
            self.assertEqual(json.loads(runtime.snapshot())['ui_operation']['state'],'done')
        finally:runtime.close()

    def test_parent_destruction_cancels_pending_ticket_and_timer(self):
        other=Host()
        result=json.loads(ui.request(other,PUBLIC,PASSWORD));identifier=other.requests[0]
        record=ui._records[other]
        self.assertTrue(record.timer.isSingleShot());self.assertLessEqual(record.timer.interval(),600000)
        other.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        self.assertFalse(record.active);self.assertNotIn(identifier,approval._tickets)
        self.assertFalse(self.entered)


if __name__=='__main__':unittest.main()
