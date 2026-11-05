# Owned observer controls and shared public observations

Original intent: CLI owns the real work; Desktop displays the same node/account
facts. Optional slower nodes must not become extra quorum dependencies. Preserve
protected keys, producer ownership and durable history before the combined
GG-W/CLI publication and physical-device run.

## Implementation and evidence

Explicit `lan.observer_create`, `observer_open`, `observer_start` and
`observer_stop` commands share one runtime implementation. A full observer has
only its protected P2P key, a signed owner/producer delegation and zero voting
power. At most two local profiles use distinct delegated producer slots. The
observer is not the owner of a producer's blocks and does not increase the
four-member committee or its three-vote quorum. A light role cannot start one.

Two bounded owner-lifetime workers separate actual SDK status/certificate reads
from authenticated grant enrollment. Enrollment retries only the same immutable
public permission; it does not retry financial transactions. An admission ACK
is neither native contact nor finality. Status validates the actual SDK node
identity, zero voting power, committee peer IDs, height and sync state. Missing
byte counters remain unknown. Flow-monitor totals cover current peer
connections, not lifetime traffic. Unexpected exit is a fault, never an
automatic native restart. Historical verified certificates remain separate
from current contact and locally executed reads.

Real isolated loopback runs exercised both signed source1/v4 and source2/v5
sessions. Each used three portable encrypted owner profiles, four actual SDK
validators and up to two managed full observers. The observers joined late,
executed the same native state (including a prior seven-atom test transfer),
stopped independently, restarted and resumed with the same protected key,
grant and native history. The source2 case also followed a real 5,000-TX block
and a closed segment. Enrollment used the signed LAN command path without
injecting grants directly into validator profiles. A separate reader process
received the exact public native view, then marked contact stale while retaining
the historical certificate. These are software/loopback results on one Windows
host, not measurements of three physical operating systems or target capacity.

The CLI Publisher/Desktop Reader shares these public observations without
opening another key profile or starting a second SDK. Stale publication clears
current connectivity and local-execution claims; whether its native process
still runs becomes unknown. Qt offscreen checks cover native sync/contact,
fault/stale presentation, exact large counters and read-only CLI ownership.

Persistent SDK children now have a separate lifetime policy. Windows queries
and verifies a shared owner CPU-rate job (default 100%, not accumulated CPU
seconds), a six-child ceiling, kill-on-owner-loss and separate 512-MiB/one-process
leaves. Other owners and the app process are outside that owner job. Disposable
test containment retains its finite CPU-time limit. Parent jobs can impose
stricter limits. Non-Windows OS resource enforcement is explicitly UNAVAILABLE;
normal exact-child stop and native parent-loss handling still apply. Native
Windows tests cover queried settings, memory/descendant limits, aggregate rate,
sibling isolation, failure containment and abrupt parent exit.

## Limits and remaining work

The native/SDK/WASM source fingerprint is unchanged in this control-only stage;
tests use the previously rebuilt and pinned lifecycle-fixed artifacts. The
earlier seven derived-SDK lifecycle tests and bounded Ghidra examination remain
scoped evidence, not a proof of whole-binary correctness.

A persisted native-start intent with missing history still fails closed. An
ambiguous interrupted first launch never silently resets its identity/history.
Recovery of that particular intent needs a separately proven lifecycle design.
This stage does not claim full-history coverage for every possible input,
long-duration physical endurance, deployed legacy schema coverage, permissionless
mining/pools/rewards, complete monetary policy, measured hundreds of 5,000-TX
blocks per second, public testnet activation or mainnet readiness. The original
eight-step objective remains open; publication waits for the coherent code phase.
