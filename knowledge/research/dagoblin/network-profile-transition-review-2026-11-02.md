# Preserved legacy network history and explicit profile transition

## Original intent

Software updates must preserve genuine blocks, owners, signing identities and
history. CLI node activity remains authoritative for Desktop observation. A
new network must not acquire fake historical counters by relabelling originals
from a different genesis or resetting an existing validator's signing journal.

## Facts and supported transition

The old private source1/v4 LAN and the segmented source2/v5 LAN have different
execution and cryptographic domains. This operation explicitly moves the same
protected node identity into the new signed test network while archiving its
old network under the old domain. It is not an in-place consensus hard fork,
financial balance migration or permissionless mainnet upgrade.

A coordinator-signed document binds the exact old native genesis to the exact
new signed session. All three owner transport identities, producer keys,
pairing nonces, endpoints, labels and participation roles must match. Native
chain IDs must differ. All four target validator/node/account key sets must
be disjoint from the old committee. Old ValidatorProfiles, native roots and
anti-double-sign state are preserved rather than reset for a new genesis.

Preparing public invitations or a document changes no old session binding.
Fresh unbound validator profiles can be prepared from a genuinely opened
protected owner offline; no connected peer or network listener is fabricated.
The same preparation functions serve the shared runtime and headless CLI.

## Original replay and public archive reader

The reader holds a checked regular-file handle and verifies its protected
file pin before and after reading. It rejects links, hardlinks, wrong owners,
unknown SQLite schemas, oversized values and malformed counter types. It uses
read-only immutable SQLite, verifies the owner-signed raw metadata binding,
and replays the actual old DAG signature, genesis, causal and nonce rules.
Metadata/table integrity cannot substitute for protocol validation.

Original payloads remain on disk with a bounded index and zero hot payload
cache. Existing memory/CPU governors and cancellation checks apply. Stored
scan/order metadata is structurally replayed; every retained SDK certificate
also passes the current exact native cryptographic verifier. A structural
certificate cache alone grants no authority. The reader never decrypts keys,
returns a writable profile or starts a consensus/network process.

The receipt distinguishes original admitted history and verified retained
certificates from complete canonical-history replay, native monetary transfer
replay, current network freshness and an external whole-disk rollback anchor.
Those stronger properties are not asserted.

## Atomic transition and recovery

The operation acquires the real protected profile lease and requires the old
peer to be stopped. It does not stop another owner implicitly. Full original
admission and stored-certificate verification precedes its first transition
write. A signed pending intent commits the exact source head and target. While
pending, ordinary startup cannot obtain the node signers for the old network.

A bounded SQLite backup retains the old journal, metadata and encrypted key
envelopes. The completed archive is synced, independently replayed and pinned
in protected metadata before the active journal changes. Only disposable,
explicitly owned staging files may be recreated after an interrupted backup;
the authoritative source and completed archives are never repaired or truncated.

One synchronous SQLite transaction replaces the active network namespace,
preserves the identical protected owner keys, clears old current-network cache
and journal tables, and binds the new session with an empty current journal.
All old originals remain in the authenticated read-only archive. Old balances,
counts, scan cursors and certificates do not become new-network authority.

A crash or unknown commit acknowledgement closes the handle. Reopening resolves
the actual old, pending or completed state. Resume rechecks the original head,
document and completed archive. A different target or corrupt completed archive
fails closed. An exact completed request is idempotent. Startup validates the
preserved archive before exposing signers for the current network.

## CLI and lifecycle

The shared operations are `lan.validator_transition_create`,
`lan.transition_invite`, `lan.transition_prepare` and `lan.transition_commit`.
Offline preparation supplies `owner_profile`; invitations/documents can be
exported to ordinary public files. Commit accepts exactly one document or file
path and a finite timeout. It closes its owned handle and starts no network.
Explicit `lan.resume` and opening the new validator profiles follow separately.

Portable password input remains hidden and requires genuine terminal streams,
including for JSON-producing offline commands. No password or private key may
be supplied as a command argument or serialized in the public document. Runtime
stop cancels owned work and releases busy state without deleting original data.

## Verification gates and limits

Focused tests exercise real protected profiles and signed original transactions,
5,000-transaction history, offline/active preparation, distinct domain and
membership rules, owner preservation, real leases, every backup/publication/
commit barrier, actual committed-but-unacknowledged SQLite writes, restart,
target drift, corruption and the portable scrypt/AES-GCM path. Mocked verifier
or process seams are explicitly labelled as policy evidence.

The actual SDK gate uses three shared signed-TCP runtimes on one Windows host:
the old committee genuinely selects history, all owners stop and transition,
and a distinct new committee genuinely selects new originals. It must prove
unchanged old native/signing state, unchanged owner ciphertexts, zero imported
old counters, real SDK rejection of old-domain originals, new-owner recovery
after a cut and identical current observations in a separate public reader.
The frozen stage checkpoint records the outcome and exact source/artifacts.

Compilation and local execution do not prove physical Linux/Android behavior,
independent operator fault domains, power-loss behavior or sustained capacity.
Native observer membership, independent complete client replay, financial
consensus/mining/pool/reward rules and the measured throughput/endurance gates
remain required. Public testnet/mainnet activation remains a separate concrete
decision. The complete delivery is not ready merely because this stage passes.
