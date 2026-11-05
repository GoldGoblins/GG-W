# Owned native startup, uncertain commits and lifetime boundaries

Original intent: preserve real node identity, account/history ownership and
consensus safety across interruption, without creating a second identity or
inventing successful recovery. CLI remains the owner; Desktop displays its
public observations. This review completes a local startup/lifetime gate within
the existing code phase, not the entire network or mainnet readiness.

## Implementation

The pinned native entry point reads its complete bounded stdin request before
opening node history. The shared Python launcher now validates and serializes
both allowed freshness modes, starts the exact child, verifies containment and
starts its bounded readiness/deadline guards before taking durable startup intent.
No private bootstrap bytes are sent before that intent is committed.

`NativeStartReservation` is one-use and tied to the same live protected profile,
database connection and exclusive lease. It holds the profile lock only through
claim and input handoff. A fresh intent can be released only if no write/flush
attempt was marked, the exact child is confirmed terminal, metadata is unchanged,
the store remains healthy, and no native root/link, certificate or fault exists.
The monotonic input marker is set before the first write attempt. No cold/older
intent is eligible for this release. No native file or signing history is deleted,
and no key or anchor is reset.

Serialization, process creation, containment and pre-input cancellation failures
therefore do not unnecessarily poison a fresh identity. A partial/unknown pipe
write remains fail-closed. Unknown claim or abort commit outcomes latch the store
until explicit reopening and cryptographic/structural revalidation. A committed
intent with missing native history remains an error after cold owner restart;
reopening does not manufacture a fresh history.

The existing finite startup deadline now also covers a blocked stdin pipe: a
separate bounded guard can stop the exact child without waiting for its controller
work lock. Terminal child pipe handles are closed. Cleanup's own stop flag cannot
relabel an unrelated I/O failure as user cancellation. Native RPC/submission and
dedicated proof reads reject ended owner/profile lifetimes before listener or
network work. Source1 now observes the same early owner-ended signal as source2,
including when database teardown is waiting on a lock. Closing one native profile
stops its child while leaving the owner and sibling profiles active.

An unexpected validator SDK exit is an operational fault with its actual exit
code, distinct from an intentional stop and from conflicting consensus evidence.
An already verified historical certificate remains cryptographically valid.
The specific exit cause takes precedence over a racing transient RPC error.
Post-readiness publication errors are not silently retried, and completion after
the startup deadline cannot be reported as successful startup.

Explicit `lan.validator_open` and `lan.observer_open` can replace a failed/closed
in-memory profile with a revalidated instance of the same stored identity. They
stop the previous controller first, preserve the previous public binding if open
fails, reject a changed identity/anchor, and start no SDK. Failed cached profiles
require this explicit reopen before another start. Closed observer controllers do
not continue enrollment work during a failed reopen. Hidden portable-password
handling remains in the shared terminal service; secrets are never arguments.

## Evidence and scope

Actual encrypted profile tests cover fresh release, live-child refusal, existing
history preservation, one-use reservations, possible writes, cold/older intents,
unknown commits before/after the claim and abort, and reopening without changing
protected identities. Real OS pipe/process tests use public fixture input only;
their fake SDK readiness is explicitly a policy boundary, not consensus evidence.
They cover durable intent before input, failed preparation/spawn/containment,
post-claim pre-input cancellation, real blocked pipe timeout/cancel, partial input,
terminal handles and unchanged metadata. Native Windows owner tests also hold the
real owner database lock during close and verify immediate role/RPC/proof cutoff,
exact child termination and an unaffected sibling. Other platforms do not acquire
Windows enforcement merely by running a Python policy test.

Separate genuine pinned-SDK loopback runs exercised both source1/v4 and source2/v5
sessions: three portable protected runtimes, four validators, late observers,
same-key restart and cold resume, real prior native test-currency transfer and
independent read-only observation. The source2 case also followed a real
5,000-transaction block and closed segment. Each fixture reached at most six
simultaneous SDK children; concurrent fixtures are separate tests on one Windows
host, not independent physical machines.

An additional real-SDK fault run injected containment failure before validator
input and exact observer cancellation after its durable claim but before input.
Both retried successfully with the same protected keys/grant; no direct grant
insertion was used. Another real-SDK run committed an observer start but lost its
acknowledgement: explicit reopen recovered the actual committed flag and continued
to reject missing history, including after cold owner restart, while a different
healthy observer and the committee continued and resumed normally. Exact owned
children were terminal after cleanup.

Real SDK fault tests on both session formats also terminated exactly one of four
validators. The remaining three continued to form quorum; the terminated member
reported its fault while the historical certificate remained valid. Explicit
same-profile restart preserved keys, accounts and monotonic signing-state height.
This tests the fixed lab committee, not independent public operator resilience.

Native/SDK/WASM source fingerprints and wire formats are unchanged. The existing
four native artifacts, WASM, native test receipts and scoped Ghidra evidence are
reused only with exact provenance checks. This Python lifecycle change is not a
new native build, whole-binary audit or universal security proof.

## Remaining original work

Linux/Termux OS resource enforcement and physical fault/endurance/power-loss
acceptance remain to be established. Windows job bounds do not claim to protect
those platforms. Deployed legacy schema coverage, complete monetary/mining/pool
rules, target capacity measurement and production-like public testnet/mainnet
readiness remain open. Public activation still requires its separate concrete
decision. Combined GitHub publication waits for the coherent code phase.
