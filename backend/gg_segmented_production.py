"""One explicit bounded producer job using the real protected own journal.

Local measurements never count queue receipts as SDK selection. Observation,
other owners and validators keep their own lifetimes when this job pauses.
"""
from copy import deepcopy
import http.client
import re
import threading
import time

from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_dag_producer_journal import OwnedSegmentedProducer
from backend.gg_segmented_submission import MAX_RAW

MAX_PENDING=16


class SegmentedProduction:
    def __init__(self,exchange):
        self.exchange=exchange;self.peer=exchange.peer;self.control=threading.RLock()
        self.cancel=threading.Event();self.worker=None;self.closed=False
        self.state={'state':'IDLE','duration_ms':0,'transactions_per_block':0,'interval_ms':1000,'elapsed_ms':0,
            'production':None,'last_error':'','stop_reason':'','last_stored_pending_count':None,'SDK_selection_asserted':False}

    def _packet(self):
        packet=self.exchange._producer_packet
        if packet is None:raise ValueError('GG_PRODUCER_VERIFIED_BASE_REQUIRED')
        # A previously verified journal floor may be newer than a reused sparse
        # view. Keep that original packet; never replace its proof/header.
        stored=self.peer._profile._meta.get('segmented_producer')
        if stored is not None and certificate_tip({key:packet[key] for key in ('schema','genesis','genesis_hash','state','signed_header')},self.exchange.anchor)[0]<stored['floor'][0]:
            packet=stored['packet']
        return deepcopy(packet)

    def start(self,duration_ms,transactions_per_block,interval_ms):
        from backend.gg_lan_dag import _integer,DAG_STRESS_MAX_TX
        if self.peer.node_role!='producer':raise ValueError('GG_LAN_REPLICA_READ_ONLY')
        _integer(duration_ms,1000,600000);_integer(transactions_per_block,1,DAG_STRESS_MAX_TX);_integer(interval_ms,0,60000)
        with self.control:
            if self.closed or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self.worker is not None and self.worker.is_alive():raise ValueError('GG_LAN_DAG_PRODUCTION_BUSY')
            if self.exchange._fault:raise ValueError(self.exchange._fault)
            if self.peer._resources_paused():raise ValueError('GG_DAG_RESOURCE_PAUSED')
            self.exchange.context.check();self._packet();self.cancel=threading.Event()
            self.state={**self.state,'state':'STARTING','duration_ms':duration_ms,'transactions_per_block':transactions_per_block,
                'interval_ms':interval_ms,'elapsed_ms':0,'production':None,'last_error':'','stop_reason':''}
            self.worker=threading.Thread(target=self._run,args=(self.cancel,duration_ms,transactions_per_block,interval_ms),name='GG-segmented-owned-producer',daemon=True)
            self.worker.start();return self.snapshot()

    def _run(self,cancel,duration_ms,count,interval_ms):
        started=time.monotonic();deadline=started+duration_ms/1000;writer=None;blocks=0;transactions=0;turn=0;last_attempt=None;next_produce=started
        status='COMPLETE';error='';reason='DURATION';pending_count=None
        def check():
            if cancel.is_set() or self.peer._cancel.is_set() or self.closed:raise ValueError('GG_LAN_NODE_CANCELLED')
            if time.monotonic()>=deadline:raise ValueError('GG_LAN_NODE_DEADLINE')
            self.exchange.context.check()
        def publish(state):
            elapsed=(time.monotonic()-started)*1000
            self.state={**self.state,'state':state,'elapsed_ms':elapsed,'last_stored_pending_count':pending_count,
                'production':{'basis':'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY','state':state,'blocks':blocks,'transactions':transactions,
                    'elapsed_ms':elapsed,'bps':blocks*1000/elapsed if elapsed else 0,'tps':transactions*1000/elapsed if elapsed else 0,
                    'SDK_selection_asserted':False}}
        try:
            check();packet=self._packet();writer=OwnedSegmentedProducer.open(self.peer._profile,self.peer._bundle,packet,
                binary=self.exchange.verifier.binary,stamp=self.exchange.verifier.stamp,hot_bytes=0,check=check)
            seen=tuple(writer._state()['floor']);estimate=writer._engine.preflight_lan_test_block(count,MAX_RAW)
            owners=sorted({row['body']['owner_peer_key'] for row in self.exchange.anchor['genesis']['membership']['validators']})
            while True:
                check();self.peer._resource_check(deadline=deadline,check=check)
                packet=self._packet();tip=certificate_tip({key:packet[key] for key in ('schema','genesis','genesis_hash','state','signed_header')},self.exchange.anchor)
                if tip!=seen:writer.observe(packet,check=check);seen=tip
                pending=writer.pending();pending_count=len(pending)
                if pending:
                    item=pending[0];context=packet['state']['dag_segmented']['active']['manifest_hash'];attempt=(item['hash'],context)
                    if last_attempt is None or last_attempt[:2]!=attempt or time.monotonic()-last_attempt[2]>=2:
                        raw=writer.read_proposal(item['hash'])
                        if len(raw)>MAX_RAW:raise ValueError('GG_SDK_BATCH_LIMIT')
                        try:
                            if self.exchange.submissions._sources():self.exchange.submissions.local(raw)
                            else:
                                remote=[owner for owner in owners if owner!=self.peer.public_key]
                                if remote:
                                    owner=remote[turn%len(remote)];turn+=1
                                    self.exchange.submissions.send(owner,raw,cancel=cancel,deadline=deadline)
                        except (ValueError,OSError,http.client.HTTPException) as failure:
                            check()
                            code=str(failure)
                            if code in ('GG_SDK_OWNER_CLOSED','GG_SDK_SESSION_CHANGED','GG_CONSENSUS_CONFLICTING_CERTIFICATE',
                                        'GG_CONSENSUS_BINARY_CHANGED','GG_VALIDATOR_LISTENER_NOT_OWNED'):raise
                        finally:last_attempt=(*attempt,time.monotonic());raw=None
                if pending_count<MAX_PENDING and time.monotonic()>=next_produce:
                    index=writer._indices[blocks%len(writer._indices)]
                    try:
                        with self.peer.resources.governor().reserve_memory(estimate*16):block=writer.produce(index,count,check=check,max_wire=MAX_RAW)
                    except ValueError as failure:
                        if str(failure)!='GG_PRODUCER_LATEST_BASE_REQUIRED':raise
                    else:
                        blocks+=1;transactions+=count;block=None;pending_count+=1;next_produce=time.monotonic()+interval_ms/1000
                publish('RUNNING');cancel.wait(.05)
        except (ValueError,OSError,RuntimeError,http.client.HTTPException) as failure:
            code=str(failure);pending_count=None
            if code=='GG_LAN_NODE_CANCELLED':status='STOPPED';reason='CANCELLED'
            elif code!='GG_LAN_NODE_DEADLINE':
                status='LIMIT_REACHED' if code in ('GG_DAG_LAN_WIRE_PROFILE_LIMIT','GG_PRODUCER_JOURNAL_CAPACITY','GG_DAG_RECORD_LIMIT','GG_DAG_STORAGE_LIMIT','GG_DAG_RESOURCE_MEMORY') else 'ERROR'
                error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code) else 'GG_LAN_NODE_PRODUCTION_FAILED';reason='FAILED'
        except Exception:
            status='ERROR';error='GG_LAN_NODE_PRODUCTION_FAILED';reason='FAILED';pending_count=None
        finally:
            if writer is not None:
                try:writer.close()
                except (ValueError,OSError,RuntimeError):status='ERROR';error='GG_PRODUCER_CLOSE_FAILED';reason='FAILED'
            publish(status);self.state={**self.state,'last_error':error,'stop_reason':reason}

    def snapshot(self):
        from backend.gg_lan_dag import dag_production_capabilities
        state=self.state;busy=self.worker is not None and self.worker.is_alive()
        enabled=self.peer.node_role=='producer' and not self.closed and not self.peer._cancel.is_set() and not self.exchange.context.stopped()
        return {**dag_production_capabilities(),**deepcopy(state),'enabled':enabled,'worker_active':busy,'worker_count':int(busy),'selected':True,
            'can_start':enabled and not busy and self.exchange._producer_packet is not None and not self.exchange._fault and not self.peer._resources_paused(),
            'counts_basis':'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY','pending_limit':MAX_PENDING,'pending_count_scope':'LAST_STORED_OWN_JOURNAL_NOT_NETWORK_SELECTION'}

    def request_stop(self):
        self.cancel.set()

    def stop(self):
        self.request_stop()
        worker=self.worker
        if worker is not None and worker is not threading.current_thread():worker.join(.25)
        return self.snapshot()

    def close(self):
        self.closed=True;self.request_stop();worker=self.worker
        if worker is not None and worker is not threading.current_thread():worker.join(10)
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():raise ValueError('GG_PRODUCER_STOP_TIMEOUT')
