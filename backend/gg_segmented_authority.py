"""Owned persistent source2 SDK authority for an explicit signed v5 session.

The context owns no listener or private signing key. The authority starts one
leased validator child from its protected ValidatorProfile. It does not pretend
that a legacy LanDagPeer has installed or activated a v5 global DAG engine.
"""
import atexit
import base64
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import threading
import time

from backend import gg_consensus as native,gg_dag_segmented as segmented
from backend import gg_dag_execution_policy as execution_rules
from backend.gg_consensus_process import OwnedNativeRPC
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_dag_segmented_session import validate_bundle
from backend.gg_node_store import NodeProfile
from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence,validate_conflict_evidence

_OWNED=set()


class OwnedSegmentedSession:
    """Explicit immutable session binding on a genuinely owned node profile."""
    def __init__(self,profile,bundle):
        if not isinstance(profile,NodeProfile):raise ValueError('GG_SDK_OWNED_NODE_PROFILE_REQUIRED')
        with profile._lock:
            if profile._closed or profile._failed or profile._db is None:raise ValueError('GG_SDK_OWNER_CLOSED')
            descriptor=profile.descriptor();contract=validate_bundle(bundle,descriptor['trusted_coordinator'])
            own=[entry for entry in contract['roster'] if entry['invite']['body']['peer_key']==descriptor['public_keys'][0]]
            if len(own)!=1:raise ValueError('GG_SDK_SESSION_OWNER')
            row=own[0]['invite']['body']
            if (row['producer_keys']!=descriptor['public_keys'][1:] or row['nonce']!=descriptor['pair_nonce']
                    or (row['host'],row['port'])!=(descriptor['host'],descriptor['port'])
                    or row.get('node_role','producer')!=descriptor.get('node_role','producer')
                    or descriptor['allow_dag_transactions'] is not True):raise ValueError('GG_SDK_SESSION_OWNER')
            shared=profile.consensus_observation()
            if profile._head['entries'] or profile._meta.get('order_index'):
                raise ValueError('GG_SDK_LEGACY_HISTORY_TRANSITION_REQUIRED')
            if shared is not None:
                profile._consensus_tip(shared)
                if (shared['packet']['genesis']!=contract['anchor']['genesis']
                        or shared['packet']['genesis_hash']!=contract['anchor']['genesis_hash']):
                    raise ValueError('GG_SDK_LEGACY_HISTORY_TRANSITION_REQUIRED')
            if profile.session() is not None and profile.session()!=bundle:raise ValueError('GG_SDK_NETWORK_ALREADY_BOUND')
            profile.bind_session(bundle)
            self.owner=profile;self._bundle=deepcopy(bundle);self._contract=contract
            self._descriptor={key:deepcopy(descriptor[key]) for key in ('public_keys','trusted_coordinator','pair_nonce','host','port')}
            self.public_key=descriptor['public_keys'][0];self.node_role=descriptor.get('node_role','producer')

    def stopped(self):
        from backend.gg_native_process_policy import owner_ended
        shared=self.owner._meta.get('consensus')
        return self.owner._closed or self.owner._failed or self.owner._db is None or owner_ended(self.owner) or shared is not None and bool(shared['fault'])

    def check(self):
        from backend.gg_native_process_policy import owner_ended
        if self.owner._closed or self.owner._failed or self.owner._db is None or owner_ended(self.owner):raise ValueError('GG_SDK_OWNER_CLOSED')
        if self.owner._meta['session']!=self._bundle:
            self.owner._failed=True;raise ValueError('GG_SDK_SESSION_CHANGED')
        descriptor=self.owner._meta['descriptor']
        if any(descriptor[key]!=value for key,value in self._descriptor.items()) or descriptor.get('node_role','producer')!=self.node_role:
            self.owner._failed=True;raise ValueError('GG_SDK_SESSION_CHANGED')
        return self

    def anchor(self):self.check();return deepcopy(self._contract['anchor'])
    def bundle(self):self.check();return deepcopy(self._bundle)


class OwnedSegmentedAuthority(OwnedNativeRPC):
    def __init__(self,profile,session,*,tools=None):
        if not isinstance(profile,ValidatorProfile) or not isinstance(session,OwnedSegmentedSession):raise ValueError('GG_SDK_OWNED_AUTHORITY_REQUIRED')
        session.check()
        if session.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        self.profile=profile;self.session=session;self._lock=threading.RLock();self._closed=False
        self._node={'process':None,'_ready':None};self._lease=None;self._connection=None;self.rpc_port=None
        self._monitor_cancel=None;self._epoch_stopping=True;self._fault='';self._tip=None;self._view=None;self._public_packet=None;self._conflict=None
        self._cut_base=None;self._last_cut_submission=None
        self.anchor=profile.anchor()
        if self.anchor is None or self.anchor!=session.anchor() or self.anchor['genesis'].get('dag_segmented') is None:raise ValueError('GG_SDK_SESSION_ANCHOR_REQUIRED')
        invite=profile.public_invite();self.member=invite['body']
        if self.member['owner_peer_key']!=session.public_key:raise ValueError('GG_SDK_VALIDATOR_OWNER')
        members=self.anchor['genesis']['membership']['validators'];matches=[i for i,member in enumerate(members) if member==invite]
        if len(matches)!=1:raise ValueError('GG_SDK_NOT_A_MEMBER')
        self.index=matches[0];self.tools=Path(native.TOOLS if tools is None else tools)
        self.binary=native._installed_binary(self.tools);self._stamp=native._validate_binary_at(self.tools,self.binary)
        self.node_id=hashlib.sha256(bytes.fromhex(self.member['node_key'])).digest()[:20].hex()
        old=profile.public_certificate()
        if old is not None:
            result=native._verify_public(old,self.binary,self._stamp)
            self._tip=certificate_tip(old,self.anchor);self._public_packet=deepcopy(old)
            self._view=(deepcopy(old['state']),deepcopy(result),time.time(),self._tip,'PERSISTED_CERTIFICATE')
        self._fault=profile.snapshot()['last_error']
        shared=session.owner.consensus_observation()
        evidence=profile.public_conflict() or (shared.get('evidence') if shared is not None else None)
        if evidence is not None:self.observe_conflict(evidence)
        elif shared is not None and shared['fault']:self._fault=shared['fault']
        _OWNED.add(self)

    def _owner_stopped(self):return self.session.stopped()

    def _process_owner(self):return self.session.owner

    def _after_native_start(self):self.profile.publish_native_admissions()

    def _rpc(self,method,params=None,*,timeout=3):
        self.session.check()
        if self.session.stopped():raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        return super()._rpc(method,params,timeout=timeout)

    def start(self):
        with self._lock:
            if self._closed or self._fault:raise ValueError(self._fault or 'GG_SDK_AUTHORITY_CLOSED')
            self.session.check()
            self._check_start()
            if self.session.stopped():raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            if self.profile.anchor()!=self.anchor or self.session.anchor()!=self.anchor:raise ValueError('GG_SDK_SESSION_CHANGED')
            if self._alive():return self.snapshot()
            self.stop();return self._launch_native()

    def certified_state(self):
        """Actual owned RPC + SDK signatures; persist the floor before exposure."""
        with self._lock:
            if self._closed or self._fault:raise ValueError(self._fault or 'GG_SDK_AUTHORITY_CLOSED')
            self.session.check();height=int(self._status()['sync_info']['latest_block_height'])
            if height<1 or self._tip is not None and height<self._tip[0]:raise ValueError('GG_VALIDATOR_NO_FRESH_CERTIFICATE')
            header=self._rpc('commit',{'height':str(height)})['signed_header']
            state=self._query('/gg/genesis' if height==1 else '/gg/state',height-1 if height>1 else None)
            packet={'schema':'gg.consensus.proof.v1',**self.anchor,'state':state,'signed_header':header}
            result=native._verify_public(packet,self.binary,self._stamp);tip=certificate_tip(packet,self.anchor)
            if result.get('dag_segmented_commitment')!=state.get('dag_segmented') or result.get('dag_history_replay_verified') is not False:
                raise ValueError('GG_SDK_SEGMENTED_STATE_REQUIRED')
            if self._tip is not None and tip[0]==self._tip[0] and tip!=self._tip:
                self._record_conflict(make_conflict_evidence(self._public_packet,packet,self.anchor));raise ValueError(self._fault)
            try:self.profile.remember_certificate(packet)
            except (ValueError,OSError):
                self._fault='GG_VALIDATOR_CERTIFICATE_SAVE_FAILED';self.stop();raise
            self._tip=tip;self._public_packet=deepcopy(packet)
            self._view=(deepcopy(state),deepcopy(result),time.time(),tip,'OWNED_SDK_QUERY')
            return deepcopy(packet)

    def cached_certificate(self):return None if self._fault or self._owner_stopped() else deepcopy(self._public_packet)

    def cached_conflict(self):
        shared=self.session.owner.consensus_observation()
        return deepcopy(self._conflict or (shared.get('evidence') if shared is not None else None))

    def export_cached_proof(self,packet,kind,selector):
        """Exact captured source2 context for the bounded LAN proof worker."""
        if kind=='base' and selector=='':return self.export_proof(packet=packet)
        if kind=='account':return self.export_proof(account=selector,packet=packet)
        if kind=='block':return self.export_proof(block=selector,packet=packet)
        if kind=='order':return self.export_proof(order_start=selector,packet=packet)
        if kind=='payload':return self.export_payload_chunk(packet,selector)
        if kind in ('closed','closed-payload'):return self.export_closed(packet,kind,selector)
        raise ValueError('GG_SDK_PROOF_KIND')

    def export_closed(self,packet,kind,selector):
        from backend.gg_segmented_payloads import parse_closed_selector,decode_chunk
        core={name:packet[name] for name in ('schema','genesis','genesis_hash','state','signed_header')}
        certificate_tip(core,self.anchor);epoch=self._check_proof_epoch()
        if kind=='closed':
            closed,start=parse_closed_selector(selector)
            if int(closed)>=int(core['state']['dag_segmented']['epoch']):raise ValueError('GG_PAYLOAD_CLOSED_SELECTOR')
            proof=self._public_query(epoch,'/gg/dag/closed-page',core['state']['height'],native._pack({'epoch':closed,'start':start}))
            result={**core,'dag_segmented_closed_page':proof}
            segmented.verify_closed_membership(result,self.anchor,binary=self.binary,stamp=self._stamp)
            self._check_proof_epoch(epoch);return result
        if kind!='closed-payload':raise ValueError('GG_SDK_PROOF_KIND')
        closed,identifier,index,offset=parse_closed_selector(selector,payload=True)
        if int(closed)>=int(core['state']['dag_segmented']['epoch']):raise ValueError('GG_PAYLOAD_CLOSED_SELECTOR')
        value=self._public_query(epoch,'/gg/dag/closed-payload-chunk',core['state']['height'],native._pack({'epoch':closed,'hash':identifier,'index':index,'offset':offset}))
        decode_chunk(value,core,identifier,index,offset,epoch=closed);self._check_proof_epoch(epoch);return value

    def export_payload_chunk(self,packet,selector):
        """Selected bounded original bytes; no execution or selection receipt."""
        from backend.gg_segmented_payloads import parse_selector,decode_chunk
        identifier,index,offset=parse_selector(selector)
        core={name:packet[name] for name in ('schema','genesis','genesis_hash','state','signed_header')}
        certificate_tip(core,self.anchor)
        if index>core['state']['dag_segmented']['active']['blocks']:raise ValueError('GG_PAYLOAD_SELECTOR')
        epoch=self._check_proof_epoch()
        value=self._public_query(epoch,'/gg/dag/payload-chunk',core['state']['height'],native._pack({'hash':identifier,'index':index,'offset':offset}))
        decode_chunk(value,core,identifier,index,offset)
        self._check_proof_epoch(epoch)
        return value

    def _check_proof_epoch(self,epoch=None):
        self.session.check()
        return super()._check_proof_epoch(epoch)

    def export_proof(self,account=None,block=None,*,order_start=None,packet=None):
        """Captured exact SDK context on dedicated reads, outside the work lock."""
        epoch=self._check_proof_epoch();source=self.anchor['genesis']['dag_segmented']
        selected=deepcopy(self._public_packet if packet is None else packet)
        if not isinstance(selected,dict) or len(native._pack(selected))>256*1024:raise ValueError('GG_SDK_CERTIFICATE_REQUIRED')
        selected={key:selected[key] for key in ('schema','genesis','genesis_hash','state','signed_header')}
        if selected['genesis']!=self.anchor['genesis'] or selected['genesis_hash']!=self.anchor['genesis_hash']:raise ValueError('GG_SDK_PROOF_PIN')
        checked=native._verify_public(selected,self.binary,self._stamp)
        if checked.get('dag_segmented_commitment')!=selected['state'].get('dag_segmented'):raise ValueError('GG_SDK_SEGMENTED_STATE_REQUIRED')
        if account is not None and (type(account) is not str or account not in source['accounts']):raise ValueError('GG_SDK_ACCOUNT')
        if block is not None and (type(block) is not str or len(block)!=64 or any(c not in '0123456789abcdef' for c in block)):raise ValueError('GG_SDK_BLOCK')
        if order_start is not None and (type(order_start) is not int or not 0<=order_start<=4095 or order_start%32):raise ValueError('GG_SDK_ORDER_CURSOR')
        height=selected['state']['height']
        # CometBFT's ABCI height=0 selector means latest, not genesis. Never
        # substitute that mutable state into a proof pinned to the initial
        # certificate. The owner poller will soon publish a positive height.
        if height==0:raise ValueError('GG_SDK_PROOF_INITIAL_WAIT')
        selected['dag_segmented_base_proof']=self._public_query(epoch,'/gg/dag/base-proof',height,b'')
        if account is not None:selected['dag_segmented_account_proof']=self._public_query(epoch,'/gg/dag/account-proof',height,bytes.fromhex(account))
        if block is not None:selected['dag_segmented_block_proof']=self._public_query(epoch,'/gg/dag/block-proof',height,bytes.fromhex(block))
        if order_start is not None:selected['dag_segmented_order_page']=self._public_query(epoch,'/gg/dag/order-page',height,native._pack({'start':order_start}))
        segmented.verify_epoch_base(selected,self.anchor,binary=self.binary,stamp=self._stamp)
        if any(key in selected for key in ('dag_segmented_account_proof','dag_segmented_block_proof','dag_segmented_order_page')):
            segmented.verify_membership(selected,self.anchor,binary=self.binary,stamp=self._stamp)
        self._check_proof_epoch(epoch)
        return selected

    def _record_conflict(self,evidence):
        self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
        errors=[];saved=False
        try:
            try:self.session.owner.save_consensus_conflict(evidence);saved=True
            except (ValueError,OSError):errors.append('owner_store')
            try:self.profile.remember_conflict(evidence);saved=True
            except (ValueError,OSError):errors.append('validator_store')
            if saved:self._conflict=deepcopy(evidence)
        finally:self.stop()
        if errors:self._fault='GG_VALIDATOR_CERTIFICATE_SAVE_FAILED';raise ValueError(self._fault)

    def observe_conflict(self,evidence):
        validate_conflict_evidence(evidence,self.anchor);evidence=deepcopy(evidence)
        for packet in evidence['certificates']:native._verify_public(packet,self.binary,self._stamp)
        with self._lock:self._record_conflict(evidence)

    def submit(self,batch):
        """Mempool admission remains distinct from an SDK-selected certificate."""
        with self._lock:
            if self._closed or self._fault:raise ValueError(self._fault or 'GG_SDK_AUTHORITY_CLOSED')
            self.session.check()
            if not isinstance(batch,bytes) or not 0<len(batch)<=execution_rules.MAX_CHECKPOINT_ENCODED_BYTES:raise ValueError('GG_SDK_BATCH_LIMIT')
            identifier=hashlib.sha256(batch).hexdigest()
            try:result=self._rpc('broadcast_tx_sync',batch,timeout=20)
            except (OSError,http.client.HTTPException):return {'state':'BROADCAST_UNKNOWN','hash':identifier,'SDK_selected':False}
            except ValueError as error:
                if str(error) in ('GG_CONSENSUS_BINARY_CHANGED','GG_VALIDATOR_LISTENER_NOT_OWNED','GG_SDK_OWNER_CLOSED','GG_SDK_SESSION_CHANGED','GG_CONSENSUS_CONFLICTING_CERTIFICATE'):raise
                return {'state':'BROADCAST_UNKNOWN','hash':identifier,'SDK_selected':False}
            if result.get('hash','').lower()!=identifier:raise ValueError('GG_VALIDATOR_BROADCAST_IDENTITY')
            return {'state':'MEMPOOL_ACCEPTED' if int(result.get('code',0))==0 else 'REJECTED','hash':identifier,'SDK_selected':False}

    def submit_proposals(self,raws):
        """Build against actual certified active state; originals stay owned."""
        if (not isinstance(raws,(list,tuple)) or not 1<=len(raws)<=execution_rules.MAX_CHECKPOINT_BLOCKS
                or any(not isinstance(raw,bytes) or not raw for raw in raws)
                or sum(len(raw) for raw in raws)>execution_rules.MAX_CHECKPOINT_RAW_BYTES):raise ValueError('GG_SDK_BATCH_LIMIT')
        with self._lock:
            packet=self.certified_state();active=packet['state']['dag_segmented']['active']
            batch=native._pack({'schema':'gg.dag.checkpoint.batch.v1','genesis_hash':self.anchor['genesis_hash'],
                'previous':active['manifest_hash'],'sequence':active['checkpoint']+1,
                'blocks':[base64.b64encode(raw).decode('ascii') for raw in raws]})
            return self.submit(batch)

    def request_cut(self):
        """Only a proposal/admission result; selection needs a later proof."""
        with self._lock:return self.submit(native._pack(self._query('/gg/dag/cut-proposal')))

    def maintain_segmented(self,*,cut_raw_bytes=256*1024*1024,cut_blocks=2048):
        """Bounded local cut policy; optional producers are never a barrier."""
        if (type(cut_raw_bytes) is not int or not 1<=cut_raw_bytes<=execution_rules.MAX_HISTORY_RAW_BYTES
                or type(cut_blocks) is not int or not 1<=cut_blocks<=execution_rules.MAX_HISTORY_BLOCKS):raise ValueError('GG_SDK_CUT_POLICY')
        packet=self.certified_state();state=packet['state']['dag_segmented'];epoch=state['epoch']
        if state['active']['blocks']==0:
            self._cut_base=(epoch,int(state['raw_bytes']));return self.snapshot()
        if self._cut_base is None or self._cut_base[0]!=epoch:
            proof=self.export_proof(packet=packet)
            base=segmented.verify_epoch_base(proof,self.anchor,binary=self.binary,stamp=self._stamp)['base']['commitment']
            self._cut_base=(epoch,int(base['raw_bytes']))
        active_bytes=int(state['raw_bytes'])-self._cut_base[1]
        if active_bytes<0:raise ValueError('GG_SDK_CUT_CONTEXT')
        if active_bytes>=cut_raw_bytes or state['active']['blocks']>=cut_blocks:
            key=(epoch,state['active']['manifest_hash']);now=time.monotonic();last=self._last_cut_submission
            if last is None or key!=last[:2] or now-last[2]>=5:
                self.request_cut();self._last_cut_submission=(*key,now)
        return self.snapshot()

    def snapshot(self):
        view=self._view;state,proof,observed,tip,origin=view if view is not None else (None,None,None,None,None)
        alive=self._alive();fault=self._fault;owner_stopped=self._owner_stopped();exit_code=self._native_exit_code()
        error=fault or ('GG_VALIDATOR_NATIVE_PROCESS_EXITED' if exit_code is not None else '')
        return {'schema':'gg.sdk.segmented-authority-observation.v1','role':'validator','scope':'PRIVATE_LAN_EXPERIMENT',
            'state':'CLOSED' if self._closed or owner_stopped else 'FAULT' if error else 'RUNNING' if alive else 'STOPPED',
            'owned_native_process':alive,'owner_stopped':owner_stopped,'validator_index':self.index,
            'certificate_verified':proof is not None and not fault,'certificate_height':tip[0] if tip else None,
            'canonical_finality':proof is not None and not fault,'certificate_id':tip[1] if tip else None,
            'verified_at':observed,'observation_origin':origin,'dag_segmented_commitment':deepcopy(state['dag_segmented']) if state else None,
            'producer_owned_nonfinancial':True,'client_full_history_replayed':False,'last_error':error,'native_exit_code':exit_code,
            'certificate_is_network_liveness':False}

    def close(self):
        with self._lock:
            self.stop();self.profile.close();self._closed=True;_OWNED.discard(self)


def shutdown():
    for authority in list(_OWNED):
        try:authority.close()
        except (ValueError,OSError,RuntimeError):pass


atexit.register(shutdown)
