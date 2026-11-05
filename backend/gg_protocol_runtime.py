"""Explicit local acceptance lifecycle for protocol-v7 CLI/Desktop work.

Status creates no key or node. This integration deliberately requires a test
genesis and literal private/loopback endpoints; public activation is a separate
task. The native protocol/economic execution itself is shared with the later
public network, with distinct genesis and test currency domains.
"""
from copy import deepcopy
from collections import deque
from contextlib import contextmanager
import ipaddress
import http.client
import json
import re
import base64
import hashlib
from pathlib import Path
import threading
import time

from backend import gg_financial_protocol as protocol
from backend import gg_protocol_setup as setup
from backend import gg_protocol_operations as operations
from backend.gg_node_store import NodeProfile,pack,unpack
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_observer_profile import ObserverProfile
from backend.gg_protocol_node import OwnedProtocolNode,validate_settings
from backend.gg_protocol_light import LightProtocolNode
from backend.gg_protocol_transport import ProofTransportServer,endpoint
from backend import gg_protocol_inbox as inbox
from backend import gg_native_resources as native_resources
from backend import gg_process_termination as termination
from backend.gg_protocol_producer import ProtocolProducer
from backend.gg_financial_account import AccountProfile,profile_path as account_profile_path
from backend.gg_financial_pool import PoolBook,verify_assignment
from backend.gg_protocol_producer import decode_core,_work_context_changed,_registry
from backend import gg_financial_economy as economy,gg_financial_wire as wire,gg_financial_dag as financial
from backend import gg_lossless_wire as lossless
from backend.gg_lan_admission import RefillBudget
from backend.application_paths import DATA_HOME
from backend.gg_node_store import _private_path
from backend.platform_files import is_link,secure_open,set_private_mode
import os
import stat

COMMANDS={
 'protocol.run':{'path'},
 'protocol.status':set(),'protocol.owner_create':{'profile','label','host','port','allowed_cidr'},'protocol.owner_open':{'profile'},
 'protocol.validator_create':{'profile','label','p2p_port','account_profile','owner_profile'},'protocol.validator_open':{'profile'},
 'protocol.validator_bind':{'profile','pin_path','membership_context_path'},'protocol.replica_create':{'profile','pin_path','label'},'protocol.replica_open':{'profile'},
 'protocol.node_start':{'profile','role','settings_path'},'protocol.node_stop':set(),'protocol.poll':set(),
 'protocol.replica_restore_start':{'owner_profile','profile','settings_path','path'},
 'protocol.light_start':{'profile','settings_path'},
 'protocol.relay_start':{'host','port','allowed_peer_keys','accept_operations','accept_accounts','pool','producer_slot','share_target'},'protocol.relay_stop':set(),
 'protocol.account_relay_status':{'profile'},
 'protocol.transfer_wait':{'profile','timeout_seconds'},
 'protocol.account_create':{'profile','label'},'protocol.account_open':{'profile'},'protocol.account_bind':{'profile','pin_path'},
 'protocol.account_observe':{'profile'},'protocol.account_review':{'profile','payments_path'},'protocol.account_sign':{'profile'},
 'protocol.registration_review':{'profile','producer_slot','label','platform','max_fee_atomic'},
 'protocol.operation_review':{'profile','intent_path','max_fee_atomic'},'protocol.cancel_review':{'profile','max_fee_atomic'},
 'protocol.operation_sign':{'profile'},'protocol.operation_submit':{'profile','attempts'},'protocol.operation_outcome':{'profile','batch_number'},
 'protocol.committee_sign':{'profile','intent_path','consent'},
 'protocol.producer_open':set(),'protocol.produce_empty':{'producer_slot'},'protocol.submit_account':{'profile','producer_slot','transactions_per_block'},
 'protocol.mine_start':{'producer_slot','duration_seconds'},'protocol.mine_stop':set(),
 'protocol.proof':{'kind','selector'},
 'protocol.pool_create':{'pool','account_profile','operator','commission_bps'},'protocol.pool_open':{'pool','account_profile','operator','commission_bps'},
 'protocol.pool_ensure':{'pool','account_profile','operator','commission_bps'},
 'protocol.pool_job':{'pool','block','worker_key','payout_account','share_target'},'protocol.pool_share':{'pool','work_path'},
 'protocol.pool_income':{'pool','income_index'},'protocol.pool_liabilities':{'pool','income_index'},
 'protocol.pool_payout_review':{'pool','income_index','account_profile','offset','limit'},'protocol.pool_payout_sign':{'pool','account_profile'},
 'protocol.pool_resume':{'pool','payout','account_profile'},'protocol.pool_payment_receipt':{'pool','payout','payment_index','block','index'},
 'protocol.worker_mine':{'work_path','pool_key','account_profile','attempts'},
 'protocol.pool_work_start':{'account_profile','duration_seconds','attempts'},'protocol.pool_work_stop':set(),
}
COMMANDS.update(setup.COMMANDS)


def read_public(path,maximum=256*1024):
    target=Path(path).absolute()
    if str(target).startswith(('\\\\','//')) or any(is_link(item) for item in (target,*target.parents)):raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
    fd=secure_open(target,os.O_RDONLY,0o600)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 0<info.st_size<=maximum:raise ValueError('GG_PROTOCOL_PUBLIC_FILE')
        raw=stream.read(maximum+1)
    if len(raw)>maximum:raise ValueError('GG_PROTOCOL_PUBLIC_FILE_LIMIT')
    return unpack(raw)


def local_acceptance(pin,settings=None):
    pin=protocol.validate_pin(pin)
    if pin['genesis']['protocol']['environment']!='TESTNET':raise ValueError('GG_PROTOCOL_LOCAL_TESTNET_REQUIRED')
    if settings is not None:
        settings=validate_settings(settings)
        ranges=tuple(ipaddress.ip_network(value) for value in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8','::1/128','fc00::/7'))
        for host in [settings['listen_host'],*(row['host'] for row in settings['peers'])]:
            address=ipaddress.ip_address(host)
            if not any(address.version==network.version and address in network for network in ranges):
                raise ValueError('GG_PROTOCOL_PUBLIC_ACTIVATION_REQUIRES_SEPARATE_TASK')
    return pin


class _CodecRelayAttempt:
    """A seed is never retired authority while its constructor can resume."""
    def __init__(self,node,relay,session):
        self.node=node;self.owner=node.owner;self.profile=node.profile
        self.epoch=node._node;self.node_process=node._node.get('process')
        self.capture=node._native_resource_attempt;self.relay=relay;self.session=session
        self.constructing=True;self.cancelled=False;self.process=None


class _CodecResources:
    """Private strong-reference binding; payloads cannot construct authority."""
    def __init__(self,node,transport,session,attempt,limits,*,client):
        self.node=node;self.owner=node.owner;self.profile=node.profile
        self.owner_lease=getattr(node.owner,'_lease',None);self.profile_lease=getattr(node.profile,'_lease',None)
        self.epoch=node._node;self.process=self.epoch['process'];self.capture=node._native_resource_attempt
        self.node_lease=getattr(node,'_lease',None)
        self.transport=transport;self.transport_process=transport.process;self.transport_lease=getattr(transport,'_lease',None)
        self.session=session;self.attempt=attempt;self.client=client;self.active=True
        self.limits=deepcopy(limits)
        self.budget=RefillBudget(limits['byte_burst'],limits['work_burst'],maximum_actors=limits['maximum_actors'],period=limits['period_seconds'])
        self.workspaces=threading.BoundedSemaphore(limits['workspaces'])


class ProtocolRuntime:
    def __init__(self):
        self.owner=None;self.node=None;self.producer=None;self.validators={};self.replicas={};self.accounts={};self.reviews={}
        self._control=threading.RLock();self._view_lock=threading.RLock();self._cancel=threading.Event();self._mine_cancel=threading.Event()
        self._thread=None;self._mine_thread=None;self._view=None;self._error='';self._mine_error='';self._mine_until=None;self._revision=0;self._proven_blocks={}
        self._drains={};self._drain_lock=threading.RLock();self._operation_cursors={}
        self.pools={};self._pool_reviews={}
        self._relay=None;self._relay_policy=None;self._account_cursor=0;self._poll_lock=threading.RLock()
        self._pool_worker=None
        self._inbox=None;self._relayed_sources={};self._uploads={};self._upload_lock=threading.RLock();self._relay_views={}
        # Original relay request rate remains <=8/s/peer in native transport.
        # Debit encoded request bytes AND declared raw chunks at that same
        # worst-case rate; the bound cannot grow with compression ratio.
        self._codec_upload_budget=RefillBudget(8*(lossless.CHUNK_BYTES+4*((lossless.CHUNK_BYTES+2)//3)+2048),8,maximum_actors=128)
        self._codec_workspaces=threading.BoundedSemaphore(2)
        # Initial LOW cells above are dormant: no codec admission uses them
        # before an actual owned native READY has bound a concrete epoch.
        self._codec_lock=threading.RLock();self._codec_server=None;self._codec_client=None
        self._codec_start_attempt=None;self._codec_pending_light=None;self._codec_pending_relay=None
        self._codec_relay_attempt=None
        self._relay_session=None;self._transfers={}
        self._observations=deque(maxlen=64);self._proof_pending=deque(maxlen=64);self._proof_phase=0
        self._operator_pending=None;self._operator_start_state='NONE';self._operator_start_error=''
        self._operator_start_request=None;self._operator_start_record=None

    @property
    def active(self):return self.node is not None

    def _reset_observation(self):
        """A newly opened node cannot inherit another source's public view."""
        self._operator_pending=None;self._operator_start_state='NONE';self._operator_start_error=''
        self._operator_start_record=None
        with self._view_lock:
            self._view=None;self._account_views=[];self._proven_blocks.clear()
            self._observations.clear();self._proof_pending.clear();self._proof_phase=0
            self._account_cursor=0;self._error='';self._relay_views.clear()

    def unlocked(self,command,args):
        if command in setup.COMMANDS:return setup.unlocked(self,command,args)
        if command=='protocol.replica_restore_start':
            return self.owner is not None and self.owner.name==args.get('owner_profile') and args.get('profile') in self.replicas
        if command=='protocol.run':return False
        name=args.get('profile')
        if command.startswith('protocol.owner_'):return self.owner is not None and self.owner.name==name
        if command.startswith('protocol.validator_'):
            if name not in self.validators:return False
            reference=self.validators[name].account_reference()
            return command!='protocol.validator_bind' or reference is None or reference['profile'] in self.accounts
        if command.startswith('protocol.replica_'):return name in self.replicas
        if command.startswith(('protocol.account_','protocol.operation_')) or command in ('protocol.registration_review','protocol.cancel_review'):return name in self.accounts
        if command=='protocol.committee_sign':
            if name not in self.validators:return False
            reference=self.validators[name].account_reference()
            return reference is None or reference['profile'] in self.accounts
        if command=='protocol.node_start':return name in (self.validators if args.get('role')=='VALIDATOR' else self.replicas)
        if command=='protocol.light_start':return name in self.replicas
        return True

    def _owned(self):
        if self.owner is None or self.owner._closed or self.owner._failed:raise ValueError('GG_PROTOCOL_OWNER_REQUIRED')
        return self.owner

    def _node(self):
        if self.node is None:raise ValueError('GG_PROTOCOL_NODE_REQUIRED')
        if callable(getattr(self.node,'process_ready',None)) and not self.node.process_ready():
            raise ValueError('GG_PROTOCOL_NODE_RECOVERING')
        return self.node

    def _governance_account(self,profile):
        reference=profile.account_reference()
        if reference is None:return None
        name=reference['profile']
        if name not in self.accounts:self.dispatch('protocol.account_open',{'profile':name})
        account=self.accounts[name]
        if account.public_address()!=reference['public_key']:raise ValueError('GG_VALIDATOR_ACCOUNT_REFERENCE')
        return account

    @staticmethod
    def _code(error):
        import re
        text=str(error);return text if re.fullmatch(r'GG_[A-Z0-9_]{1,100}',text) else 'GG_PROTOCOL_OPERATION_UNAVAILABLE'

    def _check_relay_session(self,node,session):
        if self._cancel.is_set() or self.node is not node or session is not self._relay_session:
            raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')

    @contextmanager
    def _relay_command_lock(self,node,session):
        # stop may hold the command lock while joining relay callbacks. A
        # queued callback must observe cancellation without acquiring it.
        while True:
            self._check_relay_session(node,session)
            if self._control.acquire(timeout=.05):break
        try:
            self._check_relay_session(node,session)
            yield
        finally:self._control.release()

    def _poll(self):
        with self._poll_lock:return self._poll_once()

    def _poll_once(self):
        node=self._node()
        if callable(getattr(node,'process_ready',None)) and not node.process_ready():raise ValueError('GG_PROTOCOL_NODE_RECOVERING')
        with node._lock:
            view=node.poll(producer_keys=self._owned().descriptor()['public_keys'][1:]);core=deepcopy(node._packet)
        self._observe_recent(node,core)
        view['producers']=node.snapshot()['producers']
        accounts=[]
        candidates=tuple(self.accounts.values());selected=candidates
        if node.role=='LIGHT' and candidates:
            selected=tuple(candidates[(self._account_cursor+index)%len(candidates)] for index in range(min(2,len(candidates))))
            self._account_cursor=(self._account_cursor+len(selected))%len(candidates)
        for account in selected:
            if account.anchor()!=node.anchor:continue
            with account._lock:
                packet=node.selected_proof('account',account.public_address());account.remember_account(packet);snapshot=account.snapshot();value=snapshot['account']
            accounts.append({'profile':account.name,'address':account.public_address(),'balance_atomic':value['balance_atomic'] if value else None,
                'nonce':value['nonce'] if value else None,'exists':snapshot['account_exists'],'local':True,'state':snapshot['state'],
                'certificate_height':snapshot['certificate_height'],'state_height':snapshot['certificate_height']-1 if snapshot['certificate_height'] else None,
                'verification_scope':'SDK_CERTIFIED_ACCOUNT_MEMBERSHIP_OR_ABSENCE_NOT_FULL_HISTORY_REPLAY'})
        with self._view_lock:
            previous={row['profile']:row for row in getattr(self,'_account_views',[])};previous.update({row['profile']:row for row in accounts})
            self._view=view;self._account_views=list(previous.values());self._error='';self._revision+=1
            counters=core['state']['financial_dag'];sample=(time.monotonic(),int(counters['blocks']),int(counters['applied']))
            if self._observations and (sample[1]<self._observations[-1][1] or sample[2]<self._observations[-1][2]):raise ValueError('GG_PROTOCOL_CERTIFIED_COUNTER_REWIND')
            self._observations.append(sample)
        return self.snapshot()

    def _remember_block(self,packet):
        proof=packet['financial_block'];context=proof['context'];creator=proof['creator'];summary=proof['summary']
        row={'hash':context['block_hash'],'genesis_hash':packet['genesis_hash'],'global_index':context['order_index'],'producer_key':creator['key'],'producer_index':-1,
            'sequence':creator['sequence'],'rank':creator['rank'],'parents':list(creator['parents']),'worker_key':creator['worker_key'],'work_hash':creator['work_hash'],
            'transactions':summary['transactions'],'applied':summary['applied'],'rejected':summary['rejected'],
            'state_height':packet['state']['height'],'certificate_height':str(packet['state']['height']+1)}
        with self._view_lock:
            self._proven_blocks[row['hash']]=row
            ordered=sorted(self._proven_blocks,key=lambda key:int(self._proven_blocks[key]['global_index']))
            while len(ordered)>128:self._proven_blocks.pop(ordered.pop(0))
        return row

    def _observe_recent(self,node,core):
        total=int(core['state']['financial_dag']['blocks'])
        if not total:return
        start=max(1,total-15);selector={'start':str(start),'limit':16}
        page=node._query('/gg/financial-dag/recent-blocks',core['state']['height'],pack(selector))
        if (not isinstance(page,dict) or set(page)!={'blocks','height','schema','state_root'} or page['schema']!='gg.financial.recent-blocks.v1'
                or page['height']!=core['state']['height'] or page['state_root']!=core['state']['state_root']
                or not isinstance(page['blocks'],list) or len(page['blocks'])!=min(16,total-start+1)):raise ValueError('GG_PROTOCOL_RECENT_DISCOVERY')
        for offset,row in enumerate(page['blocks']):
            if not isinstance(row,dict) or set(row)!={'block','index'} or row['index']!=str(start+offset):raise ValueError('GG_PROTOCOL_RECENT_DISCOVERY')
            protocol._hash(row['block'])
        budget=1 if node.role=='LIGHT' else 2
        origin=operations._digest(protocol.financial.DOMAIN+b'DAG-GENESIS\0',{'anchor':node.anchor['genesis_hash'],'source':protocol.financial.source_hash(node.anchor['genesis']['financial_dag'])})
        for _ in range(budget):
            self._proof_phase+=1;wanted=None
            if self._proof_pending and self._proof_phase%2==0:
                identifier,depth=self._proof_pending.popleft()
                with self._view_lock:known=identifier in self._proven_blocks
                if not known:wanted=(identifier,None,depth)
            if wanted is None:
                with self._view_lock:
                    row=next((row for row in reversed(page['blocks']) if row['block'] not in self._proven_blocks),None)
                if row is not None:wanted=(row['block'],row['index'],0)
            if wanted is None:break
            identifier,index,depth=wanted;packet=node.selected_proof('block',identifier,packet=core)
            if index is not None and packet['financial_block']['context']['order_index']!=index:raise ValueError('GG_PROTOCOL_RECENT_DISCOVERY_INDEX')
            leaf=self._remember_block(packet);key=leaf['producer_key']
            with node._lock:known=key in node._records
            if not known:node.selected_proof('registry',{'namespace':'producers','key':key},packet=core)
            if depth<7:
                with self._view_lock:known=set(self._proven_blocks)
                queued={entry[0] for entry in self._proof_pending}
                for parent in leaf['parents']:
                    if parent!=origin and parent not in known and parent not in queued:self._proof_pending.append((parent,depth+1));queued.add(parent)

    def _certified_graph(self,view,connected,*,node=None):
        node=self.node if node is None else node
        height=view.get('certificate_height');anchor=node.anchor['genesis_hash'] if node is not None else None
        certified=bool(view.get('state_root') and type(height) is int and height>0)
        leaves=sorted((row for row in self._proven_blocks.values() if certified and row.get('genesis_hash')==anchor and int(row['certificate_height'])<=height),key=lambda row:int(row['global_index']))[-128:]
        keys=sorted({row['producer_key'] for row in leaves})[-32:];indices={key:index for index,key in enumerate(keys)}
        leaves=[row for row in leaves if row['producer_key'] in indices]
        rank_order={rank:index for index,rank in enumerate(sorted({int(row['rank']) for row in leaves}))}
        identities=[]
        for key,index in indices.items():
            record=next((row for row in view.get('producers',[]) if row['producer_key']==key),None)
            identities.append({**deepcopy(record or {}),'index':index,'producer_key':key,'display_name':record['display_name'] if record else 'Producent '+key[:12]})
        blocks=[]
        for index,row in enumerate(leaves):
            blocks.append({'hash':row['hash'],'parent_hashes':list(row['parents']),'height':row['rank'],'rank':row['rank'],
                'layout_rank':rank_order[int(row['rank'])],'producer_sequence':row['sequence'],'proposer_index':indices[row['producer_key']],
                'proposer_key':row['producer_key'],'worker_key':row['worker_key'],'work_hash':row['work_hash'],
                'transaction_count':row['transactions'],'applied':row['applied'],'rejected':row['rejected'],'admission_index':index,
                'canonical_index':row['global_index'],'certificate_height':row['certificate_height'],'state':'SDK_CERTIFIED',
                'sdk_admission_verified':True,'canonical_membership_verified':True,'signature_verified':False,'payload_authenticated':False})
        known={row['hash'] for row in blocks};edges=[{'from':parent,'to':row['hash']} for row in blocks for parent in row['parent_hashes'] if parent in known]
        metrics={'bps':None,'tps':None,'window_seconds':None,'rate_basis':'SDK_CERTIFIED_COUNTER_DELTAS_LOCAL_MONOTONIC_OBSERVATION','tps_basis':'APPLIED_PAYMENTS'}
        if certified and len(self._observations)>=2:
            latest=self._observations[-1];initial=next((row for row in self._observations if row[0]>=latest[0]-5),self._observations[0]);seconds=latest[0]-initial[0]
            if seconds>=1:metrics.update(bps=(latest[1]-initial[1])/seconds,tps=(latest[2]-initial[2])/seconds,window_seconds=seconds)
        return {'schema':'gg.block-graph.v1','topology':'SDK_CERTIFIED_DAG_SUMMARY_WINDOW','source':'SDK_CERTIFIED_SUMMARIES_NOT_FULL_PAYLOAD_REPLAY',
            'producer_count':max(1,len(indices)),'registered_producer_count':view.get('producer_count'),'producer_identities':identities,
            'blocks':blocks,'edges':edges,'partial_history':True,'history_limit':128,'display_successors':7,
            'canonical_certificate_height':view.get('certificate_height'),'metrics':metrics,'stale':not connected}

    def _watch(self):
        while not self._cancel.is_set():
            ready=False
            try:self._poll();ready=True
            except (ValueError,OSError,KeyError,http.client.HTTPException) as error:
                with self._view_lock:self._error=self._code(error);self._revision+=1
            self._advance_operator_start(ready)
            if self._cancel.wait(1):return

    def _bind_operator_start(self,node):
        """Bind the validated run plan before its owned observer can start."""
        request=self._operator_start_request
        if request is None:return
        record={'node':node,'config':deepcopy(request['config']),'operator':request['operator'],
            'requires_certificate':request['extras'],'deadline':None,'attempt':request}
        self._operator_start_record=record;self._operator_pending=record
        self._operator_start_state='RECOVERING' if request['config']['role']!='LIGHT' else 'STARTING_NODE'
        self._operator_start_error=''

    def _operator_process_started(self,node,record):
        # A worker must never wait for _control: stop joins it while holding
        # that lock. This short public-state lock performs no IO or joins.
        with self._view_lock:
            if record is None or self._operator_start_record is not record or self.node is not node:return
            if self._cancel.is_set():
                self._operator_pending=None;self._operator_start_state='STOPPED';self._operator_start_error='';return
            if not getattr(node,'process_ready',lambda:False)():return
            if record['requires_certificate']:
                record['deadline']=time.monotonic()+120
                self._operator_start_state='WAITING_FOR_CERTIFICATE'
            else:
                self._operator_pending=None;self._operator_start_state='NODE_STARTED'
            self._operator_start_error='';self._revision+=1

    def _operator_process_failed(self,node,record,error):
        with self._view_lock:
            if record is None or self._operator_start_record is not record or self.node is not node:return
            stopped=self._cancel.is_set()
            self._operator_pending=None;self._operator_start_state='STOPPED' if stopped else 'FAILED'
            self._operator_start_error='' if stopped else self._code(error);self._revision+=1

    def _advance_operator_start(self,ready):
        # Reuse the owned observer thread, without blocking another CLI node's
        # startup on quorum. Nonblocking acquisition also lets stop join this
        # thread while its caller holds the command lock.
        if self._operator_pending is None or not self._control.acquire(blocking=False):return
        try:
            pending=self._operator_pending
            if pending is None:return
            if self._cancel.is_set() or self.node is not pending['node']:
                self._operator_pending=None;self._operator_start_state='STOPPED';return
            process_ready=getattr(pending['node'],'process_ready',lambda:True)()
            if not process_ready:return
            if not pending.get('requires_certificate',True):
                self._operator_pending=None;self._operator_start_state='NODE_STARTED';self._operator_start_error='';return
            if pending['deadline'] is None:
                pending['deadline']=time.monotonic()+120
                self._operator_start_state='WAITING_FOR_CERTIFICATE'
            if time.monotonic()>=pending['deadline']:
                self._operator_pending=None;self._operator_start_state='FAILED'
                self._operator_start_error='GG_PROTOCOL_START_CERTIFICATE_TIMEOUT';return
            if not ready:return
            # Consume before any effect. A partially applied startup is never
            # replayed automatically or treated as a completed account action.
            self._operator_pending=None;self._operator_start_state='STARTING_SERVICES'
            try:
                self._start_extras(pending['config'],pending['node'],operator=pending.get('operator',True))
                self._operator_start_state='STOPPED' if self._cancel.is_set() or self.node is not pending['node'] else 'READY'
                self._operator_start_error=''
            except (ValueError,OSError,KeyError,http.client.HTTPException) as error:
                stopped=self._cancel.is_set() or self.node is not pending['node']
                self._operator_start_state='STOPPED' if stopped else 'FAILED'
                self._operator_start_error='' if stopped else self._code(error)
                if not stopped:self.request_stop()
            self._revision+=1
        finally:self._control.release()

    def _start_extras(self,config,node,*,operator):
        def check():
            if self._cancel.is_set() or self.node is not node:raise ValueError('GG_PROTOCOL_START_STOPPED')
            if callable(getattr(node,'process_ready',None)) and not node.process_ready():raise ValueError('GG_PROTOCOL_NODE_RECOVERING')
        check()
        if config['producer']:self.dispatch('protocol.producer_open',{})
        for row in config.get('pools',[]):
            check();values={name:value for name,value in row.items() if name!='create'}
            self.dispatch(('protocol.pool_ensure' if operator else 'protocol.pool_create') if row['create'] else 'protocol.pool_open',values)
        check()
        if config.get('relay') is not None:self.dispatch('protocol.relay_start',config['relay'])
        for row in config.get('account_submissions',[]):check();self.dispatch('protocol.submit_account',row)
        if config['mining'] is not None:
            check()
            if not config['producer']:raise ValueError('GG_PROTOCOL_MINING_PRODUCER_REQUIRED')
            self.dispatch('protocol.mine_start',config['mining'])
        if config.get('pool_work') is not None:
            check()
            if config['mining'] is not None:raise ValueError('GG_PROTOCOL_TWO_WORK_LOOPS_REQUESTED')
            self.dispatch('protocol.pool_work_start',config['pool_work'])

    def _mine(self,key,duration):
        self._mine_until=time.monotonic()+duration
        try:
            while not self._mine_cancel.is_set() and not self._cancel.is_set() and time.monotonic()<self._mine_until:
                self.producer.reconcile(key)
                self._schedule_inbox()
                self._fill_drain(key)
                with self.owner._lock:rows=list(self.owner._db.execute('SELECT identifier FROM protocol_cores INDEXED BY protocol_active WHERE producer=? AND core IS NOT NULL ORDER BY sequence LIMIT 8',(key,)))
                with self._drain_lock:draining=key in self._drains
                if not rows and not draining:
                    self.producer.produce(key,[],check=self._check_work)
                    with self.owner._lock:rows=list(self.owner._db.execute('SELECT identifier FROM protocol_cores INDEXED BY protocol_active WHERE producer=? AND core IS NOT NULL ORDER BY sequence LIMIT 8',(key,)))
                for (identifier,) in rows:
                    self._check_work();self.producer.mine(identifier,attempts=65536,check=self._check_work)
                self.producer.submit_pending(key)
                if self._mine_cancel.wait(.25):return
        except (ValueError,OSError) as error:
            if not self._mine_cancel.is_set() and not self._cancel.is_set():self._mine_error=self._code(error)
        finally:self._mine_until=None;self._revision+=1

    def _fill_drain(self,key):
        """Fill one bounded creator window from durable account originals.

        More than eight blocks drain over subsequent certified selections.
        A selected rejection pauses the queue for an explicit retry/cancel;
        it never causes automatic replacement signatures or invented success.
        """
        with self._drain_lock:
            drain=self._drains.get(key)
            if drain is None:return {'state':'NO_ACCOUNT_DRAIN'}
            account=self.accounts.get(drain['profile']) or self._relayed_sources.get(drain['profile']);node=self._node()
            if account is None:raise ValueError('GG_PROTOCOL_DRAIN_SOURCE_MISSING')
            with account._lock:
                packet=node.selected_proof('account',account.public_address());raw=account.pending(packet);nonce=account._nonce(account._account)
            if raw is None:
                if nonce>=int(account.snapshot()['next_signing_nonce']):
                    self._drains.pop(key,None);self._relayed_sources.pop(drain['profile'],None)
                    return {'state':'NONCES_CONSUMED_RECEIPTS_STILL_REQUIRED','payments_executed_asserted':False}
                drain['state']='WAITING_FOR_PROTOCOL_OPERATION';return {'state':drain['state']}
            if type(account) is inbox.InboxEntry:self._recover_inbox_window(account,drain,nonce)
            if drain.get('rejected_nonce')==nonce:return {'state':'PAUSED_SELECTED_REJECTION','payments_executed_asserted':False}
            for identifier,row in list(drain['issued'].items()):
                if nonce>row['last']:del drain['issued'][identifier];continue
                if not row['first']<=nonce<=row['last']:continue
                with self.owner._lock:
                    stored=self.owner._db.execute('SELECT core IS NULL,sequence FROM protocol_cores WHERE identifier=?',(identifier,)).fetchone()
                if stored is None:raise ValueError('GG_PROTOCOL_DRAIN_ISSUED_CORE_MISSING')
                if not stored[0]:
                    # A later reconcile may retire this row before the next
                    # query. That cannot authorize a NEW core for these exact
                    # still-unconsumed original nonces. Mine/reuse this core.
                    drain['state']='WAITING_FOR_CREATOR_SELECTION';return {'state':drain['state']}
                else:
                    # Local retirement can be newer than the account proof.
                    # Query both creator selection and receipt at its exact
                    # verified certificate, without combining selected payloads.
                    core={name:packet[name] for name in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in packet else set())}
                    creator=node.selected_proof('registry',{'namespace':'producers','key':key},packet=core)
                    selected=_registry(creator,node.anchor,key,binary=node.binary,stamp=node._stamp)
                    if int(selected['sequence'])<stored[1]:
                        drain['state']='WAITING_FOR_ACCOUNT_PROOF';return {'state':drain['state']}
                    receipt=node.selected_proof('receipt',{'block':identifier,'index':nonce-row['first']},packet=core)['financial_receipt']
                    outcome=receipt['receipt']['leaf']['outcome']
                    if outcome!='APPLIED':
                        drain.update(state='PAUSED_SELECTED_REJECTION',rejected_nonce=nonce,outcome=outcome)
                        if type(account) is inbox.InboxEntry:account.pause(nonce);self._drains.pop(key,None)
                        return {'state':drain['state'],'outcome':outcome,'payments_executed_asserted':False}
                    drain['state']='WAITING_FOR_ACCOUNT_PROOF';return {'state':drain['state']}
            values=unpack(raw)['payments'];window=values[:8*drain['size']]
            # Existing empty/other-account cores finish first; the creator
            # sequence remains immutable and cannot be overwritten by a queue.
            with self.owner._lock:
                pending=list(self.owner._db.execute('SELECT identifier FROM protocol_cores INDEXED BY protocol_active WHERE producer=? AND core IS NOT NULL ORDER BY sequence LIMIT 8',(key,)))
                matched=[]
                for offset,(identifier,) in enumerate(pending):
                    original=unpack(self.producer.original(identifier));desired=window[offset*drain['size']:(offset+1)*drain['size']]
                    if not desired or original['body']['payments']!=desired:break
                    matched.append((identifier,{'first':int(desired[0]['body']['nonce']),'last':int(desired[-1]['body']['nonce'])}))
                if pending and not matched:
                    drain['state']='WAITING_FOR_EXISTING_CREATOR_CORES';return {'state':drain['state']}
            with self.owner._lock:
                if type(account) is inbox.InboxEntry and account._body['window'] is None:
                    if matched:
                        floor=self.owner._db.execute('SELECT sequence-1 FROM protocol_cores WHERE identifier=?',(matched[0][0],)).fetchone()[0]
                        count=len(matched)
                    else:floor=self.owner._db.execute('SELECT COALESCE(max(sequence),0) FROM protocol_cores WHERE producer=?',(key,)).fetchone()[0]
                    if not matched:count=(len(window)+drain['size']-1)//drain['size']
                    account.remember_window({'floor_sequence':str(floor),'first_nonce':str(nonce),'count':count,'size':drain['size']})
                if matched:
                    # A cold/explicitly retried drain may not yet have an
                    # issued map. Retain even a prefix followed by an empty or
                    # other-account core; it is already signed and must never
                    # be reissued after a later retirement/account-proof race.
                    drain['issued'].update(matched)
                    drain['state']='WAITING_FOR_EXISTING_CREATOR_CORES' if len(matched)<len(pending) else 'WAITING_FOR_CREATOR_SELECTION'
                    return {'state':drain['state']}
                rows=self.producer.produce_batch(key,window,drain['size'],check=self._check_work)
            for offset,row in enumerate(rows):
                selected=window[offset*drain['size']:(offset+1)*drain['size']]
                drain['issued'][row['block']]={'first':int(selected[0]['body']['nonce']),'last':int(selected[-1]['body']['nonce'])}
            drain['state']='DURABLE_SIGNED_CORE_WINDOW';drain['remaining_originals']=len(values)
            return {'state':drain['state'],'cores':rows,'remaining_originals':len(values),'payments_executed_asserted':False}

    def _recover_inbox_window(self,entry,drain,nonce):
        window=entry._body['window']
        if window is None:return
        floor=int(window['floor_sequence']);start=int(window['first_nonce']);end=min(int(entry._body['end_nonce']),start+window['count']*window['size']);key=entry._body['producer_key']
        if nonce>=end:entry.remember_window(None);drain.pop('window_loaded',None);return
        marker=pack(window)
        if drain.get('window_loaded')==marker:return
        complete=True
        for offset in range(window['count']):
            with self.owner._lock:row=self.owner._db.execute('SELECT identifier FROM protocol_cores WHERE producer=? AND sequence=?',(key,floor+offset+1)).fetchone()
            if row is None:complete=False;break
            original=unpack(self.producer.original(row[0]));payments=original['body']['payments'];first=start+offset*window['size'];last=min(end,first+window['size'])
            intended=entry._payments.rows(first-int(entry._body['first_nonce']),last-int(entry._body['first_nonce']))
            if (original['body']['producer_key']!=key or int(original['body']['sequence'])!=floor+offset+1
                    or payments!=intended):raise ValueError('GG_PROTOCOL_INBOX_SIGNING_WINDOW_CONFLICT')
            drain['issued'][row[0]]={'first':first,'last':last-1}
        # A crash can persist the window before all of its cores. An empty or
        # partial scan is never a durable negative lookup for later recovery.
        if complete:drain['window_loaded']=marker
        else:drain.pop('window_loaded',None)

    def _schedule_inbox(self):
        book=self._inbox
        if book is None:return
        with book._lock:entries=tuple(book.entries.values())
        with self._drain_lock:
            for entry in sorted(entries,key=lambda value:int(value._body['received_at_ns'])):
                # The entry can finish while this scheduling snapshot waits
                # for drain ownership. Never resurrect it or an older book.
                with book._lock:
                    if self._inbox is not book or book.entries.get(entry._body['document_hash']) is not entry:continue
                key=entry._body['producer_key']
                if key in self._drains:continue
                if entry._body['paused_nonce'] is not None:
                    with entry._lock:
                        entry.remember_account(self._node().selected_proof('account',entry.public_address()))
                        if entry._nonce(entry._account)<=int(entry._body['paused_nonce']):continue
                        entry.pause(None)
                self._relayed_sources[entry.name]=entry
                window=entry._body['window']
                self._drains[key]={'profile':entry.name,'size':window['size'] if window is not None else 5000,
                    'state':'DURABLE_RECEIVER_ORIGINALS','issued':{},'remaining_originals':None}

    def _codec_validate(self,cell,*,unpublished=False):
        slot=self._codec_client if cell.client else self._codec_server
        node=cell.node;pipe=cell.transport
        if (slot is not cell or not cell.active or self._cancel.is_set() and not unpublished
                or self.node is not node and not (unpublished and self.node is None)
                or self.owner is not cell.owner
                or node.owner is not cell.owner or node.profile is not cell.profile
                or getattr(node.owner,'_lease',None) is not cell.owner_lease
                or getattr(node.profile,'_lease',None) is not cell.profile_lease
                or node._node is not cell.epoch or node._node.get('process') is not cell.process
                or cell.process is None or cell.process.poll() is not None
                or getattr(node,'_lease',None) is not cell.node_lease
                or getattr(node,'_native_resource_attempt',None) is not cell.capture
                or pipe.process is not cell.transport_process or getattr(pipe,'_lease',None) is not cell.transport_lease
                or getattr(pipe,'_resources',None) is not cell.capture or not pipe.alive()):
            raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
        if (getattr(cell.owner,'_closed',False) or getattr(cell.owner,'_failed',False)
                or getattr(cell.profile,'_closed',False) or getattr(cell.profile,'_failed',False)
                or getattr(cell.owner,'_native_pipe_closing',False) or getattr(cell.profile,'_native_pipe_closing',False)):
            raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
        owners=getattr(pipe,'_protected_owners',())
        if len(owners)!=2 or owners[0] is not cell.owner or owners[1] is not cell.profile:
            raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
        if cell.client:
            if node._transport is not pipe or self._codec_start_attempt is not cell.attempt:
                raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
        elif self._relay is not pipe or self._relay_session is not cell.session:
            raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
        node._check_start()
        if native_resources.current(node) is not cell.capture:
            raise ValueError('GG_NATIVE_RESOURCE_PROFILE_CHANGED')
        # The hook returns attested facts only: it creates/refills no budget.
        limits=native_resources.codec_limits(node,transport=None if cell.client else pipe)
        if limits!=cell.limits:raise ValueError('GG_NATIVE_RESOURCE_PROFILE_CHANGED')
        if not cell.client:native_resources.codec_limits(node)
        # Observation/ACK refresh must not let a concurrently changed epoch
        # borrow this cell after the first identity fence.
        if (not cell.active or (self._codec_client if cell.client else self._codec_server) is not cell
                or self.node is not node and not (unpublished and self.node is None)
                or self.owner is not cell.owner
                or self._cancel.is_set() and not unpublished
                or node._node is not cell.epoch or node._node.get('process') is not cell.process
                or getattr(node,'_native_resource_attempt',None) is not cell.capture
                or node.owner is not cell.owner or node.profile is not cell.profile
                or getattr(node.owner,'_lease',None) is not cell.owner_lease or getattr(node.profile,'_lease',None) is not cell.profile_lease
                or getattr(node,'_lease',None) is not cell.node_lease or getattr(pipe,'_lease',None) is not cell.transport_lease
                or pipe.process is not cell.transport_process or getattr(pipe,'_resources',None) is not cell.capture
                or cell.client and (node._transport is not pipe or self._codec_start_attempt is not cell.attempt)
                or not cell.client and (self._relay is not pipe or self._relay_session is not cell.session)):
            raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
        node._check_start()
        if native_resources.current(node) is not cell.capture:raise ValueError('GG_NATIVE_RESOURCE_PROFILE_CHANGED')
        return cell

    def _bind_codec(self,node,transport,*,session=None,attempt=None,client=False):
        with self._codec_lock:
            previous=self._codec_client if client else self._codec_server
            if previous is not None:
                if previous.node is not node or previous.transport is not transport or previous.session is not session or previous.attempt is not attempt:
                    raise ValueError('GG_PROTOCOL_CODEC_STOP_PENDING')
                return self._codec_validate(previous,unpublished=client and self.node is None)
            if client and (attempt is None or self._codec_start_attempt is not attempt):
                raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
            if getattr(node,'_native_resource_attempt',None) is None:
                raise ValueError('GG_NATIVE_RESOURCE_ACK_REQUIRED')
            limits=native_resources.codec_limits(node,transport=None if client else transport)
            if not client:native_resources.codec_limits(node)
            cell=_CodecResources(node,transport,session,attempt,limits,client=client)
            if client:self._codec_client=cell
            else:self._codec_server=cell
            try:return self._codec_validate(cell,unpublished=client and self.node is None)
            except BaseException:
                # Retain this exact binding until its failed start closes.
                cell.active=False;raise

    def _codec_cell(self,node,*,client=False,session=None):
        with self._codec_lock:
            cell=self._codec_client if client else self._codec_server
            if cell is None:raise ValueError('GG_NATIVE_RESOURCE_ACK_REQUIRED')
            if cell.node is not node or not client and cell.session is not session:
                raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
            return self._codec_validate(cell)

    def _invalidate_codec(self,*,server=False,client=False):
        with self._codec_lock:
            for cell in ((self._codec_server,) if server else ()) + ((self._codec_client,) if client else ()):
                if cell is not None:cell.active=False

    @staticmethod
    def _codec_transport_retired(pipe):
        attempt=getattr(pipe,'_codec_constructor',None)
        if attempt is not None and attempt.constructing:return False
        if not getattr(pipe,'_resource_retired',False) or getattr(pipe,'_lease',None) is not None:return False
        if any(thread.is_alive() for thread in getattr(pipe,'_threads',())):return False
        process=getattr(pipe,'process',None)
        try:return process is None or termination.process_terminal(process)
        except OSError:return False

    def _retire_codec(self,*,server=False,client=False):
        with self._codec_lock:
            for name in (('_codec_server',) if server else ()) + (('_codec_client',) if client else ()):
                cell=getattr(self,name)
                if cell is None:continue
                if cell.active or not self._codec_transport_retired(cell.transport):
                    raise ValueError('GG_PROTOCOL_CODEC_STOP_PENDING')
                if cell.client and any(thread.is_alive() for thread in self._transfers.values()):
                    raise ValueError('GG_PROTOCOL_CODEC_STOP_PENDING')
                setattr(self,name,None)

    def _codec_relay_fence(self,attempt):
        with self._codec_lock:
            node=attempt.node
            if (self._codec_relay_attempt is not attempt or attempt.cancelled or self._cancel.is_set()
                    or self._relay is not attempt.relay or self._relay_session is not attempt.session
                    or self.node is not node or self.owner is not attempt.owner
                    or node.owner is not attempt.owner or node.profile is not attempt.profile
                    or node._node is not attempt.epoch or node._node.get('process') is not attempt.node_process
                    or attempt.node_process is None or attempt.node_process.poll() is not None
                    or getattr(node,'_native_resource_attempt',None) is not attempt.capture):
                raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
            node._check_start()
            if native_resources.current(node) is not attempt.capture:raise ValueError('GG_NATIVE_RESOURCE_PROFILE_CHANGED')

    def _new_codec_relay(self,node,session):
        # Retain the actual instance even if its constructor raises after a
        # native start. Seed only fields needed by its ordinary close method.
        relay=ProofTransportServer.__new__(ProofTransportServer)
        relay._stop=threading.Event();relay._threads=[];relay._closed=True
        relay.process=None;relay._lease=None;relay._protected_owners=()
        relay._native_retired=False;relay._resource_retired=False
        attempt=_CodecRelayAttempt(node,relay,session)
        relay._codec_constructor=attempt;self._codec_relay_attempt=attempt
        spawn=relay._spawn_pipe
        close=relay.close
        def guarded_spawn(profile):
            with self._codec_lock:
                if not attempt.constructing:raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
            self._codec_relay_fence(attempt)
            process=spawn(profile)
            # __init__'s assignment has not happened yet. Publish this exact
            # child BEFORE a cancellation exception can bypass that assignment.
            with self._codec_lock:
                attempt.process=process;relay.process=process
            self._codec_relay_fence(attempt)
            return process
        relay._spawn_pipe=guarded_spawn
        def guarded_close():
            with self._codec_lock:
                if attempt.constructing:
                    attempt.cancelled=True
                    relay.request_stop()
                    # __init__ can still reset seed fields or own a not-yet-
                    # returned Popen. Never retire/release that ownership here.
                    raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
            return close()
        relay.close=guarded_close
        return relay,attempt

    def _release_codec_relay_attempt(self,relay):
        attempt=self._codec_relay_attempt
        if attempt is None or attempt.relay is not relay:return
        if attempt.constructing or not self._codec_transport_retired(relay):raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
        self._codec_relay_attempt=None;relay._codec_constructor=None
        # The closed relay no longer needs a closure retaining this runtime.
        if '_spawn_pipe' in relay.__dict__:del relay._spawn_pipe
        if 'close' in relay.__dict__:del relay.close

    def _close_failed_codec_relay(self,relay):
        with self._codec_lock:
            self._relay_session=None;self._relay_policy=None
            if self._codec_relay_attempt is not None:self._codec_relay_attempt.cancelled=True
            self._invalidate_codec(server=True)
        relay.request_stop();relay.close()
        if not self._codec_transport_retired(relay):raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
        self._retire_codec(server=True)
        self._release_codec_relay_attempt(relay)
        if self._relay is relay:self._relay=None
        if self._codec_pending_relay is relay:self._codec_pending_relay=None

    @contextmanager
    def _codec_workspace(self,check,deadline,*,binding=None):
        if binding is None:raise ValueError('GG_NATIVE_RESOURCE_ACK_REQUIRED')
        while True:
            lossless.guard(check,deadline)
            self._codec_validate(binding)
            if binding.workspaces.acquire(timeout=.05):break
        try:
            lossless.guard(check,deadline);self._codec_validate(binding);yield
        finally:binding.workspaces.release()

    def _relay_account_request(self,node,peer,request,session):
        self._check_relay_session(node,session)
        policy=self._relay_policy
        if policy is None or not policy.get('accept_accounts') or self._inbox is None:raise ValueError('GG_PROTOCOL_RELAY_ACCOUNT_ADMISSION_DISABLED')
        method=request['method'];now=time.monotonic()
        codec_binding=self._codec_cell(node,session=session) if method in ('account_codec','account_open_codec','account_chunk_codec') else None
        if method=='account_codec' and set(request)=={'method','offer','document_hash'}:
            identifier=(peer,protocol._hash(request['document_hash']))
            with self._upload_lock:
                upload=self._uploads.get(identifier)
                codec='identity' if upload is not None and upload.get('codec') is None else 'gzip'
            return lossless.select(request['offer'],codec)
        if method=='account_challenge' and set(request)=={'method','header'}:
            packet=node.certified_state();self._check_relay_session(node,session)
            job=inbox.admission_job(request['header'],packet,node.anchor,peer,node.node_key,binary=node.binary,stamp=node._stamp)
            return {'schema':'gg.protocol.relay-admission-challenge.v1','job':job,'certificate':packet,'monetary_reward_asserted':False}
        with self._upload_lock:
            for identifier in tuple(self._uploads):
                if now-self._uploads[identifier]['updated']>120:self._uploads.pop(identifier)
            codec=None
            opening=(method=='account_open' and set(request)=={'method','header','solution'})
            if method=='account_open_codec' and set(request)=={'method','header','solution','codec'}:
                codec=lossless.selection(request['codec']);opening=True
            if opening:
                header=inbox.validate_header(request['header'],node.anchor);identifier=(peer,header['document_hash'])
                if identifier in self._uploads:
                    upload=self._uploads[identifier]
                    if upload.get('codec')!=codec:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_CODEC_CHANGED')
                    result={'state':'UPLOAD_OPEN','offset':len(upload['data'])}
                    if codec is not None:result['codec']=lossless.select(lossless.offer())
                    return result
                if len(self._uploads)>=2 or sum(row['header']['document_bytes'] for row in self._uploads.values())+header['document_bytes']>64*1024*1024:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_LIMIT')
                packet=node.certified_state();self._check_relay_session(node,session)
                expected=inbox.admission_job(header,packet,node.anchor,peer,node.node_key,binary=node.binary,stamp=node._stamp)
                economy.verify_work(expected,request['solution'],packet['state']['height'])
                self._uploads[identifier]={'header':header,'data':bytearray(),'updated':now,'codec':codec}
                result={'state':'UPLOAD_OPEN','offset':0,'admission_is_execution':False}
                if codec is not None:result['codec']=lossless.select(lossless.offer())
                return result
            if method=='account_chunk' and set(request)=={'method','document_hash','offset','data'}:
                identifier=(peer,protocol._hash(request['document_hash']));upload=self._uploads.get(identifier)
                if upload is None:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_REQUIRED')
                if upload.get('codec') is not None:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_CODEC_CHANGED')
                offset=request['offset'];data=base64.b64decode(request['data'],validate=True);current=upload['data']
                if type(offset) is not int or not 0<=offset<=len(current) or not 0<len(data)<=32768 or offset+len(data)>upload['header']['document_bytes']:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_RANGE')
                if offset<len(current):
                    if current[offset:offset+len(data)]!=data:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_DIFFERENT_BYTES')
                else:current.extend(data)
                upload['updated']=now;return {'state':'UPLOADING','offset':len(current),'admission_is_execution':False}
            if method=='account_chunk_codec' and set(request)=={'method','document_hash','chunk'}:
                identifier=(peer,protocol._hash(request['document_hash']));upload=self._uploads.get(identifier)
                if upload is None or upload.get('codec')!='gzip':raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_REQUIRED')
                chunk=request['chunk'];current=upload['data'];header=upload['header']
                offset=chunk.get('offset') if isinstance(chunk,dict) else None
                if type(offset) is not int or not 0<=offset<=len(current):raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_RANGE')
                def check():
                    if self._cancel.is_set():raise ValueError('GG_PROTOCOL_RELAY_TRANSFER_STOPPED')
                    self._check_relay_session(node,session)
                    self._codec_validate(codec_binding)
                def charge(size):
                    self._codec_validate(codec_binding)
                    if not codec_binding.budget.take(peer,len(pack(request))+size,1):raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_LIMIT')
                with self._codec_workspace(check,upload['updated']+120,binding=codec_binding):
                    data=lossless.decode(chunk,header['document_hash'],header['document_bytes'],header['document_hash'],offset,
                                         check=check,deadline=upload['updated']+120,charge=charge)
                if offset<len(current):
                    if current[offset:offset+len(data)]!=data:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_DIFFERENT_BYTES')
                else:current.extend(data)
                upload['updated']=now;return {'state':'UPLOADING','offset':len(current),'admission_is_execution':False}
            if method=='account_finish' and set(request)=={'method','document_hash','retry'}:
                identifier=(peer,protocol._hash(request['document_hash']));upload=self._uploads.get(identifier)
                if upload is None:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_REQUIRED')
                raw=bytes(upload['data']);header=upload['header']
                if len(raw)!=header['document_bytes'] or inbox.document_header(raw,node.anchor)!=header or type(request['retry']) is not bool:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_INCOMPLETE')
                with self._relay_command_lock(node,session):
                    if self.node is not node or session is not self._relay_session or self._inbox is None or self.producer is None:raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')
                    key=self.owner.descriptor()['public_keys'][self._relay_policy['producer_slot']+1]
                    account_packet=node.selected_proof('account',header['sender'])
                    observed=protocol.financial.verify_account(account_packet,node.anchor,header['sender'],binary=node.binary,stamp=node._stamp)
                    nonce=inbox.InboxEntry._nonce(observed)
                    if nonce<int(header['first_nonce']):raise ValueError('GG_PROTOCOL_INBOX_EARLIER_NONCE_REQUIRED')
                    if nonce<int(header['end_nonce']):
                        rows=unpack(raw)['payments'];total=0
                        for payment in rows:
                            body=payment['body']
                            if int(body['nonce'])>=nonce:
                                total+=wire.counter(body['amount_atomic'],positive=True,maximum=2**64-1)+wire.counter(body['max_fee_atomic'],maximum=2**64-1)
                        if not observed['financial_account_exists'] or int(observed['financial_account']['balance_atomic'])<total:raise ValueError('GG_PROTOCOL_INBOX_REVIEW_FUNDS')
                    entry=self._inbox.accept(raw,key)
                    if request['retry'] and entry._body['paused_nonce'] is not None:entry.pause(None);entry.remember_window(None)
                    self._schedule_inbox()
                self._uploads.pop(identifier,None)
                return {'state':'DURABLE_RECEIVER_ORIGINALS','document_hash':header['document_hash'],'payments_executed_asserted':False}
            if method=='account_status' and set(request)=={'method','document_hash'}:return self._inbox.status(request['document_hash'])
        raise ValueError('GG_PROTOCOL_RELAY_METHOD')

    def _submit_light_account(self,account):
        node=self._node()
        if node.role!='LIGHT':raise ValueError('GG_PROTOCOL_LIGHT_CLIENT_REQUIRED')
        codec_binding=self._codec_cell(node,client=True)
        with account._lock:raw=account.pending(node.selected_proof('account',account.public_address()))
        if raw is None:return {'state':'NO_UNCONSUMED_PAYMENT_ORIGINALS','payments_executed_asserted':False}
        header=inbox.document_header(raw,node.anchor);worker=node.profile.native_node_signer();started=time.monotonic()
        self._relay_views[account.name]={'state':'ADMISSION_WORK_PENDING','document_hash':header['document_hash'],'uploaded_bytes':0,'total_bytes':len(raw),'payments_executed_asserted':False}
        def check():
            if self._cancel.is_set() or time.monotonic()-started>300:raise ValueError('GG_PROTOCOL_RELAY_TRANSFER_STOPPED')
            node._check_start()
            self._codec_validate(codec_binding)
        codec=None
        try:
            check();selected=node._call({'method':'account_codec','offer':lossless.offer(),'document_hash':header['document_hash']})
        except ValueError as error:
            # An explicit authenticated old-peer unsupported-method reply is
            # the only fallback. Malformed selections and data never downgrade.
            if str(error)!='GG_PROTOCOL_RELAY_METHOD':raise
        else:codec=lossless.selection(selected)
        opened=None
        for _ in range(3):
            check();challenge=node._call({'method':'account_challenge','header':header})
            if not isinstance(challenge,dict) or set(challenge)!={'schema','job','certificate','monetary_reward_asserted'} or challenge['schema']!='gg.protocol.relay-admission-challenge.v1':raise ValueError('GG_PROTOCOL_RELAY_CHALLENGE')
            expected=inbox.admission_job(header,challenge['certificate'],node.anchor,worker.pubkey().hex(),node.endpoint['server_key'],binary=node.binary,stamp=node._stamp)
            if expected!=challenge['job']:raise ValueError('GG_PROTOCOL_RELAY_CHALLENGE')
            solution,_,_=economy.mine_work(expected,worker,0,2**20,check=check)
            if solution is None:raise ValueError('GG_PROTOCOL_RELAY_ADMISSION_ATTEMPTS_FINISHED')
            opening={'method':'account_open','header':header,'solution':solution}
            if codec is not None:opening.update(method='account_open_codec',codec=selected)
            try:opened=node._call(opening);break
            except ValueError as error:
                if str(error)!='GG_MINING_WORK_INVALID':raise
        if opened is None:raise ValueError('GG_PROTOCOL_RELAY_ADMISSION_CONTEXT_CHANGED')
        offset=opened.get('offset')
        if type(offset) is not int or not 0<=offset<=len(raw):raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_RANGE')
        if codec is not None:
            if opened.get('state')!='UPLOAD_OPEN' or lossless.selection(opened.get('codec'))!=codec or offset%lossless.CHUNK_BYTES and offset!=len(raw):
                raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_RANGE')
        while offset<len(raw):
            check();end=min(len(raw),offset+32768)
            if codec is None:request={'method':'account_chunk','document_hash':header['document_hash'],'offset':offset,'data':base64.b64encode(raw[offset:end]).decode('ascii')}
            else:
                actor='out:'+node.endpoint['server_key']
                def charge(size):
                    self._codec_validate(codec_binding)
                    if not codec_binding.budget.take(actor,size,1):raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_LIMIT')
                with self._codec_workspace(check,started+300,binding=codec_binding):
                    chunk=lossless.encode(raw[offset:end],header['document_hash'],len(raw),header['document_hash'],offset,
                                          check=check,deadline=started+300,charge=charge)
                request={'method':'account_chunk_codec','document_hash':header['document_hash'],'chunk':chunk}
                self._codec_validate(codec_binding)
                if not codec_binding.budget.take(actor,len(pack(request)),0):raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_LIMIT')
            response=node._call(request)
            if not isinstance(response,dict) or response.get('offset')!=end:raise ValueError('GG_PROTOCOL_RELAY_UPLOAD_RANGE')
            offset=end;self._relay_views[account.name]={'state':'TRANSFERRING_SIGNED_ORIGINALS','document_hash':header['document_hash'],'uploaded_bytes':offset,'total_bytes':len(raw),'payments_executed_asserted':False}
        response=node._call({'method':'account_finish','document_hash':header['document_hash'],'retry':True})
        if not isinstance(response,dict) or response.get('state')!='DURABLE_RECEIVER_ORIGINALS' or response.get('document_hash')!=header['document_hash']:raise ValueError('GG_PROTOCOL_RELAY_ADMISSION_OUTCOME')
        self._relay_views[account.name]={'state':'DURABLE_RECEIVER_ORIGINALS','document_hash':header['document_hash'],'uploaded_bytes':len(raw),'total_bytes':len(raw),
            'admission_work_has_monetary_reward':False,'payments_executed_asserted':False,'verification_scope':'AUTHENTICATED_RECEIVER_REPORT_NOT_EXECUTION_PROOF'}
        return deepcopy(self._relay_views[account.name])

    def _check_work(self):
        if self._mine_cancel.is_set() or self._cancel.is_set() or self._mine_until is not None and time.monotonic()>=self._mine_until:raise ValueError('GG_PROTOCOL_WORK_STOPPED')
        self._node()._check_start()

    def _check_journal(self):
        # Local owned maintenance/signing remains separate from node liveness.
        if self._cancel.is_set():raise ValueError('GG_PROTOCOL_TARGET_STOPPED')

    def _transfer_account(self,account):
        try:self._submit_light_account(account)
        except (ValueError,OSError,KeyError,TypeError) as error:
            previous=self._relay_views.get(account.name,{})
            self._relay_views[account.name]={'state':'TRANSFER_STOPPED_OR_UNRESOLVED','document_hash':previous.get('document_hash'),
                'uploaded_bytes':previous.get('uploaded_bytes'),'total_bytes':previous.get('total_bytes'),'last_error':self._code(error),'payments_executed_asserted':False}
        finally:self._revision+=1

    def snapshot(self):
        with self._drain_lock:
            drains=[{'producer_key':key,**{field:row.get(field) for field in ('profile','state','remaining_originals','outcome')}} for key,row in self._drains.items()]
        with self._view_lock:
            view=deepcopy(self._view) if self._view is not None else {'state':'WAITING_FOR_CERTIFICATE','mode':'FINANCIAL_SDK_CERTIFIED_VIEW','producers':[]}
            node=self.node;owner=self.owner
            relay=self._relay;relay_policy=self._relay_policy;receiver_inbox=self._inbox;mine_thread=self._mine_thread
            active=node is not None;profile=owner.snapshot() if owner is not None else None
            selected_accounts=tuple(sorted(((name,account) for name,account in tuple(self.accounts.items())
                if active and account.anchor()==node.anchor),key=lambda row:row[0]))
            # A cached certificate view cannot refresh local history or carry
            # a previous process's cold-audit report into a new native epoch.
            from backend import gg_local_history_status as local_history
            view['local_history']=node.local_history_observation() if active and callable(getattr(node,'local_history_observation',None)) else local_history.observation(
                None,None,None,running=False)
            if active:
                # Public configuration identity is available before the first
                # certificate; no balance, finality or traffic is inferred.
                view.update(chain_id=node.anchor['genesis']['chain_id'],genesis_hash=node.anchor['genesis_hash'],
                    network_id=node.anchor['genesis']['financial_dag']['network_id'],node_key=node.node_key,
                    environment=node.anchor['genesis']['protocol']['environment'])
            contact=view.get('network_contact_at')
            if not active or not node._alive() or contact is None or time.time()-contact>5:
                view['connection_state']='UNOBSERVED';view['peers']=[]
            recovering=bool(active and getattr(node,'_recovering',False))
            if recovering:
                # A saved floor is historical. It supplies no live balance,
                # rate, voting power or contact while this attempt replays.
                for key in ('state_root','certified_blocks','certified_transactions','rejected_transactions',
                            'producer_count','economic_state','fee_pot_atomic','account_tree','network_contact_at'):
                    view[key]=None
                view.update(state='RECOVERING',producers=[],committee=[],voting_power='0',
                    consensus_signing=False,node_ready=False,connection_state='UNOBSERVED',peers=[])
            elif not active or not node._alive():
                view.update(state='STOPPED',node_ready=False,consensus_signing=False)
            elif active and callable(getattr(node,'process_ready',None)):
                view['node_ready']=node.process_ready();view['consensus_signing']=node.role=='VALIDATOR' and view['node_ready']
            view['lan_setup']={'active':active,'coordinator':False,'allow_dag_transactions':True,'ephemeral_keys':False,'new_pairing_after_restart':False,'invites':[]}
            view['protocol_network']={'mode':'LOCAL_ACCEPTANCE','active':active,'node_role':node.role if node else None,'source_profile':owner.name if owner else None,
                'archive_startup':node.restore_progress() if active and callable(getattr(node,'restore_progress',None)) else None,
                'recovery_startup':node.recovery_progress() if active and callable(getattr(node,'recovery_progress',None)) else None,
                'native_profile':node.profile.name if node else None,
                'resources':node.resource_observation() if active and callable(getattr(node,'resource_observation',None)) else None,
                'account_sources':[{'profile':name,'address':account.public_address()} for name,account in selected_accounts],
                'worker_active':bool(mine_thread and mine_thread.is_alive()),'last_error':self._operator_start_error or self._mine_error or self._error,'revision':self._revision,
                'operator_start':{'state':self._operator_start_state,'last_error':self._operator_start_error,
                    'startup_state_is_execution_receipt':False,'pending':self._operator_pending is not None},
                'account_drains':drains,'account_transfers':deepcopy(self._relay_views),'receiver_inbox':receiver_inbox.snapshot() if receiver_inbox is not None else None,
                'pool_worker':deepcopy(self._pool_worker),'pools':[{'name':name,**book.snapshot()} for name,book in tuple(self.pools.items())],
                'own_journals':{'schema':'gg.protected.journal-sources.v1','accounts':[account.journal_observation() for name,account in selected_accounts]},
                'proof_relay':{'active':relay is not None and relay.alive(),
                    'accounts_enabled':bool(relay is not None and relay.alive() and relay_policy and relay_policy.get('accept_accounts')),
                    'peers':relay.peers() if relay is not None else [],
                    'resources':relay.resource_observation() if relay is not None and callable(getattr(relay,'resource_observation',None)) else None}}
            view['own_financial_accounts']=[] if recovering else deepcopy(getattr(self,'_account_views',[]))
            if active:
                connected=view.get('connection_state')=='CONNECTED';count=view.get('producer_count')
                certificate_height=view.get('certificate_height')
                certified=bool(view.get('state_root') and type(certificate_height) is int and certificate_height>0)
                proven=[deepcopy(row) for row in self._proven_blocks.values() if certified and row.get('genesis_hash')==node.anchor['genesis_hash'] and int(row['certificate_height'])<=certificate_height]
                proven.sort(key=lambda row:int(row['global_index']))
                view['lan']={'state':'RUNNING','scope':'LOCAL_TESTNET_PROTOCOL_ACCEPTANCE','network_kind':'LOCAL_TESTNET_ACCEPTANCE','connection_state':view.get('connection_state','UNOBSERVED'),'label':owner.descriptor()['label'],
                    'configured_peers':len(node.settings['peers']),'authenticated_peers':[{'label':row.get('label',row['node_id']),'last_seen':view.get('network_contact_at')} for row in view.get('peers',[])] if connected else [],
                    'producer_identities':deepcopy(view.get('producers',[])),'participation':{'role':'light' if node.role=='LIGHT' else 'producer' if self.producer else 'replica','producer':self.producer is not None and any(row.get('local_signer_ready') for row in view.get('producers',[])),
                        'consensus_validator':node.role=='VALIDATOR' and view.get('consensus_signing') is True and int(view.get('voting_power','0'))>0,'replica':node.role=='REPLICA','light_client':node.role=='LIGHT','local_producer_count':sum(row.get('local_signer_ready') is True for row in view.get('producers',[])) if self.producer else 0,
                        'eligible_network_producers':count},'storage':profile,'last_error':self._error}
                view['dag_proofs']={'state':'CERTIFIED' if certified else 'WAITING_FOR_CERTIFICATE','canonical_finality':certified,'history_replayed':False,'certificate_height':certificate_height,
                    'last_error':self._error,'proven_blocks':proven,'verification_scope':'SDK_CERTIFICATES_SELECTED_SUMMARIES_AND_REGISTRY_RECORDS',
                    'account_tree':deepcopy(view.get('account_tree'))}
                members=[]
                for member in view.get('committee',[]):
                    identity=next((row for row in view.get('producers',[]) if row['node_key']==member['node_key']),None)
                    members.append({**deepcopy(member),'label':identity['label'] if identity else 'Validator '+member['validator_key'][:8],
                        'owner_label':member['owner_peer_key'][:12],'local_owner':member['owner_peer_key']==owner.descriptor()['public_keys'][0],
                        'state':'SDK_CERTIFIED_MEMBERSHIP'})
                total=sum(int(row['power']) for row in members)
                view['dag_consensus']={'state':'FAULT' if view.get('state')=='FAULT' else 'CONNECTED' if connected else 'WAITING_FOR_PEERS','validator_count':len(members),'members':members,'anchor_bound':True,
                    'certificate_height':certificate_height if certified else None,
                    'own_running':int(node.role=='VALIDATOR' and view.get('consensus_signing') is True),'profiles':[profile.snapshot() for profile in tuple(self.validators.values())],
                    'voting_power_total':str(total),'quorum_voting_power_required':str(total*2//3+1) if total else None}
                view['canonical_finalized']=view.get('certified_blocks');view['worker_count']=int(view['protocol_network']['worker_active'])
                view['block_graph']=self._certified_graph(view,connected,node=node)
            return view

    def _pool_accept_share(self,book,share):
        node=self._node()
        if not isinstance(share,dict) or set(share)!={'assignment','solution'}:raise ValueError('GG_POOL_SHARE')
        with book._lock:retained=book._get('JOB',share['assignment'])
        if retained is None:raise ValueError('GG_POOL_JOB_REQUIRED')
        if self.producer is None:raise ValueError('GG_PROTOCOL_PRODUCER_OPEN_REQUIRED')
        job=retained['data']['job']
        # A stale response requires this book's exact issued job, actual hash
        # work and valid worker signature before inspecting newer SDK state.
        economy.verify_work(job,share['solution'],int(job['state_height']))
        identifier=job['payload_root'];core=decode_core(self.producer.original(identifier),node.anchor);key=core['body']['producer_key']
        packet=node.selected_proof('registry',{'namespace':'producers','key':key})
        verified=protocol.verify_selected(packet,node.anchor,registry={'namespace':'producers','key':key},binary=node.binary,stamp=node._stamp)
        record=unpack(base64.b64decode(verified['financial_registry_value'],validate=True))
        if _work_context_changed(job,packet,record,int(core['body']['sequence'])):raise ValueError('GG_POOL_JOB_STALE')
        expected=protocol.derive_block_job(core,packet,node.anchor,key,job['worker_key'],job['share_target'],binary=node.binary,stamp=node._stamp)
        if expected.document()!=job:raise ValueError('GG_POOL_JOB_STALE')
        result=book.accept_share(share['assignment'],share['solution'],packet['state']['height'])
        if result['network_work']:
            result['creator_work']=self.producer.attach_work(identifier,share['solution'],expected_job=expected,check=self._check_work)
            result['submission']=self.producer.submit_pending(key)
        return result

    def _pool_work_once(self,account,worker,attempts):
        node=self._node();self._check_work();node.certified_state()
        package=node._call({'method':'pool_job','payout_account':account.public_address()})
        if not isinstance(package,dict) or set(package)!={'assignment','manifest','certificate'}:raise ValueError('GG_POOL_WORK_PACKAGE')
        manifest=package['manifest'];key=manifest['body']['producer_key'];packet=package['certificate']
        expected=protocol.derive_manifest_job(manifest,packet,node.anchor,worker.pubkey().hex(),binary=node.binary,stamp=node._stamp)
        result=protocol.verify_selected(packet,node.anchor,registry={'namespace':'producers','key':key},binary=node.binary,stamp=node._stamp)
        record=unpack(base64.b64decode(result['financial_registry_value'],validate=True))
        if record['invite']['body']['node_key']!=node.endpoint['server_key']:raise ValueError('GG_POOL_PROVIDER_CREATOR_IDENTITY')
        assignment=verify_assignment(package['assignment'],record['invite']['body']['owner_peer_key'],account.public_address(),expected)
        cursor_key=('pool',assignment['assignment']);cursor=self._operation_cursors.get(cursor_key,(0,False))
        if cursor[1]:raise ValueError('GG_PROTOCOL_WORK_NONCE_SPACE_EXHAUSTED')
        solution,next_nonce,exhausted=economy.mine_work(expected.document(),worker,cursor[0],min(attempts,2**64-cursor[0]),check=self._check_work)
        self._operation_cursors[cursor_key]=(next_nonce,exhausted)
        while len(self._operation_cursors)>128:self._operation_cursors.pop(next(iter(self._operation_cursors)))
        if solution is not None:
            share=economy.verify_work(expected.document(),solution,packet['state']['height'])
            self._pool_worker['shares_found']+=1
            if share.network_work:self._pool_worker['network_work_found']+=1
            response=node._call({'method':'pool_share','share':{'assignment':assignment['assignment'],'solution':solution}})
            if not isinstance(response,dict) or response.get('state')!='SHARE_RETAINED':raise ValueError('GG_POOL_SHARE_OUTCOME')
            self._pool_worker['shares_retained']+=1
        self._pool_worker['last_error']=''

    def _pool_work(self,account,duration,attempts):
        self._mine_until=time.monotonic()+duration;node=self._node();worker=node.profile.native_node_signer()
        self._pool_worker={'state':'RUNNING','payout_account':account.public_address(),'shares_found':0,'shares_retained':0,'network_work_found':0,'money_created_asserted':False,'last_error':''}
        try:
            while not self._mine_cancel.is_set() and not self._cancel.is_set() and time.monotonic()<self._mine_until:
                try:self._pool_work_once(account,worker,attempts)
                except ValueError as error:
                    retryable={'GG_POOL_JOB_STALE','GG_MINING_SHARE_ALREADY_ACCEPTED','GG_PROTOCOL_RELAY_LIMIT','GG_PROTOCOL_COMMITTEE_CATCHUP_REQUIRED','GG_POOL_WAITING_FOR_CREATOR_QUEUE'}
                    if str(error) not in retryable:raise
                    self._pool_worker['last_error']=str(error)
                self._revision+=1
                if self._mine_cancel.wait(.2):return
        except (ValueError,OSError,KeyError,TypeError) as error:
            if not self._mine_cancel.is_set() and not self._cancel.is_set():self._mine_error=self._code(error);self._pool_worker['last_error']=self._mine_error
        finally:self._pool_worker['state']='STOPPED';self._mine_until=None;self._revision+=1

    def _relay_request(self,node,peer,request,session):
        if self.node is not node or session is not self._relay_session or type(node) is not OwnedProtocolNode or not isinstance(request,dict):raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')
        self._check_relay_session(node,session)
        method=request.get('method')
        if type(method) is str and method.startswith('account_'):return self._relay_account_request(node,peer,request,session)
        if method=='state' and set(request)=={'method'}:return node.certified_state()
        if method=='transition' and set(request)=={'method','epoch'}:
            from backend.gg_committee_history import history
            epoch=request['epoch']
            if type(epoch) is not int or not 1<=epoch<=1000000:raise ValueError('GG_COMMITTEE_HISTORY_SELECTOR')
            node.certified_state();self._check_relay_session(node,session)
            return history(node.anchor,node.binary,node._stamp).transition(epoch)
        if method=='query' and set(request)=={'method','path','height','selector'}:
            allowed={'/gg/financial-dag/registry-proof','/gg/financial-dag/block-proof','/gg/financial-dag/reward-proof',
                '/gg/financial-dag/account-proof','/gg/financial-dag/receipt','/gg/protocol/original-core-chunk','/gg/financial-dag/recent-blocks'}
            path=request['path'];height=request['height'];selector=request['selector']
            if type(path) is not str or path not in allowed or len(pack(selector))>4096:raise ValueError('GG_PROTOCOL_RELAY_QUERY')
            if path=='/gg/protocol/original-core-chunk':
                if height is not None:raise ValueError('GG_PROTOCOL_RELAY_QUERY')
            elif type(height) is not int or not 0<=height<2**63:raise ValueError('GG_PROTOCOL_RELAY_QUERY')
            return node._query(path,height,pack(selector))
        if method=='operation' and set(request)=={'method','batch'}:
            policy=self._relay_policy
            if policy is None:raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')
            if not policy['accept_operations']:raise ValueError('GG_PROTOCOL_RELAY_OPERATION_ADMISSION_DISABLED')
            raw=base64.b64decode(request['batch'],validate=True)
            if not 0<len(raw)<=48*1024:raise ValueError('GG_PROTOCOL_RELAY_REQUEST_LIMIT')
            batch=unpack(raw)
            if (not isinstance(batch,dict) or batch.get('schema')!='gg.financial-dag.batch.v2' or batch.get('blocks')!=[]
                    or not isinstance(batch.get('operations'),list) or len(batch['operations'])!=1
                    or batch.get('genesis_hash')!=node.anchor['genesis_hash'] or pack(batch)!=raw):raise ValueError('GG_PROTOCOL_RELAY_OPERATION_ONLY')
            # The native CheckTx path verifies exact fees, original account
            # signatures, registration work and governance quorum. This reply
            # remains a mempool outcome, never an execution receipt.
            with self._relay_command_lock(node,session):
                if session is not self._relay_session or self.node is not node:raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')
                return node._rpc('broadcast_tx_sync',raw)
        if method in ('pool_job','pool_share'):
            with self._relay_command_lock(node,session):
                if session is not self._relay_session or self.node is not node:raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')
                policy=self._relay_policy;name=policy.get('pool') if policy else None;book=self.pools.get(name)
                if book is None or self.producer is None:raise ValueError('GG_PROTOCOL_POOL_RELAY_DISABLED')
                if method=='pool_share' and set(request)=={'method','share'}:
                    share=request['share']
                    if not isinstance(share,dict) or share.get('solution',{}).get('job',{}).get('worker_key')!=peer:raise ValueError('GG_POOL_WORKER_PEER_MISMATCH')
                    return self._pool_accept_share(book,share)
                if method=='pool_job' and set(request)=={'method','payout_account'}:
                    key=self.owner.descriptor()['public_keys'][policy['producer_slot']+1];self.producer.reconcile(key);self._schedule_inbox();self._fill_drain(key)
                    with self.owner._lock:pending=self.owner._db.execute('SELECT identifier FROM protocol_cores INDEXED BY protocol_active WHERE producer=? AND core IS NOT NULL ORDER BY sequence LIMIT 1',(key,)).fetchone()
                    with self._drain_lock:
                        if pending is None and key in self._drains:raise ValueError('GG_POOL_WAITING_FOR_CREATOR_QUEUE')
                    identifier=pending[0] if pending else self.producer.produce(key,[],check=self._check_work)['block']
                    core=decode_core(self.producer.original(identifier),node.anchor);packet=node.selected_proof('registry',{'namespace':'producers','key':key})
                    selected=protocol.verify_selected(packet,node.anchor,registry={'namespace':'producers','key':key},binary=node.binary,stamp=node._stamp)
                    record=unpack(base64.b64decode(selected['financial_registry_value'],validate=True))
                    if int(record['sequence'])>=int(core['body']['sequence']):raise ValueError('GG_POOL_JOB_STALE')
                    target=policy.get('share_target') or packet['state']['protocol']['work_target']
                    job=protocol.derive_block_job(core,packet,node.anchor,key,peer,target,binary=node.binary,stamp=node._stamp)
                    assignment=book.register_job(job,request['payout_account'])
                    return {'assignment':assignment,'manifest':self.producer.work_manifest(identifier,job),'certificate':packet}
        raise ValueError('GG_PROTOCOL_RELAY_METHOD')

    def _pool_command(self,command,args):
        node=self._node();owner=self._owned()
        if command=='protocol.worker_mine':
            package=read_public(args['work_path'],32*1024*1024)
            if not isinstance(package,dict) or set(package)!={'assignment','core','certificate'}:raise ValueError('GG_POOL_WORK_PACKAGE')
            core=decode_core(pack(package['core']),node.anchor);assignment=package['assignment'];account=self.accounts[args['account_profile']]
            if account.anchor()!=node.anchor:raise ValueError('GG_ACCOUNT_NETWORK_ALREADY_BOUND')
            worker=node.profile.native_node_signer() if node.role=='LIGHT' else owner.signers()[0];body=assignment['body'];job_body=body['job']
            proof=node.selected_proof('registry',{'namespace':'producers','key':core['body']['producer_key']})
            expected=protocol.derive_block_job(core,proof,node.anchor,core['body']['producer_key'],worker.pubkey().hex(),job_body['share_target'],binary=node.binary,stamp=node._stamp)
            verified=verify_assignment(assignment,args['pool_key'],account.public_address(),expected)
            attempts=args.get('attempts',65536)
            if type(attempts) is not int or not 1<=attempts<=2**20:raise ValueError('GG_PROTOCOL_WORK_ATTEMPTS')
            cursor_key=('pool',verified['assignment']);cursor=self._operation_cursors.get(cursor_key,(0,False))
            if cursor[1]:raise ValueError('GG_PROTOCOL_WORK_NONCE_SPACE_EXHAUSTED')
            solution,next_nonce,exhausted=economy.mine_work(expected.document(),worker,cursor[0],min(attempts,2**64-cursor[0]),check=self._check_work)
            self._operation_cursors[cursor_key]=(next_nonce,exhausted)
            while len(self._operation_cursors)>128:self._operation_cursors.pop(next(iter(self._operation_cursors)))
            return {'state':'SHARE_FOUND' if solution else 'WORK_ATTEMPTS_FINISHED','share':{'assignment':verified['assignment'],'solution':solution} if solution else None,
                    'nonce_space_exhausted':exhausted,'money_created_asserted':False}
        name=args['pool']
        if type(name) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}',name):raise ValueError('GG_POOL_NAME')
        if command in ('protocol.pool_create','protocol.pool_open','protocol.pool_ensure'):
            if name in self.pools:raise ValueError('GG_POOL_ALREADY_OPEN')
            if len(self.pools)>=4:raise ValueError('GG_POOL_RESOURCE_LIMIT')
            account=self.accounts[args['account_profile']]
            if account.anchor()!=node.anchor:raise ValueError('GG_ACCOUNT_NETWORK_ALREADY_BOUND')
            key=owner.signers()[0];root=Path(DATA_HOME)/'goldgoblins/protocol-pools'/key.pubkey().hex()
            if str(root).startswith(('\\\\','//')) or any(is_link(item) for item in (root,*root.parents)):raise ValueError('GG_POOL_BOOK_PATH')
            root.mkdir(mode=0o700,parents=True,exist_ok=True);set_private_mode(root,0o700);_private_path(root,0o700)
            factory=PoolBook.create if command=='protocol.pool_create' or command=='protocol.pool_ensure' and not (root/name).exists() else PoolBook.open
            book=factory(root/name,key,node.anchor,account.public_address(),args['operator'],args['commission_bps'],binary=node.binary,stamp=node._stamp,check=self._check_journal)
            self.pools[name]=book
            return {'state':'PROTECTED_POOL_OPEN','config':deepcopy(book.config),'money_from_shares_asserted':False}
        book=self.pools.get(name)
        if book is None:raise ValueError('GG_POOL_OPEN_REQUIRED')
        if book.trust!=node.anchor:raise ValueError('GG_POOL_NETWORK_ALREADY_BOUND')
        if command=='protocol.pool_job':
            if self.producer is None:raise ValueError('GG_PROTOCOL_PRODUCER_OPEN_REQUIRED')
            core=decode_core(self.producer.original(args['block']),node.anchor);key=core['body']['producer_key']
            packet=node.selected_proof('registry',{'namespace':'producers','key':key})
            job=protocol.derive_block_job(core,packet,node.anchor,key,args['worker_key'],args['share_target'],binary=node.binary,stamp=node._stamp)
            assignment=book.register_job(job,args['payout_account'])
            return {'assignment':assignment,'core':core,'certificate':packet}
        if command=='protocol.pool_share':
            share=read_public(args['work_path'],16384)
            return self._pool_accept_share(book,share)
        if command=='protocol.pool_income':
            index=args['income_index'];packet=node.selected_proof('reward',{'index':index,'address':book.config['reward_account']})
            return book.record_income(index,packet)
        if command=='protocol.pool_liabilities':return book.liabilities(args['income_index'])
        if command=='protocol.pool_payout_review':
            account=self.accounts[args['account_profile']]
            with account._lock:
                packet=node.selected_proof('account',account.public_address());review=book.review_payout(args['income_index'],account,packet,offset=args.get('offset',0),limit=args.get('limit',5000))
            self._pool_reviews[name]=review;return review.summary()
        if command=='protocol.pool_payout_sign':
            review=self._pool_reviews.pop(name,None)
            if review is None:raise ValueError('GG_POOL_REVIEW_REQUIRED')
            raw=book.sign_payout(review,self.accounts[args['account_profile']])
            return {'state':'DURABLE_SIGNED_POOL_PAYOUT','bytes':len(raw),'payments_executed_asserted':False}
        if command=='protocol.pool_resume':
            raw=book.resume_original(args['payout'],self.accounts[args['account_profile']])
            return {'state':'DURABLE_ORIGINAL_RECOVERED' if raw else 'FRESH_REVIEW_REQUIRED_BEFORE_SIGNING','payments_executed_asserted':False}
        if command=='protocol.pool_payment_receipt':
            packet=node.selected_proof('receipt',{'block':args['block'],'index':args['index']})
            return book.remember_applied(args['payout'],args['payment_index'],packet)
        raise ValueError('GG_PROTOCOL_COMMAND')

    def _start_owned_observer(self,node,*,restore_path=None):
        # The node/worker are published before work. No command lock survives
        # into bootstrap IO, native inventory, full replay or SDK waits.
        node._foreground_cancel=self._cancel;node._recovering=True
        operator_record=self._operator_start_record
        node._recovery_progress_record=(node._node,{
            'schema':'gg.owned.recovery-observation.v1','phase':'STARTING','requested_role':node.role,
            'work_done':'0','processed_height':None,'verified_through':None,'last_error':'',
            'basis':'LOCAL_OWNED_NATIVE_PIPE_REPORT','node_ready':False,'full_original_audit_completed':False,
            'snapshot_trust_used':False,'certificate_is_network_liveness':False,
            'network_contact_asserted':False,'consensus_signing':False})
        def start_and_watch():
            try:
                if self._cancel.is_set() or self.node is not node:node.close();return
                if restore_path is None:node.start()
                else:node.restore_start(restore_path)
                if self._cancel.is_set() or self.node is not node:node.close();return
                self._operator_process_started(node,operator_record)
                self._watch()
            except BaseException as error:
                try:node.close()
                except BaseException as stop_error:error=stop_error
                self._operator_process_failed(node,operator_record,error)
                if self.node is node:
                    with self._view_lock:self._error=self._code(error);self._revision+=1
            finally:node._recovering=False
        self._thread=threading.Thread(target=start_and_watch,name='GG-protocol-certificate-observer',daemon=True)
        try:self._thread.start()
        except BaseException as error:
            self._operator_process_failed(node,operator_record,error)
            node._recovering=False;node.close();self.node=None;self._thread=None;raise

    def _start_replica_restore(self,args):
        # Publish exact ownership under the command lock, then release it
        # before full replay. The existing owned observer thread performs the
        # finite handoff and continues its normal watch after real readiness.
        if not isinstance(args,dict) or set(args)!=COMMANDS['protocol.replica_restore_start']:
            raise ValueError('GG_PROTOCOL_COMMAND')
        with self._control:
            if self.node is not None:raise ValueError('GG_PROTOCOL_NODE_ALREADY_STARTED')
            self._cancel.clear()
            setup._owner(self,args['owner_profile'])
            profile=self.replicas.get(args['profile'])
            if profile is None:
                profile=ObserverProfile.open(args['profile']);self.replicas[args['profile']]=profile
            settings=validate_settings(read_public(args['settings_path'],16384));local_acceptance(profile.anchor(),settings)
            node=OwnedProtocolNode(profile,self._owned(),settings)
            if self._cancel.is_set():node.close();raise ValueError('GG_VALIDATOR_START_CANCELLED')
            self._reset_observation();self.node=node
            progress={'schema':'gg.owned.archive-start-observation.v1','phase':'STARTING',
                'processed_height':None,'verified_through':None,'last_error':'','basis':'LOCAL_OWNED_NATIVE_PIPE_REPORT',
                'node_ready':False,'full_original_audit_completed':False,'snapshot_trust_used':False,
                'certificate_is_network_liveness':False,'network_contact_asserted':False,'consensus_signing':False}
            node._restore_progress_record=(node._node,progress)
            self._start_owned_observer(node,restore_path=args['path'])
            self._revision+=1
            return self.snapshot()

    def dispatch(self,command,args):
        if command=='protocol.replica_restore_start':return self._start_replica_restore(args)
        with self._control:
            if command not in COMMANDS or not isinstance(args,dict) or set(args)-COMMANDS[command]:raise ValueError('GG_PROTOCOL_COMMAND')
            if command.startswith('protocol.pool_') and command not in ('protocol.pool_work_start','protocol.pool_work_stop') or command=='protocol.worker_mine':return self._pool_command(command,args)
            name=args.get('profile')
            if command in setup.COMMANDS:return setup.dispatch(self,command,args)
            if command=='protocol.status':return self.snapshot()
            if command=='protocol.run':
                config=read_public(args['path'],16384)
                fields={'schema','owner_profile','native_profile','role','settings_path','account_profiles','producer','mining'}
                extended={'pools','relay','account_submissions','pool_work'}
                version=config.get('schema') if isinstance(config,dict) else None
                operator=version=='gg.protocol.operator-start.v1'
                required=fields|extended|{'bootstrap_path'} if operator else fields|extended if version=='gg.protocol.local-start.v2' else fields
                if (not isinstance(config,dict) or version not in ('gg.protocol.local-start.v1','gg.protocol.local-start.v2','gg.protocol.operator-start.v1')
                        or set(config)!=required
                        or config['role'] not in ('VALIDATOR','REPLICA','LIGHT') or type(config['producer']) is not bool
                        or not isinstance(config['account_profiles'],list) or len(config['account_profiles'])>16
                        or any(type(value) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}',value)
                               for value in (config['owner_profile'],config['native_profile'],*config['account_profiles']))
                        or type(config['settings_path']) is not str or not 0<len(config['settings_path'])<=4096
                        or len(set(config['account_profiles']))!=len(config['account_profiles'])
                        or config['mining'] is not None and (not isinstance(config['mining'],dict) or set(config['mining'])!={'producer_slot','duration_seconds'})):
                    raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                pools=config.get('pools',[]);relay=config.get('relay');submissions=config.get('account_submissions',[]);pool_work=config.get('pool_work')
                if (not isinstance(pools,list) or len(pools)>4 or not isinstance(submissions,list) or len(submissions)>16
                        or relay is not None and (not isinstance(relay,dict) or set(relay)-COMMANDS['protocol.relay_start'])
                        or pool_work is not None and (not isinstance(pool_work,dict) or set(pool_work)-COMMANDS['protocol.pool_work_start'])):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                for row in pools:
                    if (not isinstance(row,dict) or set(row)!={'pool','account_profile','operator','commission_bps','create'}
                            or type(row['pool']) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}',row['pool'])
                            or type(row['commission_bps']) is not int or not 0<=row['commission_bps']<=10000
                            or type(row['create']) is not bool or row['account_profile'] not in config['account_profiles']):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                    financial.account_address(row['operator'])
                if len({row['pool'] for row in pools})!=len(pools):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                for row in submissions:
                    if (not isinstance(row,dict) or set(row)-COMMANDS['protocol.submit_account'] or row.get('profile') not in config['account_profiles']
                            or type(row.get('producer_slot',0)) is not int or row.get('producer_slot',0) not in (0,1)
                            or type(row.get('transactions_per_block',5000)) is not int or not 1<=row.get('transactions_per_block',5000)<=5000):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                if pool_work is not None and pool_work.get('account_profile') not in config['account_profiles']:raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                if config['role']=='LIGHT' and (pools or relay is not None):raise ValueError('GG_PROTOCOL_LIGHT_CANNOT_HOST_NATIVE_RELAY_OR_POOL')
                if config['mining'] is not None:
                    mining=config['mining']
                    if (not config['producer'] or type(mining['producer_slot']) is not int or mining['producer_slot'] not in (0,1)
                            or type(mining['duration_seconds']) is not int or not 1<=mining['duration_seconds']<=3600):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                if pool_work is not None and (config['role']!='LIGHT' or config['mining'] is not None):raise ValueError('GG_PROTOCOL_START_DOCUMENT')
                operator_pin=None
                if operator:
                    setup.validate_operator_start(config)
                    from backend import gg_protocol_provisioning
                    bootstrap_path=setup._relative(args['path'],config['bootstrap_path'])
                    operator_pin=gg_protocol_provisioning.validate_bootstrap(setup.read_public(bootstrap_path))['pin']
                if self.active:raise ValueError('GG_PROTOCOL_NODE_ALREADY_STARTED')
                if self.owner is None:self.dispatch('protocol.owner_open',{'profile':config['owner_profile']})
                elif self.owner.name!=config['owner_profile']:raise ValueError('GG_PROTOCOL_OWNER_ALREADY_OPEN')
                profile_command='protocol.validator_open' if config['role']=='VALIDATOR' else 'protocol.replica_open'
                self.dispatch(profile_command,{'profile':config['native_profile']})
                profile=(self.validators if config['role']=='VALIDATOR' else self.replicas)[config['native_profile']]
                pin=local_acceptance(profile.anchor())
                if operator_pin is not None and pin!=operator_pin:raise ValueError('GG_PROTOCOL_BOOTSTRAP_PROFILE_MISMATCH')
                account_names=list(config['account_profiles'])
                if config['role']=='VALIDATOR' and profile.account_reference() is not None:
                    account_name=profile.account_reference()['profile']
                    if account_name not in account_names:account_names.append(account_name)
                if len(account_names)>16:raise ValueError('GG_PROTOCOL_ACCOUNT_PROFILE_LIMIT')
                for account_name in account_names:
                    self.dispatch('protocol.account_open',{'profile':account_name});self.accounts[account_name].bind(pin)
                settings_path=Path(config['settings_path'])
                if not settings_path.is_absolute():settings_path=Path(args['path']).absolute().parent/settings_path
                settings=read_public(settings_path,16384)
                if config['role']=='LIGHT':
                    native_resources.resolve(settings.get('resources'))
                    endpoint({key:value for key,value in settings.items() if key!='resources'})
                    if config['producer'] or config['mining'] is not None:raise ValueError('GG_PROTOCOL_LIGHT_WORKER_START_SEPARATELY')
                else:local_acceptance(pin,settings)
                extras=bool(config['producer'] or pools or relay is not None or submissions or config['mining'] is not None or pool_work is not None)
                request={'config':deepcopy(config),'operator':operator,'extras':extras}
                self._cancel.clear()
                self._operator_start_request=request
                try:
                    if config['role']=='LIGHT':self.dispatch('protocol.light_start',{'profile':config['native_profile'],'settings_path':str(settings_path)})
                    else:self.dispatch('protocol.node_start',{'profile':config['native_profile'],'role':config['role'],'settings_path':str(settings_path)})
                    # The real start path bound its record before its worker.
                    # Do not overwrite fast worker success/failure here.
                    return self.snapshot()
                except BaseException as error:
                    with self._view_lock:
                        stopped=self._cancel.is_set()
                        self._operator_pending=None;self._operator_start_state='STOPPED' if stopped else 'FAILED'
                        self._operator_start_error='' if stopped else self._code(error)
                    self.stop_node();raise
                finally:
                    if self._operator_start_request is request:self._operator_start_request=None
            if command.startswith('protocol.owner_'):
                if self.owner is not None:raise ValueError('GG_PROTOCOL_OWNER_ALREADY_OPEN')
                if command=='protocol.owner_create':
                    self.owner=NodeProfile.create(name,{'label':args['label'],'host':args['host'],'port':args['port'],'allowed_cidr':args['allowed_cidr'],
                        'trusted_coordinator':None,'allow_test_tokens':False,'allow_dag_transactions':True,'bootstrap':None,'node_role':'producer'})
                else:self.owner=NodeProfile.open(name)
                return {'state':'OWNER_OPEN','profile':self.owner.snapshot(),'public_keys':self.owner.descriptor()['public_keys']}
            if command=='protocol.validator_create':
                if name in self.validators:raise ValueError('GG_PROTOCOL_PROFILE_ALREADY_OPEN')
                if args.get('owner_profile') is not None:setup._owner(self,args['owner_profile'])
                account_name=args.get('account_profile') or ('gov_'+name if len(name)<=28 else 'gov_'+name[:19]+'_'+hashlib.sha256(name.encode()).hexdigest()[:8])
                if account_name not in self.accounts:
                    if account_profile_path(account_name).exists():self.dispatch('protocol.account_open',{'profile':account_name})
                    else:self.dispatch('protocol.account_create',{'profile':account_name,'label':'Governance '+name})
                profile=ValidatorProfile.create_for_protocol(name,self._owned(),label=args['label'],p2p_port=args['p2p_port'],account=self.accounts[account_name]);self.validators[name]=profile;return profile.public_invite()
            if command=='protocol.validator_open':
                if name not in self.validators:self.validators[name]=ValidatorProfile.open(name)
                return self.validators[name].public_invite()
            if command=='protocol.validator_bind':
                pin=local_acceptance(read_public(args['pin_path']));context=read_public(args['membership_context_path']) if args.get('membership_context_path') else None
                profile=self.validators.get(name)
                if profile is None:raise ValueError('GG_PROTOCOL_VALIDATOR_OPEN_REQUIRED')
                profile.bind_protocol(pin,membership_context=context,account=self._governance_account(profile));return profile.snapshot()
            if command=='protocol.replica_create':
                if name in self.replicas:raise ValueError('GG_PROTOCOL_PROFILE_ALREADY_OPEN')
                self.replicas[name]=ObserverProfile.create_for_protocol(name,self._owned(),local_acceptance(read_public(args['pin_path'])),label=args['label']);return self.replicas[name].snapshot()
            if command=='protocol.replica_open':
                if name not in self.replicas:self.replicas[name]=ObserverProfile.open(name)
                return self.replicas[name].snapshot()
            if command=='protocol.light_start':
                if self.node is not None:raise ValueError('GG_PROTOCOL_NODE_ALREADY_STARTED')
                if self._codec_pending_light is not None or self._codec_client is not None:raise ValueError('GG_PROTOCOL_CODEC_STOP_PENDING')
                profile=self.replicas.get(name)
                if profile is None:raise ValueError('GG_PROTOCOL_PROFILE_OPEN_REQUIRED')
                local_acceptance(profile.anchor());attempt=object();node=None
                with self._codec_lock:self._codec_start_attempt=attempt
                try:
                    node=LightProtocolNode(profile,self._owned(),read_public(args['settings_path'],16384))
                    with self._codec_lock:
                        self._codec_pending_light=node
                        if self._codec_start_attempt is not attempt:raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
                    node.start()
                    self._bind_codec(node,node._transport,attempt=attempt,client=True)
                    self._reset_observation()
                    with self._codec_lock:
                        if self._codec_start_attempt is not attempt:raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
                        self.node=node;self._cancel.clear()
                    self._bind_operator_start(node)
                    self._operator_process_started(node,self._operator_start_record)
                    self._thread=threading.Thread(target=self._watch,name='GG-light-certificate-observer',daemon=True);self._thread.start()
                    with self._codec_lock:
                        if self._codec_start_attempt is not attempt:raise ValueError('GG_PROTOCOL_CODEC_EPOCH_CHANGED')
                        self._codec_pending_light=None
                    return self.snapshot()
                except BaseException:
                    self._cancel.set();self._codec_start_attempt=None;self._invalidate_codec(client=True)
                    if node is None:raise
                    node.request_stop()
                    watcher=self._thread
                    if watcher is not None and watcher is not threading.current_thread():
                        watcher.join(8)
                        if watcher.is_alive():
                            if self.node is None:self.node=node
                            raise ValueError('GG_PROTOCOL_WORK_STOP_PENDING')
                    try:node.close();self._retire_codec(client=True)
                    except BaseException:
                        if self.node is None:self.node=node
                        raise
                    if self.node is node:self.node=None
                    self._codec_pending_light=None;raise
            if command=='protocol.relay_start':
                node=self._node()
                if type(node) is not OwnedProtocolNode:raise ValueError('GG_PROTOCOL_FULL_NODE_REQUIRED')
                if self._relay is not None or self._codec_server is not None or self._codec_pending_relay is not None or self._codec_relay_attempt is not None:raise ValueError('GG_PROTOCOL_RELAY_ALREADY_STARTED')
                policy={'accept_operations':args.get('accept_operations',False),'accept_accounts':args.get('accept_accounts',False),'pool':args.get('pool'),'producer_slot':args.get('producer_slot',0),'share_target':args.get('share_target')}
                if type(policy['accept_operations']) is not bool or type(policy['accept_accounts']) is not bool or type(policy['producer_slot']) is not int or policy['producer_slot'] not in (0,1):raise ValueError('GG_PROTOCOL_RELAY_POLICY')
                if policy['pool'] is not None and (policy['pool'] not in self.pools or self.producer is None):raise ValueError('GG_PROTOCOL_POOL_OPEN_REQUIRED')
                if policy['accept_accounts']:
                    if self.producer is None:raise ValueError('GG_PROTOCOL_PRODUCER_OPEN_REQUIRED')
                    self.producer.reconcile(self.owner.descriptor()['public_keys'][policy['producer_slot']+1])
                    self._inbox=inbox.ProtocolInbox(self._owned(),node.anchor,binary=node.binary,stamp=node._stamp);self._schedule_inbox()
                if policy['share_target'] is not None:protocol._hash(policy['share_target'])
                key=node.profile.native_signers()[1] if node.role=='VALIDATOR' else node.profile.native_node_signer()
                with self._codec_lock:
                    if self._cancel.is_set():raise ValueError('GG_PROTOCOL_RELAY_TARGET_STOPPED')
                    self._relay_policy=policy;session=object();self._relay_session=session
                    relay,attempt=self._new_codec_relay(node,session);self._relay=relay;self._codec_pending_relay=relay
                try:
                    try:
                        self._codec_relay_fence(attempt)
                        ProofTransportServer.__init__(relay,key,node.anchor,args['host'],args['port'],args['allowed_peer_keys'],lambda peer,request:self._relay_request(node,peer,request,session),binary=node.binary,stamp=node._stamp,owner=node.owner,profile=node.profile,resources=native_resources.current(node))
                    finally:
                        with self._codec_lock:attempt.constructing=False
                    with self._codec_lock:
                        self._codec_relay_fence(attempt)
                        self._bind_codec(node,relay,session=session)
                        self._codec_relay_fence(attempt)
                        self._codec_pending_relay=None
                        return {'state':'AUTHENTICATED_PROOF_RELAY_STARTED','endpoint':{'host':args['host'],'port':args['port'],'server_key':key.pubkey().hex()},'policy':deepcopy(policy)}
                except BaseException:
                    self._close_failed_codec_relay(relay);raise
            if command=='protocol.relay_stop':
                with self._codec_lock:
                    self._relay_session=None;self._relay_policy=None;self._invalidate_codec(server=True)
                    if self._codec_relay_attempt is not None:self._codec_relay_attempt.cancelled=True
                relay=self._relay
                if relay is not None:
                    relay.close()
                    if (self._codec_server is not None or self._codec_pending_relay is relay) and not self._codec_transport_retired(relay):
                        raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
                    self._retire_codec(server=True)
                    self._release_codec_relay_attempt(relay)
                    if self._relay is relay:self._relay=None
                    if self._codec_pending_relay is relay:self._codec_pending_relay=None
                return self.snapshot()
            if command=='protocol.transfer_wait':
                timeout=args.get('timeout_seconds',300)
                if type(timeout) is not int or not 1<=timeout<=300:raise ValueError('GG_PROTOCOL_TRANSFER_WAIT_LIMIT')
                thread=self._transfers.get(name)
                if thread is not None:thread.join(timeout)
                return deepcopy(self._relay_views.get(name,{'state':'NO_TRANSFER_STARTED','payments_executed_asserted':False}))
            if command=='protocol.account_relay_status':
                account=self.accounts[name];node=self._node();view=self._relay_views.get(name,{});identifier=view.get('document_hash')
                if node.role!='LIGHT' or identifier is None:return deepcopy(view)
                response=node._call({'method':'account_status','document_hash':identifier})
                if not isinstance(response,dict) or response.get('state') not in ('DURABLE_RECEIVER_ORIGINALS','NONCES_CONSUMED_OUTCOME_UNRESOLVED','NOT_RETAINED_CHECK_ACCOUNT_PROOF_OR_RESUBMIT'):raise ValueError('GG_PROTOCOL_RELAY_STATUS')
                with account._lock:account.remember_account(node.selected_proof('account',account.public_address()))
                return {'receiver_state':response['state'],'receiver_paused_nonce':response.get('receiver_paused_nonce'),'account':account.snapshot(),
                    'verification_scope':'SDK_ACCOUNT_PROOF_WITH_SEPARATE_RECEIVER_QUEUE_REPORT','payments_executed_asserted':False}
            if command=='protocol.pool_work_start':
                node=self._node()
                if node.role!='LIGHT':raise ValueError('GG_PROTOCOL_LIGHT_WORKER_REQUIRED')
                account=self.accounts[args['account_profile']]
                if account.anchor()!=node.anchor:raise ValueError('GG_ACCOUNT_NETWORK_ALREADY_BOUND')
                duration=args.get('duration_seconds',60);attempts=args.get('attempts',65536)
                if type(duration) is not int or not 1<=duration<=3600 or type(attempts) is not int or not 1<=attempts<=2**20:raise ValueError('GG_PROTOCOL_WORK_DURATION_OR_ATTEMPTS')
                if self._mine_thread is not None and self._mine_thread.is_alive():raise ValueError('GG_PROTOCOL_WORK_ALREADY_RUNNING')
                self._mine_cancel.clear();self._mine_error='';self._mine_thread=threading.Thread(target=self._pool_work,args=(account,duration,attempts),name='GG-light-pool-work',daemon=True);self._mine_thread.start();return self.snapshot()
            if command=='protocol.pool_work_stop':self._mine_cancel.set();return self.snapshot()
            if command=='protocol.node_start':
                if self.node is not None:raise ValueError('GG_PROTOCOL_NODE_ALREADY_STARTED')
                role=args['role']
                if role not in ('VALIDATOR','REPLICA'):raise ValueError('GG_PROTOCOL_NODE_ROLE')
                profile=(self.validators if role=='VALIDATOR' else self.replicas).get(name)
                if profile is None:raise ValueError('GG_PROTOCOL_PROFILE_OPEN_REQUIRED')
                settings=validate_settings(read_public(args['settings_path'],16384));local_acceptance(profile.anchor(),settings)
                node=OwnedProtocolNode(profile,self._owned(),settings)
                self._cancel.clear();self._reset_observation();self.node=node
                self._bind_operator_start(node)
                self._start_owned_observer(node)
                self._revision+=1;return self.snapshot()
            if command=='protocol.node_stop':self.stop_node();return self.snapshot()
            if command=='protocol.poll':return self._poll()
            if command=='protocol.account_create':
                if name in self.accounts:raise ValueError('GG_PROTOCOL_PROFILE_ALREADY_OPEN')
                if len(self.accounts)>=16:raise ValueError('GG_PROTOCOL_ACCOUNT_PROFILE_LIMIT')
                self.accounts[name]=AccountProfile.create(name,label=args['label']);return self.accounts[name].snapshot()
            if command=='protocol.account_open':
                if name not in self.accounts:
                    if len(self.accounts)>=16:raise ValueError('GG_PROTOCOL_ACCOUNT_PROFILE_LIMIT')
                    self.accounts[name]=AccountProfile.open(name)
                return self.accounts[name].snapshot()
            if command=='protocol.account_bind':return self.accounts[name].bind(local_acceptance(read_public(args['pin_path'])))
            if command=='protocol.account_observe':
                account=self.accounts[name];account.remember_account(self._node().selected_proof('account',account.public_address()));return account.snapshot()
            if command=='protocol.account_review':
                account=self.accounts[name];review=account.review(read_public(args['payments_path'],32*1024*1024),self._node().selected_proof('account',account.public_address()))
                self.reviews[name]=review;return review.summary()
            if command=='protocol.account_sign':
                review=self.reviews.pop(name,None)
                if review is None:raise ValueError('GG_ACCOUNT_REVIEW_REQUIRED')
                raw=self.accounts[name].sign(review,check=self._check_journal);return {'state':'DURABLE_SIGNED_ORIGINALS','bytes':len(raw),'payments_executed_asserted':False}
            if command in ('protocol.registration_review','protocol.operation_review','protocol.cancel_review'):
                account=self.accounts[name];node=self._node()
                if account.anchor()!=node.anchor:raise ValueError('GG_ACCOUNT_NETWORK_ALREADY_BOUND')
                with account._lock:
                    packet=node.selected_proof('account',account.public_address())
                    if command=='protocol.cancel_review':review=account.review_cancellation(packet,max_fee=args.get('max_fee_atomic'))
                    else:
                        if command=='protocol.registration_review':
                            invite=operations.make_producer_invite(self._owned(),node.profile,node.anchor,args.get('producer_slot',0),account.public_address(),label=args['label'],platform=args['platform'])
                            selector={'namespace':'producers','key':invite['body']['producer_key']}
                            found=node.selected_proof('registry',selector)
                            if protocol.verify_selected(found,node.anchor,registry=selector,binary=node.binary,stamp=node._stamp)['financial_registry_exists']:raise ValueError('GG_PRODUCER_ALREADY_REGISTERED')
                            intent={'producer':invite}
                        else:intent=read_public(args['intent_path'],128*1024)
                        core=node.certified_state() if 'committee' in intent else None
                        review=account.review_operation(intent,packet,max_fee=args.get('max_fee_atomic'),committee_packet=core)
                self.reviews[name]=review;return review.summary()
            if command=='protocol.operation_sign':
                review=self.reviews.pop(name,None)
                if review is None:raise ValueError('GG_ACCOUNT_REVIEW_REQUIRED')
                raw=self.accounts[name].sign_operation(review,check=self._check_journal)
                return {'state':'DURABLE_SIGNED_PROTOCOL_AUTHORIZATION','bytes':len(raw),'operation_executed_asserted':False}
            if command=='protocol.committee_sign':
                profile=self.validators[name];node=self._node();consent=args.get('consent',False)
                if type(consent) is not bool:raise ValueError('GG_PROTOCOL_COMMITTEE_SIGN_MODE')
                governance=self._governance_account(profile)
                if governance is not None:governance.bind(node.anchor)
                return operations.sign_committee(profile,self._owned(),read_public(args['intent_path'],128*1024),node.certified_state(),node.anchor,
                    consent=consent,account_profile=governance,binary=node.binary,stamp=node._stamp)
            if command=='protocol.operation_submit':
                account=self.accounts[name];node=self._node()
                with account._lock:raw=account.pending_authorization(node.selected_proof('account',account.public_address()))
                if raw is None:return {'state':'NO_PENDING_PROTOCOL_AUTHORIZATION','operation_executed_asserted':False}
                attempts=args.get('attempts',65536)
                if type(attempts) is not int or not 1<=attempts<=2**20:raise ValueError('GG_PROTOCOL_WORK_ATTEMPTS')
                core=node.certified_state();state=core['state']['protocol'];original=operations.decode_authorization(raw,node.anchor)
                cursor_key=(operations.authorization_id(original['fee']),state['economics']['next_epoch'],state['work_anchor_height'],state['work_anchor_root'])
                cursor=self._operation_cursors.get(cursor_key,(0,False))
                if cursor[1]:raise ValueError('GG_PROTOCOL_WORK_NONCE_SPACE_EXHAUSTED')
                worker=self._owned().signers()[0];remaining=min(attempts,2**64-cursor[0])
                operation,next_nonce,exhausted=operations.assemble(raw,core,node.anchor,worker=worker,start=cursor[0],attempts=remaining,
                    check=self._check_work,binary=node.binary,stamp=node._stamp)
                self._operation_cursors[cursor_key]=(next_nonce,exhausted)
                while len(self._operation_cursors)>128:self._operation_cursors.pop(next(iter(self._operation_cursors)))
                if operation is None:return {'state':'WORK_ATTEMPTS_FINISHED','nonce_space_exhausted':exhausted,'operation_executed_asserted':False}
                commitment=core['state']['financial_dag'];batch={'blocks':[],'operations':[operation],'genesis_hash':node.anchor['genesis_hash'],
                    'previous':operations._digest(protocol.financial.DOMAIN+b'DAG-COMMITMENT\0',commitment),'schema':'gg.financial-dag.batch.v2',
                    'sequence':str(int(commitment['checkpoint'])+1),'source_hash':protocol.financial.source_hash(node.anchor['genesis']['financial_dag'])}
                response=node._rpc('broadcast_tx_sync',pack(batch))
                return {'state':'MEMPOOL_ACCEPTED' if int(response.get('code',1))==0 else 'MEMPOOL_REJECTED','operation_executed_asserted':False}
            if command=='protocol.operation_outcome':
                account=self.accounts[name];node=self._node();raw=account.original(args.get('batch_number'));original=operations.decode_authorization(raw,node.anchor)
                selector=operations.receipt_selector(account.public_address(),original['fee']['body']['nonce'])
                return operations.outcome(raw,node.selected_proof('registry',selector),node.anchor,binary=node.binary,stamp=node._stamp)
            if command=='protocol.producer_open':
                if self.producer is None:self.producer=ProtocolProducer(self._owned(),self._node())
                return {'state':'PROTECTED_PRODUCER_OPEN','public_keys':self.owner.descriptor()['public_keys'][1:]}
            if command=='protocol.submit_account' and self._node().role=='LIGHT':
                account=self.accounts[name];thread=self._transfers.get(name)
                if thread is not None and thread.is_alive():return deepcopy(self._relay_views.get(name,{'state':'TRANSFER_RUNNING','payments_executed_asserted':False}))
                if sum(thread.is_alive() for thread in self._transfers.values())>=2:raise ValueError('GG_PROTOCOL_TRANSFER_LIMIT')
                self._relay_views[name]={'state':'TRANSFER_STARTED','payments_executed_asserted':False}
                thread=threading.Thread(target=self._transfer_account,args=(account,),name='GG-protected-account-transfer',daemon=True);self._transfers[name]=thread;thread.start()
                return deepcopy(self._relay_views[name])
            if command in ('protocol.produce_empty','protocol.submit_account','protocol.mine_start'):
                if self.producer is None:raise ValueError('GG_PROTOCOL_PRODUCER_OPEN_REQUIRED')
                slot=args.get('producer_slot',0)
                if type(slot) is not int or slot not in (0,1):raise ValueError('GG_PROTOCOL_PRODUCER_SLOT')
                key=self.owner.descriptor()['public_keys'][slot+1]
                if command=='protocol.produce_empty':return self.producer.produce(key,[])
                if command=='protocol.submit_account':
                    size=args.get('transactions_per_block',5000)
                    if type(size) is not int or not 1<=size<=5000:raise ValueError('GG_PROTOCOL_PAYMENT_BLOCK_SIZE')
                    with self._drain_lock:
                        previous=self._drains.get(key)
                        if previous is not None and previous['profile']!=name:raise ValueError('GG_PROTOCOL_CREATOR_DRAIN_ALREADY_ASSIGNED')
                        self._drains[key]={'profile':name,'size':size,'state':'QUEUED_DURABLE_ACCOUNT_ORIGINALS','issued':{},'remaining_originals':None}
                    return self._fill_drain(key)
                duration=args.get('duration_seconds',60)
                if type(duration) is not int or not 1<=duration<=3600:raise ValueError('GG_PROTOCOL_WORK_DURATION')
                if self._mine_thread is not None and self._mine_thread.is_alive():raise ValueError('GG_PROTOCOL_WORK_ALREADY_RUNNING')
                self._mine_cancel.clear();self._mine_error='';self._mine_thread=threading.Thread(target=self._mine,args=(key,duration),name='GG-protocol-owned-mining',daemon=True);self._mine_thread.start();return self.snapshot()
            if command=='protocol.mine_stop':self._mine_cancel.set();return self.snapshot()
            if command=='protocol.proof':
                packet=self._node().selected_proof(args['kind'],args['selector'])
                if args['kind']=='block':
                    creator=packet['financial_block']['creator']
                    core={name:packet[name] for name in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in packet else set())}
                    self._node().selected_proof('registry',{'namespace':'producers','key':creator['key']},packet=core)
                    self._remember_block(packet)
                return packet
            raise ValueError('GG_PROTOCOL_COMMAND')

    def request_stop(self):
        with self._codec_lock:
            self._cancel.set();self._mine_cancel.set()
            self._codec_start_attempt=None;self._relay_session=None
            if self._codec_relay_attempt is not None:self._codec_relay_attempt.cancelled=True
            self._invalidate_codec(server=True,client=True)
        with self._view_lock:
            self._operator_pending=None
            if self._operator_start_state not in ('NONE','FAILED'):
                self._operator_start_state='STOPPED';self._operator_start_error=''
        if self._relay is not None:self._relay.request_stop()
        if self.node is not None:self.node.request_stop()
        if self._codec_pending_light is not None and self._codec_pending_light is not self.node:self._codec_pending_light.request_stop()

    def stop_node(self):
        self.request_stop()
        # An operator observer may still be opening a requested service. Join
        # it before snapshotting/closing every resulting ingress and journal.
        watcher=self._thread
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(8)
            if watcher.is_alive():raise ValueError('GG_PROTOCOL_WORK_STOP_PENDING')
        relay=self._relay;self._relay_policy=None;self._relay_session=None
        if relay is not None:
            # A pending close retains ownership for a later explicit retry.
            # Do not release journals or lose the server reference while a
            # callback or its native child remains alive.
            relay.close()
            if (self._codec_server is not None or self._codec_pending_relay is relay) and not self._codec_transport_retired(relay):
                raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
            self._release_codec_relay_attempt(relay)
            if self._relay is relay:self._relay=None
            if self._codec_pending_relay is relay:self._codec_pending_relay=None
        for thread in (self._thread,self._mine_thread,*tuple(self._transfers.values())):
            if thread is not None and thread is not threading.current_thread():thread.join(8)
            if thread is not None and thread.is_alive():raise ValueError('GG_PROTOCOL_WORK_STOP_PENDING')
        if self.producer is not None:self.producer.close();self.producer=None
        with self._drain_lock:self._drains.clear()
        self._relayed_sources.clear();self._inbox=None;self._uploads={};self._transfers.clear()
        # Ingress is invalidated and work has joined before releasing these
        # exclusive journals. A later run reopens their exact durable history.
        for book in self.pools.values():book.close()
        self.pools.clear();self._pool_reviews.clear()
        closing_node=self.node
        if closing_node is not None:closing_node.close();self.node=None
        if self._codec_pending_light is not None and self._codec_pending_light is not closing_node:self._codec_pending_light.close()
        self._retire_codec(server=True,client=True);self._codec_pending_light=None
        self._thread=None;self._mine_thread=None;self._revision+=1

    def close(self):
        self.stop_node()
        if self.owner is not None:
            # A retired/sibling native child may still belong to this owner.
            # Prove the whole group terminal before releasing profile journals;
            # pending close retains all fields for an explicit retry.
            from backend.gg_native_process_policy import close_owner
            close_owner(self.owner)
        for collection in (self.accounts,self.validators,self.replicas):
            for profile in collection.values():profile.close()
            collection.clear()
        if self.owner is not None:self.owner.close();self.owner=None
        from backend.gg_committee_history import close_all
        close_all()
