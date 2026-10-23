"""Finite, supervised process for the complete GgEngine Lua/FrameXML core.

No user credentials or site access. The parent supplies addon source and saves.
"""
from __future__ import annotations
import ctypes,json,os,sys,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.native_worker_limits import apply as apply_worker_limits
MAX_MESSAGE=16*1024*1024
def main():
    apply_worker_limits(2*1024*1024*1024)
    lib=ctypes.CDLL(sys.argv[1])
    lib.ggbu_create.argtypes=[];lib.ggbu_create.restype=ctypes.c_void_p
    lib.ggbu_destroy.argtypes=[ctypes.c_void_p];lib.ggbu_destroy.restype=None
    lib.ggbu_request.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t];lib.ggbu_request.restype=ctypes.c_int
    lib.ggbu_response.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t)];lib.ggbu_response.restype=ctypes.c_void_p
    handle=lib.ggbu_create()
    if not handle:raise RuntimeError('GgEngine UI initialization failed')
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtGui import QGuiApplication,QFont,QFontMetricsF,QTextLayout,QTextOption
    from PySide6.QtCore import Qt,QRectF
    app=QGuiApplication([])
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from backend.game_engine_adapter_text import plain_text,font_for,layout_text
    callback_type=ctypes.CFUNCTYPE(ctypes.c_size_t,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t)
    @callback_type
    def measure(user,packet,size,output,capacity):
        try:
            req=json.loads(ctypes.string_at(packet,size));scale=max(.01,float(req.get('scale') or 1))
            font=font_for(req.get('font'),req['height'],scale)
            metrics=QFontMetricsF(font);text=req['text'] if req.get('kind')=='editbox' else plain_text(req['text'])
            if req.get('kind')=='editbox':
                prefix='';advances=[0.]
                for ch in text:
                    prefix+=ch;advances.extend([metrics.horizontalAdvance(prefix)]*len(ch.encode()))
                rows=[0]
                if req.get('wrap_width'):
                    layout=QTextLayout(text,font);option=QTextOption();option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere);layout.setTextOption(option);layout.beginLayout();rows=[]
                    while True:
                        line=layout.createLine()
                        if not line.isValid():break
                        line.setLineWidth(float(req['wrap_width']));prefix=text.encode('utf-16-le')[:line.textStart()*2].decode('utf-16-le');rows.append(len(prefix.encode()))
                    layout.endLayout()
                result=json.dumps({'advances':advances,'rows':rows,'line_height':metrics.height()}).encode()
                if len(result)>capacity:return 0
                ctypes.memmove(output,result,len(result));return len(result)
            natural=max((metrics.horizontalAdvance(s) for s in text.split('\n')),default=0)
            width=req.get('wrap_width');layout,height=layout_text(text,font,float(width)*scale if width else max(1,natural))
            measured=max((layout.lineAt(i).naturalTextWidth() for i in range(layout.lineCount())),default=0)
            result=json.dumps([measured/scale,height/scale,natural/scale]).encode()
            if len(result)>capacity:return 0
            ctypes.memmove(output,result,len(result));return len(result)
        except Exception:return 0
    lib.ggbu_text_measurer.argtypes=[ctypes.c_void_p,callback_type,ctypes.c_void_p]
    lib.ggbu_text_measurer.restype=ctypes.c_int
    assert lib.ggbu_text_measurer(handle,measure,None)==0
    try:
        while line:=sys.stdin.buffer.readline(MAX_MESSAGE+2):
            if len(line)>MAX_MESSAGE or not line.endswith(b'\n'):raise ValueError('oversized UI request')
            if lib.ggbu_request(handle,line,len(line))!=0:raise RuntimeError('invalid UI request')
            size=ctypes.c_size_t();data=lib.ggbu_response(handle,ctypes.byref(size))
            if not data or size.value>MAX_MESSAGE:raise RuntimeError('invalid UI response')
            sys.stdout.buffer.write(ctypes.string_at(data,size.value)+b'\n');sys.stdout.buffer.flush()
    finally:lib.ggbu_destroy(handle)
if __name__=='__main__':main()
