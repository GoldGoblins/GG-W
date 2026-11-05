"""Bounded disposable prefixes for authenticated GET; never admitted history.

Every request authenticates afresh. Resumed bytes still require a complete wire
digest, authenticated outer END and ordinary block/TX validation by the caller.
"""
from collections import OrderedDict
import hashlib
import re
import tempfile
import threading
import time

HASH=re.compile(r'[0-9a-f]{64}')
MAX_PEERS=2
PEER_RECORDS=8
PEER_BYTES=64*1024*1024
MAX_RECORDS=MAX_PEERS*PEER_RECORDS
MAX_BYTES=MAX_PEERS*PEER_BYTES
IDLE_SECONDS=30


def resume_hints(value,hashes,maximum):
    if not isinstance(value,list) or len(value)>len(hashes):raise ValueError('GG_LAN_GET')
    result={}
    for row in value:
        if (not isinstance(row,dict) or set(row)!={'hash','size','wire_sha256','offset'} or row['hash'] not in hashes
                or row['hash'] in result or not isinstance(row['wire_sha256'],str) or not HASH.fullmatch(row['wire_sha256'])
                or type(row['size']) is not int or not 44*1024<row['size']<=maximum or type(row['offset']) is not int
                or not 0<row['offset']<=row['size'] or row['offset']%(32*1024) and row['offset']!=row['size']):
            raise ValueError('GG_LAN_GET')
        result[row['hash']]=dict(row)
    return result


def local_error(error):
    code=str(error)
    return code.startswith('GG_LAN_GET_SPOOL_') or code in {
        'GG_LAN_GET_RESUME_BUSY','GG_LAN_GET_RESUME_CREDIT','GG_LAN_GET_RESUME_STOPPED','GG_LAN_GET_RESUME_DEADLINE'}


class GetResumeCache:
    def __init__(self):
        self.lock=threading.RLock();self.rows=OrderedDict();self.gates={};self.closed=False
        self.fault='';self.blocked=False;self.sessions=0;self.hint_fallback=set()

    def _drop(self,key,*,only_idle=False):
        with self.lock:
            row=self.rows.get(key)
            if row is None or only_idle and (row['active'] or row.get('closing')):return
            if row.get('closing'):raise ValueError('GG_LAN_GET_RESUME_BUSY')
            row['closing']=True
        failed=False
        try:
            if row['file'] is not None:row['file'].close()
        except OSError:
            with self.lock:
                self.fault='GG_LAN_GET_SPOOL_CLOSE';self.blocked=True
                if getattr(row['file'],'closed',False) is not True:
                    row['closing']=False;row['close_failed']=True
                    raise ValueError('GG_LAN_GET_SPOOL_CLOSE') from None
            failed=True
        # Credit remains reserved until the actual file handle was closed.
        with self.lock:
            if self.rows.get(key) is row:self.rows.pop(key)
        if failed:raise ValueError('GG_LAN_GET_SPOOL_CLOSE')

    def _expire_peer(self,peer,network=None,maximum=None):
        with self.lock:
            if self.closed:return
            stale=[key for key,row in self.rows.items() if key[1]==peer and not row['active']
                and not row.get('closing') and not row.get('close_failed') and
                (time.monotonic()-row['touched']>=IDLE_SECONDS or network is not None and key[0]!=network
                    or maximum is not None and row['meta']['size']>maximum)]
        for key in stale:self._drop(key,only_idle=True)

    def expire(self,peer):
        with self.lock:gate=self.gates.get(peer)
        if gate is None or not gate.acquire(blocking=False):return
        try:self._expire_peer(peer)
        finally:gate.release()

    def begin(self,peer,network,hashes,maximum,deadline,cancel):
        if (not isinstance(peer,str) or not HASH.fullmatch(peer) or not isinstance(network,str) or not HASH.fullmatch(network)
                or not isinstance(hashes,list) or not 1<=len(hashes)<=8
                or any(not isinstance(value,str) or not HASH.fullmatch(value) for value in hashes) or len(set(hashes))!=len(hashes)
                or type(maximum) is not int or not 1<=maximum<=32*1024*1024):
            raise ValueError('GG_LAN_GET')
        with self.lock:
            if self.closed or self.blocked:raise ValueError(self.fault or 'GG_LAN_GET_RESUME_STOPPED')
            if peer not in self.gates:
                if len(self.gates)>=MAX_PEERS:raise ValueError('GG_LAN_GET_RESUME_CREDIT')
                self.gates[peer]=threading.Lock()
            gate=self.gates[peer]
        while not gate.acquire(timeout=.025):
            if cancel.is_set():raise ValueError('GG_LAN_GET_RESUME_STOPPED')
            if time.monotonic()>=deadline:raise ValueError('GG_LAN_GET_RESUME_DEADLINE')
        try:
            with self.lock:
                if cancel.is_set() or self.closed:raise ValueError('GG_LAN_GET_RESUME_STOPPED')
                if self.blocked:raise ValueError(self.fault)
                if time.monotonic()>=deadline:raise ValueError('GG_LAN_GET_RESUME_DEADLINE')
            self._expire_peer(peer,network,maximum)
            return GetResumeSession(self,gate,peer,network,hashes,maximum)
        except BaseException:
            gate.release();raise

    def _new(self,key,meta):
        size=meta['size'];peer=key[1]
        while True:
            with self.lock:
                if self.closed or self.blocked:raise ValueError(self.fault or 'GG_LAN_GET_RESUME_STOPPED')
                own=[(name,row) for name,row in self.rows.items() if name[1]==peer]
                fits=(len(own)<PEER_RECORDS and sum(row['meta']['size'] for _,row in own)+size<=PEER_BYTES
                    and len(self.rows)<MAX_RECORDS and sum(row['meta']['size'] for row in self.rows.values())+size<=MAX_BYTES)
                if fits:
                    row={'meta':dict(meta),'file':None,'offset':0,'active':True,'touched':time.monotonic()}
                    self.rows[key]=row;break
                victim=next((name for name,row in own if not row['active'] and not row.get('closing')),None)
            if victim is None:raise ValueError('GG_LAN_GET_RESUME_CREDIT')
            self._drop(victim)
        try:row['file']=tempfile.TemporaryFile(mode='w+b')
        except OSError:
            with self.lock:self.rows.pop(key,None);self.fault='GG_LAN_GET_SPOOL_UNAVAILABLE'
            raise ValueError('GG_LAN_GET_SPOOL_UNAVAILABLE') from None
        return row

    def status(self):
        with self.lock:
            return {'scope':'UNTRUSTED_AUTHENTICATED_GET_PREFIXES_NOT_HISTORY','partial_records':len(self.rows),
                'downloaded_bytes':sum(row['offset'] for row in self.rows.values()),
                'reserved_disk_bytes':sum(row['meta']['size'] for row in self.rows.values()),
                'record_limit':MAX_RECORDS,'disk_byte_limit':MAX_BYTES,'peer_record_limit':PEER_RECORDS,'active_requests':self.sessions,
                'peer_disk_byte_limit':PEER_BYTES,'idle_seconds':IDLE_SECONDS,'local_fault':self.fault,'hint_fallback_peers':len(self.hint_fallback),
                'closing_files':sum(bool(row.get('closing')) for row in self.rows.values()),
                'failed_cleanup_files':sum(bool(row.get('close_failed')) for row in self.rows.values()),
                'state':'STOPPED' if self.closed else 'LOCAL_IO_FAULT' if self.blocked else 'ACTIVE'}

    def suppress_hints(self,peer):
        # A cost-only next-request fallback after an authenticated connection
        # closes before any response to a hinted GET. Never bypass validation.
        with self.lock:
            if peer in self.gates:self.hint_fallback.add(peer)

    def close(self):
        with self.lock:
            if self.sessions or any(row['active'] or row.get('closing') for row in self.rows.values()):raise ValueError('GG_LAN_GET_RESUME_BUSY')
            self.closed=True;keys=list(self.rows)
        error=None
        for key in keys:
            try:self._drop(key)
            except ValueError as failure:error=failure
        if error is not None:raise error


class GetResumeSession:
    def __init__(self,cache,gate,peer,network,hashes,maximum):
        self.cache=cache;self.gate=gate;self.peer=peer;self.network=network;self.hashes=set(hashes)
        self.maximum=maximum;self.current=None;self.closed=False;self.claimed=set()
        with cache.lock:
            if cache.closed:raise ValueError('GG_LAN_GET_RESUME_STOPPED')
            cache.sessions+=1
            for key,row in cache.rows.items():
                if key[:2]==(network,peer) and key[2] in self.hashes:
                    row['active']=True;self.claimed.add(key)

    def _key(self,identifier):return self.network,self.peer,identifier

    def hints(self):
        with self.cache.lock:
            if self.peer in self.cache.hint_fallback:return []
            return [{'hash':key[2],'size':row['meta']['size'],'wire_sha256':row['meta']['wire_sha256'],'offset':row['offset']}
                for key,row in self.cache.rows.items() if key in self.claimed and row['offset']>0]

    @property
    def offset(self):return self.current[1]['offset'] if self.current is not None else 0

    def start(self,meta,offset):
        identifier=meta['hash'];key=self._key(identifier)
        if self.closed or identifier not in self.hashes or self.current is not None:raise ValueError('GG_LAN_CHUNK_RESUME')
        with self.cache.lock:row=self.cache.rows.get(key)
        if offset:
            if row is None or row['meta']!=meta or row['offset']!=offset:raise ValueError('GG_LAN_CHUNK_RESUME')
        else:
            if row is not None:self.cache._drop(key)
            row=self.cache._new(key,meta)
        self.claimed.add(key);self.current=key,row

    def append(self,raw):
        if self.current is None:raise ValueError('GG_LAN_CHUNK_PART')
        row=self.current[1]
        try:
            row['file'].seek(row['offset'])
            if row['file'].write(raw)!=len(raw):raise OSError()
        except OSError:
            with self.cache.lock:self.cache.fault='GG_LAN_GET_SPOOL_WRITE'
            raise ValueError('GG_LAN_GET_SPOOL_WRITE') from None
        with self.cache.lock:row['offset']+=len(raw);row['touched']=time.monotonic()

    def finish(self):
        if self.current is None:raise ValueError('GG_LAN_CHUNK_END')
        row=self.current[1];meta=row['meta']
        try:
            row['file'].seek(0);raw=row['file'].read(meta['size']+1)
        except OSError:
            with self.cache.lock:self.cache.fault='GG_LAN_GET_SPOOL_READ'
            raise ValueError('GG_LAN_GET_SPOOL_READ') from None
        if len(raw)!=meta['size'] or hashlib.sha256(raw).hexdigest()!=meta['wire_sha256']:
            raise ValueError('GG_LAN_CHUNK_HASH')
        self.current=None
        return raw

    def discard_current(self):
        if self.current is None:return
        key=self.current[0];self.current=None;self.cache._drop(key)

    def admitted(self,identifier):
        with self.cache.lock:existed=self._key(identifier) in self.cache.rows
        self.cache._drop(self._key(identifier))
        with self.cache.lock:
            if existed and not self.cache.blocked:self.cache.fault=''

    def discard(self,identifier):self.cache._drop(self._key(identifier))

    def close(self):
        if self.closed:return
        self.closed=True
        with self.cache.lock:
            self.cache.sessions-=1
            for key in self.claimed:
                row=self.cache.rows.get(key)
                if row is not None:row['active']=False;row['touched']=time.monotonic()
        self.current=None;self.gate.release()
