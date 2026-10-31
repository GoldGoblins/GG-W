"""Local DAG workload budgets and honest bottleneck estimates.

Importing this module measures nothing and starts no work. Capacities must be
measured for the selected DAG workload and expressed in the same TX/s unit;
percentages of unlike resources are never compared directly.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
import threading
import time
from copy import deepcopy
from contextlib import contextmanager

RESOURCES = ('cpu', 'gpu', 'ram', 'network')


def _percent(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('GG_DAG_RESOURCE_PERCENT')
    return float(value)


@dataclass(frozen=True)
class ResourceBudget:
    """Overall is a fraction of the bottleneck; individual values are ceilings."""

    overall: float = 100
    cpu: float = 100
    gpu: float = 100
    ram: float = 100
    network: float = 100

    def __post_init__(self):
        for name in ('overall', *RESOURCES):
            object.__setattr__(self, name, _percent(getattr(self, name)))

    @classmethod
    def from_public(cls, value):
        if not isinstance(value, dict) or set(value) - {'overall', *RESOURCES}:
            raise ValueError('GG_DAG_RESOURCE_BUDGET')
        return cls(**value)

    def public(self):
        return {name: getattr(self, name) for name in ('overall', *RESOURCES)}


def bottleneck_plan(capacities, budget=None, *, active=('cpu', 'ram', 'network'),
                    transactions_per_block=None, memory_required_bytes=None,
                    memory_available_bytes=None, memory_headroom_bytes=None):
    """Estimate one workload's rate without inventing unmeasured capacities.

    RAM bandwidth belongs in capacities; RAM space is a separate fit check.
    Unused GPU capacity is excluded. An active unmeasured stage makes the
    estimate unavailable. This is an estimate, never an acknowledged TX rate.
    """
    if not isinstance(capacities, dict) or set(capacities) - set(RESOURCES):
        raise ValueError('GG_DAG_HARDWARE_CAPACITIES')
    if not isinstance(active, (tuple, list)) or not active or len(set(active)) != len(active) or any(name not in RESOURCES for name in active):
        raise ValueError('GG_DAG_HARDWARE_ACTIVE')
    if budget is None:
        budget = ResourceBudget()
    if not isinstance(budget, ResourceBudget):
        raise ValueError('GG_DAG_RESOURCE_BUDGET')
    if transactions_per_block is not None and (type(transactions_per_block) is not int or transactions_per_block < 1):
        raise ValueError('GG_DAG_TX_LIMIT')
    for size in (memory_required_bytes, memory_available_bytes, memory_headroom_bytes):
        if size is not None and (type(size) is not int or size < 0):
            raise ValueError('GG_DAG_RESOURCE_MEMORY')

    rows = {}
    unknown = []
    for name in RESOURCES:
        capacity = capacities.get(name)
        if capacity is not None and (type(capacity) not in (int, float) or not math.isfinite(capacity) or capacity < 0):
            raise ValueError('GG_DAG_HARDWARE_CAPACITY')
        used = name in active
        if used and capacity is None:
            unknown.append(name)
        ceiling = capacity * getattr(budget, name) / 100 if used and capacity is not None else None
        rows[name] = {'active': used, 'measured_capacity_tps': capacity if used else None,
                      'selected_percent': getattr(budget, name), 'ceiling_tps': ceiling,
                      'relative_percent': None, 'relative_tps': None}

    result = {'state': 'NEEDS_BENCHMARK' if unknown else 'ESTIMATED',
              'basis': 'MEASURED_WORKLOAD_COST_ESTIMATE_NOT_NETWORK_ACK',
              'overall_percent': budget.overall, 'unknown_resources': unknown,
              'bottlenecks': [], 'estimated_tps': None, 'estimated_blocks_per_second': None,
              'transactions_per_block': transactions_per_block, 'resources': rows,
              'memory_fits': None}
    if memory_required_bytes is not None and (memory_available_bytes is not None or memory_headroom_bytes is not None):
        available = memory_headroom_bytes if memory_headroom_bytes is not None else memory_available_bytes * budget.ram / 100
        result['memory_fits'] = memory_required_bytes <= available
        if not result['memory_fits']:
            result.update(state='MEMORY_LIMIT', estimated_tps=0.0, bottlenecks=['ram'])
    if result['state'] == 'MEMORY_LIMIT':
        target = 0.0
    elif budget.overall == 0 or any(getattr(budget,name)==0 or rows[name]['ceiling_tps']==0 for name in active):
        target = 0.0
        result.update(state='PAUSED',estimated_tps=0.0,
            bottlenecks=[name for name in active if getattr(budget,name)==0 or rows[name]['ceiling_tps']==0])
    elif unknown:
        return result
    else:
        ceiling = min(rows[name]['ceiling_tps'] for name in active)
        target = ceiling * budget.overall / 100
        result['estimated_tps'] = target
        result['bottlenecks'] = [name for name in active if math.isclose(rows[name]['ceiling_tps'], ceiling, rel_tol=1e-9, abs_tol=1e-12)]
        if target == 0:
            result['state'] = 'PAUSED'
    for name in active:
        capacity = rows[name]['measured_capacity_tps']
        rows[name]['relative_tps'] = target
        rows[name]['relative_percent'] = min(getattr(budget, name), target / capacity * 100) if capacity else 0.0
    if transactions_per_block is not None:
        result['estimated_blocks_per_second'] = target / transactions_per_block
    return result


def hardware_info():
    """Read-only local facts. Link speed is explicitly not measured throughput."""
    result = {'logical_cpus': os.cpu_count() or 1, 'memory_total_bytes': None,
              'memory_available_bytes': None, 'process_memory_bytes': None,
              'network_link_bytes_per_second': None,
              'network_basis': 'UNKNOWN', 'gpu_compute_supported': False,
              'gpu_compute_backend': None, 'gpu_dag_utilization_percent': 0}
    try:
        import psutil
        memory = psutil.virtual_memory()
        result.update(memory_total_bytes=memory.total, memory_available_bytes=memory.available,
                      process_memory_bytes=psutil.Process().memory_info().rss)
        speeds = [row.speed for row in psutil.net_if_stats().values() if row.isup and row.speed > 0]
        if speeds:
            result.update(network_link_bytes_per_second=max(speeds)*1_000_000/8,
                          network_basis='OS_REPORTED_LINK_SPEED_NOT_MEASURED_THROUGHPUT')
    except (ImportError, OSError, RuntimeError):
        pass
    if result['memory_total_bytes'] is None:
        try:
            page = os.sysconf('SC_PAGE_SIZE')
            total, available = os.sysconf('SC_PHYS_PAGES'), os.sysconf('SC_AVPHYS_PAGES')
            if page > 0 and total > 0:
                result['memory_total_bytes'] = total*page
            if page > 0 and available > 0:
                result['memory_available_bytes'] = available*page
        except (AttributeError, OSError, ValueError):
            pass
    return result


class HardwareTest:
    """Explicit, cancellable calibration using a separate disposable real DAG.

    It never changes the connected DAG, uses no wallet key, and never starts
    network work unless an owned caller supplies its bounded link probe.
    """

    def __init__(self, *, info_provider=hardware_info):
        self._info_provider = info_provider
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker = None
        self._status = {'state': 'UNMEASURED', 'profile': None, 'samples': [], 'last_error': ''}

    def snapshot(self):
        with self._lock:
            return deepcopy(self._status)

    def _current_profile(self):
        # Published once per completed test and never mutated internally.
        # Avoid deep-copying all samples at every transaction checkpoint.
        with self._lock:return self._status.get('profile')

    def start(self, *, duration_ms=10000, max_transactions_per_block=5000, network_probe=None):
        if type(duration_ms) is not int or not 1000 <= duration_ms <= 60000:
            raise ValueError('GG_DAG_HARDWARE_DURATION')
        if type(max_transactions_per_block) is not int or not 1 <= max_transactions_per_block <= 50000:
            raise ValueError('GG_DAG_TX_LIMIT')
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ValueError('GG_DAG_HARDWARE_BUSY')
            self._cancel = threading.Event()
            self._status = {'state': 'RUNNING', 'profile': None, 'samples': [], 'last_error': '',
                            'duration_ms': duration_ms, 'target_transactions_per_block': max_transactions_per_block}
            self._worker = threading.Thread(target=self._run,
                args=(duration_ms, max_transactions_per_block, network_probe),
                name='gg-dag-hardware-calibration', daemon=True)
            self._worker.start()
        return self.snapshot()

    def stop(self):
        self._cancel.set()
        return self.snapshot()

    def join(self, timeout=None):
        worker = self._worker
        if worker is not None:
            worker.join(timeout)
        return worker is None or not worker.is_alive()

    def _run(self, duration_ms, maximum, network_probe):
        from backend.gg_ed25519 import Keypair
        from backend.gg_parallel_dag import ParallelDag, make_public_genesis, LAN_MAX_BLOCK_BYTES
        began = time.monotonic()
        deadline = began + duration_ms/1000
        compute_deadline = began + duration_ms/1000*(.75 if network_probe is not None else 1)
        engine = None
        keys = []
        samples = []
        def permitted():
            if self._cancel.is_set():
                raise ValueError('GG_DAG_HARDWARE_CANCELLED')
            if time.monotonic() >= deadline:
                raise ValueError('GG_DAG_HARDWARE_DEADLINE')
        try:
            info = self._info_provider()
            keys = [Keypair() for _ in range(6)]
            genesis = make_public_genesis([key.pubkey().hex() for key in keys], enable_dag_transactions=True)
            engine = ParallelDag.from_public_genesis(genesis)
            engine.attach_local_producers({0: keys[0], 1: keys[1]})
            engine.configure_lan_capacity()
            available = info.get('memory_available_bytes')
            copy_size = min(8*1024*1024, max(64*1024, available//100)) if type(available) is int else 256*1024
            buffer = bytearray(copy_size)
            copied = 0
            duplicate = b''
            memory_began = time.perf_counter()
            while time.perf_counter()-memory_began < .05:
                permitted()
                duplicate = bytes(buffer)
                copied += len(duplicate)
            memory_bandwidth = copied/max(time.perf_counter()-memory_began, 1e-9)
            del buffer, duplicate
            counts = sorted({min(maximum, count) for count in (8, 32, 128, 512, 2048, 5000, 10000, 30000, 50000)})
            for count in counts:
                permitted()
                # Do not begin a larger sample that previous actual work shows
                # cannot finish in the remaining calibration window.
                if samples and samples[-1]['elapsed_ms']/1000 * count/samples[-1]['transactions'] > max(0, compute_deadline-time.monotonic())*.9:
                    break
                start = time.perf_counter()
                cpu_start = time.thread_time()
                try:
                    block = engine.produce_lan_test_block(len(samples)%2, count, LAN_MAX_BLOCK_BYTES, check=permitted)
                except ValueError as error:
                    if str(error) == 'GG_DAG_HARDWARE_DEADLINE':
                        break
                    raise
                elapsed = time.perf_counter()-start
                evidence = engine.lan_evidence()
                if evidence['protocol_fault'] or evidence['canonical']:
                    raise ValueError('GG_DAG_HARDWARE_PROOF')
                sample = {'transactions': count, 'wire_bytes': len(block['wire']),
                          'elapsed_ms': elapsed*1000, 'cpu_ms': (time.thread_time()-cpu_start)*1000,
                          'producer_ms': engine.snapshot()['last_wave']['producer_ms'],
                          'validation_ms': engine.snapshot()['last_wave']['validation_ms']}
                samples.append(sample)
                with self._lock:
                    self._status['samples'] = deepcopy(samples)
            if not samples:
                with self._lock:
                    self._status.update(state='STOPPED' if self._cancel.is_set() else 'TIME_BUDGET',
                                        stop_reason='CANCELLED' if self._cancel.is_set() else 'DURATION',last_error='')
                return
            largest = samples[-1]
            wire_per_tx = largest['wire_bytes']/largest['transactions']
            link = None
            link_error = ''
            if network_probe is not None and deadline-time.monotonic() > .25:
                try:
                    link = network_probe(deadline, self._cancel)
                except (OSError, ValueError) as error:
                    value = str(error)
                    link_error = value if re.fullmatch(r'GG_[A-Z0-9_]{1,80}',value) else 'GG_DAG_HARDWARE_LINK_FAILED'
                if link is None and not link_error:link_error='GG_DAG_HARDWARE_LINK_FAILED'
            elif network_probe is not None:
                link_error='GG_DAG_HARDWARE_DEADLINE'
            link_speed = None
            link_basis = info.get('network_basis', 'UNKNOWN')
            if isinstance(link, dict):
                value = link.get('bytes_per_second')
                if type(value) in (int, float) and math.isfinite(value) and value > 0:
                    link_speed = value
                    link_basis = 'MEASURED_AUTHENTICATED_LAN_PROBE'
            if link_error:
                link_basis = 'MEASUREMENT_FAILED'
            elif link_speed is None:
                link_speed = info.get('network_link_bytes_per_second')
            # Two paired destinations and base64 framing are a conservative
            # workload conversion. The actual link test can refine this basis.
            network_cost = wire_per_tx * 2 * 4/3
            capacities = {'cpu': largest['transactions']/(largest['elapsed_ms']/1000),
                          'gpu': None, 'ram': memory_bandwidth/(wire_per_tx*8) if copied else None,
                          'network': link_speed/network_cost if link_speed else None}
            profile = {'schema': 'gg.dag-hardware-profile.v1', 'measured_at': time.time(),
                       'hardware': info, 'capacities_tps': capacities, 'active_resources': ['cpu', 'ram', 'network'],
                       'cpu_basis': 'MEASURED_NATIVE_DAG_SIGN_AND_VERIFY_WORKLOAD',
                       'ram_basis': 'MEASURED_COPY_BANDWIDTH_WITH_ESTIMATED_EIGHT_COPY_COST',
                       'network_basis': link_basis, 'network_bytes_per_second': link_speed,'network_error':link_error,
                       'wire_bytes_per_transaction': wire_per_tx, 'network_bytes_per_transaction': network_cost,
                       'largest_measured_transactions_per_block': largest['transactions'],
                       'calibration_elapsed_ms': (time.monotonic()-began)*1000,
                       'physical_shared_ack': False, 'canonical_finalized': 0}
            with self._lock:
                self._status.update(state='STOPPED' if self._cancel.is_set() else 'PARTIAL' if link_error else 'COMPLETE',
                                    profile=profile, samples=deepcopy(samples), last_error='')
        except Exception as error:
            value = str(error)
            code = value if value in {'GG_DAG_HARDWARE_CANCELLED', 'GG_DAG_HARDWARE_DEADLINE',
                'GG_DAG_HARDWARE_PROOF', 'GG_DAG_HARDWARE_NO_COMPLETE_SAMPLE'} else 'GG_DAG_HARDWARE_FAILED'
            with self._lock:
                expected=self._cancel.is_set() or code=='GG_DAG_HARDWARE_DEADLINE'
                self._status.update(state='STOPPED' if self._cancel.is_set() else 'TIME_BUDGET' if expected else 'ERROR', last_error='' if expected else code,
                                    samples=deepcopy(samples))
        finally:
            if engine is not None:
                engine.stop()
            keys.clear()


class WorkGovernor:
    """Cooperative DAG-work ceilings; never changes global OS/GPU settings."""

    def __init__(self, budget=None, profile=None, *, info=None, cancel=None,
                 monotonic=time.monotonic, thread_clock=time.thread_time,
                 stored_bytes=lambda: 0, memory_account=None):
        self.budget = budget or ResourceBudget()
        if not isinstance(self.budget, ResourceBudget):
            raise ValueError('GG_DAG_RESOURCE_BUDGET')
        self.profile = profile or {}
        self.info = info or hardware_info()
        self.cancel = cancel or threading.Event()
        self._clock = monotonic
        self._thread_clock = thread_clock
        self._stored_bytes = stored_bytes
        self._lock = threading.RLock()
        self._threads = {}
        self._memory_account = memory_account if memory_account is not None else {'lock':threading.RLock(),'reserved':0}
        self._network_next = self._clock()
        capacities = self.profile.get('capacities_tps', {})
        active = self.profile.get('active_resources', ['cpu', 'ram', 'network'])
        self.plan = bottleneck_plan(capacities, self.budget, active=active)
        target = self.plan['estimated_tps']
        cpu_capacity = capacities.get('cpu')
        physical_cpu = self.info.get('logical_cpus', 1) * self.budget.cpu / 100
        if target is not None and cpu_capacity:
            # Calibration is the actual engine workload, not an extrapolation
            # that assumes a Python worker can consume every physical core.
            self._cpu_rate = min(physical_cpu, target/cpu_capacity)
        else:
            self._cpu_rate = physical_cpu*self.budget.overall/100
        link = self.profile.get('network_bytes_per_second') or self.info.get('network_link_bytes_per_second')
        self._network_rate = link*self.budget.network/100 if link else None
        cost = self.profile.get('network_bytes_per_transaction')
        if target is not None and cost:
            modeled = target*cost
            self._network_rate = min(self._network_rate, modeled) if self._network_rate is not None else modeled
        elif self._network_rate is not None:
            self._network_rate *= self.budget.overall/100
        self._cpu_burst = .025*self._cpu_rate
        self._cpu_tokens = self._cpu_burst
        self._cpu_at = self._clock()

    def _permitted(self, deadline):
        if self.cancel.is_set():
            raise ValueError('GG_DAG_RESOURCE_CANCELLED')
        if deadline is not None and self._clock() >= deadline:
            raise ValueError('GG_DAG_RESOURCE_DEADLINE')

    def _wait_until(self, until, deadline, check=None):
        while True:
            self._permitted(deadline)
            if check is not None:check()
            remaining = until-self._clock()
            if remaining <= 0:
                return
            if deadline is not None:
                remaining = min(remaining, deadline-self._clock())
            self.cancel.wait(min(.05, max(0, remaining)))

    def check_cpu(self, *, deadline=None, check=None):
        self._permitted(deadline)
        if check is not None:check()
        if self._cpu_rate <= 0:
            raise ValueError('GG_DAG_RESOURCE_PAUSED')
        ident = threading.get_ident()
        used = self._thread_clock()
        with self._lock:
            previous = self._threads.get(ident, used)
            self._threads[ident] = used
            # Connection threads are short-lived; bound accounting metadata.
            if len(self._threads) > 64:
                for key in tuple(self._threads):
                    if key != ident:
                        del self._threads[key]
                        break
            now = self._clock()
            self._cpu_tokens = min(self._cpu_burst, self._cpu_tokens + (now-self._cpu_at)*self._cpu_rate)
            self._cpu_at = now
            self._cpu_tokens -= max(0, used-previous)
        while True:
            self._permitted(deadline)
            if check is not None:check()
            with self._lock:
                now = self._clock()
                self._cpu_tokens = min(self._cpu_burst, self._cpu_tokens + (now-self._cpu_at)*self._cpu_rate)
                self._cpu_at = now
                debt = max(0, -self._cpu_tokens)
            # Sub-nanosecond floating-point debt must not become a busy loop
            # when adding the remaining delay no longer advances the clock.
            if debt <= 1e-9:
                return
            self._wait_until(now+min(.05, debt/self._cpu_rate), deadline, check)

    def wait_network(self, size, *, deadline=None):
        if type(size) is not int or size < 0:
            raise ValueError('GG_DAG_RESOURCE_BYTES')
        self._permitted(deadline)
        if self.budget.network == 0 or self.budget.overall == 0:
            raise ValueError('GG_DAG_RESOURCE_PAUSED')
        if self._network_rate is None:
            if self.budget.network < 100:
                raise ValueError('GG_DAG_RESOURCE_NEEDS_BENCHMARK')
            return
        if self._network_rate <= 0:
            raise ValueError('GG_DAG_RESOURCE_PAUSED')
        with self._lock:
            until = max(self._clock(), self._network_next) + size/self._network_rate
            self._network_next = until
        self._wait_until(until, deadline)

    def memory_headroom(self):
        total = self.info.get('memory_total_bytes')
        available = self.info.get('memory_available_bytes')
        if type(total) is not int or type(available) is not int:
            return None
        with self._memory_account['lock']:
            return max(0, min(total*self.budget.ram/100, available)
                       - self._stored_bytes()*4-self._memory_account['reserved'])

    def memory_committed(self):
        with self._memory_account['lock']:
            return self._stored_bytes()*4+self._memory_account['reserved']

    @contextmanager
    def reserve_memory(self, size):
        if type(size) is not int or size < 0:
            raise ValueError('GG_DAG_RESOURCE_BYTES')
        with self._memory_account['lock']:
            headroom = self.memory_headroom()
            if self.budget.ram == 0 or headroom is not None and size > headroom:
                raise ValueError('GG_DAG_RESOURCE_MEMORY')
            self._memory_account['reserved'] += size
        try:
            yield
        finally:
            with self._memory_account['lock']:
                self._memory_account['reserved'] -= size


class ResourceController:
    """One node's explicit settings, calibration and shared work accounting.

    Construction is inert. It changes no OS, wallet or other node's settings.
    A snapshot may read local hardware facts, but never starts a benchmark.
    """
    def __init__(self, *, info_provider=hardware_info, stored_bytes=lambda: 0, cancel=None):
        self._lock = threading.RLock()
        self._info_provider = info_provider
        self._info = None
        self._stored_bytes = stored_bytes
        self._cancel = cancel or threading.Event()
        self.test = HardwareTest(info_provider=info_provider)
        self.budget = ResourceBudget()
        self._governor = None
        self._governor_key = None
        self._memory_account = {'lock':threading.RLock(),'reserved':0}
        self.revision = 0

    def facts(self):
        with self._lock:
            if self._info is None:
                self._info = self._info_provider()
            return deepcopy(self._info)

    def configure(self, budget):
        with self._lock:
            self.budget = ResourceBudget.from_public({**self.budget.public(), **budget}) if isinstance(budget, dict) else ResourceBudget.from_public(budget)
            self.revision += 1
        return self.snapshot()

    def governor(self):
        with self._lock:
            profile = self.test._current_profile() or {}
            key = (tuple(self.budget.public().values()), profile.get('measured_at'))
            if self._governor is None or self._governor_key != key:
                self._governor = WorkGovernor(self.budget, profile, info=self.facts(),
                    stored_bytes=self._stored_bytes, cancel=self._cancel,memory_account=self._memory_account)
                self._governor_key = key
            return self._governor

    def snapshot(self, transactions_per_block=None):
        with self._lock:
            measured = self.test.snapshot()
            profile = measured.get('profile') or {}
            plan = bottleneck_plan(profile.get('capacities_tps', {}), self.budget,
                active=profile.get('active_resources', ['cpu', 'ram', 'network']),
                transactions_per_block=transactions_per_block)
            result = {'schema': 'gg.dag-node-resources.v1', 'budget': self.budget.public(),
                    'hardware': self.facts(), 'test': measured, 'plan': plan,
                    'scope': 'THIS_NODE_DAG_WORK_ONLY', 'revision': self.revision}
            governor = self.governor()
        result['memory_headroom_bytes'] = governor.memory_headroom()
        result['memory_committed_bytes'] = governor.memory_committed()
        wire_cost=profile.get('wire_bytes_per_transaction')
        if transactions_per_block and wire_cost and result['memory_headroom_bytes'] is not None:
            result['plan']=bottleneck_plan(profile.get('capacities_tps',{}),self.budget,
                active=profile.get('active_resources',['cpu','ram','network']),
                transactions_per_block=transactions_per_block,
                memory_required_bytes=math.ceil(transactions_per_block*wire_cost*16),
                memory_headroom_bytes=int(result['memory_headroom_bytes']))
        return result
