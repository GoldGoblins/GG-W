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
from copy import deepcopy
import ipaddress
import json
import re
import secrets
import socket
import struct
import threading
import time

from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import ParallelDag, make_public_genesis, pack, digest, _verify
from backend import gg_lan_test_tokens as test_tokens

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
FRAME_SECONDS=1.0
CONNECTION_SECONDS=3.0
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
DAG_STRESS_MAX_TX=64
DAG_STRESS_LIMITS={'min_duration_ms':1000,'max_duration_ms':60000,'min_interval_ms':100,
    'max_interval_ms':60000,'max_tx_per_block':DAG_STRESS_MAX_TX,'wire_bytes':MAX_WIRE,
    'scope':'STAGE1_SOFTWARE_PROTOCOL_BOUNDS_NOT_HARDWARE_CAPACITY'}


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
    allowed_operations={'TOKEN_STATUS','TOKEN_SYNC','TOKEN_SUBMIT','TOKEN_APPLY','CIRCLE_SIGN','CIRCLE_END',
        'DAG_STRESS_PREPARE','DAG_STRESS_BEGIN','DAG_STRESS_STOP','DAG_STRESS_STATUS'}
    allowed_stages={'CHECK','WAIT','CONNECT','AUTH','SEND','RECEIVE','VALIDATE','EXECUTE'}
    classes={'TimeoutError','ConnectionResetError','ConnectionRefusedError','BrokenPipeError','OSError','ValueError','TypeError','JSONDecodeError'}
    if not isinstance(existing,dict):existing={}
    operation=operation or existing.get('operation','');stage=stage or existing.get('stage','')
    return {'operation':operation if isinstance(operation,str) and operation in allowed_operations else '',
        'stage':stage if isinstance(stage,str) and stage in allowed_stages else '',
        'error_class':type(error).__name__ if type(error).__name__ in classes else 'Exception'}


def _receive(sock,limit,*,account=None,deadline=None,check=None):
    deadline=min(deadline if deadline is not None else float('inf'),time.monotonic()+FRAME_SECONDS)
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


def _send(sock,value,limit,*,deadline=None):
    raw=pack(value)
    if not 2<=len(raw)<=limit:raise ValueError('GG_LAN_FRAME_SIZE')
    if deadline is not None:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
        sock.settimeout(min(IO_TIMEOUT,remaining))
    sock.sendall(struct.pack('!I',len(raw))+raw)
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
        self._raw_received=0;self._connection_times=deque(maxlen=32);self._connections_admitted=0
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
            'stop_reason':'','last_error':'','participants':[]}

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
                with socket.create_connection((peer['host'],peer['port']),timeout=IO_TIMEOUT) as sock:
                    nonce=secrets.token_hex(32)
                    sock.settimeout(IO_TIMEOUT);_send(sock,{'kind':'install','bundle':bundle,'nonce':nonce},MAX_BUNDLE+1024)
                    response,_size=self._read(sock,MAX_INVITE)
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
            if plan is not None:
                state['blocks']=max(0,evidence['blocks']-plan['baseline']['blocks'])
                state['transactions']=max(0,evidence['transactions']-plan['baseline']['transactions'])
                if state['state'] in ('STARTING','RUNNING','STOPPING'):
                    state['elapsed_ms']=round((time.monotonic()-plan['started'])*1000)
            return {**state,'evidence':evidence,'run_id':plan['body']['run_id'] if plan else '',
                'worker_active':bool(self._dag_worker and self._dag_worker.is_alive())}

    @staticmethod
    def _dag_stopped_observation_matches(status,evidence,run_id):
        return (isinstance(status,dict) and status.get('run_id')==run_id
            and status.get('worker_active') is False and status.get('state') in ('COMPLETE','STOPPING')
            and status.get('last_error')=='' and LanDagPeer._dag_same_evidence(evidence,status.get('evidence')))

    def _dag_stress_command(self,peer,kind,payload):
        """Authenticated coordinator-only, idempotent two-phase finite controls."""
        if peer!=self._trusted:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
        if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        if not isinstance(payload,dict):raise ValueError('GG_LAN_DAG_STRESS_REQUEST')
        with self._dag_control:
            if kind=='DAG_STRESS_STATUS' and not payload:return self._dag_status()
            if kind=='DAG_STRESS_PREPARE' and set(payload)=={'plan'}:
                signed=payload['plan'];body=_checked(signed,_DAG_STRESS,self._trusted)
                fields={'schema','network_id','run_id','duration_ms','transactions_per_block','interval_ms','remote','expires_at_ns','baseline'}
                if (not isinstance(body,dict) or set(body)!=fields or body.get('schema')!='gg.lan-dag.stress.v1'
                        or body.get('network_id')!=self._network or type(body.get('remote')) is not bool):raise ValueError('GG_LAN_DAG_STRESS_PLAN')
                _public(body['run_id']);_integer(body['duration_ms'],1000,60000)
                _integer(body['transactions_per_block'],1,DAG_STRESS_MAX_TX);_integer(body['interval_ms'],100,60000)
                _integer(body['expires_at_ns'],1,2**63-1)
                if not self._dag_enabled or not self.allow_dag_transactions or not all(row.get('allow_dag_transactions') is True for row in self._roster.values()):
                    raise ValueError('GG_LAN_DAG_ALL_PEERS_OPT_IN_REQUIRED')
                self._engine.preflight_lan_test_block(body['transactions_per_block'],MAX_WIRE)
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
                deadline=now+duration;drain=min(2.0,body['duration_ms']/3000)
                self._dag_cancel=threading.Event()
                self._dag_plan={'body':deepcopy(body),'signed':deepcopy(signed),'deadline':deadline,
                    'production_deadline':deadline-drain,'started':now,'baseline':baseline,'begun':False}
                with self._lock:
                    self._dag_stress.update(state='STARTING',duration_ms=body['duration_ms'],transactions_per_block=body['transactions_per_block'],
                        interval_ms=body['interval_ms'],elapsed_ms=0,blocks=0,transactions=0,all_peers_synced=False,
                        acknowledged_blocks=None,acknowledged_transactions=None,acknowledged_bps=None,acknowledged_tps=None,
                        stop_reason='',last_error='',last_error_details={},failure_phase='',phase_ms={},status_polls=0,
                        acknowledgement_basis='',participants=[])
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
        def permitted():
            if cancel.is_set() or self._cancel.is_set() or time.monotonic()>=plan['production_deadline']:raise ValueError('GG_LAN_DAG_STRESS_DEADLINE')
        try:
            cadence=plan['body']['interval_ms']/1000;due=time.monotonic()
            while time.monotonic()<plan['production_deadline'] and not cancel.is_set() and not self._cancel.is_set():
                if cancel.wait(max(0,min(due,plan['production_deadline'])-time.monotonic())):break
                for producer in self._local_indices:
                    permitted();self._engine.produce_lan_test_block(producer,plan['body']['transactions_per_block'],MAX_WIRE,check=permitted)
                due=max(due+cadence,time.monotonic())
        except ValueError as error:
            code=str(error)
            if code!='GG_LAN_DAG_STRESS_DEADLINE':
                state='LIMIT_REACHED' if code in {'GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_RECORD_LIMIT','GG_DAG_STORAGE_LIMIT','GG_DAG_LAN_WIRE_PROFILE_LIMIT'} else 'ERROR'
                with self._lock:self._dag_stress.update(state=state,stop_reason='SOFTWARE_PROFILE_LIMIT' if state=='LIMIT_REACHED' else 'FAILED',last_error=_failure_code(error,'GG_LAN_DAG_STRESS_FAILED'))
        except Exception as error:
            with self._lock:self._dag_stress.update(state='ERROR',stop_reason='FAILED',last_error=_failure_code(error,'GG_LAN_DAG_STRESS_FAILED'))
        finally:
            with self._lock:
                if self._dag_plan is plan and self._dag_stress['state']=='RUNNING':self._dag_stress['state']='STOPPING'

    def start_dag_stress(self,duration_ms=10000,transactions_per_block=16,interval_ms=100,remote=True):
        _integer(duration_ms,1000,60000);_integer(transactions_per_block,1,DAG_STRESS_MAX_TX);_integer(interval_ms,100,60000)
        if type(remote) is not bool:raise ValueError('GG_LAN_OPTION')
        if self.public_key!=self._trusted:raise ValueError('GG_LAN_COORDINATOR_REQUIRED')
        with self._dag_control:
            if self._dag_controller and self._dag_controller.is_alive():raise ValueError('GG_LAN_DAG_STRESS_BUSY')
            if not self._dag_enabled:raise ValueError('GG_LAN_DAG_TRANSACTIONS_DISABLED')
            self._engine.preflight_lan_test_block(transactions_per_block,MAX_WIRE)
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
        attempted=[];statuses={};terminal='TIME_BUDGET';reason='DURATION';error='';synced=False
        deadline=plan['deadline'];run_id=plan['body']['run_id']
        phase='PREPARE';phase_started=time.monotonic();phase_ms={};details={};failure_phase='';status_polls=0
        acknowledgement_basis='';observed_before_deadline=False
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
                # Local STOP signals the production Event. Waiting on that same
                # Event here would spin; lifetime cancellation remains separate.
                self._cancel.wait(min(.025,max(0,deadline-time.monotonic())))
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
            software_limit=error in {'GG_LAN_CREDIT','GG_LAN_ORPHAN_CREDIT','GG_LAN_DAG_STRESS_RUN_LIMIT','GG_DAG_SESSION_CREDIT','GG_DAG_PEER_CREDIT','GG_DAG_STORAGE_LIMIT','GG_DAG_RECORD_LIMIT'}
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
                status=local if peer==self.public_key else statuses.get(peer,{})
                proof=status.get('evidence',{})
                rows.append({'label':roster['label'],'local':peer==self.public_key,'opted_in':roster.get('allow_dag_transactions') is True,
                    'state':terminal if peer==self.public_key else status.get('state','UNOBSERVED'),'blocks':proof.get('blocks'),'transactions':proof.get('transactions'),
                    'protocol_fault':proof.get('protocol_fault',''),'blockset_digest':proof.get('blockset_digest'),'state_root':proof.get('state_root')})
            with self._lock:
                self._dag_stress.update(state=terminal,stop_reason=reason,last_error=error,elapsed_ms=round(elapsed*1000),
                    blocks=local['blocks'],transactions=local['transactions'],participants=rows,all_peers_synced=synced,
                    last_error_details=details,failure_phase=failure_phase,phase_ms=phase_ms,status_polls=status_polls,
                    acknowledgement_basis=acknowledgement_basis if synced else '',
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
                for key in ('blocks','transactions','elapsed_ms'):state[key]=current[key]
                state['worker_active']=current['worker_active']
            except ValueError:
                if self._dag_enabled and not self._cancel.is_set():raise
                state['worker_active']=False
        else:state['worker_active']=False
        state['worker_count']=1 if state['worker_active'] else 0
        return {**dag_stress_capabilities(),**state,'enabled':self._dag_enabled,'local_opt_in':self.allow_dag_transactions,
            'role':'COORDINATOR' if self.public_key==self._trusted else 'PARTICIPANT',
            'can_start':bool(self._dag_enabled and self.public_key==self._trusted and len(participants)==3 and all(row['opted_in'] for row in participants)
                and not busy and not active and engine is not None and not engine.snapshot()['live']['enabled'] and not engine._lan_fault),
            'participants':state['participants'] or participants,'counts_basis':'LOCAL_DAG_ADMISSION_NOT_FINALITY'}

    def _credit(self,peer,size):
        with self._lock:
            value=self._traffic.setdefault(peer,{'bytes':0,'frames':0})
            value['bytes']+=size;value['frames']+=1;self._total_bytes+=size
            if value['bytes']>MAX_PEER_BYTES or value['frames']>MAX_REQUESTS or self._total_bytes>MAX_TOTAL_BYTES:raise ValueError('GG_LAN_CREDIT')

    def _account_received(self,size):
        # Charge raw reads even when JSON, signatures or announced sizes fail.
        with self._lock:
            self._raw_received+=size
            if self._raw_received>MAX_TOTAL_BYTES:raise ValueError('GG_LAN_CREDIT')

    def _read(self,sock,limit,*,deadline=None,check=None):
        def permitted():
            if self._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            if check is not None:check()
        return _receive(sock,limit,account=self._account_received,deadline=deadline,check=permitted)

    def _accept(self):
        while not self._cancel.is_set():
            try:connection,address=self._listener.accept()
            except socket.timeout:continue
            except OSError:break
            now=time.monotonic()
            with self._lock:
                while self._connection_times and self._connection_times[0]<now-1:self._connection_times.popleft()
                permitted=len(self._connection_times)<32 and self._connections_admitted<MAX_REQUESTS and self._raw_received<=MAX_TOTAL_BYTES
                if permitted:self._connection_times.append(now);self._connections_admitted+=1
            if not permitted:
                connection.close();self._cancel.wait(.01);continue
            if not self._slots.acquire(blocking=False):connection.close();continue
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
        try:
            deadline=time.monotonic()+CONNECTION_SECONDS
            first,size=self._read(sock,MAX_BUNDLE+1024,deadline=deadline)
            self._credit('unconfigured',size)
            if first=={'kind':'invite'}:_send(sock,self.public_invite(),MAX_INVITE);return
            if isinstance(first,dict) and set(first)=={'kind','announcement'} and first.get('kind')=='announce':
                _send(sock,self._receive_announcement(first['announcement'],address),MAX_INVITE);return
            if isinstance(first,dict) and set(first)=={'kind','bundle','nonce'} and first.get('kind')=='install':
                _public(first['nonce']);self.install_session(first['bundle'])
                ack={'state':'READY','network_id':self._network,'peer_key':self.public_key,'nonce':first['nonce']}
                _send(sock,_signed(self._identity,_INSTALL_ACK,ack),MAX_INVITE);return
            if size>MAX_INVITE:raise ValueError('GG_LAN_HELLO_SIZE')
            peer,session=self._server_auth(sock,first,address,deadline)
            request,size=self._read(sock,MAX_FRAME,deadline=deadline);body=self._check_frame(request,size,peer,session,0)
            payload=body['payload'];records=[]
            if body['kind'].startswith(('TOKEN_','CIRCLE_','DAG_STRESS_')):
                try:result=self._dag_stress_command(peer,body['kind'],payload) if body['kind'].startswith('DAG_STRESS_') else self._token_command(peer,body['kind'],payload)
                except ValueError as error:
                    code=str(error)
                    result={'error':code if re.fullmatch(r'GG_[A-Z0-9_]{1,80}',code) else 'GG_LAN_TOKEN_REQUEST_FAILED'}
                self._credit('out:'+peer,_send(sock,self._frame(session,0,'TOKEN_RESULT',result),MAX_FRAME,deadline=deadline))
                with self._lock:self._seen[peer]=time.time()
                return
            if body['kind']=='PAGE' and isinstance(payload,dict) and set(payload)=={'after'}:
                records=self._engine.public_proposals(payload['after'],8)['records']
            elif body['kind']=='GET' and isinstance(payload,dict) and set(payload)=={'hashes'}:
                hashes=payload['hashes']
                if not isinstance(hashes,list) or not 1<=len(hashes)<=8 or any(not isinstance(value,str) or not _HEX.fullmatch(value) for value in hashes) or len(set(hashes))!=len(hashes):raise ValueError('GG_LAN_GET')
                for identifier in hashes:
                    raw=self._engine.public_proposal(identifier)
                    if raw:records.append({'hash':identifier,'wire':raw,'admission_index':0})
            else:raise ValueError('GG_LAN_REQUEST')
            for sequence,record in enumerate(records):
                if len(record['wire'])>MAX_WIRE:raise ValueError('GG_LAN_WIRE_SIZE')
                data={'hash':record['hash'],'admission_index':record['admission_index'],'wire':base64.b64encode(record['wire']).decode('ascii')}
                self._credit('out:'+peer,_send(sock,self._frame(session,sequence,'DATA',data),MAX_FRAME))
            self._credit('out:'+peer,_send(sock,self._frame(session,len(records),'END',{'records':len(records)}),MAX_FRAME))
            with self._lock:self._seen[peer]=time.time()
        except Exception as error:self._error(error)
        finally:
            try:sock.close()
            finally:
                with self._lock:self._sockets.discard(sock);self._handlers.discard(threading.current_thread())
                self._slots.release()

    def _error(self,error):
        with self._lock:
            self._rejected+=1;self._last_error=_failure_code(error);self._last_error_at=time.time();self._last_error_details=_failure_details(error)

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
            # Existing gossip may use20 connections/s. Keep extra test-token RPCs
            # to8/s per peer so the private32/s acceptance cap retains headroom.
            stage='WAIT';delay=self._token_rpc_times.get(peer,0)+.125-time.monotonic()
            if deadline is not None:delay=min(delay,max(0,deadline-time.monotonic()))
            if delay>0 and (cancel or self._cancel).wait(delay):raise ValueError('GG_LAN_CIRCLE_CANCELLED')
            permitted();self._token_rpc_times[peer]=time.monotonic()
            timeout=min(IO_TIMEOUT,max(.001,deadline-time.monotonic())) if deadline is not None else IO_TIMEOUT
            stage='CONNECT'
            with socket.create_connection((address['host'],address['port']),timeout=timeout) as sock:
                sock.settimeout(timeout);connection_deadline=min(time.monotonic()+CONNECTION_SECONDS,deadline) if deadline is not None else time.monotonic()+CONNECTION_SECONDS
                with self._lock:
                    self._sockets.add(sock)
                    if cancel is not None:self._circle_sockets.add(sock)
                try:
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
                    with self._lock:self._seen[peer]=time.time()
                    return result
                finally:
                    with self._lock:self._sockets.discard(sock);self._circle_sockets.discard(sock)
        except Exception as error:
            # Preserve the exception and request outcome; never replay an RPC
            # whose acknowledgement might have been lost after commitment.
            error._gg_lan_details=_failure_details(error,kind,stage)
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

    def _ingest(self,raw,peer,claimed_hash=None):
        if peer not in self._roster or peer==self.public_key:raise ValueError('GG_LAN_UNKNOWN_PEER')
        if not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_WIRE:raise ValueError('GG_LAN_WIRE_SIZE')
        # Only exact bytes already admitted may bypass inspection.
        if isinstance(claimed_hash,str) and _HEX.fullmatch(claimed_hash):
            existing=self._engine.public_proposal(claimed_hash)
            if existing is not None and existing==raw:return 'DUPLICATE'
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
                if len(self._orphans)>=MAX_ORPHANS or self._orphan_bytes+len(raw)>MAX_ORPHAN_BYTES:
                    self._sync_gap=True;raise ValueError('GG_LAN_ORPHAN_CREDIT')
                self._orphans[identifier]={'wire':raw,'peer':peer,'parents':info['parents'],'created':time.monotonic()}
                self._orphan_bytes+=len(raw)
            return 'PENDING_PARENTS'
        self._engine.admit_relayed(raw,self._roster[peer]['credit_index']);self._engine.reconcile()
        self._drain_orphans()
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
                self._engine.admit_relayed(item['wire'],self._roster[item['peer']]['credit_index']);self._engine.reconcile()
            except ValueError as error:
                # A now-checkable orphan may have a false rank or reused
                # producer sequence. Reject it without undoing its real parent.
                self._error(error)

    def _pull(self,peer,kind,payload):
        address=self._roster[peer]
        with socket.create_connection((address['host'],address['port']),timeout=IO_TIMEOUT) as sock:
            sock.settimeout(IO_TIMEOUT)
            deadline=time.monotonic()+CONNECTION_SECONDS
            with self._lock:self._sockets.add(sock)
            try:
                session=self._client_auth(sock,peer,deadline)
                _send(sock,self._frame(session,0,kind,payload),MAX_FRAME)
                for sequence in range(9):
                    response,size=self._read(sock,MAX_FRAME,deadline=deadline)
                    frame=self._check_frame(response,size,peer,session,sequence)
                    if frame['kind']=='END':
                        if frame['payload']!={'records':sequence}:raise ValueError('GG_LAN_PAGE_END')
                        with self._lock:self._seen[peer]=time.time()
                        return
                    data=frame['payload']
                    if frame['kind']!='DATA' or not isinstance(data,dict) or set(data)!={'hash','admission_index','wire'}:raise ValueError('GG_LAN_DATA')
                    _public(data['hash'])
                    cursor=_integer(data['admission_index'],1 if kind=='PAGE' else 0,4095)
                    if not isinstance(data['wire'],str) or len(data['wire'])>MAX_WIRE*4//3+4:raise ValueError('GG_LAN_WIRE_SIZE')
                    try:raw=base64.b64decode(data['wire'],validate=True)
                    except (ValueError,TypeError):raise ValueError('GG_LAN_WIRE_ENCODING') from None
                    self._ingest(raw,peer,data['hash'])
                    if kind=='PAGE':
                        with self._lock:
                            if cursor<=self._cursors[peer]:raise ValueError('GG_LAN_PAGE_CURSOR')
                            self._cursors[peer]=cursor
                raise ValueError('GG_LAN_PAGE_LIMIT')
            finally:
                with self._lock:self._sockets.discard(sock)

    def _gossip_loop(self):
        while not self._cancel.wait(.1):
            for peer in tuple(self._cursors):
                if self._cancel.is_set():break
                try:
                    with self._lock:
                        missing=[]
                        for item in self._orphans.values():
                            for identifier in item['parents']:
                                if not self._engine.has_proposal(identifier) and identifier not in missing:missing.append(identifier)
                        missing=missing[:8];cursor=self._cursors[peer]
                    if missing:self._pull(peer,'GET',{'hashes':missing})
                    self._pull(peer,'PAGE',{'after':cursor});self._drain_orphans()
                except Exception as error:self._error(error)
            if self._tokens is not None and self.public_key!=self._trusted and time.monotonic()-self._last_token_sync>=1:
                self._last_token_sync=time.monotonic()
                try:
                    with self._token_operation:self._sync_tokens()
                except Exception as error:self._error(error)

    def snapshot(self):
        with self._lock:
            engine=self._engine;ledger=self._tokens;circle=dict(self._circle);participant_plan=self._token_plan
            network={'state':'STOPPED' if self._cancel.is_set() else 'READY' if engine else 'PAIRING',
                'scope':'PRIVATE_LAN_SESSION_EXPERIMENT','label':self.label,'endpoint':{'host':self.host,'port':self.port},
                'allowed_cidr':str(self.allowed),'public_key':self.public_key,'trusted_coordinator':self._trusted,'auto_produce':self.auto_produce,
                'network_id':self._network,'producer_count':6 if engine else 0,'local_producer_indices':list(self._local_indices),
                'candidate_invite_count':len(self._candidates),'configured_peers':len(self._roster),'authenticated_peers':[{'label':self._roster[peer]['label'],'last_seen':stamp,
                    'endpoint':{'host':self._roster[peer]['host'],'port':self._roster[peer]['port']},'producer_indices':self._roster[peer]['producer_indices']}
                    for peer,stamp in self._seen.items()],
                'physical_hosts_verified':False,'transactions_enabled':self._dag_enabled,'traffic_confidentiality':False,
                'allow_test_tokens':self.allow_test_tokens,'test_tokens_enabled':ledger is not None,'allow_dag_transactions':self.allow_dag_transactions,
                'orphan_count':len(self._orphans),'orphan_bytes':self._orphan_bytes,'sync_gap':self._sync_gap,
                'traffic_bytes':self._raw_received,'traffic_bytes_basis':'APPLICATION_TCP_READ_BYTES',
                'charged_transport_bytes':self._total_bytes,'rejected_frames':self._rejected,'last_error':self._last_error,'last_error_at':self._last_error_at,'last_error_details':dict(self._last_error_details),
                'limits':{'frame_bytes':MAX_FRAME,'public_bundle_bytes':MAX_BUNDLE,'orphan_count':MAX_ORPHANS,'orphan_bytes':MAX_ORPHAN_BYTES,
                    'candidate_invites':MAX_PEERS-1,'frame_deadline_seconds':FRAME_SECONDS,'connection_deadline_seconds':CONNECTION_SECONDS,
                    'raw_received_bytes':MAX_TOTAL_BYTES,'connections_per_second':32,'session_connections':MAX_REQUESTS}}
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
        if engine and self._dag_enabled:
            worker_count=body['dag_stress']['worker_count'];body['worker_count']=worker_count
            body['live'].update(mode='LAN_DAG_FINITE_STRESS',state='RUNNING' if worker_count else 'PAUSED',enabled=bool(worker_count),
                active_workers=worker_count,local_worker_count=worker_count,local_producer_indices=list(self._local_indices),
                interval_ms=body['dag_stress']['interval_ms'],cadence_origin='LOCAL_CONFIGURED_STRESS_WORKER',
                target_proposal_bps=len(self._local_indices)*1000/body['dag_stress']['interval_ms'],
                blocks=len(self._local_indices),transactions_per_block=body['dag_stress']['transactions_per_block'])
        if engine:body['block_graph']['source']='LAN_SIGNED_PROPOSAL_DAG'
        return body

    def telemetry_revision(self):
        """Constant-size identity check before copying the public DAG tail."""
        with self._lock:
            engine=self._engine;ledger=self._tokens;participant_plan=self._token_plan
            revision=(self._network,self._cancel.is_set(),self._rejected,len(self._orphans),self._orphan_bytes,
                self._raw_received,self._total_bytes,self._sync_gap,len(self._candidates),tuple(sorted(self._seen.items())),
                self._circle['state'],self._circle['transactions'],self._circle['completed_rounds'],self._circle_epoch,
                participant_plan['body']['run_id'] if participant_plan is not None else '',int(time.monotonic()))
        return revision+(('TOKEN',ledger.revision()) if ledger else ('NO_TOKENS',))+(engine.telemetry_revision() if engine else ('UNPAIRED',))

    def request_stop(self):
        """Signal work and close owned IO without waiting for a service lock."""
        self._cancel.set()
        self._circle_cancel.set()
        self._dag_cancel.set()
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
