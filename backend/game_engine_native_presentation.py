"""Checked presentation ABI. No downloads or compilation during game startup."""
from __future__ import annotations
from backend.platform_support import native_directory, native_library_name
import ctypes as C
import hashlib,json,os,struct,threading,weakref
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
class Instance(C.Structure):
    _fields_=[(name,C.c_double) for name in ('x','y','z','scale','pitch','yaw','roll','tint','r','g','b','alpha')]
class Snapshot(C.Structure):
    _fields_=[(name,C.c_double) for name in ('x','y','z','yaw','time','speed','health','resource')]+[('running',C.c_uint32)]
_lib=None;_attempted=False;_reason='NOT_LOADED';_lock=threading.RLock()

def source_digest():
    root=PROJECT/'native/presentation';d=hashlib.sha256()
    for p in sorted([*(root.glob('*.h')),root/'gg_presentation.cpp',*(root/'lua').glob('*.c'),*(root/'lua').glob('*.h')]):
        d.update(p.relative_to(root).as_posix().encode());d.update(p.read_bytes())
    return d.hexdigest()

def library():
    global _lib,_attempted,_reason
    mode=os.environ.get('GG_GAME_PRESENTATION_NATIVE','auto')
    if mode=='0':return None
    with _lock:
        if not _attempted:
            _attempted=True
            try:
                root=native_directory(PROJECT);path=root/native_library_name('gg_presentation')
                m=json.loads((root/'presentation-build.json').read_text())
                if m.get('abi')!=1 or m.get('source_sha256')!=source_digest():raise ValueError('presentation source/build mismatch')
                if m.get('binary_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('presentation binary/build mismatch')
                l=C.CDLL(str(path));P=C.c_void_p;F=C.c_float;D=C.c_double;U=C.c_uint32;S=C.c_char_p
                definitions={
                    'ggm_abi_version':([],U), 'ggm_pack_instances':([C.POINTER(Instance),U,C.POINTER(F),U],C.c_int),
                    'ggm_audio_create':([U],P),'ggm_audio_destroy':([P],None),'ggm_audio_clip':([P,U,C.POINTER(F),U,U],C.c_int),
                    'ggm_audio_clip_channels':([P,U,C.POINTER(F),U,U,U],C.c_int),'ggm_audio_pitch':([P,U,F],C.c_int),'ggm_audio_voice_active':([P,U],C.c_int),
                    'ggm_audio_voice_token':([P,U],C.c_uint64),
                    'ggm_audio_voice_stop':([P,U,C.c_uint64],C.c_int),'ggm_audio_clip_active':([P,U],C.c_int),'ggm_audio_clip_release':([P,U],C.c_int),
                    'ggm_audio_voice_position':([P,U,C.c_uint64,D,D,D],C.c_int),
                    'ggm_audio_play':([P,U,U,D,D,D,F,F,F,U],C.c_int),'ggm_audio_listener':([P,D,D,D,D],C.c_int),
                    'ggm_audio_gain':([P,F,F,F,F,U],C.c_int),'ggm_audio_render':([P,C.POINTER(F),U],C.c_int),
                    'ggm_audio_stop':([P,C.c_int],C.c_int),'ggm_audio_voices':([P],U),
                    'ggm_audio_reverb':([P,F,F,F,F],C.c_int),'ggm_audio_fade':([P,U,F,U,U],C.c_int),
                    'ggm_audio_pause':([P,U,U],C.c_int),
                    'ggm_audio_stream_create':([P,U,U,U],C.c_int),'ggm_audio_stream_write':([P,U,C.POINTER(F),U,U],C.c_int),
                    'ggm_audio_stream_free':([P,U],C.c_int),'ggm_audio_stream_play':([P,U,U,F],C.c_int),
                    'ggm_audio_stream_active':([P,U],C.c_int),
                    'ggm_lua_create':([U],P),'ggm_lua_destroy':([P],None),'ggm_lua_exec':([P,S,U,S],C.c_int),
                    'ggm_lua_snapshot':([P,C.POINTER(Snapshot),S,S],C.c_int),'ggm_lua_event':([P,S,S],C.c_int),
                    'ggm_lua_click':([P,S],C.c_int),'ggm_lua_frames':([P,C.POINTER(C.c_char),U],C.c_int),
                    'ggm_lua_error':([P,C.POINTER(C.c_char),U],C.c_int),'ggm_lua_memory':([P],U)}
                for name,(args,result) in definitions.items():f=getattr(l,name);f.argtypes=args;f.restype=result
                if l.ggm_abi_version()!=1:raise ValueError('presentation ABI mismatch')
                _lib=l;_reason='READY'
            except (OSError,ValueError,KeyError,AttributeError) as exc:_reason=type(exc).__name__+': '+str(exc)[:160]
        if _lib is None and mode=='required':raise RuntimeError(_reason)
        return _lib

def status():
    return {'backend':'CPP' if library() else 'UNAVAILABLE','reason':_reason,'abi':1}

def check(code):
    if code<0:raise ValueError('native presentation input or capacity rejected')
    return code

def encoded_text(value,limit):
    text=str(value)
    if '\x00' in text:raise ValueError('NUL is not valid in Lua interface text')
    return text.encode('utf-8')[:limit].decode('utf-8','ignore').encode('utf-8')

def pack_instances(rows):
    if len(rows)>65536:raise ValueError('instance capacity exceeded')
    l=library()
    if l is None:return None
    from PySide6.QtGui import QColor
    data=bytearray(96*len(rows))
    for i,row in enumerate(rows):
        rgb=(1.,1.,1.)
        if row.get('editor_color'):
            color=QColor(row['editor_color'])
            if not color.isValid():raise ValueError('invalid instance color')
            rgb=(color.redF(),color.greenF(),color.blueF())
        struct.pack_into('=12d',data,i*96,*(row[k] for k in ('x','y','z','scale')),
                         *(row.get(k,0) for k in ('pitch','yaw','roll')),row.get('tint',1),*rgb,row.get('alpha',1))
    out=(C.c_float*(20*len(rows)))()
    check(l.ggm_pack_instances((Instance*len(rows)).from_buffer(data),len(rows),out,len(rows)))
    return bytes(out)

class Owned:
    def _alive(self):
        if not self._finalizer.alive:raise RuntimeError('native presentation handle closed')
    def close(self):self._finalizer()

class Audio(Owned):
    def __init__(self,rate=48000):
        self.lib=library()
        if self.lib is None:raise RuntimeError('native audio unavailable')
        self.handle=self.lib.ggm_audio_create(rate)
        if not self.handle:raise ValueError('invalid audio sample rate')
        self.rate=rate;self._finalizer=weakref.finalize(self,self.lib.ggm_audio_destroy,self.handle)
    def clip(self,identity,samples,rate,channels=1):
        self._alive()
        if channels not in (1,2) or len(samples)%channels:raise ValueError('Invalid sound channel layout')
        data=(C.c_float*len(samples))(*samples);check(self.lib.ggm_audio_clip_channels(self.handle,identity,data,len(samples)//channels,rate,channels))
    def voice_active(self,voice):self._alive();return bool(self.lib.ggm_audio_voice_active(self.handle,voice))
    def voice_token(self,voice):self._alive();return self.lib.ggm_audio_voice_token(self.handle,voice)
    def stop_voice(self,voice,token):self._alive();check(self.lib.ggm_audio_voice_stop(self.handle,voice,token))
    def move_voice(self,voice,token,position):self._alive();check(self.lib.ggm_audio_voice_position(self.handle,voice,token,*position))
    def clip_active(self,identity):self._alive();return bool(check(self.lib.ggm_audio_clip_active(self.handle,identity)))
    def release_clip(self,identity):self._alive();check(self.lib.ggm_audio_clip_release(self.handle,identity))
    def play(self,identity,bus=0,position=None,gain=.5,near=2,far=60,loop=False,reverb=False,pitch=1):
        self._alive();spatial=position is not None;position=(0,0,0) if position is None else position
        if not .01<=pitch<=8:raise ValueError('Invalid sound pitch')
        voice=self.lib.ggm_audio_play(self.handle,identity,bus,*position,gain,near,far,int(loop)+2*int(spatial)+4*int(reverb))
        if pitch!=1 and voice>=0:check(self.lib.ggm_audio_pitch(self.handle,voice,pitch))
        return voice
    def reverb(self,wet=0,feedback=.9,damping=.1,width=1):self._alive();check(self.lib.ggm_audio_reverb(self.handle,wet,feedback,damping,width))
    def fade(self,voice,target,ms=15,stop=False):self._alive();check(self.lib.ggm_audio_fade(self.handle,voice,target,ms,stop))
    def pause(self,voice,paused=True):self._alive();check(self.lib.ggm_audio_pause(self.handle,voice,bool(paused)))
    def stream_create(self,identity,rate=48000,capacity=48000):self._alive();check(self.lib.ggm_audio_stream_create(self.handle,identity,rate,capacity))
    def stream_free(self,identity):self._alive();return check(self.lib.ggm_audio_stream_free(self.handle,identity))
    def stream_write(self,identity,samples,end=False):
        self._alive()
        if len(samples)%2:raise ValueError('Stereo stream frames required')
        data=(C.c_float*len(samples))(*samples)
        return check(self.lib.ggm_audio_stream_write(self.handle,identity,data,len(samples)//2,end))
    def stream_play(self,identity,bus=1,gain=.5):self._alive();return check(self.lib.ggm_audio_stream_play(self.handle,identity,bus,gain))
    def stream_active(self,identity):self._alive();return self.lib.ggm_audio_stream_active(self.handle,identity)
    def listener(self,x,y,z,yaw):self._alive();check(self.lib.ggm_audio_listener(self.handle,x,y,z,yaw))
    def gain(self,master=.5,sfx=1,music=.4,ambience=.6,enabled=True):self._alive();check(self.lib.ggm_audio_gain(self.handle,master,sfx,music,ambience,bool(enabled)))
    def render(self,n):
        self._alive()
        if not 0<=n<=16384:raise ValueError('audio block capacity exceeded')
        out=(C.c_float*(n*2))();check(self.lib.ggm_audio_render(self.handle,out,n));return bytes(out)
    def stop(self,bus=-1):self._alive();check(self.lib.ggm_audio_stop(self.handle,bus))
    def voices(self):self._alive();return self.lib.ggm_audio_voices(self.handle)

class Lua(Owned):
    def __init__(self,memory=4194304):
        self.lib=library()
        if self.lib is None:raise RuntimeError('native Lua unavailable')
        self.handle=self.lib.ggm_lua_create(memory)
        if not self.handle:raise MemoryError('Lua VM allocation rejected')
        self._finalizer=weakref.finalize(self,self.lib.ggm_lua_destroy,self.handle)
    def _result(self,code):
        if code<0:
            out=C.create_string_buffer(512);self.lib.ggm_lua_error(self.handle,out,len(out))
            raise ValueError(out.value.decode('utf-8','replace') or 'Lua input rejected')
        return code
    def execute(self,source,name='GG'):
        self._alive();data=source.encode('utf-8')
        if len(data)>262144 or data.startswith(b'\x1b'):raise ValueError('Lua source required, maximum 256 KiB')
        self._result(self.lib.ggm_lua_exec(self.handle,data,len(data),name.encode('utf-8')))
    def publish(self,player,running,health=100,resource=100):
        self._alive();s=Snapshot(*(float(player.get(k,0)) for k in ('x','y','z','yaw','time_s','speed')),health,resource,running)
        self._result(self.lib.ggm_lua_snapshot(self.handle,C.byref(s),encoded_text(player.get('cell_key',''),96),encoded_text(player.get('biome','WORLD'),96)))
    def event(self,name,payload=''):
        self._alive();self._result(self.lib.ggm_lua_event(self.handle,encoded_text(name,64),encoded_text(payload,512)))
    def click(self,identity):self._alive();self._result(self.lib.ggm_lua_click(self.handle,identity.encode()))
    def frames(self):
        self._alive();out=C.create_string_buffer(65536);self._result(self.lib.ggm_lua_frames(self.handle,out,len(out)));return json.loads(out.value)
    def memory(self):self._alive();return self.lib.ggm_lua_memory(self.handle)
