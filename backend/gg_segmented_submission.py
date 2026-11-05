"""Bounded signed LAN submission of original protected producer proposals.

QUEUED is an ephemeral transport receipt. Only a later verified SDK state can
retire the sender's durable original. TCP handlers never call SDK RPC or sign.
"""
from collections import OrderedDict
import hashlib
import http.client
import math
import re
import threading
import time

from backend.gg_dag_wire import RecordAssembler,record_frames,CHUNK_BYTES
from backend.gg_segmented_authority import OwnedSegmentedAuthority
from backend import gg_dag_execution_policy as execution_rules
from backend import gg_lossless_wire as lossless

MAX_RAW=execution_rules.MAX_CHECKPOINT_RAW_BYTES
MAX_QUEUE_BYTES=2*MAX_RAW
HASH=re.compile(r'[0-9a-f]{64}')
ACK='SEGMENTED_SUBMIT_ACK'


def validate_request(value):
    if (not isinstance(value,dict) or set(value)!={'hash','size'} or type(value['hash']) is not str
            or not HASH.fullmatch(value['hash']) or type(value['size']) is not int or not 0<value['size']<=MAX_RAW):
        raise ValueError('GG_SDK_SUBMISSION_REQUEST')
    return value


class SegmentedSubmissions:
    operation='SEGMENTED_SUBMIT'
    acknowledgement=ACK
    max_raw=MAX_RAW
    max_queue_bytes=MAX_QUEUE_BYTES
    max_actors=2

    def __init__(self,peer,sources):
        self.peer=peer;self.sources=sources;self.cancel=threading.Event();self.lock=threading.RLock()
        self.queue=OrderedDict();self.actors=set();self.bytes=0;self.results=OrderedDict();self.last_error=''
        self.receiving=set();self.receiving_bytes=0
        self.worker=threading.Thread(target=self._run,name='GG-segmented-submission-worker',daemon=True)

    def start(self):
        with self.lock:
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self.worker.ident is None:self.worker.start()

    def _sources(self):
        return tuple(node for node in self.sources() if isinstance(node,OwnedSegmentedAuthority) and node._alive() and not node._fault and not node._owner_stopped())

    @staticmethod
    def _receipt(state,identifier):return {'state':state,'hash':identifier,'SDK_selected':False}

    def _submit(self,node,actor,raw):return node.submit_proposals([raw])

    def _authorize(self,actor):
        if actor not in self.peer._roster or self.peer._roster[actor].get('node_role','producer')!='producer':raise ValueError('GG_SDK_SUBMISSION_OWNER')

    def enqueue(self,actor,raw,identifier,lease):
        """Adopt a reservation only on QUEUED; caller releases otherwise."""
        if not isinstance(raw,bytes) or not 0<len(raw)<=self.max_raw or hashlib.sha256(raw).hexdigest()!=identifier:raise ValueError('GG_SDK_SUBMISSION_INTEGRITY')
        self._authorize(actor)
        with self.lock:
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self.peer._resources_paused():return self._receipt('BUSY',identifier)
            if not self._sources():return self._receipt('UNAVAILABLE',identifier)
            others=len(self.actors|self.receiving)-int(actor in self.receiving)
            reserved=self.bytes+self.receiving_bytes-(len(raw) if actor in self.receiving else 0)
            if actor in self.actors or others>=self.max_actors or reserved+len(raw)>self.max_queue_bytes:return self._receipt('BUSY',identifier)
            self.queue[actor]=(identifier,raw,lease);self.actors.add(actor);self.bytes+=len(raw)
            return self._receipt('QUEUED',identifier)

    def _run(self):
        while not self.cancel.is_set() and not self.peer._cancel.is_set():
            if self.peer._resources_paused():self.cancel.wait(.1);continue
            with self.lock:item=self.queue.popitem(last=False) if self.queue else None
            if item is None:self.cancel.wait(.05);continue
            actor,(identifier,raw,lease)=item
            try:
                sources=self._sources()
                if not sources:result=self._receipt('UNAVAILABLE',identifier)
                else:
                    # Native verifies every original, nonce, causal dependency
                    # and execution rule. No asserted peer verification flag.
                    result=self._submit(sources[0],actor,raw)
                with self.lock:
                    self.results[identifier]=result;self.results.move_to_end(identifier)
                    while len(self.results)>64:self.results.popitem(last=False)
            except Exception as error:
                code=str(error);self.last_error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code) else 'GG_SDK_SUBMISSION_UNAVAILABLE'
            finally:
                size=len(raw);raw=None;item=None
                with self.lock:self.actors.discard(actor);self.bytes-=size
                lease.__exit__(None,None,None)

    def receive(self,sock,actor,session,payload,*,codec=None,sequence_base=0):
        from backend.gg_lan_dag import MAX_FRAME,BULK_SECONDS,_send
        validate_request(payload);identifier=payload['hash'];size=payload['size'];deadline=time.monotonic()+BULK_SECONDS
        if size>self.max_raw:raise ValueError('GG_SDK_SUBMISSION_REQUEST')
        self._authorize(actor)
        with self.lock:
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            state='BUSY' if self.peer._resources_paused() else 'UNAVAILABLE' if not self._sources() else 'BUSY' if actor in self.actors|self.receiving or len(self.actors|self.receiving)>=self.max_actors or self.bytes+self.receiving_bytes+size>self.max_queue_bytes else 'READY_FOR_DATA'
            if state=='READY_FOR_DATA':self.receiving.add(actor);self.receiving_bytes+=size
        def check():
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            self.peer.resources.governor().check_cpu(deadline=deadline)
        lease=None;assembler=RecordAssembler(maximum=size,codec=codec,check=check,deadline=deadline,
                                             charge=lambda length:self.peer._account_codec_raw(actor,length),
                                             workspace=lambda:self.peer.resources.governor().reserve_memory(lossless.WORKSPACE_BYTES))
        try:
            if state=='READY_FOR_DATA':
                reservation=self.peer.resources.governor().reserve_memory(size*16);reservation.__enter__();lease=reservation
            self.peer._credit('out:'+actor,_send(sock,self.peer._frame(session,sequence_base,self.acknowledgement,self._receipt(state,identifier)),MAX_FRAME,deadline=deadline))
            if state!='READY_FOR_DATA':return
            record=None
            for sequence in range(sequence_base+1,sequence_base+(size+CHUNK_BYTES-1)//CHUNK_BYTES+5):
                value,wire_size=self.peer._read(sock,MAX_FRAME,deadline=deadline,bulk=True,check=check)
                body=self.peer._check_frame(value,wire_size,actor,session,sequence)
                if body['kind']=='END':
                    if body['payload']!={'records':1} or assembler.pending or record is None:raise ValueError('GG_SDK_SUBMISSION_INCOMPLETE')
                    raw=record['wire']
                    if record['admission_index']!=0 or record['hash']!=identifier or len(raw)!=size or hashlib.sha256(raw).hexdigest()!=identifier:
                        raise ValueError('GG_SDK_SUBMISSION_INTEGRITY')
                    result=self.enqueue(actor,raw,identifier,lease)
                    if result['state']=='QUEUED':lease=None
                    self.peer._credit('out:'+actor,_send(sock,self.peer._frame(session,sequence_base+1,self.acknowledgement,result),MAX_FRAME,deadline=deadline))
                    self.peer._mark_seen(actor);return
                completed=assembler.feed(body['kind'],body['payload'])
                if completed is not None:
                    if record is not None:raise ValueError('GG_SDK_SUBMISSION_RECORDS')
                    record=completed;completed=None
            raise ValueError('GG_SDK_SUBMISSION_FRAME_LIMIT')
        finally:
            assembler.close()
            if state=='READY_FOR_DATA':
                with self.lock:self.receiving.discard(actor);self.receiving_bytes-=size
            if lease is not None:lease.__exit__(None,None,None)

    def local(self,raw):
        if not isinstance(raw,bytes) or not 0<len(raw)<=self.max_raw:raise ValueError('GG_SDK_BATCH_LIMIT')
        reservation=self.peer.resources.governor().reserve_memory(len(raw)*16);reservation.__enter__();adopted=False
        try:
            result=self.enqueue(self.peer.public_key,raw,hashlib.sha256(raw).hexdigest(),reservation)
            adopted=result['state']=='QUEUED';return result
        finally:
            if not adopted:reservation.__exit__(None,None,None)

    def send(self,owner,raw,*,cancel=None,deadline=None):
        from backend.gg_lan_dag import MAX_FRAME,BULK_SECONDS,CONNECTION_SECONDS,_send,pack
        if not isinstance(raw,bytes) or not 0<len(raw)<=self.max_raw:raise ValueError('GG_SDK_BATCH_LIMIT')
        if deadline is not None and (type(deadline) not in (int,float) or not math.isfinite(deadline)):raise ValueError('GG_SDK_SUBMISSION_DEADLINE')
        deadline=min(deadline,time.monotonic()+BULK_SECONDS) if deadline is not None else time.monotonic()+BULK_SECONDS
        identifier=hashlib.sha256(raw).hexdigest();lifetime=self.cancel
        class Cancellation:
            def is_set(self):return lifetime.is_set() or cancel is not None and cancel.is_set()
            def wait(self,timeout):
                until=time.monotonic()+max(0,timeout)
                while not self.is_set():
                    remaining=until-time.monotonic()
                    if remaining<=0:return False
                    lifetime.wait(min(.05,remaining))
                return True
        token=Cancellation()
        def check():
            if token.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if time.monotonic()>=deadline:raise ValueError('GG_SDK_SUBMISSION_DEADLINE')
            self.peer.resources.governor().check_cpu(deadline=deadline)
        check();self.peer._pace_connection(owner,'INCOMING',cancel=token,deadline=deadline)
        def ack(sock,session,sequence,*,initial=False):
            value,size=self.peer._read(sock,MAX_FRAME,deadline=deadline,check=check,bulk=True)
            body=self.peer._check_frame(value,size,owner,session,sequence);result=body['payload']
            if (body['kind']!=self.acknowledgement or not isinstance(result,dict) or set(result)!={'state','hash','SDK_selected'}
                    or result['hash']!=identifier or result['SDK_selected'] is not False
                    or result['state'] not in (('READY_FOR_DATA','BUSY','UNAVAILABLE') if initial else ('QUEUED','BUSY','UNAVAILABLE'))):raise ValueError('GG_SDK_SUBMISSION_ACK')
            return result
        with lossless.lan_connection(self.peer,owner,deadline,cancel=token,bulk=True,check=check,
                enabled=len(raw)>44*1024 and getattr(self.peer,'_lossless_wire',True)) as (sock,session,codec,sequence_base):
            self.peer._credit('out:'+owner,_send(sock,self.peer._frame(session,sequence_base,self.operation,{'hash':identifier,'size':len(raw)}),MAX_FRAME,deadline=deadline))
            result=ack(sock,session,sequence_base,initial=True)
            if result['state']!='READY_FOR_DATA':return result
            next_send=time.monotonic();sequence=sequence_base+1
            for kind,payload in record_frames({'hash':identifier,'admission_index':0,'wire':raw},maximum=self.max_raw,
                    codec=codec,check=check,deadline=deadline,charge=lambda size:self.peer._account_codec_raw('out:'+owner,size),
                    workspace=lambda:self.peer.resources.governor().reserve_memory(lossless.WORKSPACE_BYTES)):
                check();value=self.peer._frame(session,sequence,kind,payload);size=len(pack(value))+4
                cost=size+(payload['raw_size'] if codec is not None and kind=='DATA_PART' else 0)
                # Keep encoded application traffic below the existing 8 MiB/s
                # per-source credits. The user's lower governor still applies.
                self.peer.resources.governor().wait_network(cost,deadline=deadline)
                while time.monotonic()<next_send:
                    check();self.cancel.wait(min(.05,next_send-time.monotonic()))
                self.peer._credit('out:'+owner,_send(sock,value,MAX_FRAME,deadline=deadline,frame_seconds=BULK_SECONDS))
                next_send=max(next_send,time.monotonic())+cost/(4*1024*1024);sequence+=1
            self.peer._credit('out:'+owner,_send(sock,self.peer._frame(session,sequence,'END',{'records':1}),MAX_FRAME,deadline=deadline))
            result=ack(sock,session,sequence_base+1)
            if result['state']=='READY_FOR_DATA':raise ValueError('GG_SDK_SUBMISSION_ACK')
            self.peer._mark_seen(owner);return result

    def request_stop(self):
        self.cancel.set()
        with self.lock:
            pending=list(self.queue.items());self.queue.clear()
            for actor,(_,raw,_) in pending:self.actors.discard(actor);self.bytes-=len(raw)
        for _,(_,_,lease) in pending:lease.__exit__(None,None,None)

    def snapshot(self):
        with self.lock:
            return {'state':'STOPPED' if self.cancel.is_set() else 'RUNNING' if self.worker.is_alive() else 'STOPPED',
                'queued_or_working':len(self.actors),'retained_raw_bytes':self.bytes,'receiving':len(self.receiving),
                'receiving_raw_bytes':self.receiving_bytes,'raw_limit':self.max_raw,'queue_byte_limit':self.max_queue_bytes,
                'SDK_selection_asserted':False,'resource_paused':self.peer._resources_paused(),'last_error':self.last_error}

    def close(self):
        self.request_stop()
        if self.worker.ident is not None and self.worker is not threading.current_thread():self.worker.join(25)
        if self.worker.is_alive() and self.worker is not threading.current_thread():raise ValueError('GG_SDK_SUBMISSION_STOP_TIMEOUT')
