"""Fixed ownership slots for finite native pipes and failed constructions.

These slots grant no process/profile authority. Callers still perform all
original identity, containment, pin, signature and journal checks. There is no
PID lookup, growing registry, worker, retry loop or added process allowance.
"""
from contextlib import contextmanager
import atexit
import subprocess
import threading
import time

from backend import gg_process_termination as termination


class _OwnedTransfer:
    def __init__(self,owners):self.owners=tuple(owners)


class NativePipeStopPending(RuntimeError):
    def __init__(self,owned_transfer=None):
        super().__init__('GG_NATIVE_PIPE_STOP_PENDING');self.owned_transfer=owned_transfer

    def transferred(self,*owners):
        expected=[]
        for owner in owners:
            if owner is not None and not any(value is owner for value in expected):expected.append(owner)
        transfer=self.owned_transfer
        return type(transfer) is _OwnedTransfer and bool(expected) and len(expected)==len(transfer.owners) and all(a is b for a,b in zip(expected,transfer.owners))


class _FiniteSlot:
    def __init__(self,seconds):
        self.seconds=seconds;self._lock=threading.RLock();self._active=False
        self.process=None;self.lease=None;self.owners=();self._closers=()
        self._blocked=False
        self._terminal=False;self._lease_done=False;self._pipe_index=0
        self._completed_closers=()

    def retains(self,owner):
        return self._blocked and any(value is owner for value in self.owners)

    def defer_close(self,*owners):
        # Only existing exact owners may transfer their local close duty.
        if not self._lock.acquire(blocking=False):raise NativePipeStopPending()
        try:
            if not self._blocked:raise RuntimeError('GG_NATIVE_PIPE_NO_PENDING_OWNER')
            for owner in owners:
                if owner is not None and not any(value is owner for value in self.owners):
                    raise RuntimeError('GG_NATIVE_PIPE_FOREIGN_OWNER')
            values=list(self._closers)
            for owner in owners:
                if owner is not None and not any(value is owner for value in values):values.append(owner)
            if len(values)>3:raise RuntimeError('GG_NATIVE_PIPE_OWNER_LIMIT')
            self._closers=tuple(values)
        finally:self._lock.release()

    def _finish(self,deadline=None):
        process=self.process
        if process is not None and not self._terminal:
            until=time.monotonic()+self.seconds if deadline is None else deadline
            try:
                if not termination.process_terminal(process):process.kill()
                termination.wait_process_terminal(process,max(0,until-time.monotonic()))
            except (OSError,subprocess.TimeoutExpired):pass
            try:terminal=termination.process_terminal(process)
            except OSError:terminal=False
            if not terminal:raise NativePipeStopPending()
            self._terminal=True
        if self.lease is not None and not self._lease_done:
            try:self.lease.close()
            except (OSError,RuntimeError):raise NativePipeStopPending() from None
            self._lease_done=True
        if process is not None:
            try:
                streams=(process.stdin,process.stdout)
                while self._pipe_index<len(streams):
                    pipe=streams[self._pipe_index]
                    if pipe is not None:pipe.close()
                    self._pipe_index+=1
            except (OSError,ValueError):raise NativePipeStopPending() from None
        # Only after exact terminal/leaf/pipe proof may protected close run.
        self._blocked=False
        while self._closers:
            owner=self._closers[0]
            owner.close()  # Retain the duty/ref if its close raises.
            self._closers=self._closers[1:]
            self._completed_closers=(*self._completed_closers,owner)
        self.process=None;self.lease=None;self.owners=()

    def retire(self):
        if not self._lock.acquire(blocking=False):raise ValueError('GG_NATIVE_PIPE_BUSY')
        try:
            if self._active:raise ValueError('GG_NATIVE_PIPE_BUSY')
            self._finish()
        finally:self._lock.release()

    def retire_owner(self,owner):
        if not self._lock.acquire(blocking=False):raise NativePipeStopPending()
        try:
            if not self.retains(owner):return
            if self._active:raise NativePipeStopPending()
            self._finish()
        finally:self._lock.release()

    def _bind(self,owners):
        # Publish under the same profile lock used by its close fence. Acquiring
        # only nonblocking prevents slot/profile lock inversion on retirement.
        locks=[]
        try:
            for owner in sorted(owners,key=id):
                lock=getattr(owner,'_lock',None)
                if lock is not None:
                    if not lock.acquire(blocking=False):raise ValueError('GG_NATIVE_PIPE_OWNER_BUSY')
                    locks.append(lock)
            if any(getattr(owner,'_closed',False) or getattr(owner,'_failed',False)
                    or getattr(owner,'_native_pipe_closing',False) for owner in owners):
                raise ValueError('GG_NATIVE_PIPE_OWNER_CLOSED')
            self.owners=tuple(owners);self._active=True;self._blocked=True
        finally:
            for lock in reversed(locks):lock.release()

    @contextmanager
    def operation(self,owners=(),*,deadline=None,close_on_pending=()):
        if not self._lock.acquire(blocking=False):raise ValueError('GG_NATIVE_PIPE_BUSY')
        entered=False
        try:
            if self._active:raise ValueError('GG_NATIVE_PIPE_BUSY')
            self._finish()  # A previous exact owner retires before replacement.
            unique=[]
            for owner in owners:
                if owner is not None and not any(value is owner for value in unique):unique.append(owner)
            if len(unique)>3:raise ValueError('GG_NATIVE_PIPE_OWNER_LIMIT')
            duties=[]
            for owner in close_on_pending:
                if owner is not None and not any(value is owner for value in duties):duties.append(owner)
            if any(not any(value is owner for value in unique) for owner in duties):raise ValueError('GG_NATIVE_PIPE_FOREIGN_OWNER')
            self._terminal=False;self._lease_done=False;self._pipe_index=0
            self._completed_closers=()
            self._bind(unique);entered=True
            try:yield self
            finally:
                self._active=False
                try:self._finish(deadline)
                except BaseException:
                    if duties and self.owners:
                        # Commit local close duties before the exact operation
                        # lock is released. Exception carries a stable transfer
                        # receipt even if another caller retires/replaces us.
                        queued=list(self._closers)
                        for duty in duties:
                            if not any(value is duty for value in (*queued,*self._completed_closers)):queued.append(duty)
                        self._closers=tuple(queued)
                        raise NativePipeStopPending(_OwnedTransfer(duties)) from None
                    raise
        finally:
            # Never erase retained fields after a failed _finish.
            self._lock.release()

    def attach(self,process):
        if not self._active or self.process is not None:raise RuntimeError('GG_NATIVE_PIPE_OWNERSHIP_ORDER')
        self.process=process  # Publish before containment or any pipe handoff.

    def run(self,args,*,input,timeout,**options):
        # subprocess.run's implicit context-manager wait can trust a cached exit.
        # The original six-second request deadline also bounds this cleanup.
        deadline=time.monotonic()+timeout
        with self.operation(deadline=deadline):
            process=subprocess.Popen(args,stdin=subprocess.PIPE,**options);self.attach(process)
            output,error=process.communicate(input=input,timeout=max(0,deadline-time.monotonic()))
        return subprocess.CompletedProcess(args,process.returncode,output,error)


class _ConstructionSlot:
    def __init__(self):
        self._lock=threading.RLock();self._active=False;self.owner=None
        self.owners=();self._blocked=False

    def retains(self,owner):return self._blocked and any(value is owner for value in self.owners)

    def _retire(self):
        if self.owner is not None:
            self.owner.close()  # Existing exact close method/budget remains authoritative.
            self.owner=None
        self.owners=();self._blocked=False

    def retire(self):
        if not self._lock.acquire(blocking=False):raise NativePipeStopPending()
        try:
            if self._active:raise NativePipeStopPending()
            self._retire()
        finally:self._lock.release()

    def retire_owner(self,owner):
        if not self._lock.acquire(blocking=False):raise NativePipeStopPending()
        try:
            if not self.retains(owner):return
            if self._active:raise NativePipeStopPending()
            self._retire()
        finally:self._lock.release()

    @contextmanager
    def construction(self,owners=()):
        if not self._lock.acquire(blocking=False):raise ValueError('GG_NATIVE_PIPE_CONSTRUCTION_BUSY')
        entered=False
        try:
            if self._active:raise ValueError('GG_NATIVE_PIPE_CONSTRUCTION_BUSY')
            try:self._retire()
            except BaseException:raise NativePipeStopPending() from None
            unique=[]
            for owner in owners:
                if owner is not None and not any(value is owner for value in unique):unique.append(owner)
            if len(unique)>3:raise ValueError('GG_NATIVE_PIPE_OWNER_LIMIT')
            _FiniteSlot._bind(self,unique);entered=True
            try:yield self
            except BaseException:
                try:self._retire()
                except BaseException:raise NativePipeStopPending() from None
                raise
            else:
                self.owner=None;self.owners=();self._blocked=False
            finally:self._active=False
        finally:
            self._lock.release()

    def attach(self,owner):
        if not self._active or self.owner is not None:raise RuntimeError('GG_NATIVE_PIPE_OWNERSHIP_ORDER')
        self.owner=owner


# Fixed maximum membership. Five finite operations and four pre-publication
# constructor owners; there is no dynamically growing global collection.
LEGACY_VERIFY=_FiniteSlot(6)
GENESIS_VALIDATE=_FiniteSlot(6)
DAG_VERIFY=_FiniteSlot(5)
FINANCIAL_HISTORY=_FiniteSlot(3)
INDEX_TRANSITION=_FiniteSlot(5)
COMMITTEE_STREAM_INIT=_ConstructionSlot()
COMMITTEE_CONTEXT_INIT=_ConstructionSlot()
TRANSPORT_PIPE_INIT=_ConstructionSlot()
TRANSPORT_SERVER_INIT=_ConstructionSlot()
_FINITE_SLOTS=(LEGACY_VERIFY,GENESIS_VALIDATE,DAG_VERIFY,FINANCIAL_HISTORY,INDEX_TRANSITION)
_CONSTRUCTION_SLOTS=(COMMITTEE_STREAM_INIT,COMMITTEE_CONTEXT_INIT,TRANSPORT_PIPE_INIT,TRANSPORT_SERVER_INIT)


def require_owner_released(owner):
    # Owners are immutable tuple snapshots. Do not acquire a slot lock while
    # holding a protected profile lock: retirement may itself close that profile.
    if any(slot.retains(owner) for slot in (*_FINITE_SLOTS,*_CONSTRUCTION_SLOTS)):raise NativePipeStopPending()


def bind_owned_pipe(resource,owners):
    """Attach only exact caller-supplied protected objects, before key handoff."""
    from backend.gg_native_process_policy import MAX_NATIVE_CHILDREN
    locks=[];updates=[]
    try:
        for owner in sorted(owners,key=id):
            lock=owner._lock
            if not lock.acquire(blocking=False):raise ValueError('GG_NATIVE_PIPE_OWNER_BUSY')
            locks.append(lock)
        for owner in owners:
            if owner._closed or owner._failed or getattr(owner,'_native_pipe_closing',False):raise NativePipeStopPending()
            children=tuple(value for value in getattr(owner,'_native_pipe_resources',()) if not value._resource_retired)
            if len(children)>=MAX_NATIVE_CHILDREN:raise ValueError('GG_NATIVE_PIPE_OWNER_LIMIT')
            updates.append((owner,children+(resource,)))
        for owner,children in updates:owner._native_pipe_resources=children
    finally:
        for lock in reversed(locks):lock.release()


def release_owned_pipe(resource):
    # A busy profile may retain one terminal descriptor until its next fence or
    # bind; it is bounded and never treated as a live process. No lock inversion.
    for owner in getattr(resource,'_protected_owners',()):
        if not owner._lock.acquire(blocking=False):continue
        try:owner._native_pipe_resources=tuple(value for value in getattr(owner,'_native_pipe_resources',()) if value is not resource)
        finally:owner._lock.release()
    resource._protected_owners=()


def fence_owner_close(owner):
    lock=getattr(owner,'_lock',None)
    if lock is None:
        require_owner_released(owner)
        return
    # A later explicit close can retire a previously failed operation. An
    # operation still executing is never displaced, and local finally blocks
    # transfer their close duty instead of adding a second shutdown window.
    owner._native_pipe_closing=True
    # Signaling a known relay does not acquire its handler/work lock.
    children=getattr(owner,'_native_pipe_resources',())
    for child in children:
        if not child._resource_retired:child.request_stop()
    for slot in (*_FINITE_SLOTS,*_CONSTRUCTION_SLOTS):
        if slot.retains(owner):
            slot.retire_owner(owner)
    for child in children:
        if not child._resource_retired:child.close()
    if lock is not None:lock.acquire()
    try:
        owner._native_pipe_closing=True
        require_owner_released(owner)
        children=getattr(owner,'_native_pipe_resources',())
        if any(not child._resource_retired for child in children):raise NativePipeStopPending()
        owner._native_pipe_resources=()
    finally:
        if lock is not None:lock.release()


def close_all():
    pending=False
    for slot in (*_FINITE_SLOTS,*_CONSTRUCTION_SLOTS):
        try:slot.retire()
        except Exception:pending=True
    if pending:raise NativePipeStopPending()


atexit.register(close_all)
