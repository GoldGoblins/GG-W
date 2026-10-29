"""Owned, explicit LAN-session setup shared by Desktop and terminal clients.

Construction/status does not discover an address, bind a socket or create keys.
Only Start does that. Invitations and bootstrap documents contain public data;
peer signers stay in RAM. Restarting a peer requires fresh pairing. Financial
wallets and the public TESTNET/MAINNET descriptors are separate from this lab.
"""
from __future__ import annotations

from copy import deepcopy
import ipaddress
import json
import os
from pathlib import Path
import socket
import stat
import threading
from urllib.parse import unquote,urlsplit

BOOTSTRAP_SCHEMA='gg.lan-dag.bootstrap.v1'
MAX_PUBLIC_DOCUMENT=256*1024
MAX_BOOTSTRAP=8192
PRIVATE_NETWORKS=tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
COMMANDS={
    'lan.start':{'label','bind_host','port','allowed_cidr','trusted_coordinator','auto_produce','bootstrap','allow_test_tokens'},
    'lan.join_file':{'path','label','bind_host','port','allow_test_tokens'},
    'lan.status':set(),'lan.invite':set(),'lan.bootstrap':set(),'lan.bundle':set(),'lan.announce':set(),
    'lan.export_bootstrap':{'path'},'lan.export_invite':{'path'},'lan.peer_file':{'path'},
    'lan.pin':{'public_key'},'lan.peer_add':{'invite','host','port'},
    'lan.session_create':{'label','distribute','enable_test_tokens'},'lan.install':{'bundle'},
    'lan.distribute':set(),'lan.produce':{'interval_ms'},'lan.pause':set(),'lan.stop':set(),
    'lan.token_send':{'recipient_peer_key','amount_atomic'},
    'lan.circle_start':{'duration_ms','batch','amount_atomic'},'lan.circle_stop':set(),
}


def _api():
    from backend import gg_lan_dag
    return gg_lan_dag


def _public_size(value, maximum):
    try:encoded=json.dumps(value,separators=(',',':'),allow_nan=False)
    except (TypeError,ValueError,RecursionError):raise ValueError('GG_LAN_PUBLIC_DOCUMENT') from None
    if len(encoded.encode('utf-8'))>maximum:raise ValueError('GG_LAN_PUBLIC_DOCUMENT_SIZE')


def _cidr(value):
    try:network=ipaddress.ip_network(value,strict=False)
    except (ValueError,TypeError):raise ValueError('GG_LAN_SUBNET') from None
    loopback=ipaddress.ip_network('127.0.0.0/8')
    if network.version!=4 or not any(network.subnet_of(block) for block in (*PRIVATE_NETWORKS,loopback)):
        raise ValueError('GG_LAN_SUBNET')
    return network


def auto_bind_host(target=None):
    """Ask the kernel for an outgoing local IPv4; no UDP payload is sent."""
    route=target or ('192.0.2.1',9)  # Documentation-only destination for route selection.
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as probe:
            probe.connect(route)
            host=probe.getsockname()[0]
        address=ipaddress.ip_address(host)
    except (OSError,ValueError):raise ValueError('GG_LAN_AUTO_ADDRESS_UNAVAILABLE') from None
    if address.version!=4 or not any(address in block for block in PRIVATE_NETWORKS):
        raise ValueError('GG_LAN_AUTO_ADDRESS_UNAVAILABLE')
    return str(address)


def validate_bootstrap(value):
    _public_size(value,MAX_BOOTSTRAP)
    if not isinstance(value,dict) or set(value)!={'schema','coordinator_invite','allowed_cidr'} or value.get('schema')!=BOOTSTRAP_SCHEMA:
        raise ValueError('GG_LAN_BOOTSTRAP_SCHEMA')
    body=_api().validate_invite(value['coordinator_invite'])
    network=_cidr(value['allowed_cidr'])
    if ipaddress.ip_address(body['host']) not in network:raise ValueError('GG_LAN_BOOTSTRAP_SUBNET')
    return {'schema':BOOTSTRAP_SCHEMA,'coordinator_invite':deepcopy(value['coordinator_invite']),'allowed_cidr':str(network)}


def _local_path(value):
    if not isinstance(value,str) or not 1<=len(value)<=2048 or '\0' in value:raise ValueError('GG_LAN_PUBLIC_FILE_PATH')
    if value.startswith('file:'):
        uri=urlsplit(value)
        if uri.scheme!='file' or uri.netloc not in ('','localhost') or uri.query or uri.fragment:raise ValueError('GG_LAN_PUBLIC_FILE_PATH')
        value=unquote(uri.path)
        if os.name=='nt' and len(value)>2 and value[0]=='/' and value[2]==':':value=value[1:]
    if value.startswith(('\\\\','//')):raise ValueError('GG_LAN_PUBLIC_FILE_PATH')
    return Path(value)


def read_public_document(path,kind):
    if kind not in {'bootstrap','invite'}:raise ValueError('GG_LAN_PUBLIC_DOCUMENT')
    maximum=MAX_BOOTSTRAP if kind=='bootstrap' else 4096
    target=_local_path(path)
    descriptor=None
    try:
        descriptor=os.open(target,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0))
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):raise ValueError('GG_LAN_PUBLIC_FILE_TYPE')
        with os.fdopen(descriptor,'rb') as source:
            descriptor=None;raw=source.read(maximum+1)
        if len(raw)>maximum:raise ValueError('GG_LAN_PUBLIC_DOCUMENT_SIZE')
        value=json.loads(raw)
    except (OSError,UnicodeError,json.JSONDecodeError):raise ValueError('GG_LAN_PUBLIC_FILE_READ_FAILED') from None
    finally:
        if descriptor is not None:os.close(descriptor)
    if kind=='bootstrap':return validate_bootstrap(value)
    if kind!='invite':raise ValueError('GG_LAN_PUBLIC_DOCUMENT')
    _api().validate_invite(value)
    return value


def write_public_document(path,value,kind):
    if kind=='bootstrap':value=validate_bootstrap(value)
    elif kind=='invite':_api().validate_invite(value);_public_size(value,4096)
    else:raise ValueError('GG_LAN_PUBLIC_DOCUMENT')
    encoded=json.dumps(value,separators=(',',':'),sort_keys=True,allow_nan=False)+'\n'
    descriptor=None
    try:
        descriptor=os.open(_local_path(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):raise ValueError('GG_LAN_PUBLIC_FILE_TYPE')
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as target:
            descriptor=None;target.write(encoded)
    except FileExistsError:raise ValueError('GG_LAN_PUBLIC_FILE_EXISTS') from None
    except OSError:raise ValueError('GG_LAN_PUBLIC_FILE_WRITE_FAILED') from None
    finally:
        if descriptor is not None:os.close(descriptor)
    return {'state':'EXPORTED','kind':kind,'public_only':True,'ephemeral_private_keys_exported':False}


def _stopped():
    return {'state':'STOPPED','mode':'PRIVATE_LAN_SESSION_EXPERIMENT','producer_count':0,'worker_count':0,
            'canonical_finalized':0,'blocks_admitted':0,'transactions_validated':0,'frontier_size':0,
            'block_graph':{'schema':'gg.block-graph.v1','topology':'MULTIPARENT_DAG','producer_count':0,
                           'history_limit':128,'blocks':[],'edges':[],'metrics':{}},
            'lan':{'state':'STOPPED','scope':'PRIVATE_LAN_SESSION_EXPERIMENT','configured_peers':0,
                   'authenticated_peers':[],'physical_hosts_verified':False,'transactions_enabled':False,
                   'traffic_confidentiality':False,'mainnet_enabled':False},
            'lan_setup':{'active':False,'starting':False,'coordinator':False,'invites':[],
                         'invite_count':0,'bundle_available':False,'distribution':[],
                         'ephemeral_keys':True,'new_pairing_after_restart':True}}


class LanDagRuntime:
    def __init__(self):
        self._control=threading.RLock()
        self._peer=None;self._starting=False;self._stop_requested=threading.Event()
        self._invites={};self._bundle=None;self._bootstrap=None
        self._distribution=[];self._allowed='';self._trusted='';self._auto_produce=False
        self._announcement_error=''
        self._revision=0
        self._allow_test_tokens=False

    @property
    def active(self):
        return self._peer is not None or self._starting

    def _owned(self):
        peer=self._peer
        if peer is None:raise ValueError('GG_LAN_OWNED_PEER_REQUIRED')
        return peer

    def telemetry_revision(self):
        peer=self._peer
        return ('LAN',self._revision,self._starting,None if peer is None else peer.telemetry_revision())

    def snapshot(self):
        peer=self._peer
        if peer is None:
            body=_stopped();body['lan_setup'].update(active=self._starting,starting=self._starting)
            if self._starting:body['lan']['state']='STARTING'
            return body
        body=peer.snapshot()
        candidates=[]
        invites=self._all_invites(peer)
        for key,invite in tuple(invites.items()):
            row=invite['body']
            candidates.append({'label':row['label'],'host':row['host'],'port':row['port'],
                               'peer_key':key,'producer_keys':list(row['producer_keys']),
                               'local':key==peer.public_key,'allow_test_tokens':row.get('allow_test_tokens') is True})
        body['lan'].update(mainnet_enabled=False,allowed_cidr=self._allowed)
        body['lan_setup']={'active':True,'starting':self._starting,'coordinator':self._trusted==peer.public_key,
                           'invite_count':len(candidates),'invites':candidates,
                           'public_invite':deepcopy(self._invites.get(peer.public_key)),
                           'bootstrap':deepcopy(self._bootstrap),'bundle_available':self._bundle is not None,
                           'distribution':deepcopy(self._distribution),'auto_produce':self._auto_produce,
                           'announcement_error':self._announcement_error,
                           'allow_test_tokens':self._allow_test_tokens,
                           'ephemeral_keys':True,'new_pairing_after_restart':True}
        return body

    def _all_invites(self,peer):
        result=dict(self._invites)
        if self._trusted==peer.public_key:
            for invite in peer.candidate_invites():
                key=invite['body']['peer_key']
                if key in result or len(result)<3:result[key]=invite
        return result

    def announce(self):
        peer=self._owned()
        if self._bootstrap is None or self._trusted==peer.public_key:raise ValueError('GG_LAN_COORDINATOR_BOOTSTRAP_REQUIRED')
        try:
            peer.announce_invite(self._bootstrap['coordinator_invite'])
            self._announcement_error=''
        except (ValueError,OSError):
            # Keep the owned pairing listener available for a finite explicit
            # retry; no endless connection loop or implicit roster approval.
            self._announcement_error='GG_LAN_ANNOUNCEMENT_UNAVAILABLE'
        self._revision+=1
        return self.snapshot()

    def start(self,**options):
        if set(options)-COMMANDS['lan.start']:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
        with self._control:
            if self.active:raise ValueError('GG_LAN_ALREADY_STARTED')
            self._starting=True;self._stop_requested.clear()
            self._revision+=1
            peer=None
            try:
                bootstrap=validate_bootstrap(options['bootstrap']) if options.get('bootstrap') is not None else None
                trusted=options.get('trusted_coordinator')
                allowed=options.get('allowed_cidr')
                route=None
                if bootstrap:
                    coordinator=bootstrap['coordinator_invite']['body']
                    if trusted is not None and trusted!=coordinator['peer_key']:raise ValueError('GG_LAN_COORDINATOR_MISMATCH')
                    if allowed is not None and str(_cidr(allowed))!=bootstrap['allowed_cidr']:raise ValueError('GG_LAN_BOOTSTRAP_SUBNET')
                    trusted=coordinator['peer_key'];allowed=bootstrap['allowed_cidr'];route=(coordinator['host'],coordinator['port'])
                host=options.get('bind_host','auto')
                if host=='auto':host=auto_bind_host(route)
                auto_produce=options.get('auto_produce',bootstrap is not None)
                allow_test_tokens=options.get('allow_test_tokens',False)
                if type(allow_test_tokens) is not bool:raise ValueError('GG_LAN_OPTION')
                peer=_api().LanDagPeer(options.get('label','GG LAN node'),host,options.get('port',16120),
                                       trusted,auto_produce,allowed_cidr=allowed,allow_test_tokens=allow_test_tokens)
                self._peer=peer
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                invite=peer.start_pairing()
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                self._allowed=str(peer.allowed);self._trusted=trusted or peer.public_key
                self._auto_produce=auto_produce;self._invites={peer.public_key:invite}
                self._allow_test_tokens=allow_test_tokens
                self._bundle=None;self._distribution=[]
                self._bootstrap=bootstrap or ({'schema':BOOTSTRAP_SCHEMA,'coordinator_invite':deepcopy(invite),'allowed_cidr':self._allowed} if self._trusted==peer.public_key else None)
                self._announcement_error=''
                if bootstrap:self.announce()
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                self._starting=False
                self._revision+=1
                return self.snapshot()
            except BaseException:
                if peer is not None:peer.stop()
                self._peer=None;self._invites={};self._bundle=None;self._bootstrap=None
                self._allow_test_tokens=False
                raise
            finally:self._starting=False

    def add_peer(self,*,invite=None,host=None,port=None):
        with self._control:
            peer=self._owned()
            if invite is None:
                try:address=ipaddress.ip_address(host)
                except (ValueError,TypeError):raise ValueError('GG_LAN_ADDRESS') from None
                if address not in _cidr(self._allowed):raise ValueError('GG_LAN_SUBNET')
                invite=_api().fetch_invite(host,port)
            elif host is not None or port is not None:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            body=_api().validate_invite(invite)
            if ipaddress.ip_address(body['host']) not in _cidr(self._allowed):raise ValueError('GG_LAN_SUBNET')
            if body['peer_key'] not in self._invites and len(self._invites)>=3:raise ValueError('GG_LAN_THREE_PEERS_REQUIRED')
            self._invites[body['peer_key']]=deepcopy(invite)
            self._revision+=1
            return self.snapshot()

    def request_stop(self):
        self._stop_requested.set()
        self._revision+=1
        peer=self._peer
        if peer is not None:peer.request_stop()

    def stop(self):
        self.request_stop()
        with self._control:
            peer=self._peer
            if peer is not None:peer.stop()
            self._peer=None;self._starting=False;self._invites={};self._bundle=None;self._bootstrap=None;self._distribution=[]
            self._allow_test_tokens=False
            self._revision+=1
            return self.snapshot()

    def dispatch(self,command,args=None):
        if args is None:args={}
        if command not in COMMANDS or not isinstance(args,dict) or set(args)-COMMANDS[command]:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
        _public_size(args,MAX_PUBLIC_DOCUMENT+2048 if command=='lan.install' else 16384)
        if command=='lan.status':return self.snapshot()
        if command=='lan.start':return self.start(**args)
        if command=='lan.join_file':
            options=dict(args)
            bootstrap=read_public_document(options.pop('path',None),'bootstrap')
            return self.start(bootstrap=bootstrap,**options)
        if command=='lan.stop':return self.stop()
        with self._control:
            peer=self._owned()
            if command=='lan.invite':return peer.public_invite()
            if command=='lan.announce':return self.announce()
            if command=='lan.bootstrap':return deepcopy(self._bootstrap)
            if command=='lan.export_bootstrap':
                if self._bootstrap is None:raise ValueError('GG_LAN_BOOTSTRAP_REQUIRED')
                return write_public_document(args['path'],self._bootstrap,'bootstrap')
            if command=='lan.export_invite':return write_public_document(args['path'],peer.public_invite(),'invite')
            if command=='lan.peer_file':return self.add_peer(invite=read_public_document(args['path'],'invite'))
            if command=='lan.bundle':
                if self._bundle is None:raise ValueError('GG_LAN_SESSION_REQUIRED')
                return deepcopy(self._bundle)
            if command=='lan.pin':
                peer.pin_coordinator(args['public_key']);self._trusted=args['public_key'];self._bootstrap=None
                self._revision+=1
                return self.snapshot()
            if command=='lan.peer_add':return self.add_peer(**args)
            if command=='lan.session_create':
                distribute=args.get('distribute',False)
                enabled=args.get('enable_test_tokens',False)
                if type(distribute) is not bool or type(enabled) is not bool:raise ValueError('GG_LAN_OPTION')
                bundle=peer.create_session(list(self._all_invites(peer).values()),args.get('label','GG LAN'),enable_test_tokens=enabled)
                peer.install_session(bundle);self._bundle=deepcopy(bundle)
                if distribute:self._distribution=peer.distribute_session(bundle)
                self._revision+=1
                return self.snapshot()
            if command=='lan.install':
                result=peer.install_session(args['bundle']);self._bundle=deepcopy(args['bundle'])
                self._revision+=1
                return self.snapshot()
            if command=='lan.distribute':
                if self._bundle is None:raise ValueError('GG_LAN_SESSION_REQUIRED')
                self._distribution=peer.distribute_session(self._bundle)
                self._revision+=1
                return self.snapshot()
            if command=='lan.produce':peer.start_producing(args.get('interval_ms',250));self._revision+=1;return self.snapshot()
            if command=='lan.pause':peer.stop_producing();self._revision+=1;return self.snapshot()
            if command=='lan.token_send':
                peer.token_send(args['recipient_peer_key'],args['amount_atomic']);self._revision+=1;return self.snapshot()
            if command=='lan.circle_start':
                peer.start_token_circle(args.get('duration_ms',10000),args.get('batch',8),args.get('amount_atomic','1'))
                self._revision+=1;return self.snapshot()
            if command=='lan.circle_stop':
                peer.stop_token_circle();self._revision+=1;return self.snapshot()
        raise ValueError('GG_LAN_ACTION_ARGUMENTS')


_DESKTOP=LanDagRuntime()


def desktop_manager():return _DESKTOP
def active_manager():return _DESKTOP if _DESKTOP.active else None
def snapshot():return _DESKTOP.snapshot()
def telemetry_revision():return _DESKTOP.telemetry_revision()
def request_stop():return _DESKTOP.request_stop()
def stop():return _DESKTOP.stop()


def action(name,args=None):
    if not isinstance(name,str) or not name.startswith('lan_'):raise ValueError('GG_LAN_ACTION_ARGUMENTS')
    command='lan.'+name[4:]
    return _DESKTOP.dispatch(command,args)
