"""One explicitly owned persistent validator child, bound to installed LAN v4.

RPC stays on owned loopback. P2P endpoints and public keys come exclusively
from the immutable signed membership. Nothing starts or generates keys at import.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import http.client
import json
from pathlib import Path
from contextlib import contextmanager
from copy import deepcopy
from types import MappingProxyType
import threading
import time
from urllib.parse import urlencode


from backend import gg_consensus as native
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_consensus_process import OwnedNativeRPC
from backend.gg_native_resources import resolve

_OWNED=set()


class OwnedValidator(OwnedNativeRPC):
    def __init__(self,profile,peer,*,tools=None,resources=None):
        if not isinstance(profile,ValidatorProfile):raise ValueError('GG_VALIDATOR_PROFILE_REQUIRED')
        if peer.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        self._resource_profile=resolve(resources)
        self.profile=profile;self.peer=peer;self._lock=threading.RLock();self._closed=False
        self._node={'process':None,'_ready':None};self._lease=None;self._connection=None;self._tip=None;self._fault=''
        self._last=None;self._proof=None;self.rpc_port=None
        self._view=None
        self._public_packet=None
        self._conflict=None
        self._canonical_view=None;self._canonical_members=None;self._broadcast_attempted=None
        self._payload_view=None;self._epoch_stopping=False
        self._monitor_cancel=None
        self.anchor=profile.anchor()
        if self.anchor is None or self.anchor!=anchor_from_owned_peer(peer):raise ValueError('GG_VALIDATOR_LAN_ANCHOR_REQUIRED')
        from backend.gg_dag_order_history import OrderHistory
        self._order_history=OrderHistory(self.anchor['genesis']['dag']);self._order_loaded=False
        invite=profile.public_invite()
        if invite['body']['owner_peer_key']!=peer.public_key:raise ValueError('GG_VALIDATOR_LAN_OWNER')
        members=self.anchor['genesis']['membership']['validators']
        self.index=next((index for index,value in enumerate(members) if value==invite),None)
        if self.index is None:raise ValueError('GG_VALIDATOR_NOT_A_MEMBER')
        self.member=invite['body'];self.tools=Path(native.TOOLS if tools is None else tools)
        self.binary=native._installed_binary(self.tools);self._stamp=native._validate_binary_at(self.tools,self.binary)
        self.node_id=hashlib.sha256(bytes.fromhex(self.member['node_key'])).digest()[:20].hex()
        historical=profile.public_certificate()
        if historical is not None:
            result=native._verify_public(historical,self.binary,self._stamp)
            self._tip=profile._certificate_tip(historical);self._last=historical['state'];self._proof=result
            self._view=(self._last,self._proof,time.time(),self._tip)
            self._public_packet=historical
        self._fault=profile.snapshot()['last_error']
        evidence=profile.public_conflict()
        record=peer._profile.consensus_observation() if peer._profile is not None else None
        if evidence is None and record is not None:evidence=record.get('evidence')
        if evidence is not None:self.observe_conflict(evidence)
        elif record is not None and record['fault']:self._fault=record['fault']
        _OWNED.add(self)


    def _owner_stopped(self):
        from backend.gg_native_process_policy import owner_ended
        from backend.gg_node_store import NodeProfile
        profile=self.peer._profile
        return (self.peer._cancel.is_set() or owner_ended(profile or self.peer)
            or isinstance(profile,NodeProfile) and (profile._closed or profile._failed))

    def _process_owner(self):return self.peer._profile or self.peer

    def _after_native_start(self):self.profile.publish_native_admissions()

    def start(self):
        with self._lock:
            if self._closed or self._fault:raise ValueError(self._fault or 'GG_VALIDATOR_CLOSED')
            self._check_start()
            if self._alive():return self.snapshot()
            self.stop()
            if self.anchor!=anchor_from_owned_peer(self.peer):raise ValueError('GG_VALIDATOR_LAN_ANCHOR_CHANGED')
            return self._launch_native()


    def certified_state(self):
        with self._lock:
            if self._fault:raise ValueError(self._fault)
            height=int(self._status()['sync_info']['latest_block_height'])
            if height<1 or self._tip is not None and height<self._tip[0]:raise ValueError('GG_VALIDATOR_NO_FRESH_CERTIFICATE')
            header=self._rpc('commit',{'height':str(height)})['signed_header']
            state=self._query('/gg/genesis' if height==1 else '/gg/state',height-1 if height>1 else None)
            packet={'schema':'gg.consensus.proof.v1',**self.anchor,'state':state,'signed_header':header}
            result=native._verify_public(packet,self.binary,self._stamp)
            tip=(height,native.block_hash(header['commit']['block_id']['hash']))
            if self._tip is not None and height==self._tip[0] and self._tip!=tip:
                from backend.gg_dag_checkpoint import make_conflict_evidence
                self._record_verified_conflict(make_conflict_evidence(self._public_packet,packet,self.anchor))
                raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            try:self.profile.remember_certificate(packet)
            except (ValueError,OSError):
                self._fault='GG_VALIDATOR_CERTIFICATE_SAVE_FAILED';self.stop();raise
            self._tip=tip;self._last=state;self._proof=result
            self._view=(state,result,time.time(),tip)
            self._public_packet=deepcopy(packet)
            return json.loads(native._pack(packet))

    def cached_certificate(self):
        return None if self._fault or self._owner_stopped() else deepcopy(self._public_packet)

    def cached_conflict(self):return deepcopy(self._conflict)

    def _record_verified_conflict(self,evidence):
        with self._lock:
            if self._closed:raise ValueError('GG_VALIDATOR_CLOSED')
            self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
            errors=[];saved=False
            try:
                if self.peer._profile is not None:
                    try:self.peer._profile.save_consensus_conflict(evidence);saved=True
                    except (ValueError,OSError):errors.append('owner_store')
                try:self.profile.remember_conflict(evidence);saved=True
                except (ValueError,OSError):errors.append('validator_store')
                if saved:self._conflict=deepcopy(self.profile.public_conflict() or evidence)
            finally:self.stop()
            if errors:
                self._fault='GG_VALIDATOR_CERTIFICATE_SAVE_FAILED'
                raise ValueError(self._fault)

    def observe_conflict(self,evidence):
        """Untrusted accusations cannot halt a validator without BOTH SDK proofs."""
        from backend.gg_dag_checkpoint import validate_conflict_evidence
        validate_conflict_evidence(evidence,self.anchor)
        evidence=deepcopy(evidence)
        for packet in evidence['certificates']:native._verify_public(packet,self.binary,self._stamp)
        self._record_verified_conflict(evidence)


    def export_cached_proof(self,packet,kind,selector):
        """Only an already SDK-verified cached base packet reaches this API."""
        epoch=self._check_proof_epoch()
        from backend.gg_dag_checkpoint import certificate_tip
        certificate_tip(packet,self.anchor)
        height=packet['state']['height'];result=deepcopy(packet)
        if kind=='order':
            if type(selector) is not int or selector<0 or selector>4095 or selector%32:raise ValueError('GG_VALIDATOR_ORDER_CURSOR')
            if height==0:
                proof={'schema':'gg.dag.order-page.v1','commitment':deepcopy(packet['state']['dag']),
                    'genesis_hash':packet['genesis_hash'],'height':0,'state_root':packet['state']['state_root'],'start':0,'items':[],'complete':True}
                if selector!=0:raise ValueError('GG_VALIDATOR_ORDER_CURSOR')
            else:proof=self._public_query(epoch,'/gg/dag/order-page',height,native._pack({'start':selector}))
            field='dag_order_page';flag='dag_order_page_verified'
        elif kind in ('account','block'):
            if height==0:raise ValueError('GG_VALIDATOR_PROOF_INITIAL_WAIT')
            if not isinstance(selector,str) or len(selector)!=64 or any(c not in '0123456789abcdef' for c in selector):raise ValueError('GG_VALIDATOR_PROOF_IDENTIFIER')
            field='dag_'+kind+'_proof';flag=field+'_verified'
            proof=self._public_query(epoch,'/gg/dag/'+kind+'-proof',height,bytes.fromhex(selector))
        else:raise ValueError('GG_VALIDATOR_PROOF_KIND')
        result[field]=proof;verified=native._verify_public(result,self.binary,self._stamp)
        if verified.get(flag) is not True:raise ValueError('GG_VALIDATOR_PROOF_REQUIRED')
        self._check_proof_epoch(epoch)
        return result

    def certified_order(self):
        """Verify every bounded page under one certificate before exposing IDs."""
        from backend.gg_dag_checkpoint import check_complete_order
        with self._lock:
            packet=self.certified_state();state=packet['state'];commitment=state.get('dag')
            if commitment is None:raise ValueError('GG_VALIDATOR_DAG_NOT_CONFIGURED')
            if not self._order_loaded:
                saved=self.peer._profile.verified_order() if self.peer._profile is not None else None
                if saved is not None:
                    from backend.gg_dag_checkpoint import certificate_tip
                    from backend.gg_dag_order_history import OrderHistory
                    certificate_tip(saved['packet'],self.anchor)
                    if native._verify_public(saved['packet'],self.binary,self._stamp).get('verified') is not True:
                        raise ValueError('GG_VALIDATOR_ORDER_CACHE_CERTIFICATE')
                    self._order_history=OrderHistory.restore(self.anchor['genesis']['dag'],saved['packet']['state'],saved['order'])
                self._order_loaded=True
            cached=self._canonical_view
            if cached is not None and cached['certificate']['state']['dag']==commitment:
                view={'certificate':packet,'order':deepcopy(cached['order'])}
            else:
                deadline=time.monotonic()+30
                def check():
                    if self.peer._cancel.is_set() or time.monotonic()>=deadline:raise ValueError('GG_VALIDATOR_ORDER_CANCELLED')
                def fetch(cursor):
                    if state['height']==0:
                        page={'schema':'gg.dag.order-page.v1','commitment':deepcopy(commitment),'genesis_hash':packet['genesis_hash'],
                              'height':0,'state_root':state['state_root'],'start':0,'complete':True,'items':[]}
                    else:page=self._query('/gg/dag/order-page',state['height'],native._pack({'start':cursor}))
                    verified=native._verify_public({**packet,'dag_order_page':page},self.binary,self._stamp)
                    if verified.get('dag_order_page_verified') is not True or page['start']!=cursor:
                        raise ValueError('GG_VALIDATOR_ORDER_PROOF_REQUIRED')
                    return page
                candidate=self._order_history.fetch(state,fetch,check);order=candidate.order()
                if self.peer._profile is not None:self.peer._profile.save_verified_order(packet,order)
                self._order_history=candidate
                view={'certificate':packet,'order':order}
            # SDK-proven IDs are fetch authority, NOT local execution or UI
            # membership. A separate worker can materialize missing payload.
            self._payload_view=(deepcopy(packet),deepcopy(view['order']),MappingProxyType({leaf['hash']:leaf['index'] for leaf in view['order']}))
            recovery=self.peer.recover_certified_payloads(state,view['order'])
            if recovery['remaining']:raise ValueError('GG_DAG_CANONICAL_PAYLOAD_PENDING')
            self.peer._engine.apply_certified_order(state,view['order'],self.anchor['genesis']['dag'])
            self._canonical_view=view
            self._canonical_members=(int(packet['signed_header']['header']['height']),MappingProxyType({leaf['hash']:leaf['index'] for leaf in view['order']}))
            return deepcopy(view)

    def payload_reference(self,identifier):
        view=self._payload_view
        if view is None or self._fault or self._closed or self.peer._cancel.is_set():return None
        index=view[2].get(identifier)
        return None if index is None else {'certificate':deepcopy(view[0]),'order':deepcopy(view[1]),'index':index}

    @contextmanager
    def payload_reader(self,packet):
        epoch=self._check_proof_epoch();connection=http.client.HTTPConnection('127.0.0.1',epoch[1],timeout=3)
        try:
            yield epoch,lambda identifier,index,offset:self.export_payload_chunk(packet,identifier,index,offset,epoch=epoch,connection=connection)
        finally:connection.close()

    def export_payload_chunk(self,packet,identifier,index,offset,*,epoch=None,connection=None):
        """Bounded owned loopback read, pinned to an SDK-verified certificate.

        Chunks remain untrusted until their complete wire and every protocol
        check pass. This endpoint never supplies an execution/finality ACK.
        """
        from backend.gg_dag_checkpoint import certificate_tip
        certificate_tip(packet,self.anchor)
        if (not isinstance(identifier,str) or len(identifier)!=64 or any(c not in '0123456789abcdef' for c in identifier)
                or type(index) is not int or not 1<=index<=packet['state']['dag']['blocks']
                or type(offset) is not int or not 0<=offset<32*1024*1024 or offset%(32*1024)):
            raise ValueError('GG_VALIDATOR_PAYLOAD_SELECTOR')
        epoch=self._check_proof_epoch(epoch)
        args=(epoch,'/gg/dag/payload-chunk',packet['state']['height'],native._pack({'hash':identifier,'index':index,'offset':offset}))
        value=self._public_query(*args,connection=connection) if connection is not None else self._public_query(*args)
        expected={'data','genesis_hash','hash','height','index','offset','schema','state_root','total','wire_hash'}
        if (not isinstance(value,dict) or set(value)!=expected or value['schema']!='gg.dag.payload-chunk.v1'
                or value['genesis_hash']!=packet['genesis_hash'] or value['state_root']!=packet['state']['state_root']
                or type(value['height']) is not int or value['height']!=packet['state']['height']
                or value['hash']!=identifier or type(value['index']) is not int or value['index']!=index
                or type(value['offset']) is not int or value['offset']!=offset or type(value['total']) is not int
                or not 0<value['total']<=32*1024*1024 or offset>=value['total']
                or not isinstance(value['wire_hash'],str) or len(value['wire_hash'])!=64 or any(c not in '0123456789abcdef' for c in value['wire_hash'])
                or not isinstance(value['data'],str) or len(value['data'])>43692):raise ValueError('GG_VALIDATOR_PAYLOAD_CHUNK')
        try:data=base64.b64decode(value['data'],validate=True)
        except ValueError:raise ValueError('GG_VALIDATOR_PAYLOAD_CHUNK') from None
        if base64.b64encode(data).decode('ascii')!=value['data'] or len(data)!=min(32*1024,value['total']-offset):raise ValueError('GG_VALIDATOR_PAYLOAD_CHUNK')
        self._check_proof_epoch(epoch)
        return {'total':value['total'],'wire_hash':value['wire_hash'],'offset':offset,'data':data}

    def canonical_membership(self):
        return None if self._fault else self._canonical_members

    def maintain_checkpoint(self):
        """One bounded observation/submission; identical durable requests only.

        A crash can repeat the SAME request once in its new owned controller;
        the checkpoint predecessor/sequence prevents a second execution. No
        new candidate replaces an unresolved request under the same root.
        """
        from backend.gg_dag_checkpoint import select_checkpoint,restore_checkpoint
        with self._lock:
            view=self.certified_order();state=view['certificate']['state'];dag=state['dag']
            try:
                pending=self.profile.pending_checkpoint()
                if pending is not None and pending['previous']!=dag['manifest_hash']:
                    self.profile.resolve_checkpoint(self._canonical_members[1],self._canonical_members[0]);pending=None;self._broadcast_attempted=None
                if pending is None:
                    selected=select_checkpoint(self.peer,self.anchor,view)
                    if selected is None:return
                    pending=selected['descriptor'];self.profile.prepare_checkpoint(pending);wire=selected['wire']
                elif self._broadcast_attempted==pending['hash']:return
                else:wire=restore_checkpoint(self.peer,pending)
                # Consume the in-process attempt before touching the transport.
                self._broadcast_attempted=pending['hash']
                outcome=self.submit(wire)
                self.profile.checkpoint_outcome(pending['hash'],outcome['state'])
            except ValueError as error:
                if str(error) in ('GG_VALIDATOR_STORE_WRITE_FAILED','GG_DAG_PENDING_PAYLOAD_MISSING','GG_DAG_PENDING_PAYLOAD_CHANGED'):
                    self._fault='GG_VALIDATOR_CHECKPOINT_SAVE_OR_PAYLOAD_FAILED';self.stop()
                raise

    def export_proof(self,account,block=None):
        with self._lock:
            packet=self.certified_state();height=packet['state']['height']
            if height<1:raise ValueError('GG_VALIDATOR_NO_DAG_CHECKPOINT')
            if account not in self.anchor['genesis']['dag']['accounts']:raise ValueError('GG_VALIDATOR_DAG_ACCOUNT')
            packet['dag_account_proof']=self._query('/gg/dag/account-proof',height,bytes.fromhex(account))
            if block is not None:
                if not isinstance(block,str) or len(block)!=64:raise ValueError('GG_VALIDATOR_DAG_BLOCK')
                packet['dag_block_proof']=self._query('/gg/dag/block-proof',height,bytes.fromhex(block))
            result=native._verify_public(packet,self.binary,self._stamp)
            if result.get('dag_account_proof_verified') is not True or block is not None and result.get('dag_block_proof_verified') is not True:
                raise ValueError('GG_VALIDATOR_DAG_PROOF_REQUIRED')
            return packet

    def submit(self,batch):
        with self._lock:
            if self._fault:raise ValueError(self._fault)
            if not isinstance(batch,bytes) or not 0<len(batch)<=48*1024*1024:raise ValueError('GG_VALIDATOR_BATCH_LIMIT')
            identifier=hashlib.sha256(batch).hexdigest()
            try:result=self._rpc('broadcast_tx_sync',batch,timeout=20)
            except (OSError,http.client.HTTPException):
                return {'state':'BROADCAST_UNKNOWN','canonical_finality':False,'hash':identifier}
            except ValueError as error:
                if str(error) in ('GG_CONSENSUS_BINARY_CHANGED','GG_VALIDATOR_LISTENER_NOT_OWNED','GG_VALIDATOR_BATCH_LIMIT'):raise
                return {'state':'BROADCAST_UNKNOWN','canonical_finality':False,'hash':identifier}
            if result.get('hash','').lower()!=identifier:raise ValueError('GG_VALIDATOR_BROADCAST_IDENTITY')
            return {'state':'MEMPOOL_ACCEPTED' if int(result.get('code',0))==0 else 'REJECTED',
                'canonical_finality':False,'hash':result['hash'].lower()}

    def snapshot(self):
        # Publish one immutable verified pair. UI/status never waits on a
        # native RPC, SDK verifier, durable write or the controller's work lock.
        view=self._view;state,proof,observed,tip=view if view is not None else (None,None,None,None)
        alive=self._alive();fault=self._fault;owner_stopped=self._owner_stopped();exit_code=self._native_exit_code()
        error=fault or ('GG_VALIDATOR_NATIVE_PROCESS_EXITED' if exit_code is not None else '')
        return {'role':'validator','profile':self.profile.name,'scope':'PRIVATE_LAN_EXPERIMENT',
            'resources':self.resource_observation(),
            'state':'CLOSED' if self._closed or owner_stopped else 'FAULT' if error else 'RUNNING' if alive else 'STOPPED',
            'validator_index':self.index,'owned_native_process':alive,'owner_stopped':owner_stopped,
            'canonical_finality':proof is not None and not fault,'certificate_is_network_liveness':False,
            'certificate_height':proof['certificate_height'] if proof else None,
            'certificate_id':tip[1] if tip else None,
            'verified_at':observed,'dag_commitment':deepcopy(state.get('dag')) if state else None,'last_error':error,'native_exit_code':exit_code,
            'canonical_order_verified':self._canonical_members is not None and not fault,
            'conflict_evidence_height':self._conflict['height'] if self._conflict is not None else None,
            'canonical_order_blocks':len(self._canonical_members[1]) if self._canonical_members is not None and not fault else None}


    def close(self):
        with self._lock:
            self.stop();self.profile.close();self._closed=True;_OWNED.discard(self)


def shutdown():
    for node in list(_OWNED):
        try:node.close()
        except (OSError,ValueError,RuntimeError):pass


atexit.register(shutdown)
