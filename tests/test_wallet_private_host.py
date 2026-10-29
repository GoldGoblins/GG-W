"""Fresh host/QML privacy verification using public BIP39 vectors only.

No real host startup, node, network, user state, pixel capture or random phrase.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import weakref
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest

from backend import omni_assets as store, sensitive_ui_guard as guard
from backend import wallet_approval as approval, wallet_mnemonic as mnemonic
from backend.chat_surface_host import ChatSurfaceHost

ROOT = Path(__file__).resolve().parents[1]
PHRASE = ' '.join(['abandon'] * 11 + ['about'])


class MemoryChannel:
    """No mutation of the application's actual cross-process capture state."""
    def __init__(self): self.blocked = False; self.epoch = 0
    def call(self, blocked=None, *, token=False):
        if blocked is not None:
            self.blocked = blocked
            if blocked: self.epoch += 1
        return (self.blocked, self.epoch) if token else self.blocked


class PrivateHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-private-host-public-vector-')
        self.addCleanup(self.temp.cleanup)
        self.directory = patch.object(store, 'ROOT', Path(self.temp.name) / 'state')
        self.directory.start(); self.addCleanup(self.directory.stop)
        store.bootstrap()
        self.channel = MemoryChannel()
        for mocked in (patch.object(guard, '_channel', self.channel),
                       patch.object(guard, '_owners', set()),
                       patch('backend.live_vision.stop_if_running')):
            mocked.start(); self.addCleanup(mocked.stop)
        self.addCleanup(mnemonic.cancel_all); self.addCleanup(approval.cancel_all)
        self.host = ChatSurfaceHost.__new__(ChatSurfaceHost); QObject.__init__(self.host)
        self.public = [QSignalSpy(getattr(self.host, name)) for name in
                       ('omniStatusUpdated', 'walletAccountRolesUpdated', 'cryptoStatusUpdated',
                        'walletMnemonicSecretReady')]

    def begin(self):
        with patch.object(mnemonic._bip39(), 'generate', return_value=PHRASE):
            value = json.loads(self.host.walletMnemonicBegin('Public fixture', 'STORAGE', 12, 'PAPER'))
        self.assertEqual(value['state'], 'DISPLAY')
        self.assertEqual(value['words'], PHRASE.split())
        return value

    def test_actual_private_slots_clear_owned_paper_words_and_publish_only_public_descriptor(self):
        with patch.object(ChatSurfaceHost, '_omni_runtime', side_effect=AssertionError('PRIVATE_SLOT_STARTED_RUNTIME')):
            begin = self.begin(); identifier = begin['session_id']
            owned = mnemonic._sessions[identifier].phrase
            self.assertTrue(guard.active()); self.assertFalse(self.host.walletCaptureAllowed(0))
            for raw in ('invalid', '[]', '{', '"public-invalid-fixture"'):
                self.assertEqual(json.loads(self.host.walletMnemonicVerify(identifier, raw)),
                                 {'error': 'WALLET_MNEMONIC_OPERATION_FAILED'})
            self.assertTrue(owned)
            challenge = json.loads(self.host.walletMnemonicChallenge(identifier))
            self.assertEqual(challenge['state'], 'CHALLENGE')
            self.assertFalse(owned); self.assertFalse(guard.active())
            replay = json.loads(self.host.walletMnemonicChallenge(identifier))
            self.assertEqual(replay, {'error': 'WALLET_MNEMONIC_OPERATION_FAILED'})
            answers = {str(i): PHRASE.split()[i-1] for i in challenge['indices']}
            ready = json.loads(self.host.walletMnemonicVerify(identifier, json.dumps(answers)))
            self.assertEqual(ready['state'], 'READY'); self.assertNotIn('words', ready)
            self.assertEqual(json.loads(self.host.walletMnemonicVerify(identifier, json.dumps(answers))),
                             {'error': 'WALLET_MNEMONIC_OPERATION_FAILED'})
            ticket = approval.stage('create_wallet', {'label': 'Public fixture', 'mnemonic_session': identifier}, lambda: None)
            descriptor = json.dumps(approval._ticket(ticket).descriptor)
            request = json.dumps(approval.request(ticket))
            for raw in (descriptor, request):
                self.assertNotIn('abandon', raw); self.assertNotIn('password', raw)
                self.assertNotIn('words', raw); self.assertNotIn('commitment', raw)
            for operation in ('reveal_mnemonic', 'export_mnemonic'):
                self.assertEqual(json.loads(self.host.omniAction(operation, '{}')),
                                 {'error': 'WALLET_PRIVATE_INTERFACE_REQUIRED'})
            self.assertTrue(all(spy.count() == 0 for spy in self.public))

    def test_accessibility_labels_filter_passwords_and_sensitive_ancestors_without_global_lock(self):
        self.assertFalse(guard.active())
        class Item:
            def __init__(self, parent=None, **props): self.props=props; self.parent=parent
            def property(self, key): return self.props.get(key)
            def parentItem(self): return self.parent
        self.assertEqual(self.host._desk_item_label(Item(text='public label', echoMode=0)), 'public label')
        for props in ({'echoMode': 2}, {'echoMode': 1}, {'sensitiveInput': True}, {'privateSensitive': True}):
            self.assertEqual(self.host._desk_item_label(Item(text='public fixture word', **props)), '')
            self.assertEqual(self.host._desk_item_label(Item(Item(**props), text='public fixture descendant')), '')

    def test_qml_capture_fences_active_and_changed_epoch_before_save_without_pixels(self):
        class Result:
            def __init__(self): self.saved=0
            def saveToFile(self, path): self.saved+=1; return True
        class Content:
            def __init__(self, before=None): self.result=Result(); self.before=before; self.calls=0
            def grabToImage(self, callback):
                self.calls+=1
                def deliver():
                    if self.before: self.before()
                    callback(self.result)
                QTimer.singleShot(0, deliver); return True
        with patch.object(ChatSurfaceHost, '_desk_content_item', return_value=Content()) as getter:
            guard.enter('public-test')
            self.assertFalse(self.host._desk_grab_qml('unused-public-path')); getter.assert_not_called()
            guard.leave('public-test')
        for transient in (False, True):
            def change(transient=transient):
                guard.enter('public-test')
                if transient: guard.leave('public-test')
            content=Content(change)
            with patch.object(ChatSurfaceHost, '_desk_content_item', return_value=content):
                self.assertFalse(self.host._desk_grab_qml('unused-public-path'))
            self.assertEqual(content.result.saved, 0); guard.leave('public-test')
        content=Content()
        with patch.object(ChatSurfaceHost, '_desk_content_item', return_value=content):
            self.assertTrue(self.host._desk_grab_qml('unused-public-path'))
        self.assertEqual(content.result.saved, 1)
        self.app.processEvents()
        self.assertFalse(any(timer.isActive() for timer in self.host.findChildren(QTimer)))

    def test_real_wallet_actions_embeds_private_wizard_and_completes_public_address_handoff(self):
        vector = patch.object(mnemonic._bip39(), 'generate', return_value=PHRASE)
        vector.start(); self.addCleanup(vector.stop)
        engine=QQmlEngine(); component=QQmlComponent(engine); warnings=[]
        engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
        source=('import QtQuick\nimport '+json.dumps((ROOT/'qml/components').as_uri())+
                '\nWindow{width:640;height:650;visible:true;WalletActions{anchors.fill:parent}}')
        component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT/'qml/public-host-fixture.qml')))
        self.assertTrue(component.isReady(), [row.toString() for row in component.errors()])
        window=component.create(); self.assertIsNotNone(window)
        actions=window.findChild(QQuickItem, 'walletActions')
        wizard=window.findChild(QQuickItem, 'walletCreationWizard')
        recovery=window.findChild(QQuickItem, 'walletRecoveryPanel')
        self.assertIsNotNone(wizard); self.assertIsNotNone(recovery)
        actions.setProperty('surfaceHost', self.host)
        def js(item, expression):
            evaluator=QQmlExpression(qmlContext(item), item, expression); value=evaluator.evaluate()
            self.assertFalse(evaluator.hasError(), evaluator.error().toString())
            return value[0] if isinstance(value, tuple) else value
        def settle(): QTest.qWait(20); self.app.processEvents()
        def named(name):
            item=wizard.findChild(QQuickItem, name); self.assertIsNotNone(item, name); return item
        def click(name):
            item=named(name); self.assertTrue(item.isVisible() and item.isEnabled(), name)
            point=item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
            QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point); settle()
        try:
            js(actions, "open('create','','')"); wizard.setProperty('wordCount', 12); settle()
            click('mnemonicNext'); named('mnemonicWarningAck').setProperty('checked', True); click('mnemonicNext')
            self.assertEqual(wizard.property('revealedCount'), 12); self.assertTrue(guard.active())
            identifier=wizard.property('_sessionId'); owned=mnemonic._sessions[identifier].phrase
            named('mnemonicWrittenAck').setProperty('checked', True); click('mnemonicNext')
            self.assertEqual(wizard.property('revealedCount'), 0); self.assertFalse(owned); self.assertFalse(guard.active())
            indices=js(wizard, 'JSON.stringify(_indices)'); indices=json.loads(indices)
            for name, index in zip(('mnemonicAnswer1','mnemonicAnswer2','mnemonicAnswer3'), indices):
                named(name).setProperty('text', PHRASE.split()[index-1])
            click('mnemonicNext'); self.assertEqual(wizard.property('phase'), 'READY')
            address=actions.property('creationPublicAddress'); self.assertTrue(address)
            signals=QSignalSpy(actions.actionRequested); click('mnemonicNext')
            self.assertEqual(signals.count(), 1); name,args=signals.at(0)
            if hasattr(args, 'toVariant'): args=args.toVariant()
            self.assertEqual(name, 'create_wallet'); self.assertEqual(set(args), {'label','mnemonic_session'})
            self.assertNotIn('abandon', json.dumps(args))
            chain=store.NATIVE_SOL.split('/')[0]
            actions.setProperty('state', {'wallet_overview': {'accounts':[{'id':'public-account','chain_id':chain,'address':address}]},
                                          'ui_operation': {'name':'create_wallet','state':'done'}})
            settle(); self.assertEqual(actions.property('page'), 'receive')
            self.assertEqual(actions.property('accountId'), 'public-account')
            self.assertEqual(wizard.property('_sessionId'), ''); self.assertFalse(wizard.property('_submitted'))
            js(actions, "open('create','','')"); settle()
            self.assertEqual(wizard.property('phase'), 'SETUP')
            self.assertFalse(any(spy.count() for spy in self.public))
        finally:
            js(wizard, 'cancel()'); window.close(); window.deleteLater(); engine.deleteLater(); self.app.processEvents()
        self.assertFalse(warnings, warnings)

    def test_hiding_revealed_recovery_clears_words_cancels_actual_record_and_releases_guard(self):
        from backend import wallet_recovery_ui as recovery
        engine=QQmlEngine(); component=QQmlComponent(engine)
        source=('import QtQuick\nimport '+json.dumps((ROOT/'qml/components').as_uri())+
                '\nWindow{width:640;height:650;visible:true;WalletRecoveryPanel{anchors.fill:parent}}')
        component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT/'qml/public-recovery-lifecycle.qml')))
        self.assertTrue(component.isReady(), [row.toString() for row in component.errors()])
        window=component.create(); panel=window.findChild(QQuickItem, 'walletRecoveryPanel')
        panel.setProperty('surfaceHost', self.host)
        address='11111111111111111111111111111111'
        panel.setProperty('pubkey', address); panel.setProperty('_expectedPubkey', address)
        panel.setProperty('_requestId', 'public-lifecycle-fixture'); panel.setProperty('phase', 'PENDING')
        record=recovery._Record('public-lifecycle-fixture', 'public-recovery-lifecycle')
        record.host_ref=weakref.ref(self.host); record.expires_at=time.time()+60
        record.monotonic_deadline=time.monotonic()+60
        # Stage only a UI lifecycle record. No decryption, ticket execution or
        # approval bypass takes place; words are the published all-zero vector.
        recovery._records[self.host]=record; guard.enter(record.owner)
        try:
            self.host.walletMnemonicSecretReady.emit(json.dumps({'request_id':record.request_id,
                'state':'REVEALED','words':PHRASE.split(),'pubkey':address}))
            QTest.qWait(20); self.assertEqual(panel.property('revealedCount'), 12)
            panel.setVisible(False); QTest.qWait(20)
            self.assertEqual(panel.property('revealedCount'), 0)
            self.assertFalse(record.active); self.assertNotIn(self.host, recovery._records)
            self.assertFalse(guard.active())
        finally:
            recovery.cancel_all(self.host)
            window.close(); window.deleteLater(); engine.deleteLater(); self.app.processEvents()


if __name__ == '__main__': unittest.main()
