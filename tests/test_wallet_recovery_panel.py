"""Recovery view with public BIP39 fixtures only; never captures the view."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QObject,QPointF,QUrl,Signal,Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent,QQmlEngine,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

ROOT=Path(__file__).resolve().parents[1]
ADDRESS='11111111111111111111111111111111'


class Host(QObject):
    walletMnemonicSecretReady=Signal(str)
    def __init__(self):super().__init__();self.requests=[];self.cancelled=[];self.root=None
    @Slot(str,str,result=str)
    def walletMnemonicReveal(self,address,password):
        self.requests.append(address)
        return json.dumps(dict(request_id='public-fixture-'+str(len(self.requests)),state='approval_required'))
    @Slot(str,result=str)
    def walletMnemonicCancelReveal(self,request):
        assert self.root.property('revealedCount')==0
        assert self.root.property('_requestId')==''
        self.cancelled.append(request);return json.dumps(dict(state='CANCELLED'))


class WalletRecoveryPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QGuiApplication.instance() or QGuiApplication([])
    def setUp(self):
        self.host=Host();self.engine=QQmlEngine();self.warnings=[]
        self.engine.warnings.connect(lambda rows:self.warnings.extend(row.toString() for row in rows))
        self.component=QQmlComponent(self.engine)
        source='import QtQuick\nimport '+json.dumps((ROOT/'qml/components').as_uri())+'\nWindow{width:360;height:600;visible:true;WalletRecoveryPanel{objectName:"panel";anchors.fill:parent}}'
        self.component.setData(source.encode(),QUrl.fromLocalFile(str(ROOT/'qml/recovery-fixture.qml')))
        self.assertTrue(self.component.isReady(),[error.toString() for error in self.component.errors()])
        self.window=self.component.create();self.root=self.window.findChild(QQuickItem,'panel')
        self.root.setProperty('surfaceHost',self.host);self.host.root=self.root;self.js('open('+json.dumps(ADDRESS)+')');self.settle()
    def tearDown(self):
        self.js('cancel()');self.window.close();self.window.deleteLater();self.engine.deleteLater();self.app.processEvents()
        self.assertFalse(self.warnings,self.warnings)
    def settle(self):
        QTest.qWait(20)
        for item in self.items(self.window.contentItem()):item.ensurePolished()
        self.app.processEvents()
    def items(self,root):
        yield root
        for child in root.childItems():yield from self.items(child)
    def js(self,expression):
        evaluator=QQmlExpression(qmlContext(self.root),self.root,expression);value=evaluator.evaluate()
        self.assertFalse(evaluator.hasError(),evaluator.error().toString())
        return value[0] if isinstance(value,tuple) else value
    def request(self):
        field=self.root.findChild(QQuickItem,'recoveryPassword');field.setProperty('text','public-fixture-password')
        self.js('reveal()');self.settle();self.assertEqual(self.root.property('phase'),'PENDING')
        self.assertFalse(field.property('text'));return self.root.property('_requestId')
    def emit(self,request,*,count=24,state='REVEALED'):
        # Published all-zero vectors, not an actual generated wallet.
        words=['abandon']*(count-1)+(['about'] if count==12 else ['art'])
        self.host.walletMnemonicSecretReady.emit(json.dumps(dict(request_id=request,state=state,words=words,pubkey=ADDRESS)))
        self.settle()
    def test_approval_is_staged_without_phrase_and_wrong_request_cannot_reveal(self):
        request=self.request();self.assertEqual(self.root.property('revealedCount'),0)
        self.emit('another-public-fixture');self.assertEqual(self.root.property('revealedCount'),0)
        self.emit(request);self.assertEqual(self.root.property('phase'),'REVEALED');self.assertEqual(self.root.property('revealedCount'),24)
    def test_hidden_panel_discards_callback_and_releases_capture_guard_via_cancel(self):
        request=self.request();self.root.setVisible(False);self.emit(request)
        self.assertEqual(self.root.property('revealedCount'),0);self.assertEqual(self.root.property('_requestId'),'')
        self.assertEqual(self.host.cancelled,[request])
    def test_close_wipes_before_cancel_and_repeat_requires_fresh_password_request(self):
        first=self.request();self.emit(first,count=12);self.js('cancel()')
        self.assertEqual(self.root.property('revealedCount'),0);self.assertEqual(self.host.cancelled,[first])
        self.js('open('+json.dumps(ADDRESS)+')');self.js('reveal()');self.assertEqual(len(self.host.requests),1)
        second=self.request();self.assertNotEqual(second,first)
        self.emit(first);self.assertEqual(self.root.property('revealedCount'),0)
        self.emit(second);self.assertEqual(self.root.property('revealedCount'),24)
    def test_hiding_or_minimizing_revealed_view_cancels_and_late_reply_cannot_restore_words(self):
        for minimize in (False,True):
            self.root.setVisible(True);self.window.showNormal();self.settle()
            self.js('open('+json.dumps(ADDRESS)+')');request=self.request();self.emit(request)
            self.assertEqual(self.root.property('revealedCount'),24)
            if minimize:self.window.setVisibility(self.window.Visibility.Minimized)
            else:self.root.setVisible(False)
            self.settle()
            # Host.walletMnemonicCancelReveal asserts the widget clears words
            # and its match key before that cancellation can release a guard.
            self.assertEqual(self.root.property('revealedCount'),0)
            self.assertEqual(self.root.property('_requestId'),'')
            self.assertIn(request,self.host.cancelled)
            self.emit(request);self.assertEqual(self.root.property('revealedCount'),0)
            self.assertEqual(self.root.property('phase'),'PASSWORD')
            self.root.setVisible(True);self.window.showNormal();self.settle()
            self.emit(request);self.assertEqual(self.root.property('revealedCount'),0)
    def test_failure_reply_discloses_no_words_and_allows_new_unlock(self):
        request=self.request();self.emit(request,state='ERROR')
        self.assertEqual(self.root.property('phase'),'PASSWORD');self.assertEqual(self.root.property('revealedCount'),0)
        self.assertEqual(self.root.property('_requestId'),'')
    def test_numbered_word_grid_fits_without_screenshot_or_clipboard(self):
        request=self.request();self.emit(request)
        self.assertTrue(self.root.findChild(QQuickItem,'recoveryWordGrid').property('privateSensitive'))
        for width,height in ((328,520),(360,600),(640,520),(900,600)):
            self.window.setWidth(width);self.window.setHeight(height);self.settle()
            cells=[item for item in self.items(self.root) if item.objectName()=='recoveryWordCell']
            self.assertEqual(len(cells),24)
            self.assertEqual([cell.property('index') for cell in cells],list(range(24)))
            footer=self.root.findChild(QQuickItem,'recoveryClose').mapToScene(QPointF(0,0)).y()
            for cell in cells:
                p=cell.mapToScene(QPointF(0,0));self.assertGreaterEqual(p.y(),0);self.assertLessEqual(p.y()+cell.height(),footer)


if __name__=='__main__':unittest.main()
