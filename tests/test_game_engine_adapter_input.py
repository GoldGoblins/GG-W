"""Native hyperlink dispatch and Qt composition without premature Lua edits."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QGuiApplication,QImage,QPainter,QInputMethodEvent,QTextCharFormat
from PySide6.QtQuick import QQuickItem
from backend.game_engine_adapter_ui import GgEngineUI
from backend.game_engine_adapter_canvas import GgEngineCanvas
from backend.game_engine_adapter_text import hyperlink_spans
APP=QGuiApplication.instance() or QGuiApplication([])
class Input(unittest.TestCase):
    def setUp(self):
        self.ui=GgEngineUI();self.addCleanup(self.ui.close);self.ui.resize(400,200)
    def edit(self,text='abc'):
        import json
        self.ui.execute("E=CreateFrame('EditBox','E',UIParent) E:SetWidth(300) E:SetHeight(40) E:SetPoint('TOPLEFT',UIParent,'TOPLEFT',10,-10) E:SetFont('Fonts/ARIALN.TTF',16) E:SetAutoFocus(false) E:SetFocus() E:SetText("+json.dumps(text,ensure_ascii=False)+")")
        class Runtime:
            def __init__(self,lua):self.lua=lua;self.errors=[];self.queued_input=0
            def queue_ui_input(self):self.queued_input+=1
            def _update_frames(self):
                if hasattr(self,'canvas'):self.canvas.sync(self.lua.frames())
            def _error(self,exc):self.errors.append(str(exc))
        runtime=Runtime(self.ui);parent=QQuickItem();parent.setWidth(400);parent.setHeight(200);canvas=GgEngineCanvas(runtime,parent);runtime.canvas=canvas;canvas.sync(self.ui.frames());self.addCleanup(canvas.assets.close)
        return runtime,canvas,parent
    def test_shaped_wrapped_and_clipped_links_dispatch_original_handler(self):
        self.ui.execute("Log=CreateFrame('Frame','Log',UIParent) Log:SetWidth(110) Log:SetHeight(80) Log:SetPoint('TOPLEFT',UIParent,'TOPLEFT',10,-10) Log:EnableMouse(true) Log:SetScript('OnHyperlinkClick',function() clicked={arg1,arg2,arg3} end) T=Log:CreateFontString() T:SetAllPoints(Log) T:SetFont('Fonts/ARIALN.TTF',16) T:SetText('Text |Hitem:17|hLinked words in two lines|h')")
        rows=self.ui.frames();spans=[span for row in rows if row['kind']=='Text' for span in hyperlink_spans(row)]
        self.assertGreaterEqual(len(spans),2);self.ui.request('links',spans=spans);hit=spans[0];x,y,w,h=hit['rect'];self.ui.pointer('press',x+w/2,y+h/2);self.ui.pointer('release',x+w/2,y+h/2)
        self.assertEqual(self.ui.evaluate('return clicked[1],clicked[2],clicked[3]'),['item:17','|Hitem:17|hLinked words in two lines|h','LeftButton'])
        self.ui.request('links',spans=[]);self.ui.execute('clicked=nil');self.ui.pointer('press',x+w/2,y+h/2);self.ui.pointer('release',x+w/2,y+h/2);self.assertEqual(self.ui.evaluate('return clicked'),[None])
    def test_stale_and_excessive_link_regions_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'stale'):self.ui.request('links',spans=[{'id':'retired','rect':[0,0,10,10],'link':'x','markup':'x'}])
        with self.assertRaisesRegex(ValueError,'capacity'):self.ui.request('links',spans=[{}]*2049)
    def test_same_target_keeps_each_labels_own_markup_and_escaped_bars(self):
        row={'id':'text','x':0,'y':0,'width':400,'height':30,'font_height':16,'justify_v':'Top','text':'||Hliteral |Hitem:17|hOne|h and |Hitem:17|hTwo|h'}
        spans=hyperlink_spans(row)
        self.assertEqual([span['markup'] for span in spans],['|Hitem:17|hOne|h','|Hitem:17|hTwo|h'])
    def test_reload_resends_links_when_draw_list_is_identical(self):
        runtime,canvas,parent=self.edit();rows=self.ui.frames();canvas.sync(rows)
        class Replacement:
            closed=False
            def __init__(self):self.calls=[]
            def request(self,op,**kwargs):self.calls.append((op,kwargs))
        runtime.lua=Replacement();canvas.sync(rows)
        self.assertEqual(runtime.lua.calls,[('links',{'spans':[]})])
    def test_preedit_paints_and_cancels_without_committing_to_Lua(self):
        runtime,canvas,parent=self.edit();fmt=QTextCharFormat();fmt.setFontUnderline(True)
        event=QInputMethodEvent('候補',[QInputMethodEvent.Attribute(QInputMethodEvent.TextFormat,0,2,fmt),QInputMethodEvent.Attribute(QInputMethodEvent.Cursor,1,1,None)])
        canvas.inputMethodEvent(event);self.assertTrue(event.isAccepted());self.assertEqual(self.ui.evaluate('return E:GetText()'),['abc']);self.assertEqual(canvas.composition.text,'候補')
        image=QImage(400,200,QImage.Format_ARGB32_Premultiplied);image.fill(0);p=QPainter(image);canvas.paint(p);p.end();self.assertTrue(any(image.pixelColor(x,y).alpha() for x in range(40,160) for y in range(10,50)))
        canvas.inputMethodEvent(QInputMethodEvent('',[]));self.assertEqual(self.ui.evaluate('return E:GetText()'),['abc']);self.assertEqual(canvas.composition.text,'');self.assertFalse(runtime.errors)
    def test_committed_unicode_and_queries_use_Qt_UTF16_offsets(self):
        runtime,canvas,parent=self.edit('a😀');event=QInputMethodEvent();event.setCommitString('漢字');canvas.inputMethodEvent(event)
        self.assertEqual(self.ui.evaluate('return E:GetText()'),['a😀漢字']);self.assertEqual(canvas.inputMethodQuery(Qt.ImSurroundingText),'a😀漢字');self.assertEqual(canvas.inputMethodQuery(Qt.ImCursorPosition),5)
        self.assertEqual(runtime.queued_input,1)
        self.assertTrue(canvas.inputMethodQuery(Qt.ImEnabled));self.assertIsInstance(canvas.inputMethodQuery(Qt.ImCursorRectangle),QRectF);self.assertFalse(runtime.errors)
    def test_replacement_converts_surrogate_pair_into_one_native_character(self):
        runtime,canvas,parent=self.edit('a😀');event=QInputMethodEvent();event.setCommitString('Ö',-2,2);canvas.inputMethodEvent(event)
        self.assertEqual(self.ui.evaluate('return E:GetText()'),['aÖ']);self.assertFalse(runtime.errors)
    def test_empty_commit_deletes_and_focus_loss_discards_composition(self):
        runtime,canvas,parent=self.edit('abc');event=QInputMethodEvent();event.setCommitString('',-1,1);canvas.inputMethodEvent(event);self.assertEqual(self.ui.evaluate('return E:GetText()'),['ab'])
        canvas.inputMethodEvent(QInputMethodEvent('候補',[]));self.ui.execute('E:ClearFocus()');canvas.sync(self.ui.frames());self.assertFalse(canvas.inputMethodQuery(Qt.ImEnabled));self.assertEqual(canvas.composition.text,'')
    def test_selected_text_commit_uses_original_EditBox_selection(self):
        runtime,canvas,parent=self.edit('abc');self.ui.execute('E:HighlightText(0,-1)');canvas.sync(self.ui.frames());self.assertEqual(canvas.inputMethodQuery(Qt.ImCurrentSelection),'abc')
        event=QInputMethodEvent();event.setCommitString('new');canvas.inputMethodEvent(event);self.assertEqual(self.ui.evaluate('return E:GetText()'),['new'])
if __name__=='__main__':unittest.main()
