# Selected monetary history and coupled nonvoting observer recovery

Original intent: a slower or offline node must recover verified money and
history without gating other producers or changing ownership. CLI owns the
actual state and Desktop represents its verified observations. The complete
eight-step capacity/security/public-readiness contract remains active.

## Implementation and trust

Financial archive v2 preserves the same signed original packages and canonical
SDK header chain as v1 and adds the genuine SDK quorum commit at the recovered
application height H. The final separately pinned H+1 certificate authenticates
the entire header chain; its complete LastBlockID binds that prior commit.
Native replay checks original signatures, execution, each selected height/time,
DataHash and next AppHash. Fixed genesis consensus parameters and app version
are checked for every header. Validator proposer priorities are derived from
pinned genesis using the SDK's exact per-height transition, never copied from
untrusted priority metadata. This is the current immutable private committee,
not a specification for changing public validator membership.

V1 application archives remain readable and can still restore/re-export their
application store. They do not contain the missing quorum commit and cannot
claim SDK recovery readiness. Completed v2 application stores retain the commit
and authenticated public headers. Cold replay verifies that evidence again.
Later v2 exports combine retained old public headers with actual subsequent SDK
block metadata; no absent historical block body is invented.

`lan.observer_history_restore profile=OwnNode observer=OwnObserver path=/public/history.ggfin`
is an explicit offline operation for an existing owned observer profile with a
fresh target or a missing public SDK store. An existing target is never reset.
It first verifies the archive in the native kernel against the protected owner's
pin and the higher of the owner and observer certificate floors. It then commits an exact signed recovery intent in
observer profile v2 before native handoff. Existing v1 profiles remain readable;
only explicit recovery advances the profile schema. An incomplete recovery
cannot start, acquire a certificate, change archive or adopt another identity.
Uncertain profile commits are resolved by explicit cold reopen of actual state.
An explicitly restored missing public store retains the same protected P2P key
and previously verified certificate floor; it cannot restart from an older
archive or recover a validator signer. Pending recovery keeps the previous
historical certificate and blocks normal node start until completion.

The native request carries public grant/certificate data and an exact archive
binding. It carries neither a P2P seed nor a validator signing key. The target
is the exact leased observer's native root. The original monetary journal is
fully replayed into its resumable application store. A separate bounded public
intent database records monotonic recovery phases. The SDK's Bootstrap and
offline-state-sync APIs construct public state records. Exact SDK-generated
record inventories and their values are checked before completion and on retry;
an already used or changed SDK store is refused rather than reset or repaired.
The prior seen commit is synchronized before publication.

The public observer root identity is published last. Its bounded known staging
file may continue only an exact prefix of that same identity. A completed
publication can remove only its identical own staging hardlink. No failed
application/SDK prefix is deleted or truncated. Profile completion and the
owner's certificate floor follow native verification; a lost response can be
retried for the identical intent. A completed profile cannot rewind after it
has observed a newer certificate.

The normal observer launcher then uses the preserved P2P identity and ordinary
signed admission/start/catch-up path. Its public-only PrivValidator cannot sign
votes or proposals. Its root cannot be adopted as a validator. Recovering this
public state never reconstructs private validator signing counters or claims
current network contact. Historical SDK block bodies are not restored; selected
monetary originals and their derived receipts remain the application history.

## Evidence scope and remaining gates

Native tests cover genuine signatures/replay, prior-commit tampering, v1 read
compatibility, exact marker prefixes, changed intent/target refusal, corrupt SDK
inventory preservation, and interruptions before/after durable phase writes.
Protected Python tests cover exclusive owner/profile leases, signed intent,
unknown commit outcomes, retry, unlock, dispatch and exact child argument policy;
their native verifier is explicitly a policy seam. Separate private reports
record actual SDK processes, Windows/Linux runtime acceptance, broad regression,
packages, shared WASM verification and offscreen QML results. A test definition
here alone does not assert that those wider release gates passed.

The preceding research used a real 20,000-payment archive and the actual pinned
SDK to verify offline bootstrap handshake/start/stop with no private signer.
That isolated no-peer experiment is not live rejoin evidence. Physical Termux,
power-loss/endurance, capacity, general accounts, public issuance/fees/mining/pool
rules, Sybil defense and independent security acceptance remain distinct gates.
No root-key reset, app restart, public activation or Git publication is implied.

Primary references:

- [Pinned SDK offline bootstrap](https://github.com/cometbft/cometbft/blob/v0.40.0/node/node.go)
- [Pinned state provider and height mapping](https://github.com/cometbft/cometbft/blob/v0.40.0/statesync/stateprovider.go)
- [SDK application crash-recovery contract](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_app_requirements.md)
- [Prior state-sync validator inconsistency](https://github.com/cometbft/cometbft/security/advisories/GHSA-g5xx-c4hv-9ccc)
