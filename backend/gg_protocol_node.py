"""Owned native protocol node, certified selected queries and truthful views.

Construction starts no process/listener. Explicit start uses the existing
protected startup reservation, process containment and child lifetime guards.
RPC remains owned loopback; configured peer connectivity, certified history
and locally running producer work are reported as separate observations.
"""
import atexit
import base64
from collections import OrderedDict
from copy import deepcopy
import hashlib
import http.client
import ipaddress
from pathlib import Path
import threading
import time

from backend import gg_consensus as native,gg_financial_protocol as protocol
from backend.gg_consensus_process import OwnedNativeRPC
from backend.gg_consensus_profile import ValidatorProfile
from backend.gg_observer_profile import ObserverProfile,PUBLIC_SCHEMAS
from backend.gg_node_store import NodeProfile,pack,unpack
from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence
from backend.gg_native_process_policy import owner_ended
from backend import gg_local_history_status as local_history
from backend.gg_native_resources import resolve

_OWNED=set()


def validate_settings(value):
    fields={'listen_host','max_inbound','max_outbound','p2p_port','peers'}
    if type(value) is not dict or set(value) not in (fields,fields|{'resources'}):raise ValueError('GG_PROTOCOL_NODE_SETTINGS')
    selected_resources=resolve(value.get('resources'))
    host=ipaddress.ip_address(value['listen_host'])
    if str(host)!=value['listen_host'] or host.is_multicast or host.is_link_local:raise ValueError('GG_PROTOCOL_NODE_HOST')
    for name,minimum,maximum in (('max_inbound',0,64),('max_outbound',1,16),('p2p_port',1024,65535)):
        if type(value[name]) is not int or not minimum<=value[name]<=maximum:raise ValueError('GG_PROTOCOL_NODE_SETTINGS')
    if not isinstance(value['peers'],list) or not 1<=len(value['peers'])<=value['max_outbound']:raise ValueError('GG_PROTOCOL_NODE_PEERS')
    ids=set();endpoints=set()
    for peer in value['peers']:
        if not isinstance(peer,dict) or set(peer)!={'host','id','port'}:raise ValueError('GG_PROTOCOL_NODE_PEERS')
        address=ipaddress.ip_address(peer['host'])
        if (str(address)!=peer['host'] or address.is_multicast or address.is_link_local or address.is_unspecified
                or type(peer['port']) is not int or not 1024<=peer['port']<=65535 or type(peer['id']) is not str
                or len(peer['id'])!=40 or any(char not in '0123456789abcdef' for char in peer['id'])
                or peer['id'] in ids or (peer['host'],peer['port']) in endpoints):raise ValueError('GG_PROTOCOL_NODE_PEERS')
        ids.add(peer['id']);endpoints.add((peer['host'],peer['port']))
    result=deepcopy(value)
    if selected_resources.mode=='LOW':result.pop('resources',None)
    else:result['resources']=selected_resources.wire()
    return result


class OwnedProtocolNode(OwnedNativeRPC):
    def __init__(self,profile,owner,settings,*,tools=None):
        if type(owner) is not NodeProfile or owner._closed or owner._failed or owner._lease is None:raise ValueError('GG_PROTOCOL_NODE_OWNER_REQUIRED')
        if type(profile) not in (ValidatorProfile,ObserverProfile) or profile._closed or profile._failed or profile._lease is None:raise ValueError('GG_PROTOCOL_NODE_PROFILE_REQUIRED')
        self.role='VALIDATOR' if type(profile) is ValidatorProfile else 'REPLICA'
        if self.role=='REPLICA' and profile._body['schema'] not in PUBLIC_SCHEMAS:raise ValueError('GG_PROTOCOL_REPLICA_PROFILE_REQUIRED')
        self.anchor=protocol.validate_pin(profile.anchor());self.settings=validate_settings(settings)
        own=owner.descriptor()['public_keys'][0]
        declared=profile.public_invite()['body']['owner_peer_key'] if self.role=='VALIDATOR' else profile._body['owner_key']
        if own!=declared:raise ValueError('GG_PROTOCOL_NODE_OWNER_MISMATCH')
        self.profile=profile;self.owner=owner;self._lock=threading.RLock();self._closed=False;self._fault=profile.snapshot()['last_error'];self._stop_signal=threading.Event()
        self._start_gate=threading.Lock();self._recovering=False;self._protocol_owned_recovery=True
        self._node={'process':None,'_ready':None};self._lease=None;self._connection=None;self.rpc_port=None;self._epoch_stopping=True;self._monitor_cancel=None
        node=profile.native_signers()[1] if self.role=='VALIDATOR' else profile.native_node_signer()
        self.node_key=node.pubkey().hex();self.node_id=hashlib.sha256(bytes.fromhex(self.node_key)).digest()[:20].hex()
        self.member={'host':self.settings['listen_host'],'p2p_port':self.settings['p2p_port'],'node_key':self.node_key,
                     'validator_key':profile.public_invite()['body']['validator_key'] if self.role=='VALIDATOR' else self.node_key}
        if any(peer['id']==self.node_id for peer in self.settings['peers']):raise ValueError('GG_PROTOCOL_NODE_SELF_PEER')
        self.tools=Path(native.TOOLS if tools is None else tools);self.binary=native._installed_binary(self.tools);self._stamp=native._validate_binary_at(self.tools,self.binary)
        self._packet=profile.public_certificate();self._tip=None;self._verified_at=None;self._last_contact=None;self._peers=[];self._records=OrderedDict();self._record_cursor=0;self._last_error=''
        if self._packet is not None:
            protocol.verify_selected(self._packet,self.anchor,binary=self.binary,stamp=self._stamp);self._tip=certificate_tip(self._packet,self.anchor)
        _OWNED.add(self)

    def _owner_stopped(self):
        cancel=getattr(self,'_foreground_cancel',None)
        return self._stop_signal.is_set() or cancel is not None and cancel.is_set() or self.owner._closed or self.owner._failed or owner_ended(self.owner)
    def _rpc(self,method,params=None,*,timeout=3):
        # Observer, producer and explicit CLI operations share one owned HTTP
        # connection. Requests must never interleave on that connection.
        with self._lock:return super()._rpc(method,params,timeout=timeout)
    def _process_owner(self):return self.owner
    def _native_forbidden_ports(self):return {self.member['p2p_port']}
    def _native_bootstrap_limit(self):return 512*1024

    def _native_bootstrap(self,fresh):
        if self.profile.anchor()!=self.anchor:raise ValueError('GG_PROTOCOL_NODE_ANCHOR_CHANGED')
        node=self.profile.native_signers()[1] if self.role=='VALIDATOR' else self.profile.native_node_signer()
        value={'schema':'gg.native.protocol-bootstrap.v1',**deepcopy(self.anchor),**deepcopy(self.settings),
               'expected_fresh':fresh,'node_seed':bytes(node)[:32].hex(),'role':self.role,'root':str(self.profile.root/'native'),'rpc_port':self.rpc_port}
        if self.role=='VALIDATOR':
            value['validator_seed']=bytes(self.profile.native_signers()[0])[:32].hex()
            context=self.profile._body['anchor'].get('membership_context')
            if context is not None:value['membership_context']=deepcopy(context)
        return value

    def _native_ready(self,process):
        return {'schema':'gg.consensus.protocol-ready.v1','chain_id':self.anchor['genesis']['chain_id'],'genesis_hash':self.anchor['genesis_hash'],
                'node_id':self.node_id,'pid':process.pid,'rpc_port':self.rpc_port,'p2p_host':self.member['host'],'p2p_port':self.member['p2p_port'],
                'role':self.role,'consensus_signing':self.role=='VALIDATOR','state_sync':False}

    def _status(self):
        result=super()._status()
        if self.role=='REPLICA' and result['validator_info']['voting_power']!='0':raise ValueError('GG_PROTOCOL_REPLICA_VOTING_POWER')
        return result

    def start(self):
        if not self._start_gate.acquire(blocking=False):raise ValueError('GG_PROTOCOL_START_ALREADY_RUNNING')
        try:
            if (self._closed or self._fault or self.owner._closed or self.owner._failed or owner_ended(self.owner)
                    or self.profile._closed or self.profile._failed or getattr(self.profile,'_native_pipe_closing',False)):
                raise ValueError(self._fault or 'GG_PROTOCOL_NODE_STOPPED')
            if not self._stop_signal.is_set() and self._alive():
                self._check_start();return self.snapshot()
            self.stop();self._stop_signal.clear();self._recovering=True
            self._last_contact=None;self._peers=[];self._verified_at=None;self._records.clear();self._published_records=()
            return self._launch_native()
        finally:
            self._recovering=False;self._start_gate.release()

    def restore_start(self,path):
        from backend.gg_protected_restore import restore_start
        if self.role!='REPLICA':raise ValueError('GG_OWNED_RESTORE_NONVOTING_REQUIRED')
        if not self._start_gate.acquire(blocking=False):raise ValueError('GG_PROTOCOL_START_ALREADY_RUNNING')
        self._recovering=True
        try:return restore_start(self,path)
        finally:self._recovering=False;self._start_gate.release()

    def restore_progress(self):
        # Immutable public record replacement; no signing/work lock or IO.
        from backend.gg_protected_restore import public_progress
        return public_progress(self)

    def recovery_progress(self):
        from backend.gg_protected_restore import recovery_progress
        return recovery_progress(self)

    def process_ready(self):
        ready=self._node.get('_ready');process=self._node.get('process')
        return bool(not self._recovering and not self._epoch_stopping and not self._start_cancelled()
            and process is not None and process.poll() is None and ready is not None and ready.get('process') is process)

    def request_stop(self):
        self._stop_signal.set();self._epoch_stopping=True;self._drop_connection()
        process=self._node['process']
        if process is not None and process.poll() is None:
            try:process.terminate()
            except OSError:pass

    def certified_state(self):
        with self._lock:
            if self._fault:raise ValueError(self._fault)
            if not self.process_ready():raise ValueError('GG_PROTOCOL_NODE_RECOVERING')
            height=int(self._status()['sync_info']['latest_block_height'])
            if height<1 or self._tip is not None and height<self._tip[0]:raise ValueError('GG_PROTOCOL_NO_FRESH_CERTIFICATE')
            state=self._query('/gg/state',height-1);header=self._rpc('commit',{'height':str(height)})['signed_header']
            from backend.gg_committee_history import history
            known=history(self.anchor,self.binary,self._stamp);known.refresh()
            epoch=int(state['protocol']['committee']['epoch']);pending=state['protocol'].get('pending_committee')
            if pending is not None:epoch=int(pending['next']['epoch'])
            for selected in range(known.epoch+1,epoch+1):
                decision=self._query('/gg/protocol/committee-transition-state',None,pack(str(selected)))
                signed=self._rpc('commit',{'height':str(decision['height']+1)})['signed_header']
                known.append({'schema':'gg.financial.committee-transition-proof.v1','signed_header':signed,'state':decision})
            packet={'schema':'gg.consensus.proof.v1',**deepcopy(self.anchor),'state':state,'signed_header':header}
            protocol.verify_selected(packet,self.anchor,binary=self.binary,stamp=self._stamp);tip=certificate_tip(packet,self.anchor)
            if self._tip is not None and tip[0]==self._tip[0] and tip!=self._tip:
                evidence=make_conflict_evidence(self._packet,packet,self.anchor);self.profile.remember_conflict(evidence);self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE';raise ValueError(self._fault)
            self.profile.remember_certificate(packet)
            if tip!=self._tip:self._verified_at=time.time()
            self._packet,self._tip=deepcopy(packet),tip
            return packet

    def selected_proof(self,kind,selector,*,packet=None):
        if not self.process_ready():raise ValueError('GG_PROTOCOL_NODE_RECOVERING')
        with self._lock:
            core=self.certified_state() if packet is None else deepcopy(packet)
            protocol.verify_selected(core,self.anchor,binary=self.binary,stamp=self._stamp)
            if kind=='registry':path='/gg/financial-dag/registry-proof';field='financial_registry';expected='expected_financial_registry';kwargs={'registry':selector}
            elif kind=='block':path='/gg/financial-dag/block-proof';field='financial_block';expected='expected_financial_block';kwargs={'block':selector}
            elif kind=='reward':path='/gg/financial-dag/reward-proof';field='financial_reward';expected='expected_financial_reward';kwargs={'reward':selector}
            elif kind=='account':
                from backend.gg_financial_dag import verify_account,account_address
                selector=account_address(selector);path='/gg/financial-dag/account-proof';field='financial_account';expected='expected_financial_account';kwargs=None
            elif kind=='receipt':
                from backend.gg_protocol_producer import decode_core
                from backend import gg_financial_wire as wire
                if not isinstance(selector,dict) or set(selector)!={'block','index'} or type(selector['index']) is not int:raise ValueError('GG_PROTOCOL_RECEIPT_SELECTOR')
                original=decode_core(self.original_core(selector['block']),self.anchor);payments=original['body']['payments'];index=selector['index']
                if not 0<=index<len(payments):raise ValueError('GG_PROTOCOL_RECEIPT_SELECTOR')
                transaction_id=wire.intent_id(pack(payments[index]));path='/gg/financial-dag/receipt';field='financial_receipt';expected='expected_financial_receipt';kwargs='receipt'
            else:raise ValueError('GG_PROTOCOL_QUERY_KIND')
            value=self._query(path,core['state']['height'],pack(selector));result={**core,field:value,expected:deepcopy(selector)}
            if kwargs=='receipt':
                from backend.gg_financial_dag import verify_receipt
                result[expected]={'block':selector['block'],'index':selector['index'],'transaction_id':transaction_id}
                verify_receipt(result,self.anchor,expected_transaction_id=transaction_id,binary=self.binary,stamp=self._stamp);return result
            if kwargs is None:verify_account(result,self.anchor,selector,binary=self.binary,stamp=self._stamp)
            else:
                verified=protocol.verify_selected(result,self.anchor,binary=self.binary,stamp=self._stamp,**kwargs)
                if kind=='registry' and selector['namespace']=='producers' and verified['financial_registry_exists']:
                    record=unpack(base64.b64decode(verified['financial_registry_value'],validate=True));key=selector['key']
                    previous=self._records.get(key)
                    if previous is None or core['state']['height']>=previous[1]:self._records[key]=(record,core['state']['height'])
                    self._records.move_to_end(key)
                    while len(self._records)>256:self._records.popitem(last=False)
                    self._published_records=tuple(self._records.items())
            return result

    def original_core(self,identifier):
        """Read bounded public chunks from this exact owned native journal."""
        if not self.process_ready():raise ValueError('GG_PROTOCOL_NODE_RECOVERING')
        from backend.gg_protocol_producer import decode_core,core_id
        protocol._hash(identifier)
        with self._lock:
            chunks=[];offset=0;total=None;expected=None
            while total is None or offset<total:
                value=self._query('/gg/protocol/original-core-chunk',None,pack({'block':identifier,'max_bytes':32768,'offset':offset}))
                if (not isinstance(value,dict) or set(value)!={'block','data','offset','schema','total_bytes','wire_hash'}
                        or value['schema']!='gg.financial.original-core-chunk.v1' or value['block']!=identifier or value['offset']!=offset
                        or type(value['total_bytes']) is not int or not 0<value['total_bytes']<=32*1024*1024):raise ValueError('GG_PROTOCOL_ORIGINAL_CHUNK')
                if total is None:total=value['total_bytes'];expected=protocol._hash(value['wire_hash'])
                if value['total_bytes']!=total or value['wire_hash']!=expected:raise ValueError('GG_PROTOCOL_ORIGINAL_CHANGED')
                data=base64.b64decode(value['data'],validate=True)
                if len(data)!=min(32768,total-offset):raise ValueError('GG_PROTOCOL_ORIGINAL_CHUNK')
                chunks.append(data);offset+=len(data)
            raw=b''.join(chunks)
            if hashlib.sha256(raw).hexdigest()!=expected or core_id(decode_core(raw,self.anchor))!=identifier:raise ValueError('GG_PROTOCOL_ORIGINAL_CHANGED')
            return raw

    def _refresh_local_history(self):
        # Publish one immutable observation tied to the exact native epoch.
        process=self._node['process']
        try:
            if self.role not in ('VALIDATOR','REPLICA') or not self._alive():
                raise ValueError('GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE')
            value=self._query('/gg/protocol/local-history-status')
            checked=local_history.validate_report(value,self.anchor['genesis_hash'])
            if self._node['process'] is not process or not self._alive():
                raise ValueError('GG_PROTOCOL_LOCAL_HISTORY_UNAVAILABLE')
            self._local_history_record=(process,checked,time.time(),False)
        except (OSError,ValueError,KeyError,TypeError,http.client.HTTPException):
            self._local_history_record=(process,None,None,True)

    def local_history_observation(self):
        # Runtime snapshots must not acquire the signing/recovery work lock or
        # do IO. Recheck freshness even if the last complete poll is cached.
        if self.role=='LIGHT':
            return local_history.observation(None,self.anchor['genesis_hash'],self.role,running=False)
        current=self._node;process=current.get('process')
        saved,report,observed_at,error=getattr(self,'_local_history_record',(None,None,None,False))
        running=self._alive()
        try:
            epoch=self._check_proof_epoch()
            running=running and epoch[0] is current
        except ValueError:
            running=False
        if current is not self._node or process is not saved:
            report=None;observed_at=None;error=False
        return local_history.observation(report,self.anchor['genesis_hash'],self.role,
            running=running,observed_at=observed_at,error=error)

    def poll(self,*,producer_keys=(),maximum_records=4):
        with self._lock:
            if type(maximum_records) is not int or not 0<=maximum_records<=16:raise ValueError('GG_PROTOCOL_VIEW_BUDGET')
            core=self.certified_state();network=self._rpc('net_info');peers=network.get('peers',[])
            if not isinstance(peers,list) or len(peers)>80:raise ValueError('GG_PROTOCOL_PEER_VIEW')
            self._peers=[{'node_id':row['node_info']['id'],'remote_ip':row['remote_ip'],'outbound':row['is_outbound'],
                          'basis':'NATIVE_AUTHENTICATED_TRANSPORT_NOT_MONETARY_OR_VOTING_AUTHORITY'} for row in peers]
            self._last_contact=time.time();keys=sorted(set(self.anchor['genesis']['financial_dag']['producers'])|set(producer_keys))
            if len(keys)>256:raise ValueError('GG_PROTOCOL_SELECTED_PRODUCER_LIMIT')
            for _ in range(min(maximum_records,len(keys))):
                key=keys[self._record_cursor%len(keys)];self._record_cursor+=1
                packet=self.selected_proof('registry',{'namespace':'producers','key':key},packet=core)
                # selected_proof already verified and cached an existing record.
            self._refresh_local_history()
            self._last_error='';return self.snapshot()

    def snapshot(self):
        ready=self.process_ready()
        state=self._packet['state'] if self._packet is not None and not self._fault and ready else None;commitment=state['financial_dag'] if state else None
        rows=[];owner=self.owner.descriptor()['public_keys'][0]
        for key,(record,height) in sorted(getattr(self,'_published_records',())):
            body=record['invite']['body'];local=body['owner_peer_key']==owner
            rows.append({'index':len(rows),'producer_key':key,'owner_peer_key':body['owner_peer_key'],'node_key':body['node_key'],
                         'display_name':base64.b64decode(body['label_utf8'],validate=True).decode('utf-8')+' · '+body['platform']+' · '+key[:8],
                         'label':base64.b64decode(body['label_utf8'],validate=True).decode('utf-8'),'platform':body['platform'],'local':local,
                         'reward_account':body['reward_account'],
                         'producer_enabled':True,'local_signer_ready':local and body['node_key']==self.node_key and key in self.owner.descriptor()['public_keys'][1:],
                         'proposals':record['sequence'],'transactions':record['attempts'],'certified_sequence':record['sequence'],'last_block':record['head'] if record['sequence']!='0' else None,
                         'record_height':height,'identity_basis':'SIGNED_REGISTRATION_AND_SDK_CERTIFIED_RECORD','platform_is_hardware_attestation':False})
        committee=deepcopy(state['protocol']['committee']['members']) if state else []
        if state and state['protocol'].get('pending_committee') and state['height']+1>=int(state['protocol']['pending_committee']['effective_height']):committee=deepcopy(state['protocol']['pending_committee']['next']['members'])
        power=next((row['power'] for row in committee if row['validator_key']==self.member['validator_key']),'0') if self.role=='VALIDATOR' else '0'
        connected=bool(self._alive() and self._last_contact is not None and time.time()-self._last_contact<=5 and self._peers)
        peers=deepcopy(self._peers) if connected else []
        for peer in peers:
            identity=next((row for row in rows if hashlib.sha256(bytes.fromhex(row['node_key'])).digest()[:20].hex()==peer['node_id']),None)
            peer['label']=identity['display_name'] if identity else 'Peer '+peer['node_id'][:12]
        return {'schema':'gg.protocol.node-observation.v1','state':'FAULT' if self._fault else 'RECOVERING' if getattr(self,'_recovering',False) else 'RUNNING' if ready else 'STOP_PENDING' if self._alive() else 'STOPPED','mode':'FINANCIAL_SDK_CERTIFIED_VIEW',
                'chain_id':self.anchor['genesis']['chain_id'],'network_id':self.anchor['genesis']['financial_dag']['network_id'],'environment':self.anchor['genesis']['protocol']['environment'],
                'role':self.role,'consensus_signing':self.role=='VALIDATOR' and ready,'node_ready':ready,'node_key':self.node_key,'native_pid':self._node['process'].pid if self._alive() else None,
                'committee':committee,'voting_power':power,'resources':self.resource_observation(),
                'certificate_height':self._tip[0] if self._tip else None,'certificate_received_at':self._verified_at,'certificate_is_network_liveness':False,
                'certified_time_ns':state['protocol']['time_ns'] if state else None,'last_state_advance_at':self._verified_at,
                'state_root':state['state_root'] if state else None,'certified_blocks':commitment['blocks'] if commitment else None,
                'certified_transactions':commitment['applied'] if commitment else None,'rejected_transactions':commitment['rejected'] if commitment else None,
                'producer_count':int(state['protocol']['producer_root']['count']) if state else None,'producers':rows,'producer_rows_scope':'SELECTED_CERTIFIED_RECORDS_WITH_INDIVIDUAL_HEIGHTS',
                'network_contact_at':self._last_contact,'connection_state':'CONNECTED' if connected else 'UNOBSERVED','peers':peers,
                'economic_state':deepcopy(state['protocol']['economics']) if state else None,'fee_pot_atomic':state['protocol']['fee_pot_atomic'] if state else None,
                'account_tree':deepcopy(state.get('account_tree')) if state else None,
                'local_history':self.local_history_observation(),
                'local_full_history_replayed':False,'last_error':self._fault or self._last_error,'producer_work_running':False}

    def close(self):
        with self._lock:
            self.stop();self._closed=True;_OWNED.discard(self)


def shutdown():
    for node in tuple(_OWNED):node.close()


atexit.register(shutdown)
