"""Owned financial source-v2 context and one protected native SDK validator.

The context creates no keys/listener and never installs a legacy DAG engine.
The authority uses the existing leased native startup, durable signer intent,
bounded RPC and exact-child shutdown implementation. No activation at import.
"""
import atexit
from copy import deepcopy
import hashlib
import http.client
from pathlib import Path
import threading
import time

from backend import gg_consensus as native,gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_consensus_process import OwnedNativeRPC
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_financial_session import validate_bundle
from backend.gg_node_store import NodeProfile
from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence,validate_conflict_evidence
from backend.gg_parallel_dag import pack

_OWNED=set()


class OwnedFinancialSession:
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
                    or row.get('node_role','producer')!=descriptor.get('node_role','producer') or descriptor['allow_dag_transactions'] is not True):
                raise ValueError('GG_SDK_SESSION_OWNER')
            if profile._head['entries'] or profile._meta.get('order_index') or profile._meta.get('segmented_producer'):
                raise ValueError('GG_SDK_LEGACY_HISTORY_TRANSITION_REQUIRED')
            shared=profile.consensus_observation()
            if shared is not None:
                profile._consensus_tip(shared)
                if any(shared['packet'][key]!=contract['anchor'][key] for key in ('genesis','genesis_hash')):
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
        descriptor=self.owner._meta['descriptor']
        if (self.owner._meta['session']!=self._bundle or any(descriptor[key]!=value for key,value in self._descriptor.items())
                or descriptor.get('node_role','producer')!=self.node_role):
            self.owner._failed=True;raise ValueError('GG_SDK_SESSION_CHANGED')
        if self.stopped():raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
        return self

    def anchor(self):self.check();return deepcopy(self._contract['anchor'])
    def bundle(self):self.check();return deepcopy(self._bundle)


class OwnedFinancialAuthority(OwnedNativeRPC):
    def __init__(self,profile,session,*,tools=None):
        if not isinstance(profile,ValidatorProfile) or not isinstance(session,OwnedFinancialSession):raise ValueError('GG_FINANCIAL_OWNED_AUTHORITY_REQUIRED')
        session.check()
        if session.node_role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        self.profile=profile;self.session=session;self._lock=threading.RLock();self._closed=False
        self._node={'process':None,'_ready':None};self._lease=None;self._connection=None;self.rpc_port=None
        self._monitor_cancel=None;self._epoch_stopping=True;self._fault='';self._tip=None;self._view=None;self._public_packet=None;self._conflict=None;self._verified_at=None
        self.anchor=profile.anchor()
        if (self.anchor is None or self.anchor!=session.anchor() or self.anchor['genesis']['financial_dag']['schema'] not in financial.SESSION_SOURCE_SCHEMAS):
            raise ValueError('GG_FINANCIAL_SESSION_ANCHOR_REQUIRED')
        invite=profile.public_invite();self.member=invite['body']
        if self.member['owner_peer_key']!=session.public_key:raise ValueError('GG_SDK_VALIDATOR_OWNER')
        matches=[index for index,member in enumerate(self.anchor['genesis']['membership']['validators']) if member==invite]
        if len(matches)!=1:raise ValueError('GG_SDK_NOT_A_MEMBER')
        self.index=matches[0];self.tools=Path(native.TOOLS if tools is None else tools)
        self.binary=native._installed_binary(self.tools);self._stamp=native._validate_binary_at(self.tools,self.binary)
        self.node_id=hashlib.sha256(bytes.fromhex(self.member['node_key'])).digest()[:20].hex()
        self._fault=profile.snapshot()['last_error']
        old=profile.public_certificate()
        if old is not None:
            result=native._verify_public(old,self.binary,self._stamp);self._check_financial_result(old,result)
            self._tip=certificate_tip(old,self.anchor);self._public_packet=deepcopy(old)
            self._view=(deepcopy(old['state']),deepcopy(result),None,None,'PERSISTED_CERTIFICATE')
        shared=session.owner.consensus_observation()
        evidence=profile.public_conflict() or (shared.get('evidence') if shared is not None else None)
        if evidence is not None:self.observe_conflict(evidence)
        elif shared is not None and shared['fault']:self._fault=shared['fault']
        _OWNED.add(self)

    def _check_financial_result(self,packet,result):
        value=packet['state'].get('financial_dag')
        if (not isinstance(value,dict) or value.get('schema') not in ('gg.financial-dag.commitment.v2','gg.financial-dag.commitment.v3','gg.financial-dag.commitment.v4')
                or result.get('financial_dag_commitment')!=value or result.get('financial_history_replay_verified') is not False):
            raise ValueError('GG_FINANCIAL_CERTIFIED_STATE_REQUIRED')

    def _owner_stopped(self):return self.session.stopped()
    def _process_owner(self):return self.session.owner
    def _after_native_start(self):self.profile.publish_native_admissions()

    def _rpc(self,method,params=None,*,timeout=3):
        self.session.check();return super()._rpc(method,params,timeout=timeout)

    def start(self):
        with self._lock:
            if self._closed or self._fault:raise ValueError(self._fault or 'GG_FINANCIAL_AUTHORITY_CLOSED')
            self._check_start()
            self.session.check()
            if self.profile.anchor()!=self.anchor or self.session.anchor()!=self.anchor:raise ValueError('GG_SDK_SESSION_CHANGED')
            if self._alive():return self.snapshot()
            self.stop();return self._launch_native()

    def certified_state(self):
        with self._lock:
            if self._closed or self._fault:raise ValueError(self._fault or 'GG_FINANCIAL_AUTHORITY_CLOSED')
            self.session.check();epoch=self._check_proof_epoch()
            height=int(self._status()['sync_info']['latest_block_height'])
            shared=self.session.owner.consensus_observation();floor=self.session.owner._consensus_tip(shared) if shared is not None else None
            if height<1 or self._tip is not None and height<self._tip[0] or floor is not None and height<floor[0]:raise ValueError('GG_VALIDATOR_NO_FRESH_CERTIFICATE')
            header=self._rpc('commit',{'height':str(height)})['signed_header']
            state=self._query('/gg/genesis' if height==1 else '/gg/state',height-1 if height>1 else None)
            packet={'schema':'gg.consensus.proof.v1',**self.anchor,'state':state,'signed_header':header}
            result=native._verify_public(packet,self.binary,self._stamp);self._check_financial_result(packet,result);tip=certificate_tip(packet,self.anchor)
            if self._tip is not None and tip[0]==self._tip[0] and tip!=self._tip:
                self._record_conflict(make_conflict_evidence(self._public_packet,packet,self.anchor));raise ValueError(self._fault)
            self._check_proof_epoch(epoch)
            try:self.profile.remember_certificate(packet)
            except (ValueError,OSError):self._fault='GG_VALIDATOR_CERTIFICATE_SAVE_FAILED';self.stop();raise
            self._tip=tip;self._public_packet=deepcopy(packet)
            self._verified_at=time.time()
            self._view=(deepcopy(state),deepcopy(result),time.monotonic(),epoch,'OWNED_SDK_QUERY')
            return deepcopy(packet)

    def producer_context(self,index,*,packet=None):
        if type(index) is not int or not 0<=index<6:raise ValueError('GG_FINANCIAL_PRODUCER_SELECTOR')
        core=self.certified_state() if packet is None else deepcopy(packet)
        certificate_tip(core,self.anchor);native._verify_public(core,self.binary,self._stamp);epoch=self._check_proof_epoch()
        value=core['state']['financial_dag'];author=value['authors'][index]
        lineage=self.anchor['genesis']['financial_dag']['schema'] in financial.LINEAGE_SOURCE_SCHEMAS
        if author['sequence']=='0' or not lineage and author['epoch']!=value['epoch']:
            # Genesis and a creator that has not yet extended the current cut
            # need no history witness: every field is already in the certified
            # commitment. ABCI height=0 means "latest", not genesis height.
            parent,rank=value['last_cut'],value['epoch_base_rank']
            if lineage:
                parent=hashlib.sha256(financial.DOMAIN+b'DAG-GENESIS\0'+pack({'anchor':self.anchor['genesis_hash'],'source':financial.source_hash(self.anchor['genesis']['financial_dag'])})).hexdigest();rank='0'
            proof={'schema':'gg.financial-dag.producer-context.v1','epoch':value['epoch'],'genesis_hash':self.anchor['genesis_hash'],
                'height':core['state']['height'],'parent':parent,'parent_path':[],'parent_rank':rank,
                'producer_index':index,'sequence':str(wire.counter(author['sequence'])+1),
                'source_hash':value['source_hash'],'state_root':core['state']['state_root']}
        else:
            proof=self._public_query(epoch,'/gg/financial-dag/producer-context',core['state']['height'],pack({'producer_index':index}))
        packet={**core,'financial_producer':proof}
        financial.verify_producer(packet,self.anchor,binary=self.binary,stamp=self._stamp);self._check_proof_epoch(epoch)
        return packet

    def receipt(self,block,index,*,packet=None):
        if type(block) is not str or not wire.HASH.fullmatch(block) or type(index) is not int or not 0<=index<wire.MAX_PAYMENTS:raise ValueError('GG_FINANCIAL_RECEIPT_SELECTOR')
        core=self.certified_state() if packet is None else deepcopy(packet)
        certificate_tip(core,self.anchor);native._verify_public(core,self.binary,self._stamp);epoch=self._check_proof_epoch()
        proof=self._public_query(epoch,'/gg/financial-dag/receipt',core['state']['height'],pack({'block':block,'index':index}))
        result={**core,'financial_receipt':proof}
        financial.verify_receipt(result,self.anchor,binary=self.binary,stamp=self._stamp);self._check_proof_epoch(epoch)
        return result

    def account(self,address,*,packet=None):
        """Read a caller-selected account at the exact certified state height."""
        financial.account_address(address)
        if self.anchor['genesis']['schema'] not in ('gg.native.genesis.v6','gg.native.genesis.v7'):raise ValueError('GG_FINANCIAL_GENERAL_ACCOUNT_REQUIRED')
        core=self.certified_state() if packet is None else deepcopy(packet)
        certificate_tip(core,self.anchor);native._verify_public(core,self.binary,self._stamp);epoch=self._check_proof_epoch()
        proof=self._public_query(epoch,'/gg/financial-dag/account-proof',core['state']['height'],pack(address))
        result={**core,'financial_account':proof,'expected_financial_account':address}
        financial.verify_account(result,self.anchor,address,binary=self.binary,stamp=self._stamp);self._check_proof_epoch(epoch)
        return result

    def submit_proposals(self,actor,raws):
        """Only roster-owned producer blocks; admission never means execution."""
        with self._lock:
            self.session.check()
            own=[entry for entry in self.session._contract['roster'] if entry['invite']['body']['peer_key']==actor]
            if len(own)!=1 or own[0]['invite']['body'].get('node_role','producer')!='producer':raise ValueError('GG_FINANCIAL_SUBMISSION_OWNER')
            core=self.certified_state();batch,records=wire.batch(core,raws)
            if any(record['producer_index'] not in own[0]['producer_indices'] for record in records):raise ValueError('GG_FINANCIAL_SUBMISSION_OWNER')
            # A prefix can have been partly selected between its producer
            # context and arrival. Never rewrap or re-sign an original here.
            authors=core['state']['financial_dag']['authors']
            pending_ids={record['hash'] for record in records if record['sequence']>wire.counter(authors[record['producer_index']]['sequence'])}
            pending=[raw for raw in raws if hashlib.sha256(wire.DOMAIN+b'DAG-BLOCK\0'+raw).hexdigest() in pending_ids]
            if not pending:return {'state':'CREATOR_SEQUENCE_ADVANCED','SDK_selected':False,'payments_executed_asserted':False}
            if len(pending)!=len(raws):batch,records=wire.batch(core,pending)
            identifier=hashlib.sha256(batch).hexdigest()
            try:result=self._rpc('broadcast_tx_sync',batch,timeout=20)
            except (OSError,http.client.HTTPException):return {'state':'BROADCAST_UNKNOWN','hash':identifier,'SDK_selected':False}
            except ValueError as error:
                if str(error) in ('GG_CONSENSUS_BINARY_CHANGED','GG_VALIDATOR_LISTENER_NOT_OWNED','GG_SDK_OWNER_CLOSED','GG_SDK_SESSION_CHANGED','GG_CONSENSUS_CONFLICTING_CERTIFICATE'):raise
                return {'state':'BROADCAST_UNKNOWN','hash':identifier,'SDK_selected':False}
            if result.get('hash','').lower()!=identifier:raise ValueError('GG_VALIDATOR_BROADCAST_IDENTITY')
            return {'state':'MEMPOOL_ACCEPTED' if int(result.get('code',0))==0 else 'REJECTED','hash':identifier,
                    'blocks':[record['hash'] for record in records],'SDK_selected':False,'payments_executed_asserted':False}

    def _record_conflict(self,evidence):
        self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE';errors=[];saved=False
        try:
            try:self.session.owner.save_consensus_conflict(evidence);saved=True
            except (ValueError,OSError):errors.append('owner')
            try:self.profile.remember_conflict(evidence);saved=True
            except (ValueError,OSError):errors.append('validator')
            if saved:self._conflict=deepcopy(evidence)
        finally:self.stop()
        if errors:self._fault='GG_VALIDATOR_CERTIFICATE_SAVE_FAILED';raise ValueError(self._fault)

    def observe_conflict(self,evidence):
        validate_conflict_evidence(evidence,self.anchor);evidence=deepcopy(evidence)
        for packet in evidence['certificates']:native._verify_public(packet,self.binary,self._stamp)
        with self._lock:self._record_conflict(evidence)

    def cached_certificate(self):return None if self._fault or self._owner_stopped() else deepcopy(self._public_packet)

    def cached_conflict(self):
        shared=self.session.owner.consensus_observation()
        return deepcopy(self._conflict or (shared.get('evidence') if shared is not None else None))

    def export_cached_proof(self,packet,kind,selector):
        if kind=='producer':return self.producer_context(selector,packet=packet)
        if kind=='account':return self.account(selector,packet=packet)
        if kind=='receipt':
            from backend.gg_financial_proof_sync import parse_receipt_selector
            block,index=parse_receipt_selector(selector);return self.receipt(block,index,packet=packet)
        raise ValueError('GG_FINANCIAL_PROOF_KIND')

    def snapshot(self):
        view=self._view;state,proof,observed,epoch,origin=view if view is not None else (None,None,None,None,None)
        alive=self._alive();ended=self._owner_stopped();exit_code=self._native_exit_code()
        error=self._fault or ('GG_VALIDATOR_NATIVE_PROCESS_EXITED' if exit_code is not None else '')
        contact=bool(alive and not error and not self._closed and not ended and observed is not None and time.monotonic()-observed<=5
                     and epoch is not None and epoch[0] is self._node and epoch[1]==self.rpc_port)
        own=next((row for row in (state['accounts'] or []) if row['address']==self.member['account_key']),None) if state is not None else None
        if own is not None:own={**own,'nonce':str(own['nonce'])}
        return {'schema':'gg.sdk.financial-authority-observation.v1','scope':'PRIVATE_LAN_EXPERIMENT','role':'validator',
                'state':'CLOSED' if self._closed or ended else 'FAULT' if error else 'RUNNING' if alive else 'STOPPED',
                'owned_native_process':alive,'native_rpc_contact_fresh':contact,'certificate_is_network_liveness':False,
                'certificate_verified':proof is not None and not self._fault,'certificate_height':self._tip[0] if self._tip else None,
                'canonical_finality':proof is not None and not self._fault,'certificate_id':self._tip[1] if self._tip else None,
                'verified_at':self._verified_at,
                'financial_dag_commitment':deepcopy(state['financial_dag']) if state is not None else None,
                'own_account':deepcopy(own),'balances_basis':'LAST_VERIFIED_SDK_ACCOUNT_STATE_NOT_MINING_REWARDS',
                'account_proof_required':state is not None and state['accounts'] is None,
                'observation_origin':origin,'validator_index':self.index,'native_exit_code':exit_code,'last_error':error}

    def close(self):
        with self._lock:self.stop();self.profile.close();self._closed=True;_OWNED.discard(self)


def shutdown():
    for authority in list(_OWNED):
        try:authority.close()
        except (ValueError,OSError,RuntimeError):pass


atexit.register(shutdown)
