"""Bounded public committee certificates and a resident native verifier.

Only original predecessor-quorum certificates are persisted. Each native
process reconstructs its private trust from the pinned genesis; neither a
JSON flag, cache head nor a peer-selected filesystem path grants trust.
"""
import atexit
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import secrets
import stat
import struct
import subprocess
import threading
from backend import gg_process_termination as termination
from backend.gg_native_start import native_pipe_creation_flags
from backend import gg_native_pipe_lifecycle as native_pipes
import time

from backend.application_paths import DATA_HOME
from backend.gg_node_store import pack,unpack,_private_path
from backend.platform_files import is_link,secure_open,set_private_mode,sync_directory
from backend.platform_support import file_locks

MAX_FRAME=256*1024+1024
MAX_RECORDS=1000000
MAX_BYTES=8*1024**3
ROOT=Path(DATA_HOME)/'goldgoblins/public-committee-history'
_CACHE=OrderedDict()
_CACHE_LOCK=threading.RLock()


class _NativeStream:
    def __init__(self,pin,binary,stamp):
        from backend import gg_consensus as native
        self.binary=Path(binary);self.stamp=stamp;self.closed=False;self._lock=threading.RLock()
        env=native._environment();env['GOMEMLIMIT']='96MiB'
        with native_pipes.COMMITTEE_STREAM_INIT.construction() as reservation:
            self.process=subprocess.Popen([str(self.binary),'verify-stream'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,env=env,creationflags=native_pipe_creation_flags())
            reservation.attach(self)
            self.call('init',**deepcopy(pin))

    def _read(self,length):
        chunks=[];remaining=length
        while remaining:
            raw=self.process.stdout.read(remaining)
            if not raw:raise ValueError('GG_COMMITTEE_VERIFIER_UNAVAILABLE')
            chunks.append(raw);remaining-=len(raw)
        return b''.join(chunks)

    def call(self,action,**values):
        with self._lock:
            if self.closed or self.process.poll() is not None:raise ValueError('GG_COMMITTEE_VERIFIER_UNAVAILABLE')
            if self.stamp is not None:
                info=self.binary.stat()
                if (info.st_size,info.st_mtime_ns)!=self.stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')
            raw=pack({'schema':'gg.native.committee-verifier-request.v1','action':action,**values})
            if len(raw)>MAX_FRAME:raise ValueError('GG_CONSENSUS_PROOF_LIMIT')
            process=self.process
            def expired():
                try:process.kill()
                except OSError:pass
            deadline=threading.Timer(6,expired);deadline.daemon=True;deadline.start()
            try:
                process.stdin.write(struct.pack('>I',len(raw))+raw);process.stdin.flush()
                length=struct.unpack('>I',self._read(4))[0]
                if not 0<length<=8192:raise ValueError('GG_COMMITTEE_VERIFIER_RESPONSE')
                result=unpack(self._read(length))
                if not isinstance(result,dict) or result.get('ok') is not True:raise ValueError('GG_CONSENSUS_CERTIFICATE_INVALID')
                return result
            except (OSError,ValueError):
                if process.poll() is not None:self.closed=True
                raise
            finally:deadline.cancel()

    def close(self):
        with self._lock:
            self.closed=True
            try:
                if not termination.process_terminal(self.process):self.process.kill()
                termination.wait_process_terminal(self.process,1)
            except (OSError,subprocess.TimeoutExpired):pass
            # closed prevents further requests; only a fresh process result
            # establishes terminal cleanup. Keep this exact child and its pipes
            # available to the owner when bounded shutdown has not completed.
            try:terminal=termination.process_terminal(self.process)
            except OSError:terminal=False
            if not terminal:raise ValueError('GG_COMMITTEE_VERIFIER_STOP_PENDING')
            for stream in (self.process.stdin,self.process.stdout):
                if stream is not None:
                    try:stream.close()
                    except OSError:pass


class CommitteeHistory:
    def __init__(self,pin,binary,stamp):
        self.pin=deepcopy(pin);self.binary=Path(binary);self.stamp=stamp;self.epoch=0;self.bytes=0;self.closed=False
        self._historical=None;self._historical_epoch=0
        self._lock=threading.RLock();anchor=pin['genesis_hash']
        if type(anchor) is not str or len(anchor)!=64 or any(char not in '0123456789abcdef' for char in anchor):raise ValueError('GG_COMMITTEE_HISTORY_PIN')
        self.root=Path(ROOT).absolute()/anchor
        self._check_path();self.root.mkdir(mode=0o700,parents=True,exist_ok=True);set_private_mode(self.root,0o700);_private_path(self.root,0o700)
        with native_pipes.COMMITTEE_CONTEXT_INIT.construction() as reservation:
            self._stream=_NativeStream(pin,self.binary,stamp)
            reservation.attach(self)
            self.refresh()

    def _check_path(self):
        if str(self.root).startswith(('\\\\','//')) or any(is_link(path) for path in (self.root,*self.root.parents)):raise ValueError('GG_COMMITTEE_HISTORY_PATH')

    @contextmanager
    def _disk_lock(self):
        self._check_path();path=self.root/'history.lock';fd=secure_open(path,os.O_RDWR|os.O_CREAT,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size not in (0,1):raise ValueError('GG_COMMITTEE_HISTORY_LOCK')
            until=time.monotonic()+6
            while True:
                try:file_locks.flock(fd,file_locks.LOCK_EX|file_locks.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=until:raise ValueError('GG_COMMITTEE_HISTORY_BUSY') from None
                    time.sleep(.025)
            if os.fstat(fd).st_size==0:os.write(fd,b'0');os.fsync(fd)
            _private_path(path,0o600)
            yield
        finally:os.close(fd)

    def _path(self,epoch):
        if type(epoch) is not int or not 1<=epoch<=MAX_RECORDS:raise ValueError('GG_COMMITTEE_HISTORY_LIMIT')
        return self.root/(str(epoch).zfill(10)+'.json')

    def _read(self,epoch):
        path=self._path(epoch);self._check_path();fd=secure_open(path,os.O_RDONLY,0o600)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=256*1024:raise ValueError('GG_COMMITTEE_HISTORY_RECORD')
            raw=stream.read(256*1024+1)
        value=unpack(raw)
        if pack(value)!=raw:raise ValueError('GG_COMMITTEE_HISTORY_RECORD')
        return raw,value

    def _sync(self):
        while self.epoch<MAX_RECORDS and self._path(self.epoch+1).exists():
            raw,value=self._read(self.epoch+1)
            if self.bytes+len(raw)>MAX_BYTES:raise ValueError('GG_COMMITTEE_HISTORY_LIMIT')
            result=self._stream.call('transition',transition=value)
            if result.get('epoch')!=str(self.epoch+1):raise ValueError('GG_COMMITTEE_HISTORY_RECORD')
            self.epoch+=1;self.bytes+=len(raw)

    def refresh(self):
        with self._lock:
            if self.closed:raise ValueError('GG_COMMITTEE_HISTORY_CLOSED')
            with self._disk_lock():self._sync();return self.epoch

    def _append(self,value):
        raw=pack(value)
        try:epoch=int(value['state']['protocol']['pending_committee']['next']['epoch'])
        except (TypeError,KeyError,ValueError):raise ValueError('GG_COMMITTEE_HISTORY_RECORD') from None
        if not 0<len(raw)<=256*1024 or self.bytes+len(raw)>MAX_BYTES:raise ValueError('GG_COMMITTEE_HISTORY_LIMIT')
        if epoch<=self.epoch:
            previous,_=self._read(epoch)
            if previous!=raw:raise ValueError('GG_COMMITTEE_HISTORY_DIFFERENT_PREDECESSOR_CERTIFICATE')
            return
        if epoch!=self.epoch+1:raise ValueError('GG_COMMITTEE_HISTORY_GAP')
        result=self._stream.call('transition',transition=value)
        if result.get('epoch')!=str(epoch):raise ValueError('GG_COMMITTEE_HISTORY_RECORD')
        temporary=self.root/('.pending-'+secrets.token_hex(16))
        try:
            fd=secure_open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            set_private_mode(temporary,0o600);os.replace(temporary,self._path(epoch));sync_directory(self.root)
            self.epoch=epoch;self.bytes+=len(raw)
        except BaseException:
            # The native process may already have advanced. Retire it instead
            # of retaining an unjournaled trust context after an I/O failure.
            self.close();raise

    def append(self,value):
        with self._lock:
            if self.closed:raise ValueError('GG_COMMITTEE_HISTORY_CLOSED')
            with self._disk_lock():self._sync();self._append(value)

    def transition(self,epoch):
        with self._lock:
            if self.closed:raise ValueError('GG_COMMITTEE_HISTORY_CLOSED')
            with self._disk_lock():
                self._sync()
                if type(epoch) is not int or not 1<=epoch<=self.epoch:raise ValueError('GG_COMMITTEE_HISTORY_SELECTOR')
                return self._read(epoch)[1]

    def verify(self,payload):
        with self._lock:
            if self.closed:raise ValueError('GG_COMMITTEE_HISTORY_CLOSED')
            with self._disk_lock():
                self._sync();packet=deepcopy(payload);transitions=packet.pop('committee_transitions',[])
                if not isinstance(transitions,list) or len(transitions)>128:raise ValueError('GG_CONSENSUS_PROOF_LIMIT')
                for index,value in enumerate(transitions,1):
                    try:epoch=value['state']['protocol']['pending_committee']['next']['epoch']
                    except (KeyError,TypeError):raise ValueError('GG_COMMITTEE_HISTORY_RECORD') from None
                    if epoch!=str(index):raise ValueError('GG_COMMITTEE_HISTORY_GAP')
                    self._append(value)
                state=packet['state']['protocol'];needed=int(state['committee']['epoch'])
                if state.get('pending_committee') is not None:needed=int(state['pending_committee']['next']['epoch'])
                if not 0<=needed<=self.epoch:raise ValueError('GG_COMMITTEE_HISTORY_GAP')
                if needed==self.epoch:return self._stream.call('verify',proof=packet)['result']
                # Old protected certificates retain their historical meaning. A
                # separate bounded native context checks them without rewinding
                # the live verifier or treating an old certificate as contact.
                previous=self._historical
                if previous is None or previous.closed or previous.process.poll() is not None or self._historical_epoch>needed:
                    if previous is not None:previous.close()
                    previous=_NativeStream(self.pin,self.binary,self.stamp);self._historical=previous;self._historical_epoch=0
                for epoch in range(self._historical_epoch+1,needed+1):
                    previous.call('transition',transition=self._read(epoch)[1]);self._historical_epoch=epoch
                return previous.call('verify',proof=packet)['result']

    def close(self):
        with self._lock:
            self.closed=True;self._stream.close()
            if self._historical is not None:self._historical.close();self._historical=None


def history(pin,binary,stamp):
    key=(str(Path(binary).resolve()),stamp,pin['genesis_hash'])
    with _CACHE_LOCK:
        current=_CACHE.get(key)
        if current is not None and (current.closed or current._stream.closed or current._stream.process.poll() is not None):
            current.close();_CACHE.pop(key);current=None
        if current is None:
            # Retire an existing context before allocating another helper.
            # STOP_PENDING retains its exact cached owner and prevents both
            # capacity growth and replacement while shutdown is incomplete.
            while len(_CACHE)>=2:
                retired_key,retired=next(iter(_CACHE.items()))
                retired.close()
                _CACHE.pop(retired_key)
            current=CommitteeHistory(pin,binary,stamp);_CACHE[key]=current
        _CACHE.move_to_end(key)
        return current


def close_all():
    with _CACHE_LOCK:
        for value in _CACHE.values():value.close()
        _CACHE.clear()


atexit.register(close_all)
