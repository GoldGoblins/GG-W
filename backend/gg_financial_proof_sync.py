"""Pinned financial certificates, creator contexts and receipts on signed LAN.

Read-only peers verify the same SDK root as the local CLI. Original producer
submissions use bounded authenticated transport; a queue ACK is not selection.
Nothing starts or chooses a network at import.
"""
from collections import OrderedDict
from copy import deepcopy
import http.client
import ipaddress
import json
import re
import threading
import time
import weakref

from backend.gg_dag_proof_sync import BASE,MAX_PACKET,ProofExchange,PublicVerifier
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_financial_authority import OwnedFinancialSession,OwnedFinancialAuthority
from backend.gg_financial_session import validate_bundle
from backend.gg_financial_producer import OwnedFinancialProducer
from backend.gg_financial_retry import OwnedFinancialRetry,TRANSIENT
from backend.gg_segmented_submission import SegmentedSubmissions
from backend.gg_parallel_dag import pack
from backend import gg_financial_dag as financial

HASH=re.compile(r'[0-9a-f]{64}')


def parse_receipt_selector(value):
    if type(value) is not str or len(value)>72 or not re.fullmatch(r'[0-9a-f]{64}:(0|[1-9][0-9]{0,4})',value):raise ValueError('GG_FINANCIAL_RECEIPT_SELECTOR')
    identifier,index=value.split(':')
    if int(index)>=50000:raise ValueError('GG_FINANCIAL_RECEIPT_SELECTOR')
    return identifier,int(index)


def validate_request(value):
    if (not isinstance(value,dict) or set(value)!={'kind','genesis_hash','height','selector'} or len(pack(value))>512
            or value['kind'] not in ('certificate','producer','receipt','account') or type(value['genesis_hash']) is not str
            or not HASH.fullmatch(value['genesis_hash']) or type(value['height']) is not int or not 0<=value['height']<2**63):raise ValueError('GG_FINANCIAL_PROOF_REQUEST')
    if value['kind']=='certificate':
        if value['height']!=0 or value['selector']!='':raise ValueError('GG_FINANCIAL_PROOF_REQUEST')
    elif value['height']==0:raise ValueError('GG_FINANCIAL_PROOF_REQUEST')
    elif value['kind']=='producer':
        if type(value['selector']) is not int or not 0<=value['selector']<6:raise ValueError('GG_FINANCIAL_PROOF_REQUEST')
    elif value['kind']=='account':financial.account_address(value['selector'])
    else:parse_receipt_selector(value['selector'])
    return value


class FinancialVerifier(PublicVerifier):
    def verify(self,packet,field=None,*,expected_account=None):
        if field not in (None,'financial_producer','financial_receipt','financial_account'):raise ValueError('GG_FINANCIAL_PROOF_KIND')
        if field=='financial_account':
            if not isinstance(packet,dict) or set(packet)!=BASE|{'financial_account','expected_financial_account'} or len(pack(packet))>MAX_PACKET:raise ValueError('GG_PROOF_PACKET')
            tip=certificate_tip({key:packet[key] for key in BASE},self.anchor)
            if self.binary is None:
                from backend import gg_consensus as native
                self.binary=native._installed_binary(native.TOOLS);self.stamp=native._validate_binary_at(native.TOOLS,self.binary)
            financial.verify_account(packet,self.anchor,expected_account,binary=self.binary,stamp=self.stamp)
        else:
            if expected_account is not None:raise ValueError('GG_FINANCIAL_PROOF_KIND')
            tip=super().verify(packet,field)
        if packet['state'].get('financial_dag',{}).get('schema') not in ('gg.financial-dag.commitment.v2','gg.financial-dag.commitment.v3','gg.financial-dag.commitment.v4'):raise ValueError('GG_FINANCIAL_CERTIFIED_STATE_REQUIRED')
        return tip


class FinancialSubmissions(SegmentedSubmissions):
    def _sources(self):
        return tuple(node for node in self.sources() if isinstance(node,OwnedFinancialAuthority) and node._alive() and not node._fault and not node._owner_stopped())

    def _submit(self,node,actor,raw):
        from backend import gg_financial_wire as wire
        raws=wire.decode_own_prefix(raw,node.anchor) if raw.startswith(b'{"blocks":') else [raw]
        return node.submit_proposals(actor,raws)


class FinancialProofExchange(ProofExchange):
    def __init__(self,peer,sources,*,start=True):
        if peer._profile is None:raise ValueError('GG_SDK_OWNED_NODE_PROFILE_REQUIRED')
        self.context=OwnedFinancialSession(peer._profile,peer._bundle);self.peer=peer;self.anchor=self.context.anchor()
        def owned_sources():return tuple(node for node in sources() if isinstance(node,OwnedFinancialAuthority) and node.anchor==self.anchor)
        self.sources=owned_sources;self.verifier=FinancialVerifier(self.anchor)
        self.cancel=threading.Event();self.lock=threading.RLock();self._conflict_lock=threading.RLock()
        self._fault_evidence=None;self._notified=weakref.WeakSet()
        self.certificates=OrderedDict();self.cache=OrderedDict();self.pending=OrderedDict();self.cache_bytes=0
        self.latest_local=None;self._certificate=None;self._certificate_info=None;self._view=None;self._members=None;self._floor=None
        self._fault='';self._error='';self._verified_at=None;self._received=0;self._loaded=False;self.payloads=None
        self._origin=None;self._last_provider=None;self._producer_lock=threading.Lock();self._producer_cancel=threading.Event();self._producer_active=False
        self._proven_blocks=OrderedDict();self._receipt_revision=0
        self._account_views=OrderedDict()
        self._owned_accounts=set();self._selected_account=None
        self._writer=None;self._submission_turn=0
        self._retry=OwnedFinancialRetry(self._retry_once)
        self.submissions=FinancialSubmissions(peer,self.sources)
        from backend.gg_financial_relay import AccountPaymentRelay
        self.account_relay=AccountPaymentRelay(self)
        self.server=threading.Thread(target=self._serve_work,name='GG-financial-proof-cache',daemon=True)
        self.client=threading.Thread(target=self._client_work,name='GG-financial-account-observer',daemon=True)
        if start:self.start()

    def start(self):
        with self.lock:
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            for worker in (self.server,self.client):
                if worker.ident is None:worker.start()
            self.submissions.start()
            self.account_relay.start()

    def select_owned_account(self,address):
        """Local protected-profile selection only; peer JSON cannot call this."""
        financial.account_address(address)
        if self.anchor['genesis']['schema']!='gg.native.genesis.v6':raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
        with self.lock:
            if address not in self._owned_accounts and len(self._owned_accounts)>=16:raise ValueError('GG_ACCOUNT_LOCAL_PROFILE_LIMIT')
            self._owned_accounts.add(address);self._selected_account=address

    def forget_owned_account(self,address):
        with self.lock:
            self._owned_accounts.discard(address)
            if self._selected_account==address:self._selected_account=None

    def reply(self,request):
        validate_request(request)
        if request['genesis_hash']!=self.anchor['genesis_hash']:raise ValueError('GG_PROOF_ANCHOR')
        if self._fault:
            evidence=self.cached_conflict();return {'state':'FAULT','evidence':evidence} if evidence is not None else {'state':'FAULT'}
        if self.peer._resources_paused():return {'state':'WAIT'}
        with self.lock:
            if request['kind']=='certificate':
                candidates=[packet for packet in (self.latest_local,self._certificate) if packet is not None]
                packet=max(candidates,key=lambda item:certificate_tip(item,self.anchor)[0]) if candidates else None
                return {'state':'READY','packet':deepcopy(packet)} if packet is not None else {'state':'WAIT'}
            key=self._key(request);raw=self.cache.get(key)
            if raw is not None:self.cache.move_to_end(key);return json.loads(raw)
            packet=self.certificates.get(request['height'])
            if packet is None:return {'state':'UNAVAILABLE'}
            if key not in self.pending:
                if len(self.pending)>=32:return {'state':'BUSY'}
                self.pending[key]=(deepcopy(request),deepcopy(packet))
            return {'state':'WAIT'}

    def _observe(self,owner):
        self.context.check();deadline=time.monotonic()+20
        core=self._fetch(owner,self._request('certificate'),deadline);self._accept_certificate(core)
        self._origin='OWNED_SDK_CERTIFICATE' if owner==self.peer.public_key else 'AUTHENTICATED_LAN_SDK_CERTIFICATE'
        self._view={'certificate':deepcopy(core)};self._last_provider=owner;self._error=''
        if self.anchor['genesis']['schema']=='gg.native.genesis.v6':
            own=sorted({row['body']['account_key'] for row in self.anchor['genesis']['membership']['validators'] if row['body']['owner_peer_key']==self.peer.public_key})
            with self.lock:selected=self._selected_account
            if selected is not None:own=[selected,*[address for address in own if address!=selected]]
            for address in own:
                request=self._request('account',certificate_tip(core,self.anchor)[0],address)
                proven=self._fetch(owner,request,deadline);self._check_requested(proven,core,'account',address)
                self._remember_account(proven,address);self._cache(self._key(request),{'state':'READY','packet':proven})
        # One bounded receipt per observation supplies an actual selected block
        # and its creator. It supplies no original parent edges or replay claim.
        for author in core['state']['financial_dag']['authors']:
            with self.lock:known=author['head'] in self._proven_blocks
            if author['sequence']=='0' or known:continue
            selector=author['head']+':0';request=self._request('receipt',certificate_tip(core,self.anchor)[0],selector)
            proven=self._fetch(owner,request,deadline);self._check_requested(proven,core,'receipt',selector)
            self._remember_receipt(proven);break

    def _check_requested(self,proven,core,kind,selector):
        if kind=='account':
            tip=self.verifier.verify(proven,'financial_account',expected_account=selector)
            base={key:proven.get(key) for key in BASE};self._remember(base)
            if tip!=certificate_tip(core,self.anchor) or base['state']!=core['state']:raise ValueError('GG_PROOF_CERTIFICATE_CHANGED')
            return
        self._check_proven_base(proven,core,'financial_'+kind)
        proof=proven['financial_'+kind]
        if kind=='producer':
            if proof['producer_index']!=selector:raise ValueError('GG_FINANCIAL_PROOF_SELECTOR_CHANGED')
        else:
            block,index=parse_receipt_selector(selector)
            if proof['context']['block_hash']!=block or proof['receipt']['leaf']['index']!=index:
                raise ValueError('GG_FINANCIAL_PROOF_SELECTOR_CHANGED')

    def _remember_account(self,proven,address):
        # Always retain the independent request during verification. An absence
        # witness authenticates an interval and cannot choose the requested key.
        self.verifier.verify(proven,'financial_account',expected_account=address)
        result=financial.verify_account(proven,self.anchor,address,binary=self.verifier.binary,stamp=self.verifier.stamp)
        account=result['financial_account'];exists=result['financial_account_exists']
        row={'address':address,'exists':exists,'balance_atomic':account['balance_atomic'] if exists else '0',
             'nonce':account['nonce'] if exists else '0','state_height':proven['state']['height'],
             'certificate_height':certificate_tip({key:proven[key] for key in BASE},self.anchor)[0],
             'state_root':proven['state']['state_root'],'verification_scope':result['financial_account_scope']}
        with self.lock:
            self._account_views[address]=row;self._account_views.move_to_end(address)
            while len(self._account_views)>64:self._account_views.popitem(last=False)

    def _remember_receipt(self,proven):
        proof=proven['financial_receipt'];context=proof['context'];creator=proof['creator'];summary=proof['summary']
        row={'hash':context['block_hash'],'global_index':context['order_index'],'transactions':summary['transactions'],
             'producer_index':creator['producer_index'],'producer_key':creator['key'],'sequence':creator['sequence'],
             'applied':summary['applied'],'rejected':summary['rejected'],
             'certificate_height':certificate_tip({key:proven[key] for key in BASE},self.anchor)[0],
             'verification_scope':'SDK_CERTIFIED_MONETARY_RECEIPT','original_payload_authenticated':False}
        with self.lock:
            self._proven_blocks[row['hash']]=row;self._proven_blocks.move_to_end(row['hash'])
            while len(self._proven_blocks)>128:self._proven_blocks.popitem(last=False)
            self._receipt_revision+=1

    def _client_work(self):
        owners=sorted({invite['body']['owner_peer_key'] for invite in self.anchor['genesis']['membership']['validators']});turn=0
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
                            core=deepcopy(record['packet']);self._certificate=core;self._certificate_info=(core,tip,None)
                            self._view={'certificate':core};self._origin='PERSISTED_CERTIFICATE';self._remember(core)
                    self._loaded=True
                    if self._fault:break
                available=([self.peer.public_key] if self.latest_local is not None else [])+[owner for owner in owners if owner!=self.peer.public_key]
                if not available:raise ValueError('GG_PROOF_LOCAL_NOT_READY')
                owner=available[turn%len(available)];turn+=1;self._observe(owner)
            except (ValueError,OSError,KeyError,TypeError,RuntimeError,http.client.HTTPException) as error:
                code=str(error);self._error=code if re.fullmatch(r'GG_[A-Z0-9_]{1,90}',code) else 'GG_FINANCIAL_OBSERVATION_UNAVAILABLE'
            self.cancel.wait(2)

    def requested_proof(self,kind,selector,*,check=lambda:None,cancel=None,deadline=None):
        if kind not in ('producer','receipt','account'):raise ValueError('GG_FINANCIAL_PROOF_KIND')
        validate_request(self._request(kind,1,selector))
        self.context.check();deadline=min(time.monotonic()+20,deadline) if deadline is not None else time.monotonic()+20
        def fetch(owner,request):
            if cancel is None:return self._fetch(owner,request,deadline)
            for _ in range(16):
                check()
                if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
                if time.monotonic()>=deadline:raise ValueError('GG_FINANCIAL_PROOF_UNAVAILABLE')
                result=self.reply(request) if owner==self.peer.public_key else self.peer.public_consensus_proof(owner,request,cancel=cancel)
                if not isinstance(result,dict):raise ValueError('GG_PROOF_RESPONSE')
                if result.get('state')=='FAULT' and set(result)=={'state','evidence'}:
                    self._accept_conflict(result['evidence']);raise ValueError('GG_PROOF_CONFLICT')
                if result.get('state')=='READY' and set(result)=={'state','packet'}:
                    self._received+=len(pack(result));return result['packet']
                if result.get('state') not in ('WAIT','BUSY'):raise ValueError('GG_PROOF_UNAVAILABLE')
                cancel.wait(min(.15,max(0,deadline-time.monotonic())))
            raise ValueError('GG_PROOF_WAIT_LIMIT')
        owners=([self.peer.public_key] if self.latest_local is not None else [])
        if self._last_provider is not None and self._last_provider not in owners:owners.append(self._last_provider)
        owners.extend(owner for owner in sorted({item['body']['owner_peer_key'] for item in self.anchor['genesis']['membership']['validators']}) if owner not in owners)
        failure=None
        for owner in owners:
            check()
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            try:
                core=fetch(owner,self._request('certificate'));height=self._accept_certificate(core)[0]
                request=self._request(kind,height,selector);validate_request(request)
                proven=fetch(owner,request);self._check_requested(proven,core,kind,selector)
                if kind=='receipt':self._remember_receipt(proven)
                if kind=='account':self._remember_account(proven,selector)
                self._cache(self._key(request),{'state':'READY','packet':proven});return proven
            except (ValueError,OSError,http.client.HTTPException) as error:failure=error
        check();raise ValueError('GG_FINANCIAL_PROOF_UNAVAILABLE') from failure

    def _producer_index(self,index):
        if self.peer.node_role!='producer':raise ValueError('GG_LAN_REPLICA_READ_ONLY')
        indices=self.peer._local_indices
        if index is None:index=indices[0] if indices else None
        if type(index) is not int or index not in indices:raise ValueError('GG_FINANCIAL_OWN_PRODUCER_REQUIRED')
        return index

    def _open_writer(self,packet,check):
        if self._writer is None:
            self._writer=OwnedFinancialProducer.open(self.peer._profile,self.peer._bundle,packet,binary=self.verifier.binary,stamp=self.verifier.stamp,check=check)
        return self._writer

    def _send_originals(self,originals,check,cancel,deadline):
        from backend import gg_financial_wire as wire
        raw=originals[0]['wire'] if len(originals)==1 else wire.encode_own_prefix(self.anchor,[row['wire'] for row in originals])
        check()
        if self.submissions._sources():return self.submissions.local(raw)
        owners=sorted({item['body']['owner_peer_key'] for item in self.anchor['genesis']['membership']['validators']}-{self.peer.public_key})
        if not owners:raise ValueError('GG_FINANCIAL_SUBMISSION_UNAVAILABLE')
        # A proof cache can be reachable without a local SDK submission
        # authority. Try every eligible owner within this finite budget.
        # Rotate between attempts so one timing-out owner cannot starve all
        # later owners. Every transmission carries the same durable bytes.
        turn=self._submission_turn%len(owners);self._submission_turn+=1
        owners=owners[turn:]+owners[:turn];result={'state':'UNAVAILABLE','SDK_selected':False}
        for owner in owners:
            check()
            if time.monotonic()>=deadline:break
            try:reply=self.submissions.send(owner,raw,cancel=cancel,deadline=min(deadline,time.monotonic()+20))
            except OSError:continue
            except ValueError as error:
                if str(error) not in TRANSIENT:raise
                continue
            if reply['state']=='QUEUED':return reply
            if reply['state']=='BUSY' or result['state']!='BUSY':result=reply
        return result

    def _retry_once(self,index,budget_check,cancel,deadline):
        def check():
            budget_check()
            if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            self.context.check()
            if self.peer._resources_paused():raise ValueError('GG_DAG_RESOURCE_PAUSED')
        check()
        if not self._producer_lock.acquire(blocking=False):raise ValueError('GG_FINANCIAL_PRODUCER_BUSY')
        self._producer_active=True
        try:
            from backend import gg_financial_wire as wire
            packet=self.requested_proof('producer',index,check=check,cancel=cancel,deadline=deadline)
            writer=self._open_writer(packet,check);plan=writer.pending_batch(packet,index,check=check)
            if plan is None:return {'state':'SELECTED' if int(packet['state']['financial_dag']['authors'][index]['sequence']) else 'IDLE','pending_blocks':0,'pending_payments':0}
            values=wire.authenticate_payments(plan['payments'],self.anchor,check=check)
            packet=self.requested_proof('producer',index,check=check,cancel=cancel,deadline=deadline)
            originals=writer.retry_batch(packet,plan,values,check=check)
            if not originals:return {'state':'SELECTED','pending_blocks':0,'pending_payments':0}
            result=self._send_originals(originals,check,cancel,deadline)
            return {'state':result['state'],'pending_blocks':len(originals),'pending_payments':sum(wire.decode_block(row['wire'],writer.source,self.anchor['genesis_hash'],int(packet['financial_producer']['epoch']),allow_previous_epoch=True)['payments'] for row in originals)}
        finally:self._producer_active=False;self._producer_lock.release()

    def resume_signed(self,index=None):
        """Explicitly resume only this owned creator's retained signed input."""
        index=self._producer_index(index)
        if self.cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
        if not self._producer_lock.acquire(blocking=False):raise ValueError('GG_FINANCIAL_PRODUCER_BUSY')
        try:self._retry.start(index);return {'state':'RETRYING','producer_index':index,'requires_payment_file':False,'SDK_selected':False,'payments_executed_asserted':False}
        finally:self._producer_lock.release()

    def submit_signed(self,payments,index=None,*,transactions_per_block=None):
        """Explicit finite request; never generate or sign account payments."""
        index=self._producer_index(index)
        if not self._producer_lock.acquire(blocking=False):raise ValueError('GG_FINANCIAL_PRODUCER_BUSY')
        self._producer_active=True;self._producer_cancel.clear();writer=None
        def check():
            if self.cancel.is_set() or self._producer_cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            self.context.check()
            if self.peer._resources_paused():raise ValueError('GG_DAG_RESOURCE_PAUSED')
        try:
            if self._retry.snapshot()['worker_active']:raise ValueError('GG_FINANCIAL_PRODUCER_BUSY')
            from backend import gg_financial_wire as wire
            # Authenticate and freeze account intent bytes before fetching the
            # creator context. Slow account checks do not age that context.
            values=wire.authenticate_payments(payments,self.anchor,check=check)
            check();packet=self.requested_proof('producer',index,check=check,cancel=self._producer_cancel,deadline=time.monotonic()+20)
            # This verifier tool was selected from owned local configuration,
            # never from a peer-provided executable path or assertion.
            writer=self._open_writer(packet,check)
            pending=writer.pending_batch(packet,index,check=check)
            size=len(values) if transactions_per_block is None else transactions_per_block
            if pending is not None and (pending['payments']!=values.rows(0,min(len(values),len(pending['payments']))) or pending['transactions_per_block']!=size):
                raise ValueError('GG_FINANCIAL_PENDING_ORIGINAL_REQUIRED')
            originals=writer.produce_batch(packet,values,len(values) if transactions_per_block is None else transactions_per_block,check=check)
            original=originals[0]
            try:result=self._send_originals(originals,check,self._producer_cancel,time.monotonic()+20)
            except OSError:result={'state':'UNAVAILABLE'}
            except ValueError as error:
                if str(error) not in TRANSIENT:raise
                result={'state':'UNAVAILABLE'}
            # A transport deadline or new resource pause after the durable
            # write must not strand the originals. Cancellation still fences
            # any new worker; the retry itself waits for owned resources.
            if self.cancel.is_set() or self._producer_cancel.is_set() or self.peer._cancel.is_set():raise ValueError('GG_LAN_STOPPED')
            self.context.check();self._retry.start(index)
            return {'state':result['state'],'block':original['hash'],'producer_index':index,'signed_payments':len(payments),
                    'blocks':[row['hash'] for row in originals],'original_durable':True,'automatic_retry':True,'SDK_selected':False,'payments_executed_asserted':False}
        finally:
            self._producer_active=False;self._producer_lock.release()

    def stop_production(self):
        self._producer_cancel.set();self._retry.stop();active=self._producer_active or self._retry.snapshot()['worker_active']
        return {'state':'STOPPING' if active else 'IDLE','worker_active':active}

    def snapshot(self):
        info=self._certificate_info;core=info[0] if info is not None else None;tip=info[1] if info is not None else None
        state=core['state'] if core is not None else None;fault=self._fault;retry=self._retry.snapshot()
        own={item['body']['account_key'] for item in self.anchor['genesis']['membership']['validators'] if item['body']['owner_peer_key']==self.peer.public_key}
        with self.lock:own|=self._owned_accounts;selected=self._selected_account
        if state is not None and not fault and state['accounts'] is None:
            with self.lock:
                accounts=[deepcopy(row) for row in self._account_views.values()
                          if row['state_height']==state['height'] and row['state_root']==state['state_root']]
        else:accounts=deepcopy(state['accounts']) if state is not None and not fault else []
        # Public UI JSON passes through JavaScript; preserve the uint64 nonce
        # as decimal text without changing the canonical native proof packet.
        for account in accounts:account['nonce']=str(account['nonce'])
        accounts.sort(key=lambda row:row['address']!=selected)
        return {'source':self._origin,'role':self.peer.node_role,'state':'FAULT' if fault else 'CERTIFIED' if core is not None else 'WAITING_FOR_CERTIFICATE',
                'certificate_height':tip[0] if tip else None,'canonical_finality':core is not None and not fault,
                'certificate_id':tip[1] if tip else None,
                'financial_dag_commitment':deepcopy(state['financial_dag']) if state is not None and not fault else None,
                'verified_at':info[2] if info is not None else None,'certificate_is_network_liveness':False,
                'certified_accounts':accounts,'own_accounts':[row for row in accounts if row['address']==selected] if selected is not None else [row for row in accounts if row['address'] in own],
                'selected_account':selected,
                'account_tree':deepcopy(state.get('account_tree')) if state is not None and not fault else None,
                'accounts_basis':'REQUESTED_CERTIFIED_MEMBERSHIP_OR_ABSENCE' if self.anchor['genesis']['schema']=='gg.native.genesis.v6' else 'CERTIFIED_FULL_FIXED_TEST_ACCOUNT_LIST',
                'proven_blocks':self._receipt_rows() if not fault else [],
                'proof_payload_bytes':self._received,'last_error':fault or self._error,'durable_floor':True,
                'client_full_history_replayed':False,'submissions':self.submissions.snapshot(),'account_relay':self.account_relay.snapshot(),
                'production':{**retry,'state':'SIGNING_OR_TRANSMITTING' if self._producer_active else retry['state'],'worker_active':self._producer_active or retry['worker_active'],
                              'requires_account_signed_payments':True,'test_payments_manufactured':False}}

    def _receipt_rows(self):
        with self.lock:return deepcopy(list(self._proven_blocks.values()))

    def telemetry_revision(self):
        retry=self._retry.snapshot()
        return (*super().telemetry_revision(),self._receipt_revision,self._producer_active,
                *self.account_relay.telemetry_revision(),
                *(retry.get(key) for key in ('state','worker_active','attempts','pending_blocks','pending_payments','last_error')))

    def request_stop(self):
        self.account_relay.request_stop();self.stop_production();super().request_stop();self.submissions.request_stop()

    def close(self):
        self.request_stop()
        self._retry.close()
        for worker in (self.server,self.client):
            if worker.ident is not None and worker is not threading.current_thread():worker.join(10)
        if any(worker.is_alive() and worker is not threading.current_thread() for worker in (self.server,self.client)):raise ValueError('GG_PROOF_WORKER_STOP_TIMEOUT')
        if self._producer_lock.acquire(timeout=10):
            try:
                if self._writer is not None:self._writer.close();self._writer=None
            finally:self._producer_lock.release()
        else:raise ValueError('GG_FINANCIAL_PRODUCER_STOP_TIMEOUT')
        self.submissions.close()
        self.account_relay.close()


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
    OwnedFinancialSession(peer._profile,bundle)
    peer._bundle=deepcopy(bundle);peer._network=contract['network_id'];peer._roster=roster
    peer._local_indices=list(roster[peer.public_key]['producer_indices']) if peer.node_role=='producer' else []
    peer._dag_enabled=True
    service=peer._proof_factory(peer) if peer._proof_factory is not None else FinancialProofExchange(peer,lambda:(),start=False)
    peer._proof_service=service
    if start:service.start()
    return peer.snapshot()


def peer_snapshot(peer):
    service=peer._proof_service;proof=service.snapshot() if service is not None else {}
    commitment=proof.get('financial_dag_commitment');profile=peer._profile
    with peer._lock:
        stopped=peer._cancel.is_set();peers=peer._peer_observations();identities=peer._producer_identities()
        authenticated=[{'label':row['label'],'producer_indices':row['producer_indices']} for row in peers if row['authenticated_recently']]
        contact='STOPPED' if stopped else 'EXHAUSTED' if peer._transport_exhausted else 'CONNECTED' if peers and all(row['state']=='CONNECTED' for row in peers) else 'DEGRADED' if authenticated else 'DISCONNECTED'
        network={'state':'STOPPED' if stopped else 'READY','scope':'PRIVATE_LAN_FINANCIAL_SDK_EXPERIMENT','label':peer.label,
            'endpoint':{'host':peer.host,'port':peer.port},'allowed_cidr':str(peer.allowed),'public_key':peer.public_key,
            'trusted_coordinator':peer._trusted,'network_id':peer._network,'auto_produce':False,'producer_slot_count':6,
            'producer_count':sum(row['producer_enabled'] for row in identities),'local_producer_indices':list(peer._local_indices),
            'configured_peers':len(peer._roster),'authenticated_peers':authenticated,'connection_state':contact,'peer_status':peers,
            'producer_identities':identities,'network_kind':'PRIVATE_LAN','physical_hosts_verified':False,'traffic_confidentiality':False,
            'allow_test_tokens':False,'test_tokens_enabled':False,'allow_dag_transactions':peer.allow_dag_transactions,'transactions_enabled':True,
            'storage':{'enabled':True,'profile':profile.name,'state':'CLOSED' if profile._closed else 'FAULT' if profile._failed else 'READY','keys_encrypted_at_rest':True,'whole_disk_rollback_protection':False},
            'participation':{'role':peer.node_role,'producer':peer.node_role=='producer','replica':False,'observer':True,
                'light_client':peer.node_role=='light','local_producer_count':len(peer._local_indices),
                'eligible_network_producers':sum(row['producer_enabled'] for row in identities),'consensus_validator':False,
                'verification_scope':'SDK_CERTIFICATES_ACCOUNT_STATE_AND_REQUESTED_MONETARY_RECEIPTS','mining':False,'financial_execution':True,
                'ownership_basis':'PROTECTED_LOCAL_SIGNERS_AND_SIGNED_SESSION_ROSTER'},
            'traffic_bytes':peer._raw_received,'traffic_bytes_basis':'APPLICATION_TCP_READ_BYTES','charged_transport_bytes':peer._total_bytes,
            'authenticated_exchanges':sum(peer._peer_exchanges.values()),'rejected_frames':peer._rejected,
            'last_error':peer._last_error,'last_error_at':peer._last_error_at,'last_error_details':dict(peer._last_error_details),
            'transport':{'state':'STOPPED' if stopped else 'ACTIVE','active_handlers':len(peer._handlers),
                'counters':deepcopy(peer._transport_counts),'history':deepcopy(list(peer._transport_history))}}
    producers=[]
    source=service.anchor['genesis']['financial_dag'] if service is not None else None
    for identity in identities:
        index=identity['index'];author=commitment['authors'][index] if commitment is not None else None
        producers.append({**identity,'producer_key':source['producers'][index] if source else None,'proposals':author['sequence'] if author else None,
            'transactions':author['attempts'] if author else None,'certified_sequence':author['sequence'] if author else None,
            'last_block':author['head'] if author and author['sequence']!='0' else None,'counts_basis':'SDK_CERTIFIED_BLOCKS_AND_PAYMENT_ATTEMPTS_NOT_REWARDS'})
    return {'state':'STOPPED' if stopped else proof.get('state','WAITING_FOR_CERTIFICATE'),'mode':'FINANCIAL_SDK_CERTIFIED_VIEW',
        'producer_count':6,'worker_count':int(proof.get('production',{}).get('worker_active',False)),'producers':producers,
        'canonical_finalized':commitment['blocks'] if commitment else 0,'certified_blocks':commitment['blocks'] if commitment else None,
        'certified_transactions':commitment['applied'] if commitment else None,'rejected_transactions':commitment['rejected'] if commitment else None,
        'blocks_admitted':None,'transactions_validated':None,'local_full_history_replayed':False,'lan':network,'dag_proofs':proof,
        'financial_accounts':proof.get('certified_accounts',[]),'own_financial_accounts':proof.get('own_accounts',[]),
        'financial_account_relay':proof.get('account_relay',{}),
        'block_graph':{'blocks':[],'edges':[],'source':'NO_ORIGINAL_BLOCK_WINDOW_FETCHED','producer_count':6,'producer_identities':identities,
            'causal_edges_verified':False,'full_history_replayed':False},
        'test_accounts':[],'certified_test_accounts':[],'test_tokens':{'enabled':False,'accounts':[]},'token_circle':{'state':'DISABLED'},
        'dag_stress':{'supported':False,'enabled':False,'state':'DISABLED','can_start':False,'worker_count':0,'participants':[]},
        'dag_production':proof.get('production',{}),'dag_resources':peer.resources.snapshot()}
