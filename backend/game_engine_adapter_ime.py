"""Qt composition stays in the painter until the original EditBox commits it."""
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QInputMethodEvent,QTextLayout,QTextCharFormat,QColor
from backend.game_engine_adapter_text import font_for,layout_text

def utf16_index(text,offset,ceil=False):
    units=0
    for i,ch in enumerate(text):
        if units>=offset:return i
        units+=len(ch.encode('utf-16-le'))//2
        if units>offset:return i+1 if ceil else i
    return len(text)

def context(row):
    if not row or not row.get('editbox'):return None
    edit=row['editbox'];text=str(row.get('text') or '');prefix=text.encode()[:edit['display_from']].decode('utf-8','ignore') if not edit['multi_line'] else ''
    visible=text[len(prefix):];font=font_for(row.get('font'),row.get('font_height',12),row.get('scale',1));layout,height=layout_text(visible,font,row['width'])
    def index(line,x):
        if not layout.lineCount():return len(prefix.encode('utf-16-le'))//2
        return len(prefix.encode('utf-16-le'))//2+layout.lineAt(min(line,layout.lineCount()-1)).xToCursor(x)
    cursor=index(edit['caret_row'],edit['caret_x']);selection=[]
    for line,x0,x1 in edit['selection']:selection.extend((index(line,x0),index(line,x1)))
    a,b=(min(selection),max(selection)) if selection else (cursor,cursor)
    anchor=b if cursor==a else a
    return {'text':text,'visible':visible,'prefix':prefix,'font':font,'cursor':cursor,'anchor':anchor,'a':a,'b':b,
        'selected':text[utf16_index(text,a):utf16_index(text,b,True)],
        'rectangle':QRectF(row['x']+edit['caret_x'],row['y']+edit['caret_row']*edit['cell_h'],1,max(1,edit['cell_h']))}

class Composition:
    def __init__(self):self.text='';self.attributes=[];self.target=None
    def reset(self):self.text='';self.attributes=[];self.target=None
    def query(self,row,query):
        c=context(row)
        if query==Qt.ImEnabled:return c is not None
        if c is None:return None
        return {Qt.ImSurroundingText:c['text'],Qt.ImCursorPosition:c['cursor'],Qt.ImAbsolutePosition:c['cursor'],Qt.ImAnchorPosition:c['anchor'],Qt.ImCurrentSelection:c['selected'],Qt.ImCursorRectangle:c['rectangle'],Qt.ImFont:c['font'],Qt.ImHints:Qt.ImhNone,Qt.ImTextBeforeCursor:c['text'][:utf16_index(c['text'],c['cursor'])],Qt.ImTextAfterCursor:c['text'][utf16_index(c['text'],c['cursor']):]}.get(query)
    def event(self,row,event,lua):
        c=context(row)
        if c is None:self.reset();return False
        commit=event.commitString();start=event.replacementStart();count=event.replacementLength()
        if abs(start)>4096 or not 0<=count<=4096 or len(commit.encode())>65536 or len(event.preeditString().encode())>8192:raise ValueError('IME text capacity exceeded')
        if commit or count:
            if start or count:
                text=c['text'];cursor=c['cursor'];selected=c['a']!=c['b']
                if selected:text=text[:utf16_index(text,c['a'])]+text[utf16_index(text,c['b'],True):];cursor=c['a']
                caret=utf16_index(text,cursor);a=utf16_index(text,max(0,cursor+start));b=utf16_index(text,max(0,cursor+start+count),True)
                lua.request('ime_replace',start_chars=a-caret,length_chars=max(0,b-a),replace_selection=selected,text=commit)
            else:lua.request('text',text=commit)
        self.text=event.preeditString();self.attributes=list(event.attributes());self.target=row['id'];return True
    def paint(self,painter,row):
        if not self.text or self.target!=row['id']:return False
        c=context(row);cursor=utf16_index(c['text'],c['cursor']);a=utf16_index(c['text'],c['a']);b=utf16_index(c['text'],c['b'],True)
        if c['a']!=c['b']:cursor=a
        prefix=c['text'][:cursor];suffix=c['text'][b if c['a']!=c['b'] else cursor:];display=prefix+self.text+suffix
        display=display[len(c['prefix']):];start=len(prefix[len(c['prefix']):].encode('utf-16-le'))//2;length=len(self.text.encode('utf-16-le'))//2
        f=QTextLayout.FormatRange();f.start=start;f.length=length;f.format=QTextCharFormat();f.format.setFontUnderline(True);formats=[f]
        caret=length;caret_visible=True;caret_color=QColor.fromRgbF(*(row.get('color') or [1,1,1,1]))
        for attr in self.attributes:
            if attr.type==QInputMethodEvent.TextFormat:
                r=QTextLayout.FormatRange();r.start=start+attr.start;r.length=attr.length;r.format=QTextCharFormat(attr.value);formats.append(r)
            elif attr.type==QInputMethodEvent.Cursor:
                caret=max(0,min(length,attr.start));caret_visible=attr.length!=0
                if isinstance(attr.value,QColor):caret_color=attr.value
        layout,height=layout_text(display,c['font'],row['width'],formats=formats);painter.setPen(QColor.fromRgbF(*(row.get('color') or [1,1,1,1])));layout.draw(painter,QPointF(row['x'],row['y']))
        if caret_visible and layout.lineCount():
            line=layout.lineForTextPosition(start+caret)
            if not line.isValid():line=layout.lineAt(layout.lineCount()-1)
            x=line.cursorToX(start+caret)[0];painter.fillRect(QRectF(row['x']+x,row['y']+line.y(),1,line.height()),caret_color)
        return True
