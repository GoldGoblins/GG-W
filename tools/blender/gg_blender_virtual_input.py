"""Forward GG's existing agent pointer/keyboard into Blender's event queue."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURSORS = ROOT / "qml/components/web-cursors"
_point = (0, 0)
_cursor = None


class AgentCursor:
    """A noninteractive child bitmap using GG's existing cursor pack."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.user = c.WinDLL("user32", use_last_error=True)
        self.gdi = c.WinDLL("gdi32")
        self.plus = c.WinDLL("gdiplus")
        definitions = {
            "EnumWindows": ([c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM),w.LPARAM],w.BOOL),
            "EnumChildWindows": ([w.HWND,c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM),w.LPARAM],w.BOOL),
            "GetWindowThreadProcessId": ([w.HWND,c.POINTER(w.DWORD)],w.DWORD),
            "GetClassNameW": ([w.HWND,w.LPWSTR,c.c_int],c.c_int),
            "GetDpiForWindow": ([w.HWND],w.UINT),
            "IsWindow": ([w.HWND],w.BOOL),
            "CreateWindowExW": ([w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p],w.HWND),
            "SetLayeredWindowAttributes": ([w.HWND,w.DWORD,w.BYTE,w.DWORD],w.BOOL),
            "SendMessageW": ([w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.LPARAM),
            "SetWindowPos": ([w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT],w.BOOL),
            "ShowWindowAsync": ([w.HWND,c.c_int],w.BOOL),
            "DestroyWindow": ([w.HWND],w.BOOL),
        }
        for name,(args,result) in definitions.items():
            getattr(self.user,name).argtypes,getattr(self.user,name).restype=args,result
        callback = c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        found=[]
        def visit(hwnd, _):
            pid=w.DWORD();self.user.GetWindowThreadProcessId(hwnd,c.byref(pid))
            if pid.value == os.getpid():
                name=c.create_unicode_buffer(256);self.user.GetClassNameW(hwnd,name,len(name))
                if "ghost" in name.value.lower(): found.append(hwnd)
            return True
        cb=callback(visit)
        def top(hwnd, context):
            visit(hwnd,context);self.user.EnumChildWindows(hwnd,cb,0);return True
        self.user.EnumWindows(callback(top),0)
        if not found: raise RuntimeError("BLENDER_CURSOR_WINDOW_MISSING")
        self.parent=found[0]
        self.ratio=self.user.GetDpiForWindow(self.parent)/96
        self.size=max(24,round(24*self.ratio))
        # WS_CHILD | WS_DISABLED and input-transparent/no-activate extended
        # styles: this bitmap can never capture the user's mouse or focus.
        self.hwnd=self.user.CreateWindowExW(0x08080020,"STATIC","GG agent cursor",0x4800000E,
                                          0,0,self.size,self.size,self.parent,None,None,None)
        if not self.hwnd: raise RuntimeError("BLENDER_CURSOR_CREATE_FAILED")
        self.user.SetLayeredWindowAttributes(self.hwnd,0x00010101,255,1)
        class Startup(c.Structure):
            _fields_=[("version",w.UINT),("callback",c.c_void_p),("no_thread",w.BOOL),("no_codecs",w.BOOL)]
        self.plus.GdiplusStartup.argtypes=[c.POINTER(c.c_size_t),c.POINTER(Startup),c.c_void_p]
        self.plus.GdipCreateBitmapFromFile.argtypes=[w.LPCWSTR,c.POINTER(c.c_void_p)]
        self.plus.GdipGetImageThumbnail.argtypes=[c.c_void_p,w.UINT,w.UINT,c.POINTER(c.c_void_p),c.c_void_p,c.c_void_p]
        self.plus.GdipCreateHBITMAPFromBitmap.argtypes=[c.c_void_p,c.POINTER(w.HBITMAP),w.DWORD]
        self.plus.GdipDisposeImage.argtypes=[c.c_void_p]
        self.plus.GdiplusShutdown.argtypes=[c.c_size_t]
        self.gdi.DeleteObject.argtypes=[w.HGDIOBJ]
        self.token=c.c_size_t()
        if self.plus.GdiplusStartup(c.byref(self.token),c.byref(Startup(1,None,False,False)),None):
            raise RuntimeError("BLENDER_CURSOR_IMAGE_FAILED")
        self.pack=json.loads((CURSORS/"pack.json").read_text(encoding="utf-8"))["pack"]
        self.bitmaps={}
        self.shape=None
        self.hot=(0,0)

    def show(self,x,y,shape="default"):
        c,w=self.c,self.w
        spec=self.pack.get(shape,self.pack["default"])
        if spec.get("frames",1)!=1: spec=self.pack["default"]
        name=spec["file"]
        if name not in self.bitmaps:
            image=c.c_void_p();thumb=c.c_void_p();bitmap=w.HBITMAP()
            if self.plus.GdipCreateBitmapFromFile(str(CURSORS/name),c.byref(image)):
                raise RuntimeError("BLENDER_CURSOR_IMAGE_FAILED")
            try:
                if self.plus.GdipGetImageThumbnail(image,self.size,self.size,c.byref(thumb),None,None):
                    raise RuntimeError("BLENDER_CURSOR_SCALE_FAILED")
                if self.plus.GdipCreateHBITMAPFromBitmap(thumb,c.byref(bitmap),0xFF010101):
                    raise RuntimeError("BLENDER_CURSOR_BITMAP_FAILED")
                self.bitmaps[name]=bitmap
            finally:
                if thumb: self.plus.GdipDisposeImage(thumb)
                self.plus.GdipDisposeImage(image)
        if self.shape!=name:
            self.user.SendMessageW(self.hwnd,0x0172,0,self.bitmaps[name].value)
            self.shape=name
        self.hot=(round(spec["hotX"]*self.ratio),round(spec["hotY"]*self.ratio))
        self.user.SetWindowPos(self.hwnd,None,round(x)-self.hot[0],round(y)-self.hot[1],
                               self.size,self.size,0x0010)
        self.user.ShowWindowAsync(self.hwnd,4)

    def hide(self):
        self.user.ShowWindowAsync(self.hwnd,0)

    def close(self):
        if self.user.IsWindow(self.hwnd): self.user.DestroyWindow(self.hwnd)
        for bitmap in self.bitmaps.values(): self.gdi.DeleteObject(bitmap)
        self.bitmaps.clear()
        self.plus.GdiplusShutdown(self.token)


def _show(x,y,shape):
    global _cursor
    if os.name != "nt": return
    if _cursor is None: _cursor=AgentCursor()
    _cursor.show(x,y,shape)


def dispatch(bpy, request):
    """Coordinates use the Blender client area's top-left pixel origin."""
    global _point
    expected=request.get("target_pid")
    if expected is not None and expected != os.getpid():
        return {"ok":False,"error":"BLENDER_AGENT_TARGET_CHANGED"}
    events=request.get("events")
    if not isinstance(events,list) or not 1<=len(events)<=32:
        return {"ok":False,"error":"BLENDER_AGENT_EVENTS_INVALID"}
    window=bpy.context.window
    if window is None or not bpy.app.use_event_simulate:
        return {"ok":False,"error":"BLENDER_AGENT_INPUT_NOT_ENABLED"}
    # Prevent continuous mouse grabbing by Blender operators in this private
    # EXT profile. The GG pointer is the only position this bridge changes.
    bpy.context.preferences.inputs.use_mouse_continuous=False
    supported={"MOVE","CLICK","PRESS","RELEASE","KEY","TYPE","HIDE"}
    names={"Enter":"RET","Tab":"TAB","Escape":"ESC","Space":"SPACE",
           "Backspace":"BACK_SPACE","Delete":"DEL","Home":"HOME","End":"END",
           "ArrowUp":"UP_ARROW","ArrowDown":"DOWN_ARROW","ArrowLeft":"LEFT_ARROW","ArrowRight":"RIGHT_ARROW"}
    for event in events:
        if not isinstance(event,dict) or event.get("action") not in supported:
            return {"ok":False,"error":"BLENDER_AGENT_EVENT_INVALID"}
        if "x" in event or "y" in event:
            x,y=event.get("x"),event.get("y")
            if (isinstance(x,bool) or isinstance(y,bool)
                    or not isinstance(x,(int,float)) or not isinstance(y,(int,float))
                    or not math.isfinite(x) or not math.isfinite(y)
                    or not 0<=x<window.width or not 0<=y<window.height):
                return {"ok":False,"error":"BLENDER_AGENT_POINT_INVALID"}
        if event["action"]=="TYPE" and (not isinstance(event.get("text"),str) or len(event["text"])>256):
            return {"ok":False,"error":"BLENDER_AGENT_TEXT_INVALID"}
        if event["action"]=="KEY" and event.get("key") not in names:
            return {"ok":False,"error":"BLENDER_AGENT_KEY_UNSUPPORTED"}
        if event["action"] in {"CLICK","PRESS","RELEASE"} and event.get("button","left") not in {"left","right","middle"}:
            return {"ok":False,"error":"BLENDER_AGENT_BUTTON_INVALID"}
    count=0
    def emit(kind,value,*,text="",**modifiers):
        nonlocal count
        x,y=_point
        window.event_simulate(type=kind,value=value,x=round(x),y=window.height-1-round(y),
                              unicode=text,**modifiers)
        count+=1
    for event in events:
        action=event["action"]
        if action=="HIDE":
            if _cursor is not None: _cursor.hide()
            continue
        if "x" in event:
            _point=(event["x"],event["y"])
        shape=event.get("shape","text" if action=="TYPE" else "default")
        _show(*_point,shape)
        modifiers={name:bool(event.get(name,False)) for name in ("shift","ctrl","alt","oskey")}
        if action=="MOVE":
            emit("MOUSEMOVE","NOTHING",**modifiers)
        elif action in {"CLICK","PRESS","RELEASE"}:
            mouse={"left":"LEFTMOUSE","right":"RIGHTMOUSE","middle":"MIDDLEMOUSE"}.get(event.get("button","left"))
            if mouse is None: return {"ok":False,"error":"BLENDER_AGENT_BUTTON_INVALID"}
            emit("MOUSEMOVE","NOTHING",**modifiers)
            if action!="RELEASE": emit(mouse,"PRESS",**modifiers)
            if action!="PRESS": emit(mouse,"RELEASE",**modifiers)
        elif action=="KEY":
            key=names.get(event.get("key"))
            if key is None: return {"ok":False,"error":"BLENDER_AGENT_KEY_UNSUPPORTED"}
            emit(key,"PRESS",**modifiers);emit(key,"RELEASE",**modifiers)
        elif action=="TYPE":
            for char in event["text"]:
                digits={"0":"ZERO","1":"ONE","2":"TWO","3":"THREE","4":"FOUR","5":"FIVE","6":"SIX","7":"SEVEN","8":"EIGHT","9":"NINE"}
                key="RET" if char=="\n" else "SPACE" if char==" " else digits[char] if char in digits else char.upper() if char.isascii() and char.isalpha() else "NONE"
                emit(key,"PRESS",text="" if char=="\n" else char,**modifiers);emit(key,"RELEASE",**modifiers)
    return {"ok":True,"events_queued":count,"agent_pointer":list(_point)}
