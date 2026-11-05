# Original-preserving local index transition

## Original intent

Existing selected blocks, transaction counters, original signatures, ownership
and signing identities must survive software updates. CLI is the source of
node activity; Desktop displays verified information from that same runtime.
An update must never replace prior history with an empty demonstration chain.

## Facts and change

The private segmented candidate introduced a v2 storage index for bounded
closed-history queries. Normal startup correctly rejects the older indexless
v1 store. This change adds an explicit, local maintenance operation for that
specific storage transition. It does not change genesis, commitments, monetary
policy, consensus membership, creator keys or transaction acceptance rules.

The native command receives only the protected session's public genesis pin
and the owned validator's storage root. It acquires the real LevelDB lease,
fully replays original closed segments and the active tail, and compares
retained native DAG state provenance before its first transition write.
It opens no signer, consensus node, network listener or remote repair path.

Each synchronous batch adds one original-derived segment index, its newly
completed tree nodes and an exact progress marker. Original r/m/c records,
native history and archive bytes stay unchanged. No whole-history index list
or unbounded write batch accumulates. The final synchronous batch switches
only the storage schema and removes the marker.

Resume checks the original history again and compares every saved index
prefix exactly. An interrupted or uncertain write acknowledgement is resolved
from the actual atomic database state. Missing, extra, corrupt or differently
pinned data fails closed; there is no truncation, resealing or silent repair.
An in-progress legacy store remains unavailable for normal consensus startup.

## Shared runtime and CLI

`lan.validator_index_transition profile=<owned profile> timeout=<seconds>`
runs as a finite foreground operation. That validator must already be stopped;
the command does not stop it implicitly or start it afterward. Runtime stop,
resource pause, owner closure and timeout cancel only the owned maintenance
child. The protected validator profile and anti-double-sign state are not
rewritten. The headless release graph includes the same adapter as Desktop.

Its receipt distinguishes original DAG provenance from native monetary
transfer-history replay and current network freshness. Only the former is
performed. An already unlocked Python profile can contain keys in memory;
the adapter does not request signers and the separate native maintenance
process receives no private material. A subsequent validator start is a
separate signing operation under the existing protected ownership rules.

## Findings from actual integration

The first actual SDK attempt rejected the public CLI request before writing:
the Go request structure's field order differed from sorted canonical JSON.
The original native artifacts, failed integration and stopped public fixture
are retained. Request fields now follow lexical order. A regression supplies
sorted map JSON, independently of the typed request encoder, against a genuine
nonempty legacy-format fixture.

An actual public-only legacy-store copy also exposed Python/Go string-encoding
differences for Unicode and ampersands in local paths. The adapter now emits
Go-compatible UTF-8 JSON and string escapes for this maintenance request only.
The native binary verifies unchanged roots, height and commitment after the
transition and its idempotent repeat. Signature-domain encoders are unchanged.

Acceptance uses a separate SDK fixture conversion implemented only in Go test
code. It recreates an actual old logical database containing original legacy
namespaces and no new indexes; it preserves the original v2 database as
evidence. It never becomes a production downgrade or repair command.

The integration gate exercises three actual shared runtimes on signed loopback
TCP, protected identities, a genuine 5000-transaction original, two selected
cuts, cold original/parent recovery and optional-owner restart. It then stops
one SDK validator, recreates its old logical store, calls the shared runtime's
transition, compares its protected profile and anti-double-sign bytes, and
requires the same validator's vote in a later independently verified SDK
commit after restart. A separate public observation process must retain the
same selected counters and original headers without node ownership.

## Verification contract and limitations

Native regression coverage includes nonempty and empty legacy stores, every
batch/finalization failure barrier, unknown synchronous acknowledgements,
partial-prefix cancellation/resume, wrong pins, real DB lease contention,
corrupt originals/progress/indexes, canonical public request encoding and
unchanged roots, balances, nonces, history and archive bytes. Python policy
tests explicitly mock child receipts; they are not presented as SDK evidence.

The frozen stage checkpoint records the actual test counts, source stamps,
four fresh native builds, shared WASM provenance, cross-verifier positive and
negative cases, bounded actual-native Ghidra slice and the SDK run outcome.
A selected native function's disassembly/decompilation is a review aid, not
a whole-binary security proof. Cross-compilation is not physical target execution.

## Decisions, assumptions and unresolved work

Keep normal startup fail closed and make the transition explicit, additive,
bounded and resumable. Preserve all prior cryptographic domains and monetary
semantics. The supported legacy input is the already segmented v1 indexless
store; this does not upgrade a different source1/v4 network/profile in place.

The nonempty source1/v4 profile transition must retain old signed history under
its original network namespace. Native observer membership, independent client
history replay, public consensus/economics/mining/pools, measured sustained
capacity and physical fault/endurance/power-loss tests remain unfinished.
This stage is not mainnet readiness, physical Linux/Android evidence, a
permissionless-security result or a 200-block/s throughput measurement.
No public activation or whole-code-phase Git push follows from this stage alone.
