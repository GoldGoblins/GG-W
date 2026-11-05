# Protected financial own-original storage and recovery

## Original intent and boundaries

Keep an independently owned producer running beyond one active journal window,
retain every exact signed original and signing context, and recover without
signing a replacement for an earlier creator/epoch/sequence. CLI remains the
authority; Desktop observes its account and ownership evidence. This is own
producer storage, not a replacement for global monetary history or the SDK
validator consensus store. No public network or economic policy is activated.

## Findings and decisions

The preceding v5 journal kept all originals in one 8,191-record/512-MiB active
SQLite window. A protected v6 journal retains the same original append digest
and moves old raw data into bounded immutable chunks. Its SQLite index keeps
the exact creator, epoch, sequence, original hash, context hash, raw hash and
bounded file offsets, plus authenticated parent/rank facts. No counter stands
in for an original. The index is checked against every archived original at
cold opening; loading an old original checks its exact raw and business hashes.

Each chunk preserves canonical original metadata, original wire bytes and exact
SDK signing contexts. The complete file hash, previous chunk and global append
heads bind the chain to the sealed owner/source state. Verification authenticates
the file before parsing, then rehashes the parse pass. Records are streamed;
prefix verification uses bounded earlier-original lookups. Context-offset maps
are bounded per chunk.
Earlier own-prefix facts use indexed disk lookups into positions already checked
by cold replay. They do not require retaining all old originals or references
in RAM. Producer signatures and SDK certificate checks retain their roles.

Before publishing a chunk, the owner commits a sealed pending intent. The file
is written, flushed, fsynced and fully read back. Immutable publication uses a
same-directory exclusive hardlink; a pre-existing final file must verify.
Only then does one sealed SQLite transaction add the compact index and archive
chain entry and remove the active raw rows/contexts. A live owner faults on an
uncertain result. Cold opening can finish the exact pending operation from
retained SQL originals or use an already committed complete transition. Even
an empty/truncated pending file is recoverable; a corrupted published archive
fails closed. No unowned path or recursive cleanup is involved.

Automatic retirement reserves room for an eight-block own pipeline. Pending
originals may also be archived: retries retrieve their exact wires and future
children retain their original references. A certified cut selecting only part
of an old epoch does not erase its unselected originals. New epoch signatures
follow the real SDK-selected sequence, and both epochs remain distinguishable.

Existing v5 financial profiles remain readable. When their exclusive producer
writer opens, it validates the full old journal before atomically adding the
explicit v6 tables and sealed metadata. It preserves descriptor, encrypted keys,
SDK floor, append head, original signatures and contexts. It does not reinterpret
an old raw-wire column as an archive pointer or silently repair a malformed DB.

## Verification scope and remaining requirements

Policy tests use actual protected profiles, account/producer signatures, SQLite
and filesystem publication, with the SDK verifier explicitly mocked. They cover
cross-chunk prefix extension, hot-window retirement, cold exact-original reads,
old v5 reading/transition, partial selection across epochs, cancellation,
same-size corruption, missing files, compact-index tampering, extra hardlinks,
partial pending files and both uncertain retirement-commit outcomes. Genuine
SDK execution/certificates, Linux filesystem execution and full regressions are
separate evidence; a unit pass does not establish those wider scopes.

The fixed-size active window is no longer a lifetime original-count bound.
All archives still consume real disk and the compact SQLite index still has
its configured size ceiling. Infinite retention or public archival availability
is not claimed. Whole-disk rollback requires an external trusted checkpoint.
Portable global monetary history, validator recovery, slow-producer liveness
across cuts, sustained capacity, physical device acceptance and public monetary
policy remain separate release gates.

The pinned [CometBFT v0.40 application requirements](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_app_requirements.md)
require a trusted chain-header basis for state sync and distinguish restored
state from available historical blocks. The pinned
[expected behavior](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_comet_expected_behavior.md)
requires agreement between the application and consensus state at recovery.
Accordingly, an own-original archive does not authorize snapshot-only validator
bootstrap or replacement of validator signing state.
