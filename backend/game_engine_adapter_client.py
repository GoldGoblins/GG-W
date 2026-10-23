"""Qt login/session controller over the original, isolated native protocol.

One finite IO lane serves requests; GUI polling never blocks on a socket.
Cancellation terminates the isolated worker and invalidates its generation.
No automatic credential lookup, reconnect, network target or secret persistence.
"""
import copy,hashlib,json,os,sys,threading,time
from backend.platform_support import native_directory, native_library_name
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,QCoreApplication
from backend.game_engine_adapter_assets import PROJECT
from backend.game_engine_adapter_transport import BoundedWorker

NATIVE=native_directory(PROJECT)

def available():
    try:
        receipt=json.loads((NATIVE/'engine-client-build.json').read_text());digest=hashlib.sha256()
        root=PROJECT/'native/engine-formats'
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.suffix in ('.rs','.h','.toml','.lock'):
                digest.update(path.relative_to(root).as_posix().encode());digest.update(path.read_bytes())
        return receipt['abi']==1 and receipt['source_sha256']==digest.hexdigest() and receipt['binary_sha256']==hashlib.sha256((NATIVE/native_library_name('gg_engine_client')).read_bytes()).hexdigest()
    except (OSError,ValueError,KeyError):return False

class NativeClient(BoundedWorker):
    def __init__(self):
        if not available():raise RuntimeError('Verified GgEngine client core unavailable')
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        # The client takes credentials only in a submitted in-memory request.
        for key in ('WOW_USER','WOW_PASS'):env.pop(key,None)
        self._start_worker([sys.executable,'-B',str(PROJECT/'backend/game_engine_adapter_client_worker.py'),str(NATIVE/native_library_name('gg_engine_client'))],env)
        self.request('ping',timeout=3)

class GgEngineClient(QObject):
    changed=Signal()
    eventReceived=Signal('QVariantMap')
    def __init__(self,parent=None):
        super().__init__(parent);self._state={'phase':'LOGIN','realms':[],'characters':[],'queue':None}
        self._error='';self._worker=None;self._future=None;self._future_op='';self._queued=None;self._generation=0;self._guard=threading.Lock();self._closed=False
        self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='gg-engine-client')
        self._packets=0;self._dropped=0;self._views={};self._view_sizes={};self._view_bytes=0;self._entities={};self._entity_sizes={};self._entity_bytes=0;self._last_poll=0.;self._last_refresh=0.
        self._timer=QTimer(self);self._timer.setInterval(50);self._timer.timeout.connect(self._tick)
        app=QCoreApplication.instance()
        if app:app.aboutToQuit.connect(self.close)
    @Property('QVariantMap',notify=changed)
    def state(self):
        return {**self._state,'busy':self.busy,'error':self._error,'packets':self._packets,'dropped':self._dropped,'entity_count':len(self._entities),'entity_bytes':self._entity_bytes,'view_bytes':self._view_bytes}
    @Property(bool,notify=changed)
    def busy(self):return self._queued is not None or self._future is not None and self._future_op not in ('poll','refresh_realms')
    @Property(str,notify=changed)
    def error(self):return self._error
    def _job(self,generation,op,timeout,kwargs):
        with self._guard:
            if self._closed or generation!=self._generation:raise RuntimeError('Client request cancelled')
            worker=self._worker
        if worker is None or worker.closed:
            worker=NativeClient()
            with self._guard:
                if self._closed or generation!=self._generation:worker.close();raise RuntimeError('Client request cancelled')
                self._worker=worker
        return generation,op,worker.request(op,timeout=timeout,**kwargs)
    def _begin(self,op,timeout=6,**kwargs):
        if self._closed:return False
        if self._future is not None:
            if self._future_op in ('poll','refresh_realms') and self._queued is None and op not in ('poll','refresh_realms'):
                self._queued=(op,timeout,kwargs);self.changed.emit();return True
            return False
        self._error='';self._future_op=op;self._future=self._pool.submit(self._job,self._generation,op,timeout,kwargs);self._timer.start();self.changed.emit();return True
    @Slot(str,str,str,result=bool)
    def login(self,host,username,password):
        if self._state['phase']!='LOGIN' or self._future is not None:return False
        if not host or len(host)>253 or any(c.isspace() for c in host) or not 0<len(username)<=16 or not 0<len(password)<=16:
            self._error='Serveradress och konto behövs; konto och lösenord får ha 1–16 tecken.';self.changed.emit();return False
        self._state['phase']='AUTHENTICATING'
        return self._begin('auth',20,host=host,username=username,password=password)
    @Slot(int,result=bool)
    def selectRealm(self,index):
        realms=self._state.get('realms',[])
        if self._state['phase']!='REALMS' or not 0<=index<len(realms) or realms[index].get('flags',0)&3:return False
        return self._begin('connect_realm',25,index=index)
    @Slot(result=bool)
    def refreshRealms(self):
        if self._state['phase']!='REALMS':return False
        self._last_refresh=time.monotonic();return self._begin('refresh_realms')
    @Slot(result=bool)
    def backRealms(self):return self._begin('back_realms')
    @Slot(str,result=bool)
    def enterWorld(self,guid):
        if self._state['phase']!='CHARACTERS' or not any(c['guid']==guid for c in self._state.get('characters',[])):return False
        return self._begin('enter_world',guid=guid)
    @Slot('QVariantMap',result=bool)
    def createCharacter(self,character):
        if self._state['phase']!='CHARACTERS':return False
        if not isinstance(character,dict):return False
        return self._begin('create_character',character=character)
    @Slot(str,str,result=bool)
    def deleteCharacter(self,guid,confirmation):
        if self._state['phase']!='CHARACTERS' or not any(c['guid']==guid and c['name']==confirmation for c in self._state.get('characters',[])):return False
        return self._begin('delete_character',guid=guid)
    @Slot('QVariantMap',result=bool)
    def command(self,request):
        try:
            if not isinstance(request,dict) or len(json.dumps(request,allow_nan=False).encode())>60000:return False
        except (TypeError,ValueError):return False
        return self._begin('command',**{k:v for k,v in request.items() if k not in ('op','timeout')})
    @Slot()
    def cancel(self):
        with self._guard:
            self._generation+=1;worker,self._worker=self._worker,None
        if worker:worker.close()
        self._future=None;self._future_op='';self._queued=None;self._timer.stop();self._state={'phase':'LOGIN','realms':[],'characters':[],'queue':None}
        self._error='';self._clear_entities();self._views.clear();self._view_sizes.clear();self._view_bytes=0;self.changed.emit()
    def _remove_entity(self,guid):
        self._entities.pop(guid,None);self._entity_bytes-=self._entity_sizes.pop(guid,0)
    def _clear_entities(self):
        self._entities.clear();self._entity_sizes.clear();self._entity_bytes=0
    def _retain_entity(self,guid,data):
        size=len(json.dumps(data,separators=(',',':')).encode())
        if size>1024*1024:self._dropped+=1;return
        self._remove_entity(guid)
        while self._entities and (len(self._entities)>=4096 or self._entity_bytes+size>16*1024*1024):
            self._remove_entity(next(iter(self._entities)));self._dropped+=1
        self._entities[guid]=copy.deepcopy(data);self._entity_sizes[guid]=size;self._entity_bytes+=size
    @Slot(str,result='QVariantMap')
    def entity(self,guid):return copy.deepcopy(self._entities.get(guid,{}))
    @Slot(str,result='QVariantMap')
    def view(self,kind):return copy.deepcopy(self._views.get(kind,{}))
    def _event(self,event):
        kind=event.get('kind','');data=event.get('data')
        if not isinstance(kind,str) or not kind:return
        if kind in ('ObjectCreate','ItemCreate') and isinstance(data,dict):
            guid=data.get('guid')
            if isinstance(guid,str):self._retain_entity(guid,data)
        elif kind in ('ObjectMove','UnitMove','ObjectValues') and isinstance(data,dict):
            previous=self._entities.get(data.get('guid'))
            if previous is not None:
                previous=copy.deepcopy(previous)
                if kind=='ObjectValues':
                    old=dict(previous.get('fields',{}).get('fields',[]));old.update(data.get('fields',{}).get('fields',[]));previous['fields']={'fields':list(old.items())}
                else:previous.update(data)
                self._retain_entity(data['guid'],previous)
        elif kind=='ObjectDestroyed' and isinstance(data,list) and data:self._remove_entity(data[0])
        elif kind=='ObjectsRemoved' and isinstance(data,list) and data:
            for guid in data[0]:self._remove_entity(guid)
        elif kind in ('LoggedOut','Disconnected','Worldport'):self._clear_entities()
        if kind in ('PacketDropped',):self._dropped+=1
        if kind=='CharActionResult' and isinstance(data,dict) and data.get('code') not in (0x2e,0x39):self._error='Karaktärsåtgärden nekades: '+str(data.get('code'))
        if kind in ('LoginFailed','Disconnected') and isinstance(data,dict):self._error=str(data.get('reason') or 'Anslutningen nekades.')[:240]
        # Retain bounded latest views; entity updates have their own keyed store.
        if kind not in ('ObjectCreate','ItemCreate','ObjectMove','UnitMove','ObjectValues','ObjectDestroyed','ObjectsRemoved'):
            size=len(json.dumps(event,separators=(',',':')).encode())
            if size<=1024*1024:
                self._view_bytes-=self._view_sizes.pop(kind,0);self._views.pop(kind,None)
                while self._views and (len(self._views)>=128 or self._view_bytes+size>8*1024*1024):
                    old=next(iter(self._views));self._views.pop(old);self._view_bytes-=self._view_sizes.pop(old)
                self._views[kind]=event;self._view_sizes[kind]=size;self._view_bytes+=size
        self.eventReceived.emit(event)
    def _tick(self):
        if self._closed:return
        if self._future is not None and self._future.done():
            future,self._future=self._future,None;self._future_op=''
            try:
                generation,op,result=future.result()
                if generation!=self._generation:return
                if op=='poll':
                    self._error=''
                    self._state=result['state']
                    for packet in result['packets']:
                        self._packets+=1
                        for event in packet.get('events',[packet]):self._event(event)
                elif isinstance(result,dict) and 'phase' in result:self._state=result
                else:self._error=''
            except (OSError,ValueError,RuntimeError,TimeoutError) as error:
                self._error=str(error)[:240]
                if self._state['phase']=='AUTHENTICATING':self._state['phase']='LOGIN'
                worker=self._worker
                if worker is None or worker.closed:self._state['phase']='LOGIN'
            self.changed.emit()
        if self._future is None:
            if self._queued is not None:
                op,timeout,kwargs=self._queued;self._queued=None;self._begin(op,timeout,**kwargs);return
            now=time.monotonic();phase=self._state['phase']
            if phase in ('REALM_AUTH','QUEUE','ROSTER_LOADING','CHARACTERS','CHARACTER_ACTION','WORLD_LOADING','WORLD') and now-self._last_poll>=.05:
                self._last_poll=now;self._begin('poll',3)
            elif phase=='REALMS' and now-self._last_refresh>=5:self.refreshRealms()
            elif phase=='LOGIN':self._timer.stop()
    @Slot()
    def close(self):
        if self._closed:return
        self.cancel();self._closed=True;self._pool.shutdown(wait=False,cancel_futures=True)

def client_for(host):
    if not hasattr(host,'_engine_client'):host._engine_client=GgEngineClient(host)
    return host._engine_client
