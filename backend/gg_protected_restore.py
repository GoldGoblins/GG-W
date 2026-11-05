"""One protected nonvoting restore/start pipe; no checkpoint or signer import.

The actual verified native child performs both complete original replay passes
and retains its real ledger for SDK startup. Public progress is never a proof,
network contact, monetary receipt or permission to bypass a protected intent.
"""
from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import threading
import time

from backend import gg_consensus as native,gg_process_termination as termination
from backend import gg_native_resources as resources
from backend import gg_native_pipe_lifecycle as pipes
from backend.gg_consensus_process import _reserve_p2p_endpoint
from backend.gg_dag_checkpoint import certificate_tip
from backend.gg_native_process_policy import contain_owned_native
from backend.gg_native_start import (START_MAX_SECONDS,native_pipe_creation_flags,
    NativeStartReservation,OwnedRecoveryProgress,owned_recovery_preflight)
from backend.platform_files import is_link

FRAME_MAX=512*1024
COMMAND='financial-owned-restore-start'
HASH=re.compile(r'[0-9a-f]{64}')
PHASES=frozenset({'FULL_ORIGINAL_AUDIT','APPLICATION_RESTORED'})


class _HandoffResource:
    """Exact profile-close fence retained until strict kernel terminal proof."""
    def __init__(self,node):
        self.resources=resources.current(node)
        self.node=node;self.process=None;self.lease=None;self.epoch=None;self.rpc_port=None;self.cancel=threading.Event()
        self._resource_retired=False;self.profile=node.profile;self.anchor=node.anchor;self.owner_reference=node.owner
        self._protected_owners=(node._process_owner(),node.profile)
        self._protected_lifetimes=tuple((owner,getattr(owner,'_db',None),getattr(owner,'_lease',None)) for owner in self._protected_owners)
        self.attempt=secrets.token_hex(16);self.progress=None
        self._root=node.profile.root/'native';self._root_identity=None
        self._profile_root_identity=node.profile.root.stat(follow_symlinks=False)

    def current(self):
        node=self.node
        return (node._node is self.epoch and self.epoch is not None and self.epoch.get('process') is self.process
            and node.rpc_port==self.rpc_port and node.profile is self.profile and node.anchor is self.anchor
            and node.owner is self.owner_reference and getattr(node,'_restore_resource',None) is self)

    def check(self):
        if not self.current() or self.cancel.is_set() or self._resource_retired:raise ValueError('GG_OWNED_RESTORE_EPOCH_CHANGED')
        for owner,database,lease in self._protected_lifetimes:
            if (owner._closed or owner._failed or getattr(owner,'_native_pipe_closing',False)
                    or owner._db is not database or owner._lease!=lease):raise ValueError('GG_NATIVE_START_PROFILE_UNAVAILABLE')
        self.node._check_start()
        if resources.current(self.node)!=self.resources:raise ValueError('GG_NATIVE_RESOURCE_PROFILE_CHANGED')
        if (any(is_link(item) for item in (self._root,*self._root.parents))
                or not os.path.samestat(self._profile_root_identity,self.profile.root.stat(follow_symlinks=False))):
            raise ValueError('GG_OWNED_RECOVERY_ROOT_CHANGED')
        try:root_info=self._root.stat(follow_symlinks=False)
        except FileNotFoundError:
            if self._root_identity is not None:raise ValueError('GG_OWNED_RECOVERY_ROOT_CHANGED') from None
        else:
            if not self._root.is_dir():raise ValueError('GG_OWNED_RECOVERY_ROOT_CHANGED')
            if self._root_identity is None:self._root_identity=root_info
            elif not os.path.samestat(self._root_identity,root_info):raise ValueError('GG_OWNED_RECOVERY_ROOT_CHANGED')

    def request_stop(self):
        # Never route an old resource's stop through node._node: that may now
        # belong to a different explicit start. Signal only this exact Popen.
        self.cancel.set();process=self.process
        if process is not None:
            try:
                if not termination.process_terminal(process):process.terminate()
            except OSError:pass

    def close(self):self.request_stop();_stop_attempt(self)

    def retire_after_terminal(self,process):
        if self._resource_retired:return
        if process is not self.process:raise pipes.NativePipeStopPending()
        if process is not None and not termination.process_terminal(process):raise pipes.NativePipeStopPending()
        self._resource_retired=True
        pipes.release_owned_pipe(self)


def _stop_attempt(resource):
    node=resource.node
    with node._lock:
        if resource.current():
            node.stop()
            return
    # A newer explicit attempt owns node's fields. Retire only the retained old
    # process/leaf/pipes, with the existing normal stop budgets, preserving all
    # exact references if terminal proof or leaf close fails.
    process=resource.process
    if process is not None:
        try:
            if not termination.process_terminal(process):process.terminate()
            try:termination.wait_process_terminal(process,4)
            except subprocess.TimeoutExpired:process.kill();termination.wait_process_terminal(process,3)
        except (OSError,subprocess.TimeoutExpired):raise pipes.NativePipeStopPending() from None
        if not termination.process_terminal(process):raise pipes.NativePipeStopPending()
    if resource.lease is not None:
        try:resource.lease.close()
        except (OSError,RuntimeError):raise pipes.NativePipeStopPending() from None
    if process is not None:
        for stream in (process.stdin,process.stdout):
            if stream is not None:
                try:stream.close()
                except (OSError,ValueError):raise pipes.NativePipeStopPending() from None
    resource.retire_after_terminal(process)


def _guard_attempt(resource,cancel,expired,deadline):
    node=resource.node
    while not cancel.wait(.05):
        process=resource.process
        try:
            if termination.process_terminal(process):return
            unavailable=any(owner._closed or owner._failed or getattr(owner,'_native_pipe_closing',False)
                or owner._db is not database or owner._lease!=lease for owner,database,lease in resource._protected_lifetimes)
            timed_out=deadline.expired() if isinstance(deadline,OwnedRecoveryProgress) else time.monotonic()>=deadline
            if timed_out or resource.cancel.is_set() or not resource.current() or not resources.matches(node) or unavailable:
                if timed_out:expired.set()
                process.kill();return
        except OSError:return


def _watch_attempt_owner(resource,cancel):
    while not cancel.wait(.2):
        if not resource.current():return
        try:resource.check()
        except ValueError:
            resource.close()
            return


def _update_progress(resource,phase,**values):
    with resource.node._lock:
        resource.check()
        _progress(resource.node,phase,**values)


def _read_attempt_frame(resource):
    frame=_read_frame(resource.process)
    with resource.node._lock:resource.check()
    if set(frame)=={'error'} and type(frame['error']) is str and re.fullmatch(r'GG_[A-Z0-9_]{1,100}',frame['error']):
        raise ValueError(frame['error'])
    return frame


def _call_attempt(resource,callback,*args):
    resource.check()
    result=callback(*args)
    resource.check()
    return result


def _progress(node,phase,*,processed=None,verified=None,error=''):
    # Replace one bounded public object, so UI reads require no work lock.
    for height in (processed,verified):
        if height is not None and (type(height) is not int or not 0<=height<=2**63-1):raise ValueError('GG_OWNED_RESTORE_HEIGHT')
    record={'schema':'gg.owned.archive-start-observation.v1','phase':phase,
        'processed_height':str(processed) if processed is not None else None,
        'verified_through':str(verified) if verified is not None else None,'last_error':error,
        'basis':'LOCAL_OWNED_NATIVE_PIPE_REPORT','node_ready':phase=='READY',
        'full_original_audit_completed':verified is not None,
        'snapshot_trust_used':False,'certificate_is_network_liveness':False,
        'network_contact_asserted':False,'consensus_signing':False}
    node._restore_progress_record=(node._node,record)


def public_progress(node):
    epoch,body=getattr(node,'_restore_progress_record',(None,None))
    if body is None:return None
    record=deepcopy(body)
    current=node._node
    if epoch is not current:
        record.update(phase='UNAVAILABLE',processed_height=None,verified_through=None,
            full_original_audit_completed=False,node_ready=False)
    elif record['phase']=='READY' and (node._epoch_stopping or node._start_cancelled() or not node._alive()):
        record.update(phase='STOPPED',node_ready=False)
    return record


def _read_frame(process):
    raw=process.stdout.readline(FRAME_MAX+1)
    if len(raw)<3 or len(raw)>FRAME_MAX or not raw.endswith(b'\n'):raise ValueError('GG_OWNED_RESTORE_FRAME')
    value=json.loads(raw)
    if not isinstance(value,dict) or native._pack(value)!=raw[:-1]:raise ValueError('GG_OWNED_RESTORE_FRAME')
    return value


def _bound(frame,node,process,schema,fields):
    if (set(frame)!=fields|{'schema','genesis_hash','pid'} or frame['schema']!=schema
            or frame['genesis_hash']!=node.anchor['genesis_hash'] or type(frame['pid']) is not int
            or frame['pid']!=process.pid):raise ValueError('GG_OWNED_RESTORE_FRAME')


def _certificate_frame(frame,node,process,schema,archive=None,certificate=None):
    _bound(frame,node,process,schema,{'archive_sha256','certificate','native_node_ready'})
    digest=frame['archive_sha256'];packet=frame['certificate']
    if (frame['native_node_ready'] is not False or type(digest) is not str or not HASH.fullmatch(digest)
            or not isinstance(packet,dict) or packet.get('genesis')!=node.anchor['genesis']
            or packet.get('genesis_hash')!=node.anchor['genesis_hash']):raise ValueError('GG_OWNED_RESTORE_CERTIFICATE')
    # Structural anti-rewind check only. The actual contained, binary-pinned
    # native child has already verified every original and SDK certificate.
    tip=certificate_tip(packet,node.anchor)
    if archive is not None and (digest!=archive or packet!=certificate):raise ValueError('GG_OBSERVER_RECOVERY_INTENT_CHANGED')
    return digest,packet,tip


def _ack(process,node,archive,phase,*,genesis_hash=None):
    raw=native._pack({'schema':'gg.native.owned-archive-ack.v1','pid':process.pid,
        'genesis_hash':node.anchor['genesis_hash'] if genesis_hash is None else genesis_hash,'archive_sha256':archive,'phase':phase})+b'\n'
    process.stdin.write(raw);process.stdin.flush()


def _public_request(node,path,floor):
    key=node.node_key if getattr(node,'role',None)=='REPLICA' else node.member['node_key']
    return resources.bootstrap(node,{'schema':'gg.native.owned-archive-start.v1','archive_path':str(path),'expected_node_key':key,
        'genesis':deepcopy(node.anchor['genesis']),'genesis_hash':node.anchor['genesis_hash'],
        'minimum_certificate_height':floor[0] if floor is not None else 0,
        'minimum_certificate_block':floor[1] if floor is not None else '',
        'restore_root':str(node.profile.root/'native')})


def _recovery_progress(resource,phase,**values):
    resource.check();node=resource.node
    body={'schema':'gg.owned.recovery-observation.v1','phase':phase,'requested_role':getattr(node,'role','REPLICA'),
        'work_done':values.get('work_done','0'),'processed_height':values.get('processed_height'),
        'verified_through':values.get('verified_through') if phase=='READY' else None,'last_error':values.get('error',''),
        'basis':'LOCAL_OWNED_NATIVE_PIPE_REPORT','node_ready':phase=='READY',
        'full_original_audit_completed':phase=='READY',
        'snapshot_trust_used':False,'certificate_is_network_liveness':False,
        'network_contact_asserted':False,'consensus_signing':phase=='READY' and getattr(node,'role',None)=='VALIDATOR'}
    node._recovery_progress_record=(resource.epoch,body)


def recovery_progress(node):
    epoch,body=getattr(node,'_recovery_progress_record',(None,None))
    if body is None:return None
    result=deepcopy(body)
    if epoch is not node._node:
        result.update(phase='UNAVAILABLE',node_ready=False,consensus_signing=False,
            processed_height=None,verified_through=None,full_original_audit_completed=False)
    elif body['phase']=='READY':
        if not node.process_ready():
            result.update(phase='STOP_PENDING' if node._alive() else 'STOPPED',node_ready=False,consensus_signing=False,
                verified_through=None,full_original_audit_completed=False)
    elif node._stop_signal.is_set() or node._closed or node.profile._closed or node.profile._failed:
        result.update(phase='STOP_PENDING' if node._alive() else 'STOPPED',node_ready=False,consensus_signing=False,
            verified_through=None,full_original_audit_completed=False)
    return result


def _progress_lease(resource,*,archive=False):
    return OwnedRecoveryProgress(pid=resource.process.pid,genesis_hash=resource.anchor['genesis_hash'],
        root=resource.profile.root/'native',attempt=resource.attempt,
        resource_profile=resource.resources.ready(),archive=archive)


def _accept_recovery_progress(resource,frame):
    resource.check();values=resource.progress.accept(frame)
    _recovery_progress(resource,**values)


def _ack_prepared_protocol(resource,frame):
    node=resource.node;process=resource.process;resource.check();resource.progress.ready()
    expected=resources.readiness(node,node._native_ready(process))
    expected.update(schema='gg.consensus.protocol-prepared.v1',consensus_signing=False)
    if (frame!=expected or not resources.valid_readiness(frame.get('resources'))
            or any(type(frame.get(name)) is not type(value) for name,value in expected.items() if type(value) in (int,bool))):
        raise ValueError('GG_OWNED_RECOVERY_PREPARED')
    resource.progress.handshake()
    resource.epoch['_prepared']={'process':process,'resources':frame['resources'],
        'sdk_rates':{name:frame[name] for name in ('sdk_send_bytes_per_second','sdk_recv_bytes_per_second')}}
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        resource.check()
        if not node._alive():raise ValueError('GG_VALIDATOR_START_FAILED')
        if node._owned_endpoint(resource.epoch,resource.rpc_port):
            try:node._status()
            except (ValueError,OSError,http.client.HTTPException):pass
            else:
                resource.check()
                raw=native._pack({'schema':'gg.native.owned-recovery-start-ack.v1',
                    'attempt':resource.attempt,'pid':process.pid,'genesis_hash':resource.anchor['genesis_hash'],
                    'root':str(resource.profile.root/'native'),'resource_profile':resource.resources.ready()})+b'\n'
                process.stdin.write(raw);process.stdin.close();resource.check();return
        if resource.cancel.wait(.05):raise ValueError('GG_VALIDATOR_START_CANCELLED')
    raise ValueError('GG_VALIDATOR_READY_TIMEOUT')


def owned_start(node):
    """Normal protocol restart, using the same full-audit child through READY.

    This entry does not accept archive authority or manufacture signer state.
    The native process keeps its original SafePV journal and gates SDK signing.
    """
    node._last_start_budget=owned_recovery_preflight(node.profile.root/'native')
    node._unchanged();guard_cancel=threading.Event();expired=threading.Event()
    resource=None;guard=None;reservations=[];raw=None;payloads={};bootstrap=None
    try:
        with node._lock:
            node._check_start();resources.capture(node)
            previous=getattr(node,'_restore_resource',None)
            if previous is not None and not previous._resource_retired:raise pipes.NativePipeStopPending()
            resource=_HandoffResource(node);node._restore_resource=resource
            pipes.bind_owned_pipe(resource,resource._protected_owners)
            reservations.append(_reserve_p2p_endpoint(node.member['host'],node.member['p2p_port']))
            for _ in range(16):
                reserve=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                try:reserve.bind(('127.0.0.1',0))
                except BaseException:reserve.close();raise
                if reserve.getsockname()[1] not in node._native_forbidden_ports():reservations.append(reserve);break
                reserve.close()
            else:raise ValueError('GG_VALIDATOR_RPC_PORT_RESERVATION')
            node.rpc_port=reservations[1].getsockname()[1]
            bootstrap=resources.bootstrap(node,node._native_bootstrap(False))
            certificate=node.profile.public_certificate()
            floor=certificate_tip(certificate,node.anchor) if certificate is not None else None
            for fresh in (False,True):
                bootstrap['expected_fresh']=fresh
                payloads[fresh]=native._pack({'schema':'gg.native.owned-protocol-start.v1',
                    'attempt':resource.attempt,'bootstrap':bootstrap,
                    'minimum_certificate_height':floor[0] if floor is not None else 0,
                    'minimum_certificate_block':floor[1] if floor is not None else ''})+b'\n'
            if max(map(len,payloads.values()))>FRAME_MAX:raise ValueError('GG_VALIDATOR_BOOTSTRAP_LIMIT')
            bootstrap.clear();bootstrap=None
            node._check_start()
            for reserve in reservations:reserve.close()
            if os.name=='nt':
                process=subprocess.Popen([str(node.binary),'protocol-owned-start'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,cwd=node.profile.root,env=native._environment(resource.resources),creationflags=native_pipe_creation_flags())
            else:
                from backend.gg_posix_native import launch
                process=launch(node.binary,cwd=node.profile.root,env=native._environment(resource.resources),
                    arguments=('protocol-owned-start',),resources=resource.resources)
            resource.process=process;node._node={'process':process,'_ready':None}
            resource.epoch=node._node;resource.rpc_port=node.rpc_port
            node._lease=contain_owned_native(process,node._process_owner(),resources=resource.resources);resource.lease=node._lease
            resource.progress=_progress_lease(resource)
            guard=threading.Thread(target=_guard_attempt,args=(resource,guard_cancel,expired,resource.progress),
                name='GG-owned-recovery-stall-guard',daemon=True);guard.start()
            _recovery_progress(resource,'STARTING')
        # The protected intent stays monotonic across any possible input write.
        with NativeStartReservation(node.profile,process,resources=resource.resources) as intent:
            try:
                resource.check();raw=payloads[intent.fresh];intent.mark_input_started()
                process.stdin.write(raw);process.stdin.flush()
            except BaseException:_stop_attempt(resource);raise
        raw=None;payloads.clear()
        prepared=False
        while True:
            resource.check()
            if resource.progress.expired():raise ValueError('GG_OWNED_RECOVERY_STALLED')
            frame=_read_attempt_frame(resource)
            if frame.get('schema')=='gg.native.owned-recovery-progress.v1':
                if prepared:raise ValueError('GG_OWNED_RECOVERY_PREPARED')
                _accept_recovery_progress(resource,frame);continue
            if frame.get('schema')=='gg.consensus.protocol-prepared.v1':
                if prepared:raise ValueError('GG_OWNED_RECOVERY_PREPARED')
                _ack_prepared_protocol(resource,frame);prepared=True;continue
            if not prepared:raise ValueError('GG_OWNED_RECOVERY_PREPARED')
            resource.progress.ready()
            resource.epoch['_ready']=_validated_ready_frame(node,process,frame)
            process.stdout.close();break
        # READY attestation is followed by the existing actual listener/RPC test.
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            resource.check()
            if not node._alive():raise ValueError('GG_VALIDATOR_START_FAILED')
            if node._owned_endpoint(resource.epoch,resource.rpc_port):
                try:node._status()
                except (ValueError,OSError,http.client.HTTPException):pass
                else:
                    node._after_native_start();resource.check()
                    if expired.is_set():raise ValueError('GG_OWNED_RECOVERY_STALLED')
                    node._epoch_stopping=False;guard_cancel.set();node._recovering=False
                    node._monitor_cancel=threading.Event()
                    threading.Thread(target=_watch_attempt_owner,args=(resource,node._monitor_cancel),
                        name='GG-validator-owner-lifetime',daemon=True).start()
                    last=recovery_progress(node) or {}
                    _recovery_progress(resource,'READY',work_done=last.get('work_done','0'),
                        processed_height=last.get('processed_height'),verified_through=last.get('processed_height'))
                    return node.snapshot()
            if resource.cancel.wait(.05):raise ValueError('GG_VALIDATOR_START_CANCELLED')
        raise ValueError('GG_VALIDATOR_READY_TIMEOUT')
    except BaseException as error:
        if resource is not None:
            if resource.current():
                code=str(error) if re.fullmatch(r'GG_[A-Z0-9_]{1,100}',str(error)) else 'GG_OWNED_RECOVERY_FAILED'
                try:_recovery_progress(resource,'FAILED',error=code)
                except ValueError:pass
            _stop_attempt(resource)
        raise
    finally:
        raw=None;payloads.clear()
        if bootstrap is not None:bootstrap.clear()
        guard_cancel.set()
        if guard is not None:guard.join(1)
        for reserve in reservations:reserve.close()


def _prepare_private_grant(resource,archive,certificate):
    node=resource.node
    with node._lock:
        resource.check()
        node.profile.prepare_recovery(archive,certificate)
        resource.check()
        # The real signed profile commit has completed before the first seed
        # is requested for serialization or sent to this exact private pipe.
        bootstrap=resources.bootstrap(node,node._native_bootstrap(False))
        try:
            resource.check()
            raw=native._pack({'schema':'gg.native.owned-archive-restore.v1','pid':resource.process.pid,
                'genesis_hash':resource.anchor['genesis_hash'],'archive_sha256':archive,'phase':'RESTORE','bootstrap':bootstrap})+b'\n'
            if len(raw)>FRAME_MAX:raise ValueError('GG_VALIDATOR_BOOTSTRAP_LIMIT')
            return raw
        finally:bootstrap.clear()


def _floor(node):
    selected=node.profile.public_certificate()
    floor=certificate_tip(selected,node.anchor) if selected is not None else None
    # Legacy session floors are distinct from protocol-v7 profile floors.
    # NodeProfile's legacy session floor must never be repinned to schema7.
    if getattr(node,'role',None)!='REPLICA':
        owner=node._process_owner();saved=owner.consensus_observation()
        if saved is not None:
            if saved['fault']:raise ValueError(saved['fault'])
            other=owner._consensus_tip(saved)
            if floor is not None and other[0]==floor[0] and other!=floor:raise ValueError('GG_CONSENSUS_CONFLICTING_CERTIFICATE')
            if floor is None or other[0]>floor[0]:floor=other
    return floor


def _validated_ready_frame(node,process,frame):
    rates={name:frame.get(name) for name in ('sdk_send_bytes_per_second','sdk_recv_bytes_per_second')}
    expected=resources.readiness(node,node._native_ready(process))
    if (not resources.valid_readiness(frame.get('resources'))
            or not resources.valid_sdk_rates(resources.current(node),rates)
            or frame!=expected
            or any(type(frame.get(name)) is not type(value) for name,value in expected.items() if type(value) in (int,bool))):
        raise ValueError('GG_OWNED_RESTORE_READY')
    return {'process':process,'resources':frame['resources'],'sdk_rates':rates}


def restore_start(node,path):
    """Use already opened profiles and return only after owned RPC readiness.

    The runtime calls this on its existing owned observer thread. No profile is
    opened, key created, helper process spawned, or external endpoint accepted.
    Completed work renews a finite180s stall lease; bootstrap and final RPC
    readiness retain short guards. No heartbeat or old certificate extends it.
    """
    from backend.gg_observer_profile import ObserverProfile
    if type(node.profile) is not ObserverProfile or getattr(node,'role',None) not in (None,'REPLICA'):
        raise ValueError('GG_OWNED_RESTORE_NONVOTING_REQUIRED')
    if not isinstance(path,(str,Path)) or not str(path) or len(str(path))>4096:raise ValueError('GG_FINANCIAL_HISTORY_PATH')
    target=Path(path).expanduser()
    if not target.is_absolute() or any(is_link(item) for item in (target,*target.parents)):
        raise ValueError('GG_FINANCIAL_HISTORY_PATH')
    target=target.resolve(strict=True)
    if not target.is_file():raise ValueError('GG_FINANCIAL_HISTORY_PATH')
    native_root=node.profile.root/'native'
    if target.is_relative_to(native_root):raise ValueError('GG_FINANCIAL_HISTORY_PATH')
    node._unchanged()
    guard_cancel=threading.Event();expired=threading.Event();guard=None;reservations=[];raw=None
    resource=None
    try:
        with node._lock:
            if node._node['process'] is not None:raise ValueError('GG_OWNED_RESTORE_NODE_ALREADY_STARTED')
            previous=getattr(node,'_restore_resource',None)
            if previous is not None and not previous._resource_retired:raise pipes.NativePipeStopPending()
            had_attempt=hasattr(node,'_native_resource_attempt')
            previous_attempt=getattr(node,'_native_resource_attempt',None)
            try:
                resources.capture(node)
                node._check_start();floor=_floor(node)
                resource=_HandoffResource(node)
            except BaseException:
                if had_attempt:node._native_resource_attempt=previous_attempt
                elif hasattr(node,'_native_resource_attempt'):del node._native_resource_attempt
                raise
            node._restore_resource=resource
            pipes.bind_owned_pipe(resource,resource._protected_owners)
            reservations.append(_reserve_p2p_endpoint(node.member['host'],node.member['p2p_port']))
            for _ in range(16):
                reserve=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                try:reserve.bind(('127.0.0.1',0))
                except BaseException:reserve.close();raise
                if reserve.getsockname()[1] not in node._native_forbidden_ports():reservations.append(reserve);break
                reserve.close()
            else:raise ValueError('GG_VALIDATOR_RPC_PORT_RESERVATION')
            node.rpc_port=reservations[1].getsockname()[1]
            request=_public_request(node,target,floor)
            request['attempt']=resource.attempt
            raw=native._pack(request)+b'\n'
            request.clear()
            if len(raw)>FRAME_MAX:raise ValueError('GG_VALIDATOR_BOOTSTRAP_LIMIT')
            node._check_start()
            if resource.cancel.is_set() or resource._resource_retired:raise ValueError('GG_VALIDATOR_START_CANCELLED')
            for reserve in reservations:reserve.close()
            if os.name=='nt':
                process=subprocess.Popen([str(node.binary),COMMAND],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,cwd=node.profile.root,env=native._environment(resource.resources),creationflags=native_pipe_creation_flags())
            else:
                from backend.gg_posix_native import launch
                process=launch(node.binary,cwd=node.profile.root,env=native._environment(resource.resources),arguments=(COMMAND,),resources=resource.resources)
            # Publish the exact Popen before containment, private seed handoff,
            # callback or any failure that can invoke an owner close fence.
            resource.process=process;node._node={'process':process,'_ready':None}
            resource.epoch=node._node;resource.rpc_port=node.rpc_port
            node._lease=contain_owned_native(process,node._process_owner(),resources=resource.resources)
            resource.lease=node._lease
            resource.progress=_progress_lease(resource,archive=True)
            _recovery_progress(resource,'STARTING')
            guard=threading.Thread(target=_guard_attempt,args=(resource,guard_cancel,expired,resource.progress),
                name='GG-owned-restore-start-deadline',daemon=True);guard.start()
            resource.check()
            process.stdin.write(raw);process.stdin.flush();raw=None
            resource.check()
        _update_progress(resource,'FULL_ORIGINAL_AUDIT',processed=0)
        archive=certificate=None;verified=None;restored=False;phase='AUDIT';last_height=0
        while True:
            with node._lock:resource.check()
            if resource.progress.expired():raise ValueError('GG_OWNED_RECOVERY_STALLED')
            frame=_read_attempt_frame(resource)
            schema=frame.get('schema')
            if schema=='gg.native.owned-recovery-progress.v1':
                _accept_recovery_progress(resource,frame);continue
            if schema=='gg.native.owned-archive-progress.v1':
                _bound(frame,node,process,schema,{'phase','processed_height','native_node_ready','certificate_is_network_liveness'})
                height=frame['processed_height'];reported=frame['phase']
                if (reported not in PHASES or type(height) is not int or height<0 or height>2**63-1
                        or frame['native_node_ready'] is not False or frame['certificate_is_network_liveness'] is not False
                        or reported=='FULL_ORIGINAL_AUDIT' and (phase!='AUDIT' or height<last_height)
                        or reported=='APPLICATION_RESTORED' and (phase!='RESTORE' or height!=verified)):
                    raise ValueError('GG_OWNED_RESTORE_PHASE')
                if reported=='FULL_ORIGINAL_AUDIT':last_height=height
                _update_progress(resource,reported,processed=height,verified=verified);continue
            if schema=='gg.native.owned-archive-audited.v1':
                if phase!='AUDIT':raise ValueError('GG_OWNED_RESTORE_PHASE')
                archive,certificate,tip=_certificate_frame(frame,node,process,schema)
                if floor is not None and (tip[0]<floor[0] or tip[0]==floor[0] and tip!=floor):raise ValueError('GG_OBSERVER_RECOVERY_CERTIFICATE_REWIND')
                node._unchanged()
                raw=_prepare_private_grant(resource,archive,certificate)
                # The protected exact intent exists before native root writes.
                verified=certificate['state']['height'];phase='RESTORE'
                _update_progress(resource,'RESTORING_APPLICATION',processed=0,verified=verified)
                with node._lock:resource.check()
                process.stdin.write(raw);process.stdin.flush();raw=None
                with node._lock:resource.check()
                continue
            if schema=='gg.native.owned-archive-restored.v1':
                if phase!='RESTORE':raise ValueError('GG_OWNED_RESTORE_PHASE')
                _certificate_frame(frame,node,process,schema,archive,certificate)
                node._unchanged()
                with node._lock:
                    resource.check()
                    _call_attempt(resource,node.profile.finish_recovery,archive,certificate)
                    if getattr(node,'role',None)!='REPLICA':node._process_owner().save_consensus_certificate(certificate)
                    resource.check()
                    node._packet=deepcopy(certificate) if getattr(node,'role',None)=='REPLICA' else getattr(node,'_packet',None)
                    node._tip=certificate_tip(certificate,node.anchor)
                phase='START';restored=True
                _update_progress(resource,'SDK_START',processed=verified,verified=verified)
                with node._lock:resource.check()
                _ack(process,node,archive,'START',genesis_hash=resource.anchor['genesis_hash']);process.stdin.close()
                with node._lock:resource.check()
                continue
            # Exactly the original native-ready record, only after both durable
            # acknowledgements. It is still followed by actual owned RPC checks.
            with node._lock:
                resource.check()
                if not restored or phase!='START':raise ValueError('GG_OWNED_RESTORE_READY')
                resource.progress.ready()
                resource.epoch['_ready']=_validated_ready_frame(node,process,frame)
            process.stdout.close()
            break
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            with node._lock:resource.check()
            if not node._alive():raise ValueError('GG_VALIDATOR_START_FAILED')
            if node._owned_endpoint(resource.epoch,resource.rpc_port):
                with node._lock:
                    resource.check()
                    try:_call_attempt(resource,node._status)
                    except (ValueError,OSError,http.client.HTTPException):pass
                    else:
                        _call_attempt(resource,node._after_native_start)
                        if expired.is_set() or time.monotonic()>=deadline:raise ValueError('GG_VALIDATOR_READY_TIMEOUT')
                        node._epoch_stopping=False;node._recovering=False;guard_cancel.set()
                        node._monitor_cancel=threading.Event()
                        threading.Thread(target=_watch_attempt_owner,args=(resource,node._monitor_cancel),name='GG-validator-owner-lifetime',daemon=True).start()
                        resource.check()
                        _progress(node,'READY',processed=verified,verified=verified)
                        _recovery_progress(resource,'READY',processed_height=str(verified),verified_through=str(verified),
                            work_done=str(resource.progress._work))
                        visible=node.snapshot();resource.check();return visible
            time.sleep(.05)
        raise ValueError('GG_VALIDATOR_READY_TIMEOUT')
    except BaseException as error:
        code=str(error) if re.fullmatch(r'GG_[A-Z0-9_]{1,100}',str(error)) else 'GG_OWNED_RESTORE_START_FAILED'
        if resource is not None:
            with node._lock:
                if resource.current():_progress(node,'FAILED',error=code)
            _stop_attempt(resource) # An old failure can never stop a newer epoch.
        raise
    finally:
        raw=None
        guard_cancel.set()
        if guard is not None:guard.join(1)
        for reserve in reservations:reserve.close()
