# DAGoblin: protected producer journal across SDK cuts

Date: 2026-11-01. Extends the signed v5 session and certified epoch-base reviews.

## Original intent

Preserve real owner identity, signed history, sequence and transaction nonce
across restarts and segment changes. A slower producer must resume in its own
time while other nodes continue. CLI and Desktop must eventually observe the
same native authority, without treating an own-chain preview as global state.

## Findings and decisions

The native SDK is already the full global original-history authority. The
producer profile therefore stores its own signed proposals, not another copy
of every global block. Its two producer keys and transport key remain encrypted
in the existing exclusively leased NodeProfile.

Explicit activation on an empty compatible profile creates profile schema 4,
one `own_proposals` table and signed producer metadata in the same SQLite
database. Legacy profiles keep schema 3 and their existing history. A bound
foreign network, nonempty legacy journal, wrong role, wrong keys or missing
selected own signatures cannot be silently converted into a new signing state.

Every original proposal and its integrity head commit together before the
proposal returns to its caller. Recovery validates stored bytes, replays the
own-chain protocol and checks selected owner heads/nonces against the actual
pinned SDK base proof before attaching the existing producer keys. Pending
proposals are read back exactly; recovery does not sign replacements for them.

## Cut and crash behavior

An SDK-verified later base determines which own prefix was selected. A cut
cannot manufacture a missing own signature or reset a selected nonce. Original
unselected proposals also remain available as audit records, even when their
old epoch/precheck makes them ineligible for future selection.

Rotation first stops the old signing engine and commits an archive intent in
the sealed profile. The implementation streams bounded original wires into an
own archive, flushes it, verifies its content, publishes an immutable file and
only then commits the new base and clears the active own table. A crash at an
ambiguous boundary leaves either old rows plus the declared intent, or the new
base plus its published archive. Recovery may rebuild only the exact pending
path named by that sealed intent; it never overwrites an immutable archive.

Archives form a content-hash chain and are rehashed on recovery. They are own
journal archives, not public global-history proofs. The archive-restored global
engine retains its separate read-only default. The own-chain engine exposes no
global preview claim; its certified global commitment is a distinct SDK
observation, with no claim that a stored packet establishes current liveness.

SQLite keeps the existing exclusive locking, DELETE journal and synchronous
EXTRA configuration. SQLite documents both its atomic-commit model and the
extra directory synchronization used by EXTRA. Those mechanisms depend on the
filesystem, OS and hardware honoring their contracts; our executed process
and fault tests do not substitute for physical power-loss tests. See
[SQLite atomic commit](https://www.sqlite.org/atomiccommit.html) and
[synchronous settings](https://www.sqlite.org/pragma.html#pragma_synchronous).

## Faults reproduced and fixed

- A newly detected cold-payload corruption initially did not stop subsequent
  signing. The producer and parent profile now latch failure immediately.
- The shared profile writer could miss its failure latch if ROLLBACK itself
  raised. It now faults and restores its in-memory view before rollback cleanup,
  preserves the original write error and requires verified reopening.
- An already-cancelled observation could first persist a cut intent. Cancellation
  is now checked before verification effects and state transitions. Parent
  profile recovery also accepts a cancellation callback and releases its lease
  when interrupted; cancellation is not mislabeled as corrupt history.
- Corrupt SQLite identifiers and private JSON collections caused unnecessary
  allocations before rejection. Tests reproduced peaks of 8,396,243 and
  8,137,191 Python-traced bytes. SQL field types/lengths are now checked before
  retrieving their values. Private metadata bytes and the transport seal are
  authenticated before larger collections are decoded. Recomputing an unsigned
  binding does not bypass signature verification.
- Archive bytes are authenticated before collection decoding. A second pass
  checks the same file identity, size, modification time, whole hash and EOF;
  a replacement cannot borrow the first pass's authentication.
- The broad regression exposed an existing payload-worker status race: a bad
  chunk error became visible before its spool closed and credit was released.
  An event-controlled reproduction confirmed that order. Error publication now
  follows cleanup, while slow close remains outside the status lock. No invalid
  payload was admitted in the failing test.

These are scoped local integrity/availability findings. They are not claims of
demonstrated financial theft. Original failing observations remain preserved.

## Executed evidence

Forty-one focused tests passed without failure, error or skip: 26 new journal
cases and 15 existing protected-store cases. They cover real encrypted storage,
raw replay, duplicate writers, wrong slots, missing own history, an actual child
process exiting immediately after COMMIT, ambiguous append/cut outcomes, failed
fsync/rollback, archive cancellation/corruption/deletion/links/replacement, two
cut recovery, and encrypted-key persistence. Certificate-result seams in these
unit tests are explicitly mocked and are not counted as SDK quorum evidence.

Four focused allocation cases after the fixes peaked at 47,587, 476,611,
474,134 and 570,217 Python-traced bytes. These are allocation measurements for
the corrupt inputs, not resident-memory or whole-process bounds.

The separate hardened run used four actual SDK validators on one Windows host,
with signed v5 membership and 17 process instances across restarts. It selected
15,003 unique transactions into six DAG blocks and two cuts. The fast protected
producer closed/reopened its own journal before broadcasting the exact stored
5,000-TX proposal and again before later production. The original identity,
nonce, sequence, cut parent and precheck were accepted by every validator.

A second protected owner stored one pending transaction and remained offline
across both global cuts. On return its old original wire remained in its own
archive. The real SDK rejected that stale wire, then accepted its new valid
proposal with nonce 0 and sequence 1. That pending transaction had never been
selected, so it did not consume the selected nonce. In total 15,004 transactions
were locally signed, including that one retired proposal; it is excluded from
the 15,003 network-selected count.

The fast profile produced two own archives and retained one active own proposal;
the slow profile produced a separate archive spanning its offline interval.
Recovery ran with a zero-byte hot payload cache. Five separate global portable
archive exports also replayed successfully: four independent stores at 10,001
transactions were identical, followed by a two-cut export at 15,001. Those
exports do not claim a final global archive at 15,003.

Native/WASM source did not change in this stage. Tests use the exact previously
compiled artifacts with integrity checks. Prior native Go/Ghidra evidence
applies to those unchanged native sources; it is not relabeled as a fresh build
or a whole-binary audit.

## Bounds and outstanding work

The active own journal is capped at 4,095 proposals and 512 MiB of raw wires,
with at most 32 MiB per wire. This is not a total RSS bound. Archive writes
require measured free disk space plus a reserve, and unsupported hard-link
publication fails closed. Closed own archives remain on disk; retention,
retrieval, pruning and long-history startup policy still need their own tests.
Restoring a whole older valid disk image is not solved by a local signature.

This stage supplies the durable producer library and its explicit profile
version. It does not activate the legacy LAN runtime for v5 or migrate an
existing nonempty v4 profile. Owned SDK/controller lifecycle, signed v5 runtime
negotiation, full-node observer membership, network-profile migration and Desktop
bindings still need integration before the next physical network run.

Linux/Android execution, physical power loss, sustained target capacity,
monetary issuance/fees/mining/pools, endurance and public-network acceptance
remain open. No active Desktop restart, installed-tool replacement, device
update, bootstrap distribution, public activation or Git push occurred here.
