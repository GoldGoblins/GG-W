"""Resumable SDK payload recovery; bounded untrusted spools are never history.

Only verified complete order authorizes reads. Wire/body hashes, every signature,
TX/parent/nonce/balance rule and durable admission still precede publication.
Network work slices and governed cancellable validation are separate stages.
"""
from collections import OrderedDict
import hashlib
import http.client
import json
import re
import tempfile
import threading
import time

HASH=re.compile(r'[0-9a-f]{64}')
MAX_BYTES=32*1024*1024
CHUNK_BYTES=32*1024
JOB_SECONDS=8
PARTIAL_RECORDS=8
PARTIAL_BYTES=64*1024*1024
PARTIAL_IDLE_SECONDS=30
FAILURES=(ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException)


class PayloadRecovery:
    def __init__(self,exchange):
        self.exchange=exchange;self.peer=exchange.peer;self.cancel=threading.Event();self.lock=threading.Lock()
        self.lanes=OrderedDict();self.active=None;self.blocks=0;self.bytes=0;self.error='';self.turn=0
        self.partials=OrderedDict();self.partial_bytes=0;self.failed=OrderedDict();self.phase='IDLE';self.local_fault=''
        self.worker=threading.Thread(target=self._work,name='GG-SDK-payload-recovery',daemon=True);self.worker.start()

    def request(self,actor,hashes):
        if self.cancel.is_set() or self.peer._cancel.is_set() or self.exchange._fault:return
        if actor not in self.peer._roster or not isinstance(hashes,list) or not 1<=len(hashes)<=8:return
        if any(not isinstance(value,str) or not HASH.fullmatch(value) for value in hashes):return
        hashes=[identifier for identifier in hashes if not self.peer._engine.has_proposal(identifier)]
        with self.lock:
            lane=self.lanes.setdefault(actor,OrderedDict())
            for identifier in hashes:
                if identifier!=self.active and len(lane)<8:lane[identifier]=None

    def _next(self):
        with self.lock:
            actors=list(self.lanes)
            for step in range(len(actors)):
                index=(self.turn+step)%len(actors);lane=self.lanes[actors[index]]
                if lane:
                    identifier=lane.popitem(last=False)[0];self.turn=(index+1)%len(actors);self.active=identifier
                    return actors[index],identifier
            return None

    def _cancel_check(self):
        if self.cancel.is_set() or self.peer._cancel.is_set() or self.exchange._fault:raise ValueError('GG_PAYLOAD_RECOVERY_STOPPED')

    def _check(self,deadline):
        self._cancel_check()
        if deadline is not None and time.monotonic()>=deadline:raise ValueError('GG_PAYLOAD_RECOVERY_DEADLINE')
        self.peer._resource_check(deadline,check=self._cancel_check)

    def _error(self,error):
        code=str(error)
        with self.lock:
            if not self.local_fault:self.error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_PAYLOAD_SOURCE_UNAVAILABLE'

    def _drop(self,identifier):
        with self.lock:
            partial=self.partials.get(identifier)
            if partial is None or partial.get('closing'):return
            partial['closing']=True
        if partial is not None:
            try:partial['file'].close()
            except OSError:
                with self.lock:self.local_fault=self.error='GG_PAYLOAD_SPOOL_CLOSE_FAILED'
                self.cancel.set()
                if getattr(partial['file'],'closed',False) is not True:
                    try:partial['file'].close()
                    except OSError:
                        if getattr(partial['file'],'closed',False) is not True:
                            with self.lock:partial['closing']=False
                            return
            # A zero-row snapshot/reusable credit requires confirmed close.
            with self.lock:
                if self.partials.get(identifier) is partial:
                    self.partials.pop(identifier);self.partial_bytes-=partial['total']

    def _failed(self,identifier,node):
        with self.lock:
            self.failed[identifier]=node;self.failed.move_to_end(identifier)
            while len(self.failed)>PARTIAL_RECORDS:self.failed.popitem(last=False)

    def _expire(self,allowed=None,binding=None):
        now=time.monotonic()
        with self.lock:
            stale=[identifier for identifier,partial in self.partials.items()
                if now-partial['touched']>=PARTIAL_IDLE_SECONDS
                or allowed is not None and (partial['binding']!=binding
                    or partial['index']<=len(allowed) and (identifier,partial['index']) not in allowed)]
            identifiers=list(self.partials)
        stale.extend(identifier for identifier in identifiers if self.peer._engine.has_proposal(identifier))
        for identifier in set(stale):self._drop(identifier)

    def _new_partial(self,leaf,binding,total,wire_hash,node):
        with self.lock:
            if len(self.partials)>=PARTIAL_RECORDS or self.partial_bytes+total>PARTIAL_BYTES:return None
        # TemporaryFile is owned, private, deleted on close and never journaled.
        # Reserve the declared disk credit before accepting more chunks. Large
        # untrusted records do not occupy unaccounted live bytearrays between jobs.
        try:spool=tempfile.TemporaryFile(mode='w+b')
        except OSError:raise ValueError('GG_PAYLOAD_SPOOL_UNAVAILABLE') from None
        partial={'file':spool,'binding':binding,'index':leaf['index'],'total':total,'wire_hash':wire_hash,
            'offset':0,'touched':time.monotonic(),'source':node}
        with self.lock:self.partials[leaf['hash']]=partial;self.partial_bytes+=total
        return partial

    def _finish(self,leaf,partial):
        with self.lock:self.phase='VALIDATING'
        self._check(None)
        # Re-read and hash the bytes actually stored, not an incremental digest
        # of earlier network buffers. Changed/truncated spool data cannot pass.
        total=partial['total']
        try:
            with self.peer.resources.governor().reserve_memory(total):
                try:
                    partial['file'].seek(0);wire=partial['file'].read(total+1)
                except OSError:raise ValueError('GG_PAYLOAD_SPOOL_READ') from None
                if len(wire)!=total or hashlib.sha256(wire).hexdigest()!=partial['wire_hash']:raise ValueError('GG_PAYLOAD_WIRE_DIGEST')
                self._check(None)
                # Finite input limits still bound work. Full validation has its own
                # CPU/memory governor and cancellation checks; a nearly exhausted
                # network time slice must not discard valid completed downloads.
                result=self.peer._ingest_sdk_payload(wire,leaf['hash'],deadline=None,check=self._cancel_check)
        except FAILURES as error:
            if not str(error).startswith('GG_DAG_RESOURCE_') and str(error)!='GG_PAYLOAD_RECOVERY_STOPPED':self._drop(leaf['hash'])
            raise
        self._drop(leaf['hash'])
        with self.lock:
            if not self.local_fault:self.error=''
            if result=='ADMITTED_UNFINALIZED':self.blocks+=1;self.bytes+=total
        return total

    def _materialize(self,packet,leaf,sources,deadline,remaining,binding):
        with self.lock:self.phase='DOWNLOADING'
        identifier=leaf['hash'];partial=self.partials.get(identifier)
        if partial is not None and (partial['binding']!=binding or partial['index']!=leaf['index']):
            self._drop(identifier);partial=None
        if partial is not None and partial['offset']==partial['total']:
            if partial['total']>remaining:return 0
            try:return self._finish(leaf,partial)
            except FAILURES as error:
                self._error(error)
                if leaf['hash'] not in self.partials and not str(error).startswith('GG_PAYLOAD_SPOOL_'):self._failed(identifier,partial['source'])
                return 0
        preferred=partial['source'] if partial is not None else None;failed=self.failed.get(identifier)
        sources=sorted(sources,key=lambda node:(node is failed,node is not preferred))
        received=0
        for node in sources:
            try:
                self._check(deadline)
                with node.payload_reader(packet) as (epoch,read):
                    # The fresh next-offset response carries the same descriptor;
                    # no extra offset-zero read is needed just to resume a slice.
                    offset=partial['offset'] if partial is not None else 0
                    chunk=read(identifier,leaf['index'],offset)
                    total=chunk['total'];wire_hash=chunk['wire_hash']
                    if type(total) is not int or not 0<total<=min(self.peer._wire_limit,MAX_BYTES):raise ValueError('GG_PAYLOAD_EXCEEDS_LOCAL_LIMIT')
                    if not isinstance(wire_hash,str) or not HASH.fullmatch(wire_hash):raise ValueError('GG_PAYLOAD_CHUNK_CHANGED')
                    if partial is not None and (total!=partial['total'] or wire_hash!=partial['wire_hash']):raise ValueError('GG_PAYLOAD_CHUNK_CHANGED')
                    if partial is None:
                        if total>remaining:return received
                        partial=self._new_partial(leaf,binding,total,wire_hash,node)
                        if partial is None:return received
                    while partial['offset']<total:
                        self._cancel_check()
                        offset=partial['offset']
                        if chunk['offset']!=offset or chunk['total']!=total or chunk['wire_hash']!=wire_hash:raise ValueError('GG_PAYLOAD_CHUNK_CHANGED')
                        part=chunk['data']
                        if not isinstance(part,bytes) or len(part)!=min(CHUNK_BYTES,total-offset):raise ValueError('GG_PAYLOAD_CHUNK_SIZE')
                        if received+len(part)>remaining:return received
                        try:written=partial['file'].write(part)
                        except OSError:raise ValueError('GG_PAYLOAD_SPOOL_WRITE') from None
                        if written!=len(part):raise ValueError('GG_PAYLOAD_SPOOL_WRITE')
                        with self.lock:
                            partial['offset']+=len(part);partial['touched']=time.monotonic();partial['source']=node
                        received+=len(part)
                        if partial['offset']==total:break
                        if time.monotonic()>=deadline:return received
                        self._check(deadline);chunk=read(identifier,leaf['index'],partial['offset'])
                    node._check_proof_epoch(epoch)
                if time.monotonic()>=deadline or total>remaining:return received
                return self._finish(leaf,partial)
            except FAILURES as error:
                code=str(error)
                if code in ('GG_PAYLOAD_RECOVERY_DEADLINE','GG_DAG_RESOURCE_DEADLINE'):return received
                if code in ('GG_PAYLOAD_CHUNK_CHANGED','GG_PAYLOAD_CHUNK_SIZE','GG_PAYLOAD_WIRE_DIGEST','GG_PAYLOAD_SPOOL_WRITE'):
                    self._drop(identifier);partial=None
                    if code!='GG_PAYLOAD_SPOOL_WRITE':self._failed(identifier,node)
                # Publish a terminal bad-chunk error after confirmed cleanup.
                # Slow close stays outside the status lock; its credit remains
                # reserved until _drop has actually closed the owned spool.
                self._error(error)
                if code=='GG_PAYLOAD_RECOVERY_STOPPED':raise
        return received

    def _recover(self,identifier):
        with self.lock:self.phase='VERIFYING_REFERENCE'
        deadline=time.monotonic()+JOB_SECONDS;sources=tuple(self.exchange.sources());reference=None
        for node in sources:
            reference=node.payload_reference(identifier)
            if reference is not None:break
        if reference is None:return False
        packet=reference['certificate'];order=reference['order']
        if (not isinstance(order,list) or type(reference['index']) is not int or not 1<=reference['index']<=len(order)
                or order[reference['index']-1].get('hash')!=identifier):raise ValueError('GG_PAYLOAD_REFERENCE')
        self.exchange.verifier.verify(packet);self.exchange._remember(packet)
        self.peer._engine.authorize_certified_payloads(packet['state'],order,self.exchange.anchor['genesis']['dag'])
        binding=hashlib.sha256(json.dumps(self.exchange.anchor,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self._expire({(leaf['hash'],leaf['index']) for leaf in order},binding)
        missing=[leaf for leaf in order[:reference['index']] if not self.peer._engine.has_proposal(leaf['hash'])][:8]
        total=0;progress=False
        with self.peer.resources.governor().reserve_memory(2*1024*1024):
            for leaf in missing:
                if time.monotonic()>=deadline:break
                size=self._materialize(packet,leaf,sources,deadline,MAX_BYTES-total,binding)
                if not size:break
                total+=size
                partial=self.partials.get(leaf['hash'])
                progress=progress or self.peer._engine.has_proposal(leaf['hash']) or partial is not None and partial['offset']>0
                if not self.peer._engine.has_proposal(leaf['hash']):break
        return progress

    def _work(self):
        try:
            while not self.cancel.is_set() and not self.peer._cancel.is_set() and not self.exchange._fault:
                if self.peer._resources_paused():self.cancel.wait(.2);continue
                self._expire()
                if self.cancel.is_set():break
                task=self._next()
                if task is None:self.cancel.wait(.05);continue
                actor,identifier=task;progress=False
                try:
                    if not self.peer._engine.has_proposal(identifier):progress=self._recover(identifier)
                except FAILURES as error:self._error(error)
                finally:
                    with self.lock:self.active=None;self.phase='IDLE'
                if progress and not self.peer._engine.has_proposal(identifier):self.request(actor,[identifier])
        finally:
            for identifier in list(self.partials):self._drop(identifier)
            with self.lock:self.failed.clear()

    def snapshot(self):
        with self.lock:return {'enabled':True,'state':'FAULT' if self.exchange._fault or self.local_fault else 'STOPPED' if self.cancel.is_set() else 'RECOVERING' if self.active else 'IDLE',
            'pending':sum(len(lane) for lane in self.lanes.values()),'recovered_blocks':self.blocks,'recovered_bytes':self.bytes,
            'last_error':self.error,'scope':'OWNED_SDK_COMMITTED_PAYLOAD_FULL_LOCAL_VALIDATION','max_pending_per_actor':8,
            'max_records_per_job':8,'max_bytes_per_job':MAX_BYTES,'network_slice_seconds':JOB_SECONDS,'phase':self.phase,
            'partial_records':len(self.partials),'partial_downloaded_bytes':sum(row['offset'] for row in self.partials.values()),
            'partial_reserved_bytes':self.partial_bytes,'max_partial_records':PARTIAL_RECORDS,'max_partial_bytes':PARTIAL_BYTES}

    def request_stop(self):self.cancel.set()

    def close(self):
        self.request_stop()
        if self.worker is threading.current_thread():return
        self.worker.join(10)
        if self.worker.is_alive():raise ValueError('GG_PAYLOAD_WORKER_STOP_TIMEOUT')
        for identifier in list(self.partials):self._drop(identifier)
        with self.lock:
            if self.partials:raise ValueError('GG_PAYLOAD_SPOOL_CLOSE_FAILED')
