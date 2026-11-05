"""Owned bounded IPC for the native SDK's encrypted proof transport.

Keys enter a verified child through its private stdin, never argv or a file.
Transport authentication establishes a peer identity, never account execution
or voting authority. Application clients still verify every selected proof.
"""
from copy import deepcopy
import ipaddress
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import threading
from backend import gg_process_termination as termination
from backend.gg_native_start import native_pipe_creation_flags
from backend import gg_native_resources as resource_profiles
from backend import gg_native_pipe_lifecycle as native_pipes
import time

from backend import gg_consensus as native,gg_financial_protocol as protocol
from backend.gg_ed25519 import Keypair
from backend.gg_node_store import pack,unpack

MAX_FRAME=256*1024+4096
SCHEMA='gg.protocol.transport-frame.v1'



def _transport_budget(value):
    if type(value) is not dict:raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
    base=resource_profiles.LOW.transport()
    if set(value)!=set(base) or value.get('schema')!=base['schema']:
        raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
    if any(type(value[name]) is not int for name in set(base)-{'schema'}):
        raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
    if (not 8<=value['connections']<=64 or not 32<=value['requests_per_second']<=8192
            or not 8<=value['requests_per_connection_second']<=1024
            or not 2<=value['handlers']<=64 or not 8<=value['queue_count']<=256
            or value['queue_bytes']!=value['queue_count']*65536
            or not 1<=value['client_interval_micros']<=135000
            or value['client_interval_micros']*value['requests_per_connection_second']<1000000
            or value['request_seconds']!=20 or value['request_bytes']!=65536 or value['response_bytes']!=MAX_FRAME):
        raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
    return deepcopy(value)


def endpoint(value):
    if not isinstance(value,dict) or set(value)!={'host','port','server_key'}:raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT')
    host=value['host'];port=value['port']
    if type(host) is not str or type(port) is not int or not 1<=port<=65535:raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT')
    try:address=ipaddress.ip_address(host)
    except ValueError:raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT') from None
    networks=tuple(ipaddress.ip_network(item) for item in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','::1/128','fc00::/7'))
    if not any(address.version==network.version and address in network for network in networks):raise ValueError('GG_PROTOCOL_LOCAL_TESTNET_ENDPOINT_REQUIRED')
    protocol.financial.account_address(value['server_key']);return deepcopy(value)


def _code(error):
    text=str(error)
    return text if re.fullmatch(r'GG_[A-Z0-9_]{1,100}',text) else 'GG_PROTOCOL_RELAY_REQUEST_FAILED'


def _protected_context(key,pin,owner,profile):
    if owner is None and profile is None:return ()
    from backend.gg_node_store import NodeProfile
    from backend.gg_consensus_profile import ValidatorProfile
    from backend.gg_observer_profile import ObserverProfile,PUBLIC_SCHEMAS
    if (type(owner) is not NodeProfile or type(profile) not in (ValidatorProfile,ObserverProfile)
            or owner._closed or owner._failed or owner._lease is None or owner._db is None
            or profile._closed or profile._failed or profile._lease is None or profile._db is None):
        raise ValueError('GG_PROTOCOL_RELAY_OWNED_PROFILE_REQUIRED')
    with owner._lock,profile._lock:
        if type(profile) is ObserverProfile and profile._body['schema'] not in PUBLIC_SCHEMAS:
            raise ValueError('GG_PROTOCOL_RELAY_OWNED_PROFILE_REQUIRED')
        if type(profile) is ObserverProfile:
            recovery=profile._recovery_intent()
            if recovery is not None and not recovery['complete']:raise ValueError('GG_OBSERVER_RECOVERY_INCOMPLETE')
        declared=profile.public_invite()['body']['owner_peer_key'] if type(profile) is ValidatorProfile else profile._body['owner_key']
        signer=profile.native_signers()[1] if type(profile) is ValidatorProfile else profile.native_node_signer()
        if (declared!=owner.descriptor()['public_keys'][0] or profile.anchor()!=pin
                or signer.pubkey()!=key.pubkey()):raise ValueError('GG_PROTOCOL_RELAY_OWNER_MISMATCH')
    return (owner,profile)


class _Pipe:
    def __init__(self,key,pin,config,*,binary=None,stamp=None,owner=None,profile=None,resources=None):
        if type(key) is not Keypair:raise ValueError('GG_PROTOCOL_RELAY_OWNED_KEY_REQUIRED')
        pin=protocol.validate_pin(pin)
        if pin['genesis']['protocol']['environment']!='TESTNET':raise ValueError('GG_PROTOCOL_LOCAL_TESTNET_REQUIRED')
        self.anchor=pin;self.binary=native._installed_binary(native.TOOLS) if binary is None else Path(binary)
        self.stamp=native._validate_binary_at(native.TOOLS,self.binary) if binary is None else stamp
        self._write_lock=threading.RLock();self._closed=False
        self._protected_owners=_protected_context(key,pin,owner,profile)
        self._resources=resource_profiles.resolve(resources)
        if self._resources.mode=='SERVER' and not self._protected_owners:raise ValueError('GG_PROTOCOL_RELAY_OWNED_PROFILE_REQUIRED')
        self._transport_budget=self._resources.transport();self._peer_budget=resource_profiles.LOW.transport()
        self.process=None;self._lease=None;self._native_retired=False;self._resource_retired=False
        deadline=time.monotonic()+20
        def remaining():
            left=deadline-time.monotonic()
            if left<=0:raise ValueError("GG_PROTOCOL_RELAY_START_TIMEOUT")
            return min(10,left)
        with native_pipes.TRANSPORT_PIPE_INIT.construction(self._protected_owners) as reservation:
            reservation.attach(self)
            if self._protected_owners:native_pipes.bind_owned_pipe(self,self._protected_owners)
            if self._closed or any(getattr(value,"_native_pipe_closing",False) for value in self._protected_owners):raise ValueError("GG_PROTOCOL_RELAY_OWNER_CLOSED")
            self.process=self._spawn_pipe(profile)
            if self._protected_owners:
                from backend.gg_native_process_policy import contain_owned_native
                self._lease=contain_owned_native(self.process,owner,resources=self._resources)
            bootstrap={'schema':'gg.protocol.transport-bootstrap.v1','genesis_hash':pin['genesis_hash'],'private_key':bytes(key).hex(),**config}
            if self._protected_owners:bootstrap['resources']=self._resources.wire()
            self._send_raw(pack(bootstrap),timeout=remaining());del bootstrap
            self.ready=self._read(timeout=remaining())
            expected=config['expected_key'] if config['mode']=='CLIENT' else key.pubkey().hex()
            expected_ready={'event':'READY','genesis_hash':pin['genesis_hash'],'peer_key':expected,'schema':SCHEMA}
            if self._protected_owners:
                limits=_transport_budget(self.ready.get('limits'))
                if not resource_profiles.valid_readiness(self.ready.get('resources')):raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
                if config['mode']=='SERVER' and limits!=self._transport_budget:raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
                if _transport_budget(self.ready.get('local_limits'))!=self._transport_budget:raise ValueError('GG_PROTOCOL_RELAY_RESOURCE_PROFILE')
                expected_ready.update(resources=self._resources.ready(),limits=limits,local_limits=self._transport_budget)
                self._peer_budget=limits
            if self.ready!=expected_ready:raise ValueError('GG_PROTOCOL_RELAY_IDENTITY')

    def _spawn_pipe(self,profile):
        if self._protected_owners and os.name!='nt':
            from backend.gg_posix_native import launch
            return launch(self.binary,cwd=profile.root,env=native._environment(self._resources),arguments=('protocol-transport',),resources=self._resources)
        return subprocess.Popen([str(self.binary),'protocol-transport'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,env=native._environment(self._resources),creationflags=native_pipe_creation_flags())

    def resource_observation(self):return resource_profiles.pipe_observation(self)

    def alive(self):return not self._closed and self.process is not None and not any(getattr(owner,"_native_pipe_closing",False) or owner._closed or owner._failed for owner in getattr(self,"_protected_owners",())) and self.process.poll() is None

    def _unchanged(self):
        if not self.alive():raise ValueError('GG_PROTOCOL_RELAY_STOPPED')
        if self.stamp is not None:
            info=self.binary.stat()
            if (info.st_size,info.st_mtime_ns)!=self.stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')

    def _timer(self,seconds):
        process=self.process
        def expired():
            try:process.kill()
            except OSError:pass
        timer=threading.Timer(seconds,expired);timer.daemon=True;timer.start();return timer

    def _send_raw(self,raw,*,timeout=25):
        if type(raw) is not bytes or not 0<len(raw)<=MAX_FRAME:raise ValueError('GG_PROTOCOL_RELAY_FRAME_LIMIT')
        with self._write_lock:
            self._unchanged();deadline=self._timer(timeout)
            try:self.process.stdin.write(struct.pack('>I',len(raw))+raw);self.process.stdin.flush()
            except OSError:raise ValueError('GG_PROTOCOL_RELAY_DISCONNECTED') from None
            finally:deadline.cancel()

    def send(self,value):self._send_raw(pack(value))

    def _read_exact(self,length):
        result=[]
        while length:
            raw=self.process.stdout.read(length)
            if not raw:raise ValueError('GG_PROTOCOL_RELAY_DISCONNECTED')
            result.append(raw);length-=len(raw)
        return b''.join(result)

    def _read(self,*,timeout=None):
        self._unchanged();deadline=self._timer(timeout) if timeout is not None else None
        try:
            length=struct.unpack('>I',self._read_exact(4))[0]
            if not 0<length<=MAX_FRAME:raise ValueError('GG_PROTOCOL_RELAY_FRAME_LIMIT')
            result=unpack(self._read_exact(length))
            if not isinstance(result,dict) or result.get('schema')!=SCHEMA:raise ValueError('GG_PROTOCOL_RELAY_RESPONSE')
            return result
        except OSError:raise ValueError('GG_PROTOCOL_RELAY_DISCONNECTED') from None
        finally:
            if deadline is not None:deadline.cancel()

    def request_stop(self):
        self._closed=True
        try:
            if self.process is not None and not termination.process_terminal(self.process):self.process.kill()
        except OSError:pass

    def close(self):
        if getattr(self,'_resource_retired',False):return
        if not getattr(self,'_native_retired',False):
            self.request_stop()
            if self.process is not None:
                try:termination.wait_process_terminal(self.process,1)
                except (OSError,subprocess.TimeoutExpired):pass
                try:terminal=termination.process_terminal(self.process)
                except OSError:terminal=False
                if not terminal:raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
            lease=getattr(self,'_lease',None)
            if lease is not None:lease.close();self._lease=None
            for stream in (() if self.process is None else (self.process.stdin,self.process.stdout)):
                if stream is not None:
                    try:stream.close()
                    except OSError:pass
            self._native_retired=True
        # A server's handlers are part of its ownership, even after child exit.
        if not any(thread.is_alive() for thread in getattr(self,'_threads',())):
            self._resource_retired=True
            native_pipes.release_owned_pipe(self)


class ProofTransportClient(_Pipe):
    def __init__(self,key,pin,settings,**kwargs):
        self.settings=endpoint(settings);self._control=threading.RLock();self._counter=0;self.last_contact=None;self._last_request=0;self._backoff=0
        super().__init__(key,pin,{'mode':'CLIENT','host':settings['host'],'port':settings['port'],'expected_key':settings['server_key'],'allowed_keys':[]},**kwargs)

    def call(self,request):
        with self._control:
            if not isinstance(request,dict) or len(pack(request))>65536:raise ValueError('GG_PROTOCOL_RELAY_REQUEST_LIMIT')
            own=getattr(self,'_transport_budget',resource_profiles.LOW.transport())
            peer=getattr(self,'_peer_budget',resource_profiles.LOW.transport())
            # Authenticated peer receive limits can lower local SERVER pace.
            interval=max(own['client_interval_micros'],peer['client_interval_micros'])/1000000
            delay=max(interval,getattr(self,'_backoff',0))-(time.monotonic()-self._last_request)
            if delay>0:time.sleep(delay)
            self._last_request=time.monotonic()
            self._counter+=1
            self.send({'schema':SCHEMA,'event':'REQUEST','genesis_hash':self.anchor['genesis_hash'],'id':self._counter,'payload':deepcopy(request)})
            result=self._read(timeout=35)
            if (set(result)-{'schema','event','genesis_hash','id','payload','error'} or result.get('event')!='RESPONSE'
                    or result.get('genesis_hash')!=self.anchor['genesis_hash'] or result.get('id')!=self._counter):raise ValueError('GG_PROTOCOL_RELAY_RESPONSE')
            self.last_contact=time.time()
            if result.get('error'):
                if result['error'] in ('GG_PROTOCOL_RELAY_LIMIT','GG_PROTOCOL_RELAY_QUEUE_FULL','GG_PROTOCOL_RELAY_TIMEOUT'):
                    self._backoff=min(2,max(.135,getattr(self,'_backoff',0)*2))
                raise ValueError(_code(ValueError(result['error'])))
            self._backoff=0
            if 'payload' not in result:raise ValueError('GG_PROTOCOL_RELAY_RESPONSE')
            return result['payload']


class ProofTransportServer(_Pipe):
    def __init__(self,key,pin,host,port,allowed,handler,**kwargs):
        settings=endpoint({'host':host,'port':port,'server_key':key.pubkey().hex()})
        if (not isinstance(allowed,list) or not 1<=len(allowed)<=64 or len(set(allowed))!=len(allowed)):raise ValueError('GG_PROTOCOL_RELAY_ALLOWLIST')
        for peer in allowed:protocol.financial.account_address(peer)
        budget=resource_profiles.resolve(kwargs.get('resources')).transport()
        self._handler=handler;self._queue=queue.Queue(maxsize=budget['queue_count']);self._queued_bytes=0;self._queue_lock=threading.Lock()
        self._stop=threading.Event();self._threads=[];self.last_error='';self._peers={}
        self._peer_lock=threading.RLock()
        with native_pipes.TRANSPORT_SERVER_INIT.construction((kwargs.get('owner'),kwargs.get('profile'))) as reservation:
            super().__init__(key,pin,{'mode':'SERVER','host':settings['host'],'port':settings['port'],'expected_key':'','allowed_keys':list(allowed)},**kwargs)
            reservation.attach(self)
            def start(thread):
                self._threads.append(thread)
                try:thread.start()
                except Exception:
                    # A failed synchronous Thread.start with no identity never
                    # published a joinable worker. Preserve every started thread.
                    if thread.ident is None:self._threads.remove(thread)
                    raise
            for index in range(budget['handlers']):
                start(threading.Thread(target=self._worker,name='GG-proof-relay-handler-'+str(index),daemon=True))
            start(threading.Thread(target=self._reader,name='GG-proof-relay-reader',daemon=True))

    def _reply(self,request,*,value=None,error=None):
        result={'schema':SCHEMA,'event':'RESPONSE','genesis_hash':self.anchor['genesis_hash'],'id':request['id']}
        if error:result['error']=_code(error)
        else:result['payload']=value
        if len(pack(result))>MAX_FRAME:result.pop('payload',None);result['error']='GG_PROTOCOL_RELAY_FRAME_LIMIT'
        self.send(result)

    def _reader(self):
        try:
            while not self._stop.is_set():
                request=self._read()
                if (set(request)!={'schema','event','genesis_hash','id','peer_key','payload'} or request['event']!='REQUEST'
                        or request['genesis_hash']!=self.anchor['genesis_hash'] or type(request['id']) is not int):raise ValueError('GG_PROTOCOL_RELAY_REQUEST')
                with self._peer_lock:
                    self._peers[request['peer_key']]=time.time()
                    while len(self._peers)>64:self._peers.pop(next(iter(self._peers)))
                size=len(pack(request['payload']))
                if not 0<size<=self._transport_budget['request_bytes']:raise ValueError('GG_PROTOCOL_RELAY_REQUEST_LIMIT')
                with self._queue_lock:
                    try:
                        if self._queued_bytes+size>self._transport_budget['queue_bytes']:raise queue.Full
                        self._queue.put_nowait((request,size,time.monotonic()+20));self._queued_bytes+=size
                        accepted=True
                    except queue.Full:accepted=False
                if not accepted:self._reply(request,error=ValueError('GG_PROTOCOL_RELAY_QUEUE_FULL'))
        except (ValueError,OSError) as error:
            if not self._stop.is_set():self.last_error=_code(error)
        finally:self.request_stop()

    def _worker(self):
        while not self._stop.is_set():
            try:request,size,expires=self._queue.get(timeout=.1)
            except queue.Empty:continue
            with self._queue_lock:self._queued_bytes-=size
            try:
                if time.monotonic()>expires:
                    self._reply(request,error=ValueError('GG_PROTOCOL_RELAY_TIMEOUT'));continue
                try:value=self._handler(request['peer_key'],request['payload'])
                except Exception as error:self._reply(request,error=error)
                else:self._reply(request,value=value)
            except (ValueError,OSError):self.request_stop();return
            finally:self._queue.task_done()

    def peers(self):
        with self._peer_lock:return [{'peer_key':key,'last_request_at':at} for key,at in self._peers.items() if time.time()-at<=5]

    def request_stop(self):
        self._stop.set();super().request_stop()

    def close(self):
        self.request_stop()
        pending=False
        deadline=time.monotonic()+2 if getattr(self,'_resources',resource_profiles.LOW).mode=='SERVER' else None
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(2 if deadline is None else max(0,deadline-time.monotonic()))
                if thread.is_alive():pending=True
        super().close()
        if pending:raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
