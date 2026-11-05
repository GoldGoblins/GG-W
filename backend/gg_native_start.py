"""A one-use, same-lease reservation before private SDK bootstrap handoff.

Only a proven never-handed-off fresh attempt may release its own startup intent.
Cold/older intents and any possible pipe write remain fail-closed. This context
never stops a process, deletes native files, resets keys or opens a profile.
"""
from copy import deepcopy
import math
import os
from pathlib import Path
import stat
import subprocess
import threading
import time

from backend.platform_files import is_link
from backend import gg_process_termination as termination
from backend.gg_native_resources import resolve,valid_readiness

START_MAX_SECONDS=180
START_BASE_STORE_BYTES=16*1024**2
START_REPLAY_BYTES_PER_SECOND=4*1024**2
START_INVENTORY_MAX_ENTRIES=4096
START_INVENTORY_MAX_DEPTH=16


def owned_recovery_preflight(root):
    """Short ownership/path preflight; the owned native child inventories data.

    This path deliberately does not enumerate history, estimate verification
    cost, or certify a file. Native no-follow handles and full replay remain
    mandatory on every attempt, including a previously successful restart.
    """
    root=Path(root)
    if not root.is_absolute() or any(is_link(path) for path in (root,*root.parents)):
        raise ValueError('GG_NATIVE_PATH')
    if root.exists() and not root.is_dir():raise ValueError('GG_NATIVE_PATH')
    return {'schema':'gg.native.owned-recovery-budget.v1','bootstrap_seconds':12,
        'stall_seconds':START_MAX_SECONDS,'maximum_depth':START_INVENTORY_MAX_DEPTH,
        'basis':'OWNED_STREAMED_FULL_COLD_VERIFICATION_NOT_HISTORY_SIZE_ALLOWANCE'}


class OwnedRecoveryProgress:
    """One attempt's untrusted progress lease; completed work is not a proof."""
    LIMIT=2**63-1
    FIELDS=frozenset(('schema pid genesis_hash root attempt resource_profile phase '
        'work_done processed_height verified_through native_node_ready').split())

    def __init__(self,*,pid,genesis_hash,root,attempt,resource_profile,archive=False,clock=time.monotonic):
        self._clock=clock;self._expires=clock()+12;self._work=0;self._phase=-1;self._height=None;self._verified=None
        self._binding={'schema':'gg.native.owned-recovery-progress.v1','pid':pid,
            'genesis_hash':genesis_hash,'root':str(root),'attempt':attempt,
            'resource_profile':deepcopy(resource_profile),'native_node_ready':False}
        self._phases=('INVENTORY',)+(('ARCHIVE_AUDIT','ARCHIVE_RESTORE') if archive else ())+(
            'VERIFY_HISTORY','VERIFY_SDK_BINDINGS','SDK_START')

    def expired(self):return self._clock()>=self._expires

    def handshake(self):
        """Prepared listener acknowledgement has a short, finite deadline."""
        self._expires=min(self._expires,self._clock()+12)

    def ready(self):
        if self.expired() or self._phase!=self._phases.index('SDK_START') or self._height is None:
            raise ValueError('GG_OWNED_RECOVERY_INCOMPLETE')

    def accept(self,frame):
        if (not isinstance(frame,dict) or set(frame)!=self.FIELDS
                or not valid_readiness(frame.get('resource_profile'))
                or any(type(frame.get(key)) is not type(value) or frame[key]!=value
                       for key,value in self._binding.items())):
            raise ValueError('GG_OWNED_RECOVERY_FRAME')
        phase=frame['phase'];work=frame['work_done'];height=frame['processed_height'];verified=frame['verified_through']
        if phase not in self._phases:raise ValueError('GG_OWNED_RECOVERY_PHASE')
        index=self._phases.index(phase)
        if (index not in (self._phase,self._phase+1) or type(work) is not int or not self._work<=work<=self.LIMIT
                or any(value is not None and (type(value) is not int or not 0<=value<=self.LIMIT)
                       for value in (height,verified))
                or index==self._phase and height is not None and self._height is not None and height<self._height
                or verified is not None):
            raise ValueError('GG_OWNED_RECOVERY_PROGRESS')
        if self.expired():raise ValueError('GG_OWNED_RECOVERY_STALLED')
        if work>self._work:
            self._work=work;self._expires=self._clock()+START_MAX_SECONDS
        if height is not None or index!=self._phase:self._height=height
        self._phase=index;self._verified=verified
        return {'phase':phase,'work_done':str(work),'processed_height':str(self._height) if self._height is not None else None,
            'verified_through':str(verified) if verified is not None else None}


def native_pipe_creation_flags():
    """Detach Windows piped native children without console-host association.

    This selects only console creation flags. The caller still owns the exact
    child, private pipes, start gate and resource Job; no breakaway is enabled.
    """
    return subprocess.DETACHED_PROCESS if os.name=='nt' else 0


def native_start_budget(root,*,base_seconds=12):
    """Bound a cold start by owned file volume; this never verifies its data.

    Fresh/small stores keep the original budget. Large original-replay stores
    receive a finite allowance, without changing memory, readiness, ownership,
    signer intent or cancellation rules. No file contents are read here.
    """
    if (type(base_seconds) not in (int,float) or not math.isfinite(base_seconds)
            or not 0<base_seconds<=START_MAX_SECONDS):raise ValueError('GG_NATIVE_START_BUDGET')
    root=Path(root)
    if not root.is_absolute() or any(is_link(path) for path in (root,*root.parents)):
        raise ValueError('GG_NATIVE_PATH')
    total=entries=files=0
    if root.is_dir():
        pending=[(root,0)]
        while pending:
            directory,depth=pending.pop()
            if depth>START_INVENTORY_MAX_DEPTH:raise ValueError('GG_NATIVE_START_INVENTORY_LIMIT')
            if is_link(directory):raise ValueError('GG_NATIVE_PATH')
            with os.scandir(directory) as children:
                for child in children:
                    entries+=1
                    if entries>START_INVENTORY_MAX_ENTRIES:raise ValueError('GG_NATIVE_START_INVENTORY_LIMIT')
                    info=child.stat(follow_symlinks=False)
                    if (stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400):
                        raise ValueError('GG_NATIVE_PATH')
                    if stat.S_ISDIR(info.st_mode):pending.append((Path(child.path),depth+1))
                    elif stat.S_ISREG(info.st_mode):total+=info.st_size;files+=1
                    else:raise ValueError('GG_NATIVE_PATH')
    extra=max(0,total-START_BASE_STORE_BYTES)
    seconds=min(START_MAX_SECONDS,base_seconds+(extra+START_REPLAY_BYTES_PER_SECOND-1)//START_REPLAY_BYTES_PER_SECOND)
    return {'schema':'gg.native.start-budget.v1','seconds':seconds,'base_seconds':base_seconds,
            'maximum_seconds':START_MAX_SECONDS,'observed_native_file_bytes':total,'files':files,
            'inventory_entries':entries,'basis':'BOUNDED_LOCAL_FILE_VOLUME_NOT_VERIFICATION_OR_NETWORK_LIVENESS'}


class NativeStartReservation:
    def __init__(self,profile,process,*,resources=None):
        from backend.gg_consensus_profile import ValidatorProfile
        from backend.gg_observer_profile import ObserverProfile
        if not isinstance(profile,(ValidatorProfile,ObserverProfile)) or not isinstance(process,subprocess.Popen):
            raise ValueError('GG_NATIVE_START_OWNED_CONTEXT_REQUIRED')
        if process.stdin is None:raise ValueError('GG_NATIVE_START_PRIVATE_PIPE_REQUIRED')
        self._resources=resolve(resources)
        self._resource_identity=self._resources
        self._profile=profile;self._process=process;self._used=False;self._active=False
        self._input_started=False;self._fresh=None;self._thread=None;self._body=None;self._db=None;self._lease=None

    def __enter__(self):
        if self._used:raise ValueError('GG_NATIVE_START_RESERVATION_REUSED')
        self._used=True;profile=self._profile;profile._lock.acquire()
        try:
            if profile._closed or profile._failed or getattr(profile,'_native_pipe_closing',False) or profile._db is None or profile._lease is None:
                raise ValueError('GG_NATIVE_START_PROFILE_UNAVAILABLE')
            if self._process.poll() is not None:raise ValueError('GG_NATIVE_START_CHILD_NOT_RUNNING')
            self._db=profile._db;self._lease=profile._lease
            self._fresh=profile.claim_native_start()
            self._body=deepcopy(profile._body);self._thread=threading.get_ident();self._active=True
            return self
        except BaseException:
            profile._lock.release();raise

    def _check(self):
        if not self._active or self._thread!=threading.get_ident():raise ValueError('GG_NATIVE_START_RESERVATION_INACTIVE')

    @property
    def resources(self):return self._resources

    @property
    def fresh(self):self._check();return self._fresh

    def mark_input_started(self):
        """Monotonic boundary: call BEFORE the first write/flush attempt."""
        self._check()
        if self._resources is not self._resource_identity or resolve(self._resources) is not self._resource_identity:raise ValueError('GG_NATIVE_RESOURCE_PROFILE_CHANGED')
        if self._input_started:raise ValueError('GG_NATIVE_START_HANDOFF_ALREADY_STARTED')
        profile=self._profile
        # The reservation still holds this exact profile lock. Close intent is
        # published before a closer can wait on it, including a slow commit.
        if (profile._closed or profile._failed or getattr(profile,'_native_pipe_closing',False)
                or profile._db is not self._db or profile._lease!=self._lease
                or profile._body!=self._body or profile._body.get('fault')):
            raise ValueError('GG_NATIVE_START_PROFILE_UNAVAILABLE')
        self._input_started=True

    def __exit__(self,kind,error,traceback):
        self._check();profile=self._profile
        try:
            if self._fresh and not self._input_started:
                root=profile.root/'native'
                try:terminal=termination.process_terminal(self._process)
                except OSError:terminal=False
                if (not terminal or profile._closed or profile._failed
                        or profile._db is not self._db or profile._lease!=self._lease
                        or profile._body!=self._body or profile._body.get('certificate') is not None
                        or profile._body.get('fault') or root.exists()
                        or any(is_link(path) for path in (root,*root.parents))):
                    raise ValueError('GG_NATIVE_START_ABORT_NOT_PROVEN')
                profile._write({'native_started':False})
            if kind is None and not self._input_started:raise ValueError('GG_NATIVE_START_HANDOFF_REQUIRED')
        finally:
            self._active=False;self._body=None;profile._lock.release()
        return False
