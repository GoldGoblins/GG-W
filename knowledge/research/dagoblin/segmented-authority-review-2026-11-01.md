# Owned segmented SDK authority — review started 2026-11-01

Review completed 2026-11-02. This is a private LAN software stage, not a
mainnet readiness or throughput certificate.

## Original intent

Actual CLI/node activity must be authoritative. Desktop must eventually show
the same certified activity, identities and ownership. An optional slow
producer must recover without holding back the active validators. Existing
identities and original signed history must survive restart. Never display
mempool admission, local signatures or stored observations as live finality.

## Findings and implementation

The legacy owned validator assumes a source1 global order journal. Passing a
pretend active legacy peer to it would conceal a missing source2 integration.
The new `OwnedSegmentedSession` binds an actual, exclusively open protected
NodeProfile to its validated signed v5 roster and exact owned descriptor.
The new `OwnedSegmentedAuthority` uses an actual leased ValidatorProfile,
membership-bound bootstrap v2 and the original persistent native root.
No legacy DAG engine is created to satisfy an interface.

`OwnedNativeRPC` now contains the common process and RPC guards. Twelve moved
methods are compared structurally with their stage backup; the sole semantic
adaptation is an explicit owner-lifetime hook. Exact listener/PID ownership,
native binary checks, bounded RPC, dedicated public reads, readiness attestation,
process containment and cleanup remain shared with the source1 controller.

Fresh certificates are verified by the native verifier and durably saved
before a verified view is published. Historical certificates are verified
again after profile reopen and labelled as persisted observations. Mempool
acceptance and uncertain submission responses always report SDK_selected=false.
Base, account, block and order proofs use one captured SDK certificate and
process epoch, outside the signing work lock. Eviction or restart causes an
explicit failure; a newer context is never silently substituted.

Both certificates in conflict evidence must pass native verification before
the conflict is persisted in the protected owner and validator stores. The
shared owner fault also blocks its other validator children and own producer.
A faulted schema4 journal can reopen to retain its evidence, but cannot sign.
Normal source1 consensus history remains an explicit transition error.

## Actual SDK evidence

The final isolated experiment uses nine real native SDK process instances,
at most four concurrently, on one Windows host. Three protected owner profiles
and four protected validator profiles use real encrypted keys and a genuinely
signed v5 membership. No legacy active DAG engine is installed.

The SDK selected 15,002 unique transactions in five DAG blocks across two
segment cuts. The protected journals signed 15,003 transactions: one retired
pending transaction is explicitly excluded from the selected count. Three
validators continued while the fourth was stopped; it then caught up using
its original native root. All validator profiles and an owner profile were
closed and reopened before selecting the next exact nonce.

The optional third producer owns no validator child. It remained offline
across both cuts, reopened its original keys, archived its old pending wire,
and produced a new accepted block. The actual SDK rejected its stale wire.
The actual block proof names this distinct producer key as creator. A real
public base query also completed while the controller work lock was held.
All owned children terminated and both native and Python source stamps
remained unchanged during the final experiment.

Policy tests deliberately mock native result seams to inject persistence
failures, contradictory certificates, target drift and evicted contexts.
They do not demonstrate an actual malicious quorum. Separate actual packets
are checked by native, Python and WASM verification. Machine-readable receipts,
source stamps and the full regression results are retained in the private
`segmented-authority-v1` evidence directory.

## Decisions, assumptions and remaining work

This adds an owned authority library and packaging graph entries. Actual v5
LAN negotiation, foreground CLI commands and Desktop bindings still require
integration with this same source. Nonempty v4 network profiles must not be
cleared or rebound: an explicit network-scoped transition is still needed.
Native observer membership is also unfinished.

Four validator keys on one host do not establish independent host fault
tolerance. This run does not test Linux/Android execution, radio conditions,
physical power loss, sustained throughput or global history reconstruction by
the client. Monetary policy, mining/pool security, public testnet acceptance
and mainnet readiness remain open. No 5000-TX/block at hundreds of blocks/s
claim follows from these tests. The unchanged native Go/WASM artifacts retain
their prior source-matched build/test provenance; this stage is not a new build.

No active app restart, installed tool replacement, physical-device update,
bootstrap publication, Git push or public network activation occurred.
