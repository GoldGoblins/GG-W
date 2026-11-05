"""Owned persistent SDK process groups; no lifetime CPU-expiration policy.

Windows enforces one aggregate CPU-rate budget for an actual node owner's SDK
children. LOW keeps its 512MiB leaf; SERVER uses its explicit finite leaf and
aggregate memory envelope. Every leaf keeps one-process/kill-on-close limits.
The parent is never assigned to these jobs. Linux/Android verify inherited hard
rlimits, with an application-owned child registry; CPU-rate/descendant limits
remain unavailable there. These mechanisms are not a security sandbox.
"""
import ctypes
from ctypes import wintypes
import math
import os
import subprocess
import threading
import time
import weakref

from backend import gg_testnet_process as limits
from backend import gg_posix_native as posix
from backend import gg_process_termination as termination
from backend import gg_native_resources as resource_profiles

MAX_NATIVE_CHILDREN=6  # four committee slots plus this owner's two observer slots
DEFAULT_CPU_PERCENT=100.0
_CPU_RATE_INFORMATION=15
_CPU_ENABLE=0x1
_CPU_HARD_CAP=0x4
_GROUP_FLAGS=limits._KILL_ON_CLOSE|limits._ACTIVE_PROCESS
_registry_lock=threading.RLock()
_groups=weakref.WeakKeyDictionary()
_ended=weakref.WeakSet()
_attached=weakref.WeakKeyDictionary()


class _AlreadyAttached(ValueError):pass


class _CpuRate(ctypes.Structure):
    _fields_=[('flags',wintypes.DWORD),('rate',wintypes.DWORD)]


def _percent(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not .01<=value<=100:
        raise ValueError('GG_NATIVE_CPU_RATE')
    return round(float(value)*100)


def _owner_open(owner):
    from backend.gg_node_store import NodeProfile
    from backend.gg_lan_dag import LanDagPeer
    if isinstance(owner,NodeProfile):
        return not owner._closed and not owner._failed and owner._lease is not None and owner._db is not None
    if isinstance(owner,LanDagPeer):
        return owner._profile is None and not owner._cancel.is_set() and owner._bundle is not None
    return False


class _Group:
    def __init__(self,cpu_percent,resources=None):
        self._resources=resource_profiles.resolve(resources)
        self._flags=_GROUP_FLAGS|(0x200 if self._resources.owner_memory_bytes else 0)
        self._lock=threading.RLock();self._kernel=None;self._job=None;self._closed=False;self._rate=_percent(cpu_percent);self._children=set()
        if os.name!='nt':return
        self._kernel=limits._kernel();job=self._kernel.CreateJobObjectW(None,None)
        if not job:raise RuntimeError('GG_NATIVE_GROUP_CREATE_FAILED')
        self._job=job
        try:
            settings=limits._ExtendedLimits();settings.basic.flags=self._flags;settings.basic.active_processes=self._resources.maximum_native_children
            settings.job_memory=self._resources.owner_memory_bytes
            if not self._kernel.SetInformationJobObject(job,9,ctypes.byref(settings),ctypes.sizeof(settings)):
                raise RuntimeError('GG_NATIVE_GROUP_LIMIT_FAILED')
            self._set_cpu(self._rate)
            actual=limits._ExtendedLimits()
            if (not self._kernel.QueryInformationJobObject(job,9,ctypes.byref(actual),ctypes.sizeof(actual),None)
                    or actual.basic.flags & self._flags!=self._flags or actual.basic.flags & (limits._PROCESS_TIME|0x4)
                    or actual.basic.active_processes!=self._resources.maximum_native_children
                    or actual.job_memory!=self._resources.owner_memory_bytes):raise RuntimeError('GG_NATIVE_GROUP_LIMIT_MISMATCH')
        except BaseException:
            self.close();raise

    def _set_cpu(self,rate):
        requested=_CpuRate(_CPU_ENABLE|_CPU_HARD_CAP,rate)
        if not self._kernel.SetInformationJobObject(self._job,_CPU_RATE_INFORMATION,ctypes.byref(requested),ctypes.sizeof(requested)):
            raise RuntimeError('GG_NATIVE_CPU_RATE_SET_FAILED')
        actual=_CpuRate()
        if (not self._kernel.QueryInformationJobObject(self._job,_CPU_RATE_INFORMATION,ctypes.byref(actual),ctypes.sizeof(actual),None)
                or actual.flags!=requested.flags or actual.rate!=rate):raise RuntimeError('GG_NATIVE_CPU_RATE_QUERY_FAILED')
        self._rate=rate

    def set_cpu(self,percent):
        rate=_percent(percent)
        if rate>self._resources.owner_cpu_basis_points:raise ValueError('GG_NATIVE_CPU_RATE_PROFILE_LIMIT')
        with self._lock:
            if self._closed:raise ValueError('GG_NATIVE_GROUP_CLOSED')
            if self._kernel is None:raise ValueError('GG_NATIVE_CPU_RATE_UNAVAILABLE')
            else:
                try:self._set_cpu(rate)
                except BaseException:
                    self.close();raise

    def attach(self,process):
        with self._lock:
            if self._closed:raise ValueError('GG_NATIVE_GROUP_CLOSED')
            self._children={child for child in self._children if not termination.process_terminal(child)}
            if self._kernel is None:
                if process in self._children:raise ValueError('GG_NATIVE_CHILD_ALREADY_ATTACHED')
                if len(self._children)>=self._resources.maximum_native_children:raise ValueError('GG_NATIVE_CHILD_REGISTRY_FULL')
                if process.poll() is not None:raise ValueError('GG_NATIVE_CHILD_NOT_RUNNING')
                self._children.add(process);return
            child=wintypes.HANDLE();kernel=self._kernel;current=kernel.GetCurrentProcess()
            try:
                if not kernel.DuplicateHandle(current,wintypes.HANDLE(int(process._handle)),current,ctypes.byref(child),0,False,0x2):
                    raise RuntimeError('GG_NATIVE_GROUP_CHILD_HANDLE')
                if kernel.GetProcessId(child)!=process.pid:raise RuntimeError('GG_NATIVE_GROUP_CHILD_IDENTITY')
                if not kernel.AssignProcessToJobObject(self._job,child):raise RuntimeError('GG_NATIVE_GROUP_ASSIGN_FAILED')
                # Assignment already transferred lifetime responsibility to
                # this group. Keep its exact owner even if readback now fails.
                self._children.add(process)
                member=wintypes.BOOL()
                if not kernel.IsProcessInJob(child,self._job,ctypes.byref(member)) or not member.value:
                    raise RuntimeError('GG_NATIVE_GROUP_MEMBERSHIP_FAILED')
            finally:
                if child.value:kernel.CloseHandle(child)

    def has_live_children(self):
        with self._lock:
            self._children={child for child in self._children if not termination.process_terminal(child)}
            return bool(self._children)

    def facts(self):
        with self._lock:return {'provider':'WINDOWS_JOB_OBJECT' if self._kernel is not None else 'OWNED_PROCESS_REGISTRY',
            'verified':not self._closed,'cpu_rate_percent':self._rate/100 if self._kernel is not None and not self._closed else None,
            'cpu_rate_scope':'THIS_OWNED_NODE_NATIVE_SDK_CHILDREN','lifetime_cpu_seconds':None,
            'maximum_native_children':self._resources.maximum_native_children,
            'resource_profile':self._resources.wire(),
            'owner_aggregate_memory_bytes':self._resources.owner_memory_bytes if self._kernel is not None and self._resources.owner_memory_bytes else None,
            'owner_aggregate_memory_enforced':self._kernel is not None and bool(self._resources.owner_memory_bytes),'child_count_enforcement':'KERNEL_JOB' if self._kernel is not None else 'APPLICATION_REGISTRY',
            'descendant_process_limit_enforced':self._kernel is not None,'closed':self._closed}

    def close(self):
        with self._lock:
            self._closed=True
            if self._job is not None:
                if not self._kernel.CloseHandle(self._job):raise RuntimeError('GG_NATIVE_GROUP_CLOSE_FAILED')
                self._job=None
            children=tuple(self._children)
        # Signal every exact owned child before waiting, with one total deadline.
        # Never enumerate a UID, PID range, unrelated process, or reused group ID.
        for process in children:
            try:
                if not termination.process_terminal(process):process.kill()
            except OSError:pass
        deadline=time.monotonic()+3
        for process in children:
            try:termination.wait_process_terminal(process,max(0,deadline-time.monotonic()))
            except (OSError,subprocess.TimeoutExpired):pass
        try:terminal=all(termination.process_terminal(process) for process in children)
        except OSError:terminal=False
        if not terminal:raise RuntimeError('GG_NATIVE_GROUP_STOP_FAILED')
        with self._lock:self._children.difference_update(children)

    def __del__(self):
        try:self.close()
        except Exception:pass


class NativeChildLease:
    def __init__(self,leaf,group,process):self._leaf=leaf;self._group=group;self._process=process;self._closed=False
    @property
    def facts(self):
        facts=self._leaf.facts
        return {**facts,'verified':facts['verified'] and not self._closed and self._process.poll() is None,
            'mode':'OWNED_PERSISTENT_NATIVE','group':self._group.facts(),'lease_closed':self._closed,
            'parent_job_limits_may_be_stricter':True,'inherited_limits_may_be_stricter':True}
    @property
    def closed(self):return self._closed
    def close(self):self._leaf.close();self._closed=True


def contain_owned_native(process,owner,*,resources=None):
    explicit=resources is not None
    selected=resource_profiles.resolve(resources)
    if (not isinstance(process,subprocess.Popen) or type(process.pid) is not int or process.pid==os.getpid()
            or process.pid<=0):raise ValueError('GG_NATIVE_OWNED_CHILD_REQUIRED')
    if process.poll() is not None:raise ValueError('GG_NATIVE_CHILD_NOT_RUNNING')
    leaf=None
    try:
        with _registry_lock:
            if process in _attached:raise _AlreadyAttached('GG_NATIVE_CHILD_ALREADY_ATTACHED')
        if os.name!='nt':
            # The finite kernel-readback wait must not hold the owner registry.
            leaf=posix.contain(process,cancelled=lambda:not _owner_open(owner) or owner_ended(owner),resources=selected)
        with _registry_lock:
            if process in _attached:raise _AlreadyAttached('GG_NATIVE_CHILD_ALREADY_ATTACHED')
            if not _owner_open(owner) or owner in _ended:raise ValueError('GG_NATIVE_OWNER_CLOSED_OR_UNOWNED')
            group=_groups.get(owner)
            if group is not None and explicit and group._resources!=selected:
                # Changing an owner envelope never silently widens existing
                # children. Only an already terminal group can be replaced.
                if group.has_live_children():raise ValueError('GG_NATIVE_OWNER_RESOURCE_PROFILE_CHANGED')
                group.close();_groups.pop(owner,None);group=None
            if group is None:
                group=_Group(selected.owner_cpu_basis_points/100,selected);_groups[owner]=group
            group.attach(process)
            if leaf is None:leaf=limits._persistent_child_lease(process,resources=selected)
            _attached[process]=weakref.ref(group)
            return NativeChildLease(leaf,group,process)
    except _AlreadyAttached:raise
    except BaseException:
        limits._stop_owned(process);raise


def set_owner_cpu_percent(owner,percent):
    _percent(percent)
    with _registry_lock:
        if not _owner_open(owner) or owner in _ended:raise ValueError('GG_NATIVE_OWNER_CLOSED_OR_UNOWNED')
        group=_groups.get(owner)
        if group is None:raise ValueError('GG_NATIVE_GROUP_NOT_STARTED')
        group.set_cpu(percent);return group.facts()


def close_owner(owner):
    """Called after owner cancellation; never targets a searched PID."""
    from backend.gg_native_pipe_lifecycle import fence_owner_close
    with _registry_lock:
        _ended.add(owner);group=_groups.get(owner)
    # Cancellation is published before any protected DB-lock wait, as before.
    if getattr(owner,"_lock",None) is not None:owner._native_pipe_closing=True
    if group is not None:
        group.close()
        with _registry_lock:
            if _groups.get(owner) is group:_groups.pop(owner)
    fence_owner_close(owner)


def owner_ended(owner):
    with _registry_lock:return owner in _ended
