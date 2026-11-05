# Portable selected monetary history and explicit application recovery

## Original intent

Recover the actual selected monetary history and account state from original
signed payments and producer blocks. Preserve owner identities and receipts;
never let a snapshot, transport acknowledgement or UI counter stand in for
execution or consensus. The full eight-step delivery/capacity/public-security
contract remains unchanged.

## Findings and decisions

Final account equality alone does not authenticate the SDK height at which an
otherwise valid financial package was selected. An adversarial test moved a
package between an empty and nonempty application height, rebuilt the internal
journal hashes and retained the same certified final account state. The first
experimental archive reader accepted that altered schedule. That test is
retained as a regression; the experimental format was not published.

The archive now carries the canonical SDK header chain from height one through
the final proof header. The final separately pinned quorum certificate commits
to that chain through LastBlockID. Each package's exact bytes must match its
SDK block's DataHash, its journal timestamp must match the SDK header time, and
each reexecuted application state must match the following header's AppHash.
The final header must match the pinned certificate. Unknown fields, missing
heights, foreign genesis, certificate rollback/conflict, trailing data and
changed originals fail verification. Original account/producer signatures and
all monetary transitions execute through the existing native kernel.

Native export opens the selected financial journal and SDK block metadata in
read-only mode. A busy source is refused; no automatic app/node stop occurs.
Restored application stores retain their authenticated public headers so they
can be exported again without a private consensus database. Candidate input,
private key files and cached receipt/index values are never copied as history.
Receipt indexes and creator views are derived again from the originals.

Application recovery uses an explicit local store-v2 recovery record. It binds
the complete archive, trusted final certificate and intended height. Every
selected journal entry and its next public header commit atomically with the
derived account/receipt indexes. A partial store cannot open in normal mode.
Resume replays its retained prefix, compares exact journal/header bytes and
extends only the same archive/certificate intent. It does not delete, truncate
or silently repair a failed prefix. Completion is a synchronous metadata
transition after the entire archive and final certificate match. Old store-v1
data remains readable without implicit conversion.

## CLI and ownership

Offline CLI operations derive trust from an existing protected node profile:

```text
lan.financial_history_export profile=OwnNode observer=HistoryObserver path=/public/history.ggfin
lan.financial_history_export profile=OwnNode validator=OwnValidator path=/public/history.ggfin
lan.financial_history_verify profile=OwnNode path=/public/history.ggfin
lan.financial_history_restore profile=OwnNode path=/public/history.ggfin destination=/public/recovered-application
```

Choose exactly one owned validator or observer for export. A nonvoting observer
can supply the offline source without stopping validator votes elsewhere.
Operations use the existing protected unlock and stop/cancellation boundaries;
they do not ask for internal identifiers or approval tokens. Destinations inside
protected node/validator/observer profile roots are refused. Verification and
recovery enforce the owner's stored certificate floor. Export is historical and
read-only and cannot lower that floor. Successful recovery saves the exact native
verified public certificate; a lost reply can be retried against the same
completed target. Source keys, descriptors and producer journals are not replaced.

The Linux child uses the existing resource launcher before reading its request.
Only explicit history modes are accepted as additional arguments. The owned
lease, cancellation checks and operation deadline remain active. No private
signer enters the native archive request or an artifact.

## Evidence and unresolved requirements

Native tests exercise actual signatures, SDK header hashes, original execution,
source immutability, rebuilt receipts, prefix/completion I/O uncertainty and
corrupt persisted header evidence. Python tests explicitly mock the native child
where they test ownership, unlock, path and dispatch policy; those passes are not
cryptographic or live-consensus evidence. Actual SDK process, Linux, packaged CLI
and broader regression results are separate release checks.

This restores the monetary application store. It does not restore validator keys,
private signing counters or the SDK consensus database, and it does not declare
a native node ready to vote. The pinned
[CometBFT v0.40 application requirements](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_app_requirements.md)
and [expected recovery behavior](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_comet_expected_behavior.md)
require agreement between application and consensus state. Coupled node recovery
and archival availability remain required before claiming that wider outcome.

The final certificate is historical evidence, not network liveness. Sustained
5,000-payment blocks at the agreed hundreds-of-blocks/s rate, storage endurance,
cross-cut slow-producer recovery, general accounts, public economic policy,
independent security acceptance and physical device tests remain open gates.
No public testnet/mainnet activation or Git publication follows from this file.
