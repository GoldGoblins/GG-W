"""Shared owned native process transport; no source-specific DAG cache.

Lifecycle and RPC guards are shared by the legacy and segmented controllers.
Importing creates no key, listener or process. A concrete owner hook is required.
"""
from abc import ABC,abstractmethod
import base64
import hashlib
import http.client
import json
import os
import socket
import subprocess
import threading
import time
from urllib.parse import urlencode
import psutil
from backend import gg_consensus as native
from backend import gg_process_termination as termination
from backend import gg_native_resources as resources
from backend.gg_native_process_policy import contain_owned_native
from backend.gg_native_start import NativeStartReservation,native_start_budget,native_pipe_creation_flags

START_SECONDS=12


def _reserve_p2p_endpoint(host,port):
    reserve=socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM)
    try:
        # Match Go's POSIX TCP listener: a stopped owned connection may remain
        # in TIME_WAIT, while an active listener must still reject this bind.
        # Windows keeps the previous socket defaults; never enable REUSEPORT.
        if os.name!='nt':reserve.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        reserve.bind((host,port))
        return reserve
    except BaseException:
        reserve.close();raise


class OwnedNativeRPC(ABC):
    @abstractmethod
    def _owner_stopped(self):
        """True once the concrete owned session/profile lifetime has ended."""
        raise NotImplementedError

    def _process_owner(self):
        """Concrete typed controller supplies its actual node/profile lifetime."""
        raise ValueError('GG_NATIVE_PROCESS_OWNER_REQUIRED')

    def resource_observation(self):return resources.observation(self)

    def _unchanged(self):
        stat=self.binary.stat()
        if (stat.st_size,stat.st_mtime_ns)!=self._stamp:raise ValueError('GG_CONSENSUS_BINARY_CHANGED')

    def _alive(self):
        process=self._node['process'];return process is not None and process.poll() is None

    def _native_exit_code(self):
        process=self._node['process'];code=process.poll() if process is not None else None
        return code if type(code) is int and not self._epoch_stopping else None

    def _owned(self):
        return self._owned_endpoint(self._node,self.rpc_port)

    def _owned_endpoint(self,node,rpc_port):
        process=node['process']
        if process is None or process.poll() is not None:return False
        try:
            rows=psutil.Process(process.pid).net_connections(kind='tcp')
            listeners={(row.laddr.ip,row.laddr.port) for row in rows if row.status==psutil.CONN_LISTEN}
            expected={('127.0.0.1',rpc_port),(self.member['host'],self.member['p2p_port'])}
            return listeners==expected
        except (psutil.AccessDenied,PermissionError):
            self._unchanged();ready=node.get('_ready') or node.get('_prepared')
            return os.name!='nt' and ready is not None and ready.get('process') is process
        except (psutil.Error,OSError):return False

    def _rpc(self,method,params=None,*,timeout=3):
        if method not in {'status','net_info','abci_query','commit','broadcast_tx_sync','tx','block'}:raise ValueError('GG_VALIDATOR_RPC_METHOD')
        if self._start_cancelled():raise ValueError('GG_NATIVE_OWNER_STOPPED')
        self._unchanged()
        if not self._owned():raise ValueError('GG_VALIDATOR_LISTENER_NOT_OWNED')
        connection=self._connection
        if connection is None:
            connection=http.client.HTTPConnection('127.0.0.1',self.rpc_port,timeout=timeout)
            self._connection=connection
        def check_connection():
            if self._start_cancelled() or self._connection is not connection:raise ValueError('GG_NATIVE_OWNER_STOPPED')
        try:
            check_connection()
            connection.timeout=timeout
            sock=connection.sock
            if sock is not None:sock.settimeout(timeout)
            if method=='broadcast_tx_sync':
                raw=params
                if not isinstance(raw,bytes) or not 0<len(raw)<=48*1024*1024:raise ValueError('GG_VALIDATOR_BATCH_LIMIT')
                body=native._pack({'jsonrpc':'2.0','id':1,'method':method,'params':{'tx':base64.b64encode(raw).decode('ascii')}})
                check_connection();connection.request('POST','/',body=body,headers={'Content-Type':'application/json'})
            else:
                path='/'+method+('?' + urlencode(params) if params else '')
                if len(path)>8192:raise ValueError('GG_VALIDATOR_REQUEST_LIMIT')
                check_connection();connection.request('GET',path)
            check_connection();response=connection.getresponse();raw=response.read(512*1024+1)
            check_connection()
            if response.status!=200 or len(raw)>512*1024:raise ValueError('GG_VALIDATOR_RPC_RESPONSE')
            value=json.loads(raw)
            if not isinstance(value,dict) or 'error' in value or 'result' not in value:raise ValueError('GG_VALIDATOR_RPC_UNAVAILABLE')
            if response.will_close:self._drop_connection(connection)
            return value['result']
        except BaseException as error:
            cancelled=self._start_cancelled() or self._connection is not connection
            self._drop_connection(connection)
            # Closing a socket deliberately interrupts an in-flight request.
            # Report the lifecycle boundary, including HTTP internals racing
            # with close(), without publishing an observer thread traceback.
            if cancelled and isinstance(error,Exception):raise ValueError('GG_NATIVE_OWNER_STOPPED') from None
            raise

    def _drop_connection(self,expected=None):
        connection=self._connection if expected is None else expected
        if self._connection is connection:self._connection=None
        if connection is not None:
            try:connection.close()
            except OSError:pass

    def _status(self):
        result=self._rpc('status');public=self.member['validator_key']
        if (result['node_info']['network']!=self.anchor['genesis']['chain_id'] or result['node_info']['id'].lower()!=self.node_id
                or result['validator_info']['address'].lower()!=hashlib.sha256(bytes.fromhex(public)).digest()[:20].hex()):
            raise ValueError('GG_VALIDATOR_NODE_IDENTITY')
        return result

    def _query(self,path,height=None,data=None):
        params={'path':json.dumps(path),'prove':'false'}
        if height is not None:params['height']=str(height)
        if data is not None:params['data']='0x'+data.hex()
        response=self._rpc('abci_query',params)['response']
        if int(response.get('code',0))!=0:raise ValueError('GG_VALIDATOR_QUERY_REJECTED')
        raw=base64.b64decode(response['value'],validate=True)
        if len(raw)>65536:raise ValueError('GG_VALIDATOR_QUERY_LIMIT')
        return json.loads(raw)

    def _check_proof_epoch(self,epoch=None):
        # Published lifecycle fields are replaced atomically, never edited in
        # place. Public reads must not wait on signing/recovery's work lock.
        if (self._fault or self._closed or self.profile._closed or self.profile._failed
                or getattr(self.profile,'_native_pipe_closing',False) or self._epoch_stopping or self._owner_stopped()):raise ValueError('GG_VALIDATOR_PROOF_UNAVAILABLE')
        current=(self._node,self.rpc_port)
        if epoch is not None and (current[0] is not epoch[0] or current[1]!=epoch[1]):raise ValueError('GG_VALIDATOR_PROOF_PROCESS_CHANGED')
        if current[0] is not self._node or current[1]!=self.rpc_port:raise ValueError('GG_VALIDATOR_PROOF_PROCESS_CHANGED')
        return current

    def _public_query(self,epoch,path,height,data,*,connection=None):
        """Dedicated bounded read connection, never the consensus work socket."""
        self._check_proof_epoch(epoch);self._unchanged()
        borrowed=connection is not None
        if borrowed and (connection.host!='127.0.0.1' or connection.port!=epoch[1]):raise ValueError('GG_VALIDATOR_LISTENER_NOT_OWNED')
        if not borrowed or connection.sock is None:
            if not self._owned_endpoint(*epoch):raise ValueError('GG_VALIDATOR_LISTENER_NOT_OWNED')
        params={'path':json.dumps(path),'prove':'false','height':str(height),'data':'0x'+data.hex()}
        request='/abci_query?'+urlencode(params)
        if len(request)>8192:raise ValueError('GG_VALIDATOR_REQUEST_LIMIT')
        if connection is None:connection=http.client.HTTPConnection('127.0.0.1',epoch[1],timeout=3)
        try:
            connection.request('GET',request)
            response=connection.getresponse();raw=response.read(512*1024+1)
            if response.status!=200 or len(raw)>512*1024:raise ValueError('GG_VALIDATOR_RPC_RESPONSE')
            value=json.loads(raw)
            if not isinstance(value,dict) or 'error' in value or 'result' not in value:raise ValueError('GG_VALIDATOR_RPC_UNAVAILABLE')
            response=value['result']['response']
            if int(response.get('code',0))!=0:raise ValueError('GG_VALIDATOR_QUERY_REJECTED')
            raw=base64.b64decode(response['value'],validate=True)
            if len(raw)>65536:raise ValueError('GG_VALIDATOR_QUERY_LIMIT')
            result=json.loads(raw)
        finally:
            if not borrowed:connection.close()
        self._check_proof_epoch(epoch)
        return result

    def _watch_owner(self,cancel):
        while not cancel.wait(.2):
            if self._start_cancelled():
                self.close();return

    def stop(self):
        with self._lock:
            self._epoch_stopping=True
            if self._monitor_cancel is not None:self._monitor_cancel.set();self._monitor_cancel=None
            self._drop_connection();process=self._node['process']
            errors=[]
            try:
                if process is not None:
                    if not termination.process_terminal(process):process.terminate()
                    try:termination.wait_process_terminal(process,4)
                    except subprocess.TimeoutExpired:process.kill();termination.wait_process_terminal(process,3)
            except (OSError,subprocess.TimeoutExpired):errors.append('process')
            try:
                if self._lease is not None:self._lease.close()
            except (OSError,RuntimeError):errors.append('lease')
            if process is not None:
                try:
                    if not termination.process_terminal(process):
                        process.kill();termination.wait_process_terminal(process,3)
                except (OSError,subprocess.TimeoutExpired):errors.append('final_stop')
                try:terminal=termination.process_terminal(process)
                except OSError:terminal=False
                if not terminal:raise ValueError('GG_VALIDATOR_STOP_FAILED')
            if process is not None:
                for stream in (process.stdin,process.stdout):
                    if stream is not None:
                        try:stream.close()
                        except (OSError,ValueError):pass
            self._lease=None;self._node={'process':None,'_ready':None}
            resource=getattr(self,'_restore_resource',None)
            if resource is not None:resource.retire_after_terminal(process)
            if errors:raise ValueError('GG_VALIDATOR_STOP_CLEANUP_FAILED')

    def _native_bootstrap(self,fresh):
        validator,node=self.profile.native_signers()
        return {'schema':'gg.consensus.bootstrap.v2','genesis':self.anchor['genesis'],'genesis_hash':self.anchor['genesis_hash'],
            'validator_index':self.index,'validator_seed':bytes(validator)[:32].hex(),'node_seed':bytes(node)[:32].hex(),
            'root':str(self.profile.root/'native'),'rpc_port':self.rpc_port,'p2p_port':self.member['p2p_port'],
            'expected_fresh':fresh,'peers':[]}

    def _native_ready(self,process):
        return {'schema':'gg.consensus.ready.v2','chain_id':self.anchor['genesis']['chain_id'],'node_id':self.node_id,
            'pid':process.pid,'rpc_port':self.rpc_port,'p2p_host':self.member['host'],'p2p_port':self.member['p2p_port']}

    def _native_forbidden_ports(self):return {self.member['p2p_port'],*(invite['body']['p2p_port'] for invite in self.anchor['genesis']['membership']['validators'])}

    def _native_bootstrap_limit(self):return 65536

    def _after_native_start(self):pass

    def _start_cancelled(self):
        return self._closed or self.profile._closed or self.profile._failed or getattr(self.profile,'_native_pipe_closing',False) or self._owner_stopped() or not resources.matches(self)

    def _check_start(self):
        if self._start_cancelled():raise ValueError('GG_VALIDATOR_START_CANCELLED')
        resources.current(self)

    def _guard_start(self,process,cancel,expired,deadline):
        # No controller/profile work lock: this also bounds a blocked stdin write.
        while not cancel.wait(.05):
            if process.poll() is not None:return
            timed_out=time.monotonic()>=deadline
            if self._start_cancelled() or timed_out:
                if timed_out:expired.set()
                try:process.kill()
                except OSError:pass
                return

    def _spawn_native(self):
        if os.name!='nt':
            from backend.gg_posix_native import launch
            return launch(self.binary,cwd=self.profile.root,env=native._environment(resources.current(self)),resources=resources.current(self))
        return subprocess.Popen([str(self.binary)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            cwd=self.profile.root,env=native._environment(resources.current(self)),creationflags=native_pipe_creation_flags())

    def _launch_native(self):
        if getattr(self,'_protocol_owned_recovery',False):
            from backend.gg_protected_restore import owned_start
            return owned_start(self)
        resources.capture(self)
        self._unchanged();self._check_start()
        start_budget=native_start_budget(self.profile.root/'native',base_seconds=START_SECONDS)
        self._check_start();self._last_start_budget=dict(start_budget)
        reservations=[];payloads={};bootstrap=None;raw=None;guard=None;ready=None;abort_cancelled=None
        guard_cancel=threading.Event();expired=threading.Event()
        try:
            reserve=_reserve_p2p_endpoint(self.member['host'],self.member['p2p_port']);reservations.append(reserve)
            forbidden=self._native_forbidden_ports()
            for _ in range(16):
                reserve=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
                try:reserve.bind(('127.0.0.1',0))
                except BaseException:reserve.close();raise
                if reserve.getsockname()[1] not in forbidden:
                    reservations.append(reserve);break
                reserve.close()
            else:raise ValueError('GG_VALIDATOR_RPC_PORT_RESERVATION')
            self.rpc_port=reservations[1].getsockname()[1]
            # Validate/serialize both possible public freshness modes before any
            # durable intent. Secrets still enter the child only through its pipe.
            bootstrap=resources.bootstrap(self,self._native_bootstrap(False))
            payloads[False]=native._pack(bootstrap)
            bootstrap['expected_fresh']=True;payloads[True]=native._pack(bootstrap)
            if max(map(len,payloads.values()))>self._native_bootstrap_limit():raise ValueError('GG_VALIDATOR_BOOTSTRAP_LIMIT')
            bootstrap.clear();bootstrap=None;self._check_start()
            for reserve in reservations:reserve.close()
            process=self._spawn_native()
            self._node={'process':process,'_ready':None};self._lease=contain_owned_native(process,self._process_owner(),resources=resources.current(self))
            deadline=time.monotonic()+start_budget['seconds']
            guard=threading.Thread(target=self._guard_start,args=(process,guard_cancel,expired,deadline),name='GG-owned-native-start-deadline',daemon=True)
            guard.start()
            expected=resources.readiness(self,self._native_ready(process))
            ready=threading.Thread(target=native._read_ready,args=(self._node,process,expected),name='GG-owned-validator-ready',daemon=True);ready.start()
            self._check_start()
            with NativeStartReservation(self.profile,process,resources=resources.current(self)) as intent:
                try:
                    self._check_start()
                    if not self._alive():raise ValueError('GG_VALIDATOR_START_FAILED')
                    raw=payloads[intent.fresh];intent.mark_input_started()
                    process.stdin.write(raw);process.stdin.close()
                except BaseException:
                    # A fresh no-input reservation can release only after this
                    # exact child is confirmed terminal. Unknown writes retain it.
                    abort_cancelled=self._start_cancelled();self.stop();raise
            raw=None;payloads.clear()
            while time.monotonic()<deadline:
                self._check_start()
                if not self._alive():raise ValueError('GG_VALIDATOR_START_FAILED')
                attested=self._node.get('_ready')
                if (attested is not None and attested.get('process') is process
                        and attested.get('resources')==resources.current(self).ready() and self._owned()):
                    try:self._status()
                    except (ValueError,OSError,http.client.HTTPException):pass
                    else:
                        self._after_native_start();self._check_start()
                        if expired.is_set() or time.monotonic()>=deadline:raise ValueError('GG_VALIDATOR_READY_TIMEOUT')
                        if not self._alive():raise ValueError('GG_VALIDATOR_START_FAILED')
                        guard_cancel.set()
                        self._monitor_cancel=threading.Event()
                        self._epoch_stopping=False
                        threading.Thread(target=self._watch_owner,args=(self._monitor_cancel,),name='GG-validator-owner-lifetime',daemon=True).start()
                        self._check_start()
                        return self.snapshot()
                time.sleep(.05)
            raise ValueError('GG_VALIDATOR_READY_TIMEOUT')
        except BaseException as error:
            was_cancelled=self._start_cancelled() if abort_cancelled is None else abort_cancelled
            self.stop()
            if expired.is_set() and (isinstance(error,OSError) or isinstance(error,ValueError) and str(error) in {
                    'GG_VALIDATOR_START_FAILED','GG_NATIVE_START_CHILD_NOT_RUNNING'}):
                raise ValueError('GG_VALIDATOR_READY_TIMEOUT') from None
            if was_cancelled and isinstance(error,OSError):raise ValueError('GG_VALIDATOR_START_CANCELLED') from None
            raise
        finally:
            guard_cancel.set()
            if guard is not None and guard.ident is not None:guard.join(1)
            if ready is not None and ready.ident is not None:ready.join(1)
            raw=None;payloads.clear()
            if bootstrap is not None:bootstrap.clear()
            for reserve in reservations:reserve.close()
