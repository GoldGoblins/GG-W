"""Bounded game logs, original console reload and real Qt screenshots."""
import json
import os
import time
from pathlib import Path
from PySide6.QtCore import QTimer

MAX_LOG=1024*1024


class ClientTools:
    def __init__(self,presentation):
        self.presentation=presentation;self.chat=False;self.combat=False
        self.last_sequence=None;self.last_scope=None;self.capture_pending=False
        self._capture_job=None

    def root(self):
        lua=self.presentation.lua
        if not lua or not getattr(lua,'saving_enabled',False):raise ValueError('CLIENT_SAVE_UNAVAILABLE')
        root=lua.character_saved_root or lua.saved_root
        if not root:raise ValueError('CLIENT_SAVE_UNAVAILABLE')
        return Path(root)

    def log(self,name,lines,*,rewrite=False):
        if name not in ('FrameXML.log','Chat.log','Combat.log'):raise ValueError('CLIENT_LOG_INVALID')
        if not isinstance(lines,list) or len(lines)>4096 or any(not isinstance(s,str) or len(s)>4096 for s in lines):raise ValueError('CLIENT_LOG_CAPACITY')
        if not lines:return
        chunk=('\n'.join(s.replace('\r',' ').replace('\n',' ') for s in lines)+'\n').encode('utf-8')
        if len(chunk)>MAX_LOG:raise ValueError('CLIENT_LOG_CAPACITY')
        directory=self.root()/'Logs';directory.mkdir(parents=True,exist_ok=True);target=directory/name
        previous=b''
        if not rewrite and target.is_file():
            with target.open('rb') as stream:
                stream.seek(max(0,target.stat().st_size-MAX_LOG));previous=stream.read(MAX_LOG)
        data=previous+chunk
        if len(data)>MAX_LOG:
            data=data[-MAX_LOG:];data=data.partition(b'\n')[2]
        temporary=directory/(name+'.tmp')
        try:
            with temporary.open('wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,target)
        finally:temporary.unlink(missing_ok=True)

    def events(self,rows):
        if not self.chat:return
        lines=[json.dumps(row,ensure_ascii=False,separators=(',',':')) for row in rows[:128] if str(row.get('event','')).startswith('CHAT_MSG_')]
        try:self.log('Chat.log',lines)
        except (ValueError,OSError) as exc:self.presentation._error(exc)

    def flags(self,request):
        logging=request.get('logging') if isinstance(request,dict) else None
        if isinstance(logging,dict):self.chat=logging.get('chat') is True;self.combat=logging.get('combat') is True

    def snapshot(self,snapshot):
        try:scope=str(self.root())
        except ValueError:return
        rows=snapshot.get('event_journal',{}).get('events',[])
        if self.last_scope!=scope:
            self.last_sequence=None;self.last_scope=scope
        sequence=max((int(r.get('sequence',0)) for r in rows),default=0)
        if self.last_sequence is None or sequence<self.last_sequence:self.last_sequence=sequence;return
        new=[r for r in rows if int(r.get('sequence',0))>self.last_sequence]
        self.last_sequence=sequence
        if self.combat:
            lines=[json.dumps(r,ensure_ascii=False,separators=(',',':')) for r in new if r.get('kind') in ('COMBAT_DAMAGE','COMBAT_HEAL','COMBAT_DEFEAT','COMBAT_ABILITY','COMBAT_STATUS','COMBAT_ATTACK')]
            try:self.log('Combat.log',lines)
            except (ValueError,OSError) as exc:self.presentation._error(exc)

    def requests(self,request):
        if not isinstance(request,dict):return
        p=self.presentation;self.flags(request)
        try:
            for row in request.get('load_logs',[])[:32]:self.log('FrameXML.log',row['lines'],rewrite=row.get('rewrite') is True)
        except (ValueError,OSError,KeyError) as exc:p._error(exc)
        for line in request.get('console',[])[:32]:
            if isinstance(line,str) and line.strip().casefold() in ('reloadui','reload'):
                if not p._reload_ui():p.lua.event('UI_ERROR_MESSAGE','CLIENT_UI_RELOAD_FAILED')
            else:p.lua.event('UI_ERROR_MESSAGE','CLIENT_CONSOLE_COMMAND_UNKNOWN')
        count=request.get('screenshots',0)
        if type(count) is int and count>0:
            if self.capture_pending or count>4:
                p.lua.event('SCREENSHOT_FAILED');return
            try:root=self.root()
            except ValueError:
                p.lua.event('SCREENSHOT_FAILED');return
            job={'vm':p.lua,'root':root,'count':count,'grab':None,'ready':None,'timer':None}
            self._capture_job=job;self.capture_pending=True
            QTimer.singleShot(0,lambda:self.capture(job))

    def _capture_current(self,job):
        p=self.presentation
        if self._capture_job is not job or p.lua is not job['vm'] or not p.lua or p.lua.closed:return False
        try:return self.root()==job['root']
        except ValueError:return False

    def _capture_finish(self,job,success=False,*,notify=True):
        if self._capture_job is not job:return
        current=self._capture_current(job)
        timer=job.get('timer')
        if timer:timer.stop();timer.deleteLater()
        grab,ready=job.get('grab'),job.get('ready')
        if grab is not None and ready is not None:
            try:grab.ready.disconnect(ready)
            except (RuntimeError,TypeError):pass
        self._capture_job=None;self.capture_pending=False
        if notify and current:job['vm'].event('SCREENSHOT_SUCCEEDED' if success else 'SCREENSHOT_FAILED')

    def capture(self,job):
        """Yield to Qt's render thread; a synchronous grab holds Python's GIL."""
        if self._capture_job is not job:return
        p=self.presentation
        try:
            if not self._capture_current(job):
                self._capture_finish(job,notify=False);return
            window=p._canvas.window() if p._canvas else None
            if window is None or not window.isVisible():raise ValueError('SCREENSHOT_WINDOW_UNAVAILABLE')
            directory=job['root']/'Screenshots'
            if directory.exists() and len(list(directory.glob('GG-*.png')))+job['count']>32:raise ValueError('SCREENSHOT_FOLDER_FULL')
            grab=window.contentItem().grabToImage()
            if grab is None:raise ValueError('SCREENSHOT_IMAGE_UNAVAILABLE')
            job['grab']=grab;job['ready']=lambda:self._capture_ready(job)
            grab.ready.connect(job['ready'])
            timer=QTimer();timer.setSingleShot(True)
            timer.timeout.connect(lambda:self._capture_finish(job))
            job['timer']=timer;timer.start(5000)
        except (ValueError,OSError,RuntimeError):self._capture_finish(job)

    def _capture_ready(self,job):
        if self._capture_job is not job:return
        success=False
        try:
            if not self._capture_current(job):return
            image=job['grab'].image()
            if image.isNull():raise ValueError('SCREENSHOT_IMAGE_UNAVAILABLE')
            directory=job['root']/'Screenshots';directory.mkdir(parents=True,exist_ok=True)
            if len(list(directory.glob('GG-*.png')))+job['count']>32:raise ValueError('SCREENSHOT_FOLDER_FULL')
            for index in range(job['count']):
                if not image.save(str(directory/('GG-'+str(time.time_ns())+'-'+str(index)+'.png')),'PNG'):raise OSError('SCREENSHOT_SAVE_FAILED')
            success=True
        except (ValueError,OSError,RuntimeError):pass
        finally:
            self._capture_finish(job,success)

    def close(self):
        if self._capture_job is not None:self._capture_finish(self._capture_job,notify=False)
