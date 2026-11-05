"""Owned, explicit LAN-session setup shared by Desktop and terminal clients.

Construction/status does not discover an address, bind a socket or create keys.
Only Start does that. Invitations and bootstrap documents contain public data;
peer signers stay in RAM unless an explicit encrypted node profile is selected.
Profiles restore the same verified private-LAN session. Financial
wallets and the public TESTNET/MAINNET descriptors are separate from this lab.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import http.client
import ipaddress
import json
import os
import re
from pathlib import Path
import socket
import stat
import threading
import time
from urllib.parse import unquote,urlsplit

BOOTSTRAP_SCHEMA='gg.lan-dag.bootstrap.v1'
MAX_PUBLIC_DOCUMENT=256*1024
MAX_BOOTSTRAP=32*1024
PRIVATE_NETWORKS=tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
COMMANDS={
    'lan.start':{'label','bind_host','port','allowed_cidr','trusted_coordinator','auto_produce','bootstrap','allow_test_tokens','allow_dag_transactions','profile','node_role'},
    'lan.join_file':{'path','label','bind_host','port','allow_test_tokens','allow_dag_transactions','profile','node_role'},
    'lan.resume':{'profile'},
    'lan.archive_import':{'profile','path','timeout'},
    'lan.financial_history_export':{'profile','path','validator','observer','timeout'},
    'lan.financial_history_verify':{'profile','path','timeout'},
    'lan.financial_history_restore':{'profile','path','destination','timeout'},
    'lan.observer_history_restore':{'profile','path','observer','timeout'},
    'lan.status':set(),'lan.invite':set(),'lan.bootstrap':set(),'lan.bundle':set(),'lan.announce':set(),
    'lan.export_bootstrap':{'path'},'lan.export_invite':{'path'},'lan.peer_file':{'path'},
    'lan.pin':{'public_key'},'lan.peer_add':{'invite','host','port'},
    'lan.session_create':{'label','distribute','enable_test_tokens','enable_dag_transactions','enable_consensus','enable_segmented','enable_financial','financial_accounts'},'lan.install':{'bundle'},
    'lan.account_create':{'profile','label'},'lan.account_open':{'profile'},'lan.account_select':{'profile'},'lan.account_status':{'profile'},
    'lan.account_close':{'profile'},
    'lan.account_review':{'profile','payments','path'},'lan.account_sign':{'profile'},
    'lan.account_submit':{'profile','producer_index','transactions_per_block','relay_peer'},'lan.account_export':{'profile','path','batch'},
    'lan.financial_relay_start':{'producer_index','transactions_per_block'},'lan.financial_relay_stop':set(),
    'lan.financial_relay_status':set(),
    'lan.financial_submit':{'payments','producer_index','transactions_per_block'},'lan.financial_submit_file':{'path','producer_index','transactions_per_block'},'lan.financial_resume':{'producer_index'},'lan.financial_receipt':{'block','index'},
    'lan.validator_create':{'profile','label','p2p_port'},'lan.validator_open':{'profile'},
    'lan.validator_start':{'profile'},'lan.validator_stop':{'profile'},'lan.validator_invite':{'profile'},
    'lan.validator_index_transition':{'profile','timeout'},
    'lan.observer_create':{'profile','label','p2p_port','producer_slot'},'lan.observer_open':{'profile'},
    'lan.observer_start':{'profile'},'lan.observer_stop':{'profile'},
    'lan.validator_transition_create':{'profile','label','p2p_port','owner_profile'},
    'lan.transition_invite':{'profiles','path','owner_profile'},'lan.transition_prepare':{'invites','invite_paths','label','path','owner_profile'},
    'lan.transition_commit':{'profile','document','path','timeout'},
    'lan.distribute':set(),'lan.produce':{'interval_ms'},'lan.pause':set(),'lan.stop':set(),
    'lan.token_send':{'recipient_peer_key','amount_atomic'},
    'lan.circle_start':{'duration_ms','batch','amount_atomic'},'lan.circle_stop':set(),
    'lan.dag_stress_start':{'duration_ms','transactions_per_block','interval_ms'},'lan.dag_stress_stop':set(),
    'lan.dag_produce_start':{'duration_ms','transactions_per_block','interval_ms'},'lan.dag_produce_stop':set(),
    'lan.resources':{'budget'},'lan.hardware_test_start':{'duration_ms','max_transactions_per_block'},
    'lan.hardware_test_stop':set(),
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


def read_signed_payments(path,anchor,*,authenticated=False):
    """Read one explicitly named bounded public file, never a wallet vault."""
    from backend import gg_financial_wire as wire
    from backend.platform_files import is_link,secure_open,NOFOLLOW
    target=_local_path(path)
    if is_link(target):raise ValueError('GG_LAN_PUBLIC_FILE_TYPE')
    try:
        descriptor=secure_open(target,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|NOFOLLOW)
        with os.fdopen(descriptor,'rb') as source:
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):raise ValueError('GG_LAN_PUBLIC_FILE_TYPE')
            if not 0<info.st_size<=wire.MAX_RAW:raise ValueError('GG_FINANCIAL_PAYMENT_DOCUMENT_SIZE')
            raw=source.read(wire.MAX_RAW+1)
    except OSError:raise ValueError('GG_LAN_PUBLIC_FILE_READ_FAILED') from None
    return wire.decode_payment_document(raw,anchor,authenticated=authenticated)


def read_account_intent(path,anchor,address):
    """Finite public recipient intent, independently bound to sender/network."""
    from backend import gg_financial_wire as wire
    from backend.gg_dag_json import preflight_lan_block
    from backend.gg_node_store import unpack
    from backend.platform_files import secure_open,NOFOLLOW,is_link
    target=_local_path(path)
    if is_link(target):raise ValueError('GG_LAN_PUBLIC_FILE_TYPE')
    try:
        fd=secure_open(target,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|NOFOLLOW)
        with os.fdopen(fd,'rb') as source:
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=wire.MAX_RAW:raise ValueError('GG_ACCOUNT_INTENT_FILE_SIZE')
            raw=source.read(wire.MAX_RAW+1)
        preflight_lan_block(raw,wire.MAX_PAYMENTS);value=unpack(raw)
        if (not isinstance(value,dict) or set(value)!={'schema','genesis_hash','sender','payments'}
                or value['schema']!='gg.financial.payment-intent.v1' or value['genesis_hash']!=anchor['genesis_hash']
                or value['sender']!=address or not isinstance(value['payments'],list) or not 1<=len(value['payments'])<=wire.MAX_PAYMENTS):raise ValueError()
        return value['payments']
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError):raise ValueError('GG_ACCOUNT_INTENT_FILE_INVALID') from None


def export_account_original(profile,path,number=None):
    from backend.platform_files import secure_open,NOFOLLOW,sync_directory,is_link
    from backend import gg_financial_account as accounts,gg_node_store as nodes,gg_consensus_profile as validators,gg_observer_profile as observers
    target=_local_path(path).absolute()
    protected=(profile.root.parent,accounts.ROOT,nodes.ROOT,validators.ROOT,observers.ROOT)
    if (any(is_link(item) for item in (target,*target.parents)) or any(target.resolve().is_relative_to(Path(root).resolve()) for root in protected)):raise ValueError('GG_ACCOUNT_EXPORT_DESTINATION')
    raw=profile.original(number)
    try:
        fd=secure_open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as destination:destination.write(raw);destination.flush();os.fsync(destination.fileno())
        sync_directory(target.parent)
    except FileExistsError:raise ValueError('GG_ACCOUNT_EXPORT_EXISTS') from None
    except OSError:raise ValueError('GG_ACCOUNT_EXPORT_FAILED') from None
    return {'state':'EXPORTED','signed_public_payments_only':True,'private_keys_exported':False,'bytes':len(raw)}


def read_public_document(path,kind):
    if kind not in {'bootstrap','invite','network_transition'}:raise ValueError('GG_LAN_PUBLIC_DOCUMENT')
    maximum=MAX_BOOTSTRAP if kind=='bootstrap' else MAX_PUBLIC_DOCUMENT+4096 if kind=='network_transition' else _api().MAX_INVITE
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
    if kind=='network_transition':
        from backend.gg_network_transition import _target
        try:_target(value,value['body']['bundle']['body']['coordinator'])
        except (ValueError,KeyError,TypeError):raise ValueError('GG_LAN_PUBLIC_DOCUMENT') from None
        return value
    if kind!='invite':raise ValueError('GG_LAN_PUBLIC_DOCUMENT')
    _api().validate_invite(value)
    return value


def write_public_document(path,value,kind):
    if kind=='bootstrap':value=validate_bootstrap(value)
    elif kind=='invite':_api().validate_invite(value);_public_size(value,_api().MAX_INVITE)
    elif kind=='network_transition':
        from backend.gg_network_transition import _target
        try:_target(value,value['body']['bundle']['body']['coordinator'])
        except (ValueError,KeyError,TypeError):raise ValueError('GG_LAN_PUBLIC_DOCUMENT') from None
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
    capabilities=_api().dag_stress_capabilities()
    stress={**capabilities,'enabled':False,'local_opt_in':False,'role':'',
            'can_start':False,'state':'IDLE','participants':[],'elapsed_ms':0,
            'blocks':0,'transactions':0,'all_peers_synced':False,
            'acknowledged_blocks':None,'acknowledged_transactions':None,
            'acknowledged_bps':None,'acknowledged_tps':None,'stop_reason':'','last_error':''}
    return {'state':'STOPPED','mode':'PRIVATE_LAN_SESSION_EXPERIMENT','producer_count':0,'worker_count':0,
            'canonical_finalized':0,'blocks_admitted':0,'transactions_validated':0,'frontier_size':0,
            'block_graph':{'schema':'gg.block-graph.v1','topology':'MULTIPARENT_DAG','producer_count':0,
                           'history_limit':128,'blocks':[],'edges':[],'metrics':{}},
            'lan':{'state':'STOPPED','scope':'PRIVATE_LAN_SESSION_EXPERIMENT','configured_peers':0,
                   'authenticated_peers':[],'physical_hosts_verified':False,'transactions_enabled':False,
                   'traffic_confidentiality':False,'mainnet_enabled':False},
            'dag_stress':stress,
            'dag_production':{**_api().dag_production_capabilities(),'enabled':False,'can_start':False,
                'state':'IDLE','worker_active':False,'worker_count':0,'production':None,'duration_ms':0,
                'transactions_per_block':0,'interval_ms':1000,'elapsed_ms':0,'last_error':'','stop_reason':''},
            'lan_setup':{'active':False,'starting':False,'coordinator':False,'invites':[],'windows_profile_controls':os.name=='nt',
                         'invite_count':0,'bundle_available':False,'distribution':[],
                         'ephemeral_keys':True,'new_pairing_after_restart':True}}


class LanDagRuntime:
    def __init__(self):
        self._control=threading.RLock()
        self._peer=None;self._starting=False;self._stop_requested=threading.Event()
        self._archive_importing=False
        self._network_transitioning=False
        self._invites={};self._bundle=None;self._bootstrap=None
        self._distribution=[];self._allowed='';self._trusted='';self._auto_produce=False
        self._announcement_error=''
        self._revision=0
        self._allow_test_tokens=False
        self._allow_dag_transactions=False
        self._validator_profiles={};self._validator_nodes={};self._validator_errors={};self._validator_starting=set();self._validator_transitioning=set()
        self._validator_lock=threading.RLock();self._validator_cancel=threading.Event();self._validator_thread=None
        self._observer_inbox=None
        self._observers=None
        self._account_profiles={};self._account_reviews={};self._selected_account=None
        self._account_lock=threading.RLock()

    @property
    def active(self):
        return self._peer is not None or self._starting or self._archive_importing or self._network_transitioning

    def _owned(self):
        peer=self._peer
        if peer is None:raise ValueError('GG_LAN_OWNED_PEER_REQUIRED')
        return peer

    def telemetry_revision(self):
        peer=self._peer
        with self._validator_lock:
            voters=tuple((name,node.snapshot().get('certificate_height'),node.snapshot().get('state'),node.snapshot().get('canonical_order_blocks')) for name,node in self._validator_nodes.items())
        exchange=getattr(peer,'_proof_service',None) if peer is not None else None
        return ('LAN',self._revision,self._starting,voters,None if peer is None else peer.telemetry_revision(),
                exchange.telemetry_revision() if exchange is not None else None)

    def _new_proof_exchange(self,peer):
        from backend.gg_dag_proof_sync import ProofExchange
        def sources():
            with self._validator_lock:return tuple(self._validator_nodes.values())
        if peer._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
            from backend.gg_financial_proof_sync import FinancialProofExchange
            return FinancialProofExchange(peer,sources,start=False)
        if peer._bundle['body']['schema']=='gg.lan-dag.session.v5':
            from backend.gg_segmented_proof_sync import SegmentedProofExchange
            return SegmentedProofExchange(peer,sources,start=False)
        return ProofExchange(peer,sources)

    def _attach_peer(self,peer):
        from backend.gg_observer_enrollment import EnrollmentInbox
        def profiles():
            with self._validator_lock:return tuple(self._validator_profiles.values())
        self._peer=peer;peer._proof_factory=self._new_proof_exchange
        self._observer_inbox=EnrollmentInbox(peer,profiles);peer._observer_admissions=self._observer_inbox

    def observer_unlocked(self,name):
        observers=self._observers
        return observers is not None and observers.unlocked(name)

    def _observer_controls(self):
        peer=self._owned()
        if self._stop_requested.is_set():raise ValueError('GG_OBSERVER_OWNER_STOPPED')
        with self._validator_lock:
            if self._observers is None:
                from backend.gg_observer_control import ObserverControl
                self._observers=ObserverControl(self)
            return self._observers

    def _consensus_summary(self,peer):
        membership=peer._bundle['body'].get('consensus') if peer._bundle else None
        with self._validator_lock:
            nodes={name:node.snapshot() for name,node in self._validator_nodes.items()}
            profiles={name:profile.snapshot() for name,profile in self._validator_profiles.items()}
            starting=set(self._validator_starting);transitioning=set(self._validator_transitioning);errors=dict(self._validator_errors)
        owned=[]
        for name,status in profiles.items():
            owned.append({**status,**nodes.get(name,{}),'state':'INDEX_TRANSITION' if name in transitioning else 'STARTING' if name in starting else nodes.get(name,status).get('state'),
                'last_error':nodes.get(name,status).get('last_error','') or errors.get(name,'')})
        certified=[row for row in nodes.values() if row.get('canonical_finality') is True]
        exchange=getattr(peer,'_proof_service',None)
        remote=exchange.snapshot() if exchange is not None else None
        if remote is not None and remote.get('canonical_finality') is True:certified.append(remote)
        latest=max(certified,key=lambda row:row['certificate_height']) if certified else None
        conflict=remote is not None and remote['state']=='FAULT' or any(row.get('last_error')=='GG_CONSENSUS_CONFLICTING_CERTIFICATE' for row in owned) or latest is not None and any(
            row['certificate_height']==latest['certificate_height'] and row['certificate_id']!=latest['certificate_id'] for row in certified)
        if conflict:latest=None
        members=[]
        if membership:
            from backend.gg_consensus_membership import public_label
            for index,invite in enumerate(membership['validators']):
                owner=peer._roster.get(invite['body']['owner_peer_key'],{})
                local=next((row for row in nodes.values() if row['validator_index']==index),None)
                members.append({'index':index,'label':public_label(invite['body']),'owner_label':owner.get('label',''),
                    'local_owner':invite['body']['owner_peer_key']==peer.public_key,'state':local['state'] if local else 'UNOBSERVED',
                    'validator_key':invite['body']['validator_key'],'node_key':invite['body']['node_key']})
        financial=peer._bundle is not None and peer._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7')
        commitment=(latest.get('financial_dag_commitment') or latest.get('dag_segmented_commitment') or latest.get('dag_commitment')) if latest else None
        return {'scope':'PRIVATE_LAN_EXPERIMENT','anchor_bound':membership is not None,
            'chain_id':membership['chain_id'] if membership else '', 'validator_count':len(members),'quorum_required':3 if membership else None,
            'own_running':sum(row.get('owned_native_process') is True and name not in starting for name,row in nodes.items()),'profiles':owned,'members':members,
            'storage_transition_profiles':sorted(transitioning),
            'state':'FAULT' if conflict else 'CERTIFIED' if latest else 'WAITING_FOR_CERTIFICATE' if membership else 'UNBOUND',
            'certificate_height':latest['certificate_height'] if latest else None,'verified_at':latest.get('verified_at') if latest else None,
            'certified_dag_blocks':commitment.get('blocks') if commitment else None,
            'certified_dag_transactions':commitment.get('applied' if financial else 'transactions') if commitment else None,
            'last_error':remote['last_error'] if remote is not None and remote['state']=='FAULT' else 'GG_CONSENSUS_CONFLICTING_CERTIFICATE' if conflict else '', 'automatic_checkpoint_submission':not financial}

    def snapshot(self):
        peer=self._peer
        with self._account_lock:account_profiles=tuple(self._account_profiles.values());selected_account=self._selected_account
        account_view={'profiles':[profile.snapshot() for profile in account_profiles],'selected_profile':selected_account}
        if peer is None:
            body=_stopped();body['lan_setup'].update(active=self._starting or self._network_transitioning,starting=self._starting)
            body['financial_account_profiles']=account_view
            if self._starting:body['lan']['state']='STARTING'
            if self._network_transitioning:body['lan']['state']='NETWORK_TRANSITION'
            return body
        self._watch_selected_account(peer)
        body=peer.snapshot();body['financial_account_profiles']=account_view
        exchange=getattr(peer,'_proof_service',None)
        if exchange is not None:body['dag_proofs']=exchange.snapshot()
        body['dag_consensus']=self._consensus_summary(peer)
        from backend.gg_observer_control import empty_snapshot
        observers=self._observers
        body['native_observers']=observers.snapshot() if observers is not None else empty_snapshot()
        body['lan'].setdefault('participation',{})['native_full_observer']=body['native_observers']['own_running']>0
        if self._observer_inbox is not None:body['observer_admissions']=self._observer_inbox.snapshot()
        segmented=peer._bundle is not None and peer._bundle['body']['schema']=='gg.lan-dag.session.v5'
        financial=peer._bundle is not None and peer._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7')
        if body['dag_consensus']['state']!='FAULT' and not (segmented or financial):
            with self._validator_lock:memberships=[node.canonical_membership() for node in self._validator_nodes.values()]
            if exchange is not None:memberships.append(exchange.canonical_membership())
            memberships=[row for row in memberships if row is not None]
            if memberships:
                height,members=max(memberships,key=lambda row:row[0]);graph=body['block_graph']
                with peer._engine._lock:count=sum(key in peer._engine._records for key in members)
                body['canonical_finalized']=count;graph.update(canonical_finalized=count,canonical_certificate_height=height,canonical_members=len(members))
                for block in graph.get('blocks',[]):
                    if block['hash'] in members:block.update(canonical_membership_verified=True,canonical_index=members[block['hash']])
        if peer.node_role=='light':body['test_accounts']=[]
        proofs=body.get('dag_proofs',{})
        if proofs.get('certified_accounts') and not financial:
            own=peer.public_invite()['body']['producer_keys'];identities=body['lan'].get('producer_identities',[])
            certified_accounts=[]
            for leaf in proofs['certified_accounts']:
                index=(peer._bundle['body']['public_genesis']['genesis']['producers'] if segmented else peer._engine._producer_public).index(leaf['address'])
                label=next((row.get('display_name') for row in identities if row.get('index')==index),peer.label)
                certified_accounts.append({'producer_index':index,'address':leaf['address'],'balance_atomic':leaf['balance_atomic'],
                    'nonce':leaf['nonce'],'display_name':label,'local':leaf['address'] in own,'verification_scope':'SDK_CERTIFIED_MEMBERSHIP'})
            body['certified_test_accounts']=certified_accounts
            if peer.node_role=='light':body['test_accounts']=deepcopy(certified_accounts)
        body['lan'].setdefault('participation',{})['consensus_validator']=body['dag_consensus']['own_running']>0
        candidates=[]
        invites=self._all_invites(peer)
        for key,invite in tuple(invites.items()):
            row=invite['body']
            candidates.append({'label':row['label'],'host':row['host'],'port':row['port'],
                               'peer_key':key,'producer_keys':list(row['producer_keys']),
                               'local':key==peer.public_key,'node_role':row.get('node_role','producer'),'allow_test_tokens':row.get('allow_test_tokens') is True,
                               'allow_dag_transactions':row.get('allow_dag_transactions') is True,
                               'validator_invite_count':len(row.get('consensus_invites',[]))})
        body['lan'].update(mainnet_enabled=False,allowed_cidr=self._allowed)
        body['lan_setup']={'active':True,'starting':self._starting,'coordinator':self._trusted==peer.public_key,
                           'windows_profile_controls':os.name=='nt',
                           'invite_count':len(candidates),'invites':candidates,
                           'validator_invite_count':sum(row['validator_invite_count'] for row in candidates),
                           'public_invite':deepcopy(invites.get(peer.public_key)),
                           'bootstrap':deepcopy(self._bootstrap),'bundle_available':self._bundle is not None,
                           'distribution':deepcopy(self._distribution),'auto_produce':self._auto_produce,
                           'announcement_error':self._announcement_error,
                           'allow_test_tokens':self._allow_test_tokens,
                           'allow_dag_transactions':self._allow_dag_transactions,
                           'ephemeral_keys':not body['lan'].get('storage',{}).get('enabled',False),
                           'new_pairing_after_restart':not body['lan'].get('storage',{}).get('enabled',False)}
        return body

    def account_unlocked(self,name):
        with self._account_lock:profile=self._account_profiles.get(name)
        return profile is not None and not profile._closed and not profile._failed

    def _watch_selected_account(self,peer):
        with self._account_lock:profile=self._account_profiles.get(self._selected_account)
        service=getattr(peer,'_proof_service',None)
        if profile is None or service is None or peer._bundle['body']['schema']!='gg.lan-dag.session.v7':return
        anchor=profile.anchor()
        if anchor is not None and anchor!=service.anchor:return
        service.select_owned_account(profile.public_address())

    def _account_status(self,profile):
        # Local cached node view only. Reading status must not fetch a peer,
        # bind a wallet, advance its signer floor or create any signature.
        result=profile.snapshot();peer=self._peer;service=getattr(peer,'_proof_service',None) if peer is not None else None
        observed={'state':'OFFLINE','value':None,'basis':'CURRENT_OWNED_CLI_CERTIFIED_VIEW','certificate_is_network_liveness':False}
        if service is not None and peer._bundle['body']['schema']=='gg.lan-dag.session.v7':
            if profile.anchor() is not None and profile.anchor()!=service.anchor:observed['state']='NETWORK_MISMATCH'
            else:
                view=service.snapshot();row=next((row for row in view['certified_accounts'] if row['address']==profile.public_address()),None)
                observed['state']='FAULT' if view['state']=='FAULT' else 'CERTIFIED' if row is not None else 'WAITING_FOR_ACCOUNT_PROOF'
                if observed['state']=='CERTIFIED':observed['value']=deepcopy(row)
        result['observed_account']=observed;return result

    def _account_command(self,command,args):
        from backend import gg_financial_account as accounts,gg_financial_wire as wire
        with self._control:
            with self._account_lock:name=args.get('profile',self._selected_account)
            if command in ('lan.account_create','lan.account_open'):
                if type(name) is not str:raise ValueError('GG_ACCOUNT_PROFILE_NAME')
                with self._account_lock:existing=self._account_profiles.get(name);count=len(self._account_profiles)
                if existing is not None:
                    if command=='lan.account_create':raise ValueError('GG_ACCOUNT_PROFILE_EXISTS_USE_OPEN')
                else:
                    if count>=16:raise ValueError('GG_ACCOUNT_LOCAL_PROFILE_LIMIT')
                    existing=accounts.AccountProfile.create(name,label=args.get('label',name)) if command=='lan.account_create' else accounts.AccountProfile.open(name)
                    with self._account_lock:self._account_profiles[name]=existing
                with self._account_lock:
                    if self._selected_account is None:self._selected_account=name
                self._revision+=1;return self.snapshot()
            if command=='lan.account_status' and name is None:return self.snapshot()['financial_account_profiles']
            with self._account_lock:profile=self._account_profiles.get(name)
            if profile is None:raise ValueError('GG_ACCOUNT_PROFILE_NOT_OPEN')
            if command=='lan.account_status':return self._account_status(profile)
            if command=='lan.account_close':
                with self._account_lock:
                    self._account_profiles.pop(name,None);self._account_reviews.pop(name,None)
                    if self._selected_account==name:self._selected_account=None
                peer=self._peer;service=getattr(peer,'_proof_service',None) if peer is not None else None
                if service is not None and hasattr(service,'forget_owned_account'):service.forget_owned_account(profile.public_address())
                profile.close();self._revision+=1;return self.snapshot()
            if command=='lan.account_select':
                peer=self._peer;service=getattr(peer,'_proof_service',None) if peer is not None else None
                if service is not None and profile.anchor() is not None and profile.anchor()!=service.anchor:raise ValueError('GG_ACCOUNT_NETWORK_ALREADY_BOUND')
                with self._account_lock:self._selected_account=name
                self._revision+=1;return self.snapshot()
            if command=='lan.account_export':return export_account_original(profile,args.get('path'),args.get('batch'))
            peer=self._owned();service=getattr(peer,'_proof_service',None)
            if peer._bundle is None or peer._bundle['body']['schema']!='gg.lan-dag.session.v7' or service is None:raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
            self._watch_selected_account(peer);profile.bind(service.anchor)
            def check():
                if self._stop_requested.is_set() or peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                service.context.check()
            check();packet=service.requested_proof('account',profile.public_address(),check=check,cancel=self._stop_requested)
            if service.verifier.binary is not None:profile._binary=service.verifier.binary;profile._stamp=service.verifier.stamp
            if command=='lan.account_review':
                if ('payments' in args)==('path' in args):raise ValueError('GG_ACCOUNT_PAYMENT_INTENT')
                values=read_account_intent(args['path'],service.anchor,profile.public_address()) if 'path' in args else args['payments']
                review=profile.review(values,packet,check=check)
                with self._account_lock:self._account_reviews[name]=review
                return {'state':'REVIEWED',**review.summary()}
            profile.remember_account(packet)
            if command=='lan.account_sign':
                with self._account_lock:review=self._account_reviews.get(name)
                if review is None:raise ValueError('GG_ACCOUNT_REVIEW_REQUIRED')
                profile.sign(review,check=check)
                with self._account_lock:self._account_reviews.pop(name,None)
                self._revision+=1
                return {'state':'SIGNED_DURABLY','signed_payments':review.summary()['payments'],'original_durable':True,'payments_executed_asserted':False}
            if command=='lan.account_submit':
                raw=profile.pending(packet)
                if raw is None:return {'state':'NO_UNCONSUMED_ORIGINALS','payments_executed_asserted':False}
                if peer.node_role!='producer' or 'relay_peer' in args:
                    if 'producer_index' in args or 'transactions_per_block' in args:raise ValueError('GG_ACCOUNT_RELAY_RECEIVER_CHOOSES_PRODUCER')
                    result=service.account_relay.submit_document(raw,args.get('relay_peer'));self._revision+=1
                    return {**result,'account_originals_durable':True,'payments_executed_asserted':False}
                values=wire.decode_payment_document(raw,service.anchor,authenticated=True)
                options={'transactions_per_block':args['transactions_per_block']} if 'transactions_per_block' in args else {}
                result=service.submit_signed(values,args.get('producer_index'),**options);self._revision+=1
                return {**result,'account_originals_durable':True,'payments_executed_asserted':False}
            raise ValueError('GG_LAN_ACTION_ARGUMENTS')

    def _all_invites(self,peer):
        result=dict(self._invites)
        if peer._invite is not None:result[peer.public_key]=peer.public_invite()
        if self._trusted==peer.public_key:
            for invite in peer.candidate_invites():
                key=invite['body']['peer_key']
                if key in result or len(result)<3:result[key]=invite
        return result

    def _validator_profile(self,name,*,create=False,label=None,p2p_port=None,reopen=False):
        peer=self._owned()
        if peer.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        if peer._profile is None:raise ValueError('GG_VALIDATOR_DURABLE_LAN_OWNER_REQUIRED')
        from backend.gg_consensus_profile import ValidatorProfile
        if not isinstance(name,str):raise ValueError('GG_VALIDATOR_PROFILE_NAME')
        with self._validator_lock:existing=self._validator_profiles.get(name)
        expected_invite=None;expected_anchor=None
        if existing is not None:
            if create:raise ValueError('GG_VALIDATOR_PROFILE_EXISTS_USE_RESUME')
            if not existing._closed and not existing._failed:return existing
            if not reopen:raise ValueError('GG_VALIDATOR_PROFILE_REOPEN_REQUIRED')
            expected_invite=existing.public_invite();expected_anchor=existing.anchor()
            with self._validator_lock:previous_node=self._validator_nodes.get(name)
            if previous_node is not None:previous_node.close()
            else:existing.close()
        if (existing is None and len(self._validator_profiles)>=4
                or create and len(peer.public_invite()['body'].get('consensus_invites',[]))>=4):raise ValueError('GG_VALIDATOR_LOCAL_PROFILE_LIMIT')
        if create and (peer._engine is not None or peer._bundle is not None):raise ValueError('GG_LAN_CONSENSUS_ALREADY_BOUND')
        if create and (p2p_port is None or type(p2p_port) is int and p2p_port==0):
            with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as reserve:
                reserve.bind((peer.host,0));p2p_port=reserve.getsockname()[1]
        profile=ValidatorProfile.create(name,peer,label=name if label is None else label,p2p_port=p2p_port) if create else ValidatorProfile.open(name)
        try:
            invite=profile.public_invite()
            if expected_invite is not None and (invite!=expected_invite or expected_anchor is not None and profile.anchor()!=expected_anchor):
                raise ValueError('GG_VALIDATOR_REOPEN_IDENTITY_OR_ANCHOR_CHANGED')
            if invite['body']['owner_peer_key']!=peer.public_key:raise ValueError('GG_VALIDATOR_LAN_OWNER')
            if peer._engine is not None or peer._bundle is not None:
                membership=peer._bundle['body'].get('consensus')
                if not membership or invite not in membership['validators']:raise ValueError('GG_VALIDATOR_NOT_A_MEMBER')
                if profile.anchor() is not None:
                    from backend.gg_consensus_membership import anchor_from_bundle
                    if profile.anchor()!=anchor_from_bundle(peer._bundle,peer._trusted):raise ValueError('GG_VALIDATOR_PROFILE_NETWORK_OR_OWNER')
            else:
                invites=peer.public_invite()['body'].get('consensus_invites',[])
                if invite not in invites:invites.append(invite)
                peer.advertise_consensus_invites(invites)
                self._invites[peer.public_key]=peer.public_invite()
                if self._trusted==peer.public_key and self._bootstrap is not None:
                    self._bootstrap['coordinator_invite']=peer.public_invite()
            with self._validator_lock:
                self._validator_profiles[name]=profile
                if existing is not None:self._validator_nodes.pop(name,None)
            return profile
        except BaseException:profile.close();raise

    def validator_unlocked(self,name):
        with self._validator_lock:profile=self._validator_profiles.get(name) if isinstance(name,str) else None
        return profile is not None and profile.snapshot()['state'] not in ('CLOSED','FAULT')

    def _start_validator(self,name):
        with self._validator_lock:
            if name in self._validator_starting or name in self._validator_transitioning:raise ValueError('GG_VALIDATOR_OPERATION_BUSY')
        peer=self._owned();profile=self._validator_profile(name)
        if peer._bundle is None:raise ValueError('GG_CONSENSUS_ACTIVE_LAN_REQUIRED')
        profile.bind_anchor(peer._bundle,peer._trusted)
        from backend.gg_consensus_node import OwnedValidator
        with self._validator_lock:
            if name in self._validator_starting or name in self._validator_transitioning:raise ValueError('GG_VALIDATOR_OPERATION_BUSY')
            self._validator_starting.add(name);node=self._validator_nodes.get(name)
        self._revision+=1
        try:
            if node is None:
                if peer._bundle['body']['schema'] in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7'):
                    from backend.gg_financial_authority import OwnedFinancialAuthority
                    node=OwnedFinancialAuthority(profile,peer._proof_service.context)
                elif peer._bundle['body']['schema']=='gg.lan-dag.session.v5':
                    from backend.gg_segmented_authority import OwnedSegmentedAuthority
                    node=OwnedSegmentedAuthority(profile,peer._proof_service.context)
                else:node=OwnedValidator(profile,peer)
                with self._validator_lock:self._validator_nodes[name]=node
            node.start()
            with self._validator_lock:self._validator_nodes[name]=node;self._validator_errors.pop(name,None)
            if self._validator_thread is None or not self._validator_thread.is_alive() or self._validator_cancel.is_set():
                self._validator_cancel=threading.Event()
                self._validator_thread=threading.Thread(target=self._poll_validators,args=(self._validator_cancel,),name='GG-owned-validator-observer',daemon=True)
                self._validator_thread.start()
        except BaseException:
            if node is not None:node.stop()
            raise
        finally:
            with self._validator_lock:self._validator_starting.discard(name)
            self._revision+=1

    def _transition_validator(self,name,timeout):
        peer=self._owned();profile=self._validator_profile(name)
        if peer._bundle is None or peer._bundle['body']['schema']!='gg.lan-dag.session.v5':raise ValueError('GG_INDEX_TRANSITION_SEGMENTED_SESSION_REQUIRED')
        with self._validator_lock:
            if name in self._validator_starting or name in self._validator_transitioning:raise ValueError('GG_VALIDATOR_OPERATION_BUSY')
            node=self._validator_nodes.get(name)
            if node is not None and node._alive():raise ValueError('GG_INDEX_TRANSITION_STOP_VALIDATOR_FIRST')
            self._validator_transitioning.add(name)
        self._revision+=1
        try:
            from backend.gg_segmented_index_transition import transition
            def check():
                if self._stop_requested.is_set() or self._peer is not peer or peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                if peer._resources_paused():raise ValueError('GG_DAG_RESOURCE_PAUSED')
            result=transition(profile,peer._proof_service.context,timeout=timeout,check=check)
            with self._validator_lock:self._validator_errors.pop(name,None)
            return {'profile':name,'storage_transition':result}
        except (ValueError,OSError) as error:
            code=str(error)
            with self._validator_lock:self._validator_errors[name]=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_INDEX_TRANSITION_UNAVAILABLE'
            raise
        finally:
            with self._validator_lock:self._validator_transitioning.discard(name)
            self._revision+=1

    def _poll_validators(self,cancel):
        while not cancel.is_set():
            with self._validator_lock:
                nodes=tuple((name,node) for name,node in self._validator_nodes.items() if name not in self._validator_starting and name not in self._validator_transitioning)
            for name,node in nodes:
                if cancel.is_set() or self._stop_requested.is_set():return
                if not node._alive():continue
                try:
                    from backend.gg_financial_authority import OwnedFinancialAuthority
                    if isinstance(node,OwnedFinancialAuthority):node.certified_state()
                    elif hasattr(node,'session'):node.maintain_segmented()
                    else:node.maintain_checkpoint()
                    with self._validator_lock:self._validator_errors.pop(name,None)
                except (ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException) as error:
                    code=str(error)
                    if not code.startswith('GG_') or len(code)>96:code='GG_VALIDATOR_OBSERVATION_UNAVAILABLE'
                    with self._validator_lock:self._validator_errors[name]=code
                self._revision+=1
            if cancel.is_set() or self._stop_requested.is_set():return
            inbox=self._observer_inbox
            if inbox is not None:
                try:inbox.serve_one()
                except (ValueError,OSError):
                    if cancel.is_set() or self._stop_requested.is_set():return
            cancel.wait(2)

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
            peer=None;profile=None
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
                auto_produce=options.get('auto_produce',False)
                allow_test_tokens=options.get('allow_test_tokens',False)
                allow_dag_transactions=options.get('allow_dag_transactions',False)
                if type(allow_test_tokens) is not bool or type(allow_dag_transactions) is not bool:raise ValueError('GG_LAN_OPTION')
                extra={'allow_dag_transactions':True} if allow_dag_transactions else {}
                role=options.get('node_role','producer')
                if role not in ('producer','replica','light'):raise ValueError('GG_LAN_NODE_ROLE')
                if role!='producer' and (auto_produce or allow_test_tokens):raise ValueError('GG_LAN_REPLICA_READ_ONLY')
                if role=='light' and not allow_dag_transactions:raise ValueError('GG_LAN_LIGHT_REQUIRES_DAG_CONSENSUS')
                if role!='producer':extra['node_role']=role
                if 'profile' in options:
                    # Validate all public configuration before creating keys
                    # or files. The profile is never implicitly recreated.
                    from backend.gg_node_store import NodeProfile
                    api=_api();label=api._label(options.get('label','GG LAN node'))
                    host,port=api._endpoint(host,options.get('port',16120),allow_zero=True)
                    allowed=str(_cidr(allowed or ('127.0.0.0/8' if host.startswith('127.') else host+'/24')))
                    if ipaddress.ip_address(host) not in _cidr(allowed):raise ValueError('GG_LAN_SUBNET')
                    if type(auto_produce) is not bool:raise ValueError('GG_LAN_OPTION')
                    if trusted is not None:api._public(trusted)
                    profile=NodeProfile.create(options['profile'],{'label':label,'host':host,'port':port,
                        'allowed_cidr':allowed,'trusted_coordinator':trusted,'allow_test_tokens':allow_test_tokens,
                        'allow_dag_transactions':allow_dag_transactions,'bootstrap':bootstrap,'node_role':role})
                    extra['node_profile']=profile
                peer=_api().LanDagPeer(options.get('label','GG LAN node'),host,options.get('port',16120),
                                       trusted,auto_produce,allowed_cidr=allowed,allow_test_tokens=allow_test_tokens,**extra)
                self._attach_peer(peer)
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                invite=peer.start_pairing()
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                self._allowed=str(peer.allowed);self._trusted=trusted or peer.public_key
                self._auto_produce=auto_produce;self._invites={peer.public_key:invite}
                self._allow_test_tokens=allow_test_tokens
                self._allow_dag_transactions=allow_dag_transactions
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
                elif profile is not None:profile.close()
                self._peer=None;self._invites={};self._bundle=None;self._bootstrap=None
                self._allow_test_tokens=False
                self._allow_dag_transactions=False
                raise
            finally:self._starting=False

    def import_archive(self,profile,path,timeout=1800):
        """Offline public-history import shares the same start/stop ownership."""
        from backend.gg_dag_archive import import_profile_archive
        with self._control:
            if self.active:raise ValueError('GG_LAN_STOP_BEFORE_ARCHIVE_IMPORT')
            self._archive_importing=True;self._stop_requested.clear();self._revision+=1
            def check():
                if self._stop_requested.is_set():raise ValueError('GG_DAG_ARCHIVE_CANCELLED')
            try:return import_profile_archive(profile,path,check=check,timeout=timeout)
            finally:self._archive_importing=False;self._revision+=1

    def financial_history(self,mode,**args):
        from backend.gg_financial_archive import history
        with self._control:
            if self.active:raise ValueError('GG_LAN_STOP_BEFORE_FINANCIAL_HISTORY')
            self._archive_importing=True;self._stop_requested.clear();self._revision+=1
            def check():
                if self._stop_requested.is_set():raise ValueError('GG_FINANCIAL_HISTORY_CANCELLED')
            try:
                if mode=='observer-restore':
                    from backend.gg_observer_recovery import restore_observer
                    return restore_observer(check=check,**args)
                return history(mode,check=check,**args)
            finally:self._archive_importing=False;self._revision+=1

    @contextmanager
    def _transition_owner(self,name):
        if name is None:
            yield self._owned()._profile;return
        if self.active:raise ValueError('GG_LAN_STOP_BEFORE_OFFLINE_TRANSITION_PREPARATION')
        from backend.gg_node_store import NodeProfile
        profile=NodeProfile.open(name,migrate=False)
        try:yield profile
        finally:profile.close()

    def prepare_transition_validator(self,name,label=None,p2p_port=None,owner_profile=None):
        from backend.gg_consensus_profile import ValidatorProfile
        with self._control,self._transition_owner(owner_profile) as owner:
            if owner is None or owner.session() is None or owner.session()['body']['schema']!='gg.lan-dag.session.v4':
                raise ValueError('GG_NETWORK_TRANSITION_OWNED_LEGACY_REQUIRED')
            config=owner.descriptor()
            if p2p_port is None:
                with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
                    probe.bind((config['host'],0));p2p_port=probe.getsockname()[1]
            profile=ValidatorProfile.create_for_owned_profile(name,owner,label=name if label is None else label,p2p_port=p2p_port)
            try:return {'state':'PREPARED_UNBOUND_VALIDATOR','invite':profile.public_invite(),'native_started':False,'old_session_changed':False}
            finally:profile.close()

    def prepare_transition_invite(self,names,path=None,owner_profile=None):
        from backend.gg_consensus_profile import ValidatorProfile
        from backend.gg_network_transition import prepare_invite_from_profile
        if not isinstance(names,list) or len(names)>4 or any(type(name) is not str for name in names) or len(names)!=len(set(names)):
            raise ValueError('GG_NETWORK_TRANSITION_VALIDATORS')
        with self._control,self._transition_owner(owner_profile) as owner:
            profiles=[]
            try:
                for name in names:profiles.append(ValidatorProfile.open(name))
                invite=prepare_invite_from_profile(owner,profiles)
                return {'state':'PREPARED_TRANSITION_INVITE','invite':invite,'old_session_changed':False,
                    'export':write_public_document(path,invite,'invite') if path is not None else None}
            finally:
                for profile in reversed(profiles):profile.close()

    def prepare_network_transition(self,invites=None,label='GG segmented LAN',path=None,owner_profile=None,invite_paths=None):
        from backend.gg_network_transition import prepare_from_profile
        if (invites is None)==(invite_paths is None):raise ValueError('GG_NETWORK_TRANSITION_INVITES')
        with self._control,self._transition_owner(owner_profile) as owner:
            if invite_paths is not None:
                if not isinstance(invite_paths,list) or len(invite_paths)!=3:raise ValueError('GG_NETWORK_TRANSITION_INVITES')
                invites=[read_public_document(value,'invite') for value in invite_paths]
            document=prepare_from_profile(owner,invites,label=label)
            return {'state':'PREPARED_NETWORK_TRANSITION','document':document,'old_session_changed':False,
                'export':write_public_document(path,document,'network_transition') if path is not None else None}

    def commit_network_transition(self,profile,document=None,path=None,timeout=1800):
        from backend.gg_network_transition import transition
        if (document is None)==(path is None):raise ValueError('GG_NETWORK_TRANSITION_DOCUMENT_REQUIRED')
        with self._control:
            if self.active:raise ValueError('GG_LAN_STOP_BEFORE_NETWORK_TRANSITION')
            self._network_transitioning=True;self._stop_requested.clear();self._revision+=1
            def check():
                if self._stop_requested.is_set():raise ValueError('GG_NETWORK_TRANSITION_CANCELLED')
            try:
                value=read_public_document(path,'network_transition') if path is not None else document
                return transition(profile,value,check=check,timeout=timeout)
            finally:self._network_transitioning=False;self._revision+=1

    def resume(self,profile):
        """Restore exact owned identity/history; never resume production work."""
        from backend.gg_node_store import NodeProfile
        with self._control:
            if self.active:raise ValueError('GG_LAN_ALREADY_STARTED')
            self._starting=True;self._stop_requested.clear();self._revision+=1
            owned=None;peer=None
            try:
                owned=NodeProfile.open(profile);config=owned.descriptor()
                bootstrap=validate_bootstrap(config['bootstrap']) if config['bootstrap'] is not None else None
                peer=_api().LanDagPeer(config['label'],config['host'],config['port'],config['trusted_coordinator'],False,
                    allowed_cidr=config['allowed_cidr'],allow_test_tokens=config['allow_test_tokens'],
                    allow_dag_transactions=config['allow_dag_transactions'],node_profile=owned,node_role=config.get('node_role','producer'))
                self._attach_peer(peer)
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                invite=peer.start_pairing()
                self._allowed=config['allowed_cidr'];self._trusted=config['trusted_coordinator'];self._auto_produce=False
                self._allow_test_tokens=config['allow_test_tokens'];self._allow_dag_transactions=config['allow_dag_transactions']
                self._bundle=owned.session();self._distribution=[];self._invites={peer.public_key:invite}
                if self._bundle is not None:
                    for entry in self._bundle['body']['roster']:
                        row=entry['invite'];self._invites[row['body']['peer_key']]=deepcopy(row)
                    coordinator=self._invites[self._trusted]
                    bootstrap={'schema':BOOTSTRAP_SCHEMA,'coordinator_invite':deepcopy(coordinator),'allowed_cidr':self._allowed}
                elif self._trusted==peer.public_key:
                    bootstrap={'schema':BOOTSTRAP_SCHEMA,'coordinator_invite':deepcopy(invite),'allowed_cidr':self._allowed}
                self._bootstrap=bootstrap;self._announcement_error=''
                if self._bundle is None and bootstrap is not None and self._trusted!=peer.public_key:self.announce()
                if self._stop_requested.is_set():raise ValueError('GG_LAN_START_CANCELLED')
                self._starting=False;self._revision+=1
                return self.snapshot()
            except BaseException:
                if peer is not None:peer.stop()
                elif owned is not None:owned.close()
                self._peer=None;self._invites={};self._bundle=None;self._bootstrap=None
                self._allow_test_tokens=False;self._allow_dag_transactions=False
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
        self._validator_cancel.set()
        observers=self._observers
        if observers is not None:observers.request_stop()
        if self._observer_inbox is not None:self._observer_inbox.request_stop()
        self._revision+=1
        peer=self._peer
        if peer is not None:peer.request_stop()

    def stop(self):
        self.request_stop()
        with self._control:
            with self._account_lock:
                account_profiles=tuple(self._account_profiles.values())
                self._account_profiles={};self._account_reviews={};self._selected_account=None
            for profile in account_profiles:profile.close()
            observers=self._observers
            if observers is not None:observers.close()
            self._observers=None
            with self._validator_lock:
                nodes=tuple(self._validator_nodes.values());profiles=tuple(self._validator_profiles.values())
            for node in nodes:node.close()
            for profile in profiles:profile.close()
            with self._validator_lock:
                self._validator_nodes={};self._validator_profiles={};self._validator_errors={};self._validator_starting=set();self._validator_transitioning=set()
            peer=self._peer
            if peer is not None:peer.stop()
            self._peer=None;self._starting=False;self._invites={};self._bundle=None;self._bootstrap=None;self._distribution=[]
            self._observer_inbox=None
            self._allow_test_tokens=False
            self._allow_dag_transactions=False
            self._revision+=1
            return self.snapshot()

    def dispatch(self,command,args=None):
        if args is None:args={}
        if command not in COMMANDS or not isinstance(args,dict) or set(args)-COMMANDS[command]:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
        _public_size(args,MAX_PUBLIC_DOCUMENT+8192 if command in {'lan.install','lan.transition_prepare','lan.transition_commit'} else 16384)
        if command=='lan.status':return self.snapshot()
        if command.startswith('lan.account_'):return self._account_command(command,args)
        if command in ('lan.financial_relay_start','lan.financial_relay_stop','lan.financial_relay_status'):
            with self._control:
                peer=self._owned();service=getattr(peer,'_proof_service',None)
                if service is None or peer._bundle['body']['schema']!='gg.lan-dag.session.v7':raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
                relay=service.account_relay
                if command=='lan.financial_relay_start':result=relay.enable(args.get('producer_index'),args.get('transactions_per_block',5000))
                elif command=='lan.financial_relay_stop':result=relay.disable()
                else:result=relay.snapshot()
                self._revision+=1;return result
        if command=='lan.start':return self.start(**args)
        if command=='lan.resume':
            if set(args)!={'profile'}:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.resume(args['profile'])
        if command=='lan.archive_import':
            if not {'profile','path'}<=set(args):raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.import_archive(args['profile'],args['path'],args.get('timeout',1800))
        if command in {'lan.financial_history_export','lan.financial_history_verify','lan.financial_history_restore'}:
            if not {'profile','path'}<=set(args):raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.financial_history(command.rsplit('_',1)[1],**args)
        if command=='lan.observer_history_restore':
            if not {'profile','path','observer'}<=set(args):raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.financial_history('observer-restore',**args)
        if command=='lan.transition_commit':
            if 'profile' not in args:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.commit_network_transition(**args)
        if command=='lan.validator_transition_create':
            if 'profile' not in args:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.prepare_transition_validator(args['profile'],args.get('label'),args.get('p2p_port'),args.get('owner_profile'))
        if command=='lan.transition_invite':
            if 'profiles' not in args:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            return self.prepare_transition_invite(args['profiles'],args.get('path'),args.get('owner_profile'))
        if command=='lan.transition_prepare':return self.prepare_network_transition(**args)
        if command=='lan.join_file':
            options=dict(args)
            bootstrap=read_public_document(options.pop('path',None),'bootstrap')
            return self.start(bootstrap=bootstrap,**options)
        if command=='lan.stop':return self.stop()
        if command.startswith('lan.observer_'):
            if 'profile' not in args:raise ValueError('GG_LAN_ACTION_ARGUMENTS')
            controls=self._observer_controls();name=args['profile']
            if command=='lan.observer_create':controls.open(name,create=True,label=args.get('label'),p2p_port=args.get('p2p_port'),producer_slot=args.get('producer_slot'))
            elif command=='lan.observer_open':controls.open(name)
            elif command=='lan.observer_start':controls.start(name)
            elif command=='lan.observer_stop':controls.stop(name)
            return self.snapshot()
        with self._control:
            peer=self._owned()
            if command in {'lan.validator_create','lan.validator_open'}:
                self._validator_profile(args['profile'],create=command=='lan.validator_create',label=args.get('label'),p2p_port=args.get('p2p_port'),reopen=command=='lan.validator_open')
                self._revision+=1;return self.snapshot()
            if command=='lan.validator_invite':return self._validator_profile(args['profile']).public_invite()
            if command=='lan.validator_start':self._start_validator(args['profile']);return self.snapshot()
            if command=='lan.validator_index_transition':return self._transition_validator(args['profile'],args.get('timeout',1800))
            if command=='lan.validator_stop':
                with self._validator_lock:node=self._validator_nodes.get(args['profile'])
                if node is None:raise ValueError('GG_VALIDATOR_NOT_STARTED')
                node.stop();self._revision+=1;return self.snapshot()
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
                enabled_dag=args.get('enable_dag_transactions',False)
                consensus=args.get('enable_consensus',False)
                segmented=args.get('enable_segmented',False)
                financial=args.get('enable_financial',False)
                if any(type(value) is not bool for value in (distribute,enabled,enabled_dag,consensus,segmented,financial)):raise ValueError('GG_LAN_OPTION')
                if financial and (segmented or not consensus or not enabled_dag or enabled):raise ValueError('GG_LAN_FINANCIAL_REQUIRES_DAG_CONSENSUS')
                if segmented and (not consensus or not enabled_dag or enabled):raise ValueError('GG_LAN_SEGMENTED_REQUIRES_DAG_CONSENSUS')
                extra={'enable_dag_transactions':True} if enabled_dag else {}
                if segmented:extra['enable_segmented']=True
                if financial:extra['enable_financial']=True
                if 'financial_accounts' in args:
                    if not financial:raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
                    extra['financial_accounts']=args['financial_accounts']
                invites=list(self._all_invites(peer).values())
                if consensus:
                    if not enabled_dag:raise ValueError('GG_LAN_CONSENSUS_REQUIRES_DAG_MODE')
                    extra['consensus_invites']=[item for invite in invites for item in invite['body'].get('consensus_invites',[])]
                bundle=peer.create_session(invites,args.get('label','GG LAN'),enable_test_tokens=enabled,**extra)
                peer.install_session(bundle);self._bundle=deepcopy(bundle)
                if distribute:self._distribution=peer.distribute_session(bundle)
                self._revision+=1
                return self.snapshot()
            if command in ('lan.financial_submit','lan.financial_submit_file'):
                if peer._bundle is None or peer._bundle['body']['schema'] not in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7') or peer._proof_service is None:raise ValueError('GG_LAN_FINANCIAL_SESSION_REQUIRED')
                payments=read_signed_payments(args['path'],peer._proof_service.anchor,authenticated=True) if command=='lan.financial_submit_file' else args['payments']
                options={'transactions_per_block':args['transactions_per_block']} if 'transactions_per_block' in args else {}
                result=peer._proof_service.submit_signed(payments,args.get('producer_index'),**options);self._revision+=1;return result
            if command=='lan.financial_resume':
                if peer._bundle is None or peer._bundle['body']['schema'] not in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7') or peer._proof_service is None:raise ValueError('GG_LAN_FINANCIAL_SESSION_REQUIRED')
                result=peer._proof_service.resume_signed(args.get('producer_index'));self._revision+=1;return result
            if command=='lan.financial_receipt':
                from backend.gg_financial_proof_sync import parse_receipt_selector
                selector=str(args['block'])+':'+str(args['index']);parse_receipt_selector(selector)
                if peer._bundle is None or peer._bundle['body']['schema'] not in ('gg.lan-dag.session.v6','gg.lan-dag.session.v7') or peer._proof_service is None:raise ValueError('GG_LAN_FINANCIAL_SESSION_REQUIRED')
                return peer._proof_service.requested_proof('receipt',selector)
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
            if command=='lan.dag_stress_start':
                peer.start_dag_stress(duration_ms=args.get('duration_ms',10000),
                    transactions_per_block=args.get('transactions_per_block',16),interval_ms=args.get('interval_ms',100),remote=True)
                self._revision+=1;return self.snapshot()
            if command=='lan.dag_stress_stop':
                peer.stop_dag_stress();self._revision+=1;return self.snapshot()
            if command=='lan.dag_produce_start':
                peer.start_dag_production(duration_ms=args.get('duration_ms',60000),
                    transactions_per_block=args.get('transactions_per_block',1),interval_ms=args.get('interval_ms',1000))
                self._revision+=1;return self.snapshot()
            if command=='lan.dag_produce_stop':
                peer.stop_dag_production();self._revision+=1;return self.snapshot()
            if command=='lan.resources':
                peer.resources.configure(args.get('budget',{}))
                self._revision+=1;return self.snapshot()
            if command=='lan.hardware_test_start':
                peer.hardware_test_start(args.get('duration_ms',10000),args.get('max_transactions_per_block',5000))
                self._revision+=1;return self.snapshot()
            if command=='lan.hardware_test_stop':
                peer.resources.test.stop();self._revision+=1;return self.snapshot()
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
