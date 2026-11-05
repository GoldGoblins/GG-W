"""Source2 sparse proof exchange on the authenticated private LAN.

The shared cache worker/lifecycle handles real source2 authorities. No legacy
global engine, order replay or producer key is fabricated. Original recovery
authenticates a bounded display window independently of account observation.
Construction is an explicit owned runtime action, never an import/status effect.
"""
from collections import OrderedDict
from copy import deepcopy
import http.client
import ipaddress
import json
import re
import threading
import time
from types import MappingProxyType
import weakref

from backend import gg_consensus as native,gg_dag_segmented as segmented
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_dag_proof_sync import BASE,MAX_PACKET,ProofExchange,PublicVerifier
from backend.gg_parallel_dag import pack
from backend.gg_segmented_authority import OwnedSegmentedSession
from backend.gg_dag_segmented_session import validate_bundle

HASH=re.compile(r'[0-9a-f]{64}')


def install(peer,bundle,*,start):
    contract=validate_bundle(bundle,peer._trusted)
    if peer._profile is None:raise ValueError('GG_SDK_OWNED_NODE_PROFILE_REQUIRED')
    if peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
    if peer._engine is not None or peer._tokens is not None:raise ValueError('GG_SDK_LEGACY_HISTORY_TRANSITION_REQUIRED')
    if peer._bundle is not None:
        if peer._bundle!=bundle:raise ValueError('GG_LAN_NETWORK_ALREADY_BOUND')
        if peer._proof_service is not None:
            if start:peer._proof_service.start()
            return peer.snapshot()
    roster={}
    for index,entry in enumerate(contract['roster']):
        row=entry['invite']['body']
        if ipaddress.ip_address(row['host']) not in peer.allowed:raise ValueError('GG_LAN_SUBNET')
        roster[row['peer_key']]={**deepcopy(row),'producer_indices':list(entry['producer_indices']),'credit_index':index}
    # Reject incompatible history or identity before the durable session bind.
    OwnedSegmentedSession(peer._profile,bundle)
    peer._bundle=deepcopy(bundle);peer._network=contract['network_id'];peer._roster=roster
    peer._local_indices=list(roster[peer.public_key]['producer_indices']) if peer.node_role=='producer' else []
    peer._dag_enabled=True
    service=peer._proof_factory(peer) if peer._proof_factory is not None else SegmentedProofExchange(peer,lambda:(),start=False)
    peer._proof_service=service
    if start:service.start()
    return peer.snapshot()


def peer_snapshot(peer):
    """Certified sparse observation; never fabricate replay or causal edges."""
    service=peer._proof_service;proof=service.snapshot() if service is not None else {}
    production=service.production.snapshot() if service is not None else {}
    commitment=proof.get('dag_segmented_commitment') if proof.get('state')!='FAULT' else None;profile=peer._profile
    with peer._lock:
        stopped=peer._cancel.is_set();peers=peer._peer_observations();identities=peer._producer_identities()
        authenticated=[{'label':row['label'],'producer_indices':row['producer_indices']} for row in peers if row['authenticated_recently']]
        contact=('STOPPED' if stopped else 'EXHAUSTED' if peer._transport_exhausted else
                 'CONNECTED' if peers and all(row['state']=='CONNECTED' for row in peers) else 'DEGRADED' if authenticated else 'DISCONNECTED')
        network={'state':'STOPPED' if stopped else 'EXHAUSTED' if peer._transport_exhausted else 'READY',
            'scope':'PRIVATE_LAN_SEGMENTED_SDK_EXPERIMENT','label':peer.label,'endpoint':{'host':peer.host,'port':peer.port},
            'allowed_cidr':str(peer.allowed),'public_key':peer.public_key,'trusted_coordinator':peer._trusted,
            'network_id':peer._network,'auto_produce':False,'producer_count':sum(row['producer_enabled'] for row in identities),
            'producer_slot_count':6,'local_producer_indices':list(peer._local_indices),'configured_peers':len(peer._roster),
            'candidate_invite_count':len(peer._candidates),'authenticated_peers':authenticated,'connection_state':contact,
            'peer_status':peers,'producer_identities':identities,
            'storage':{'enabled':True,'profile':profile.name,'state':'CLOSED' if profile._closed else 'FAULT' if profile._failed else 'READY',
                'keys_encrypted_at_rest':True,'whole_disk_rollback_protection':False},
            'participation':{'role':peer.node_role,'producer':peer.node_role=='producer','replica':False,'observer':True,
                'light_client':peer.node_role=='light','local_producer_count':len(peer._local_indices),
                'eligible_network_producers':sum(row['producer_enabled'] for row in identities),'consensus_validator':False,
                'verification_scope':'SDK_CERTIFICATES_AND_REQUESTED_ACTIVE_MEMBERSHIP','mining':False,'financial_execution':False,
                'ownership_basis':'PROTECTED_LOCAL_SIGNERS_AND_SIGNED_SESSION_ROSTER'},
            'network_kind':'PRIVATE_LAN','physical_hosts_verified':False,'traffic_confidentiality':False,
            'allow_test_tokens':False,'test_tokens_enabled':False,'allow_dag_transactions':peer.allow_dag_transactions,'transactions_enabled':True,
            'traffic_bytes':peer._raw_received,'traffic_bytes_basis':'APPLICATION_TCP_READ_BYTES',
            'charged_transport_bytes':peer._total_bytes,'authenticated_exchanges':sum(peer._peer_exchanges.values()),
            'rejected_frames':peer._rejected,'last_error':peer._last_error,'last_error_at':peer._last_error_at,
            'last_error_details':dict(peer._last_error_details),
            'transport':{'state':'STOPPED' if stopped else 'ACTIVE','credit_mode':'REFILLING_PER_INGRESS',
                'active_handlers':len(peer._handlers),'connections_admitted':peer._connections_admitted,
                'counters':deepcopy(peer._transport_counts),'history':deepcopy(list(peer._transport_history))}}
    producers=[]
    for identity in identities:
        index=identity['index'];author=commitment['authors'][index] if commitment is not None else None
        producers.append({**identity,'proposals':author['sequence'] if author else None,'transactions':author['nonce'] if author else None,
            'certified_sequence':author['sequence'] if author else None,'counts_basis':'SDK_CERTIFIED_AUTHOR_PREFIX'})
    return {'state':'STOPPED' if stopped else proof.get('state','WAITING_FOR_CERTIFICATE'),'mode':'SEGMENTED_SDK_CERTIFIED_VIEW',
        'producer_count':6,'worker_count':production.get('worker_count',0),'producers':producers,'canonical_finalized':commitment['blocks'] if commitment else 0,
        'certified_blocks':commitment['blocks'] if commitment else None,'certified_transactions':commitment['transactions'] if commitment else None,
        'blocks_admitted':None,'transactions_validated':None,'local_full_history_replayed':False,'lan':network,'dag_proofs':proof,
        'block_graph':{**proof.get('original_graph',{}),'topology':'CERTIFIED_ORIGINAL_DAG_WINDOW','source':'SDK_MEMBERSHIP_AND_SIGNED_ORIGINALS','producer_count':6,
            'producer_identities':identities,'causal_edges_verified':bool(proof.get('original_graph',{}).get('blocks')),'full_history_replayed':False},
        'test_accounts':[],'certified_test_accounts':[],'test_tokens':{'enabled':False,'accounts':[]},'token_circle':{'state':'DISABLED'},
        'dag_stress':{'supported':False,'enabled':True,'state':'IDLE','can_start':False,'worker_count':0,
            'transactions_per_block':0,'interval_ms':1000,'participants':[]},
        'dag_production':production,'dag_resources':peer.resources.snapshot()}


def validate_request(value):
    if (not isinstance(value,dict) or set(value)!={'kind','genesis_hash','height','selector'} or len(pack(value))>512
            or value['kind'] not in ('certificate','base','order','account','block','payload','closed','closed-payload')
            or type(value['genesis_hash']) is not str or not HASH.fullmatch(value['genesis_hash'])
            or type(value['height']) is not int or not 0<=value['height']<2**63):raise ValueError('GG_PROOF_REQUEST')
    kind=value['kind'];selector=value['selector']
    if kind=='certificate':
        if value['height']!=0 or selector!='':raise ValueError('GG_PROOF_REQUEST')
    elif value['height']==0:raise ValueError('GG_PROOF_REQUEST')
    elif kind=='base':
        if selector!='':raise ValueError('GG_PROOF_REQUEST')
    elif kind=='order':
        if type(selector) is not int or not 0<=selector<4095 or selector%32:raise ValueError('GG_PROOF_REQUEST')
    elif kind=='payload':
        from backend.gg_segmented_payloads import parse_selector
        parse_selector(selector)
    elif kind in ('closed','closed-payload'):
        from backend.gg_segmented_payloads import parse_closed_selector
        parse_closed_selector(selector,payload=kind=='closed-payload')
    elif type(selector) is not str or not HASH.fullmatch(selector):raise ValueError('GG_PROOF_REQUEST')
    return value


class SegmentedVerifier(PublicVerifier):
    def verify(self,packet,field=None):
        required=BASE if field is None else BASE|{'dag_segmented_base_proof'}|{field}
        if field=='dag_segmented_closed_page':required=BASE|{field}
        if not isinstance(packet,dict) or set(packet)!=required or len(pack(packet))>MAX_PACKET:raise ValueError('GG_PROOF_PACKET')
        tip=certificate_tip({name:packet[name] for name in BASE},self.anchor)
        if self.binary is None:
            self.binary=native._installed_binary(native.TOOLS);self.stamp=native._validate_binary_at(native.TOOLS,self.binary)
        if field is None:
            checked=native._verify_public(packet,self.binary,self.stamp)
            if (checked.get('dag_segmented_commitment')!=packet['state'].get('dag_segmented')
                    or checked.get('dag_history_replay_verified') is not False):raise ValueError('GG_SDK_SEGMENTED_STATE_REQUIRED')
        elif field=='dag_segmented_closed_page':
            segmented.verify_closed_membership(packet,self.anchor,binary=self.binary,stamp=self.stamp)
        else:
            segmented.verify_epoch_base(packet,self.anchor,binary=self.binary,stamp=self.stamp)
            if field!='dag_segmented_base_proof':segmented.verify_membership(packet,self.anchor,binary=self.binary,stamp=self.stamp)
        return tip


class SegmentedProofExchange(ProofExchange):
    """Real source2 policy using source-neutral bounded cache worker methods."""
    def __init__(self,peer,sources,*,start=True):
        if peer._profile is None:raise ValueError('GG_SDK_OWNED_NODE_PROFILE_REQUIRED')
        self.context=OwnedSegmentedSession(peer._profile,peer._bundle)
        self.peer=peer;self.sources=sources;self.anchor=self.context.anchor();self.verifier=SegmentedVerifier(self.anchor)
        self.cancel=threading.Event();self.lock=threading.RLock();self._conflict_lock=threading.RLock()
        self._fault_evidence=None;self._notified=weakref.WeakSet()
        self.certificates=OrderedDict();self.cache=OrderedDict();self.pending=OrderedDict();self.cache_bytes=0
        self.latest_local=None;self._certificate=None;self._certificate_info=None;self._view=None;self._members=None;self._floor=None
        self._fault='';self._error='';self._verified_at=None;self._received=0;self._loaded=False;self.payloads=None
        self._origin=None;self._producer_packet=None
        from backend.gg_segmented_submission import SegmentedSubmissions
        self.submissions=SegmentedSubmissions(peer,sources)
        from backend.gg_segmented_production import SegmentedProduction
        self.production=SegmentedProduction(self)
        from backend.gg_segmented_payloads import SegmentedPayloads
        self.payloads=SegmentedPayloads(self)
        self.server=threading.Thread(target=self._serve_work,name='GG-segmented-proof-cache',daemon=True)
        self.client=threading.Thread(target=self._client_work,name='GG-segmented-proof-observer',daemon=True)
        if start:self.start()

    def start(self):
        with self.lock:
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            for thread in (self.server,self.client):
                if thread.ident is None:thread.start()
            self.submissions.start()
            self.payloads.start()

    def reply(self,request):
        validate_request(request)
        if request['genesis_hash']!=self.anchor['genesis_hash']:raise ValueError('GG_PROOF_ANCHOR')
        if self._fault:
            evidence=self.cached_conflict()
            return {'state':'FAULT','evidence':evidence} if evidence is not None else {'state':'FAULT'}
        if self.peer._resources_paused():return {'state':'WAIT'}
        with self.lock:
            if request['kind']=='certificate':
                candidates=[packet for packet in (self.latest_local,self._certificate) if packet is not None]
                packet=max(candidates,key=lambda value:certificate_tip(value,self.anchor)[0]) if candidates else None
                return {'state':'READY','packet':deepcopy(packet)} if packet is not None else {'state':'WAIT'}
            key=self._key(request);raw=self.cache.get(key)
            if raw is not None:self.cache.move_to_end(key);return json.loads(raw)
            packet=self.certificates.get(request['height'])
            if packet is None:return {'state':'UNAVAILABLE'}
            if key not in self.pending:
                if len(self.pending)>=32:return {'state':'BUSY'}
                self.pending[key]=(deepcopy(request),deepcopy(packet))
            return {'state':'WAIT'}

    def _check_proven_base(self,proven,packet,field):
        tip=self.verifier.verify(proven,field);base={name:proven[name] for name in BASE}
        self._remember(base)
        if tip!=certificate_tip(packet,self.anchor) or base['state']!=packet['state']:raise ValueError('GG_PROOF_CERTIFICATE_CHANGED')

    def _observe(self,owner):
        self.context.check();deadline=time.monotonic()+120
        packet=self._fetch(owner,self._request('certificate'),deadline);height=self._accept_certificate(packet)[0]
        commitment=packet['state']['dag_segmented'];previous=self._view
        if previous is not None and previous['certificate']['state']['dag_segmented']==commitment:
            # Preserve the original proof/core context verbatim. A fresh SDK
            # certificate with the exact same DAG commitment authenticates the
            # same leaves, but does not rewrite their original proof height.
            self._origin='OWNED_SDK_PROOFS' if owner==self.peer.public_key else 'AUTHENTICATED_REMOTE_SDK_PROOFS';self._error=''
            return
        request=self._request('base',height);base=self._fetch(owner,request,deadline)
        self._check_proven_base(base,packet,'dag_segmented_base_proof');self._cache(self._key(request),{'state':'READY','packet':base})
        self._producer_packet=deepcopy(base)
        count=commitment['active']['blocks'];order=[];payload_proofs={}
        # Four actual pages at most. This is a relevant-membership projection,
        # never a complete global replay or a fabricated causal DAG graph.
        start=max(0,((count-1)//32-3)*32) if count else 0
        for cursor in range(start,count,32):
            request=self._request('order',height,cursor);proven=self._fetch(owner,request,deadline)
            self._check_proven_base(proven,packet,'dag_segmented_order_page');page=proven['dag_segmented_order_page']
            if page['start']!=cursor:raise ValueError('GG_PROOF_ORDER_CURSOR')
            order.extend(deepcopy(item['leaf']) for item in page['items']);self._cache(self._key(request),{'state':'READY','packet':proven})
            for item in page['items']:payload_proofs[item['leaf']['hash']]=proven
        if count==0:
            observation=segmented.verify_epoch_base(base,self.anchor,binary=self.verifier.binary,stamp=self.verifier.stamp)
            if observation['base']['commitment']!=commitment:raise ValueError('GG_PROOF_CERTIFICATE_CHANGED')
            accounts=deepcopy(observation['base']['accounts'])
        else:
            accounts=[]
            for public in self.anchor['genesis']['dag_segmented']['accounts']:
                request=self._request('account',height,public);proven=self._fetch(owner,request,deadline)
                self._check_proven_base(proven,packet,'dag_segmented_account_proof');leaf=proven['dag_segmented_account_proof']['leaf']
                if leaf['address']!=public:raise ValueError('GG_PROOF_ACCOUNT')
                accounts.append(deepcopy(leaf));self._cache(self._key(request),{'state':'READY','packet':proven})
        if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_PROOF_SYNC_CANCELLED')
        self.context.check()
        self._view={'certificate':deepcopy(packet),'base_packet':deepcopy(base),'order':order,'accounts':accounts,'payload_proofs':payload_proofs}
        self._members=(height,MappingProxyType({leaf['hash']:leaf['index'] for leaf in order}))
        self._origin='OWNED_SDK_PROOFS' if owner==self.peer.public_key else 'AUTHENTICATED_REMOTE_SDK_PROOFS';self._error=''

    def _client_work(self):
        owners=sorted({row['body']['owner_peer_key'] for row in self.anchor['genesis']['membership']['validators']});turn=0
        while not self.cancel.is_set() and not self.peer._cancel.is_set() and not self._fault:
            if self.peer._resources_paused():self.cancel.wait(.2);continue
            try:
                self.context.check()
                if not self._loaded:
                    record=self.peer._profile.consensus_observation()
                    if record is not None:
                        tip=self.verifier.verify(record['packet']);self._floor=tip;self._fault=record['fault']
                        if record.get('evidence') is not None:self._accept_conflict(record['evidence'])
                        if not self._fault:
                            public=deepcopy(record['packet']);self._certificate=public;self._certificate_info=(public,tip,time.time())
                            self._origin='PERSISTED_CERTIFICATE';self._remember(public)
                    self._loaded=True
                    if self._fault:break
                available=([self.peer.public_key] if self.latest_local is not None else [])+[owner for owner in owners if owner!=self.peer.public_key]
                if not available:raise ValueError('GG_PROOF_LOCAL_NOT_READY')
                owner=available[turn%len(available)];turn+=1;self._observe(owner)
            except (ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException) as error:
                code=str(error);self._error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_PROOF_OBSERVATION_UNAVAILABLE'
            self.cancel.wait(2)

    def snapshot(self):
        info=self._certificate_info;packet=info[0] if info else None;tip=info[1] if info else None;view=self._view
        shared=self.peer._profile._meta.get('consensus');fault=self._fault or (shared['fault'] if shared is not None else '')
        if self.peer._profile._failed:fault=fault or 'GG_SDK_OWNER_CLOSED'
        current=view is not None and packet is not None and view['certificate']['state']['dag_segmented']==packet['state']['dag_segmented']
        originals=self.payloads.snapshot()
        if fault:originals={**originals,'state':'FAULT','blocks':[],'edges':[]}
        return {'source':'AUTHENTICATED_LAN_SEGMENTED_SDK_PROOFS','role':self.peer.node_role,
            'state':'FAULT' if fault else 'STOPPED' if self.cancel.is_set() or self.peer._profile._closed else 'CERTIFIED' if current else 'SYNCING_PROOFS' if packet else 'WAITING_FOR_CERTIFICATE',
            'certificate_height':tip[0] if tip else None,'certificate_id':tip[1] if tip else None,
            'canonical_finality':packet is not None and not fault,'dag_segmented_commitment':deepcopy(packet['state']['dag_segmented']) if packet else None,
            'verified_at':info[2] if info else None,'observation_origin':self._origin,'canonical_order_complete':False,
            'certified_accounts':deepcopy(view['accounts']) if current and not fault else [],
            'accounts_certificate_height':int(view['certificate']['signed_header']['header']['height']) if current and not fault else None,
            'proven_blocks':deepcopy(view['order']) if current and not fault else [],'causal_edges_verified':False,
            'client_full_history_replayed':False,'network_liveness_asserted':False,
            'conflict_evidence_height':self._fault_evidence['height'] if self._fault_evidence is not None else None,
            'proof_payload_bytes':self._received,'last_error':fault or self._error,'durable_floor':True,
            'payload_recovery':{key:value for key,value in originals.items() if key not in ('blocks','edges')},
            'original_graph':{'blocks':originals['blocks'],'edges':originals['edges'],
                'verification_scope':'BOUNDED_AUTHENTICATED_ORIGINAL_WINDOW_NOT_FULL_HISTORY_REPLAY'},
            'submissions':self.submissions.snapshot()}

    def request_stop(self):
        self.production.request_stop();super().request_stop();self.submissions.request_stop()

    def close(self):
        self.request_stop()
        self.production.close()
        for thread in (self.server,self.client):
            if thread.ident is not None and thread is not threading.current_thread():thread.join(10)
        if any(thread.is_alive() and thread is not threading.current_thread() for thread in (self.server,self.client)):
            raise ValueError('GG_PROOF_WORKER_STOP_TIMEOUT')
        self.submissions.close()
        self.payloads.close()
