# Source2 LAN runtime, protected production and shared Desktop observations

This review concerns the private LAN software implementation. The complete
delivery remains unfinished and unpublished. No public/testnet/mainnet launch,
physical-device update or measured sustained capacity follows from these tests.

## Original intent and resulting behavior

Actual node/CLI activity must be the source of Desktop data. A producer owns
its own signing keys and original proposals; multiple validators may verify
them. An optional slow producer must not become a global production barrier.
Restart must preserve identity, selected nonces, pending originals and history.

Explicit `enable_segmented=true` now requires both DAG and consensus opt-in.
The actual existing signed pairing transport installs and distributes the v5
contract on protected NodeProfiles. No pretend legacy global DAG engine is
created. The shared LanDagRuntime selects real OwnedSegmentedAuthority objects,
polls their actual SDK state and runs bounded cut maintenance. Existing v1–v4
behavior remains separate. The CLI parser types the consensus/segmented flags.

The producer command opens the actual protected own journal, signs/persists
before exposure, and closes its owned handle when bounded work stops. Pending
originals are reused after restart. A local pending ceiling of 16 provides
backpressure for that producer; another owner and the validator processes have
independent lifetimes. Job counters describe local work, never SDK selection.
Proof observation publishes a verified producer base before optional account
display work finishes. An unchanged certified DAG commitment reuses its original
proofs without replacing their original certificate or proof height.

The source2 owner floor accepts only its exact signed-session native anchor.
Legacy source1 floors/history are not relabelled. A newer observed epoch prevents
signing until the own journal recovers its verified base. Verified conflict
evidence stops shared owner work and masks current account/counter claims.

## Original submission and bounds

An optional producer can send original block bytes through authenticated,
channel-bound signed fragments. Declaration, readiness, data and final receipt
are distinct protocol stages. Hash, size, exact frame sequence, record count,
canonical framing, role and the original bytes are checked. A transport key for
a replica does not grant the producer submission role.

TCP handlers enqueue bounded work; they do not invoke SDK RPC or sign. There
are at most two receiving/queued/working actors, at most one slot per actor,
and at most 64 MiB of distinct original queued/incoming bytes. Memory reservations cover
decoding/encoding overhead and are released on cancellation and completion.
Raw proposals are bounded by the existing 32 MiB consensus policy. Encoded
checkpoint batches use its existing 48 MiB bound, the same bound used by the
native node and shared owned RPC. This fixes an inconsistent Python-only cap
that could otherwise create a legal original too large for its submission path.
These are existing consensus limits, not new or measured capacity.

`QUEUED`, uncertain delivery and native mempool admission never retire an
original. Only a later verified SDK state establishes selection. Queue loss or
an ambiguous response leaves the producer's durable original available. The
worker builds a batch against actual certified active SDK state; the native
implementation validates signatures, dependencies, nonces and execution.
Default local cut maintenance proposes a cut at 256 MiB or 2048 active blocks.
The actual test lowers the trigger to one block to exercise that code path;
it does not claim to have reached the default byte threshold.

Current encoded transport pacing is bounded at 4 MiB/s per transfer and retains
the existing admission credits and the user's resource governor. This candidate
does not meet the requested 5000 TX/block at hundreds of blocks/s. Raising limits
alone would not establish that target.

## CLI and Desktop truthfulness

The existing per-user public observation channel now admits the exact source2
private-LAN scope and preserves certified counters as decimal strings. Reading
it does not create a node, open protected keys or issue commands. Counts above
JavaScript's exact integer range remain exact in CLI and QML. Unknown counters
remain unknown instead of becoming fabricated zero measurements.

Desktop shows SDK-selected block/TX totals separately from local signature work,
signed-roster owner names and the actual creator's producer index. Active order
positions use the verified global index. The sparse proof list never invents
causal rank or parent links. Original block retrieval is still needed for the
full causal graph. A sparse observer does not claim full payload replay, even
if its declared participation policy is named replica. SDK validator status is
reported separately from this Python client's replay scope.

## Evidence, findings and corrections

Actual runs use three protected shared runtimes, signed TCP pairing and real
SDK children on one Windows host. The complete command-path experiment selects
5002 unique TX in three DAG blocks across two cuts. Journals sign 5003 TX; one
retired unselected TX is excluded from network counters. It uses five SDK process
instances, at most four concurrently. The optional producer owns no validator.
Three remaining validators continue when the fourth stops. The optional owner
closes/reopens its original profile, archives stale pending bytes and resumes the
next exact selected nonce. Its actual SDK block-membership proof names its own
distinct creator key. A separate public-reader process gets the same totals
without acquiring node ownership. All owned SDK children terminate.

The first actual run found a wrapper bug: strict certificate shape validation
was being passed the entire proof packet. The correction validates the strict
core separately and still native-verifies the attached proof. The failing run
and a regression test are retained; the global strict certificate contract was
not loosened. A resource pause/retry test found a missing wait operation in the
combined cancellation signal. A failed-primary-owner test found that rotation
was advanced only after successful delivery. Both regressions are retained:
retry waits now remain cancellable, and failed delivery advances to the next
validator owner while keeping the exact original. Unexpected provider errors
produce explicit error status and release owned work/reservations. QML checks
also caught and corrected a ternary-expression error before any active UI
reload. Policy tests inject SDK-result, persistence and
cancellation seams; they are not presented as genuine quorum attacks.

Final machine-readable source stamps, exact suite counts, actual SDK receipts,
and native/Python/WASM positive and negative proof checks are kept in the private
`segmented-lan-runtime-v1` checkpoint. The unchanged native Go/WASM artifacts
retain their prior source-matched build, Go-test and Ghidra provenance. This
Python/QML stage is not a new native build or a fresh disassembly.

## Assumptions and remaining work

Four validator keys on one Windows host are not four independent physical
fault domains. This also does not establish tolerance of a physical host that
owns two of four voting keys. Linux/Android execution, radio links, power loss,
long endurance and target throughput still require their acceptance evidence.

Nonempty v4 profiles remain intact and cannot be silently cleared or rebound.
An explicit network-scoped transition workflow, native observer membership,
source2 original-payload retrieval and full visual graph recovery remain open.
Monetary policy, permissionless mining/pools, rewards and mainnet economics are
not implemented by this nonfinancial fixed-committee experiment. Its finite test
allocation and nonce bounds must not be advertised as a public monetary model.
Public testnet activation and mainnet readiness remain separate unfinished gates.

No active app restart/reload, installed-tool replacement, new device bootstrap,
Git push or public network activation is part of this checkpoint.
