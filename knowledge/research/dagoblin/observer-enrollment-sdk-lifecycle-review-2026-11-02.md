# Authenticated observer enrollment and SDK lifecycle review

## Original intent and scope

CLI owns the real activity; Desktop must represent actual node/producer
ownership, connection, execution and historical observations. A slower optional
node must not acquire a vote or become an extra committee barrier. Finish the
coherent code phase before publishing the combined GG-W/CLI update.

This stage adds the authenticated backend enrollment path and fixes a concrete
SDK resource failure it exposed. Automatic observer commands and the complete
CLI/Desktop role/liveness display remain a subsequent part of the same task.

## Findings

The existing LAN has owner-authenticated, signed, session-bound frames,
connection pacing, ingress credits, handler ceilings, deadlines and stop-owned
sockets. A dedicated OBSERVER_ADMIT operation now carries the public grant;
it is not disguised as a proof or a proposal. The authenticated sender must be
the signed grant owner. The installed signed session binds its producer,
endpoint and immutable native genesis. Only actual already unlocked, owned,
bound validator profiles are eligible writers.

The request handler queues at most six immutable delegations and replies WAIT.
The existing owned validator loop commits them and publishes the native public
peer cache. READY names only the validator profiles whose actual persistence
operation succeeded. The receipt explicitly does not prove native connectivity
or finality. It opens/unlocks/starts no validator and changes no committee,
allocation or producer eligibility. Exact idempotent ACK polling cannot consume
the fresh-signature budget and starve itself while storage is slow. Changed
grants and changed session bytes never use that verified cache.

The first actual partial-admission test failed. A fresh observer was admitted
to one committee owner's two validators while the other owner still rejected
its connection. The observer reached its unchanged 512 MiB private-commit limit
before completing block sync. The failure and subsequent bounded diagnostics
were retained; every run terminated its owned children.

Sanitized diagnostics retained only fixed error markers, function names and
numeric resource counters, never arbitrary stderr, buffers, keys or arguments.
They located the failed allocation in SDK MConnection channel creation during
reconnection. One trace counted hundreds of mempool broadcast and consensus
query workers. The observer reached 512 MiB while the whole owned job peaked
around 1.3 GiB, well below its 3 GiB cap. This was the observer's own limit.

The pinned CometBFT 0.40.0 source showed two relevant lifecycle problems:

1. Mempool broadcast waited for block sync without selecting peer.Quit, retaining
   disconnected peer objects/buffers. Its peer-state readiness loop also lacked
   cancellation before consensus supplied state.
2. A handshake can succeed locally and be rejected immediately by the remote
   peer filter. A successful dial resets the reconnect routine, so failure-only
   backoff does not bound this repeated success/disconnect path. Reconnect
   registration also used separate Has/Set calls.

## Decisions and implementation

Keep the 512 MiB process limit and the peer filters. Add cancellation to both
mempool waits. Serialize per-peer reconnect registration and add the existing
five-second reconnect interval before the first reconnect attempt, with
immediate cancellation on switch stop. Initial configured peer dialing is
unchanged. Consensus rules, message formats, signatures and voting power are
unchanged.

The SDK remains the same pinned upstream version. The existing two resource
patches and four exact lifecycle hunks are applied to a separately verified
derived module tree. The upstream ZIP/cache is not edited. Every ordered hunk,
input/output file and complete derived tree is integrity checked; the scope
guard rejects reordered, duplicated or caller-selected transformations. The
scope includes resource/lifecycle code only, not an arbitrary patch facility.

Both native and WASM source fingerprints changed because their dependency
recipe is part of the build identity. Fresh candidates were therefore built
for Windows AMD64, Linux AMD64, Linux ARM64, Android ARM64 and WASM. No installed
runtime binary was replaced. Compilation is not physical-target execution.

## Verified results

- Sixteen enrollment tests passed using actual encrypted leased profiles and
  actual signed TCP where transport is claimed. They cover foreign owner,
  altered signatures/fields, missing/closed writer ownership, blocked storage,
  stop, uncertain commit/reopen, ACK context, six bounded slots, exact retries
  and session mutation.
- Seven tests ran in the actual derived SDK packages through a test-only Go
  file overlay. They cover peer/reactor cancellation during sync, cancellation
  before peer state exists, reconnect deduplication/stop, concurrent reconnect
  jobs and the existing receive-buffer ownership/bound. No SDK source cache was
  altered to inject tests. An earlier test-fixture initialization failure was
  retained before the corrected fixture passed.
- The complete ordinary native Go suite passed 683 tests with zero failures
  or skips and unchanged native sources.
- A fresh actual test used three portable protected runtimes, signed TCP grant
  requests and five SDK processes on one Windows host. The observer caught up
  after a real 5,000-TX block and a segment cut while only one committee owner
  had admitted it. The other owner's two validator profiles had no grant.
- The observer stayed alive for another fifteen seconds with those unadmitted
  persistent destinations. Its measured peak private commit was 191.23 MiB;
  the hard process limit remained 512 MiB. This is one bounded case, not an
  endurance or target-capacity measurement.
- The second owner subsequently committed and acknowledged the same grant over
  signed TCP. The SDK reached all four peers without restarting the observer.
  This is independent of the earlier ACK's limited persistence meaning.
- A separate actual current-binary regression executed 5,002 signed DAG TX in
  three blocks, one cut and a native test-currency transfer of seven atomic
  units. Late block/ABCI execution matched full native accounts/state; exact
  closed/current original bytes were retrieved. Stop and cold restart retained
  the same protected observer identity and caught up while the committee kept
  progressing. Six SDK instances ran, at most five simultaneously.
- Every successful owned SDK run ended with zero children remaining. These
  process tests do not establish physical Linux/Android execution, general
  full-history correctness, mining or financial mainnet readiness.

## Reverse engineering

Ghidra decompiled 1,689 bytes / 355 instructions from the current Windows
candidate's actual patched SDK mempool broadcast routine under bounded
memory/time. Go disassembly independently supplies the call/control-flow
context. The selected function's referenced code/global data and Go register
ABI are not reconstructed by that slice alone. This is executable evidence for
the reviewed lifecycle path, not a whole-binary or cryptographic audit.

## Remaining work in the original contract

Complete explicit runtime/CLI observer profile/start/stop/restore commands,
bounded automatic enrollment and native status observation, shared public
Desktop projection, and accurate separation of native full observer, sparse
proof reader, light client, validator and producer. An ACK, running process or
cached certificate must not be displayed as current native connectivity.

Review long-running containment: the existing shared native launcher still
uses the disposable-node CPU-time budget. The permanent-node policy and
endurance behavior need completing rather than silently raising test limits.
Deployed legacy-schema inventory, monetary/mining/pool rules, measured target
capacity, physical-device faults/power loss/endurance and separate public
activation decisions remain open. No app restart, device/bootstrap update,
public activation or Git push was performed in this stage.
