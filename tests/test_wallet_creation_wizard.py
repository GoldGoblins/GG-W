"""Local wizard lifecycle with published BIP39 vectors only; no screenshots."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QObject,QPointF,Qt,QUrl,Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent,QQmlEngine,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy,QTest

ROOT=Path(__file__).resolve().parents[1]


class PublicVectorHost(QObject):
    """Known all-zero BIP39 vectors are public test material, never user keys."""
    def __init__(self):
        super().__init__();self.calls=[];self.cancelled=[];self.count=24;self.word_values=[];self.root=None;self.claimed=False
    @Slot(str,str,int,str,result=str)
    def walletMnemonicBegin(self,label,purpose,count,method):
        self.calls.append((label,purpose,count,method));self.count=count;self.method=method
        self.word_values=['abandon']*(count-1)+(['about'] if count==12 else ['art'])
        return json.dumps(dict(session_id='public-fixture-session',words=self.word_values.copy(),state='WORDS'))
    @Slot(str,result=str)
    def walletMnemonicChallenge(self,_session):
        assert self.root.property('revealedCount')==0,'Full phrase must be cleared before challenge request'
        return json.dumps(dict(indices=[1,self.count//2,self.count],state='CHALLENGE'))
    @Slot(str,str,result=str)
    def walletMnemonicVerify(self,_session,answers):
        values=json.loads(answers)
        expected={str(n):self.word_values[n-1] for n in (1,self.count//2,self.count)}
        if values!=expected:return json.dumps(dict(error='TEST_WORD_MISMATCH',state='CHALLENGE'))
        return json.dumps(dict(state='VERIFIED_NEEDS_PASSWORD' if self.method=='AI' else 'READY',address='11111111111111111111111111111111',derivation_path="m/44'/501'/0'/0'"))
    @Slot(str,str,result=str)
    def walletMnemonicSetPassword(self,_session,password):
        if len(password)<12:return json.dumps(dict(error='TEST_PASSWORD_SHORT'))
        return json.dumps(dict(state='READY'))
    @Slot(str,str,str,str,result=str)
    def walletMnemonicRestore(self,phrase,label,purpose,method):
        assert not self.root.findChild(QQuickItem,'mnemonicRestorePhrase').property('text')
        self.method=method;count=len(phrase.split())
        if count not in (12,24):return json.dumps(dict(error='PUBLIC_FIXTURE_WORD_COUNT'))
        return json.dumps(dict(session_id='public-restored-session',state='VERIFIED_NEEDS_PASSWORD' if method=='AI' else 'READY',address='11111111111111111111111111111111',word_count=count,derivation_path="m/44'/501'/0'/0'"))
    @Slot(str,result=str)
    def walletMnemonicCancel(self,session):
        if self.claimed:return json.dumps(dict(state='CLAIMED',error='WALLET_MNEMONIC_CLAIMED'))
        self.cancelled.append(session);self.word_values=[];return json.dumps(dict(state='CANCELLED'))


class WalletCreationWizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.engine=QQmlEngine();self.host=PublicVectorHost();self.warnings=[]
        self.engine.warnings.connect(lambda rows:self.warnings.extend(row.toString() for row in rows))
        self.component=QQmlComponent(self.engine)
        source='''import QtQuick
import COMPONENTS
Window {width:360;height:600;visible:true;WalletCreationWizard{objectName:"wizard";anchors.fill:parent}}
'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
        self.component.setData(source.encode(),QUrl.fromLocalFile(str(ROOT/'qml/wizard-fixture.qml')))
        self.assertTrue(self.component.isReady(),[error.toString() for error in self.component.errors()])
        self.window=self.component.create()
        self.root=self.window.findChild(QQuickItem,'wizard');self.root.setProperty('surfaceHost',self.host);self.host.root=self.root
        self.settle()
    def tearDown(self):
        self.js('cancel()');self.window.close();self.window.deleteLater();self.engine.deleteLater();self.app.processEvents()
        self.assertFalse(self.warnings,self.warnings)
    def settle(self):
        QTest.qWait(20)
        def polish(item):
            item.ensurePolished()
            for child in item.childItems():polish(child)
        polish(self.window.contentItem());self.app.processEvents()
    def js(self,text):
        expression=QQmlExpression(qmlContext(self.root),self.root,text);value=expression.evaluate()
        self.assertFalse(expression.hasError(),expression.error().toString())
        return value[0] if isinstance(value,tuple) else value
    def named(self,name):
        item=self.root.findChild(QQuickItem,name);self.assertIsNotNone(item,name);return item
    def items(self,root):
        yield root
        for child in root.childItems():yield from self.items(child)
    def click(self,name):
        item=self.named(name);self.assertTrue(item.isVisible() and item.isEnabled(),name)
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint()
        self.assertGreaterEqual(point.y(),0);self.assertLess(point.y(),self.window.height())
        QTest.mouseClick(self.window,Qt.LeftButton,Qt.NoModifier,point);self.settle()
    def start(self,count=24,mode='SELF_CUSTODY'):
        self.js("open('STORAGE')");self.root.setProperty('wordCount',count);self.root.setProperty('accountMode',mode)
        self.js('showWarning()');self.settle();self.assertEqual(self.root.property('phase'),'WARNING')
        self.assertFalse(self.named('mnemonicNext').isEnabled());self.js('reveal()');self.assertFalse(self.host.calls)
        self.named('mnemonicWarningAck').setProperty('checked',True);self.click('mnemonicNext')
        self.assertEqual(self.root.property('phase'),'REVEAL');self.assertEqual(self.root.property('revealedCount'),count)
    def next_to_challenge(self):
        self.named('mnemonicWrittenAck').setProperty('checked',True);self.click('mnemonicNext')
        self.assertEqual(self.root.property('phase'),'CHALLENGE');self.assertEqual(self.root.property('revealedCount'),0)
    def fill_correct(self):
        for name,n in zip(('mnemonicAnswer1','mnemonicAnswer2','mnemonicAnswer3'),(1,self.host.count//2,self.host.count)):
            self.named(name).setProperty('text',self.host.word_values[n-1])
    def test_warning_before_begin_show_once_and_transient_visibility_has_no_expiry(self):
        for count in (12,24):
            self.host.calls=[];self.start(count)
            self.assertEqual(self.host.calls[-1][1:],('STORAGE',count,'PAPER'))
            self.root.setVisible(False);self.settle();self.root.setVisible(True);self.settle()
            self.assertEqual(self.root.property('revealedCount'),count)
            self.next_to_challenge();before=len(self.host.calls);self.js('reveal()')
            self.assertEqual(len(self.host.calls),before);self.assertEqual(self.root.property('revealedCount'),0)
            self.js('cancel()');self.assertEqual(self.root.property('_sessionId'),'')
    def test_wrong_answers_do_not_finish_and_three_attempts_cancel(self):
        self.start();self.next_to_challenge();actions=QSignalSpy(self.root.actionRequested)
        for attempt in range(3):
            for name in ('mnemonicAnswer1','mnemonicAnswer2','mnemonicAnswer3'):self.named(name).setProperty('text','invalid')
            self.click('mnemonicNext');self.assertEqual(actions.count(),0)
        self.assertEqual(self.root.property('phase'),'SETUP');self.assertTrue(self.host.cancelled)
        self.assertEqual(self.root.property('revealedCount'),0)
    def test_successful_challenge_emits_only_public_approval_request_and_cancel_clears_ticket(self):
        self.start(mode='AI_ASSISTED');self.assertEqual(self.host.calls[-1][-1],'AI')
        self.next_to_challenge();self.fill_correct();self.click('mnemonicNext')
        self.assertEqual(self.root.property('phase'),'PASSWORD');self.assertFalse(self.named('mnemonicNext').isEnabled())
        self.named('mnemonicVaultPassword').setProperty('text','public-fixture-password')
        self.named('mnemonicVaultPasswordAgain').setProperty('text','different-fixture-password')
        self.assertFalse(self.named('mnemonicNext').isEnabled())
        self.named('mnemonicVaultPasswordAgain').setProperty('text','public-fixture-password');self.click('mnemonicNext')
        self.assertFalse(self.named('mnemonicVaultPassword').property('text'));self.assertFalse(self.named('mnemonicVaultPasswordAgain').property('text'))
        self.assertEqual(self.root.property('phase'),'READY');self.assertEqual(self.root.property('revealedCount'),0)
        actions=QSignalSpy(self.root.actionRequested);self.click('mnemonicNext')
        self.assertEqual(self.root.property('phase'),'APPROVAL');self.assertEqual(actions.count(),1)
        name,args=actions.at(0);self.assertEqual(name,'create_wallet')
        if hasattr(args,'toVariant'):args=args.toVariant()
        self.assertEqual(set(args),{'label','mnemonic_session'})
        self.assertNotIn('abandon',json.dumps(args));self.assertFalse(self.named('mnemonicNext').isEnabled())
        self.click('mnemonicCancel');self.assertEqual(self.root.property('_sessionId'),'');self.assertTrue(self.host.cancelled)
    def test_hardware_choices_do_not_generate_local_words(self):
        for method in ('LEDGER','TANGEM','EXTERNAL'):
            self.js("open('TRADING')");self.root.setProperty('method',method);self.settle()
            self.assertFalse(self.named('mnemonicNext').isEnabled());self.js('showWarning()');self.js('reveal()')
            self.assertFalse(self.host.calls);self.assertEqual(self.root.property('revealedCount'),0)
    def test_account_control_and_purpose_are_independent_choices(self):
        self.click('mnemonicAiAssisted');self.assertEqual(self.root.property('method'),'AI')
        self.click('mnemonicPurposeStorage');self.assertEqual(self.root.property('method'),'AI')
        self.click('mnemonicSelfCustody');self.assertEqual(self.root.property('method'),'PAPER')
        self.assertEqual(self.root.property('purpose'),'STORAGE');self.assertFalse(self.root.property('storeLocally'))
        self.assertFalse(self.host.calls)
    def test_claimed_creation_cannot_silently_cancel_an_in_progress_save(self):
        self.start();self.next_to_challenge();self.fill_correct();self.click('mnemonicNext');self.click('mnemonicNext')
        closed=QSignalSpy(self.root.closeRequested);self.host.claimed=True;self.click('mnemonicCancel')
        self.assertEqual(closed.count(),0);self.assertTrue(self.root.property('_sessionId'))
        self.assertEqual(self.root.property('revealedCount'),0)
        self.host.claimed=False;self.click('mnemonicCancel');self.assertEqual(closed.count(),1)
    def test_restore_is_private_and_never_reveals_full_phrase_or_auto_saves(self):
        self.js("openRestore('STORAGE')");self.assertEqual(self.root.property('phase'),'RESTORE')
        field=self.named('mnemonicRestorePhrase');self.assertTrue(field.property('sensitiveInput'))
        field.setProperty('text',' '.join(['abandon']*11+['about']))
        actions=QSignalSpy(self.root.actionRequested);self.click('mnemonicNext')
        self.assertEqual(self.root.property('phase'),'READY');self.assertFalse(field.property('text'))
        self.assertEqual(self.root.property('revealedCount'),0);self.assertEqual(actions.count(),0)
        self.click('mnemonicNext');self.assertEqual(actions.count(),1)
        self.js('complete()');self.assertFalse(self.root.property('_submitted'))
        self.js("open('TRADING')");self.assertEqual(self.root.property('phase'),'SETUP')
    def test_external_method_has_functional_public_address_handoff_without_key_generation(self):
        self.root.setProperty('method','LEDGER');self.settle();external=QSignalSpy(self.root.externalRequested)
        self.click('mnemonicExternalConnect');self.assertEqual(external.count(),1)
        self.assertEqual(external.at(0),['LEDGER','TRADING']);self.assertFalse(self.host.calls)
    def test_failed_matching_approval_revokes_ticket_without_silently_creating_a_new_identity(self):
        self.start();self.next_to_challenge();self.fill_correct();self.click('mnemonicNext');self.click('mnemonicNext')
        count=len(self.host.calls)
        self.root.setProperty('state',{'ui_operation':{'name':'refresh_wallet','state':'error'}});self.settle()
        self.assertEqual(self.root.property('phase'),'APPROVAL')
        self.root.setProperty('state',{'ui_operation':{'name':'create_wallet','state':'rejected'}});self.settle()
        self.assertEqual(self.root.property('phase'),'SETUP');self.assertFalse(self.root.property('_submitted'))
        self.assertEqual(self.root.property('_sessionId'),'');self.assertEqual(len(self.host.calls),count)
        self.assertIn('Återställ',self.root.property('errorText'))
    def test_word_grid_numbers_and_controls_fit_without_capturing_secret_ui(self):
        self.start(24)
        self.assertTrue(self.named('mnemonicWordsGrid').property('privateSensitive'))
        for width,height in ((328,520),(360,600),(640,520),(900,600)):
            self.window.setWidth(width);self.window.setHeight(height);self.settle()
            cells=[item for item in self.items(self.root) if item.objectName()=='mnemonicWordCell'];self.assertEqual(len(cells),24)
            for cell in cells:
                self.assertGreaterEqual(cell.width(),80);self.assertGreaterEqual(cell.height(),17)
                p=cell.mapToScene(QPointF(0,0));self.assertGreaterEqual(p.y(),0)
                self.assertLessEqual(p.y()+cell.height(),height)
            ack=self.named('mnemonicWrittenAck');p=ack.mapToScene(QPointF(0,0))
            self.assertLessEqual(p.y()+ack.height(),self.named('mnemonicCancel').mapToScene(QPointF(0,0)).y())


if __name__=='__main__':unittest.main()
