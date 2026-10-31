"""Bounded experimental LAN gossip of real signed empty DAG proposals.

Each process owns two producer signers and a separate transport signer in RAM.
The public roster is explicitly paired and coordinator-pinned. Frames have
identity/integrity/replay checks, but no traffic confidentiality, public-network
security claim, Byzantine finality, PQC or financial transaction execution.
Importing this module opens no socket and creates no key.
"""
from __future__ import annotations

import base64
from collections import OrderedDict,deque
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import errno
import ipaddress
import json
import math
import re
import secrets
import select
import socket
import struct
import threading
import time

from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag, make_public_genesis, pack, digest, _verify
from backend import gg_lan_test_tokens as test_tokens
from backend.gg_dag_hardware import ResourceController
from backend.gg_dag_wire import record_frames, RecordAssembler, MAX_BLOCK_WIRE_BYTES, CHUNK_BYTES

MAX_FRAME=64*1024
MAX_BUNDLE=256*1024
MAX_INVITE=4096
MAX_WIRE=44*1024
MAX_PEERS=3
PRODUCERS_PER_PEER=2
MAX_ORPHANS=32
MAX_ORPHAN_BYTES=1024*1024
MAX_PEER_BYTES=8*1024*1024
MAX_TOTAL_BYTES=32*1024*1024
MAX_REQUESTS=16384
ORPHAN_SECONDS=5.0
IO_TIMEOUT=.35
# A TCP retransmission on the measured Wi-Fi path can take 1.8 seconds.
# Socket polling remains short for cancellation; complete signed frames and
# handshakes have separate finite budgets, always capped by the caller's run.
FRAME_SECONDS=3.0
CONNECTION_SECONDS=8.0
PEER_FRESH_SECONDS=15.0
PEER_OFFLINE_SECONDS=45.0
_HEX=re.compile(r'^[0-9a-f]{64}$')
_SIG=re.compile(r'^[0-9a-f]{128}$')
_PRIVATE=tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8'))
_INVITE=b'GG-LAN-DAG-INVITE-v1\0'
_BUNDLE=b'GG-LAN-DAG-BUNDLE-v1\0'
_SERVER=b'GG-LAN-DAG-SERVER-AUTH-v1\0'
_CLIENT=b'GG-LAN-DAG-CLIENT-AUTH-v1\0'
_FRAME=b'GG-LAN-DAG-FRAME-v1\0'
_INSTALL_ACK=b'GG-LAN-DAG-INSTALL-ACK-v1\0'
_ANNOUNCE=b'GG-LAN-DAG-ANNOUNCE-v1\0'
_ANNOUNCE_ACK=b'GG-LAN-DAG-ANNOUNCE-ACK-v1\0'
_CIRCLE=b'GG-LAN-TEST-TOKEN-CIRCLE-v1\0'
_DAG_STRESS=b'GG-LAN-DAG-STRESS-v1\0'
DAG_STRESS_MAX_TX=50000
DAG_STRESS_LIMITS={'min_duration_ms':1000,'max_duration_ms':600000,'min_interval_ms':0,
    'max_interval_ms':60000,'max_tx_per_block':DAG_STRESS_MAX_TX,'wire_bytes':MAX_BLOCK_WIRE_BYTES,
    'scope':'BOUNDED_EXPERIMENT_NOT_HARDWARE_CAPACITY','automatic_interval_ms':0}
BULK_SECONDS=120.0


def dag_stress_capabilities():
    """Read-only constants: importing or querying creates no key/socket/work."""
    return {'supported':True,'limits':dict(DAG_STRESS_LIMITS)}


def _integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('GG_LAN_INTEGER')
    return value


def _public(value):
    if not isinstance(value,str) or not _HEX.fullmatch(value):raise ValueError('GG_LAN_PUBLIC_KEY')
    return value


def _label(value):
    if not isinstance(value,str) or not 1<=len(value)<=64 or any(ord(char)<32 for char in value):raise ValueError('GG_LAN_LABEL')
    return value


def _endpoint(host,port,*,allow_zero=False):
    try:address=ipaddress.ip_address(host)
    except ValueError:raise ValueError('GG_LAN_ADDRESS') from None
    if address.version!=4 or not any(address in block for block in _PRIVATE) or address.is_unspecified or address.is_multicast:raise ValueError('GG_LAN_ADDRESS')
    _integer(port,0 if allow_zero else 1024,65535)
    return str(address),port


def _signed(key,domain,body):
    return {'body':body,'signature':key.sign_message(domain+pack(body)).hex()}


def _checked(value,domain,public):
    if not isinstance(value,dict) or set(value)!={'body','signature'} or not isinstance(value['signature'],str) or not _SIG.fullmatch(value['signature']):raise ValueError('GG_LAN_SIGNATURE')
    _verify(public,domain+pack(value['body']),value['signature'])
    return value['body']


def _failure_code(error,fallback='GG_LAN_IO_OR_PROTOCOL_FAILED'):
    code=str(error)
    if re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code):return code
    if isinstance(error,socket.timeout):return 'GG_LAN_IO_TIMEOUT'
    if isinstance(error,ConnectionResetError):return 'GG_LAN_CONNECTION_RESET'
    if isinstance(error,ConnectionRefusedError):return 'GG_LAN_CONNECTION_REFUSED'
    if isinstance(error,BrokenPipeError):return 'GG_LAN_BROKEN_PIPE'
    if isinstance(error,OSError):return 'GG_LAN_IO_FAILED'
    return fallback


def _failure_details(error,operation='',stage=''):
    existing=getattr(error,'_gg_lan_details',{})
    allowed_operations={'PAGE','GET','INCOMING','TOKEN_STATUS','TOKEN_SYNC','TOKEN_SUBMIT','TOKEN_APPLY','CIRCLE_SIGN','CIRCLE_END',
        'DAG_STRESS_PREPARE','DAG_STRESS_BEGIN','DAG_STRESS_STOP','DAG_STRESS_STATUS','HARDWARE_PROBE'}
    allowed_stages={'CHECK','ACCEPT','WAIT','CONNECT','AUTH','SEND','RECEIVE','VALIDATE','EXECUTE'}
    classes={'TimeoutError','ConnectionResetError','ConnectionRefusedError','BrokenPipeError','OSError','ValueError','TypeError','JSONDecodeError'}
    if not isinstance(existing,dict):existing={}
    operation=operation or existing.get('operation','');stage=stage or existing.get('stage','')
    return {'operation':operation if isinstance(operation,str) and operation in allowed_operations else '',
        'stage':stage if isinstance(stage,str) and stage in allowed_stages else '',
        'error_class':type(error).__name__ if type(error).__name__ in classes else 'Exception'}


def _receive(sock,limit,*,account=None,deadline=None,check=None,frame_seconds=None):
    deadline=min(deadline if deadline is not None else float('inf'),time.monotonic()+(FRAME_SECONDS if frame_seconds is None else frame_seconds))
    def exact(count):
        data=bytearray()
        while len(data)<count:
            if check is not None:check()
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ValueError('GG_LAN_READ_DEADLINE')
            sock.settimeout(min(IO_TIMEOUT,remaining))
            # IO_TIMEOUT is a cancellation polling interval, not a new frame
            # budget. A slow signer may be silent for more than one poll.
            try:chunk=sock.recv(min(65536,count-len(data)))
            except socket.timeout:continue
            if not chunk:raise ValueError('GG_LAN_EOF')
            if account is not None:account(len(chunk))
            if check is not None:check()
            if time.monotonic()>=deadline:raise ValueError('GG_LAN_READ_DEADLINE')
            data.extend(chunk)
        return bytes(data)
    size=struct.unpack('!I',exact(4))[0]
    if not 2<=size<=limit:raise ValueError('GG_LAN_FRAME_SIZE')
    raw=exact(size)
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('GG_LAN_DUPLICATE_JSON')
            value[key]=item
        return value
    try:value=json.loads(raw,object_pairs_hook=unique)
    except (UnicodeError,RecursionError):raise ValueError('GG_LAN_JSON') from None
    if pack(value)!=raw:raise ValueError('GG_LAN_CANONICAL')
    return value,size+4


def _send(sock,value,limit,*,deadline=None,frame_seconds=None):
    raw=pack(value)
    if not 2<=len(raw)<=limit:raise ValueError('GG_LAN_FRAME_SIZE')
    until=min(time.monotonic()+(FRAME_SECONDS if frame_seconds is None else frame_seconds),deadline if deadline is not None else float('inf'))
    remaining=until-time.monotonic()
    if remaining<=0:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
    # sendall already tracks partial progress. A polling timeout here cannot be
    # retried safely: the peer may have received or executed part of the frame.
    sock.settimeout(remaining)
    sock.sendall(struct.pack('!I',len(raw))+raw)
    if time.monotonic()>=until:raise ValueError('GG_LAN_SEND_DEADLINE')
    return len(raw)+4


def validate_invite(invite):
    if len(pack(invite))>MAX_INVITE or not isinstance(invite,dict):raise ValueError('GG_LAN_INVITE_SIZE')
    body=invite.get('body')
    fields={'schema','label','host','port','peer_key','producer_keys','nonce'}
    if not isinstance(body,dict):raise ValueError('GG_LAN_INVITE')
    if body.get('schema')=='gg.lan-dag.invite.v3':
        if set(body)!=fields|{'allow_test_tokens','allow_dag_transactions'} or body.get('allow_dag_transactions') is not True or type(body.get('allow_test_tokens')) is not bool:raise ValueError('GG_LAN_INVITE')
    elif body.get('schema')=='gg.lan-dag.invite.v2':
        if set(body)!=fields|{'allow_test_tokens'} or body.get('allow_test_tokens') is not True:raise ValueError('GG_LAN_INVITE')
    elif body.get('schema')!='gg.lan-dag.invite.v1' or set(body)!=fields:raise ValueError('GG_LAN_INVITE')
    _public(body['peer_key']);_public(body['nonce']);_label(body['label']);_endpoint(body['host'],body['port'])
    producers=body['producer_keys']
    if (not isinstance(producers,list) or len(producers)!=PRODUCERS_PER_PEER
            or any(not isinstance(value,str) or not _HEX.fullmatch(value) for value in producers)
            or len(set(producers))!=PRODUCERS_PER_PEER or body['peer_key'] in producers):raise ValueError('GG_LAN_PRODUCERS')
    _checked(invite,_INVITE,body['peer_key'])
    return deepcopy(body)


def fetch_invite(host,port):
    """Finite public pairing read; it does not trust or install that identity."""
    host,port=_endpoint(host,port)
    with socket.create_connection((host,port),timeout=IO_TIMEOUT) as sock:
        sock.settimeout(IO_TIMEOUT);_send(sock,{'kind':'invite'},MAX_INVITE)
        invite,_size=_receive(sock,MAX_INVITE)
    validate_invite(invite)
    return invite


class LanDagPeer:
    def __init__(self,label,bind_host='127.0.0.1',port=0,trusted_coordinator=None,auto_produce=False,*,allowed_cidr=None,allow_test_tokens=False,allow_dag_transactions=False):
        self.label=_label(label);self.host,self.port=_endpoint(bind_host,port,allow_zero=True)
        self.allowed=ipaddress.ip_network(allowed_cidr or ('127.0.0.0/8' if self.host.startswith('127.') else self.host+'/24'),strict=False)
        if self.allowed.version!=4 or ipaddress.ip_address(self.host) not in self.allowed or not any(self.allowed.subnet_of(block) for block in _PRIVATE):raise ValueError('GG_LAN_SUBNET')
        if type(auto_produce) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(allow_test_tokens) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(allow_dag_transactions) is not bool:raise ValueError('GG_LAN_OPTION')
        self.allow_test_tokens=allow_test_tokens
        self.allow_dag_transactions=allow_dag_transactions;self._dag_enabled=False
        self._identity=Keypair();self._local_keys=[Keypair() for _ in range(PRODUCERS_PER_PEER)]
        self.public_key=self._identity.pubkey().hex()
        self._trusted=_public(trusted_coordinator) if trusted_coordinator is not None else self.public_key
        self.auto_produce=auto_produce;self._pair_nonce=secrets.token_hex(32)
        self._lock=threading.RLock();self._configuration=threading.RLock();self._cancel=threading.Event()
        self._listener=None;self._acceptor=None;self._gossip=None;self._engine=None;self._invite=None
        self._network='';self._bundle=None;self._roster={};self._local_indices=[];self._cursors={}
        self._handlers=set();self._sockets=set();self._slots=threading.BoundedSemaphore(4)
        self._orphans=OrderedDict();self._orphan_bytes=0;self._sync_gap=False
        self._traffic={};self._total_bytes=0;self._rejected=0;self._last_error='';self._last_error_at=0.0;self._last_error_details={};self._seen={}
        self._seen_monotonic={};self._peer_failures={};self._peer_exchanges={}
        self._raw_received=0;self._connection_times=deque(maxlen=32);self._connections_admitted=0
        self._outbound_next={};self._gossip_next={};self._gossip_health={};self._control_waiters={}
        self._transport_exhausted='';self._transport_revision=0;self._transport_history=deque(maxlen=32)
        self._transport_counts={'failures':0,'expected_closures':0,'successes':0,
            'admission_drops':{'RATE':0,'HANDLERS':0,'SESSION':0,'BYTES':0}}
        self._candidates=OrderedDict()
        self._tokens=None;self._token_operation=threading.RLock();self._token_plan=None
        self._circle_cancel=threading.Event();self._circle_thread=None;self._circle_sockets=set()
        self._circle={'state':'IDLE','transactions':0,'completed_rounds':0,'elapsed_ms':0,'tps':0,
            'all_peers_synced':False,'last_error':'','last_error_details':{},'stop_reason':''}
        self._token_rpc_times={};self._token_peer_cursors={};self._closed_circle_ids=set();self._last_token_sync=0.0;self._circle_epoch=0
        self._dag_control=threading.RLock();self._dag_plan=None;self._dag_closed=set()
        self._dag_cancel=threading.Event();self._dag_worker=None;self._dag_controller=None
        self._dag_stress={'state':'IDLE','duration_ms':0,'transactions_per_block':0,'interval_ms':100,
            'elapsed_ms':0,'blocks':0,'transactions':0,'all_peers_synced':False,
            'acknowledged_blocks':None,'acknowledged_transactions':None,'acknowledged_bps':None,'acknowledged_tps':None,
            'stop_reason':'','last_error':'','participants':[],'production':None}
        self._wire_limit=MAX_WIRE;self._orphan_limit=MAX_ORPHAN_BYTES
        self._peer_bytes_limit=MAX_PEER_BYTES;self._total_bytes_limit=MAX_TOTAL_BYTES;self._frame_limit=MAX_REQUESTS
        self.resources=ResourceController(cancel=self._cancel,
            stored_bytes=lambda: 3*((self._engine.stored_wire_bytes() if self._engine else 0)+self._orphan_bytes))

    def _large_capacity(self):
        if self._wire_limit>MAX_WIRE:return
        governor=self.resources.governor();headroom=governor.memory_headroom()
        if headroom is None:raise ValueError('GG_DAG_RESOURCE_NEEDS_MEMORY_MEASUREMENT')
        wire=min(MAX_BLOCK_WIRE_BYTES,int(headroom)//16)
        if wire<=MAX_WIRE:raise ValueError('GG_DAG_RESOURCE_MEMORY')
        session=min(512*1024*1024,int(headroom)//8)
        self._engine.configure_lan_capacity(block_bytes=wire,session_bytes=max(wire,session))
        self._wire_limit=wire;self._orphan_limit=min(64*1024*1024,int(headroom)//8)
        # Raise finite byte/frame credits only for an explicitly requested
        # large-block experiment. Existing consumption is retained.
        self._peer_bytes_limit=1024*1024*1024;self._total_bytes_limit=2*1024*1024*1024;self._frame_limit=131072

    def _preflight_resources(self,transactions):
        if self._resources_paused():raise ValueError('GG_DAG_RESOURCE_PAUSED')
        size=self._engine.preflight_lan_test_block(transactions,self._wire_limit)
        with self.resources.governor().reserve_memory(size*16):pass
        return size

    def _resource_check(self,deadline=None,check=None):
        pause_deadline=deadline if deadline is not None else time.monotonic()+BULK_SECONDS
        while self._resources_paused():
            if check is not None:check()
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if time.monotonic()>=pause_deadline:raise ValueError('GG_DAG_RESOURCE_DEADLINE')
            self._cancel.wait(.05)
        self.resources.governor().check_cpu(deadline=deadline,check=check)

    def _resources_paused(self):
        return any(getattr(self.resources.budget,name)==0 for name in ('overall','cpu','ram','network'))

    def hardware_test_start(self,duration_ms=10000,max_transactions_per_block=5000):
        if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        if self._gossip_active():raise ValueError('GG_DAG_HARDWARE_ACTIVE_WORK')
        return self.resources.test.start(duration_ms=duration_ms,
            max_transactions_per_block=max_transactions_per_block,
            network_probe=self._hardware_link_probe if len(self._roster)==3 else None)

    def _hardware_link_probe(self,deadline,cancel):
        """Finite authenticated echo against the two already paired nodes.

        Includes real upload/download and authentication cost. It is an
        observed LAN sample, not a claim of the ISP's maximum line speed.
        """
        rates=[]
        payload={'chunks':4,'data':base64.b64encode(bytes(16*1024)).decode('ascii')}
        for peer in self._roster:
            if peer==self.public_key:continue
            began=time.monotonic();until=min(deadline,began+CONNECTION_SECONDS)
            self._pace_connection(peer,'HARDWARE_PROBE',cancel=cancel,deadline=until)
            with self._connection(peer,deadline=until,cancel=cancel) as sock:
                def permitted():
                    if cancel.is_set() or self._cancel.is_set():raise ValueError('GG_DAG_HARDWARE_CANCELLED')
                    if time.monotonic()>=until:raise ValueError('GG_DAG_HARDWARE_DEADLINE')
                session=self._client_auth(sock,peer,until,permitted)
                _send(sock,self._frame(session,0,'HARDWARE_PROBE',payload),MAX_FRAME,deadline=until)
                received=0
                for sequence in range(4):
                    response,size=self._read(sock,MAX_FRAME,deadline=until,check=permitted)
                    body=self._check_frame(response,size,peer,session,sequence)
                    if body['kind']!='HARDWARE_ECHO' or body['payload']!={'data':payload['data']}:raise ValueError('GG_DAG_HARDWARE_LINK_PROOF')
                    received+=16*1024
                    if sequence<3:_send(sock,self._frame(session,sequence+1,'HARDWARE_PROBE_NEXT',{'data':payload['data']}),MAX_FRAME,deadline=until)
                rates.append(received/max(time.monotonic()-began,1e-9))
        if not rates:raise ValueError('GG_DAG_HARDWARE_LINK_UNAVAILABLE')
        return {'bytes_per_second':min(rates),'peer_samples':len(rates),'basis':'AUTHENTICATED_BIDIRECTIONAL_LAN_ECHO_INCLUDING_SETUP'}

    def start_pairing(self):
        with self._lock:
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self._listener:return self.public_invite()
            listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            try:
                listener.bind((self.host,self.port));listener.listen(4);listener.settimeout(.1)
            except Exception:listener.close();raise
            self.port=listener.getsockname()[1];self._listener=listener
            body={'schema':'gg.lan-dag.invite.v1','label':self.label,'host':self.host,'port':self.port,
                'peer_key':self.public_key,'producer_keys':[key.pubkey().hex() for key in self._local_keys],'nonce':self._pair_nonce}
            if self.allow_test_tokens:body.update(schema='gg.lan-dag.invite.v2',allow_test_tokens=True)
            if self.allow_dag_transactions:body.update(schema='gg.lan-dag.invite.v3',allow_test_tokens=self.allow_test_tokens,allow_dag_transactions=True)
            self._invite=_signed(self._identity,_INVITE,body)
            self._acceptor=threading.Thread(target=self._accept,name='gg-lan-accept',daemon=True);self._acceptor.start()
            return self.public_invite()

    def public_invite(self):
        with self._lock:
            if self._invite is None:raise ValueError('GG_LAN_PAIRING_REQUIRED')
            return deepcopy(self._invite)

    def pin_coordinator(self,public_key):
        with self._configuration:
            with self._lock:
                if self._engine is not None or self._cancel.is_set():raise ValueError('GG_LAN_TRUST_ALREADY_BOUND')
                self._trusted=_public(public_key)

    def candidate_invites(self):
        """At most two endpoint-checked candidates; they are not trusted peers."""
        with self._lock:return deepcopy(list(self._candidates.values()))

    def announce_invite(self,coordinator_invite):
        """Return this public invite to a pinned bootstrap without an IP lookup."""
        coordinator=validate_invite(coordinator_invite)
        if coordinator['peer_key']!=self._trusted or self._trusted==self.public_key:raise ValueError('GG_LAN_COORDINATOR_PIN')
        if ipaddress.ip_address(coordinator['host']) not in self.allowed:raise ValueError('GG_LAN_SUBNET')
        if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        nonce=secrets.token_hex(32);invite=self.public_invite()
        body={'schema':'gg.lan-dag.announce.v1','coordinator':self._trusted,'invite':invite,'nonce':nonce}
        with socket.create_connection((coordinator['host'],coordinator['port']),timeout=IO_TIMEOUT) as sock:
            sock.settimeout(IO_TIMEOUT)
            _send(sock,{'kind':'announce','announcement':_signed(self._identity,_ANNOUNCE,body)},MAX_INVITE*2)
            response,_size=self._read(sock,MAX_INVITE)
        expected={'state':'CANDIDATE','coordinator':self._trusted,'peer_key':self.public_key,'nonce':nonce,'invite_hash':digest(invite)}
        if _checked(response,_ANNOUNCE_ACK,self._trusted)!=expected:raise ValueError('GG_LAN_ANNOUNCE_ACK')
        return {'state':'CANDIDATE','coordinator':self._trusted}

    def _receive_announcement(self,value,address):
        if self._trusted!=self.public_key or self._engine is not None or self._cancel.is_set():raise ValueError('GG_LAN_PAIRING_CLOSED')
        if len(pack(value))>MAX_INVITE*2:raise ValueError('GG_LAN_ANNOUNCE_SIZE')
        body=value.get('body') if isinstance(value,dict) else None
        if (not isinstance(body,dict) or set(body)!={'schema','coordinator','invite','nonce'}
                or body.get('schema')!='gg.lan-dag.announce.v1' or body.get('coordinator')!=self.public_key):raise ValueError('GG_LAN_ANNOUNCE')
        _public(body['nonce']);invite=body['invite'];candidate=validate_invite(invite);public=candidate['peer_key']
        _checked(value,_ANNOUNCE,public)
        if public==self.public_key or candidate['host']!=address or ipaddress.ip_address(address) not in self.allowed:raise ValueError('GG_LAN_ANNOUNCE_ENDPOINT')
        with self._lock:
            existing=self._candidates.get(public)
            if existing is not None and existing!=invite:raise ValueError('GG_LAN_CANDIDATE_CHANGED')
            if existing is None and len(self._candidates)>=MAX_PEERS-1:raise ValueError('GG_LAN_CANDIDATE_CREDIT')
        # A signature proves key ownership; the matching back-fetch also proves
        # the advertised listener is reachable at the connection's source IP.
        if fetch_invite(candidate['host'],candidate['port'])!=invite:raise ValueError('GG_LAN_ANNOUNCE_ENDPOINT')
        with self._lock:
            if self._cancel.is_set() or self._engine is not None:raise ValueError('GG_LAN_PAIRING_CLOSED')
            if public not in self._candidates and len(self._candidates)>=MAX_PEERS-1:raise ValueError('GG_LAN_CANDIDATE_CREDIT')
            self._candidates[public]=deepcopy(invite)
        return _signed(self._identity,_ANNOUNCE_ACK,{'state':'CANDIDATE','coordinator':self.public_key,
            'peer_key':public,'nonce':body['nonce'],'invite_hash':digest(invite)})

    def create_session(self,invites,label='GG LAN',*,enable_test_tokens=False,enable_dag_transactions=False):
        if type(enable_test_tokens) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(enable_dag_transactions) is not bool or enable_dag_transactions and enable_test_tokens:raise ValueError('GG_LAN_OPTION')
        if self._trusted!=self.public_key:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
        if not isinstance(invites,list) or len(invites)!=MAX_PEERS:raise ValueError('GG_LAN_THREE_PEERS_REQUIRED')
        checked=[validate_invite(value) for value in invites]
        keys=[row['peer_key'] for row in checked];producer_keys=[key for row in checked for key in row['producer_keys']]
        if (len(set(keys))!=MAX_PEERS or self.public_key not in keys or len(set(producer_keys))!=MAX_PEERS*PRODUCERS_PER_PEER
                or set(keys)&set(producer_keys) or len({(row['host'],row['port']) for row in checked})!=MAX_PEERS):raise ValueError('GG_LAN_ROSTER')
        for row in checked:
            if ipaddress.ip_address(row['host']) not in self.allowed:raise ValueError('GG_LAN_SUBNET')
        ordered=sorted(zip(checked,invites),key=lambda pair:pair[0]['peer_key'])
        roster=[];public=[]
        for index,(row,invite) in enumerate(ordered):
            roster.append({'invite':deepcopy(invite),'producer_indices':[2*index,2*index+1]})
            public.extend(row['producer_keys'])
        body={'schema':'gg.lan-dag.session.v1','label':_label(label),'coordinator':self.public_key,
            'roster':roster,'public_genesis':make_public_genesis(public,enable_dag_transactions=enable_dag_transactions),'transactions_enabled':False}
        if enable_test_tokens:
            if not all(row.get('allow_test_tokens') is True for row in checked):raise ValueError('GG_LAN_TOKEN_ALL_PEERS_OPT_IN_REQUIRED')
            body.update(schema='gg.lan-dag.session.v2',test_tokens=test_tokens.genesis(checked,self.public_key))
        if enable_dag_transactions:
            if not all(row.get('allow_dag_transactions') is True for row in checked):raise ValueError('GG_LAN_DAG_ALL_PEERS_OPT_IN_REQUIRED')
            body.update(schema='gg.lan-dag.session.v3',transactions_enabled=True,dag_test_mode='PRODUCER_OWNED_NONFINANCIAL')
        bundle=_signed(self._identity,_BUNDLE,body)
        if len(pack(bundle))>MAX_BUNDLE:raise ValueError('GG_LAN_BUNDLE_SIZE')
        return bundle

    def install_session(self,bundle):
        if len(pack(bundle))>MAX_BUNDLE:raise ValueError('GG_LAN_BUNDLE_SIZE')
        with self._configuration:
            body=_checked(bundle,_BUNDLE,self._trusted)
            expected={'schema','label','coordinator','roster','public_genesis','transactions_enabled'}
            enabled=isinstance(body,dict) and body.get('schema')=='gg.lan-dag.session.v2'
            dag_enabled=isinstance(body,dict) and body.get('schema')=='gg.lan-dag.session.v3'
            if enabled:expected.add('test_tokens')
            if dag_enabled:expected.add('dag_test_mode')
            if (not isinstance(body,dict) or set(body)!=expected
                    or body.get('schema') not in ('gg.lan-dag.session.v1','gg.lan-dag.session.v2','gg.lan-dag.session.v3') or body.get('coordinator')!=self._trusted
                    or body.get('transactions_enabled') is not dag_enabled
                    or dag_enabled and body.get('dag_test_mode')!='PRODUCER_OWNED_NONFINANCIAL'):raise ValueError('GG_LAN_SESSION')
            _label(body['label']);roster=body['roster']
            if not isinstance(roster,list) or len(roster)!=MAX_PEERS:raise ValueError('GG_LAN_ROSTER')
            peers={};all_producers=[];endpoints=set()
            for index,entry in enumerate(roster):
                if (not isinstance(entry,dict) or set(entry)!={'invite','producer_indices'}
                        or not isinstance(entry['producer_indices'],list) or any(type(value) is not int for value in entry['producer_indices'])
                        or entry['producer_indices']!=[2*index,2*index+1]):raise ValueError('GG_LAN_ROSTER')
                invite=validate_invite(entry['invite']);public=invite['peer_key']
                if public in peers or (invite['host'],invite['port']) in endpoints or ipaddress.ip_address(invite['host']) not in self.allowed:raise ValueError('GG_LAN_ROSTER')
                peers[public]={**invite,'producer_indices':entry['producer_indices'],'credit_index':index}
                all_producers.extend(invite['producer_keys']);endpoints.add((invite['host'],invite['port']))
            if len(set(all_producers))!=MAX_PEERS*PRODUCERS_PER_PEER or set(peers)&set(all_producers):raise ValueError('GG_LAN_ROSTER')
            if self._trusted not in peers:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
            own=peers.get(self.public_key)
            if own is None or own['nonce']!=self._pair_nonce or own['producer_keys']!=[key.pubkey().hex() for key in self._local_keys] or (own['host'],own['port'])!=(self.host,self.port):raise ValueError('GG_LAN_OWN_IDENTITY')
            network=digest(body,b'GG-LAN-DAG-NETWORK-v1\0')
            ledger=None
            if dag_enabled and (not self.allow_dag_transactions or not all(row.get('allow_dag_transactions') is True for row in peers.values())):
                raise ValueError('GG_LAN_DAG_ALL_PEERS_OPT_IN_REQUIRED')
            if enabled:
                if not self.allow_test_tokens or not all(row.get('allow_test_tokens') is True for row in peers.values()):
                    raise ValueError('GG_LAN_TOKEN_ALL_PEERS_OPT_IN_REQUIRED')
                ledger=test_tokens.TestTokenLedger(network,body['test_tokens'],list(peers.values()),self._trusted,
                    self.public_key,self._local_keys[0],self._identity if self.public_key==self._trusted else None)
            with self._lock:
                if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                if self._engine is not None:
                    if self._network!=network:raise ValueError('GG_LAN_NETWORK_ALREADY_BOUND')
                    return self.snapshot()
            engine=ParallelDag.from_public_genesis(body['public_genesis'])
            if engine._lan_test_mode!=dag_enabled:raise ValueError('GG_LAN_DAG_GENESIS_MODE')
            if engine._producer_public!=all_producers:raise ValueError('GG_LAN_PRODUCER_BINDING')
            engine.attach_local_producers(dict(zip(own['producer_indices'],self._local_keys)))
            with self._lock:
                if self._cancel.is_set():
                    engine.stop();raise ValueError('GG_LAN_STOPPED')
                self._engine=engine;self._network=network;self._bundle=deepcopy(bundle);self._roster=peers
                self._tokens=ledger;self._dag_enabled=dag_enabled
                self._local_indices=list(own['producer_indices']);self._cursors={key:0 for key in peers if key!=self.public_key}
                self._gossip=threading.Thread(target=self._gossip_loop,name='gg-lan-gossip',daemon=True);self._gossip.start()
            if self.auto_produce and not dag_enabled:self.start_producing()
            return self.snapshot()

    def distribute_session(self,bundle):
        self.install_session(bundle);results=[]
        for public,peer in list(self._roster.items()):
            if public==self.public_key:continue
            try:
                deadline=time.monotonic()+CONNECTION_SECONDS
                self._pace_connection(public,'INCOMING',deadline=deadline)
                with self._connection(public,deadline=deadline) as sock:
                    nonce=secrets.token_hex(32)
                    _send(sock,{'kind':'install','bundle':bundle,'nonce':nonce},MAX_BUNDLE+1024,deadline=deadline)
                    response,_size=self._read(sock,MAX_INVITE,deadline=deadline)
                    if _checked(response,_INSTALL_ACK,public)!={'state':'READY','network_id':self._network,'peer_key':public,'nonce':nonce}:raise ValueError('GG_LAN_INSTALL_ACK')
                results.append({'label':peer['label'],'state':'READY'})
            except (OSError,ValueError):results.append({'label':peer['label'],'state':'UNAVAILABLE'})
        return results

    def start_producing(self,interval_ms=250):
        _integer(interval_ms,100,60000)
        with self._configuration:
            with self._lock:
                if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                engine=self._engine
            if engine is None:raise ValueError('GG_LAN_SESSION_REQUIRED')
            if self._dag_enabled:raise ValueError('GG_LAN_DAG_USE_FINITE_STRESS')
            result=engine.start_async_live(6,0,interval_ms,producer_count=6,local_producers=self._local_indices)
            # request_stop is lock-free and can race the engine replacing its
            # resumable live Event. Recheck after startup, then join that work.
            if self._cancel.is_set():
                engine.request_stop();engine.stop_live();raise ValueError('GG_LAN_STOPPED')
            return result

    def stop_producing(self):
        with self._lock:engine=self._engine
        return engine.stop_live() if engine else self.snapshot()

    @staticmethod
    def _dag_same_evidence(left,right):
        fields=('chain_id','blocks','transactions','blockset_digest','state_root','producer_blocks','producer_transactions')
        for value in (left,right):
            if not isinstance(value,dict) or any(key not in value for key in fields) or value.get('protocol_fault')!='':return False
            if not isinstance(value['chain_id'],str) or not re.fullmatch(r'ggdag:[0-9a-f]{24}',value['chain_id']):return False
            if any(type(value[key]) is not int or value[key]<0 for key in ('blocks','transactions')):return False
            if any(not isinstance(value[key],str) or not _HEX.fullmatch(value[key]) for key in ('blockset_digest','state_root')):return False
            for key,total in (('producer_blocks','blocks'),('producer_transactions','transactions')):
                rows=value[key]
                if not isinstance(rows,list) or len(rows)!=6 or any(type(row) is not int or row<0 for row in rows) or sum(rows)!=value[total]:return False
        return all(left[key]==right[key] for key in fields)

    def _dag_status(self):
        engine=self._engine
        if engine is None or not self._dag_enabled:raise ValueError('GG_LAN_DAG_TRANSACTIONS_DISABLED')
        evidence=engine.lan_evidence()
        with self._lock:
            plan=self._dag_plan;state=dict(self._dag_stress)
            production=state.get('production')
            if isinstance(production,dict):
                production=dict(production)
                if production.get('state')=='RUNNING' and plan is not None and 'production_started' in plan:
                    production['elapsed_ms']=(time.monotonic()-plan['production_started'])*1000
                state['production']=self._dag_public_production(production)
            if plan is not None:
                state['blocks']=max(0,evidence['blocks']-plan['baseline']['blocks'])
                state['transactions']=max(0,evidence['transactions']-plan['baseline']['transactions'])
                if state['state'] in ('STARTING','RUNNING','STOPPING'):
                    state['elapsed_ms']=round((time.monotonic()-plan['started'])*1000)
            return {**state,'evidence':evidence,'workload':engine.workload_observation(),'run_id':plan['body']['run_id'] if plan else '',
                'worker_active':bool(self._dag_worker and self._dag_worker.is_alive())}

    @staticmethod
    def _dag_stopped_observation_matches(status,evidence,run_id):
        return (isinstance(status,dict) and status.get('run_id')==run_id
            and status.get('worker_active') is False and status.get('state') in ('COMPLETE','STOPPING')
            and status.get('last_error')=='' and LanDagPeer._dag_same_evidence(evidence,status.get('evidence')))

    @staticmethod
    def _dag_public_production(value):
        """Owned admitted work over its own worker window, never replica ACK."""
        if not isinstance(value,dict):return None
        state=value.get('state');blocks=value.get('blocks');transactions=value.get('transactions');elapsed=value.get('elapsed_ms')
        if (state not in ('RUNNING','COMPLETE','STOPPED','ERROR','LIMIT_REACHED')
                or any(type(number) is not int or not 0<=number<=2**53-1 for number in (blocks,transactions))
                or type(elapsed) not in (int,float) or not math.isfinite(elapsed) or not 0<=elapsed<=10**9):return None
        elapsed=round(elapsed,3);seconds=elapsed/1000
        return {'basis':'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY','state':state,
            'blocks':blocks,'transactions':transactions,'elapsed_ms':round(elapsed,3),
            'bps':round(blocks/seconds,3) if seconds>0 else None,
            'tps':round(transactions/seconds,3) if seconds>0 else None}

    @staticmethod
    def _dag_public_workload(value):
        result={'basis':'RECENT_JOBS_NOT_CAPACITY','local':None,'relay':None}
        if not isinstance(value,dict):return result
        for name,fields in (('local',('sign_ms','verify_ms','wall_ms','age_seconds')),
                            ('relay',('wall_ms','cpu_ms','age_seconds'))):
            row=value.get(name)
            if not isinstance(row,dict) or type(row.get('transactions')) is not int or not 0<=row['transactions']<=DAG_STRESS_MAX_TX:continue
            result[name]={'transactions':row['transactions']}
            for key in fields:
                number=row.get(key)
                result[name][key]=number if type(number) in (int,float) and math.isfinite(number) and 0<=number<=10**9 else None
            if name=='relay':
                resolved=row.get('cpu_sample_resolved')
                result[name]['cpu_sample_resolved']=resolved if type(resolved) is bool else None
                if resolved is False:result[name]['cpu_ms']=None
        return result

    @staticmethod
    def _dag_evidence_check(status,evidence,run_id):
        """Describe the unchanged ACK predicate without exposing IDs/digests."""
        status=status if isinstance(status,dict) else {}
        observed=status.get('evidence');observed=observed if isinstance(observed,dict) else {}
        pending=[]
        for name,ok in (('observation',bool(status)),('run',status.get('run_id')==run_id),
                ('worker',status.get('worker_active') is False),('state',status.get('state') in ('COMPLETE','STOPPING')),
                ('peer_error',status.get('last_error')==''),('proof_format',LanDagPeer._dag_same_evidence(observed,observed) and LanDagPeer._dag_same_evidence(evidence,evidence))):
            if not ok:pending.append(name)
        for key in ('chain_id','blocks','transactions','blockset_digest','state_root','producer_blocks','producer_transactions'):
            if observed.get(key)!=evidence.get(key):pending.append(key)
        def count(key):
            value=observed.get(key)
            return value if type(value) is int and 0<=value<=2**53-1 else None
        return {'matched':LanDagPeer._dag_stopped_observation_matches(status,evidence,run_id),
            'blocks':count('blocks'),'transactions':count('transactions'),'pending':pending}

    def _dag_stress_command(self,peer,kind,payload):
        """Authenticated coordinator-only, idempotent two-phase finite controls."""
        if peer!=self._trusted:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
        if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        if not isinstance(payload,dict):raise ValueError('GG_LAN_DAG_STRESS_REQUEST')
        with self._dag_control:
            if kind=='DAG_STRESS_STATUS' and not payload:return self._dag_status()
            if kind=='DAG_STRESS_PREPARE' and set(payload)=={'plan'}:
                if self.resources.test.snapshot()['state']=='RUNNING':raise ValueError('GG_DAG_HARDWARE_ACTIVE_WORK')
                signed=payload['plan'];body=_checked(signed,_DAG_STRESS,self._trusted)
                fields={'schema','network_id','run_id','duration_ms','transactions_per_block','interval_ms','remote','expires_at_ns','baseline'}
                if (not isinstance(body,dict) or set(body)!=fields or body.get('schema')!='gg.lan-dag.stress.v1'
                        or body.get('network_id')!=self._network or type(body.get('remote')) is not bool):raise ValueError('GG_LAN_DAG_STRESS_PLAN')
                _public(body['run_id']);_integer(body['duration_ms'],1000,600000)
                _integer(body['transactions_per_block'],1,DAG_STRESS_MAX_TX);_integer(body['interval_ms'],0,60000)
                _integer(body['expires_at_ns'],1,2**63-1)
                if not self._dag_enabled or not self.allow_dag_transactions or not all(row.get('allow_dag_transactions') is True for row in self._roster.values()):
                    raise ValueError('GG_LAN_DAG_ALL_PEERS_OPT_IN_REQUIRED')
                if body['transactions_per_block']>64 or any(value<100 for value in self.resources.budget.public().values()):self._large_capacity()
                self._preflight_resources(body['transactions_per_block'])
                remaining=(body['expires_at_ns']-time.time_ns())/1e9
                if remaining<=0 or remaining>body['duration_ms']/1000+1:raise ValueError('GG_LAN_DAG_STRESS_CLOCK_OR_EXPIRY')
                current=self._dag_plan
                if current is not None and current['body']['run_id']==body['run_id']:
                    if current['body']!=body:raise ValueError('GG_LAN_DAG_STRESS_CHANGED')
                    if body['run_id'] in self._dag_closed:raise ValueError('GG_LAN_DAG_STRESS_REPLAY')
                    return self._dag_status()
                if body['run_id'] in self._dag_closed:raise ValueError('GG_LAN_DAG_STRESS_REPLAY')
                if len(self._dag_closed)>=4096:raise ValueError('GG_LAN_DAG_STRESS_RUN_LIMIT')
                if self._dag_worker and self._dag_worker.is_alive() or current is not None and time.monotonic()<current['deadline'] and current['body']['run_id'] not in self._dag_closed:
                    raise ValueError('GG_LAN_DAG_STRESS_BUSY')
                if self._engine.snapshot()['live']['enabled']:raise ValueError('GG_LAN_DAG_UNRELATED_PRODUCER_ACTIVE')
                baseline=self._engine.lan_evidence()
                if not self._dag_same_evidence(baseline,body['baseline']):raise ValueError('GG_LAN_DAG_BASELINE_NOT_SYNCED')
                if current is not None:self._dag_closed.add(current['body']['run_id'])
                now=time.monotonic();duration=min(remaining,body['duration_ms']/1000)
                # Reserve a bounded portion of the same global budget for drain
                # and authenticated evidence; this is not additional run time.
                # STOP and fresh evidence use the same authenticated transport
                # as setup. Low payloads still need time for those round trips.
                deadline=now+duration;drain=min(30.0,body['duration_ms']/2000)
                self._dag_cancel=threading.Event()
                self._dag_plan={'body':deepcopy(body),'signed':deepcopy(signed),'deadline':deadline,
                    'production_deadline':deadline-drain,'started':now,'baseline':baseline,'begun':False}
                with self._lock:
                    self._dag_stress.update(state='STARTING',duration_ms=body['duration_ms'],transactions_per_block=body['transactions_per_block'],
                        interval_ms=body['interval_ms'],elapsed_ms=0,blocks=0,transactions=0,all_peers_synced=False,
                        acknowledged_blocks=None,acknowledged_transactions=None,acknowledged_bps=None,acknowledged_tps=None,
                        stop_reason='',last_error='',last_error_details={},failure_phase='',phase_ms={},status_polls=0,convergence={},
                        acknowledgement_basis='',participants=[],production=None)
                return self._dag_status()
            if kind in ('DAG_STRESS_BEGIN','DAG_STRESS_STOP') and set(payload)=={'run_id'}:
                _public(payload['run_id']);plan=self._dag_plan
                if plan is None or plan['body']['run_id']!=payload['run_id']:
                    if kind=='DAG_STRESS_STOP':return {'state':'ALREADY_CLOSED','run_id':payload['run_id']}
                    raise ValueError('GG_LAN_DAG_STRESS_RUN')
                if kind=='DAG_STRESS_BEGIN':
                    if payload['run_id'] in self._dag_closed or time.monotonic()>=plan['production_deadline']:raise ValueError('GG_LAN_DAG_STRESS_REPLAY_OR_EXPIRED')
                    if plan['begun']:return self._dag_status()
                    if self._engine.snapshot()['live']['enabled']:raise ValueError('GG_LAN_DAG_UNRELATED_PRODUCER_ACTIVE')
                    plan['begun']=True
                    with self._lock:self._dag_stress['state']='RUNNING'
                    with self._engine._lock:
                        for index in self._local_indices:self._engine._producer_stats[index]['configured_interval_ms']=plan['body']['interval_ms']
                    result=self._dag_status()
                    if self.public_key==self._trusted or plan['body']['remote']:
                        self._dag_worker=threading.Thread(target=self._dag_produce_loop,args=(plan,self._dag_cancel),name='gg-lan-dag-stress-worker',daemon=True)
                        self._dag_worker.start()
                        result['worker_active']=True
                    return result
                self._dag_cancel.set();self._dag_closed.add(payload['run_id'])
                worker=self._dag_worker
                if worker and worker is not threading.current_thread():worker.join(min(1,max(0,plan['deadline']-time.monotonic())))
                if worker and worker.is_alive():raise ValueError('GG_LAN_DAG_STRESS_STOP_TIMEOUT')
                with self._lock:
                    if self._dag_stress['state'] not in ('ERROR','LIMIT_REACHED','COMPLETE','TIME_BUDGET'):
                        self._dag_stress['state']='STOPPING' if self.public_key==self._trusted else 'COMPLETE'
                    self._dag_stress['elapsed_ms']=round((time.monotonic()-plan['started'])*1000)
                return self._dag_status()
            raise ValueError('GG_LAN_DAG_STRESS_REQUEST')

    def _dag_produce_loop(self,plan,cancel):
        started=time.monotonic();produced_blocks=0;produced_transactions=0;production_state='COMPLETE'
        with self._lock:
            plan['production_started']=started
            self._dag_stress['production']={'state':'RUNNING','blocks':0,'transactions':0,'elapsed_ms':0}
        def alive():
            if cancel.is_set() or self._cancel.is_set() or time.monotonic()>=plan['production_deadline']:raise ValueError('GG_LAN_DAG_STRESS_DEADLINE')
        def permitted():
            alive()
            while any(getattr(self.resources.budget,name)==0 for name in ('overall','cpu','ram','network')):
                alive();cancel.wait(.05)
            self._resource_check(plan['production_deadline'],alive)
        try:
            cadence=plan['body']['interval_ms']/1000;due=time.monotonic()
            while time.monotonic()<plan['production_deadline'] and not cancel.is_set() and not self._cancel.is_set():
                if cancel.wait(max(0,min(due,plan['production_deadline'])-time.monotonic())):break
                for producer in self._local_indices:
                    permitted()
                    estimate=self._engine.preflight_lan_test_block(plan['body']['transactions_per_block'],self._wire_limit)
                    with self.resources.governor().reserve_memory(estimate*16):
                        block=self._engine.produce_lan_test_block(producer,plan['body']['transactions_per_block'],self._wire_limit,check=permitted)
                    produced_blocks+=1;produced_transactions+=block['transactions']
                    with self._lock:
                        self._dag_stress['production']={'state':'RUNNING','blocks':produced_blocks,
                            'transactions':produced_transactions,'elapsed_ms':(time.monotonic()-started)*1000}
                due=max(due+cadence,time.monotonic())
        except ValueError as error:
            code=str(error)
            if code not in {'GG_LAN_DAG_STRESS_DEADLINE','GG_DAG_RESOURCE_DEADLINE'}:
                state='LIMIT_REACHED' if code in {'GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_RECORD_LIMIT','GG_DAG_STORAGE_LIMIT','GG_DAG_LAN_WIRE_PROFILE_LIMIT'} else 'ERROR'
                production_state=state
                with self._lock:self._dag_stress.update(state=state,stop_reason='SOFTWARE_PROFILE_LIMIT' if state=='LIMIT_REACHED' else 'FAILED',last_error=_failure_code(error,'GG_LAN_DAG_STRESS_FAILED'))
        except Exception as error:
            production_state='ERROR'
            with self._lock:self._dag_stress.update(state='ERROR',stop_reason='FAILED',last_error=_failure_code(error,'GG_LAN_DAG_STRESS_FAILED'))
        finally:
            with self._lock:
                if production_state=='COMPLETE' and (cancel.is_set() or self._cancel.is_set()):production_state='STOPPED'
                self._dag_stress['production']=self._dag_public_production({'state':production_state,
                    'blocks':produced_blocks,'transactions':produced_transactions,'elapsed_ms':(time.monotonic()-started)*1000})
                if self._dag_plan is plan and self._dag_stress['state']=='RUNNING':self._dag_stress['state']='STOPPING'

    def start_dag_stress(self,duration_ms=10000,transactions_per_block=16,interval_ms=100,remote=True):
        if self.resources.test.snapshot()['state']=='RUNNING':raise ValueError('GG_DAG_HARDWARE_ACTIVE_WORK')
        _integer(duration_ms,1000,600000);_integer(transactions_per_block,1,DAG_STRESS_MAX_TX);_integer(interval_ms,0,60000)
        if self._transport_exhausted:raise ValueError('GG_LAN_SESSION_EXHAUSTED')
        if type(remote) is not bool:raise ValueError('GG_LAN_OPTION')
        if self.public_key!=self._trusted:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
        with self._dag_control:
            if self._dag_controller and self._dag_controller.is_alive():raise ValueError('GG_LAN_DAG_STRESS_BUSY')
            if not self._dag_enabled:raise ValueError('GG_LAN_DAG_TRANSACTIONS_DISABLED')
            if transactions_per_block>64 or any(value<100 for value in self.resources.budget.public().values()):self._large_capacity()
            self._preflight_resources(transactions_per_block)
            baseline=self._engine.lan_evidence()
            body={'schema':'gg.lan-dag.stress.v1','network_id':self._network,'run_id':secrets.token_hex(32),
                'duration_ms':duration_ms,'transactions_per_block':transactions_per_block,'interval_ms':interval_ms,
                'remote':remote,'expires_at_ns':time.time_ns()+duration_ms*1_000_000,'baseline':baseline}
            signed=_signed(self._identity,_DAG_STRESS,body)
            self._dag_stress_command(self.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
            plan=self._dag_plan;cancel=self._dag_cancel
            self._dag_controller=threading.Thread(target=self._dag_coordinate,args=(plan,cancel),name='gg-lan-dag-stress-control',daemon=True)
            self._dag_controller.start()
            return self._dag_stress_snapshot()

    def _dag_coordinate(self,plan,cancel):
        attempted=[];statuses={};cleanup_statuses={};terminal='TIME_BUDGET';reason='DURATION';error='';synced=False
        deadline=plan['deadline'];run_id=plan['body']['run_id']
        phase='PREPARE';phase_started=time.monotonic();phase_ms={};details={};failure_phase='';status_polls=0
        acknowledgement_basis='';observed_before_deadline=False;last_check=None
        def check_observations(evidence,observations):
            return [{'label':self._roster[peer]['label'],**self._dag_evidence_check(observations.get(peer),evidence,run_id)}
                    for peer in attempted]
        def remember_check(evidence):
            nonlocal last_check
            now=time.monotonic()
            if now<deadline:
                peers=check_observations(evidence,statuses);now=time.monotonic()
                if now<deadline:last_check={'remaining_ms':round((deadline-now)*1000,3),'peers':peers}
        def enter_phase(name):
            nonlocal phase,phase_started
            now=time.monotonic();phase_ms[phase]=round(phase_ms.get(phase,0)+(now-phase_started)*1000,3)
            phase=name;phase_started=now
        def peer_failure(status):
            if not isinstance(status,dict):return ''
            proof=status.get('evidence');fault=proof.get('protocol_fault') if isinstance(proof,dict) else ''
            value=status.get('last_error') or fault
            return _failure_code(ValueError(str(value)),'GG_LAN_DAG_PEER_FAILED') if value else ''
        try:
            for peer in self._roster:
                if peer==self.public_key:continue
                attempted.append(peer)
                statuses[peer]=self._token_rpc(peer,'DAG_STRESS_PREPARE',{'plan':plan['signed']},cancel=cancel,deadline=deadline)
            enter_phase('BEGIN')
            for peer in attempted:
                statuses[peer]=self._token_rpc(peer,'DAG_STRESS_BEGIN',{'run_id':run_id},cancel=cancel,deadline=deadline)
            self._dag_stress_command(self.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id})
            enter_phase('PRODUCE')
            while time.monotonic()<plan['production_deadline'] and not cancel.is_set() and not self._cancel.is_set():
                if self._dag_stress['state'] in ('ERROR','LIMIT_REACHED'):break
                cancel.wait(min(.1,max(0,plan['production_deadline']-time.monotonic())))
            if cancel.is_set() or self._cancel.is_set():reason='CANCELLED'
            enter_phase('STOP')
            self._dag_stress_command(self.public_key,'DAG_STRESS_STOP',{'run_id':run_id})
            for peer in attempted:
                statuses[peer]=self._token_rpc(peer,'DAG_STRESS_STOP',{'run_id':run_id},deadline=deadline)
            enter_phase('CONVERGENCE')
            while time.monotonic()<deadline and not self._cancel.is_set():
                # STOP is already an authenticated, run-bound observation after
                # joining that peer's worker. Reuse its complete proof when it
                # matches the fresh local set; request only missing observations.
                local=self._dag_status();evidence=local['evidence'];unmatched=[]
                remember_check(evidence)
                for peer in attempted:
                    status=statuses.get(peer,{});peer_error=peer_failure(status)
                    if peer_error:
                        terminal='LIMIT_REACHED' if status.get('state')=='LIMIT_REACHED' else 'ERROR';error=peer_error
                    if not self._dag_stopped_observation_matches(status,evidence,run_id):unmatched.append(peer)
                if evidence['protocol_fault']:terminal='ERROR';error=evidence['protocol_fault']
                if error:break
                if not unmatched and local.get('worker_active') is False and time.monotonic()<deadline:
                    synced=True;observed_before_deadline=True
                    acknowledgement_basis='STOP_OBSERVATIONS' if status_polls==0 else 'STOP_AND_STATUS_OBSERVATIONS'
                    break
                for peer in unmatched:
                    status_polls+=1
                    statuses[peer]=self._token_rpc(peer,'DAG_STRESS_STATUS',{},deadline=deadline)
                # Check newly received matching evidence before a poll pause
                # can consume the last part of the original signed budget.
                fresh=self._dag_status();remember_check(fresh['evidence'])
                if fresh.get('worker_active') is False and all(
                        self._dag_stopped_observation_matches(statuses.get(peer),fresh['evidence'],run_id)
                        for peer in attempted):continue
                # Status RPCs share the connection gate with PAGE traffic. Leave
                # one control interval for the actual block exchange needed to
                # converge. Keep the original deadline and lifetime cancellation.
                self._cancel.wait(min(.125,max(0,deadline-time.monotonic())))
            local=self._dag_status()
            synced=synced and observed_before_deadline and local.get('worker_active') is False and all(
                self._dag_stopped_observation_matches(statuses.get(peer),local['evidence'],run_id) for peer in attempted)
            if local['last_error']:
                error=local['last_error'];terminal='LIMIT_REACHED' if local['state']=='LIMIT_REACHED' else 'ERROR'
            if error:synced=False;reason='SOFTWARE_PROFILE_LIMIT' if terminal=='LIMIT_REACHED' else 'FAILED'
            elif synced and local['transactions']>0:terminal='COMPLETE'
            else:terminal='TIME_BUDGET'
        except Exception as exception:
            failure_phase=phase;details=_failure_details(exception)
            error=_failure_code(exception,'GG_LAN_DAG_STRESS_FAILED')
            software_limit=error in {'GG_LAN_CREDIT','GG_LAN_SESSION_EXHAUSTED','GG_LAN_ORPHAN_CREDIT','GG_LAN_DAG_STRESS_RUN_LIMIT','GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_STORAGE_LIMIT','GG_DAG_RECORD_LIMIT'}
            terminal='LIMIT_REACHED' if software_limit else 'TIME_BUDGET' if time.monotonic()>=deadline else 'ERROR'
            if reason=='CANCELLED' or self._cancel.is_set():reason='CANCELLED';terminal='TIME_BUDGET'
            else:reason='SOFTWARE_PROFILE_LIMIT' if software_limit else 'DURATION' if terminal=='TIME_BUDGET' else 'FAILED'
            synced=False
        finally:
            if not synced and not failure_phase:failure_phase=phase
            enter_phase('CLEANUP')
            # Roll back every attempted remote start, including a lost ACK.
            # These controls only address this run ID and never engine live work.
            self._dag_cancel.set();self._dag_closed.add(run_id)
            cleanup_deadline=time.monotonic()+1
            for peer in attempted:
                try:
                    observation=self._token_rpc(peer,'DAG_STRESS_STOP',{'run_id':run_id},deadline=cleanup_deadline)
                    cleanup_statuses[peer]=observation
                    # Later cleanup may invalidate an earlier observation, but
                    # can never establish a new ACK after the work deadline.
                    peer_error=peer_failure(observation)
                    if peer_error:
                        synced=False;terminal='LIMIT_REACHED' if observation.get('state')=='LIMIT_REACHED' else 'ERROR'
                        reason='SOFTWARE_PROFILE_LIMIT' if terminal=='LIMIT_REACHED' else 'FAILED';error=peer_error;failure_phase='CLEANUP'
                    if synced and not self._dag_stopped_observation_matches(observation,statuses[peer].get('evidence'),run_id):synced=False
                except Exception:pass
            worker=self._dag_worker
            if worker and worker is not threading.current_thread():worker.join(max(0,cleanup_deadline-time.monotonic()))
            elapsed=max(.001,time.monotonic()-plan['started']);local=self._dag_status()
            synced=synced and local.get('worker_active') is False and all(
                self._dag_stopped_observation_matches(statuses.get(peer),local['evidence'],run_id) for peer in attempted)
            if local['evidence']['protocol_fault']:
                synced=False;terminal='ERROR';reason='FAILED';error=local['evidence']['protocol_fault']
            elif terminal=='COMPLETE' and not synced:
                terminal='TIME_BUDGET';reason='DURATION';error='GG_LAN_DAG_FINAL_EVIDENCE_CHANGED';failure_phase='FINAL_EVIDENCE'
            enter_phase('FINALIZE')
            rows=[]
            for peer,roster in self._roster.items():
                status=local if peer==self.public_key else cleanup_statuses.get(peer,{})
                proof=status.get('evidence',{})
                rows.append({'label':roster['label'],'local':peer==self.public_key,'opted_in':roster.get('allow_dag_transactions') is True,
                    'state':terminal if peer==self.public_key else status.get('state','UNCONFIRMED'),'blocks':proof.get('blocks'),'transactions':proof.get('transactions'),
                    'protocol_fault':proof.get('protocol_fault',''),'blockset_digest':proof.get('blockset_digest'),'state_root':proof.get('state_root'),
                    'workload':self._dag_public_workload(status.get('workload')),
                    'production':self._dag_public_production(status.get('production'))})
            with self._lock:
                self._dag_stress.update(state=terminal,stop_reason=reason,last_error=error,elapsed_ms=round(elapsed*1000),
                    blocks=local['blocks'],transactions=local['transactions'],participants=rows,all_peers_synced=synced,
                    last_error_details=details,failure_phase=failure_phase,phase_ms=phase_ms,status_polls=status_polls,
                    acknowledgement_basis=acknowledgement_basis if synced else '',
                    workload=self._dag_public_workload(local.get('workload')),
                    convergence={'before_deadline':last_check,
                        'cleanup':{'within_deadline':time.monotonic()<deadline,
                            'peers':check_observations(local['evidence'],cleanup_statuses)}},
                    acknowledged_blocks=local['blocks'] if synced else None,acknowledged_transactions=local['transactions'] if synced else None,
                    acknowledged_bps=round(local['blocks']/elapsed,3) if synced else None,acknowledged_tps=round(local['transactions']/elapsed,3) if synced else None)

    def stop_dag_stress(self):
        with self._dag_control:
            if self.public_key!=self._trusted:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
            if self._dag_plan is not None:
                self._dag_cancel.set()
                with self._lock:
                    if self._dag_stress['state'] in ('STARTING','RUNNING'):self._dag_stress['state']='STOPPING'
            return self._dag_stress_snapshot()

    def _dag_stress_snapshot(self):
        with self._lock:
            state=deepcopy(self._dag_stress);engine=self._engine
            participants=[{'label':row.get('label','Peer'),'local':peer==self.public_key,'opted_in':row.get('allow_dag_transactions') is True} for peer,row in self._roster.items()]
            busy=bool(self._dag_controller and self._dag_controller.is_alive() or self._dag_worker and self._dag_worker.is_alive())
            active=self._dag_plan is not None and time.monotonic()<self._dag_plan['deadline'] and self._dag_plan['body']['run_id'] not in self._dag_closed
        if self._dag_enabled:
            try:
                current=self._dag_status()
                for key in ('blocks','transactions','elapsed_ms','workload','production'):state[key]=current[key]
                state['worker_active']=current['worker_active']
            except ValueError:
                if self._dag_enabled and not self._cancel.is_set():raise
                state['worker_active']=False
        else:state['worker_active']=False
        state['worker_count']=1 if state['worker_active'] else 0
        return {**dag_stress_capabilities(),**state,'enabled':self._dag_enabled,'local_opt_in':self.allow_dag_transactions,
            'role':'COORDINATOR' if self.public_key==self._trusted else 'PARTICIPANT',
            'can_start':bool(self._dag_enabled and self.public_key==self._trusted and len(participants)==3 and all(row['opted_in'] for row in participants)
                and not self._transport_exhausted and not busy and not active and engine is not None and not engine.snapshot()['live']['enabled'] and not engine._lan_fault),
            'participants':state['participants'] or participants,'counts_basis':'LOCAL_DAG_ADMISSION_NOT_FINALITY',
            'measurement_scope':'THREE_REPLICA_SYNC_TEST_NOT_NETWORK_CAPACITY'}

    def _credit(self,peer,size):
        with self._lock:
            value=self._traffic.setdefault(peer,{'bytes':0,'frames':0})
            value['bytes']+=size;value['frames']+=1;self._total_bytes+=size
            if value['bytes']>self._peer_bytes_limit or self._total_bytes>self._total_bytes_limit:
                self._exhaust_transport('BYTES');raise ValueError('GG_LAN_CREDIT')
            if value['frames']>self._frame_limit:
                self._exhaust_transport('FRAMES');raise ValueError('GG_LAN_CREDIT')

    def _account_received(self,size):
        # Charge raw reads even when JSON, signatures or announced sizes fail.
        with self._lock:
            self._raw_received+=size
            if self._raw_received>self._total_bytes_limit:
                self._exhaust_transport('BYTES');raise ValueError('GG_LAN_CREDIT')

    def _exhaust_transport(self,reason):
        with self._lock:
            if reason not in {'SESSION','BYTES','FRAMES'}:raise ValueError('GG_LAN_CREDIT')
            if not self._transport_exhausted:
                self._transport_exhausted=reason;self._transport_revision+=1

    def _gossip_active(self):
        with self._lock:
            plan=self._dag_plan
            return bool(self._orphans or plan is not None and plan.get('begun') and time.monotonic()<plan['deadline']
                or any(worker is not None and worker.is_alive() for worker in (self._dag_worker,self._dag_controller))
                or self._circle['state']=='RUNNING' or self._engine and self._engine._live.get('enabled'))

    def _pace_connection(self,peer,operation,*,cancel=None,deadline=None):
        """One bounded gate for gossip and control; never wait holding a lock.

        Total <=10/s/peer, active gossip <=8/s (idle <=5/s), control <=8/s.
        Two remote peers therefore leave acceptance headroom below32/s even
        when GET/PAGE and control are interleaved. No request is replayed.
        """
        if peer not in self._roster or peer==self.public_key:raise ValueError('GG_LAN_UNKNOWN_PEER')
        gossip=operation in {'PAGE','GET'}
        if not gossip:
            with self._lock:self._control_waiters[peer]=self._control_waiters.get(peer,0)+1
        try:return self._wait_connection(peer,gossip,cancel=cancel,deadline=deadline)
        finally:
            if not gossip:
                with self._lock:
                    self._control_waiters[peer]-=1
                    if not self._control_waiters[peer]:del self._control_waiters[peer]

    def _wait_connection(self,peer,gossip,*,cancel=None,deadline=None):
        while True:
            if self._cancel.is_set() or cancel is not None and cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
            now=time.monotonic()
            if deadline is not None and now>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
            active=self._gossip_active() if gossip else False
            with self._lock:
                now=time.monotonic()
                if self._cancel.is_set() or cancel is not None and cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
                if deadline is not None and now>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
                if self._transport_exhausted:raise ValueError('GG_LAN_SESSION_EXHAUSTED')
                due=max(self._outbound_next.get(peer,0),self._gossip_next.get(peer,0) if gossip
                    else self._token_rpc_times.get(peer,float('-inf'))+.125)
                if gossip and self._control_waiters.get(peer,0):due=max(due,now+.025)
                if now>=due:
                    self._outbound_next[peer]=now+.1
                    if gossip:self._gossip_next[peer]=now+(.125 if active else .2)
                    else:self._token_rpc_times[peer]=now
                    return
            delay=min(.1,due-now)
            if deadline is not None:delay=min(delay,max(0,deadline-time.monotonic()))
            (cancel or self._cancel).wait(delay)

    def _gossip_result(self,peer,*,progress=False,error=False,active=False):
        if peer not in self._roster or peer==self.public_key:raise ValueError('GG_LAN_UNKNOWN_PEER')
        with self._lock:
            state=self._gossip_health.setdefault(peer,{'idle':0,'errors':0,'next':0})
            if error:
                state['errors']=min(5,state['errors']+1);state['idle']=0
                delay=min(1.0 if active else 4.0,.25*2**(state['errors']-1))
            else:
                state['errors']=0;state['idle']=0 if progress else min(5,state['idle']+1)
                delay=.1 if active or progress else min(2.0,.1*2**state['idle'])
            state['at']=time.monotonic();state['next']=state['at']+delay
            return delay

    def _transport_success(self):
        with self._lock:self._transport_counts['successes']+=1;self._transport_revision+=1

    @contextmanager
    def _connection(self,peer,*,deadline,cancel=None,bulk=False):
        """One owned IPv4 TCP attempt within the caller's original budget.

        Register before connect, so stop can close pending sockets. Only
        readiness is polled; neither connect nor an application RPC is retried.
        """
        address=self._roster.get(peer)
        if address is None or peer==self.public_key:raise ValueError('GG_LAN_UNKNOWN_PEER')
        endpoint=_endpoint(address['host'],address['port'])
        lifetime_deadline=min(deadline,time.monotonic()+BULK_SECONDS) if bulk else min(deadline,time.monotonic()+CONNECTION_SECONDS)
        deadline=min(lifetime_deadline,time.monotonic()+CONNECTION_SECONDS)
        def check():
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if cancel is not None and cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
            if time.monotonic()>=deadline:raise socket.timeout()
        def failed(code):
            if code in {errno.ECONNREFUSED,10061}:raise ConnectionRefusedError(code,'GG_LAN_CONNECT_FAILED')
            if code in {errno.ECONNRESET,10054}:raise ConnectionResetError(code,'GG_LAN_CONNECT_FAILED')
            if code in {errno.ETIMEDOUT,10060}:raise socket.timeout()
            raise OSError(code,'GG_LAN_CONNECT_FAILED')
        check();sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            with self._lock:
                check();self._sockets.add(sock)
                if cancel is not None:self._circle_sockets.add(sock)
            try:
                sock.setblocking(False);check();code=sock.connect_ex(endpoint)
                pending={errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EALREADY,errno.EINTR,10035,10036,10037}
                if code not in {0,errno.EISCONN,10056}:
                    if code not in pending:failed(code)
                    while True:
                        check()
                        _readable,writable,errors=select.select([],[sock],[sock],min(IO_TIMEOUT,deadline-time.monotonic()))
                        check()
                        if writable or errors:
                            code=sock.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
                            if code:failed(code)
                            break
                check();sock.settimeout(IO_TIMEOUT)
            except (OSError,ValueError):
                check();raise
            if bulk:deadline=lifetime_deadline
            yield sock
            check()
        finally:
            with self._lock:self._sockets.discard(sock);self._circle_sockets.discard(sock)
            sock.close()

    def _read(self,sock,limit,*,deadline=None,check=None,bulk=False,on_bytes=None):
        def permitted():
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if check is not None:check()
        def account(size):
            self._account_received(size)
            if on_bytes is not None:on_bytes(size)
        return _receive(sock,limit,account=account,deadline=deadline,check=permitted,
            frame_seconds=BULK_SECONDS if bulk else FRAME_SECONDS)

    def _accept(self):
        while not self._cancel.is_set():
            try:connection,address=self._listener.accept()
            except socket.timeout:continue
            except OSError:break
            now=time.monotonic()
            with self._lock:
                while self._connection_times and self._connection_times[0]<now-1:self._connection_times.popleft()
                reason=('BYTES' if self._raw_received>self._total_bytes_limit else 'SESSION'
                    if self._transport_exhausted or self._connections_admitted>=MAX_REQUESTS else 'RATE'
                    if len(self._connection_times)>=32 else '')
                if not reason:self._connection_times.append(now);self._connections_admitted+=1
            if reason:
                if reason in {'SESSION','BYTES'}:self._exhaust_transport(reason)
                self._error(ValueError('GG_LAN_ACCEPT_'+reason+'_LIMIT'),'INCOMING','ACCEPT',reason=reason)
                connection.close();self._cancel.wait(.01);continue
            if not self._slots.acquire(blocking=False):
                self._error(ValueError('GG_LAN_ACCEPT_HANDLER_LIMIT'),'INCOMING','ACCEPT',reason='HANDLERS')
                connection.close();continue
            connection.settimeout(IO_TIMEOUT)
            with self._lock:self._sockets.add(connection)
            worker=threading.Thread(target=self._serve,args=(connection,address[0]),name='gg-lan-connection',daemon=True)
            with self._lock:self._handlers.add(worker)
            worker.start()

    def _frame(self,session,sequence,kind,payload):
        body={'schema':'gg.lan-dag.frame.v1','network_id':self._network,'session':session,'sequence':sequence,'kind':kind,'payload':payload}
        return _signed(self._identity,_FRAME,body)

    def _check_frame(self,value,size,peer,session,sequence):
        if peer not in self._roster or peer==self.public_key:raise ValueError('GG_LAN_UNKNOWN_PEER')
        self._credit(peer,size)
        body=_checked(value,_FRAME,peer)
        if (not isinstance(body,dict) or set(body)!={'schema','network_id','session','sequence','kind','payload'}
                or body.get('schema')!='gg.lan-dag.frame.v1' or body.get('network_id')!=self._network
                or body.get('session')!=session or type(body.get('sequence')) is not int or body['sequence']!=sequence):raise ValueError('GG_LAN_FRAME_REPLAY_OR_DOMAIN')
        return body

    def _hello(self,peer,nonce):
        return {'kind':'hello','network_id':self._network,'peer_key':peer,'nonce':nonce}

    def _transcript(self,client,server,client_nonce,server_nonce):
        return {'schema':'gg.lan-dag.auth.v1','network_id':self._network,'client_key':client,'server_key':server,'client_nonce':client_nonce,'server_nonce':server_nonce}

    def _server_auth(self,sock,hello,address,deadline=None):
        if not isinstance(hello,dict) or set(hello)!={'kind','network_id','peer_key','nonce'} or hello.get('kind')!='hello':raise ValueError('GG_LAN_HELLO')
        if hello.get('network_id')!=self._network or not self._network:raise ValueError('GG_LAN_NETWORK_DOMAIN')
        peer=hello['peer_key'];_public(hello['nonce'])
        if peer not in self._roster or peer==self.public_key or address!=self._roster[peer]['host']:raise ValueError('GG_LAN_UNKNOWN_PEER')
        transcript=self._transcript(peer,self.public_key,hello['nonce'],secrets.token_hex(32))
        _send(sock,_signed(self._identity,_SERVER,transcript),MAX_INVITE,deadline=deadline)
        auth,size=self._read(sock,MAX_INVITE,deadline=deadline)
        if _checked(auth,_CLIENT,peer)!=transcript:raise ValueError('GG_LAN_HANDSHAKE')
        self._credit(peer,size)
        return peer,digest(transcript,b'GG-LAN-DAG-CHANNEL-v1\0')

    def _client_auth(self,sock,peer,deadline=None,check=None):
        if check is not None:check()
        nonce=secrets.token_hex(32);_send(sock,self._hello(self.public_key,nonce),MAX_INVITE,deadline=deadline)
        challenge,size=self._read(sock,MAX_INVITE,deadline=deadline,check=check);body=_checked(challenge,_SERVER,peer)
        expected={'schema','network_id','client_key','server_key','client_nonce','server_nonce'}
        if (not isinstance(body,dict) or set(body)!=expected or body.get('schema')!='gg.lan-dag.auth.v1'
                or body.get('network_id')!=self._network or body.get('client_key')!=self.public_key
                or body.get('server_key')!=peer or body.get('client_nonce')!=nonce):raise ValueError('GG_LAN_HANDSHAKE')
        _public(body['server_nonce']);self._credit(peer,size)
        if check is not None:check()
        _send(sock,_signed(self._identity,_CLIENT,body),MAX_INVITE,deadline=deadline)
        return digest(body,b'GG-LAN-DAG-CHANNEL-v1\0')

    def _serve(self,sock,address):
        operation='INCOMING';stage='RECEIVE';peer=None;complete=False;first_bytes=[0]
        def first_received(size):first_bytes[0]+=size
        try:
            deadline=time.monotonic()+CONNECTION_SECONDS
            first,size=self._read(sock,MAX_BUNDLE+1024,deadline=deadline,on_bytes=first_received)
            self._credit('unconfigured',size)
            if first=={'kind':'invite'}:
                stage='SEND';_send(sock,self.public_invite(),MAX_INVITE,deadline=deadline);complete=True;return
            if isinstance(first,dict) and set(first)=={'kind','announcement'} and first.get('kind')=='announce':
                stage='EXECUTE';response=self._receive_announcement(first['announcement'],address)
                stage='SEND';_send(sock,response,MAX_INVITE,deadline=deadline);complete=True;return
            if isinstance(first,dict) and set(first)=={'kind','bundle','nonce'} and first.get('kind')=='install':
                stage='EXECUTE'
                _public(first['nonce']);self.install_session(first['bundle'])
                ack={'state':'READY','network_id':self._network,'peer_key':self.public_key,'nonce':first['nonce']}
                stage='SEND';_send(sock,_signed(self._identity,_INSTALL_ACK,ack),MAX_INVITE,deadline=deadline);complete=True;return
            if size>MAX_INVITE:raise ValueError('GG_LAN_HELLO_SIZE')
            stage='AUTH'
            peer,session=self._server_auth(sock,first,address,deadline)
            stage='RECEIVE';request,size=self._read(sock,MAX_FRAME,deadline=deadline)
            stage='VALIDATE';body=self._check_frame(request,size,peer,session,0);operation=body['kind']
            payload=body['payload'];records=[]
            if body['kind']=='HARDWARE_PROBE':
                if (not isinstance(payload,dict) or set(payload)!={'chunks','data'} or payload['chunks']!=4
                        or type(payload['chunks']) is not int or not isinstance(payload['data'],str)
                        or payload['data']!=base64.b64encode(bytes(16*1024)).decode('ascii')):raise ValueError('GG_DAG_HARDWARE_LINK_REQUEST')
                for sequence in range(4):
                    if sequence:
                        response,size=self._read(sock,MAX_FRAME,deadline=deadline)
                        follow=self._check_frame(response,size,peer,session,sequence)
                        if follow['kind']!='HARDWARE_PROBE_NEXT' or follow['payload']!={'data':payload['data']}:raise ValueError('GG_DAG_HARDWARE_LINK_REQUEST')
                    self._credit('out:'+peer,_send(sock,self._frame(session,sequence,'HARDWARE_ECHO',{'data':payload['data']}),MAX_FRAME,deadline=deadline))
                complete=True;return
            if body['kind'].startswith(('TOKEN_','CIRCLE_','DAG_STRESS_')):
                stage='EXECUTE'
                try:result=self._dag_stress_command(peer,body['kind'],payload) if body['kind'].startswith('DAG_STRESS_') else self._token_command(peer,body['kind'],payload)
                except ValueError as error:
                    code=str(error)
                    result={'error':code if re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code) else 'GG_LAN_TOKEN_REQUEST_FAILED'}
                stage='SEND';self._credit('out:'+peer,_send(sock,self._frame(session,0,'TOKEN_RESULT',result),MAX_FRAME,deadline=deadline))
                self._mark_seen(peer)
                complete=True;return
            stage='EXECUTE'
            if body['kind']=='PAGE' and isinstance(payload,dict) and set(payload)=={'after'}:
                page=self._engine.public_proposals(payload['after'],8)['records']
                page_bytes=0
                for record in page:
                    # Pack medium blocks together; a blanket one-record page
                    # makes authentication/polling the artificial bottleneck.
                    if records and page_bytes+len(record['wire'])>2*1024*1024:break
                    records.append(record);page_bytes+=len(record['wire'])
            elif body['kind']=='GET' and isinstance(payload,dict) and set(payload)=={'hashes'}:
                hashes=payload['hashes']
                if not isinstance(hashes,list) or not 1<=len(hashes)<=8 or any(not isinstance(value,str) or not _HEX.fullmatch(value) for value in hashes) or len(set(hashes))!=len(hashes):raise ValueError('GG_LAN_GET')
                for identifier in hashes:
                    raw=self._engine.public_proposal(identifier)
                    if raw:records.append({'hash':identifier,'wire':raw,'admission_index':0})
            else:raise ValueError('GG_LAN_REQUEST')
            if self._resources_paused():records=[]
            stage='SEND'
            bulk=self._wire_limit>MAX_WIRE
            if bulk:deadline=time.monotonic()+BULK_SECONDS
            sequence=0
            for record in records:
                for frame_kind,data in record_frames(record,maximum=self._wire_limit):
                    value=self._frame(session,sequence,frame_kind,data)
                    self.resources.governor().wait_network(len(pack(value))+4,deadline=deadline)
                    self._credit('out:'+peer,_send(sock,value,MAX_FRAME,deadline=deadline,frame_seconds=BULK_SECONDS if bulk else FRAME_SECONDS))
                    sequence+=1
            self._credit('out:'+peer,_send(sock,self._frame(session,sequence,'END',{'records':len(records)}),MAX_FRAME,deadline=deadline,frame_seconds=BULK_SECONDS if bulk else FRAME_SECONDS))
            self._mark_seen(peer)
            complete=True
        except Exception as error:
            self._error(error,operation,stage,peer,empty_probe=peer is None and stage=='RECEIVE' and first_bytes[0]==0)
        finally:
            if complete:self._transport_success()
            try:sock.close()
            finally:
                with self._lock:self._sockets.discard(sock);self._handlers.discard(threading.current_thread())
                self._slots.release()

    def _error(self,error,operation='',stage='',peer=None,*,reason='',cancel=None,empty_probe=False):
        with self._lock:
            if getattr(error,'_gg_lan_recorded',False):return
            error._gg_lan_recorded=True
            code=_failure_code(error);details=_failure_details(error,operation,stage);stamp=time.time()
            expected=(empty_probe and code=='GG_LAN_EOF') or (self._cancel.is_set() or cancel is not None and cancel.is_set()) and code in {
                'GG_LAN_EOF','GG_LAN_IO_TIMEOUT','GG_LAN_CONNECTION_RESET','GG_LAN_CONNECTION_REFUSED',
                'GG_LAN_BROKEN_PIPE','GG_LAN_IO_FAILED','GG_LAN_READ_DEADLINE','GG_LAN_SEND_DEADLINE',
                'GG_LAN_CIRCLE_DEADLINE','GG_LAN_STOPPED','GG_LAN_CIRCLE_CANCELLED'}
            label=self._roster.get(peer,{}).get('label','') if isinstance(peer,str) else ''
            if (not isinstance(label,str) or not re.fullmatch(r'[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ0-9 _-]{0,63}',label)
                    or re.search(r'[0-9a-f]{16,}|[A-Za-z0-9]{24,}|[0-9a-f]{8}-[0-9a-f]{4}-|secret|password|bearer|api[_ -]?key|token',label,re.I)):label=''
            reason=reason if reason in self._transport_counts['admission_drops'] else ''
            if reason:self._transport_counts['admission_drops'][reason]+=1
            if empty_probe and code=='GG_LAN_EOF':reason='NO_REQUEST'
            self._transport_counts['expected_closures' if expected else 'failures']+=1
            self._transport_history.append({'at':stamp,'operation':details['operation'],'stage':details['stage'],
                'code':code,'peer_label':label,'expected':expected,'reason':reason})
            self._transport_revision+=1
            if not expected:
                self._rejected+=1;self._last_error=code;self._last_error_at=stamp;self._last_error_details=details
                if peer in self._roster:
                    self._peer_failures[peer]={'monotonic':time.monotonic(),'code':code,'at':stamp}

    def _mark_seen(self,peer):
        """Only completed, authenticated exchanges establish recent contact."""
        with self._lock:
            self._seen[peer]=time.time();self._seen_monotonic[peer]=time.monotonic()
            self._peer_exchanges[peer]=self._peer_exchanges.get(peer,0)+1

    def _peer_observations(self):
        now=time.monotonic();rows=[]
        for peer,owner in self._roster.items():
            if peer==self.public_key:continue
            seen=self._seen_monotonic.get(peer)
            age=max(0,now-seen) if seen is not None else None
            failure=self._peer_failures.get(peer,{})
            failed=bool(failure) and (seen is None or failure.get('monotonic',-1)>seen)
            state=('STOPPED' if self._cancel.is_set() else 'EXHAUSTED' if self._transport_exhausted else 'UNOBSERVED' if age is None
                   else 'DISCONNECTED' if age>PEER_OFFLINE_SECONDS else 'STALE' if age>PEER_FRESH_SECONDS
                   else 'DEGRADED' if failed else 'CONNECTED')
            rows.append({'label':owner.get('label','Okänd nod'),'state':state,'last_seen':self._seen.get(peer),
                         'age_seconds':round(age,1) if age is not None else None,
                         'authenticated_recently':age is not None and age<=PEER_FRESH_SECONDS and not self._cancel.is_set() and not self._transport_exhausted,
                         'completed_exchanges':self._peer_exchanges.get(peer,0),
                         'last_error':failure.get('code','') if failed else '',
                         'producer_indices':list(owner.get('producer_indices',()))})
        return rows

    def _producer_identities(self):
        rows=[]
        for peer,owner in self._roster.items():
            for slot,index in enumerate(owner.get('producer_indices',())):
                rows.append({'index':index,'node_label':owner['label'],'local':peer==self.public_key,
                             'node_producer_index':slot,'display_name':owner['label']+' · '+str(slot+1),
                             'identity_basis':'SIGNED_SESSION_ROSTER'})
        return sorted(rows,key=lambda row:row['index'])

    def _token_ledger(self):
        ledger=self._tokens
        if ledger is None:raise ValueError('GG_LAN_TEST_TOKENS_DISABLED')
        if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        return ledger

    def token_snapshot(self):
        ledger=self._tokens
        return ledger.snapshot() if ledger is not None else {'enabled':False,'symbol':test_tokens.ASSET,
            'settlement':'SINGLE_PAIRED_COORDINATOR','accounts':[],'sequence':0,'receipts':[],
            'financial_assets':False,'dag_finality':False}

    def _circle_plan_body(self,signed):
        body=_checked(signed,_CIRCLE,self._trusted)
        fields={'schema','network_id','run_id','ring','amount_atomic','batch','duration_ms','max_transfers','initial_sequence','initial_head'}
        if (not isinstance(body,dict) or set(body)!=fields or body.get('schema')!='gg.lan-test-token.circle.v1'
                or body.get('network_id')!=self._network):raise ValueError('GG_LAN_CIRCLE_DOMAIN')
        _public(body['run_id']);_public(body['initial_head'])
        if not isinstance(body['ring'],list) or len(body['ring'])!=3 or set(body['ring'])!=set(self._roster) or body['ring'][0]!=self._trusted:
            raise ValueError('GG_LAN_CIRCLE_RING')
        _integer(body['batch'],1,test_tokens.MAX_BATCH);_integer(body['duration_ms'],1,60000)
        _integer(body['max_transfers'],1,test_tokens.MAX_TRANSFERS);_integer(body['initial_sequence'],0,test_tokens.MAX_TRANSFERS)
        if test_tokens.amount_atomic(body['amount_atomic'])>int(test_tokens.ALLOCATION_ATOMIC):raise ValueError('GG_LAN_TOKEN_AMOUNT')
        ledger=self._token_ledger()
        if ledger.head_at(body['initial_sequence'])!=body['initial_head']:raise ValueError('GG_LAN_CIRCLE_START_HEAD')
        current=self._token_plan
        if current is not None and current['body']['run_id']==body['run_id']:
            if current['body']!=body:raise ValueError('GG_LAN_CIRCLE_CHANGED')
            if time.monotonic()>=current['deadline']:raise ValueError('GG_LAN_CIRCLE_EXPIRED')
        else:
            if body['run_id'] in self._closed_circle_ids:raise ValueError('GG_LAN_CIRCLE_REPLAY')
            if len(self._closed_circle_ids)>=test_tokens.MAX_TRANSFERS:raise ValueError('GG_LAN_CIRCLE_RUN_LIMIT')
            if current is not None:
                if time.monotonic()<current['deadline']:raise ValueError('GG_LAN_CIRCLE_BUSY')
                self._closed_circle_ids.add(current['body']['run_id'])
            self._token_plan={'body':deepcopy(body),'deadline':time.monotonic()+body['duration_ms']/1000}
        return body

    def _token_command(self,peer,kind,payload):
        ledger=self._token_ledger()
        if not isinstance(payload,dict):raise ValueError('GG_LAN_TOKEN_REQUEST')
        with self._token_operation:
            if kind=='TOKEN_STATUS' and not payload:return ledger.status()
            if kind=='TOKEN_SYNC' and set(payload)=={'after'}:
                return {'records':ledger.records(payload['after']),**ledger.status()}
            if kind=='TOKEN_SUBMIT' and set(payload)=={'transactions'}:
                if self.public_key!=self._trusted:raise ValueError('GG_LAN_TOKEN_COORDINATOR_REQUIRED')
                if self._circle_thread and self._circle_thread.is_alive() and peer!=self.public_key:raise ValueError('GG_LAN_CIRCLE_BUSY')
                receipts=ledger.commit_batch(payload['transactions'])
                return {'receipts':receipts,**ledger.status()}
            if kind=='TOKEN_APPLY' and set(payload)=={'records'}:
                if peer!=self._trusted:raise ValueError('GG_LAN_TOKEN_COORDINATOR_REQUIRED')
                return ledger.apply_receipts(payload['records'])
            if kind=='CIRCLE_SIGN' and set(payload) in ({'plan','records','count'},{'plan','records','count','budget_ms'}):
                if peer!=self._trusted:raise ValueError('GG_LAN_TOKEN_COORDINATOR_REQUIRED')
                epoch=self._circle_epoch
                ledger.apply_receipts(payload['records'])
                plan=self._circle_plan_body(payload['plan']);count=_integer(payload['count'],1,plan['batch'])
                if ledger.status()['committed']-plan['initial_sequence']+count>plan['max_transfers']:raise ValueError('GG_LAN_CIRCLE_BUDGET')
                recipient=plan['ring'][(plan['ring'].index(self.public_key)+1)%3]
                budget=_integer(payload.get('budget_ms',plan['duration_ms']),1,60000)
                signing_deadline=min(self._token_plan['deadline'],time.monotonic()+budget/1000)
                def permitted():
                    if time.monotonic()>=signing_deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
                    if epoch!=self._circle_epoch or self._cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
                transactions=ledger.sign_batch(recipient,plan['amount_atomic'],count,check=permitted)
                if epoch!=self._circle_epoch or self._cancel.is_set():
                    self._closed_circle_ids.add(plan['run_id']);self._token_plan=None
                    raise ValueError('GG_LAN_CIRCLE_CANCELLED')
                return {'transactions':transactions,**ledger.status()}
            if kind=='CIRCLE_END' and set(payload)=={'run_id'}:
                if peer!=self._trusted:raise ValueError('GG_LAN_TOKEN_COORDINATOR_REQUIRED')
                _public(payload['run_id'])
                if self._token_plan is not None and self._token_plan['body']['run_id']==payload['run_id']:
                    self._closed_circle_ids.add(payload['run_id']);self._token_plan=None
                return ledger.status()
        raise ValueError('GG_LAN_TOKEN_REQUEST')

    def _token_rpc(self,peer,kind,payload,*,cancel=None,deadline=None):
        stage='CHECK'
        def permitted():
            if self._cancel.is_set() or cancel is not None and cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
            if deadline is not None and time.monotonic()>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
        try:
            permitted()
            if peer==self.public_key:
                stage='EXECUTE';result=self._dag_stress_command(peer,kind,payload) if kind.startswith('DAG_STRESS_') else self._token_command(peer,kind,payload);permitted();return result
            address=self._roster.get(peer)
            if address is None:raise ValueError('GG_LAN_UNKNOWN_PEER')
            connection_deadline=min(time.monotonic()+CONNECTION_SECONDS,deadline if deadline is not None else float('inf'))
            stage='WAIT';self._pace_connection(peer,kind,cancel=cancel,deadline=connection_deadline)
            permitted()
            stage='CONNECT'
            with self._connection(peer,deadline=connection_deadline,cancel=cancel) as sock:
                stage='AUTH';session=self._client_auth(sock,peer,connection_deadline,check=permitted)
                permitted();stage='SEND'
                self._credit('out:'+peer,_send(sock,self._frame(session,0,kind,payload),MAX_FRAME,deadline=connection_deadline))
                stage='RECEIVE';response,size=self._read(sock,MAX_FRAME,deadline=connection_deadline,check=permitted)
                stage='VALIDATE';permitted();body=self._check_frame(response,size,peer,session,0)
                if body['kind']!='TOKEN_RESULT' or not isinstance(body['payload'],dict):raise ValueError('GG_LAN_TOKEN_RESPONSE')
                result=body['payload']
                if 'error' in result:
                    code=result['error']
                    raise ValueError(code if isinstance(code,str) and re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code) else 'GG_LAN_TOKEN_REQUEST_FAILED')
                permitted()
                self._mark_seen(peer)
                self._transport_success()
                return result
        except Exception as error:
            # Preserve the exception and request outcome; never replay an RPC
            # whose acknowledgement might have been lost after commitment.
            error._gg_lan_details=_failure_details(error,kind,stage)
            self._error(error,kind,stage,peer,cancel=cancel)
            raise

    def _sync_tokens(self,*,cancel=None,deadline=None):
        ledger=self._token_ledger()
        if self.public_key==self._trusted:return ledger.status()
        for _index in range(test_tokens.MAX_TRANSFERS//test_tokens.MAX_BATCH+1):
            current=ledger.status();result=self._token_rpc(self._trusted,'TOKEN_SYNC',{'after':current['committed']},cancel=cancel,deadline=deadline)
            records=result.get('records')
            ledger.apply_receipts(records)
            status=ledger.status()
            if status['committed']==result.get('committed'):
                if status['head']!=result.get('head') or status['state_root']!=result.get('state_root'):raise ValueError('GG_LAN_TOKEN_SYNC_HEAD')
                return status
            if not records:raise ValueError('GG_LAN_TOKEN_SYNC_GAP')
        raise ValueError('GG_LAN_TOKEN_SYNC_LIMIT')

    def token_send(self,recipient_peer_key,amount_atomic):
        with self._token_operation:
            ledger=self._token_ledger()
            if self._circle_thread and self._circle_thread.is_alive() or self._token_plan is not None and time.monotonic()<self._token_plan['deadline']:
                raise ValueError('GG_LAN_CIRCLE_BUSY')
            self._sync_tokens()
            transaction=ledger.sign_batch(recipient_peer_key,amount_atomic)
            self._token_rpc(self._trusted,'TOKEN_SUBMIT',{'transactions':transaction})
            # Another sender may have committed between our initial sync and
            # submit. Fetch the missing ordered prefix rather than applying a
            # possibly non-adjacent acknowledgement directly.
            self._sync_tokens()
            if not all(ledger.has_transaction(value) for value in transaction):raise ValueError('GG_LAN_TOKEN_NOT_ACKNOWLEDGED')
            return self.token_snapshot()

    def _push_token_peer(self,peer,*,cancel=None,leave=0,deadline=None):
        ledger=self._token_ledger()
        if peer==self.public_key:return ledger.status()
        cursor=self._token_peer_cursors.get(peer)
        if cursor is None:
            status=self._token_rpc(peer,'TOKEN_STATUS',{},cancel=cancel,deadline=deadline)
            cursor=_integer(status.get('committed'),0,test_tokens.MAX_TRANSFERS)
            if ledger.head_at(cursor)!=status.get('head'):raise ValueError('GG_LAN_TOKEN_SYNC_HEAD')
            self._token_peer_cursors[peer]=cursor
        target=ledger.status()['committed']
        while target-cursor>leave:
            records=ledger.records(cursor)
            if not records:raise ValueError('GG_LAN_TOKEN_SYNC_GAP')
            status=self._token_rpc(peer,'TOKEN_APPLY',{'records':records},cancel=cancel,deadline=deadline)
            received=_integer(status.get('committed'),cursor+1,test_tokens.MAX_TRANSFERS)
            if ledger.head_at(received)!=status.get('head'):raise ValueError('GG_LAN_TOKEN_SYNC_HEAD')
            cursor=received;self._token_peer_cursors[peer]=cursor
        return {'committed':cursor,'head':ledger.head_at(cursor)}

    def _all_tokens_synced(self,*,cancel=None,deadline=None):
        ledger=self._token_ledger();expected=ledger.status()
        for peer in self._roster:
            if peer==self.public_key:continue
            self._push_token_peer(peer,cancel=cancel,deadline=deadline)
            status=self._token_rpc(peer,'TOKEN_STATUS',{},cancel=cancel,deadline=deadline)
            if status!=expected:raise ValueError('GG_LAN_TOKEN_PEERS_NOT_SYNCED')
        return True

    def start_token_circle(self,duration_ms=10000,batch=8,amount_atomic='1'):
        _integer(duration_ms,1,60000);_integer(batch,1,test_tokens.MAX_BATCH);test_tokens.amount_atomic(amount_atomic)
        if self._transport_exhausted:raise ValueError('GG_LAN_SESSION_EXHAUSTED')
        with self._token_operation:
            ledger=self._token_ledger()
            if self.public_key!=self._trusted:raise ValueError('GG_LAN_TOKEN_COORDINATOR_REQUIRED')
            if self._circle_thread and self._circle_thread.is_alive():raise ValueError('GG_LAN_CIRCLE_BUSY')
            if len(self._closed_circle_ids)>=test_tokens.MAX_TRANSFERS:raise ValueError('GG_LAN_CIRCLE_RUN_LIMIT')
            status=ledger.status();remaining=test_tokens.MAX_TRANSFERS-status['committed']
            if remaining<3*batch:raise ValueError('GG_LAN_TOKEN_RECORD_LIMIT')
            if test_tokens.amount_atomic(amount_atomic)*batch>int(test_tokens.ALLOCATION_ATOMIC):raise ValueError('GG_LAN_TOKEN_AMOUNT')
            self._circle_cancel=threading.Event();self._token_peer_cursors={}
            ring=[self.public_key]+sorted(peer for peer in self._roster if peer!=self.public_key)
            plan={'schema':'gg.lan-test-token.circle.v1','network_id':self._network,'run_id':secrets.token_hex(32),
                'ring':ring,'amount_atomic':amount_atomic,'batch':batch,'duration_ms':duration_ms,
                'max_transfers':remaining,'initial_sequence':status['committed'],'initial_head':status['head']}
            signed=_signed(self._identity,_CIRCLE,plan)
            self._circle={'state':'RUNNING','transactions':0,'completed_rounds':0,'elapsed_ms':0,'tps':0,
                'all_peers_synced':False,'last_error':'','last_error_details':{},'stop_reason':'','duration_ms':duration_ms,'batch':batch,
                'role':'COORDINATOR','scope':'PRIVATE_COORDINATOR_ORDERED_TEST_LEDGER'}
            self._circle_thread=threading.Thread(target=self._circle_loop,args=(signed,self._circle_cancel),name='gg-lan-token-circle',daemon=True)
            self._circle_thread.start()
            return self.snapshot()

    def stop_token_circle(self):
        self._circle_epoch+=1
        plan=self._token_plan
        if plan is not None:
            self._closed_circle_ids.add(plan['body']['run_id']);self._token_plan=None
        self._circle_cancel.set()
        if self._lock.acquire(blocking=False):
            try:sockets=list(self._circle_sockets)
            finally:self._lock.release()
            for sock in sockets:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
        return {'state':'STOPPING' if self._circle_thread and self._circle_thread.is_alive() else self._circle['state']}

    def _circle_loop(self,signed,cancel):
        started=time.monotonic();plan=signed['body'];deadline=started+plan['duration_ms']/1000
        initial=plan['initial_sequence'];ledger=self._tokens;error='';details={};reason='DURATION';state='COMPLETE';synced=False
        def permitted():
            if cancel.is_set() or self._cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
            if time.monotonic()>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
        try:
            self._all_tokens_synced(cancel=cancel,deadline=deadline)
            synced=True
            last_cycle=0.0
            while time.monotonic()<deadline and not cancel.is_set() and not self._cancel.is_set():
                if last_cycle and time.monotonic()+last_cycle*1.25+.05>=deadline:break
                cycle_started=time.monotonic()
                if ledger.status()['committed']+3*plan['batch']>test_tokens.MAX_TRANSFERS:
                    reason='RECORD_LIMIT';break
                for peer in plan['ring']:
                    permitted()
                    if peer!=self.public_key:self._push_token_peer(peer,cancel=cancel,leave=test_tokens.MAX_BATCH,deadline=deadline)
                    cursor=ledger.status()['committed'] if peer==self.public_key else self._token_peer_cursors[peer]
                    records=ledger.records(cursor)
                    permitted()
                    budget=max(1,int((deadline-time.monotonic())*1000))
                    result=self._token_rpc(peer,'CIRCLE_SIGN',{'plan':signed,'records':records,'count':plan['batch'],'budget_ms':budget},cancel=cancel,deadline=deadline)
                    if peer!=self.public_key:
                        received=_integer(result.get('committed'),0,test_tokens.MAX_TRANSFERS)
                        if ledger.head_at(received)!=result.get('head'):raise ValueError('GG_LAN_TOKEN_SYNC_HEAD')
                        self._token_peer_cursors[peer]=received
                    transactions=result.get('transactions')
                    if not isinstance(transactions,list) or len(transactions)!=plan['batch']:raise ValueError('GG_LAN_CIRCLE_BATCH')
                    ledger.commit_batch(transactions,check=permitted);synced=False
                    elapsed=max(.001,time.monotonic()-started)
                    with self._lock:self._circle.update(transactions=ledger.status()['committed']-initial,elapsed_ms=round(elapsed*1000),tps=round((ledger.status()['committed']-initial)/elapsed,3))
                self._all_tokens_synced(cancel=cancel,deadline=deadline);synced=True
                with self._lock:self._circle['completed_rounds']+=plan['batch']
                last_cycle=time.monotonic()-cycle_started
            if cancel.is_set() or self._cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
            if not synced:synced=self._all_tokens_synced(cancel=cancel,deadline=deadline)
            if ledger.status()['committed']==initial:state='NO_TRANSFERS';reason='NO_TRANSFERS'
        except Exception as exception:
            code=str(exception)
            error=_failure_code(exception,'GG_LAN_CIRCLE_FAILED');details=_failure_details(exception)
            if cancel.is_set() or self._cancel.is_set():state='STOPPED';reason='CANCELLED'
            elif time.monotonic()>=deadline or code=='GG_LAN_CIRCLE_DEADLINE':
                with self._lock:rounds=self._circle['completed_rounds']
                complete=synced and ledger.status()['committed']-initial==rounds*3 and rounds>0
                state='COMPLETE' if complete else 'TIME_BUDGET';reason='DURATION'
                error='' if complete else 'GG_LAN_CIRCLE_DEADLINE'
                if complete:details={}
            else:state='ERROR';reason='FAILED'
        finally:
            elapsed=max(.001,time.monotonic()-started);cleanup_started=time.monotonic();cleanup_deadline=cleanup_started+1
            if not self._cancel.is_set():
                for peer in plan['ring']:
                    try:self._token_rpc(peer,'CIRCLE_END',{'run_id':plan['run_id']},deadline=cleanup_deadline)
                    except Exception:pass
            count=ledger.status()['committed']-initial
            with self._lock:self._circle.update(state=state,transactions=count,elapsed_ms=round(elapsed*1000),tps=round(count/elapsed,3),all_peers_synced=synced,last_error=error,last_error_details=details,stop_reason=reason,cleanup_ms=round((time.monotonic()-cleanup_started)*1000))

    def _ingest(self,raw,peer,claimed_hash=None,*,deadline=None):
        if peer not in self._roster or peer==self.public_key:raise ValueError('GG_LAN_UNKNOWN_PEER')
        if not isinstance(raw,bytes) or not 1<=len(raw)<=self._wire_limit:raise ValueError('GG_LAN_WIRE_SIZE')
        # Only exact bytes already admitted may bypass inspection.
        if isinstance(claimed_hash,str) and _HEX.fullmatch(claimed_hash):
            existing=self._engine.public_proposal(claimed_hash)
            if existing is not None and existing==raw:return 'DUPLICATE'
        if self._wire_limit>MAX_WIRE:
            with self.resources.governor().reserve_memory(len(raw)*16):
                result=self._ingest_new(raw,peer,claimed_hash,deadline)
        else:result=self._ingest_new(raw,peer,claimed_hash,deadline)
        if result=='ADMITTED_UNFINALIZED':self._drain_orphans()
        return result

    def _ingest_new(self,raw,peer,claimed_hash,deadline):
        info=self._engine.inspect_empty_proposal(raw);identifier=info['hash']
        if claimed_hash is not None and claimed_hash!=identifier:raise ValueError('GG_LAN_PROPOSAL_HASH')
        existing=self._engine.public_proposal(identifier)
        if existing is not None:
            if existing!=raw:raise ValueError('GG_LAN_PROPOSAL_CHANGED')
            return 'DUPLICATE'
        missing=[parent for parent in info['parents'] if not self._engine.has_proposal(parent)]
        if missing:
            with self._lock:
                if identifier in self._orphans:
                    if self._orphans[identifier]['wire']!=raw:raise ValueError('GG_LAN_PROPOSAL_CHANGED')
                    return 'PENDING_PARENTS'
                if len(self._orphans)>=MAX_ORPHANS or self._orphan_bytes+len(raw)>self._orphan_limit:
                    self._sync_gap=True;raise ValueError('GG_LAN_ORPHAN_CREDIT')
                self._orphans[identifier]={'wire':raw,'peer':peer,'parents':info['parents'],'created':time.monotonic()}
                self._orphan_bytes+=len(raw)
            return 'PENDING_PARENTS'
        if self._wire_limit>MAX_WIRE:
            self._engine.admit_relayed(raw,self._roster[peer]['credit_index'],check=lambda:self._resource_check(deadline))
        else:self._engine.admit_relayed(raw,self._roster[peer]['credit_index'])
        self._engine.reconcile()
        return 'ADMITTED_UNFINALIZED'

    def _drain_orphans(self):
        # Bounded by count32 and at most8 admissions per call; no hidden queue.
        for _index in range(8):
            selected=None
            with self._lock:
                for identifier,item in list(self._orphans.items()):
                    if time.monotonic()-item['created']>ORPHAN_SECONDS:
                        self._orphan_bytes-=len(item['wire']);del self._orphans[identifier];self._sync_gap=True
                    elif all(self._engine.has_proposal(parent) for parent in item['parents']):
                        selected=(identifier,item);break
                if selected:
                    identifier,item=selected;del self._orphans[identifier];self._orphan_bytes-=len(item['wire'])
            if selected is None:break
            try:
                if self._wire_limit>MAX_WIRE:
                    with self.resources.governor().reserve_memory(len(item['wire'])*16):
                        self._engine.admit_relayed(item['wire'],self._roster[item['peer']]['credit_index'],check=self._resource_check)
                else:self._engine.admit_relayed(item['wire'],self._roster[item['peer']]['credit_index'])
                self._engine.reconcile()
            except ValueError as error:
                # A now-checkable orphan may have a false rank or reused
                # producer sequence. Reject it without undoing its real parent.
                self._error(error)

    def _pull(self,peer,kind,payload):
        stage='WAIT';bulk=self._wire_limit>MAX_WIRE
        deadline=time.monotonic()+(BULK_SECONDS if bulk else CONNECTION_SECONDS)
        assembler=RecordAssembler(maximum=self._wire_limit);memory=ExitStack();completed=0
        try:
            self._pace_connection(peer,kind,deadline=deadline)
            stage='CONNECT'
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            with self._connection(peer,deadline=deadline,bulk=bulk) as sock:
                control_deadline=min(deadline,time.monotonic()+CONNECTION_SECONDS)
                stage='AUTH';session=self._client_auth(sock,peer,control_deadline)
                stage='SEND';_send(sock,self._frame(session,0,kind,payload),MAX_FRAME,deadline=control_deadline)
                maximum_frames=8*((self._wire_limit+CHUNK_BYTES-1)//CHUNK_BYTES+2)+1 if bulk else 9
                for sequence in range(maximum_frames):
                    stage='RECEIVE';response,size=self._read(sock,MAX_FRAME,deadline=deadline,bulk=bulk)
                    stage='VALIDATE';frame=self._check_frame(response,size,peer,session,sequence)
                    if frame['kind']=='END':
                        if assembler.pending or frame['payload']!={'records':completed}:raise ValueError('GG_LAN_PAGE_END')
                        self._mark_seen(peer)
                        self._transport_success();return completed
                    data=frame['payload']
                    if frame['kind']=='DATA_START':
                        # Validate the announced size before reserving memory;
                        # assembler allocates only as bounded chunks arrive.
                        assembler.feed(frame['kind'],data)
                        memory.enter_context(self.resources.governor().reserve_memory(data['size']*2))
                        continue
                    record=assembler.feed(frame['kind'],data)
                    if record is None:continue
                    memory.close();completed+=1
                    if completed>8:raise ValueError('GG_LAN_PAGE_LIMIT')
                    cursor=_integer(record['admission_index'],1 if kind=='PAGE' else 0,4095)
                    stage='EXECUTE';self._ingest(record['wire'],peer,record['hash'],deadline=deadline)
                    if kind=='PAGE':
                        with self._lock:
                            if cursor<=self._cursors[peer]:raise ValueError('GG_LAN_PAGE_CURSOR')
                            self._cursors[peer]=cursor
                raise ValueError('GG_LAN_PAGE_LIMIT')
        except Exception as error:
            error._gg_lan_details=_failure_details(error,kind,stage)
            self._error(error,kind,stage,peer);raise
        finally:
            assembler.close();memory.close()

    def _gossip_loop(self):
        # A stalled peer must not stop the other peer's actual block exchange.
        # The signed roster is fixed for this session: exactly two owned lanes.
        workers=[threading.Thread(target=self._gossip_peer_loop,args=(peer,),
                    name='gg-lan-peer-'+str(index),daemon=True)
                 for index,peer in enumerate(tuple(self._cursors)[:MAX_PEERS-1])]
        for worker in workers:worker.start()
        for worker in workers:worker.join()

    def _gossip_peer_loop(self,peer):
        while not self._cancel.wait(.1):
            with self._lock:
                if self._transport_exhausted:return
            if self._resources_paused():continue
            try:
                active=self._gossip_active()
                with self._lock:
                    health=self._gossip_health.get(peer,{})
                    next_poll=health.get('next',0)
                    if active and health.get('errors',0):
                        next_poll=min(next_poll,health.get('at',next_poll)+1.0)
                    if time.monotonic()<next_poll and (not active or health.get('errors',0)):continue
                    missing=[]
                    for item in self._orphans.values():
                        for identifier in item['parents']:
                            if not self._engine.has_proposal(identifier) and identifier not in missing:missing.append(identifier)
                    missing=missing[:8];cursor=self._cursors[peer]
                received=self._pull(peer,'GET',{'hashes':missing}) if missing else 0
                received=(received or 0)+(self._pull(peer,'PAGE',{'after':cursor}) or 0);self._drain_orphans()
                self._gossip_result(peer,progress=received>0,active=active)
            except Exception as error:
                self._error(error);self._gossip_result(peer,error=True,active=self._gossip_active())
            if self._tokens is not None and peer==self._trusted and time.monotonic()-self._last_token_sync>=1:
                self._last_token_sync=time.monotonic()
                try:
                    with self._token_operation:self._sync_tokens()
                except Exception as error:self._error(error)

    def snapshot(self):
        with self._lock:
            engine=self._engine;ledger=self._tokens;circle=dict(self._circle);participant_plan=self._token_plan
            peers=self._peer_observations();identities=self._producer_identities()
            contact=('STOPPED' if self._cancel.is_set() else 'EXHAUSTED' if self._transport_exhausted else 'PAIRING' if not engine
                     else 'CONNECTED' if peers and all(row['state']=='CONNECTED' for row in peers)
                     else 'DEGRADED' if any(row['state'] in ('CONNECTED','DEGRADED','STALE') for row in peers)
                     else 'DISCONNECTED')
            network={'state':'STOPPED' if self._cancel.is_set() else 'EXHAUSTED' if self._transport_exhausted else 'READY' if engine else 'PAIRING',
                'scope':'PRIVATE_LAN_SESSION_EXPERIMENT','label':self.label,'endpoint':{'host':self.host,'port':self.port},
                'allowed_cidr':str(self.allowed),'public_key':self.public_key,'trusted_coordinator':self._trusted,'auto_produce':self.auto_produce,
                'network_id':self._network,'producer_count':6 if engine else 0,'local_producer_indices':list(self._local_indices),
                'candidate_invite_count':len(self._candidates),'configured_peers':len(self._roster),'authenticated_peers':[{'label':self._roster[peer]['label'],'last_seen':stamp,
                    'endpoint':{'host':self._roster[peer]['host'],'port':self._roster[peer]['port']},'producer_indices':self._roster[peer]['producer_indices']}
                    for peer,stamp in self._seen.items() if peer in self._roster and peer in self._seen_monotonic
                    and time.monotonic()-self._seen_monotonic[peer]<=PEER_FRESH_SECONDS and not self._cancel.is_set() and not self._transport_exhausted],
                'connection_state':contact,'peer_status':peers,'producer_identities':identities,
                'network_kind':'PRIVATE_LAN','peer_fresh_seconds':PEER_FRESH_SECONDS,
                'authenticated_exchanges':sum(self._peer_exchanges.values()),
                'physical_hosts_verified':False,'transactions_enabled':self._dag_enabled,'traffic_confidentiality':False,
                'allow_test_tokens':self.allow_test_tokens,'test_tokens_enabled':ledger is not None,'allow_dag_transactions':self.allow_dag_transactions,
                'orphan_count':len(self._orphans),'orphan_bytes':self._orphan_bytes,'sync_gap':self._sync_gap,
                'traffic_bytes':self._raw_received,'traffic_bytes_basis':'APPLICATION_TCP_READ_BYTES',
                'charged_transport_bytes':self._total_bytes,'rejected_frames':self._rejected,'last_error':self._last_error,'last_error_at':self._last_error_at,'last_error_details':dict(self._last_error_details),
                'transport':{'state':'STOPPED' if self._cancel.is_set() else 'EXHAUSTED' if self._transport_exhausted else 'ACTIVE',
                    'exhausted_reason':self._transport_exhausted,'connections_admitted':self._connections_admitted,
                    'active_handlers':len(self._handlers),'counters':deepcopy(self._transport_counts),'history':deepcopy(list(self._transport_history))},
                'limits':{'frame_bytes':MAX_FRAME,'public_bundle_bytes':MAX_BUNDLE,'orphan_count':MAX_ORPHANS,'orphan_bytes':self._orphan_limit,
                    'candidate_invites':MAX_PEERS-1,'frame_deadline_seconds':FRAME_SECONDS,'connection_deadline_seconds':CONNECTION_SECONDS,
                    'raw_received_bytes':self._total_bytes_limit,'peer_bytes':self._peer_bytes_limit,
                    'block_wire_bytes':self._wire_limit,'bulk_deadline_seconds':BULK_SECONDS,
                    'connections_per_second':32,'session_connections':MAX_REQUESTS,'frames_per_direction':self._frame_limit}}
        body=engine.snapshot() if engine else {'state':'STOPPED','mode':'LOCAL_PARALLEL_PROPOSAL_DAG','producer_count':0,'worker_count':0,
            'canonical_finalized':0,'block_graph':{'topology':'MULTIPARENT_DAG','producer_count':0,'blocks':[],'edges':[]}}
        body['lan']=network
        body['test_tokens']=ledger.snapshot() if ledger else self.token_snapshot()
        if ledger is not None and self.public_key!=self._trusted and participant_plan is not None:
            expired=time.monotonic()>=participant_plan['deadline']
            circle={'state':'EXPIRED' if expired else 'RUNNING','role':'PARTICIPANT',
                'transactions':max(0,ledger.revision()-participant_plan['body']['initial_sequence']),
                'counts_basis':'OBSERVED_RECEIPTS_SINCE_PLAN_START','last_error':'','last_error_details':{},
                'stop_reason':'DURATION' if expired else '',
                'scope':'PRIVATE_COORDINATOR_ORDERED_TEST_LEDGER'}
        body['token_circle']=circle
        body['dag_stress']=self._dag_stress_snapshot()
        body['dag_resources']=self.resources.snapshot(body['dag_stress']['transactions_per_block'] or None)
        if engine and self._dag_enabled:
            worker_count=body['dag_stress']['worker_count'];body['worker_count']=worker_count
            body['live'].update(mode='LAN_DAG_FINITE_STRESS',state='RUNNING' if worker_count else 'PAUSED',enabled=bool(worker_count),
                active_workers=worker_count,local_worker_count=worker_count,local_producer_indices=list(self._local_indices),
                interval_ms=body['dag_stress']['interval_ms'],cadence_origin='LOCAL_CONFIGURED_STRESS_WORKER',
                target_proposal_bps=len(self._local_indices)*1000/body['dag_stress']['interval_ms'] if body['dag_stress']['interval_ms'] else None,
                blocks=len(self._local_indices),transactions_per_block=body['dag_stress']['transactions_per_block'])
        if engine:
            graph=body['block_graph'];graph['source']='LAN_SIGNED_PROPOSAL_DAG'
            graph['producer_identities']=deepcopy(identities)
            owners={row['index']:row for row in identities}
            if self._dag_enabled:
                body['test_accounts']=engine.lan_test_accounts()
                for account in body['test_accounts']:
                    owner=owners.get(account['producer_index'])
                    if owner:account.update(node_label=owner['node_label'],local=owner['local'],display_name=owner['display_name'])
            for producer in body.get('producers',[]):
                owner=owners.get(producer['index'])
                if owner:producer.update(owner)
            for block in graph.get('blocks',[]):
                owner=owners.get(block.get('proposer_index'))
                if owner and block.get('state')!='GENESIS':
                    block.update(producer_name=owner['display_name'],node_label=owner['node_label'],local_producer=owner['local'])
            network['verified_dag_blocks']=body.get('blocks_admitted',0)
            network['verified_dag_transactions']=body.get('transactions_validated',0)
        return body

    def telemetry_revision(self):
        """Constant-size identity check before copying the public DAG tail."""
        with self._lock:
            engine=self._engine;ledger=self._tokens;participant_plan=self._token_plan
            revision=(self._network,self._cancel.is_set(),self._rejected,self._transport_revision,len(self._orphans),self._orphan_bytes,
                self._raw_received,self._total_bytes,self._sync_gap,len(self._candidates),tuple(sorted(self._seen.items())),
                self._circle['state'],self._circle['transactions'],self._circle['completed_rounds'],self._circle_epoch,
                participant_plan['body']['run_id'] if participant_plan is not None else '',int(time.monotonic()))
        return revision+(('TOKEN',ledger.revision()) if ledger else ('NO_TOKENS',))+(engine.telemetry_revision() if engine else ('UNPAIRED',))

    def request_stop(self):
        """Signal work and close owned IO without waiting for a service lock."""
        self._cancel.set()
        self._circle_cancel.set()
        self._dag_cancel.set()
        self.resources.test.stop()
        engine=self._engine
        if engine:engine.request_stop()
        listener=self._listener
        if listener:
            try:listener.close()
            except OSError:pass
        if self._lock.acquire(blocking=False):
            try:sockets=list(self._sockets)
            finally:self._lock.release()
            for sock in sockets:
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                try:sock.close()
                except OSError:pass

    def stop(self):
        self.request_stop()
        if not self.resources.test.join(2):raise ValueError('GG_DAG_HARDWARE_STOP_TIMEOUT')
        # Wait for any in-progress install/start to observe the lifetime cancel
        # before capturing the final engine. Do not join handlers under this
        # configuration lock: an accepted install handler may itself need it.
        with self._configuration:
            with self._lock:
                engine=self._engine;listener=self._listener;sockets=list(self._sockets)
        if engine:engine.request_stop()
        if listener:
            try:listener.close()
            except OSError:pass
        for sock in sockets:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            try:sock.close()
            except OSError:pass
        for worker in (self._acceptor,self._gossip,self._circle_thread,self._dag_worker,self._dag_controller):
            if worker and worker is not threading.current_thread():worker.join(2)
        with self._lock:handlers=list(self._handlers)
        for worker in handlers:
            if worker is not threading.current_thread():worker.join(2)
        if any(worker and worker.is_alive() for worker in (self._acceptor,self._gossip,self._circle_thread,self._dag_worker,self._dag_controller,*handlers)):raise ValueError('GG_LAN_STOP_TIMEOUT')
        # The historical result remains in _dag_stress. Disable live evidence
        # reads before clearing the engine/signers; stopped status never creates
        # a fresh proof or tries to reconcile a cleared ledger.
        with self._lock:self._dag_enabled=False
        if engine:engine.stop()
        if self._tokens:self._tokens.clear()
        with self._lock:
            self._identity=None;self._local_keys.clear();self._orphans.clear();self._candidates.clear();self._orphan_bytes=0;self._listener=None
        return self.snapshot()
