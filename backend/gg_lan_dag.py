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
import hashlib
import ipaddress
import json
import math
import os
import re
import secrets
import select
import socket
import struct
import threading
import time

from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag, make_public_genesis, pack, digest, _verify, HOT_PAYLOAD_BYTES
from backend import gg_lan_test_tokens as test_tokens
from backend.gg_dag_hardware import ResourceController
from backend.gg_lan_admission import RefillBudget
from backend.gg_dag_wire import record_frames, RecordAssembler, MAX_BLOCK_WIRE_BYTES, CHUNK_BYTES
from backend.gg_lan_resume import GetResumeCache, resume_hints, local_error as local_get_error
from backend import gg_lossless_wire as lossless

MAX_FRAME=64*1024
MAX_BUNDLE=256*1024
MAX_INVITE=16*1024
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
MAX_GET_BUFFER_BYTES=MAX_BLOCK_WIRE_BYTES


def dag_stress_capabilities():
    """Read-only constants: importing or querying creates no key/socket/work."""
    return {'supported':True,'limits':dict(DAG_STRESS_LIMITS)}


def dag_production_capabilities():
    return {'supported':True,'scope':'BOUNDED_LOCAL_OWNED_PRODUCTION',
        'limits':{**DAG_STRESS_LIMITS,'scope':'LOCAL_WORK_NOT_REPLICA_BARRIER'}}


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
        'DAG_STRESS_PREPARE','DAG_STRESS_BEGIN','DAG_STRESS_STOP','DAG_STRESS_STATUS','HARDWARE_PROBE','SEGMENTED_SUBMIT','OBSERVER_ADMIT'}
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
    if body.get('schema')=='gg.lan-dag.invite.v6':
        if (set(body)!=fields|{'allow_test_tokens','allow_dag_transactions','node_role'} or body['node_role']!='light'
                or body['allow_test_tokens'] is not False or body['allow_dag_transactions'] is not True):raise ValueError('GG_LAN_INVITE')
    elif body.get('schema')=='gg.lan-dag.invite.v5':
        if (not isinstance(body.get('peer_key'),str) or not _HEX.fullmatch(body['peer_key'])
                or not isinstance(body.get('producer_keys'),list) or len(body['producer_keys'])!=2
                or any(not isinstance(key,str) or not _HEX.fullmatch(key) for key in body['producer_keys'])):
            raise ValueError('GG_LAN_CONSENSUS_INVITES')
        if (set(body)!=fields|{'allow_test_tokens','allow_dag_transactions','node_role','consensus_invites'}
                or body.get('node_role') not in ('producer','replica') or body.get('allow_dag_transactions') is not True
                or body.get('allow_test_tokens') is not False or not isinstance(body['consensus_invites'],list)
                or not 1<=len(body['consensus_invites'])<=4):raise ValueError('GG_LAN_INVITE')
        from backend.gg_consensus_membership import validate_invite as check_member
        members=[check_member(invite) for invite in body['consensus_invites']]
        keys=[row[name] for row in members for name in ('validator_key','node_key','account_key')]
        if (len(set(keys))!=len(keys) or any(row['owner_peer_key']!=body['peer_key'] or row['host']!=body['host']
                or row['p2p_port']==body['port'] for row in members)
                or len({row['p2p_port'] for row in members})!=len(members)
                or set(keys)&set([body['peer_key'],*body['producer_keys']])):raise ValueError('GG_LAN_CONSENSUS_INVITES')
    elif body.get('schema')=='gg.lan-dag.invite.v4':
        if (set(body)!=fields|{'allow_test_tokens','allow_dag_transactions','node_role'}
                or body.get('node_role') not in ('producer','replica')
                or any(type(body.get(key)) is not bool for key in ('allow_test_tokens','allow_dag_transactions'))
                or body['node_role']=='replica' and body['allow_test_tokens']):raise ValueError('GG_LAN_INVITE')
    elif body.get('schema')=='gg.lan-dag.invite.v3':
        if set(body)!=fields|{'allow_test_tokens','allow_dag_transactions'} or body.get('allow_dag_transactions') is not True or type(body.get('allow_test_tokens')) is not bool:raise ValueError('GG_LAN_INVITE')
    elif body.get('schema')=='gg.lan-dag.invite.v2':
        if set(body)!=fields|{'allow_test_tokens'} or body.get('allow_test_tokens') is not True:raise ValueError('GG_LAN_INVITE')
    elif body.get('schema')!='gg.lan-dag.invite.v1' or set(body)!=fields:raise ValueError('GG_LAN_INVITE')
    _public(body['peer_key']);_public(body['nonce']);_label(body['label']);_endpoint(body['host'],body['port'])
    producers=body['producer_keys']
    if (not isinstance(producers,list) or len(producers)!=PRODUCERS_PER_PEER
            or any(not isinstance(value,str) or not _HEX.fullmatch(value) for value in producers)
            or len(set(producers))!=PRODUCERS_PER_PEER or body['peer_key'] in producers):raise ValueError('GG_LAN_PRODUCERS')
    from backend.gg_ed25519 import require_public_key
    try:
        for public in producers:require_public_key(bytes.fromhex(public))
    except (ValueError,TypeError):raise ValueError('GG_LAN_PRODUCERS') from None
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


def _consensus_invite_upgrade(previous,current):
    """Permit append-only public validator ads before roster approval.

    Endpoint, owner, producer identities, nonce and participation policy remain
    immutable. A replay cannot downgrade or remove an already advertised key.
    Both complete invitations are separately signature-validated by callers.
    """
    old=previous['body'];new=current['body']
    if old['schema'] not in ('gg.lan-dag.invite.v3','gg.lan-dag.invite.v4','gg.lan-dag.invite.v5') or new['schema']!='gg.lan-dag.invite.v5':return False
    fields=('label','host','port','peer_key','producer_keys','nonce')
    if any(old[key]!=new[key] for key in fields):return False
    if any(old.get(key,False)!=new.get(key,False) for key in ('allow_test_tokens','allow_dag_transactions')):return False
    if old.get('node_role','producer')!=new.get('node_role','producer'):return False
    before=old.get('consensus_invites',[]);after=new['consensus_invites']
    return len(after)>=len(before) and after[:len(before)]==before


class LanDagPeer:
    def __init__(self,label,bind_host='127.0.0.1',port=0,trusted_coordinator=None,auto_produce=False,*,allowed_cidr=None,allow_test_tokens=False,allow_dag_transactions=False,node_profile=None,node_role='producer'):
        from backend.gg_ed25519 import verification_backend
        verification_backend()  # Fail before key creation or any listener.
        self.label=_label(label);self.host,self.port=_endpoint(bind_host,port,allow_zero=True)
        self.allowed=ipaddress.ip_network(allowed_cidr or ('127.0.0.0/8' if self.host.startswith('127.') else self.host+'/24'),strict=False)
        if self.allowed.version!=4 or ipaddress.ip_address(self.host) not in self.allowed or not any(self.allowed.subnet_of(block) for block in _PRIVATE):raise ValueError('GG_LAN_SUBNET')
        if type(auto_produce) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(allow_test_tokens) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(allow_dag_transactions) is not bool:raise ValueError('GG_LAN_OPTION')
        if node_role not in ('producer','replica','light'):raise ValueError('GG_LAN_NODE_ROLE')
        if node_role!='producer' and (auto_produce or allow_test_tokens):raise ValueError('GG_LAN_REPLICA_READ_ONLY')
        if node_role=='light' and not allow_dag_transactions:raise ValueError('GG_LAN_LIGHT_REQUIRES_DAG_CONSENSUS')
        self.node_role=node_role
        self.allow_test_tokens=allow_test_tokens
        self.allow_dag_transactions=allow_dag_transactions;self._dag_enabled=False
        self._profile=node_profile;self._recovering_engine=None
        if node_profile is not None:
            from backend.gg_node_store import NodeProfile
            if not isinstance(node_profile,NodeProfile):raise ValueError('GG_NODE_PROFILE_REQUIRED')
            if node_profile._meta.get('protocol_producer') is not None:raise ValueError('GG_PROTOCOL_PROFILE_USE_PROTOCOL_RUNTIME')
            self._identity,self._local_keys=node_profile.signers()
        else:self._identity=Keypair();self._local_keys=[Keypair() for _ in range(PRODUCERS_PER_PEER)]
        self.public_key=self._identity.pubkey().hex()
        self._trusted=_public(trusted_coordinator) if trusted_coordinator is not None else self.public_key
        self.auto_produce=auto_produce;self._pair_nonce=node_profile.descriptor()['pair_nonce'] if node_profile is not None else secrets.token_hex(32)
        if node_profile is not None:
            descriptor=node_profile.descriptor()
            if descriptor.get('node_role','producer')!=self.node_role:raise ValueError('GG_NODE_PROFILE_CONFIGURATION')
            if any(descriptor[key]!=value for key,value in {'label':self.label,'host':self.host,'port':self.port,
                    'allowed_cidr':str(self.allowed),'trusted_coordinator':self._trusted,'allow_test_tokens':self.allow_test_tokens,
                    'allow_dag_transactions':self.allow_dag_transactions}.items()):raise ValueError('GG_NODE_PROFILE_CONFIGURATION')
        self._lock=threading.RLock();self._configuration=threading.RLock();self._cancel=threading.Event()
        self._listener=None;self._acceptor=None;self._gossip=None;self._engine=None;self._invite=None
        self._network='';self._bundle=None;self._roster={};self._local_indices=[];self._cursors={};self._scan_cursors={}
        self._canonical_recovery_lock=threading.Lock()
        self._get_resumes=GetResumeCache()
        self._consensus_invites=self._profile.descriptor().get('validator_invites',[]) if self._profile is not None else []
        self._proof_factory=None;self._proof_service=None
        self._observer_admissions=None
        self._handlers=set();self._sockets=set();self._slots=threading.BoundedSemaphore(4)
        self._socket_cancels={}
        self._socket_peers={};self._active_addresses={}
        self._orphans=OrderedDict();self._orphan_bytes=0;self._sync_gap=False
        self._deferred_after={};self._orphan_after={}
        self._traffic={};self._total_bytes=0;self._rejected=0;self._last_error='';self._last_error_at=0.0;self._last_error_details={};self._seen={}
        self._seen_monotonic={};self._peer_failures={};self._peer_exchanges={};self._peer_sync={}
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
        self._node_cancel=threading.Event();self._node_worker=None;self._node_plan=None
        if self._profile is not None:
            used=self._profile.used_controls()
            self._dag_closed.update(used['dag']);self._closed_circle_ids.update(used['circle'])
        self._work_mode='STRESS'
        self._node_state={'state':'IDLE','duration_ms':0,'transactions_per_block':0,'interval_ms':1000,
            'elapsed_ms':0,'production':None,'last_error':'','stop_reason':''}
        self._dag_stress={'state':'IDLE','duration_ms':0,'transactions_per_block':0,'interval_ms':100,
            'elapsed_ms':0,'blocks':0,'transactions':0,'all_peers_synced':False,
            'acknowledged_blocks':None,'acknowledged_transactions':None,'acknowledged_bps':None,'acknowledged_tps':None,
            'stop_reason':'','last_error':'','participants':[],'production':None}
        self._wire_limit=MAX_WIRE;self._orphan_limit=MAX_ORPHAN_BYTES
        self._peer_bytes_limit=MAX_PEER_BYTES;self._total_bytes_limit=MAX_TOTAL_BYTES;self._frame_limit=MAX_REQUESTS
        self._raw_auth_budget=RefillBudget(MAX_PEER_BYTES,MAX_REQUESTS,maximum_actors=MAX_PEERS)
        self._raw_anon_budget=RefillBudget(MAX_BUNDLE*4,MAX_REQUESTS,maximum_actors=64)
        self._raw_anon_total=RefillBudget(MAX_TOTAL_BYTES,MAX_REQUESTS,maximum_actors=1)
        self._frame_budget=RefillBudget(MAX_PEER_BYTES,MAX_REQUESTS,maximum_actors=MAX_PEERS*2)
        self._accept_budget=RefillBudget(1,32,maximum_actors=64)
        self._accept_total=RefillBudget(1,128,maximum_actors=1)
        self.resources=ResourceController(cancel=self._cancel,
            stored_bytes=lambda: 3*(((self._engine or self._recovering_engine).memory_basis_bytes() if self._engine or self._recovering_engine else 0)+self._orphan_bytes))

    def _large_capacity(self,engine=None):
        if self._wire_limit>MAX_WIRE:return
        governor=self.resources.governor();headroom=governor.memory_headroom()
        if headroom is None:raise ValueError('GG_DAG_RESOURCE_NEEDS_MEMORY_MEASUREMENT')
        wire=min(MAX_BLOCK_WIRE_BYTES,int(headroom)//16)
        if wire<=MAX_WIRE:raise ValueError('GG_DAG_RESOURCE_MEMORY')
        session=min(512*1024*1024,int(headroom)//8)
        (engine or self._engine).configure_lan_capacity(block_bytes=wire,session_bytes=max(wire,session))
        self._wire_limit=wire;self._orphan_limit=min(64*1024*1024,int(headroom)//8)
        # Raise finite byte/frame credits only for an explicitly requested
        # large-block experiment. Existing consumption is retained.
        self._peer_bytes_limit=1024*1024*1024;self._total_bytes_limit=2*1024*1024*1024;self._frame_limit=131072
        self._raw_auth_budget.set_limits(self._peer_bytes_limit,self._frame_limit)
        self._frame_budget.set_limits(self._peer_bytes_limit,self._frame_limit)

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
        with self._dag_control:
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
        with self._configuration:
            # Recovery precedes listeners, public invites and signer exposure.
            if self._profile is not None and self._engine is None and self._profile.session() is not None:
                self.install_session(self._profile.session(),_start_gossip=False)
            invite=self._start_pairing_listener()
            if self._bundle is not None and self._bundle['body']['schema'] in ('gg.lan-dag.session.v5','gg.lan-dag.session.v6','gg.lan-dag.session.v7') and self._proof_service is not None:
                self._proof_service.start()
            return invite

    def _start_pairing_listener(self):
        with self._lock:
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self._listener:return self.public_invite()
            listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            try:
                # Linux keeps closed accepted connections in TIME_WAIT. Reopen
                # this stopped endpoint without permitting concurrent listeners.
                # Windows REUSEADDR has different ownership semantics; leave it off.
                if os.name!='nt':listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                listener.bind((self.host,self.port));listener.listen(4);listener.settimeout(.1)
            except Exception:listener.close();raise
            self.port=listener.getsockname()[1]
            try:
                if self._profile is not None:self._profile.configure_pairing(port=self.port)
            except BaseException:listener.close();raise
            self._listener=listener
            body={'schema':'gg.lan-dag.invite.v1','label':self.label,'host':self.host,'port':self.port,
                'peer_key':self.public_key,'producer_keys':[key.pubkey().hex() for key in self._local_keys],'nonce':self._pair_nonce}
            if self.allow_test_tokens:body.update(schema='gg.lan-dag.invite.v2',allow_test_tokens=True)
            if self.allow_dag_transactions:body.update(schema='gg.lan-dag.invite.v3',allow_test_tokens=self.allow_test_tokens,allow_dag_transactions=True)
            if self.node_role=='replica':body.update(schema='gg.lan-dag.invite.v4',node_role=self.node_role,
                allow_test_tokens=False,allow_dag_transactions=self.allow_dag_transactions)
            if self.node_role=='light':body.update(schema='gg.lan-dag.invite.v6',node_role='light',allow_test_tokens=False,allow_dag_transactions=True)
            if self._consensus_invites:
                body.update(schema='gg.lan-dag.invite.v5',node_role=self.node_role,allow_test_tokens=False,
                    allow_dag_transactions=True,consensus_invites=deepcopy(self._consensus_invites))
            self._invite=_signed(self._identity,_INVITE,body)
            self._acceptor=threading.Thread(target=self._accept,name='gg-lan-accept',daemon=True);self._acceptor.start()
            self._start_gossip()
            return self.public_invite()

    def _start_gossip(self):
        if self.node_role=='light':return
        with self._lock:
            if self._engine is not None and self._listener is not None and self._gossip is None and not self._cancel.is_set():
                self._gossip=threading.Thread(target=self._gossip_loop,name='gg-lan-gossip',daemon=True);self._gossip.start()

    def public_invite(self):
        with self._lock:
            if self._invite is None:raise ValueError('GG_LAN_PAIRING_REQUIRED')
            return deepcopy(self._invite)

    def advertise_consensus_invites(self,invites):
        with self._configuration,self._lock:
            if self._engine is not None:raise ValueError('GG_LAN_CONSENSUS_ALREADY_BOUND')
            if self._invite is None or self._cancel.is_set():raise ValueError('GG_LAN_PAIRING_REQUIRED')
            if self.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
            if not self.allow_dag_transactions or self.allow_test_tokens:raise ValueError('GG_LAN_CONSENSUS_REQUIRES_DAG_MODE')
            body=deepcopy(self._invite['body'])
            body.update(schema='gg.lan-dag.invite.v5',node_role=self.node_role,allow_test_tokens=False,
                allow_dag_transactions=True,consensus_invites=deepcopy(invites))
            signed=_signed(self._identity,_INVITE,body);validate_invite(signed)
            if not _consensus_invite_upgrade(self._invite,signed):raise ValueError('GG_LAN_CONSENSUS_INVITE_REPLACEMENT')
            if self._profile is not None:self._profile.save_validator_invites(invites)
            self._consensus_invites=deepcopy(invites);self._invite=signed
            return deepcopy(signed)

    def pin_coordinator(self,public_key):
        with self._configuration:
            with self._lock:
                if self._engine is not None or self._bundle is not None or self._cancel.is_set():raise ValueError('GG_LAN_TRUST_ALREADY_BOUND')
                if self._profile is not None:self._profile.configure_pairing(trusted_coordinator=_public(public_key))
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
            if existing is not None and existing!=invite and not _consensus_invite_upgrade(existing,invite):raise ValueError('GG_LAN_CANDIDATE_CHANGED')
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

    def create_session(self,invites,label='GG LAN',*,enable_test_tokens=False,enable_dag_transactions=False,consensus_invites=None,enable_segmented=False,enable_financial=False,financial_accounts=None):
        if type(enable_test_tokens) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(enable_segmented) is not bool:raise ValueError('GG_LAN_OPTION')
        if type(enable_financial) is not bool:raise ValueError('GG_LAN_OPTION')
        if financial_accounts is not None and not enable_financial:raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
        if enable_financial and (enable_segmented or not enable_dag_transactions or enable_test_tokens or consensus_invites is None):raise ValueError('GG_LAN_FINANCIAL_REQUIRES_DAG_CONSENSUS')
        if enable_segmented and (not enable_dag_transactions or enable_test_tokens or consensus_invites is None):raise ValueError('GG_LAN_SEGMENTED_REQUIRES_DAG_CONSENSUS')
        if type(enable_dag_transactions) is not bool or enable_dag_transactions and enable_test_tokens:raise ValueError('GG_LAN_OPTION')
        if consensus_invites is not None and not enable_dag_transactions:raise ValueError('GG_LAN_CONSENSUS_REQUIRES_DAG_MODE')
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
        if enable_financial:
            from backend.gg_consensus_membership import make_membership
            from backend.gg_financial_session import make_bundle
            owners={row['peer_key']:row for row in checked}
            membership=make_membership(consensus_invites,owners=owners,forbidden_keys=[*producer_keys,*keys])
            if financial_accounts is not None:
                from backend.gg_financial_dag import GENERAL_SOURCE_SCHEMA
                return make_bundle(self._identity,invites,membership,label=label,network_nonce=secrets.token_hex(32),source_schema=GENERAL_SOURCE_SCHEMA,financial_accounts=financial_accounts)
            return make_bundle(self._identity,invites,membership,label=label,network_nonce=secrets.token_hex(32))
        body={'schema':'gg.lan-dag.session.v1','label':_label(label),'coordinator':self.public_key,
            'roster':roster,'public_genesis':make_public_genesis(public,enable_dag_transactions=enable_dag_transactions),'transactions_enabled':False}
        if enable_test_tokens:
            if not all(row.get('allow_test_tokens') is True for row in checked):raise ValueError('GG_LAN_TOKEN_ALL_PEERS_OPT_IN_REQUIRED')
            body.update(schema='gg.lan-dag.session.v2',test_tokens=test_tokens.genesis(checked,self.public_key))
        if enable_dag_transactions:
            if not all(row.get('allow_dag_transactions') is True for row in checked):raise ValueError('GG_LAN_DAG_ALL_PEERS_OPT_IN_REQUIRED')
            body.update(schema='gg.lan-dag.session.v3',transactions_enabled=True,dag_test_mode='PRODUCER_OWNED_NONFINANCIAL')
        if consensus_invites is not None:
            from backend.gg_consensus_membership import make_membership
            owners={row['peer_key']:row for row in checked}
            body.update(schema='gg.lan-dag.session.v4',consensus=make_membership(consensus_invites,
                owners=owners,forbidden_keys=[*producer_keys,*keys]))
            if enable_segmented:
                from backend.gg_dag_segmented_session import make_bundle
                return make_bundle(self._identity,invites,body['consensus'],label=label,network_nonce=secrets.token_hex(32))
        if any(row.get('node_role')=='light' for row in checked) and consensus_invites is None:raise ValueError('GG_LAN_LIGHT_REQUIRES_DAG_CONSENSUS')
        bundle=_signed(self._identity,_BUNDLE,body)
        if len(pack(bundle))>MAX_BUNDLE:raise ValueError('GG_LAN_BUNDLE_SIZE')
        return bundle

    def install_session(self,bundle,*,_start_gossip=True):
        if len(pack(bundle))>MAX_BUNDLE:raise ValueError('GG_LAN_BUNDLE_SIZE')
        with self._configuration:
            body=_checked(bundle,_BUNDLE,self._trusted)
            if isinstance(body,dict) and body.get('schema') in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
                from backend.gg_financial_proof_sync import install
                return install(self,bundle,start=_start_gossip)
            if isinstance(body,dict) and body.get('schema')=='gg.lan-dag.session.v5':
                from backend.gg_segmented_proof_sync import install
                return install(self,bundle,start=_start_gossip)
            expected={'schema','label','coordinator','roster','public_genesis','transactions_enabled'}
            enabled=isinstance(body,dict) and body.get('schema')=='gg.lan-dag.session.v2'
            dag_enabled=isinstance(body,dict) and body.get('schema') in ('gg.lan-dag.session.v3','gg.lan-dag.session.v4')
            anchored=isinstance(body,dict) and body.get('schema')=='gg.lan-dag.session.v4'
            if self.node_role=='light' and not anchored:raise ValueError('GG_LAN_LIGHT_REQUIRES_DAG_CONSENSUS')
            if enabled:expected.add('test_tokens')
            if dag_enabled:expected.add('dag_test_mode')
            if anchored:expected.add('consensus')
            if (not isinstance(body,dict) or set(body)!=expected
                    or body.get('schema') not in ('gg.lan-dag.session.v1','gg.lan-dag.session.v2','gg.lan-dag.session.v3','gg.lan-dag.session.v4') or body.get('coordinator')!=self._trusted
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
            if (own is None or own['nonce']!=self._pair_nonce or own['producer_keys']!=[key.pubkey().hex() for key in self._local_keys]
                    or own.get('node_role','producer')!=self.node_role or (own['host'],own['port'])!=(self.host,self.port)):raise ValueError('GG_LAN_OWN_IDENTITY')
            network=digest(body,b'GG-LAN-DAG-NETWORK-v1\0')
            if anchored:
                from backend.gg_consensus_membership import anchor_from_bundle
                anchor=anchor_from_bundle(bundle,self._trusted)
                if anchor['genesis']['dag']['network_id']!=network:raise ValueError('GG_LAN_CONSENSUS_ANCHOR')
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
            if any(row.get('node_role','producer')!='producer' for row in peers.values()):
                engine.configure_lan_roles([index for row in peers.values() if row.get('node_role','producer')=='producer' for index in row['producer_indices']])
            cursors={key:0 for key in peers if key!=self.public_key}
            if self._profile is not None:
                self._recovering_engine=engine
                try:
                    # Persistent DAG sessions use a measured finite memory
                    # envelope; resource checks also count the replaying engine.
                    if dag_enabled:self._large_capacity(engine)
                    engine.configure_owned_ingress()
                    if dag_enabled:
                        headroom=self.resources.governor().memory_headroom()
                        if headroom is None:raise ValueError('GG_DAG_RESOURCE_NEEDS_MEMORY_MEASUREMENT')
                        engine.configure_payload_archive(self._profile.read_dag,hot_bytes=min(HOT_PAYLOAD_BYTES,max(0,int(headroom)//64)))
                    engine.begin_history_replay()
                    for kind,raw in self._profile.records():
                        self._resource_check()
                        if kind=='dag':engine.admit_relayed(raw,own['credit_index'],check=self._resource_check)
                        elif ledger is not None:ledger.apply_receipts([json.loads(raw)])
                        else:raise ValueError('GG_NODE_STORE_UNEXPECTED_TOKEN_HISTORY')
                    engine.finish_history_replay(self._profile.fault())
                    self._profile.bind_session(bundle)
                    saved_cursors=self._profile.cursors()
                    if set(saved_cursors)-set(cursors):raise ValueError('GG_NODE_STORE_CURSOR_PEER')
                    cursors.update(saved_cursors)
                    self._profile.resolve_peer_scans()
                    cursors.update(self._profile.cursors())
                    engine.attach_durable_journal(lambda raw:self._profile.append('dag',[raw]),self._profile.latch_fault)
                    if ledger is not None:ledger.attach_durable_journal(lambda rows:self._profile.append('token',rows))
                except BaseException:
                    engine.stop()
                    if ledger is not None:ledger.clear()
                    raise
                finally:self._recovering_engine=None
            if self.node_role=='producer':engine.attach_local_producers(dict(zip(own['producer_indices'],self._local_keys)))
            with self._lock:
                if self._cancel.is_set():
                    engine.stop();raise ValueError('GG_LAN_STOPPED')
                self._engine=engine;self._network=network;self._bundle=deepcopy(bundle);self._roster=peers
                self._consensus_invites=deepcopy(own.get('consensus_invites',[]))
                self._tokens=ledger;self._dag_enabled=dag_enabled
                self._local_indices=list(own['producer_indices']) if self.node_role=='producer' else [];self._cursors=cursors
                self._scan_cursors=dict(cursors)
                if self._profile is not None:
                    for key,value in self._profile.scan_progress().items():self._scan_cursors[key]=value['position']
                if _start_gossip:self._start_gossip()
            if anchored and self._proof_factory is not None and self._proof_service is None:
                self._proof_service=self._proof_factory(self)
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
        if self.node_role!='producer':raise ValueError('GG_LAN_REPLICA_READ_ONLY')
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

    def _sync_work_busy(self):
        plan=self._dag_plan
        return bool(any(worker and worker.is_alive() for worker in (self._dag_worker,self._dag_controller))
            or plan is not None and time.monotonic()<plan['deadline'] and plan['body']['run_id'] not in self._dag_closed)

    def start_dag_production(self,duration_ms=60000,transactions_per_block=1,interval_ms=1000):
        if self._bundle is not None and self._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):raise ValueError('GG_FINANCIAL_ACCOUNT_SIGNED_PAYMENTS_REQUIRED')
        if self._bundle is not None and self._bundle['body']['schema']=='gg.lan-dag.session.v5':
            return self._proof_service.production.start(duration_ms,transactions_per_block,interval_ms)
        """Local owner's finite work only: no RPC, peer baseline or peer vote."""
        if self.node_role!='producer':raise ValueError('GG_LAN_REPLICA_READ_ONLY')
        _integer(duration_ms,1000,600000);_integer(transactions_per_block,1,DAG_STRESS_MAX_TX);_integer(interval_ms,0,60000)
        with self._dag_control:
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if self._engine is None or not self._dag_enabled or not self.allow_dag_transactions:
                raise ValueError('GG_LAN_DAG_TRANSACTIONS_DISABLED')
            if self._transport_exhausted:raise ValueError('GG_LAN_SESSION_EXHAUSTED')
            if self._sync_work_busy() or self._node_worker and self._node_worker.is_alive():raise ValueError('GG_LAN_DAG_PRODUCTION_BUSY')
            if self.resources.test.snapshot()['state']=='RUNNING':raise ValueError('GG_DAG_HARDWARE_ACTIVE_WORK')
            if self._engine.snapshot()['live']['enabled']:raise ValueError('GG_LAN_DAG_UNRELATED_PRODUCER_ACTIVE')
            if self._engine._lan_fault:raise ValueError(self._engine._lan_fault)
            if transactions_per_block>64 or any(value<100 for value in self.resources.budget.public().values()):self._large_capacity()
            self._preflight_resources(transactions_per_block)
            now=time.monotonic();cancel=threading.Event()
            plan={'started':now,'deadline':now+duration_ms/1000,'duration_ms':duration_ms,
                'transactions_per_block':transactions_per_block,'interval_ms':interval_ms}
            with self._lock:
                self._node_cancel=cancel;self._node_plan=plan
                self._work_mode='OWN'
                self._node_state={'state':'RUNNING','duration_ms':duration_ms,'transactions_per_block':transactions_per_block,
                    'interval_ms':interval_ms,'elapsed_ms':0,
                    'production':self._dag_public_production({'state':'RUNNING','blocks':0,'transactions':0,'elapsed_ms':0}),
                    'last_error':'','stop_reason':''}
                self._node_worker=threading.Thread(target=self._node_produce_loop,args=(plan,cancel),name='gg-lan-owned-producer',daemon=True)
                self._node_worker.start()
            return self._node_snapshot()

    def stop_dag_production(self):
        if self._bundle is not None and self._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):return self._proof_service.stop_production()
        if self._bundle is not None and self._bundle['body']['schema']=='gg.lan-dag.session.v5':
            return self._proof_service.production.stop()
        # Signal before the control lock so cancellation cannot wait for a start.
        self._node_cancel.set()
        with self._dag_control:
            worker=self._node_worker
            with self._lock:
                if worker and worker.is_alive():self._node_state['state']='STOPPING'
            if worker and worker is not threading.current_thread():worker.join(.25)
            return self._node_snapshot()

    def _node_produce_loop(self,plan,cancel):
        blocks=0;transactions=0;state='COMPLETE';reason='DURATION';error=''
        started=time.monotonic()
        with self._lock:plan['worker_started']=started
        def permitted():
            if cancel.is_set() or self._cancel.is_set():raise ValueError('GG_LAN_NODE_CANCELLED')
            if time.monotonic()>=plan['deadline']:raise ValueError('GG_LAN_NODE_DEADLINE')
            if self._transport_exhausted:raise ValueError('GG_LAN_SESSION_EXHAUSTED')
            self._resource_check(plan['deadline'],permitted_without_resources)
        def permitted_without_resources():
            if cancel.is_set() or self._cancel.is_set():raise ValueError('GG_LAN_NODE_CANCELLED')
            if time.monotonic()>=plan['deadline']:raise ValueError('GG_LAN_NODE_DEADLINE')
        try:
            with self._engine._lock:
                for index in self._local_indices:self._engine._producer_stats[index]['configured_interval_ms']=plan['interval_ms']
            cadence=plan['interval_ms']/1000;due=started
            while time.monotonic()<plan['deadline']:
                if cancel.wait(max(0,min(due,plan['deadline'])-time.monotonic())):break
                produced=False
                for producer in self._local_indices:
                    permitted()
                    if self._engine.producer_availability(producer) in ('GG_DAG_PRODUCER_QUARANTINED','GG_DAG_CANONICAL_PARENT_PENDING'):continue
                    estimate=self._engine.preflight_lan_test_block(plan['transactions_per_block'],self._wire_limit)
                    with self.resources.governor().reserve_memory(estimate*16):
                        block=self._engine.produce_lan_test_block(producer,plan['transactions_per_block'],self._wire_limit,check=permitted)
                    blocks+=1;transactions+=block['transactions']
                    produced=True
                    with self._lock:
                        self._node_state['production']=self._dag_public_production({'state':'RUNNING','blocks':blocks,
                            'transactions':transactions,'elapsed_ms':(time.monotonic()-started)*1000})
                due=max(due+cadence,time.monotonic())
                if not produced:cancel.wait(min(.1,max(0,plan['deadline']-time.monotonic())))
        except Exception as exception:
            code=str(exception)
            if code in ('GG_LAN_NODE_CANCELLED','GG_LAN_NODE_DEADLINE','GG_DAG_RESOURCE_DEADLINE'):pass
            else:
                limited=code in {'GG_LAN_SESSION_EXHAUSTED','GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_RECORD_LIMIT','GG_DAG_STORAGE_LIMIT','GG_DAG_LAN_WIRE_PROFILE_LIMIT'}
                state='LIMIT_REACHED' if limited else 'ERROR';reason='SOFTWARE_PROFILE_LIMIT' if limited else 'FAILED'
                error=_failure_code(exception,'GG_LAN_NODE_PRODUCTION_FAILED')
        finally:
            if state=='COMPLETE' and (cancel.is_set() or self._cancel.is_set()):state='STOPPED';reason='CANCELLED'
            elapsed=(time.monotonic()-started)*1000
            with self._lock:
                if self._node_plan is plan:
                    self._node_state.update(state=state,stop_reason=reason,last_error=error,elapsed_ms=round(elapsed,3),
                        production=self._dag_public_production({'state':state,'blocks':blocks,'transactions':transactions,'elapsed_ms':elapsed}))

    def _node_snapshot(self):
        with self._lock:
            state=deepcopy(self._node_state);busy=bool(self._node_worker and self._node_worker.is_alive())
            if busy and state['state'] in ('RUNNING','STOPPING') and self._node_plan:
                state['elapsed_ms']=round((time.monotonic()-self._node_plan.get('worker_started',self._node_plan['started']))*1000,3)
                if state['production'] and state['production']['state']=='RUNNING':
                    state['production']=self._dag_public_production({**state['production'],'elapsed_ms':state['elapsed_ms']})
            enabled=bool(self.node_role=='producer' and self._dag_enabled and self._engine and not self._cancel.is_set())
            return {**dag_production_capabilities(),**state,'enabled':enabled,'worker_active':busy,'worker_count':int(busy),'selected':self._work_mode=='OWN',
                'can_start':bool(enabled and not busy and not self._sync_work_busy() and not self._transport_exhausted
                    and not self._engine._lan_fault and not self._engine._live.get('enabled') and self.resources.test.snapshot()['state']!='RUNNING'),
                'counts_basis':'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY'}

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
                if self.node_role!='producer':raise ValueError('GG_LAN_REPLICA_READ_ONLY')
                if self._node_worker and self._node_worker.is_alive():raise ValueError('GG_LAN_DAG_PRODUCTION_BUSY')
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
                if self._profile is not None:self._profile.claim_control('dag',body['run_id'])
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
                    self._work_mode='STRESS'
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
        if self.node_role!='producer':raise ValueError('GG_LAN_REPLICA_READ_ONLY')
        if any(row.get('node_role','producer')!='producer' for row in self._roster.values()):raise ValueError('GG_LAN_STRESS_PRODUCER_ROSTER_REQUIRED')
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
            participants=[{'label':row.get('label','Peer'),'local':peer==self.public_key,'opted_in':row.get('allow_dag_transactions') is True,
                'producer_enabled':row.get('node_role','producer')=='producer'} for peer,row in self._roster.items()]
            busy=bool(self._dag_controller and self._dag_controller.is_alive() or self._dag_worker and self._dag_worker.is_alive()
                or self._node_worker and self._node_worker.is_alive())
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
            'can_start':bool(self.node_role=='producer' and self._dag_enabled and self.public_key==self._trusted and len(participants)==3 and all(row['opted_in'] and row['producer_enabled'] for row in participants)
                and not self._transport_exhausted and not busy and not active and engine is not None and not engine.snapshot()['live']['enabled'] and not engine._lan_fault),
            'participants':state['participants'] or participants,'counts_basis':'LOCAL_DAG_ADMISSION_NOT_FINALITY',
            'measurement_scope':'THREE_REPLICA_SYNC_TEST_NOT_NETWORK_CAPACITY'}

    def _credit(self,peer,size):
        with self._lock:
            if self._profile is not None and peer not in self._roster and not (isinstance(peer,str) and peer.startswith('out:') and peer[4:] in self._roster):peer='unconfigured'
            value=self._traffic.setdefault(peer,{'bytes':0,'frames':0})
            value['bytes']+=size;value['frames']+=1;self._total_bytes+=size
            if self._profile is not None:
                if peer!='unconfigured' and not self._frame_budget.take(peer,size if peer.startswith('out:') else 0):raise ValueError('GG_LAN_PEER_CREDIT')
                return
            if value['bytes']>self._peer_bytes_limit or self._total_bytes>self._total_bytes_limit:
                self._exhaust_transport('BYTES');raise ValueError('GG_LAN_CREDIT')
            if value['frames']>self._frame_limit:
                self._exhaust_transport('FRAMES');raise ValueError('GG_LAN_CREDIT')

    def _account_received(self,size,sock=None):
        # Charge raw reads even when JSON, signatures or announced sizes fail.
        with self._lock:
            self._raw_received+=size
            if self._profile is not None:
                peer=self._socket_peers.get(sock,'anon:unknown')
                if peer in self._roster:
                    allowed=self._raw_auth_budget.take(peer,size,0)
                else:
                    allowed=self._raw_anon_total.take('anonymous',size,0) and self._raw_anon_budget.take(peer,size,0)
                if not allowed:raise ValueError('GG_LAN_PEER_CREDIT')
                return
            if self._raw_received>self._total_bytes_limit:
                self._exhaust_transport('BYTES');raise ValueError('GG_LAN_CREDIT')

    def _account_codec_raw(self,peer,size):
        # Encoded reads/writes retain their original credits. Compression also
        # spends RAW byte credits before bounded encode/decode work begins.
        if type(size) is not int or not 0<size<=CHUNK_BYTES:raise ValueError('GG_WIRE_CODEC_RAW_SIZE')
        with self._lock:
            outgoing=peer.startswith('out:');identity=peer[4:] if outgoing else peer
            if identity not in self._roster:raise ValueError('GG_LAN_UNKNOWN_PEER')
            if self._profile is not None:
                budget=self._frame_budget if outgoing else self._raw_auth_budget
                if not budget.take(peer if outgoing else identity,size,0):raise ValueError('GG_LAN_PEER_CREDIT')
            else:
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
                or any(worker is not None and worker.is_alive() for worker in (self._dag_worker,self._dag_controller,self._node_worker))
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
                check();self._sockets.add(sock);self._socket_peers[sock]=peer
                if cancel is not None:self._socket_cancels[sock]=cancel
                if cancel is self._circle_cancel:self._circle_sockets.add(sock)
            try:
                if self._profile is not None:sock.bind((self.host,0))
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
            with self._lock:
                self._sockets.discard(sock);self._circle_sockets.discard(sock);self._socket_peers.pop(sock,None);self._socket_cancels.pop(sock,None)
            sock.close()

    def cancel_operation(self,cancel):
        """Cancel only sockets registered to this exact owned operation."""
        if not isinstance(cancel,threading.Event):raise ValueError('GG_LAN_OWNED_CANCEL_EVENT')
        cancel.set()
        with self._lock:sockets=tuple(sock for sock,event in self._socket_cancels.items() if event is cancel)
        for sock in sockets:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            try:sock.close()
            except OSError:pass

    def _read(self,sock,limit,*,deadline=None,check=None,bulk=False,on_bytes=None):
        def permitted():
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            cancel=self._socket_cancels.get(sock)
            if cancel is not None and cancel.is_set():raise ValueError('GG_LAN_OPERATION_CANCELLED')
            if check is not None:check()
        def account(size):
            self._account_received(size,sock)
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
                if self._profile is not None:
                    known_addresses={row['host'] for row in self._roster.values()}
                    allowed_address=ipaddress.ip_address(address[0]) in self.allowed and (not self._roster or address[0] in known_addresses)
                    reason=('SESSION' if self._transport_exhausted else 'RATE' if not allowed_address or not self._accept_budget.take(address[0],0)
                        or not self._accept_total.take('all',0) else 'HANDLERS' if self._active_addresses.get(address[0],0)>=2 else '')
                else:
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
            with self._lock:
                self._sockets.add(connection);self._socket_peers[connection]='anon:'+address[0]
                self._active_addresses[address[0]]=self._active_addresses.get(address[0],0)+1
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
        with self._lock:self._socket_peers[sock]=peer
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
        operation='INCOMING';stage='RECEIVE';peer=None;complete=False;first_bytes=[0];memory=ExitStack()
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
            wire_codec=None;response_base=0
            if body['kind']==lossless.PROBE:
                if not getattr(self,'_lossless_wire',True):raise ValueError('GG_LAN_REQUEST')
                selected=lossless.select(body['payload'])
                self._credit('out:'+peer,_send(sock,self._frame(session,0,lossless.ACK,selected),MAX_FRAME,deadline=deadline))
                request,size=self._read(sock,MAX_FRAME,deadline=deadline)
                body=self._check_frame(request,size,peer,session,1);operation=body['kind']
                if body['kind'] not in ('PAGE','GET','SEGMENTED_SUBMIT','ACCOUNT_PAYMENT_RELAY'):raise ValueError('GG_WIRE_CODEC_OPERATION')
                wire_codec=lossless.selection(selected);response_base=1
            payload=body['payload'];records=[]
            if body['kind']=='OBSERVER_ADMIT':
                if (not isinstance(payload,dict) or set(payload)!={'grant'} or len(pack(payload))>4096):
                    raise ValueError('GG_OBSERVER_ADMISSION_REQUEST')
                inbox=self._observer_admissions
                if inbox is None:raise ValueError('GG_OBSERVER_ADMISSION_UNAVAILABLE')
                result=inbox.offer(peer,payload['grant'])
                self._credit('out:'+peer,_send(sock,self._frame(session,0,'OBSERVER_ADMIT_ACK',result),MAX_FRAME,deadline=deadline))
                self._mark_seen(peer);complete=True;return
            if body['kind']=='CONSENSUS_PROOF':
                if self._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
                    from backend.gg_financial_proof_sync import validate_request
                elif self._bundle['body']['schema']=='gg.lan-dag.session.v5':
                    from backend.gg_segmented_proof_sync import validate_request
                else:
                    from backend.gg_dag_proof_sync import validate_request
                validate_request(payload)
                result=self._proof_service.reply(payload) if self._proof_service is not None else {'state':'WAIT'}
                raw=pack(result)
                if len(raw)>256*1024:raise ValueError('GG_LAN_PROOF_LIMIT')
                record={'hash':hashlib.sha256(raw).hexdigest(),'wire':raw,'admission_index':0};sequence=0
                for kind,data in record_frames(record,maximum=256*1024):
                    self._credit('out:'+peer,_send(sock,self._frame(session,sequence,kind,data),MAX_FRAME,deadline=deadline));sequence+=1
                self._credit('out:'+peer,_send(sock,self._frame(session,sequence,'END',{'records':1}),MAX_FRAME,deadline=deadline))
                self._mark_seen(peer);complete=True;return
            if body['kind']=='SEGMENTED_SUBMIT':
                if self._bundle['body']['schema'] not in ('gg.lan-dag.session.v5','gg.lan-dag.session.v6','gg.lan-dag.session.v7') or self._proof_service is None:raise ValueError('GG_LAN_SEGMENTED_SESSION_REQUIRED')
                self._proof_service.submissions.receive(sock,peer,session,payload,codec=wire_codec,sequence_base=response_base);complete=True;return
            if body['kind']=='ACCOUNT_PAYMENT_RELAY':
                if self._bundle['body']['schema']!='gg.lan-dag.session.v7' or self._proof_service is None:
                    raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
                self._proof_service.account_relay.receive(sock,peer,session,payload,codec=wire_codec,sequence_base=response_base);complete=True;return
            if body['kind']=='ACCOUNT_RELAY_STATUS':
                if self._bundle['body']['schema']!='gg.lan-dag.session.v7' or self._proof_service is None:
                    raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
                result=self._proof_service.account_relay.reply_status(payload)
                self._credit('out:'+peer,_send(sock,self._frame(session,0,'ACCOUNT_RELAY_STATUS_ACK',result),MAX_FRAME,deadline=deadline))
                self._mark_seen(peer);complete=True;return
            if self.node_role=='light' and body['kind'] in ('PAGE','GET'):raise ValueError('GG_LAN_LIGHT_PAYLOAD_DISABLED')
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
            wire_limit=MAX_WIRE;remote_tip=0;next_wire=0
            if isinstance(payload,dict) and 'wire_limit' in payload:
                wire_limit=min(self._wire_limit,_integer(payload['wire_limit'],1,MAX_BLOCK_WIRE_BYTES))
            if body['kind']=='PAGE' and isinstance(payload,dict) and set(payload) in ({'after'},{'after','wire_limit'}):
                page_result=self._engine.public_proposals(payload['after'],8,
                    _reserve=lambda size:memory.enter_context(self.resources.governor().reserve_memory(size*2)))
                page=page_result['records'];remote_tip=page_result['tip']
                page_bytes=0
                for record in page:
                    if len(record['wire'])>wire_limit:
                        next_wire=len(record['wire']);break
                    # Pack medium blocks together; a blanket one-record page
                    # makes authentication/polling the artificial bottleneck.
                    if records and page_bytes+len(record['wire'])>2*1024*1024:break
                    records.append(record);page_bytes+=len(record['wire'])
            elif body['kind']=='GET' and isinstance(payload,dict) and set(payload) in ({'hashes'},{'hashes','wire_limit'},{'hashes','wire_limit','resume'}):
                hashes=payload['hashes']
                if not isinstance(hashes,list) or not 1<=len(hashes)<=8 or any(not isinstance(value,str) or not _HEX.fullmatch(value) for value in hashes) or len(set(hashes))!=len(hashes):raise ValueError('GG_LAN_GET')
                resumes=resume_hints(payload.get('resume',[]),hashes,wire_limit)
                page_bytes=0
                for identifier in hashes:
                    size=self._engine.proposal_wire_size(identifier)
                    if size is not None and (size>wire_limit or records and page_bytes+size>2*1024*1024):continue
                    if size is not None:memory.enter_context(self.resources.governor().reserve_memory(size*2))
                    raw=self._relay_proposal(identifier)
                    if raw and len(raw)<=wire_limit:
                        hint=resumes.get(identifier);offset=0
                        if hint and hint['size']==len(raw) and hint['wire_sha256']==hashlib.sha256(raw).hexdigest():offset=hint['offset']
                        records.append({'hash':identifier,'wire':raw,'admission_index':0,'resume_offset':offset});page_bytes+=len(raw)
                missing=[identifier for identifier in hashes if not self._engine.has_proposal(identifier)]
                request=getattr(self._proof_service,'request_payloads',None)
                if missing and callable(request):request(peer,missing)
            else:raise ValueError('GG_LAN_REQUEST')
            if self._resources_paused():records=[]
            stage='SEND'
            bulk=wire_limit>MAX_WIRE
            if bulk:deadline=time.monotonic()+BULK_SECONDS
            sequence=response_base;next_send=time.monotonic()
            for record in records:
                for frame_kind,data in record_frames(record,maximum=wire_limit,resume_offset=record.get('resume_offset',0),
                        codec=wire_codec,check=lambda: self._codec_check(deadline),deadline=deadline,
                        charge=lambda size:self._account_codec_raw('out:'+peer,size),
                        workspace=lambda:self.resources.governor().reserve_memory(lossless.WORKSPACE_BYTES)):
                    value=self._frame(session,sequence,frame_kind,data)
                    cost=len(pack(value))+4
                    if wire_codec is not None and frame_kind=='DATA_PART':cost+=data['raw_size']
                    self.resources.governor().wait_network(cost,deadline=deadline)
                    if wire_codec is not None:
                        while time.monotonic()<next_send:
                            self._codec_check(deadline);self._cancel.wait(min(.05,max(0,next_send-time.monotonic())))
                    self._credit('out:'+peer,_send(sock,value,MAX_FRAME,deadline=deadline,frame_seconds=BULK_SECONDS if bulk else FRAME_SECONDS))
                    if wire_codec is not None:next_send=max(next_send,time.monotonic())+cost/(4*1024*1024)
                    sequence+=1
            end={'records':len(records)}
            if 'wire_limit' in payload and body['kind']=='PAGE':end.update(tip=remote_tip,next_wire_bytes=next_wire)
            self._credit('out:'+peer,_send(sock,self._frame(session,sequence,'END',end),MAX_FRAME,deadline=deadline,frame_seconds=BULK_SECONDS if bulk else FRAME_SECONDS))
            self._mark_seen(peer)
            complete=True
        except Exception as error:
            self._error(error,operation,stage,peer,empty_probe=peer is None and stage=='RECEIVE' and first_bytes[0]==0)
        finally:
            if complete:self._transport_success()
            try:memory.close();sock.close()
            finally:
                with self._lock:
                    self._sockets.discard(sock);self._handlers.discard(threading.current_thread());self._socket_peers.pop(sock,None)
                    count=self._active_addresses.get(address,0)-1
                    if count>0:self._active_addresses[address]=count
                    else:self._active_addresses.pop(address,None)
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
            rows.append({'label':owner.get('label','Okänd nod'),'state':state,'last_seen':self._seen.get(peer),'node_role':owner.get('node_role','producer'),
                         'age_seconds':round(age,1) if age is not None else None,
                         'authenticated_recently':age is not None and age<=PEER_FRESH_SECONDS and not self._cancel.is_set() and not self._transport_exhausted,
                         'completed_exchanges':self._peer_exchanges.get(peer,0),
                         'sync':deepcopy(self._peer_sync.get(peer,{'state':'UNOBSERVED'})),
                         'last_error':failure.get('code','') if failed else '',
                         'producer_indices':list(owner.get('producer_indices',()))})
        return rows

    def _producer_identities(self):
        rows=[]
        for peer,owner in self._roster.items():
            for slot,index in enumerate(owner.get('producer_indices',())):
                rows.append({'index':index,'node_label':owner['label'],'local':peer==self.public_key,
                             'node_role':owner.get('node_role','producer'),'producer_enabled':owner.get('node_role','producer')=='producer',
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
            if self._profile is not None:self._profile.claim_control('circle',body['run_id'])
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

    def public_consensus_proof(self,peer,payload,*,cancel=None):
        if self._bundle is not None and self._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
            from backend.gg_financial_proof_sync import validate_request
        elif self._bundle is not None and self._bundle['body']['schema']=='gg.lan-dag.session.v5':
            from backend.gg_segmented_proof_sync import validate_request
        else:
            from backend.gg_dag_proof_sync import validate_request
        validate_request(payload);deadline=time.monotonic()+CONNECTION_SECONDS
        self._pace_connection(peer,'CONSENSUS_PROOF',cancel=cancel,deadline=deadline)
        assembler=RecordAssembler(maximum=256*1024);result=None
        try:
            with self._connection(peer,deadline=deadline,cancel=cancel) as sock:
                session=self._client_auth(sock,peer,deadline)
                self._credit('out:'+peer,_send(sock,self._frame(session,0,'CONSENSUS_PROOF',payload),MAX_FRAME,deadline=deadline))
                for sequence in range(12):
                    if self._cancel.is_set() or cancel is not None and cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                    response,size=self._read(sock,MAX_FRAME,deadline=deadline)
                    body=self._check_frame(response,size,peer,session,sequence)
                    if body['kind']=='END':
                        if body['payload']!={'records':1} or assembler.pending or result is None:raise ValueError('GG_LAN_PROOF_INCOMPLETE')
                        self._mark_seen(peer);return result
                    record=assembler.feed(body['kind'],body['payload'])
                    if record is not None:
                        raw=record['wire']
                        if result is not None or record['admission_index']!=0 or hashlib.sha256(raw).hexdigest()!=record['hash']:raise ValueError('GG_LAN_PROOF_INTEGRITY')
                        result=json.loads(raw)
                        if pack(result)!=raw or not isinstance(result,dict):raise ValueError('GG_LAN_PROOF_ENCODING')
                raise ValueError('GG_LAN_PROOF_FRAME_LIMIT')
        finally:assembler.close()

    def native_observer_admit(self,peer,grant,*,cancel=None):
        """Explicit public capability request on an authenticated owner channel."""
        from backend.gg_consensus_membership import anchor_from_bundle
        from backend.gg_native_observer import validate_grant
        from backend.gg_observer_enrollment import validate_ack
        if len(pack({'grant':grant}))>4096:raise ValueError('GG_OBSERVER_ADMISSION_REQUEST')
        anchor=anchor_from_bundle(self._bundle,self._trusted)
        checked=validate_grant(grant,self._bundle,self._trusted)
        if checked['owner_peer_key']!=self.public_key:raise ValueError('GG_OBSERVER_ADMISSION_AUTH_OWNER')
        if peer not in {row['body']['owner_peer_key'] for row in anchor['genesis']['membership']['validators']}:
            raise ValueError('GG_OBSERVER_ADMISSION_TARGET')
        if self._cancel.is_set() or cancel is not None and cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        if peer==self.public_key:
            if self._observer_admissions is None:raise ValueError('GG_OBSERVER_ADMISSION_UNAVAILABLE')
            return validate_ack(self._observer_admissions.offer(self.public_key,grant),grant,anchor,peer)
        deadline=time.monotonic()+CONNECTION_SECONDS
        self._pace_connection(peer,'OBSERVER_ADMIT',cancel=cancel,deadline=deadline)
        with self._connection(peer,deadline=deadline,cancel=cancel) as sock:
            session=self._client_auth(sock,peer,deadline)
            self._credit('out:'+peer,_send(sock,self._frame(session,0,'OBSERVER_ADMIT',{'grant':grant}),MAX_FRAME,deadline=deadline))
            response,size=self._read(sock,MAX_FRAME,deadline=deadline)
            body=self._check_frame(response,size,peer,session,0)
            if body['kind']!='OBSERVER_ADMIT_ACK':raise ValueError('GG_OBSERVER_ADMISSION_ACK_INVALID')
            result=validate_ack(body['payload'],grant,anchor,peer);self._mark_seen(peer);return result

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
        if self._profile is not None and result in ('ADMITTED_UNFINALIZED','DUPLICATE'):self._resolve_scan_progress()
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
                owned=[item for item in self._orphans.values() if item['peer']==peer]
                peer_full=self._profile is not None and (len(owned)>=MAX_ORPHANS//2 or sum(len(item['wire']) for item in owned)+len(raw)>self._orphan_limit//2)
                if peer_full or len(self._orphans)>=MAX_ORPHANS or self._orphan_bytes+len(raw)>self._orphan_limit:
                    # An observed signed envelope with missing parents is not
                    # admitted. Persistent scans may defer it without holding
                    # payload RAM; certified recovery uses parent-ordered GET.
                    if self._profile is not None:self._sync_gap=True;return 'PENDING_PARENTS'
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
        if self._profile is not None:self._resolve_scan_progress()

    def _resolve_scan_progress(self):
        # Storage work stays outside the shared transport/engine lock. The
        # profile serializes commits, and published positions never rewind.
        self._profile.resolve_peer_scans()
        progress=self._profile.scan_progress()
        with self._lock:
            for peer,value in progress.items():
                self._cursors[peer]=max(self._cursors.get(peer,0),value['validated_prefix'])
                self._scan_cursors[peer]=max(self._scan_cursors.get(peer,0),value['position'])
                sync=self._peer_sync.get(peer)
                if sync is not None and value['position']<=sync['remote_records']:
                    sync.update(received_records=value['position'],validated_prefix=value['validated_prefix'],
                        declined_records=value['declined_records'],unresolved_records=value['unresolved_records'],
                        pending_records=sync['remote_records']-value['position'])
                    if not sync['next_wire_bytes']:
                        sync['state']='CATCHING_UP' if sync['pending_records'] else 'SCANNED_WITH_REFUSALS' if value['unresolved_records'] else 'CAUGHT_UP'

    def _relay_proposal(self,identifier):return self._engine.public_proposal(identifier)

    def _ingest_sdk_payload(self,raw,identifier,*,deadline,check=None):
        if self.node_role=='light' or self._profile is None:raise ValueError('GG_LAN_SDK_PAYLOAD_DISABLED')
        if not isinstance(raw,bytes) or not 1<=len(raw)<=self._wire_limit:raise ValueError('GG_LAN_WIRE_SIZE')
        if self._engine.has_proposal(identifier):return 'DUPLICATE'
        self._resource_check(deadline,check)
        with self.resources.governor().reserve_memory(len(raw)*16):
            info=self._engine.inspect_empty_proposal(raw)
            self._resource_check(deadline,check)
            if info['hash']!=identifier:raise ValueError('GG_LAN_PROPOSAL_HASH')
            with self._engine._lock:
                if identifier not in self._engine._recovery_hashes:raise ValueError('GG_LAN_SDK_PAYLOAD_NOT_AUTHORIZED')
            admission=self._engine.admit_relayed(raw,self._roster[self.public_key]['credit_index'],check=lambda:self._resource_check(deadline,check))
            self._engine.reconcile()
        self._drain_orphans();self._resolve_scan_progress()
        return admission['state']

    def recover_certified_payloads(self,state,order,*,preferred=None):
        """Bounded parent-ordered catch-up, only after SDK-verified full order.

        Each authenticated payload still follows ordinary full admission and
        synchronous journal rules. Partial progress never becomes membership.
        """
        if self.node_role=='light':raise ValueError('GG_LAN_LIGHT_PAYLOAD_DISABLED')
        if not isinstance(order,list) or len(order)>4095:raise ValueError('GG_DAG_CERTIFIED_ORDER_INCONSISTENT')
        from backend.gg_dag_checkpoint import source_from_owned_peer
        self._engine.authorize_certified_payloads(state,order,source_from_owned_peer(self))
        hashes=[leaf['hash'] for leaf in order]
        def missing():return [identifier for identifier in hashes if not self._engine.has_proposal(identifier)]
        absent=missing()
        if not absent:return {'remaining':0,'received':0}
        request=getattr(self._proof_service,'request_payloads',None)
        if callable(request):request(self.public_key,absent[:8])
        if not self._canonical_recovery_lock.acquire(blocking=False):return {'remaining':len(absent),'received':0}
        received=0;deadline=time.monotonic()+8
        try:
            sources=[key for key,row in self._roster.items() if key!=self.public_key and row.get('node_role')!='light']
            sources.sort(key=lambda key:(key!=preferred,key))
            while absent and received<32 and time.monotonic()<deadline:
                before=len(absent)
                for owner in sources:
                    if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                    if time.monotonic()>=deadline:break
                    try:self._pull(owner,'GET',{'hashes':absent[:min(8,32-received)]},deadline=None if self._wire_limit>MAX_WIRE else deadline);self._drain_orphans()
                    except (ValueError,OSError,RuntimeError):continue
                    absent=missing()
                    if len(absent)<before:break
                progress=before-len(absent);received+=progress
                if not progress:break
            return {'remaining':len(absent),'received':received}
        finally:self._canonical_recovery_lock.release()

    def _codec_check(self,deadline=None):
        if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        self.resources.governor().check_cpu(deadline=deadline)

    def _pull(self,peer,kind,payload,*,deadline=None):
        # Freeze the advertised receive policy for the entire authenticated
        # request. A concurrent local profile change applies on the next pull.
        wire_limit=self._wire_limit;payload={**payload,'wire_limit':wire_limit}
        stage='WAIT';bulk=wire_limit>MAX_WIRE
        bound=time.monotonic()+(BULK_SECONDS if bulk else CONNECTION_SECONDS)
        deadline=min(bound,deadline) if deadline is not None else bound
        codec_check=lambda:self._codec_check(deadline)
        assembler=RecordAssembler(maximum=wire_limit,check=codec_check,deadline=deadline,
                                  charge=lambda size:self._account_codec_raw(peer,size),
                                  workspace=lambda:self.resources.governor().reserve_memory(lossless.WORKSPACE_BYTES));memory=ExitStack();completed=0
        resume=None;received_ids=set();hinted=False;response_started=False
        deferred=[];deferred_bytes=0;defer_validation=bulk and kind=='GET';end_received=False
        requested_after=_integer(payload.get('after'),0,4095) if kind=='PAGE' else 0
        prefix_open=True;observed=[];persistent=self._profile is not None
        try:
            if bulk and kind=='GET':
                resume=self._get_resumes.begin(peer,self._network,payload.get('hashes'),wire_limit,deadline,self._cancel)
                hints=resume.hints()
                if hints:payload['resume']=hints;hinted=True
                assembler=RecordAssembler(maximum=wire_limit,resume=resume,check=codec_check,deadline=deadline,
                                          charge=lambda size:self._account_codec_raw(peer,size),
                                          workspace=lambda:self.resources.governor().reserve_memory(lossless.WORKSPACE_BYTES))
            self._pace_connection(peer,kind,deadline=deadline)
            stage='CONNECT'
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if kind=='PAGE':
                with self._lock:
                    if requested_after!=(self._scan_cursors if persistent else self._cursors).get(peer,0):raise ValueError('GG_LAN_PAGE_CURSOR')
            stage='AUTH'
            with lossless.lan_connection(self,peer,deadline,bulk=bulk,check=codec_check,
                    enabled=bulk and getattr(self,'_lossless_wire',True),operation=kind) as (sock,session,codec,response_base):
                assembler.codec=codec
                control_deadline=min(deadline,time.monotonic()+CONNECTION_SECONDS)
                stage='SEND';_send(sock,self._frame(session,response_base,kind,payload),MAX_FRAME,deadline=control_deadline)
                maximum_frames=8*((wire_limit+CHUNK_BYTES-1)//CHUNK_BYTES+2)+1 if bulk else 9
                for sequence in range(response_base,response_base+maximum_frames):
                    stage='RECEIVE';response,size=self._read(sock,MAX_FRAME,deadline=deadline,bulk=bulk)
                    stage='VALIDATE';frame=self._check_frame(response,size,peer,session,sequence)
                    response_started=True
                    if frame['kind']=='END':
                        end=frame['payload']
                        if (assembler.pending or not isinstance(end,dict) or set(end) not in ({'records'},{'records','tip','next_wire_bytes'})
                                or type(end['records']) is not int or end['records']!=completed):raise ValueError('GG_LAN_PAGE_END')
                        tip=None;next_wire=0
                        if kind=='PAGE' and 'tip' in end:
                            tip=_integer(end['tip'],0,4095);next_wire=_integer(end['next_wire_bytes'],0,MAX_BLOCK_WIRE_BYTES)
                            if tip<requested_after+completed or next_wire and (next_wire<=wire_limit or tip==requested_after+completed):raise ValueError('GG_LAN_PAGE_END')
                        # Observation progress commits only after authenticated
                        # END. Declined envelopes never become admission ACKs.
                        if kind=='PAGE' and persistent:
                            if observed:self._profile.save_scan_page(peer,observed)
                            self._resolve_scan_progress()
                        if tip is not None:
                            progress=self._profile.scan_progress().get(peer,{}) if persistent else {}
                            with self._lock:
                                cursor=(self._scan_cursors if persistent else self._cursors)[peer]
                                unresolved=progress.get('unresolved_records',0)
                                self._peer_sync[peer]={'state':'BLOCK_EXCEEDS_LOCAL_LIMIT' if next_wire else 'CATCHING_UP' if tip>cursor else 'SCANNED_WITH_REFUSALS' if unresolved else 'CAUGHT_UP',
                                    'remote_records':tip,'received_records':cursor,'validated_prefix':self._cursors[peer],
                                    'declined_records':progress.get('declined_records',0),'unresolved_records':unresolved,'pending_records':max(0,tip-cursor),
                                    'request_wire_limit':wire_limit,'next_wire_bytes':next_wire,'observed_at':time.time(),
                                    'basis':'AUTHENTICATED_PEER_LOG_NOT_FINALITY'}
                        if defer_validation:
                            end_received=True;break
                        self._mark_seen(peer)
                        self._transport_success();return completed
                    data=frame['payload']
                    if frame['kind']=='DATA_START':
                        # Validate the announced size before reserving memory;
                        # assembler allocates only as bounded chunks arrive.
                        if defer_validation and (not isinstance(data,dict) or type(data.get('size')) is not int or deferred_bytes+data['size']>MAX_GET_BUFFER_BYTES):raise ValueError('GG_LAN_GET_CREDIT')
                        assembler.feed(frame['kind'],data)
                        memory.enter_context(self.resources.governor().reserve_memory(data['size']*2))
                        continue
                    record=assembler.feed(frame['kind'],data)
                    if record is None:continue
                    if kind=='GET':
                        if record['hash'] not in payload['hashes'] or record['hash'] in received_ids:raise ValueError('GG_LAN_GET')
                        received_ids.add(record['hash'])
                    if not defer_validation:memory.close()
                    completed+=1
                    if completed>8:raise ValueError('GG_LAN_PAGE_LIMIT')
                    cursor=_integer(record['admission_index'],1 if kind=='PAGE' else 0,4095)
                    if kind=='PAGE' and cursor!=requested_after+completed:raise ValueError('GG_LAN_PAGE_CURSOR')
                    if defer_validation:
                        deferred.append(record);deferred_bytes+=len(record['wire']);continue
                    stage='EXECUTE'
                    try:result=self._ingest(record['wire'],peer,record['hash'],deadline=deadline)
                    except ValueError as error:
                        if not (persistent and kind=='PAGE' and str(error)=='GG_DAG_PRODUCER_QUARANTINE_CREDIT'):raise
                        result='REFUSED'
                    if kind=='PAGE':
                        if persistent:
                            from backend import gg_peer_scan as peer_scan
                            disposition='REFUSED' if result=='REFUSED' else 'DEFERRED' if result=='PENDING_PARENTS' else 'ADMITTED'
                            observed.append(peer_scan.event('OBSERVED',cursor,record['hash'],disposition,peer_scan.REASONS.get(disposition,'')))
                        else:
                            prefix_open=prefix_open and result in ('ADMITTED_UNFINALIZED','DUPLICATE')
                            with self._lock:
                                if prefix_open:self._cursors[peer]=cursor
                if not end_received:raise ValueError('GG_LAN_PAGE_LIMIT')
            # The bounded authenticated GET is complete and its socket is closed.
            # Full block verification runs under CPU/RAM/cancellation governance,
            # independently of the expired network receive budget.
            for record in deferred:
                stage='EXECUTE'
                try:result=self._ingest(record['wire'],peer,record['hash'],deadline=None)
                except ValueError as error:
                    if resume is not None and str(error) in {'GG_DAG_SIGNATURE','GG_DAG_TX_SIGNATURE','GG_DAG_BLOCK_SIGNATURE',
                            'GG_LAN_PROPOSAL_HASH','GG_LAN_PROPOSAL_CHANGED','GG_DAG_WIRE_CANONICAL','GG_DAG_PAYLOAD_ROOT'}:
                        resume.discard(record['hash'])
                    raise
                if resume is not None and result in ('ADMITTED_UNFINALIZED','DUPLICATE'):resume.admitted(record['hash'])
            self._mark_seen(peer);self._transport_success();return completed
        except Exception as error:
            error._gg_lan_details=_failure_details(error,kind,stage)
            if hinted and not response_started and stage in ('SEND','RECEIVE') and _failure_code(error) in {
                    'GG_LAN_EOF','GG_LAN_CONNECTION_RESET','GG_LAN_BROKEN_PIPE','GG_LAN_IO_TIMEOUT','GG_LAN_READ_DEADLINE'}:
                self._get_resumes.suppress_hints(peer)
            self._error(error,kind,stage,None if local_get_error(error) else peer);raise
        finally:
            try:assembler.close(preserve=True)
            finally:
                try:memory.close()
                finally:
                    if resume is not None:resume.close()

    def _gossip_loop(self):
        # A stalled peer must not stop the other peer's actual block exchange.
        # The signed roster is fixed for this session: exactly two owned lanes.
        workers=[threading.Thread(target=self._gossip_peer_loop,args=(peer,),
                    name='gg-lan-peer-'+str(index),daemon=True)
                 for index,peer in enumerate(peer for peer in tuple(self._cursors)[:MAX_PEERS-1] if self._roster[peer].get('node_role')!='light')]
        for worker in workers:worker.start()
        for worker in workers:worker.join()

    def _gossip_peer_loop(self,peer):
        while not self._cancel.wait(.1):
            try:self._get_resumes.expire(peer)
            except Exception as error:self._error(error)
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
                missing=self._pending_fetches(peer)
                with self._lock:cursor=(self._scan_cursors if self._profile is not None else self._cursors)[peer]
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

    def _pending_fetches(self,peer):
        # Rotate both bounded sources. A permanently unresolvable early hash
        # cannot starve later deferred work; a RAM drop cannot forget its hash.
        with self._lock:
            parents=[]
            for item in self._orphans.values():
                for identifier in item['parents']:
                    if not self._engine.has_proposal(identifier) and identifier not in parents:parents.append(identifier)
            after=self._deferred_after.get(peer,0)
        deferred=self._profile.deferred_payloads(peer,after,4 if parents else 8) if self._profile is not None else {'hashes':[],'after':0}
        with self._lock:
            self._deferred_after[peer]=deferred['after'];offset=self._orphan_after.get(peer,0)
            if parents:
                offset%=len(parents);parents=parents[offset:]+parents[:offset]
                selected=parents[:8-len(deferred['hashes'])];self._orphan_after[peer]=offset+len(selected)
            else:selected=[]
        return list(dict.fromkeys([*selected,*deferred['hashes']]))[:8]

    def snapshot(self):
        if self._bundle is not None and self._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
            from backend.gg_financial_proof_sync import peer_snapshot
            return peer_snapshot(self)
        if self._bundle is not None and self._bundle['body']['schema']=='gg.lan-dag.session.v5':
            from backend.gg_segmented_proof_sync import peer_snapshot
            return peer_snapshot(self)
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
                'network_id':self._network,'producer_count':sum(len(row.get('producer_indices',())) for row in self._roster.values() if row.get('node_role','producer')=='producer'),
                'producer_slot_count':6 if engine else 0,'local_producer_indices':list(self._local_indices),
                'candidate_invite_count':len(self._candidates),'configured_peers':len(self._roster),'authenticated_peers':[{'label':self._roster[peer]['label'],'last_seen':stamp,
                    'endpoint':{'host':self._roster[peer]['host'],'port':self._roster[peer]['port']},'producer_indices':self._roster[peer]['producer_indices']}
                    for peer,stamp in self._seen.items() if peer in self._roster and peer in self._seen_monotonic
                    and time.monotonic()-self._seen_monotonic[peer]<=PEER_FRESH_SECONDS and not self._cancel.is_set() and not self._transport_exhausted],
                'connection_state':contact,'peer_status':peers,'producer_identities':identities,
                'storage':self._profile.snapshot() if self._profile is not None else {'enabled':False,'state':'RAM_ONLY'},
                'payload_resume':self._get_resumes.status(),
                'participation':{'role':self.node_role,'producer':engine is not None and self.node_role=='producer','local_producer_count':len(self._local_indices),
                    'eligible_network_producers':sum(len(row.get('producer_indices',())) for row in self._roster.values() if row.get('node_role','producer')=='producer'),
                    'replica':engine is not None and self.node_role!='light','verification_scope':'SDK_CERTIFICATES_AND_RELEVANT_MEMBERSHIP' if self.node_role=='light' else 'ALL_ADMITTED_DAG_TEST_TX' if self._dag_enabled else 'EMPTY_PROPOSALS_ONLY',
                    'consensus_validator':False,'light_client':self.node_role=='light','mining':False,
                    'financial_execution':False,'ownership_basis':'LOCAL_SIGNERS_AND_SIGNED_SESSION_ROSTER'},
                'network_kind':'PRIVATE_LAN','peer_fresh_seconds':PEER_FRESH_SECONDS,
                'authenticated_exchanges':sum(self._peer_exchanges.values()),
                'physical_hosts_verified':False,'transactions_enabled':self._dag_enabled,'traffic_confidentiality':False,
                'allow_test_tokens':self.allow_test_tokens,'test_tokens_enabled':ledger is not None,'allow_dag_transactions':self.allow_dag_transactions,
                'orphan_count':len(self._orphans),'orphan_bytes':self._orphan_bytes,'sync_gap':self._sync_gap,
                'traffic_bytes':self._raw_received,'traffic_bytes_basis':'APPLICATION_TCP_READ_BYTES',
                'charged_transport_bytes':self._total_bytes,'rejected_frames':self._rejected,'last_error':self._last_error,'last_error_at':self._last_error_at,'last_error_details':dict(self._last_error_details),
                'transport':{'state':'STOPPED' if self._cancel.is_set() else 'EXHAUSTED' if self._transport_exhausted else 'ACTIVE',
                    'credit_mode':'REFILLING_PER_INGRESS' if self._profile is not None else 'FINITE_SESSION',
                    'credit_period_seconds':1.0 if self._profile is not None else None,
                    'exhausted_reason':self._transport_exhausted,'connections_admitted':self._connections_admitted,
                    'active_handlers':len(self._handlers),'counters':deepcopy(self._transport_counts),'history':deepcopy(list(self._transport_history))},
                'limits':{'frame_bytes':MAX_FRAME,'public_bundle_bytes':MAX_BUNDLE,'orphan_count':MAX_ORPHANS,'orphan_bytes':self._orphan_limit,
                    'candidate_invites':MAX_PEERS-1,'frame_deadline_seconds':FRAME_SECONDS,'connection_deadline_seconds':CONNECTION_SECONDS,
                    'raw_received_bytes':None if self._profile is not None else self._total_bytes_limit,'peer_bytes':self._peer_bytes_limit,
                    'block_wire_bytes':self._wire_limit,'bulk_deadline_seconds':BULK_SECONDS,
                    'connections_per_second':32,'connection_rate_basis':'PER_SOURCE_ADDRESS' if self._profile is not None else 'WHOLE_SESSION',
                    'handlers_per_source_address':2 if self._profile is not None else None,
                    'session_connections':None if self._profile is not None else MAX_REQUESTS,'frames_per_direction':self._frame_limit}}
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
        body['dag_production']=self._node_snapshot()
        own=body['dag_production'];source=own if own['selected'] else body['dag_stress']
        body['dag_resources']=self.resources.snapshot(source['transactions_per_block'] or None)
        if engine and self._dag_enabled:
            worker_count=own['worker_count']+body['dag_stress']['worker_count'];body['worker_count']=worker_count
            body['live'].update(mode='LAN_DAG_INDEPENDENT_OWN_PRODUCERS' if own['selected'] else 'LAN_DAG_FINITE_STRESS',state='RUNNING' if worker_count else 'PAUSED',enabled=bool(worker_count),
                active_workers=worker_count,local_worker_count=worker_count,local_producer_indices=list(self._local_indices),
                interval_ms=source['interval_ms'],cadence_origin='LOCAL_CONFIGURED_NODE_WORKER' if own['selected'] else 'LOCAL_CONFIGURED_STRESS_WORKER',
                target_proposal_bps=len(self._local_indices)*1000/source['interval_ms'] if source['interval_ms'] else None,
                blocks=len(self._local_indices),transactions_per_block=source['transactions_per_block'])
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
        from backend.gg_native_process_policy import close_owner
        close_owner(self._profile or self)
        self._circle_cancel.set()
        self._dag_cancel.set()
        self._node_cancel.set()
        if self._observer_admissions is not None:self._observer_admissions.request_stop()
        if self._proof_service is not None:self._proof_service.request_stop()
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
        for worker in (self._acceptor,self._gossip,self._circle_thread,self._dag_worker,self._dag_controller,self._node_worker):
            if worker and worker is not threading.current_thread():worker.join(2)
        with self._lock:handlers=list(self._handlers)
        for worker in handlers:
            if worker is not threading.current_thread():worker.join(2)
        if any(worker and worker.is_alive() for worker in (self._acceptor,self._gossip,self._circle_thread,self._dag_worker,self._dag_controller,self._node_worker,*handlers)):raise ValueError('GG_LAN_STOP_TIMEOUT')
        # The historical result remains in _dag_stress. Disable live evidence
        # reads before clearing the engine/signers; stopped status never creates
        # a fresh proof or tries to reconcile a cleared ledger.
        with self._lock:self._dag_enabled=False
        if self._proof_service is not None:self._proof_service.close()
        self._get_resumes.close()
        if engine:engine.stop()
        if self._tokens:self._tokens.clear()
        with self._lock:
            self._identity=None;self._local_keys.clear();self._orphans.clear();self._candidates.clear();self._orphan_bytes=0;self._listener=None
        if self._profile is not None:self._profile.close()
        return self.snapshot()
