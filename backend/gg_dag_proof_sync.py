"""Bounded public proof exchange over the already authenticated private LAN.

TCP handlers only read caches/enqueue bounded work. SDK verification, native
RPC and durable floors run in owned workers. Nothing starts on import/status.
"""
from collections import OrderedDict
from copy import deepcopy
import http.client
import json
import re
import threading
import time
import weakref
from types import MappingProxyType

from backend import gg_consensus as native
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_dag_checkpoint import certificate_tip,check_complete_order,make_conflict_evidence,validate_conflict_evidence,CONFLICT
from backend.gg_parallel_dag import pack

HASH=re.compile(r'[0-9a-f]{64}')
MAX_PACKET=256*1024-64
BASE=frozenset(('schema','genesis','genesis_hash','state','signed_header'))


def validate_request(value):
    if (not isinstance(value,dict) or set(value)!={'kind','genesis_hash','height','selector'} or len(pack(value))>512
            or value['kind'] not in ('certificate','order','account','block')
            or not isinstance(value['genesis_hash'],str) or not HASH.fullmatch(value['genesis_hash'])
            or type(value['height']) is not int or not 0<=value['height']<2**63):raise ValueError('GG_PROOF_REQUEST')
    kind=value['kind'];selector=value['selector']
    if kind=='certificate':
        if value['height']!=0 or selector!='':raise ValueError('GG_PROOF_REQUEST')
    elif value['height']==0:raise ValueError('GG_PROOF_REQUEST')
    elif kind=='order':
        if type(selector) is not int or not 0<=selector<4095 or selector%32:raise ValueError('GG_PROOF_REQUEST')
    elif not isinstance(selector,str) or not HASH.fullmatch(selector):raise ValueError('GG_PROOF_REQUEST')
    return value


class PublicVerifier:
    def __init__(self,anchor):
        self.anchor=deepcopy(anchor);self.binary=None;self.stamp=None

    def verify(self,packet,field=None):
        if not isinstance(packet,dict) or set(packet)!=BASE|({field} if field else set()) or len(pack(packet))>MAX_PACKET:
            raise ValueError('GG_PROOF_PACKET')
        base={name:packet[name] for name in BASE};tip=certificate_tip(base,self.anchor)
        if self.binary is None:
            self.binary=native._installed_binary(native.TOOLS)
            self.stamp=native._validate_binary_at(native.TOOLS,self.binary)
        result=native._verify_public(packet,self.binary,self.stamp)
        if field is not None and result.get(field+'_verified') is not True:raise ValueError('GG_PROOF_MEMBERSHIP_REQUIRED')
        return tip

    def verify_conflict(self,evidence):
        validate_conflict_evidence(evidence,self.anchor)
        for packet in evidence['certificates']:self.verify(packet)
        return evidence['height']


class ProofExchange:
    def __init__(self,peer,sources):
        self.peer=peer;self.sources=sources;self.anchor=anchor_from_owned_peer(peer)
        self.verifier=PublicVerifier(self.anchor);self.cancel=threading.Event();self.lock=threading.RLock()
        self._conflict_lock=threading.RLock();self._fault_evidence=None;self._notified=weakref.WeakSet()
        self.certificates=OrderedDict();self.cache=OrderedDict();self.pending=OrderedDict();self.cache_bytes=0
        self.latest_local=None;self._certificate=None;self._certificate_info=None;self._view=None;self._members=None;self._floor=None
        self._fault='';self._error='';self._verified_at=None;self._received=0;self._loaded=False
        from backend.gg_dag_order_history import OrderHistory
        self._order_history=OrderHistory(self.anchor['genesis']['dag'])
        from backend.gg_dag_payloads import PayloadRecovery
        self.payloads=PayloadRecovery(self) if peer.node_role!='light' else None
        self.server=threading.Thread(target=self._serve_work,name='GG-public-proof-cache',daemon=True)
        self.client=threading.Thread(target=self._client_work,name='GG-public-proof-observer',daemon=True)
        self.server.start();self.client.start()

    def _request(self,kind,height=0,selector=''):
        return {'kind':kind,'genesis_hash':self.anchor['genesis_hash'],'height':height,'selector':selector}

    @staticmethod
    def _key(request):return request['kind'],request['height'],request['selector']

    def _remember(self,packet):
        tip=certificate_tip(packet,self.anchor);height=tip[0]
        with self.lock:
            previous=self.certificates.get(height)
            if previous is None or certificate_tip(previous,self.anchor)==tip:
                self.certificates[height]=deepcopy(packet);self.certificates.move_to_end(height)
                while len(self.certificates)>64:self.certificates.popitem(last=False)
                return
        # Never hold the handler/cache mutex during SDK, durable writes or stop.
        self._accept_conflict(make_conflict_evidence(previous,packet,self.anchor))
        raise ValueError(CONFLICT)

    def _notify_conflict_sources(self,evidence):
        for node in tuple(self.sources()):
            if self.cancel.is_set():break
            with self._conflict_lock:
                if node in self._notified:continue
                self._notified.add(node)
            try:node.observe_conflict(evidence)
            except (ValueError,OSError,RuntimeError):
                if node.cached_conflict() is None or node.snapshot().get('owned_native_process') is True:
                    with self._conflict_lock:self._notified.discard(node)

    def _accept_conflict(self,evidence):
        validate_conflict_evidence(evidence,self.anchor)
        evidence=deepcopy(evidence)
        self.verifier.verify_conflict(evidence)
        try:
            with self._conflict_lock:
                if self._fault_evidence is None:
                    if self.peer._profile is not None:
                        self.peer._profile.save_consensus_conflict(evidence)
                        stored=self.peer._profile.consensus_observation()['evidence']
                        if stored!=evidence:self.verifier.verify_conflict(stored)
                        evidence=stored
                    self._fault_evidence=deepcopy(evidence)
                self._fault=CONFLICT
        except (ValueError,OSError):
            self._fault='GG_NODE_STORE_WRITE_FAILED'
            self._notify_conflict_sources(evidence)
            raise
        with self.lock:self.pending.clear();self.cache.clear();self.cache_bytes=0
        self._notify_conflict_sources(self._fault_evidence)

    def cached_conflict(self):return deepcopy(self._fault_evidence)

    def _cache(self,key,result):
        raw=pack(result)
        if len(raw)>256*1024:raise ValueError('GG_PROOF_PACKET')
        with self.lock:
            previous=self.cache.pop(key,None)
            if previous is not None:self.cache_bytes-=len(previous)
            self.cache[key]=raw;self.cache_bytes+=len(raw)
            while len(self.cache)>64 or self.cache_bytes>8*1024*1024:
                _,discarded=self.cache.popitem(last=False);self.cache_bytes-=len(discarded)

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

    def _serve_work(self):
        while not self.cancel.is_set() and not self.peer._cancel.is_set():
            if self.peer._resources_paused():self.cancel.wait(.2);continue
            try:
                all_sources=tuple(self.sources())
                if self._fault_evidence is not None:
                    self._notify_conflict_sources(self._fault_evidence);self.cancel.wait(.2);continue
                for node in all_sources:
                    evidence=node.cached_conflict()
                    if isinstance(evidence,dict):self._accept_conflict(evidence)
                if self._fault:self.cancel.wait(.2);continue
                sources=tuple(node for node in all_sources if node.snapshot().get('owned_native_process') is True)
                latest=None
                for node in sources:
                    packet=node.cached_certificate()
                    if packet is not None:
                        self._remember(packet)
                        if latest is None or certificate_tip(packet,self.anchor)[0]>=certificate_tip(latest,self.anchor)[0]:latest=packet
                self.latest_local=latest
                with self.lock:
                    work=self.pending.popitem(last=False)[1] if self.pending else None
                if work is not None:
                    request,packet=work;result={'state':'UNAVAILABLE'}
                    for node in sources:
                        if self.cancel.is_set():break
                        try:
                            proof=node.export_cached_proof(packet,request['kind'],request['selector'])
                            result={'state':'READY','packet':proof};break
                        except (ValueError,OSError,KeyError,TypeError,http.client.HTTPException):continue
                    self._cache(self._key(request),result)
            except (ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException):pass
            self.cancel.wait(.05 if self.pending else .2)

    def _fetch(self,owner,request,deadline):
        for _ in range(16):
            if self.cancel.is_set() or self.peer._cancel.is_set() or time.monotonic()>=deadline:raise ValueError('GG_PROOF_SYNC_CANCELLED')
            result=self.reply(request) if owner==self.peer.public_key else self.peer.public_consensus_proof(owner,request,cancel=self.cancel)
            if not isinstance(result,dict):raise ValueError('GG_PROOF_RESPONSE')
            if result.get('state')=='FAULT' and set(result)=={'state','evidence'}:
                self._accept_conflict(result['evidence']);raise ValueError(CONFLICT)
            if result.get('state')=='READY' and set(result)=={'state','packet'}:
                self._received+=len(pack(result));return result['packet']
            if result.get('state') not in ('WAIT','BUSY'):raise ValueError('GG_PROOF_UNAVAILABLE')
            self.cancel.wait(.15)
        raise ValueError('GG_PROOF_WAIT_LIMIT')

    def _accept_certificate(self,packet):
        tip=self.verifier.verify(packet)
        self._remember(packet)
        with self._conflict_lock:
            if self._fault:raise ValueError(self._fault)
            if self._floor is not None:
                if tip[0]<self._floor[0]:raise ValueError('GG_PROOF_CERTIFICATE_REWIND')
                if tip[0]==self._floor[0] and tip!=self._floor:
                    self._accept_conflict(make_conflict_evidence(self._certificate,packet,self.anchor));raise ValueError(CONFLICT)
            try:
                if self.peer._profile is not None:self.peer._profile.save_consensus_certificate(packet)
            except (ValueError,OSError):self._fault='GG_NODE_STORE_WRITE_FAILED';raise
            public=deepcopy(packet);observed=time.time()
            self._floor=tip;self._certificate=public;self._verified_at=observed
            self._certificate_info=(public,tip,observed)
        return tip

    def _check_proven_base(self,proven,packet,field):
        tip=self.verifier.verify(proven,field)
        base={name:proven.get(name) for name in BASE};expected=certificate_tip(packet,self.anchor)
        self._remember(base)
        if tip!=expected or base['state']!=packet['state']:raise ValueError('GG_PROOF_CERTIFICATE_CHANGED')

    def _observe(self,owner):
        deadline=time.monotonic()+120
        packet=self._fetch(owner,self._request('certificate'),deadline);height=self._accept_certificate(packet)[0]
        commitment=packet['state']['dag'];previous=self._view
        if previous is not None and previous['certificate']['state']['dag']==commitment:
            view={**previous,'certificate':deepcopy(packet)}
        else:
            order=[];light=self.peer.node_role=='light';count=commitment['blocks']
            cursor=((count-1)//32)*32 if light and count else 0
            def check():
                if self.cancel.is_set() or self.peer._cancel.is_set() or time.monotonic()>=deadline:raise ValueError('GG_PROOF_SYNC_CANCELLED')
            def fetch(cursor):
                request=self._request('order',height,cursor);proven=self._fetch(owner,request,deadline)
                self._check_proven_base(proven,packet,'dag_order_page');page=proven['dag_order_page']
                if page['start']!=cursor:raise ValueError('GG_PROOF_ORDER_CURSOR')
                self._cache(self._key(request),{'state':'READY','packet':proven});return page
            if light:order=[deepcopy(item['leaf']) for item in fetch(cursor)['items']]
            else:
                candidate=self._order_history.fetch(packet['state'],fetch,check);order=candidate.order()
                if self.peer._profile is not None:self.peer._profile.save_verified_order(packet,order)
                self._order_history=candidate
            accounts=[]
            for public in self.peer.public_invite()['body']['producer_keys']:
                request=self._request('account',height,public);proven=self._fetch(owner,request,deadline)
                self._check_proven_base(proven,packet,'dag_account_proof')
                if proven['dag_account_proof']['leaf']['address']!=public:raise ValueError('GG_PROOF_ACCOUNT')
                accounts.append(deepcopy(proven['dag_account_proof']['leaf']));self._cache(self._key(request),{'state':'READY','packet':proven})
            view={'certificate':deepcopy(packet),'order':order,'accounts':accounts}
        if self.peer.node_role!='light':
            recovery=self.peer.recover_certified_payloads(packet['state'],view['order'],preferred=owner)
            if recovery['remaining']:raise ValueError('GG_DAG_CANONICAL_PAYLOAD_PENDING')
            self.peer._engine.apply_certified_order(packet['state'],view['order'],self.anchor['genesis']['dag'])
        self._view=view;self._members=(height,MappingProxyType({leaf['hash']:leaf['index'] for leaf in view['order']}));self._error=''

    def _client_work(self):
        owners=sorted({row['body']['owner_peer_key'] for row in self.anchor['genesis']['membership']['validators']});turn=0
        while not self.cancel.is_set() and not self.peer._cancel.is_set() and not self._fault:
            if self.peer._resources_paused():self.cancel.wait(.2);continue
            try:
                if not self._loaded:
                    record=self.peer._profile.consensus_observation() if self.peer._profile is not None else None
                    if record is not None:
                        tip=self.verifier.verify(record['packet']);self._floor=tip;self._fault=record['fault']
                        if record.get('evidence') is not None:self._accept_conflict(record['evidence'])
                        if not self._fault:
                            public=deepcopy(record['packet']);self._certificate=public
                            self._certificate_info=(public,tip,time.time());self._remember(public)
                    if self.peer.node_role!='light' and self.peer._profile is not None:
                        saved=self.peer._profile.verified_order()
                        if saved is not None:
                            from backend.gg_dag_order_history import OrderHistory
                            self.verifier.verify(saved['packet']);self._remember(saved['packet'])
                            self._order_history=OrderHistory.restore(self.anchor['genesis']['dag'],saved['packet']['state'],saved['order'])
                    self._loaded=True
                    if self._fault:break
                remote=[owner for owner in owners if owner!=self.peer.public_key]
                available=([self.peer.public_key] if self.latest_local is not None else [])+remote
                owner=available[turn%len(available)] if available else self.peer.public_key;turn+=1
                if owner==self.peer.public_key and self.latest_local is None:raise ValueError('GG_PROOF_LOCAL_NOT_READY')
                self._observe(owner)
            except (ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException) as error:
                code=str(error);self._error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_PROOF_OBSERVATION_UNAVAILABLE'
            self.cancel.wait(2)

    def canonical_membership(self):return None if self._fault else self._members

    def request_payloads(self,actor,hashes):
        if self.payloads is not None:self.payloads.request(actor,hashes)

    def telemetry_revision(self):
        # Membership/account verification can finish after the final network
        # read. Its own revision must wake Desktop even on an idle transport.
        members=self._members;info=self._certificate_info
        payload=self.payloads.snapshot() if self.payloads is not None else {}
        return ('SDK_PROOFS',info[1] if info else None,members[0] if members else None,self._fault,self._error,self._received,
            payload.get('pending'),payload.get('recovered_blocks'),payload.get('last_error'))

    def snapshot(self):
        info=self._certificate_info;packet=info[0] if info else None;tip=info[1] if info else None
        view=self._view;fault=self._fault
        current=view is not None and packet is not None and view['certificate']['state']['dag']==packet['state']['dag']
        return {'source':'AUTHENTICATED_LAN_SDK_PROOFS','role':self.peer.node_role,
            'state':'FAULT' if fault else 'CERTIFIED' if current else 'SYNCING_PROOFS' if packet else 'WAITING_FOR_CERTIFICATE',
            'certificate_height':tip[0] if tip else None,'certificate_id':tip[1] if tip else None,
            'canonical_finality':packet is not None and not fault,'dag_commitment':deepcopy(packet['state']['dag']) if packet else None,
            'verified_at':info[2] if info else None,'canonical_order_complete':current and self.peer.node_role!='light' and not fault,
            'certified_accounts':deepcopy(view['accounts']) if current and not fault else [],
            'accounts_certificate_height':int(view['certificate']['signed_header']['header']['height']) if current and not fault else None,
            'proven_blocks':deepcopy(view['order'][-32:]) if view is not None and not fault else [],
            'conflict_evidence_height':self._fault_evidence['height'] if self._fault_evidence is not None else None,
            'proof_payload_bytes':self._received,'last_error':fault or self._error,'durable_floor':self.peer._profile is not None,
            'payload_recovery':self.payloads.snapshot() if self.payloads is not None else {'enabled':False,'state':'LIGHT_PROOFS_ONLY'}}

    def request_stop(self):
        self.cancel.set()
        if self.payloads is not None:self.payloads.request_stop()

    def close(self):
        self.request_stop()
        for thread in (self.server,self.client):
            if thread is not threading.current_thread():thread.join(10)
        if any(thread.is_alive() and thread is not threading.current_thread() for thread in (self.server,self.client)):
            raise ValueError('GG_PROOF_WORKER_STOP_TIMEOUT')
        if self.payloads is not None:self.payloads.close()
