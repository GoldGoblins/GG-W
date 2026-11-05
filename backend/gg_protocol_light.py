"""An owned light account/work client with no local consensus node.

The remote peer is authenticated by the native encrypted transport. State,
roles, balances and receipts remain independently native-verified SDK proofs.
Committee catch-up is bounded per call and never gates remote consensus.
"""
from collections import OrderedDict
from copy import deepcopy
import base64
import hashlib
import threading
import time

from backend import gg_consensus as native,gg_financial_protocol as protocol
from backend.gg_node_store import NodeProfile,pack,unpack
from backend.gg_observer_profile import ObserverProfile,PUBLIC_SCHEMAS
from backend.gg_protocol_node import OwnedProtocolNode
from backend.gg_protocol_transport import ProofTransportClient,endpoint,SCHEMA as TRANSPORT_SCHEMA
from backend.gg_committee_history import history
from backend import gg_native_resources as native_resources
from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence


class LightProtocolNode(OwnedProtocolNode):
    def __init__(self,profile,owner,settings,*,binary=None,stamp=None):
        if (type(owner) is not NodeProfile or owner._closed or owner._failed or owner._lease is None
                or type(profile) is not ObserverProfile or profile._body['schema'] not in PUBLIC_SCHEMAS):raise ValueError('GG_PROTOCOL_OWNED_LIGHT_PROFILE_REQUIRED')
        recovery=profile._recovery_intent()
        if recovery is not None and not recovery['complete']:raise ValueError('GG_OBSERVER_RECOVERY_INCOMPLETE')
        with owner._lock,profile._lock:
            identity,_=owner.signers()
            if profile._body['owner_key']!=identity.pubkey().hex():raise ValueError('GG_PROTOCOL_OWNER_MISMATCH')
            self.node_key=profile.native_node_signer().pubkey().hex()
        self.owner=owner;self.profile=profile;self.anchor=protocol.validate_pin(profile.anchor());self.role='LIGHT'
        self._transport_lifetimes=tuple((item,item._db,item._lease) for item in (owner,profile))
        if type(settings) is not dict:raise ValueError('GG_PROTOCOL_RELAY_ENDPOINT')
        selected=native_resources.resolve(settings.get('resources'))
        self.endpoint=endpoint({key:value for key,value in settings.items() if key!='resources'})
        self.settings={'peers':[deepcopy(self.endpoint)]}
        if selected.mode=='SERVER':self.settings['resources']=selected.wire()
        self._transport=None;self._transport_ready_epoch=None
        self.binary=native._installed_binary(native.TOOLS) if binary is None else binary
        self._stamp=native._validate_binary_at(native.TOOLS,self.binary) if binary is None else stamp
        self.node_id=hashlib.sha256(bytes.fromhex(self.node_key)).digest()[:20].hex();self.member={'validator_key':self.node_key}
        self._lock=threading.RLock();self._closed=False;self._stop_signal=threading.Event();self._fault=profile.snapshot()['last_error']
        self._packet=profile.public_certificate();self._tip=None;self._verified_at=None;self._last_contact=None;self._peers=[]
        self._records=OrderedDict();self._record_cursor=0;self._last_error='';self._node={'process':None};self.catchup_remaining=0
        if self._packet is not None:
            protocol.verify_selected(self._packet,self.anchor,binary=self.binary,stamp=self._stamp);self._tip=certificate_tip(self._packet,self.anchor)

    def _alive(self):return self._transport is not None and self._transport.alive()

    def process_ready(self):
        """Readiness of this authenticated transport, never a local SDK node."""
        transport=self._transport;epoch=self._node
        saved=self._transport_ready_epoch
        if transport is None or saved is None or saved[0] is not transport:return False
        try:
            if self._fault or self._start_cancelled() or not transport.alive():return False
            selected=native_resources.current(self)
        except ValueError:return False
        if any(item._db is not database or item._lease!=lease
                for item,database,lease in self._transport_lifetimes):return False
        process=epoch.get('process');ready=getattr(transport,'ready',None)
        protected=getattr(transport,'_protected_owners',())
        if (process is None or process is not transport.process or process.poll() is not None
                or saved is None or saved[0] is not transport or saved[1] is not process
                or len(protected)!=2 or protected[0] is not self.owner or protected[1] is not self.profile
                or getattr(transport,'_resources',None)!=selected
                or type(ready) is not dict or ready.get('event')!='READY' or ready.get('schema')!=TRANSPORT_SCHEMA
                or ready.get('genesis_hash')!=self.anchor['genesis_hash']
                or ready.get('peer_key')!=self.endpoint['server_key']
                or not native_resources.valid_readiness(ready.get('resources'))
                or ready['resources']!=selected.ready()):return False
        return self._transport is transport and self._node is epoch and native_resources.matches(self) and transport.alive()

    def _check_start(self):
        if self._start_cancelled() or self._fault or not self._alive():raise ValueError(self._fault or 'GG_PROTOCOL_LIGHT_STOPPED')

    def start(self):
        with self._lock:
            if self._start_cancelled() or self._fault:raise ValueError(self._fault or 'GG_PROTOCOL_LIGHT_STOPPED')
            if self._alive():return self.snapshot()
            if self._transport is not None:self._transport.close();self._transport=None
            native_resources.capture(self)
            self._transport=ProofTransportClient(self.profile.native_node_signer(),self.anchor,self.endpoint,binary=self.binary,stamp=self._stamp,owner=self.owner,profile=self.profile,resources=native_resources.current(self))
            self._transport_ready_epoch=(self._transport,self._transport.process)
            self._node={'process':self._transport.process};return self.snapshot()

    def _call(self,value):
        self._check_start();return self._transport.call(value)

    def _query(self,path,height=None,data=None):
        return self._call({'method':'query','path':path,'height':height,'selector':unpack(data) if data is not None else None})

    def _rpc(self,method,params=None,*,timeout=3):
        if method!='broadcast_tx_sync' or type(params) is not bytes or len(params)>48*1024:raise ValueError('GG_PROTOCOL_LIGHT_RPC_METHOD_OR_LIMIT')
        return self._call({'method':'operation','batch':base64.b64encode(params).decode('ascii')})

    def certified_state(self):
        with self._lock:
            packet=self._call({'method':'state'})
            if (not isinstance(packet,dict) or set(packet)-protocol.BASE-{'committee_transitions'} or not protocol.BASE<=set(packet)
                    or packet['genesis']!=self.anchor['genesis'] or packet['genesis_hash']!=self.anchor['genesis_hash']):raise ValueError('GG_PROTOCOL_LIGHT_STATE')
            current=history(self.anchor,self.binary,self._stamp);current.refresh();state=packet['state']['protocol']
            epoch=int(state['committee']['epoch'])
            if state.get('pending_committee') is not None:epoch=int(state['pending_committee']['next']['epoch'])
            if not 0<=epoch<=1000000:raise ValueError('GG_COMMITTEE_HISTORY_LIMIT')
            for selected in range(current.epoch+1,min(epoch,current.epoch+6)+1):
                transition=self._call({'method':'transition','epoch':selected});current.append(transition)
            self.catchup_remaining=max(0,epoch-current.epoch)
            if self.catchup_remaining:raise ValueError('GG_PROTOCOL_COMMITTEE_CATCHUP_REQUIRED')
            protocol.verify_selected(packet,self.anchor,binary=self.binary,stamp=self._stamp);tip=certificate_tip(packet,self.anchor)
            if self._tip is not None:
                if tip[0]<self._tip[0]:raise ValueError('GG_PROTOCOL_CERTIFICATE_REWIND')
                if tip[0]==self._tip[0] and tip!=self._tip:
                    self.profile.remember_conflict(make_conflict_evidence(self._packet,packet,self.anchor));self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE';raise ValueError(self._fault)
            self.profile.remember_certificate(packet)
            if self._tip!=tip:self._verified_at=time.time()
            self._packet,self._tip=deepcopy(packet),tip;self._last_contact=time.time()
            return packet

    def poll(self,*,producer_keys=(),maximum_records=2):
        with self._lock:
            if type(maximum_records) is not int or not 0<=maximum_records<=16:raise ValueError('GG_PROTOCOL_VIEW_BUDGET')
            packet=self.certified_state();keys=sorted(set(self.anchor['genesis']['financial_dag']['producers'])|set(producer_keys))
            if len(keys)>256:raise ValueError('GG_PROTOCOL_SELECTED_PRODUCER_LIMIT')
            for _ in range(min(maximum_records,2,len(keys))):
                key=keys[self._record_cursor%len(keys)];self._record_cursor+=1
                self.selected_proof('registry',{'namespace':'producers','key':key},packet=packet)
            self._peers=[{'node_id':hashlib.sha256(bytes.fromhex(self.endpoint['server_key'])).digest()[:20].hex(),
                'remote_ip':self.endpoint['host'],'outbound':True,'basis':'AUTHENTICATED_ENCRYPTED_PROOF_PROVIDER_NOT_VOTER'}]
            return self.snapshot()

    def resource_observation(self):
        if self._transport is not None:return native_resources.pipe_observation(self._transport,node=self)
        return native_resources.observation(self,scope='AUTHENTICATED_TRANSPORT_ONLY')

    def snapshot(self):
        with self._lock:
            value=super().snapshot();value['native_pid']=None;value['native_sdk_process']=False
            value['committee_catchup_remaining']=self.catchup_remaining;value['consensus_signing']=False;value['voting_power']='0'
            value['producer_work_running']=False;value['role']='LIGHT';value['local_full_history_replayed']=False
            for row in value['producers']:row['local_signer_ready']=False
            return value

    def request_stop(self):
        self._stop_signal.set()
        if self._transport is not None:self._transport.request_stop()

    def stop(self):
        self.request_stop()
        if self._transport is not None:self._transport.close();self._transport=None
        self._transport_ready_epoch=None
        self._node={'process':None}

    def close(self):
        with self._lock:self.stop();self._closed=True
