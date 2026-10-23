"""Shared Qt font metrics and the legacy colour/hyperlink escape grammar."""
from pathlib import Path
import re
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QColor,QFont,QFontDatabase,QTextCharFormat,QTextLayout,QTextOption
from backend.game_engine_adapter_assets import asset_path
PROJECT=Path(__file__).resolve().parents[1]
FONTS={}

def font_for(path,height=12,scale=1):
    key=str(path or '').replace('\\','/');family=FONTS.get(key)
    if family is None:
        family='Sans Serif'
        try:p=asset_path(key)
        except ValueError:p=PROJECT
        if p.is_relative_to(PROJECT/'qml') and p.suffix.lower() in ('.ttf','.otf') and p.is_file() and p.stat().st_size<8*1024*1024:
            identity=QFontDatabase.addApplicationFont(str(p));names=QFontDatabase.applicationFontFamilies(identity)
            if names:family=names[0]
        if len(FONTS)<128:FONTS[key]=family
    font=QFont(family);font.setPixelSize(max(1,min(1024,round(float(height)*float(scale)))))
    return font

def parse_markup(source,base=None,link_ranges=None):
    text=[];runs=[];at=0;start=0;current=QColor(base or 'white');link=None;link_open=None;link_start=0
    source=str(source or '')
    def flush():
        nonlocal start
        end=len(''.join(text).encode('utf-16-le'))//2
        if end>start:runs.append((start,end-start,QColor(current),link))
        start=end
    while at<len(source):
        if source.startswith('||',at):text.append('|');at+=2;continue
        if source.startswith('|c',at) and re.fullmatch('[0-9a-fA-F]{8}',source[at+2:at+10]):
            flush();rgba=source[at+2:at+10];current=QColor('#'+rgba);at+=10;continue
        if source.startswith('|r',at):flush();current=QColor(base or 'white');at+=2;continue
        if source.startswith('|H',at):
            end=source.find('|h',at+2)
            if end>=0:
                flush();link=source[at+2:end];link_open=at;link_start=start;at=end+2;continue
        if source.startswith('|h',at):
            flush()
            if link_ranges is not None and link_open is not None:link_ranges.append((link_start,start,link,source[link_open:at+2]))
            link=None;link_open=None;at+=2;continue
        text.append(source[at]);at+=1
    flush();return ''.join(text),runs

def plain_text(source):return parse_markup(source)[0]

def hyperlink_spans(row):
    """The same shaped, wrapped UTF-16 layout used to paint, in Qt coordinates."""
    if row.get('editbox') or not row.get('text') or row.get('alpha',1)<=0:return []
    ranges=[];text,runs=parse_markup(row['text'],link_ranges=ranges);links=[run for run in runs if run[3]]
    if not links:return []
    rect=QRectF(row['x'],row['y'],row['width'],row['height'])
    layout,height=layout_text(text,font_for(row.get('font'),row.get('font_height',12),row.get('scale',1)),rect.width(),row.get('justify_h','Left'))
    dy=0 if row.get('justify_v')=='Top' else rect.height()-height if row.get('justify_v')=='Bottom' else (rect.height()-height)/2
    clip=rect.intersected(QRectF(*row['clip'])) if row.get('clip') else rect;spans=[]
    for start,length,shade,link in links:
        markup=next((markup for a,b,target,markup in ranges if target==link and a<=start<b),row['text'])
        for i in range(layout.lineCount()):
            line=layout.lineAt(i);a=max(start,line.textStart());b=min(start+length,line.textStart()+line.textLength())
            if a>=b:continue
            x0=line.cursorToX(a)[0];x1=line.cursorToX(b)[0]
            hit=QRectF(rect.x()+min(x0,x1),rect.y()+dy+line.y(),abs(x1-x0),line.height()).intersected(clip)
            if not hit.isEmpty():spans.append({'id':row['id'],'rect':[hit.x(),hit.y(),hit.width(),hit.height()],'link':link,'markup':markup})
    return spans

def layout_text(text,font,width,justify='Left',formats=None):
    # QTextLayout uses a paragraph separator for explicit line breaks.
    layout=QTextLayout(text.replace('\n','\u2028'),font)
    if formats is not None:layout.setFormats(formats)
    option=QTextOption();option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    option.setAlignment({'Right':Qt.AlignRight,'Center':Qt.AlignHCenter}.get(justify,Qt.AlignLeft))
    layout.setTextOption(option);layout.beginLayout();y=0
    while True:
        line=layout.createLine()
        if not line.isValid():break
        line.setLineWidth(max(1,width));line.setPosition(QPointF(0,y));y+=line.height()
    layout.endLayout();return layout,y

def paint_text(painter,rect,row):
    base=QColor.fromRgbF(*(row.get('color') or [1,1,1,1]));edit=row.get('editbox')
    text,runs=parse_markup(row.get('text'),base) if not edit else (str(row.get('text') or ''),[])
    if edit and not edit['multi_line']:text=text.encode()[edit['display_from']:].decode('utf-8','replace')
    font=font_for(row.get('font'),row.get('font_height') or 12,row.get('scale') or 1)
    layout,height=layout_text(text,font,rect.width(),row.get('justify_h','Left'))
    dy=0 if row.get('justify_v')=='Top' else rect.height()-height if row.get('justify_v')=='Bottom' else (rect.height()-height)/2
    if edit:dy=0
    origin=QPointF(rect.x(),rect.y()+dy)
    if edit:
        from PySide6.QtCore import QRectF
        for line,x0,x1 in edit['selection']:painter.fillRect(QRectF(rect.x()+x0,rect.y()+line*edit['cell_h'],x1-x0,edit['cell_h']),QColor.fromRgbF(*edit['highlight_color']))
    shadow=row.get('shadow')
    if shadow:
        painter.setPen(QColor.fromRgbF(*shadow['color']));layout.draw(painter,origin+QPointF(shadow['offset'][0],-shadow['offset'][1]))
    outline=row.get('outline')
    if outline in ('Normal','Thick'):
        painter.setPen(QColor('black'));radius=2 if outline=='Thick' else 1
        for dx,dy in ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)):layout.draw(painter,origin+QPointF(dx*radius,dy*radius))
    formats=[];gradient=row.get('alpha_gradient')
    if gradient:
        start,length=gradient;utf16=0
        for index,ch in enumerate(text):
            shade=next((c for s,n,c,_ in runs if s<=utf16<s+n),base);shade=QColor(shade)
            shade.setAlphaF(shade.alphaF()*max(0,min(1,1-(index-start)/max(.0001,length))))
            f=QTextLayout.FormatRange();f.start=utf16;f.length=len(ch.encode('utf-16-le'))//2;f.format=QTextCharFormat();f.format.setForeground(shade);formats.append(f);utf16+=f.length
    else:
        for start,length,shade,_ in runs:
            f=QTextLayout.FormatRange();f.start=start;f.length=length;f.format=QTextCharFormat();f.format.setForeground(shade);formats.append(f)
    layout,_=layout_text(text,font,rect.width(),row.get('justify_h','Left'),formats);painter.setPen(base);layout.draw(painter,origin)
    if edit and edit['caret_on']:
        from PySide6.QtCore import QRectF
        painter.fillRect(QRectF(rect.x()+edit['caret_x'],rect.y()+edit['caret_row']*edit['cell_h'],1,max(1,edit['cell_h'])),base)
