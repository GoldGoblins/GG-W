"""Bounded capture interlock for GG's own sensitive local UI.

Only process identifiers are shared, never phrases, images, account identifiers
or passwords. This is not an OS-wide screen-capture/forensics protection.
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import struct
import sys
import threading

MAX_OWNERS=64
_lock=threading.RLock()
_owners:set[str]=set()
_channel=None


def _windows_scope():
    """Use the actual token SID, never configurable wallet/profile paths."""
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    security=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    security.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    security.GetLengthSid.argtypes=[ctypes.c_void_p];security.GetLengthSid.restype=wintypes.DWORD
    token=wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE')
    try:
        size=wintypes.DWORD();security.GetTokenInformation(token,1,None,0,ctypes.byref(size))
        if not 0<size.value<=16384:raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE')
        data=ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token,1,data,size,ctypes.byref(size)):raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE')
        sid=ctypes.cast(data,ctypes.POINTER(ctypes.c_void_p))[0];length=security.GetLengthSid(sid)
        if not 8<=length<=128:raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE')
        return hashlib.sha256(ctypes.string_at(sid,length)).hexdigest()[:24]
    finally:kernel.CloseHandle(token)


def _clean_pids(raw):
    if not isinstance(raw,list) or len(raw)>MAX_OWNERS or any(type(pid)is not int or not 0<pid<2**32 for pid in raw):
        raise RuntimeError('SENSITIVE_UI_GUARD_INVALID')
    import psutil
    return sorted(set(pid for pid in raw if psutil.pid_exists(pid)))


class _WindowsChannel:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        import mmap
        name='Local\\GoldGoblins.SensitiveUI.'+_windows_scope()
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype=wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype=wintypes.DWORD
        self.kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.mutex=self.kernel.CreateMutexW(None,False,name+'.Lock')
        if not self.mutex:raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE')
        try:self.memory=mmap.mmap(-1,4096,tagname=name)
        except BaseException:self.kernel.CloseHandle(self.mutex);raise
    def call(self,blocked=None,*,token=False):
        if self.kernel.WaitForSingleObject(self.mutex,300) not in (0,0x80):
            raise RuntimeError('SENSITIVE_UI_GUARD_BUSY')
        try:
            count=struct.unpack('!I',self.memory[:4])[0]
            if count==0:data={'pids':[],'generation':0}
            elif 0<count<=4092:data=json.loads(self.memory[4:4+count])
            else:raise RuntimeError('SENSITIVE_UI_GUARD_INVALID')
            if not isinstance(data,dict) or set(data)!={'pids','generation'} or type(data['generation'])is not int or not 0<=data['generation']<2**63:raise RuntimeError('SENSITIVE_UI_GUARD_INVALID')
            pids=_clean_pids(data['pids'])
            if blocked is True:
                if len(pids)>=MAX_OWNERS and os.getpid() not in pids:raise RuntimeError('SENSITIVE_UI_GUARD_LIMIT')
                pids=sorted(set(pids+[os.getpid()]))
                data['generation']=(data['generation']+1)%(2**63)
            elif blocked is False:pids=[pid for pid in pids if pid!=os.getpid()]
            data['pids']=pids
            raw=json.dumps(data,separators=(',',':')).encode()
            self.memory[4:4+len(raw)]=raw;self.memory[:4]=struct.pack('!I',len(raw))
            return (bool(pids),data['generation']) if token else bool(pids)
        finally:self.kernel.ReleaseMutex(self.mutex)
    def close(self):
        self.memory.close();self.kernel.CloseHandle(self.mutex)


def _termux_candidate(executable, uid):
    """Fixed private metadata location for Android, which lacks /dev/shm.

    Resolve the actual interpreter, never wallet/profile or environment paths.
    This flag contains process ids only; no recovery material is written here.
    """
    from pathlib import PurePosixPath
    path=PurePosixPath(str(executable));parts=path.parts
    if not str(path).startswith(('/data/data/','/data/user/')) or len(parts)<7:
        return None
    if parts[-2]!='bin':return None
    for index,name in enumerate(parts):
        if (name=='com.termux' or name.startswith('com.termux.')) and tuple(parts[index+1:index+3])==('files','usr'):
            prefix=PurePosixPath(*parts[:index+3])
            if path.parent!=prefix/'bin':return None
            return prefix/'tmp'/('gg-sensitive-ui-'+str(uid))
    return None


class _PosixChannel:
    def __init__(self):
        from pathlib import Path
        uid=os.getuid();candidates=[(Path('/run/user')/str(uid)/'gg-sensitive-ui',True),(Path('/dev/shm')/('gg-sensitive-ui-'+str(uid)),True)]
        termux=_termux_candidate(Path(sys.executable).resolve(),uid)
        if termux is not None:candidates.append((Path(termux),False))
        mounts=[]
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            left,right=line.split(' - ',1);mounts.append((Path(left.split()[4].replace('\\040',' ')),right.split()[0]))
        for root,ram_only in candidates:
            parent=root.parent.resolve();matches=[(mount,kind) for mount,kind in mounts if parent.is_relative_to(mount)]
            if not parent.is_dir():continue
            if ram_only and (not matches or max(matches,key=lambda row:len(str(row[0])))[1]!='tmpfs'):continue
            if not ram_only and (root.parent.is_symlink() or parent.stat().st_uid!=uid):continue
            if root.is_symlink():continue
            root.mkdir(mode=0o700,exist_ok=True)
            if root.stat().st_uid!=uid:continue
            root.chmod(0o700);self.root=root;return
        raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE')
    def call(self,blocked=None,*,token=False):
        import fcntl
        fd=os.open(self.root/'sensitive-ui.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            path=self.root/'sensitive-ui.json'
            try:
                read_fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                with os.fdopen(read_fd,'rb') as handle:raw=handle.read(4097)
                if len(raw)>4096:raise RuntimeError('SENSITIVE_UI_GUARD_INVALID')
                data=json.loads(raw)
            except FileNotFoundError:data={'pids':[],'generation':0}
            if not isinstance(data,dict) or set(data)!={'pids','generation'} or type(data['generation'])is not int or not 0<=data['generation']<2**63:raise RuntimeError('SENSITIVE_UI_GUARD_INVALID')
            pids=_clean_pids(data['pids'])
            if blocked is True:
                if len(pids)>=MAX_OWNERS and os.getpid() not in pids:raise RuntimeError('SENSITIVE_UI_GUARD_LIMIT')
                pids=sorted(set(pids+[os.getpid()]))
                data['generation']=(data['generation']+1)%(2**63)
            elif blocked is False:pids=[pid for pid in pids if pid!=os.getpid()]
            write_fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            data['pids']=pids
            with os.fdopen(write_fd,'wb') as handle:handle.write(json.dumps(data,separators=(',',':')).encode())
            return (bool(pids),data['generation']) if token else bool(pids)
    def close(self):pass


def _shared():
    global _channel
    if _channel is None:
        _channel=_WindowsChannel() if os.name=='nt' else _PosixChannel()
        atexit.register(_channel.close)
    return _channel


def enter(owner:str)->None:
    if not isinstance(owner,str) or not owner or len(owner)>192:raise ValueError('SENSITIVE_UI_OWNER_INVALID')
    with _lock:
        if owner in _owners:return
        if len(_owners)>=MAX_OWNERS:raise RuntimeError('SENSITIVE_UI_OWNER_LIMIT')
        _owners.add(owner)
        try:_shared().call(True)
        except Exception:raise RuntimeError('SENSITIVE_UI_GUARD_UNAVAILABLE') from None
    # Publish the interlock first, then cancel existing captures. Never resume
    # them on leave; a later observation requires a new explicit request.
    vision = sys.modules.get('backend.live_vision')
    if vision is not None:
        vision.stop_if_running()


def leave(owner:str)->None:
    with _lock:
        _owners.discard(owner)
        if not _owners:
            try:_shared().call(False)
            except Exception:pass  # A stale interlock fails closed.


def active()->bool:
    with _lock:
        if _owners:return True
        try:return _shared().call()
        except Exception:return True


def capture_token()->int:
    with _lock:
        try:
            blocked,generation=_shared().call(token=True)
            if _owners or blocked:raise RuntimeError('GG_CAPTURE_BLOCKED_SENSITIVE_UI')
            return generation
        except Exception:raise RuntimeError('GG_CAPTURE_BLOCKED_SENSITIVE_UI') from None


def require_capture_allowed(token:int|None=None)->None:
    if token is None:
        if active():raise RuntimeError('GG_CAPTURE_BLOCKED_SENSITIVE_UI')
    elif capture_token()!=token:raise RuntimeError('GG_CAPTURE_BLOCKED_SENSITIVE_UI')
