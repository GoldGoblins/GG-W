"""One owned native full observer, with zero consensus signing authority."""
import atexit
import base64
from copy import deepcopy
import hashlib
import re
from pathlib import Path
import threading
import time

from backend import gg_consensus as native
from backend.gg_consensus_process import OwnedNativeRPC
from backend.gg_native_resources import resolve
from backend.gg_observer_profile import ObserverProfile
from backend.gg_consensus_membership import anchor_from_owned_peer
from backend.gg_dag_checkpoint import certificate_tip,make_conflict_evidence,validate_conflict_evidence
from backend.gg_lan_dag import LanDagPeer
from backend.gg_segmented_authority import OwnedSegmentedSession
from backend.gg_financial_authority import OwnedFinancialSession

_OWNED=set()
_SESSIONS=(OwnedSegmentedSession,OwnedFinancialSession)


class OwnedObserver(OwnedNativeRPC):
    def __init__(self,profile,owner,*,tools=None,resources=None):
        if not isinstance(profile,ObserverProfile) or not isinstance(owner,(LanDagPeer,*_SESSIONS)):
            raise ValueError('GG_OBSERVER_OWNED_CONTEXT_REQUIRED')
        self._resource_profile=resolve(resources)
        self.profile=profile;self.owner=owner;self._lock=threading.RLock();self._closed=False
        self._node={'process':None,'_ready':None};self._lease=None;self._connection=None;self.rpc_port=None
        self._monitor_cancel=None;self._epoch_stopping=True;self._fault='';self._tip=None;self._view=None;self._public_packet=None
        self._stop_signal=threading.Event();self._managed_cancel=None;self._transport_view=None;self._view_epoch=None
        self.anchor=profile.anchor();self.member=profile.public_grant()['body']
        self._check_context()
        self.tools=Path(native.TOOLS if tools is None else tools)
        self.binary=native._installed_binary(self.tools);self._stamp=native._validate_binary_at(self.tools,self.binary)
        self.node_id=hashlib.sha256(bytes.fromhex(self.member['node_key'])).digest()[:20].hex()
        old=profile.public_certificate()
        if old is not None:
            result=native._verify_public(old,self.binary,self._stamp)
            if result.get('verified') is not True:raise ValueError('GG_OBSERVER_CERTIFICATE_REQUIRED')
            self._tip=certificate_tip(old,self.anchor);self._public_packet=deepcopy(old)
            self._view=(deepcopy(old['state']),time.time(),'PERSISTED_CERTIFICATE')
        evidence=profile.public_conflict()
        if evidence is not None:
            validate_conflict_evidence(evidence,self.anchor)
            for packet in evidence['certificates']:
                if native._verify_public(packet,self.binary,self._stamp).get('verified') is not True:
                    raise ValueError('GG_OBSERVER_CONFLICT_CERTIFICATE_REQUIRED')
            self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
        _OWNED.add(self)

    def _owner_stopped(self):
        from backend.gg_native_process_policy import owner_ended
        if isinstance(self.owner,_SESSIONS):return self.owner.stopped()
        return self.owner._cancel.is_set() or owner_ended(self._process_owner()) or self.owner._profile is not None and (
            self.owner._profile._closed or self.owner._profile._failed)

    def _start_cancelled(self):
        return (super()._start_cancelled() or self._stop_signal.is_set()
            or self._managed_cancel is not None and self._managed_cancel.is_set())

    def _process_owner(self):
        return self.owner.owner if isinstance(self.owner,_SESSIONS) else self.owner._profile or self.owner

    def _check_context(self):
        if self._closed or self._owner_stopped():raise ValueError('GG_OBSERVER_OWNER_STOPPED')
        if self._managed_cancel is not None and self._managed_cancel.is_set():raise ValueError('GG_OBSERVER_STOPPED')
        if isinstance(self.owner,_SESSIONS):
            self.owner.check();anchor=self.owner.anchor();key=self.owner.public_key;role=self.owner.node_role
        else:
            anchor=anchor_from_owned_peer(self.owner);key=self.owner.public_key;role=self.owner.node_role
        if role=='light':raise ValueError('GG_LAN_LIGHT_READ_ONLY')
        if anchor!=self.anchor or self.member['owner_peer_key']!=key or self.profile.anchor()!=anchor:
            raise ValueError('GG_OBSERVER_OWNER_OR_ANCHOR_CHANGED')
        if self.profile._closed or self.profile._failed:raise ValueError('GG_OBSERVER_PROFILE_UNAVAILABLE')

    def _native_bootstrap(self,fresh):
        self._check_context();node=self.profile.native_node_signer()
        return {'schema':'gg.native.observer-bootstrap.v1','genesis':self.anchor['genesis'],
            'genesis_hash':self.anchor['genesis_hash'],'observer_grant':self.profile.public_grant(),
            'node_seed':bytes(node)[:32].hex(),'root':str(self.profile.root/'native'),
            'rpc_port':self.rpc_port,'expected_fresh':fresh}

    def _native_ready(self,process):
        return {'schema':'gg.consensus.observer-ready.v1','chain_id':self.anchor['genesis']['chain_id'],
            'genesis_hash':self.anchor['genesis_hash'],'node_id':self.node_id,'pid':process.pid,
            'rpc_port':self.rpc_port,'p2p_host':self.member['host'],'p2p_port':self.member['p2p_port'],
            'consensus_signing':False,'state_sync':False}

    def _status(self):
        self._check_context();result=self._rpc('status');public=self.member['node_key']
        try:
            info=result['validator_info']
            if (result['node_info']['network']!=self.anchor['genesis']['chain_id']
                    or result['node_info']['id'].lower()!=self.node_id
                    or info['address'].lower()!=hashlib.sha256(bytes.fromhex(public)).digest()[:20].hex()
                    or info['pub_key']!={'type':'tendermint/PubKeyEd25519','value':base64.b64encode(bytes.fromhex(public)).decode('ascii')}
                    or info['voting_power']!='0'):raise ValueError()
        except (KeyError,TypeError,ValueError,AttributeError):raise ValueError('GG_OBSERVER_NODE_IDENTITY_OR_VOTE') from None
        return result

    def _rpc(self,method,params=None,*,timeout=3):
        if method=='broadcast_tx_sync':raise ValueError('GG_OBSERVER_READ_ONLY')
        if self._stop_signal.is_set():raise ValueError('GG_OBSERVER_STOPPED')
        self._check_context()
        return super()._rpc(method,params,timeout=timeout)

    def start(self,*,cancel=None):
        with self._lock:
            if cancel is not None:
                if not isinstance(cancel,threading.Event):raise ValueError('GG_OBSERVER_CANCEL_EVENT')
                self._managed_cancel=cancel
            if self._fault:raise ValueError(self._fault)
            # Profile/owner closure is permanent; our local stop signal is
            # resumable only after the old exact child has retired below.
            if self.profile._closed or self.profile._failed or getattr(self.profile,'_native_pipe_closing',False):
                raise ValueError('GG_OBSERVER_PROFILE_UNAVAILABLE')
            self._check_context()
            if not self._stop_signal.is_set() and self._alive():
                self._check_start();return self.snapshot()
            self.stop();self._stop_signal.clear();return self._launch_native()

    def restore_start(self,path):
        from backend.gg_protected_restore import restore_start
        self._check_context()
        return restore_start(self,path)

    def request_stop(self):
        """Interrupt only this exact SDK child and RPC; no work-lock wait."""
        self._stop_signal.set();self._epoch_stopping=True
        self._drop_connection();process=self._node['process']
        if process is not None and process.poll() is None:
            try:process.terminate()
            except OSError:pass

    def stop(self):
        self.request_stop();super().stop()

    def refresh_status(self):
        """Owned SDK transport observation, independent of an old certificate."""
        with self._lock:
            try:self._check_context();status=self._status();net=self._rpc('net_info')
            except BaseException:
                self._transport_view=None;raise
            try:
                height=status['sync_info']['latest_block_height'];catching=status['sync_info']['catching_up']
                count=net['n_peers'];peers=net['peers']
                if (type(height) is not str or not re.fullmatch(r'0|[1-9][0-9]{0,18}',height) or int(height)>=2**63
                        or type(catching) is not bool or type(count) is not str or not re.fullmatch(r'[0-4]',count)
                        or not isinstance(peers,list) or len(peers)!=int(count)):raise ValueError()
                allowed={hashlib.sha256(bytes.fromhex(row['body']['node_key'])).digest()[:20].hex()
                    for row in self.anchor['genesis']['membership']['validators']}
                ids=[];received=sent=0;has_counters=True
                for peer in peers:
                    identifier=peer['node_info']['id'].lower()
                    if identifier not in allowed or peer['node_info']['network']!=self.anchor['genesis']['chain_id'] or identifier in ids:
                        raise ValueError()
                    ids.append(identifier)
                    try:
                        counters=peer['connection_status']
                        values=[counters[name]['Bytes'] for name in ('RecvMonitor','SendMonitor')]
                        parsed=[]
                        for value in values:
                            if type(value) is int and 0<=value<2**63:parsed.append(value)
                            elif type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,18}',value) and int(value)<2**63:parsed.append(int(value))
                            else:raise ValueError()
                        received+=parsed[0];sent+=parsed[1]
                    except (KeyError,TypeError,ValueError):has_counters=False
                observation={'latest_height':height,'catching_up':catching,'peer_count':len(ids),'peer_ids':sorted(ids),
                    'received_bytes':str(received) if has_counters else None,'sent_bytes':str(sent) if has_counters else None,
                    'traffic_scope':'SDK_FLOW_MONITOR_BYTES_OF_CURRENT_CONNECTED_PEERS_NOT_LIFETIME_TOTAL',
                    'observed_at':time.time()}
            except (KeyError,TypeError,ValueError,AttributeError):
                self._transport_view=None;raise ValueError('GG_OBSERVER_NATIVE_STATUS_INVALID') from None
            self._check_context()
            if self._stop_signal.is_set():raise ValueError('GG_OBSERVER_STOPPED')
            self._transport_view=(observation,time.monotonic(),self._node)
            return self.snapshot()

    def certified_state(self):
        with self._lock:
            self._check_context()
            if self._fault:raise ValueError(self._fault)
            height=int(self._status()['sync_info']['latest_block_height'])
            if height<1 or self._tip is not None and height<self._tip[0]:raise ValueError('GG_OBSERVER_NO_FRESH_CERTIFICATE')
            header=self._rpc('commit',{'height':str(height)})['signed_header']
            state=self._query('/gg/genesis' if height==1 else '/gg/state',height-1 if height>1 else None)
            packet={'schema':'gg.consensus.proof.v1',**self.anchor,'state':state,'signed_header':header}
            verified=native._verify_public(packet,self.binary,self._stamp)
            if verified.get('verified') is not True:raise ValueError('GG_OBSERVER_CERTIFICATE_REQUIRED')
            tip=certificate_tip(packet,self.anchor)
            if self._tip is not None and tip[0]==self._tip[0] and tip!=self._tip:
                evidence=make_conflict_evidence(self._public_packet,packet,self.anchor)
                self._fault='GG_CONSENSUS_CONFLICTING_CERTIFICATE'
                try:self.profile.remember_conflict(evidence)
                except (ValueError,OSError):
                    self._fault='GG_OBSERVER_CERTIFICATE_SAVE_FAILED';raise
                finally:self.stop()
                raise ValueError(self._fault)
            try:self.profile.remember_certificate(packet)
            except (ValueError,OSError):
                self._fault='GG_OBSERVER_CERTIFICATE_SAVE_FAILED';self.stop();raise
            self._tip=tip;self._public_packet=deepcopy(packet);self._view=(deepcopy(state),time.time(),'OWNED_SDK_QUERY');self._view_epoch=self._node
            return deepcopy(packet)

    def cached_certificate(self):
        return None if self._fault or self._closed or self._owner_stopped() else deepcopy(self._public_packet)

    def snapshot(self):
        view=self._view;state,observed,origin=view if view is not None else (None,None,None)
        alive=self._alive();stopped=self._owner_stopped();verified=view is not None and not self._fault
        process=self._node['process'];exit_code=process.poll() if process is not None else None
        unexpected=process is not None and exit_code is not None and not self._epoch_stopping and not self._stop_signal.is_set()
        error=self._fault or ('GG_OBSERVER_NATIVE_PROCESS_EXITED' if unexpected else '')
        transport=self._transport_view;current=transport is not None and transport[2] is self._node
        age=max(0,time.monotonic()-transport[1]) if current else None
        observation=deepcopy(transport[0]) if current else {'peer_count':None,'latest_height':None,'catching_up':None,
            'received_bytes':None,'sent_bytes':None,'observed_at':None}
        fresh=current and age<=5 and alive and not stopped and not self._stop_signal.is_set()
        behind=self._tip is not None and observation['latest_height'] is not None and int(observation['latest_height'])<self._tip[0]
        connected=fresh and observation['peer_count']>0
        contact_state=('STOPPED' if self._closed or stopped or self._stop_signal.is_set() or unexpected else
            'UNOBSERVED' if not current else 'STALE' if not fresh else 'DISCONNECTED' if not connected else
            'SYNCING' if observation['catching_up'] or behind else 'CONNECTED')
        same_execution=origin=='OWNED_SDK_QUERY' and self._view_epoch is self._node and alive and not stopped and not self._stop_signal.is_set()
        from backend.gg_consensus_membership import public_label
        return {'schema':'gg.native.observer-observation.v1','role':'native_full_observer','scope':'PRIVATE_LAN_EXPERIMENT',
            'resources':self.resource_observation(),
            'profile':self.profile.name,'display_name':public_label(self.member),'native_node_key':self.member['node_key'],
            'owner_peer_key':self.member['owner_peer_key'],'delegating_producer_key':self.member['producer_key'],
            'state':'CLOSED' if self._closed or stopped else 'FAULT' if error else 'RUNNING' if alive else 'STOPPED',
            'owned_native_process':alive,'owner_stopped':stopped,'consensus_signing':False,'voting_power':0,
            'state_sync':False,'certificate_verified':verified,'certificate_height':self._tip[0] if self._tip else None,
            'canonical_finality':verified,'verified_at':observed,'observation_origin':origin,
            'local_state_read_from_owned_sdk':same_execution,
            'native_connection':{**observation,'state':contact_state,'connected':bool(connected),'stale':not fresh,
                'observation_age_s':age,'behind_saved_certificate':bool(behind),'source':'OWNED_SDK_STATUS_AND_NET_INFO'},
            'native_exit_code':exit_code if unexpected else None,'native_limits':self._lease.facts if self._lease is not None else None,
            'client_full_history_replayed':False,'certificate_is_network_liveness':False,
            'commitment':deepcopy(state.get('financial_dag',state.get('dag_segmented',state.get('dag')))) if state else None,'last_error':error}

    def close(self):
        with self._lock:
            self.stop();self.profile.close();self._closed=True;_OWNED.discard(self)


def shutdown():
    for node in list(_OWNED):
        try:node.close()
        except (ValueError,OSError,RuntimeError):pass


atexit.register(shutdown)
