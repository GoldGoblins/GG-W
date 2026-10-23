"""Original staged window settings apply to this client's actual Qt window."""
import json
import os
from pathlib import Path
import re
import tempfile
from PySide6.QtCore import QTimer
from PySide6.QtQuick import QQuickWindow

NAMES={'gxwindow':'gxWindow','gxresolution':'gxResolution'}


def settings(values):
    if set(values)!=set(NAMES.values()) or values['gxWindow'] not in ('0','1'):
        raise ValueError('GRAPHICS_WINDOW_MODE_INVALID')
    match=re.fullmatch(r'([0-9]{3,4})x([0-9]{3,4})',values['gxResolution'])
    if not match:raise ValueError('GRAPHICS_RESOLUTION_INVALID')
    width,height=map(int,match.groups())
    if not 320<=width<=7680 or not 200<=height<=4320 or width*height>32_000_000:
        raise ValueError('GRAPHICS_RESOLUTION_INVALID')
    return width,height


class ClientGraphics:
    def __init__(self,presentation):
        self.presentation=presentation;self.pending={};self.values=None
        self.standalone=False;self.generation=0;self.error='';self.restarting=False
        self.restore_values=None;self.loaded_path=None
        self.serial=0

    def changed_vm(self):
        self.serial+=1;self.restarting=False;self.pending={};self.error=''

    def path(self):
        ui=self.presentation.lua
        if not ui or not getattr(ui,'saving_enabled',False):return None
        root=getattr(ui,'saved_root',None)
        return Path(root)/'Graphics.json' if root else None

    def load(self):
        path=self.path()
        if not path or path==self.loaded_path:return
        self.loaded_path=path;self.restore_values=None
        try:
            if not path.is_file() or path.stat().st_size>4096:return
            data=json.loads(path.read_text())
            if not isinstance(data,dict) or set(data)!=set(('schema','values')) or data['schema']!='gg.game.graphics.v1':return
            settings(data['values']);self.restore_values=dict(data['values'])
        except (OSError,ValueError,TypeError,KeyError):return

    def save(self,values):
        path=self.path()
        if not path:return
        path.parent.mkdir(parents=True,exist_ok=True)
        name=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.Graphics-',delete=False) as stream:
                name=Path(stream.name);json.dump(dict(schema='gg.game.graphics.v1',values=values),stream)
                stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(name,path)
            self.loaded_path=path;self.restore_values=dict(values)
        finally:
            if name:name.unlink(missing_ok=True)

    def window(self):
        canvas=self.presentation._canvas
        return canvas.window() if canvas else None

    def seed(self):
        ui=self.presentation.lua
        if not ui or not self.presentation.full_ui:return
        self.load()
        window=self.window()
        if self.values is None:
            self.values={'gxWindow':'1','gxResolution':'1280x720'}
            if window:self.values={'gxWindow':'0' if window.visibility()==QQuickWindow.Visibility.FullScreen else '1',
                                   'gxResolution':str(window.width())+'x'+str(window.height())}
        ui.request('graphics_seed',values=self.values)

    def attach(self,standalone):
        self.standalone=standalone
        window=self.window()
        if window:
            self.values={'gxWindow':'0' if window.visibility()==QQuickWindow.Visibility.FullScreen else '1',
                         'gxResolution':str(window.width())+'x'+str(window.height())}
            self.seed()
            if standalone and self.restore_values and self.restore_values!=self.values:
                ui=self.presentation.lua;chosen=dict(self.restore_values)
                def restore():
                    if self.presentation.lua is ui and not ui.closed:
                        self.requests(dict(cvars=list(chosen.items()),client_tools=dict(graphics_restarts=1)))
                QTimer.singleShot(0,restore)

    def requests(self,request):
        rows=request.get('cvars',[])
        if isinstance(rows,list):
            for row in rows[:64]:
                if isinstance(row,(list,tuple)) and len(row)==2 and isinstance(row[0],str) and row[0].casefold() in NAMES:
                    self.pending[NAMES[row[0].casefold()]]=row[1]
        count=request.get('client_tools',{}).get('graphics_restarts',0)
        if not count:return
        if type(count) is not int or not 1<=count<=4:
            self.fail('GRAPHICS_RESTART_CAPACITY');return
        if self.restarting:self.fail('GRAPHICS_RESTART_PENDING');return
        p=self.presentation;window=self.window()
        if not window or not window.isVisible():self.fail('GRAPHICS_WINDOW_UNAVAILABLE');return
        if self.values is None:self.attach(self.standalone)
        chosen=dict(self.values,**self.pending)
        try:
            width,height=settings(chosen)
            if chosen['gxWindow']=='1' and (width<window.minimumWidth() or height<window.minimumHeight()
                    or width>window.maximumWidth() or height>window.maximumHeight()):raise ValueError('GRAPHICS_WINDOW_SIZE_UNAVAILABLE')
            # The embedded game shares the desktop window. Only the separate
            # game client owns the window's size and fullscreen mode.
            if not self.standalone and chosen!=self.values:raise ValueError('GRAPHICS_STANDALONE_WINDOW_REQUIRED')
        except (ValueError,TypeError) as exc:self.fail(str(exc));return
        self.serial+=1;serial=self.serial
        self.restarting=True;requested_vm=p.lua;self.error=''
        def apply():
            try:
                if serial!=self.serial or p.lua is not requested_vm or requested_vm.closed:return
                if not window.isVisible():raise ValueError('GRAPHICS_WINDOW_UNAVAILABLE')
                self.save(chosen)
                if self.standalone:
                    if chosen['gxWindow']=='0':window.showFullScreen()
                    else:window.showNormal();window.resize(width,height)
                # Qt releases and recreates this scene's renderer on the next
                # frame. Retained item/geometry owners and gameplay stay live.
                window.releaseResources();window.update()
                self.values=chosen;self.pending={};self.generation+=1
                requested_vm.request('runtime_config',values=chosen)
                requested_vm.request('graphics_mode',width=width,height=height)
                requested_vm.event('DISPLAY_SIZE_CHANGED')
            except OSError:self.fail('GRAPHICS_SAVE_FAILED')
            except (ValueError,RuntimeError) as exc:self.fail(str(exc))
            finally:
                if serial==self.serial:self.restarting=False
        QTimer.singleShot(0,apply)

    def fail(self,error):
        self.error=error
        if self.presentation.lua:self.presentation.lua.event('UI_ERROR_MESSAGE',error)
