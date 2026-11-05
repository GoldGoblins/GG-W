"""Explicit local native budgets; no host detection, authority or activation.

A frozen value is captured once for a concrete owned start. LOW preserves the
legacy launch budgets. New owned LOW starts also require attestation. SERVER is a finite local operator envelope,
never a genesis, peer claim, signing permission or benchmark override.
"""
from dataclasses import dataclass

SCHEMA="gg.native.resources.v1"
READY_SCHEMA="gg.native.resources-ready.v1"
MiB=1024**2
GiB=1024**3


@dataclass(frozen=True,slots=True)
class NativeResources:
    mode:str
    go_max_procs:int
    verify_workers:int
    go_heap_bytes:int
    process_memory_bytes:int
    virtual_bytes:int
    open_files:int
    owner_memory_bytes:int
    owner_cpu_basis_points:int
    maximum_native_children:int

    def __post_init__(self):
        values=(self.go_max_procs,self.verify_workers,self.go_heap_bytes,self.process_memory_bytes,
            self.virtual_bytes,self.open_files,self.owner_memory_bytes,self.owner_cpu_basis_points,
            self.maximum_native_children)
        if any(type(value) is not int for value in values):
            raise ValueError("GG_NATIVE_RESOURCE_PROFILE")
        if self.mode=="LOW":
            if values!=(2,8,256*MiB,512*MiB,8*GiB,1024,0,10000,6):
                raise ValueError("GG_NATIVE_RESOURCE_PROFILE")
            return
        if (self.mode!="SERVER" or not 1<=self.go_max_procs<=256
                or not 1<=self.verify_workers<=self.go_max_procs
                or not 96*MiB<=self.go_heap_bytes<=1<<40
                or not 512*MiB<=self.process_memory_bytes<=1<<40
                or self.go_heap_bytes>self.process_memory_bytes-64*MiB
                or not 8*GiB<=self.virtual_bytes<=1<<44
                or self.virtual_bytes<2*self.process_memory_bytes
                or not 1024<=self.open_files<=65536
                or not self.process_memory_bytes<=self.owner_memory_bytes<=1<<42
                or not 1<=self.owner_cpu_basis_points<=10000
                or not 1<=self.maximum_native_children<=6
                or any(value%MiB for value in (self.go_heap_bytes,self.process_memory_bytes,
                    self.virtual_bytes,self.owner_memory_bytes))):
            raise ValueError("GG_NATIVE_RESOURCE_PROFILE")

    def wire(self):
        return {"schema":SCHEMA,**{name:getattr(self,name) for name in self.__dataclass_fields__}}

    def sdk_rates(self):
        self.__post_init__()
        rate=self.go_max_procs*(64*MiB) if self.mode=="SERVER" else 5120000
        return {"sdk_send_bytes_per_second":rate,"sdk_recv_bytes_per_second":rate}

    def ready(self):
        return {"schema":READY_SCHEMA,"profile":self.wire(),"go_max_procs":self.go_max_procs,
            "go_heap_bytes":self.go_heap_bytes,"verify_workers":self.verify_workers,
            "effective_verify_workers":min(self.go_max_procs,self.verify_workers),
            "commit_wait_ms":10 if self.mode=="SERVER" else 100}

    def transport(self):
        cpu=self.go_max_procs
        server=self.mode=="SERVER"
        rate=min(1024,max(8,cpu*8)) if server else 8
        handlers=min(64,max(2,self.verify_workers)) if server else 2
        count=min(256,max(8,handlers*2)) if server else 8
        return {"schema":"gg.native.transport-budget.v1",
            "connections":min(64,max(8,cpu*2)) if server else 8,
            "requests_per_second":min(8192,max(32,cpu*64)) if server else 32,
            "requests_per_connection_second":rate,"handlers":handlers,"queue_count":count,
            "queue_bytes":count*65536,"client_interval_micros":(1000000+rate-1)//rate if server else 135000,
            "request_seconds":20,"request_bytes":65536,"response_bytes":256*1024+4096}

    def environment(self):
        if self.mode=="LOW":return {"GOMAXPROCS":"2","GOMEMLIMIT":"256MiB"}
        return {"GOMAXPROCS":str(self.go_max_procs),"GOMEMLIMIT":str(self.go_heap_bytes)+"B"}


LOW=NativeResources("LOW",2,8,256*MiB,512*MiB,8*GiB,1024,0,10000,6)


def resolve(value=None):
    if value is None:return LOW
    if type(value) is NativeResources:
        # Constructor validation is mandatory even for a caller-supplied value.
        value.__post_init__()
        return value
    if type(value) is not dict:raise ValueError("GG_NATIVE_RESOURCE_PROFILE")
    if value=={"schema":SCHEMA,"mode":"LOW"}:return LOW
    expected=set(NativeResources.__dataclass_fields__)|{"schema"}
    if set(value)!=expected or value.get("schema")!=SCHEMA or value.get("mode") not in ("LOW","SERVER"):
        raise ValueError("GG_NATIVE_RESOURCE_PROFILE")
    return NativeResources(**{name:value[name] for name in NativeResources.__dataclass_fields__})


def configured(node):
    settings=getattr(node,"settings",None)
    if settings is not None:
        if type(settings) is not dict:raise ValueError("GG_NATIVE_RESOURCE_PROFILE")
        return resolve(settings.get("resources"))
    return resolve(getattr(node,"_resource_profile",None))


def capture(node):
    profile=configured(node)
    node._native_resource_attempt=profile
    return profile


def current(node):
    profile=configured(node)
    captured=getattr(node,"_native_resource_attempt",None)
    if captured is not None and resolve(captured)!=profile:
        raise ValueError("GG_NATIVE_RESOURCE_PROFILE_CHANGED")
    return profile if captured is None else captured


def bootstrap(node,value):
    profile=current(node);wire=profile.wire()
    if "resources" in value and value["resources"]!=wire:
        raise ValueError("GG_NATIVE_RESOURCE_PROFILE_CHANGED")
    value["resources"]=wire
    return value


def valid_sdk_rates(profile,value):
    try:
        expected=resolve(profile).sdk_rates()
    except (ValueError,TypeError):return False
    return (type(value) is dict and set(value)==set(expected)
        and all(type(value[name]) is int and value[name]==expected[name] for name in expected))


def readiness(node,value):
    profile=current(node)
    value["resources"]=profile.ready()
    value.update(profile.sdk_rates())
    return value



def _kernel_public(lease):
    if lease is None:return None
    facts=lease.facts
    names=("provider","verified","memory_bytes","data_bytes","virtual_address_bytes","open_files",
        "cpu_seconds","active_process_limit","kill_on_close","descendant_process_limit_enforced",
        "limits_applied_before_exec","no_new_privileges","memory_metric")
    result={name:facts[name] for name in names if name in facts}
    group=facts.get("group")
    if type(group) is dict:
        keys=("provider","verified","cpu_rate_percent","maximum_native_children","lifetime_cpu_seconds",
            "owner_aggregate_memory_bytes","owner_aggregate_memory_enforced","child_count_enforcement",
            "descendant_process_limit_enforced","closed")
        result["group"]={name:group[name] for name in keys if name in group}
    return result


def _observation(profile,expected,actual,lease,running,scope,*,local_limits=None,peer_limits=None,sdk_rates=None):
    from copy import deepcopy
    applied=(deepcopy(actual) if running and profile==expected and valid_readiness(actual)
        and actual["profile"]==expected.wire() else None)
    sdk_valid=valid_sdk_rates(expected,sdk_rates)
    if scope=="OWNED_SDK_NODE" and not sdk_valid:applied=None
    kernel=_kernel_public(lease)
    state=("PROFILE_CHANGED" if profile!=expected else "STOPPED" if not running else
        "AWAITING_NATIVE_ACK" if applied is None else "APPLIED" if kernel and kernel.get("verified") else "KERNEL_UNVERIFIED")
    result={"schema":"gg.native.resource-observation.v1","scope":scope,"state":state,
        "requested":profile.wire(),"captured":expected.wire(),"applied":applied,"kernel":kernel,
        "native_attested":applied is not None,"kernel_and_go_are_separate_facts":True,
        "performance_or_capacity_asserted":False}
    if scope=="OWNED_SDK_NODE":
        result["requested_sdk_rates"]=profile.sdk_rates()
        result["applied_sdk_rates"]=deepcopy(sdk_rates) if applied is not None else None
    if scope=="AUTHENTICATED_TRANSPORT_ONLY":
        result["requested_transport_budget"]=profile.transport()
        result["applied_transport_budget"]=deepcopy(local_limits) if applied is not None and local_limits==expected.transport() else None
        result["authenticated_peer_receive_limits"]=deepcopy(peer_limits) if applied is not None else None
        result["full_sdk_node_running"]=False
    return result


def observation(node,*,scope="OWNED_SDK_NODE"):
    try:
        profile=configured(node)
        captured=resolve(getattr(node,"_native_resource_attempt",profile))
    except ValueError:
        return {"schema":"gg.native.resource-observation.v1","scope":scope,"state":"INVALID_PROFILE",
            "requested":None,"captured":None,"applied":None,"kernel":None,"native_attested":False,
            "kernel_and_go_are_separate_facts":True,"performance_or_capacity_asserted":False}
    epoch=getattr(node,"_node",{})
    process=epoch.get("process")
    ready=epoch.get("_ready")
    running=process is not None and process.poll() is None
    actual=ready.get("resources") if type(ready) is dict and ready.get("process") is process else None
    sdk_rates=ready.get("sdk_rates") if type(ready) is dict and ready.get("process") is process else None
    return _observation(profile,captured,actual,getattr(node,"_lease",None),running,scope,sdk_rates=sdk_rates)


def pipe_observation(pipe,*,node=None):
    ready=getattr(pipe,"ready",{})
    captured=resolve(pipe._resources)
    try:requested=captured if node is None else configured(node)
    except ValueError:return observation(node,scope="AUTHENTICATED_TRANSPORT_ONLY")
    running=pipe.alive()
    if node is not None:
        owners=getattr(pipe,"_protected_owners",())
        running=(running and len(owners)==2 and owners[0] is node.owner and owners[1] is node.profile
            and node._transport is pipe and node._node.get("process") is pipe.process and not node._owner_stopped())
    return _observation(requested,captured,ready.get("resources"),getattr(pipe,"_lease",None),
        running,"AUTHENTICATED_TRANSPORT_ONLY",local_limits=ready.get("local_limits"),peer_limits=ready.get("limits"))

def codec_limits(node,*,transport=None):
    """Merge hook for the separate codec lane; returns facts, never refills.

    The caller binds one RefillBudget/workspace set per owned node+relay epoch.
    LOW remains 8 operations and two 1 MiB workspaces. SERVER is bounded by
    the attested local profile and, for clients, authenticated peer receives.
    """
    profile=current(node)
    observed=(node if transport is None else transport).resource_observation()
    applied=observed.get("applied")
    if (observed.get("state")!="APPLIED" or observed.get("native_attested") is not True or not valid_readiness(applied)
            or applied["profile"]!=profile.wire()):
        raise ValueError("GG_NATIVE_RESOURCE_ACK_REQUIRED")
    budget=profile.transport()
    rate=budget["requests_per_connection_second"]
    peer=observed.get("authenticated_peer_receive_limits")
    if type(peer) is dict:
        # This field already passed the private-pipe strict limit decoder.
        rate=min(rate,peer["requests_per_connection_second"])
    unit=32768+4*((32768+2)//3)+2048
    return {"schema":"gg.native.codec-budget.v1","profile":profile.wire(),"period_seconds":1,
        "byte_burst":rate*unit,"work_burst":rate,"maximum_actors":128,
        "workspaces":2 if profile.mode=="LOW" else min(64,max(2,profile.verify_workers)),
        "workspace_bytes":1024*1024}

def valid_readiness(value):
    if type(value) is not dict:return False
    try:
        profile=resolve(value.get("profile"))
        expected=profile.ready()
        return (set(value)==set(expected) and type(value.get("profile")) is dict
            and all(type(value[name]) is int for name in ("go_max_procs","go_heap_bytes",
                "verify_workers","effective_verify_workers","commit_wait_ms"))
            and value==expected)
    except (KeyError,ValueError,TypeError):return False


def matches(node):
    try:
        current(node)
        return True
    except ValueError:return False
