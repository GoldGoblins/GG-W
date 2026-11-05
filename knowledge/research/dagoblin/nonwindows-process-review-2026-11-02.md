# Linux and Android permanent native process limits

## Original intent

Keep the real CLI/node authoritative and let Desktop display its observed state.
Slow participants must not stop faster participants. Preserve distinct protected
node identities, actual SDK execution and independently verified certificates.
One coherent code phase precedes combined publication and physical acceptance.

## Findings and primary sources

Windows persistent SDK children already have separate 512 MiB job leaves and an
owner-wide CPU-rate/child-count job. A lifetime CPU-seconds cutoff is unsuitable
for a permanent node. Linux and Android cannot honestly inherit these Windows
claims. GOMEMLIMIT is a Go runtime soft limit, not a kernel memory boundary.

* [Linux getrlimit](https://man7.org/linux/man-pages/man2/getrlimit.2.html): hard
  limits survive exec; an ordinary child cannot raise them. RLIMIT_DATA includes
  mmap from Linux 4.7; RLIMIT_AS measures virtual address space, not RSS.
  RLIMIT_NPROC counts the real UID's processes/threads and would interfere with
  sibling SDKs and unrelated user applications. RLIMIT_CPU is accumulated time.
* [Go GC guide](https://go.dev/doc/gc-guide#Memory_limit): runtime-managed memory
  limits are soft and do not account for every source of memory consumption.
* [Python subprocess](https://docs.python.org/3/library/subprocess.html): a
  threaded application's preexec_fn can deadlock; start_new_session is provided
  for session setup without that hook.
* [Kernel no_new_privs](https://docs.kernel.org/userspace-api/no_new_privs.html):
  the flag is inherited across exec and prevents privilege gain through exec.
* [cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html): memory.max,
  cpu.max and pids.max provide separate kernel scopes when delegation permits.

## Implementation decisions

The actual managed Linux/Android SDK is execed by a separate isolated, stdlib-only
Python launcher. Before reading any bootstrap, it creates no threads, requires
the new session leader and an ordinary non-root UID without CAP_SYS_RESOURCE,
sets no_new_privs, and irreversibly lowers both soft and hard limits:

| Resource | Maximum | Exact meaning |
| --- | ---: | --- |
| RLIMIT_DATA | 512 MiB | Process data segment/mapping limit; not total RSS |
| RLIMIT_AS | 8 GiB | Virtual address space, including Go arena reservations |
| RLIMIT_NOFILE | 1024 | Open file-descriptor ceiling |
| RLIMIT_CORE | 0 | Core-file size resource limit |

Stricter inherited limits are retained. The parent reads the kernel's limits and
privilege state for its exact owned Popen child before durable start claim or
private stdin. Verification has a finite deadline and observes owner cancellation
without holding the owner registry lock. Unsupported platforms, old kernels,
privileged launch contexts and failed readback fail closed before bootstrap.

The Linux owner registry admits at most six live managed SDK children. This is
an application registry ceiling, not a cgroup or a kernel descendant limit.
Closing a leaf stops only its exact owned process. Owner close signals all its
registered children before one bounded wait; other owners are outside that
scope. One Popen child cannot be attached to a second owner or duplicate lease.
The SDK's existing parent-loss exit remains necessary on abrupt launcher death.
No process group ID, UID-wide process list or searched PID is used for killing.

A real Linux cold-resume test reproduced a separate pairing-listener failure:
after a server-active TCP close, TIME_WAIT prevented rebinding the saved port.
Non-Windows pairing listeners now set SO_REUSEADDR before bind, on both the
original and resumed socket. SO_REUSEPORT is not enabled. Tests require immediate
reopening after a real completed connection and rejection of a second active
listener on the same endpoint. Windows REUSEADDR is left off because its address
ownership semantics differ. See [Linux socket](https://man7.org/linux/man-pages/man7/socket.7.html).

Reported facts identify LINUX_RLIMIT, the exact memory metrics and actual limits.
CPU-rate adjustment explicitly reports unavailable on Linux/Android; no sampled
RSS watcher, GOMAXPROCS value or software child registry is advertised as kernel
CPU-rate, RSS or descendant enforcement. No accumulated CPU lifetime limit is
introduced. The desktop and unrelated programs receive no new limit.

## Verification boundary and remaining questions

Local Linux tests use an existing unprivileged WSL Linux kernel. They must check
real SDK startup/replay, resource exhaustion, preserved inherited limits,
single-owner lifetime and terminal cleanup. These are development tests, not
physical Linux/Termux or public-network acceptance. Native and WASM sources are
unchanged; existing artifact receipts must still match exactly.

These limits are resource containment, not a security sandbox. Read-only file
mappings and other memory categories are not a 512 MiB RSS guarantee. Kernel
CPU-rate/descendant containment needs a separately available delegated cgroup.
RLIMIT_CORE alone does not guarantee that a privileged host core-dump collector
cannot collect memory when core_pattern uses a pipe. A privileged host debugger,
same-UID hostile peer process and OS compromise are not eliminated by rlimits.
Production core-dump/key-memory policy remains part of host/security acceptance.

Physical Android procfs permissions, kernel version and permanent background
execution remain to be measured on the actual phone. Monetary rules, mining,
pool payouts, permissionless participation, throughput targets and public testnet
readiness are separate incomplete gates. This change does not certify them.
