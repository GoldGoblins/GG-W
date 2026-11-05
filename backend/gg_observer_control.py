"""Explicit observer ownership and bounded work shared by terminal/Desktop.

No profile, key, socket or thread is created on import or construction. Two
session-owned lanes separate native status from finite-deadline LAN enrollment.
They never create validators or retry economic transactions.
"""
from copy import deepcopy
from contextlib import contextmanager
import http.client
import socket
import threading
import time

from backend.gg_observer_profile import ObserverProfile,profile_path
from backend.gg_observer_node import OwnedObserver
from backend.gg_consensus_membership import anchor_from_bundle

MAX_LOCAL_OBSERVERS=2
ERRORS=(ValueError,OSError,KeyError,TypeError,AttributeError,RuntimeError,http.client.HTTPException)


def empty_snapshot():
    return {'schema':'gg.native.observer-controls.v1','profiles':[],'own_running':0,'own_connected':0,
        'validator_votes':0,'certificate_is_network_liveness':False}


def _code(error):
    value=str(error)
    return value if value.startswith('GG_') and len(value)<=96 else 'GG_OBSERVER_OPERATION_UNAVAILABLE'


class ObserverControl:
    def __init__(self,runtime):
        self.runtime=runtime;self.peer=runtime._owned();self.lock=threading.RLock();self.cancel=threading.Event()
        self.profiles={};self.nodes={};self.events={};self.busy=set();self.stopping=set();self.errors={}
        self.acks={};self.enrollment_errors={};self._due={};self._attempts={};self._reserved_slots={}
        self._status_thread=None;self._enroll_thread=None

    def _active(self):
        peer=self.peer
        if self.cancel.is_set() or self.runtime._stop_requested.is_set() or self.runtime._peer is not peer or peer._cancel.is_set():
            raise ValueError('GG_OBSERVER_OWNER_STOPPED')
        if peer._profile is None:raise ValueError('GG_OBSERVER_PERSISTENT_OWNER_REQUIRED')
        if peer.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        if peer._bundle is None:raise ValueError('GG_OBSERVER_ACTIVE_LAN_REQUIRED')
        return peer

    @contextmanager
    def _operation(self,name,*,new_run=False):
        profile_path(name);self._active()
        previous=None
        with self.lock:
            if name in self.busy or name in self.stopping:raise ValueError('GG_OBSERVER_OPERATION_BUSY')
            names=set(self.profiles)|self.busy
            if name not in names and len(names)>=MAX_LOCAL_OBSERVERS:raise ValueError('GG_OBSERVER_LOCAL_PROFILE_LIMIT')
            self.busy.add(name)
            node=self.nodes.get(name);existing=self.events.get(name)
            profile=self.profiles.get(name)
            unavailable=profile is not None and (profile._closed or profile._failed)
            if existing is None or new_run and (node is None or not node._alive() or existing.is_set() or unavailable):
                previous=existing;self.events[name]=threading.Event()
            event=self.events[name]
        try:
            if previous is not None:self.peer.cancel_operation(previous)
            yield event
        finally:
            with self.lock:
                self.busy.discard(name);self._reserved_slots.pop(name,None)
                if name not in self.profiles and name not in self.nodes:self.events.pop(name,None)
            self.runtime._revision+=1

    def _load(self,name,*,create=False,label=None,p2p_port=None,producer_slot=None,reopen=False):
        peer=self._active()
        with self.lock:cached=self.profiles.get(name);event=self.events[name]
        expected_grant=None;expected_anchor=None
        if cached is not None:
            if create:raise ValueError('GG_OBSERVER_PROFILE_EXISTS_USE_RESUME')
            if not cached._closed and not cached._failed:return cached
            if not reopen:raise ValueError('GG_OBSERVER_PROFILE_REOPEN_REQUIRED')
            expected_grant=cached.public_grant();expected_anchor=cached.anchor()
            with self.lock:previous_node=self.nodes.get(name)
            if previous_node is not None:previous_node.close()
            else:cached.close()
        if create:
            keys=peer._profile.descriptor()['public_keys'][1:]
            with self.lock:
                used={value.public_grant()['body']['producer_key'] for value in self.profiles.values()}
                reserved=set(self._reserved_slots.values())
                if producer_slot is None:
                    producer_slot=next((index for index,key in enumerate(keys) if key not in used and index not in reserved),None)
                if type(producer_slot) is not int or producer_slot not in range(len(keys)):
                    raise ValueError('GG_OBSERVER_PRODUCER_SLOT')
                if producer_slot in reserved or keys[producer_slot] in used:raise ValueError('GG_OBSERVER_PRODUCER_SLOT_IN_USE')
                self._reserved_slots[name]=producer_slot
            if p2p_port is None:
                with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as reserve:
                    reserve.bind((peer.host,0));p2p_port=reserve.getsockname()[1]
            profile=ObserverProfile.create_for_owned_profile(name,peer._profile,label=label or peer.label+' native observer',
                p2p_port=p2p_port,producer_slot=producer_slot)
        else:profile=ObserverProfile.open(name)
        try:
            if expected_grant is not None and (profile.public_grant()!=expected_grant or profile.anchor()!=expected_anchor):
                raise ValueError('GG_OBSERVER_REOPEN_IDENTITY_OR_ANCHOR_CHANGED')
            if (profile.anchor()!=anchor_from_bundle(peer._bundle,peer._trusted)
                    or profile.public_grant()['body']['owner_peer_key']!=peer.public_key):raise ValueError('GG_OBSERVER_PROFILE_NETWORK_OR_OWNER')
            self._active()
            if event.is_set():raise ValueError('GG_OBSERVER_STOPPED')
            with self.lock:
                grant=profile.public_grant()['body']
                if any(other!=name and (value.public_grant()['body']['producer_key']==grant['producer_key']
                        or value.public_grant()['body']['p2p_port']==grant['p2p_port']) for other,value in self.profiles.items()):
                    raise ValueError('GG_OBSERVER_LOCAL_IDENTITY_OR_ENDPOINT_IN_USE')
                self.profiles[name]=profile
                if cached is not None:self.nodes.pop(name,None)
            return profile
        except BaseException:profile.close();raise

    def open(self,name,*,create=False,label=None,p2p_port=None,producer_slot=None):
        with self._operation(name,new_run=not create):
            self._load(name,create=create,label=label,p2p_port=p2p_port,producer_slot=producer_slot,reopen=not create)
        return self.snapshot()

    def unlocked(self,name):
        with self.lock:profile=self.profiles.get(name)
        return profile is not None and profile.snapshot()['state'] not in ('CLOSED','FAULT')

    def _ensure_workers(self):
        with self.lock:
            for field,target,title in (('_status_thread',self._status_work,'GG-owned-observer-status'),
                    ('_enroll_thread',self._enroll_work,'GG-owned-observer-enrollment')):
                worker=getattr(self,field)
                if worker is None or not worker.is_alive():
                    worker=threading.Thread(target=target,name=title,daemon=True);setattr(self,field,worker);worker.start()

    def start(self,name):
        with self._operation(name,new_run=True) as event:
            profile=self._load(name)
            with self.lock:node=self.nodes.get(name)
            try:
                if node is None:
                    context=self.peer._proof_service.context if self.peer._bundle['body']['schema'] in ('gg.lan-dag.session.v5','gg.lan-dag.session.v6','gg.lan-dag.session.v7') else self.peer
                    node=OwnedObserver(profile,context)
                    with self.lock:self.nodes[name]=node
                self._ensure_workers()
                node.start(cancel=event);self._active()
                if event.is_set():raise ValueError('GG_OBSERVER_STOPPED')
                with self.lock:self.errors.pop(name,None)
            except BaseException as error:
                self.peer.cancel_operation(event)
                if node is not None:node.request_stop()
                with self.lock:self.errors[name]=_code(error)
                raise
        return self.snapshot()

    def stop(self,name):
        profile_path(name)
        with self.lock:
            if name not in self.profiles and name not in self.busy:raise ValueError('GG_OBSERVER_NOT_OPEN')
            event=self.events.get(name);node=self.nodes.get(name)
            if event is not None:event.set()
            if node is not None:self.stopping.add(name)
        if event is not None:self.peer.cancel_operation(event)
        if node is not None:node.request_stop();self._ensure_workers()
        self.runtime._revision+=1;return self.snapshot()

    def _items(self):
        with self.lock:return tuple((name,node,self.events[name],name in self.busy) for name,node in self.nodes.items())

    def _status_work(self):
        while not self.cancel.is_set():
            for name,node,event,busy in self._items():
                if self.cancel.is_set():return
                if busy:continue
                if event.is_set():
                    try:node.stop()
                    except ERRORS as error:
                        with self.lock:self.errors[name]=_code(error)
                    finally:
                        with self.lock:
                            if self.events.get(name) is event:self.stopping.discard(name)
                    continue
                if not node._alive():continue
                try:
                    status=node.refresh_status();height=status['native_connection']['latest_height']
                    if int(height)>0 and (node._tip is None or int(height)>node._tip[0] or node._view_epoch is not node._node):
                        node.certified_state()
                    with self.lock:
                        if self.events.get(name) is event:self.errors.pop(name,None)
                except ERRORS as error:
                    if event.is_set() or self.cancel.is_set():continue
                    code=_code(error)
                    if code=='GG_OBSERVER_NODE_IDENTITY_OR_VOTE':node.request_stop()
                    with self.lock:
                        if self.events.get(name) is event:self.errors[name]=code
                self.runtime._revision+=1
            self.cancel.wait(1)

    def _enroll_work(self):
        while not self.cancel.is_set():
            for name,node,event,_busy in self._items():
                if event.is_set() or self.cancel.is_set() or node._closed or node.profile._closed or node.profile._failed:continue
                owners=sorted({row['body']['owner_peer_key'] for row in node.anchor['genesis']['membership']['validators']})
                for owner in owners:
                    if event.is_set() or self.cancel.is_set():break
                    key=(name,owner)
                    with self.lock:
                        ack=self.acks.get(name,{}).get(owner)
                        if ack is not None and ack['state']=='READY':continue
                        if time.monotonic()<self._due.get(key,0):continue
                    try:
                        ack=self.peer.native_observer_admit(owner,node.profile.public_grant(),cancel=event)
                        with self.lock:
                            if self.events.get(name) is not event:continue
                            self.acks.setdefault(name,{})[owner]=ack;self.enrollment_errors.pop(name,None)
                            self._attempts[key]=0;self._due[key]=time.monotonic()+1
                    except ERRORS as error:
                        if event.is_set() or self.cancel.is_set():break
                        with self.lock:
                            attempts=min(4,self._attempts.get(key,0)+1);self._attempts[key]=attempts
                            self._due[key]=time.monotonic()+min(15,2**attempts);self.enrollment_errors[name]=_code(error)
                    self.runtime._revision+=1
            self.cancel.wait(.5)

    def snapshot(self):
        with self.lock:
            profiles=tuple(self.profiles.items());nodes=dict(self.nodes);busy=set(self.busy);stopping=set(self.stopping)
            errors=dict(self.errors);enrollment_errors=dict(self.enrollment_errors);acks=deepcopy(self.acks)
            cancelled={name for name,event in self.events.items() if event.is_set() or self.cancel.is_set()}
        rows=[]
        for name,profile in profiles:
            node=nodes.get(name);row={**profile.snapshot(),**(node.snapshot() if node is not None else {})}
            ready=[ack for ack in acks.get(name,{}).values() if ack['state']=='READY']
            if name in cancelled:
                if row.get('state')!='FAULT':row['state']='STOPPED'
                row['local_state_read_from_owned_sdk']=False
                if 'native_connection' in row:row['native_connection'].update(state='STOPPED',connected=False,stale=True)
            row.update(profile=name,state='STOPPING' if name in stopping else 'STARTING' if name in busy else row['state'],
                last_error=row.get('last_error','') or errors.get(name,''),
                enrollment={'state':'ACKNOWLEDGED' if ready else 'WAITING' if node is not None else 'NOT_STARTED',
                    'owners_acknowledged':len(ready),'admitted_validator_count':sum(len(ack['admitted_validator_keys']) for ack in ready),
                    'receipt_is_native_connectivity':False,'last_error':enrollment_errors.get(name,'')})
            rows.append(row)
        for name in sorted(busy-{name for name,_profile in profiles}):
            rows.append({'profile':name,'role':'native_full_observer','state':'STARTING','owned_native_process':False,
                'consensus_signing':False,'voting_power':0,'last_error':'','enrollment':{'state':'NOT_STARTED'}})
        result=empty_snapshot();result.update(profiles=rows,own_running=sum(bool(row.get('owned_native_process')) for row in rows),
            own_connected=sum(bool(row.get('native_connection',{}).get('connected')) for row in rows))
        return result

    def request_stop(self):
        self.cancel.set()
        with self.lock:items=tuple((self.events.get(name),node) for name,node in self.nodes.items());events=tuple(self.events.values())
        for event in events:self.peer.cancel_operation(event)
        for _event,node in items:node.request_stop()

    def close(self):
        self.request_stop()
        with self.lock:nodes=tuple(self.nodes.values());profiles=tuple(self.profiles.values());threads=(self._status_thread,self._enroll_thread)
        for node in nodes:node.close()
        for worker in threads:
            if worker is not None and worker is not threading.current_thread():worker.join(4)
        if any(worker is not None and worker is not threading.current_thread() and worker.is_alive() for worker in threads):
            raise ValueError('GG_OBSERVER_WORKER_STOP_TIMEOUT')
        for profile in profiles:profile.close()
        with self.lock:self.nodes.clear();self.profiles.clear();self.events.clear();self.busy.clear();self.stopping.clear()
