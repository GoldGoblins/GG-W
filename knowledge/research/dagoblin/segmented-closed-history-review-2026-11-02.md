# Closed segment membership and cold original recovery

This extends the private nonfinancial LAN candidate. Full delivery and mainnet
readiness remain incomplete. Software checks on one Windows host do not prove
physical Linux/Android behavior, target throughput or physical fault tolerance.

## Original intent and facts

Actual selected blocks must remain available after segment retirement and node
restart. The Desktop graph must use their genuine creator and signed parent
references, while a sparse client must not claim full transaction replay.

The SDK commitment already contains a closed-segment root. Its leaves commit
complete cut preimages, including the preceding selected order/account roots
and original-history root. This implementation adds arbitrary closed-cut
membership proofs and bounded, indexed original reads. It does not change the
existing consensus commitments, creator signatures or monetary rules.

## Proof chain

The new closed-page proof binds the entire current SDK commitment, an exact
canonical cut preimage, its position/count-aware closed-tree witness and a
bounded page of selected order witnesses. The verifier matches the existing
accumulator's odd-node duplication and root bagging. Global counts remain
uint64, including in the shared WASM source; they are not narrowed through
architecture-sized integers or JavaScript numbers.

Verification checks the pinned genesis and SDK quorum, current commitment,
closed cut position, account-root consistency, actual selected order root,
global index, producer sequence, creator key and allowed producer role.
The returned scope explicitly excludes full history replay and availability.
Original bytes still require a complete wire digest, canonical body hash and
the creator's signature before they can enter the displayed graph.

## Original-derived durable index

Full original archive replay derives compact order metadata, payload sizes,
wire digests, byte offsets and each record's selected manifest timestamp.
A cut's archive reference, index, newly completed closed-tree nodes, native
history and active-state metadata enter one synchronous database batch. They
are not published as selected history during archive preparation.

Startup still replays all original archives and compares their newly derived
index bytes and tree nodes exactly. Inventory rejects missing, additional or
malformed nodes. A resealed metadata offset cannot substitute for this replay.
Public reads use a bounded segment index and logarithmic closed-tree lookups;
they do not scan all archives or retain all closed history in RAM per query.

The native store uses the explicit v2 index-bearing storage schema. An older
indexless v1 candidate database is preserved and rejected with a concrete
transition-required error. The lossless transition workflow remains required
before release; no existing profile is silently cleared, rebound or rekeyed.

## Bounded reads and client behavior

Proof and payload reader slots bound concurrent work. Database snapshot leases
are captured under the store lock; archive access, hashing, signature checks
and chunk encoding occur outside consensus/store locks. A concurrent cut does
not replace a captured proof's SDK context. Close rejects new leases and waits
for owned readers to release theirs. Corrupt indexed originals fail closed.

Archive chunks bind their selected epoch as well as the exact requested SDK
height/root, body hash, local index and aligned offset. No peer supplies file
paths or trusted snapshot flags. One temporary client spool holds at most one
32 MiB original under the resource governor. A fresh verified certificate can
authorize reads while an older independently verified membership proof remains
unchanged. An incomplete active original can continue from its closed archive
after a cut, instead of repeatedly discarding progress.

The display worker discovers recent closed pages and walks backward within a
bounded 128-header window. A failed cold source does not prevent an already
known active original from progressing. All displayed edges come from genuine
signed parent references with both endpoints present. Missing parents remain
missing. A read-only CLI/Desktop observation reader receives the same headers;
it does not open node keys or start another producer or validator.

## Findings and corrections

The first native regression found that the streaming replay cursor deliberately
has no retained start-base graph. Index derivation now uses the exact archive
header already verified against its separate base, rather than trying to
reconstruct a writer header from an absent cursor pointer.

The actual SDK/LAN experiment then exposed a clock-rule mismatch: consensus
already allows an original's creation timestamp up to five seconds beyond its
selected manifest time. The new cold reader initially used a stricter bound,
which could incorrectly fail healthy validators when serving valid originals.
The corrected index retains each original's actual manifest timestamp and the
reader applies the exact existing five-second allowance. A regression selects
and cold-reads originals at that boundary. The failing original contexts and
run receipts are retained; the consensus acceptance rule was not loosened.

## Evidence scope and remaining work

Native checks cover actual selected originals across three closed epochs,
restart, active-view eviction, accumulator peak/odd boundaries, global uint64
arithmetic, manipulated cut/order/creator proofs, invalid selectors, bounded
readers, cancelled work, a cut during a pinned read, close during a pinned read,
corrupt indexes/archives and the atomic selection barrier. Arithmetic tests
with large opaque subtree digests do not claim a physically generated history
of that size. Python policy seams are explicitly mocked; separate actual
native/Python/WASM agreement checks exercise the built verifiers.

The actual integration driver requires authenticated shared LAN runtimes,
genuine SDK selection, cuts, optional-owner restart, cold recovery of the same
original headers/causal edge and a separate read-only observation process.
Exact source stamps, final results, failing attempts, fresh native artifacts,
WASM provenance and bounded Ghidra inspection are retained in the private
`segmented-closed-history-v1` evidence directory. Ghidra inspection of selected
function bytes is not a whole-binary security or cryptographic correctness proof.

Full independent client transaction replay, lossless network/profile and old
storage transitions, native observer membership, permissionless consensus and
economic/mining/pool rules, sustained target capacity and physical endurance,
power-loss and network acceptance remain open. No active-app restart,
installed-tool replacement, physical device update, Git push or public network
activation is part of this stage.
