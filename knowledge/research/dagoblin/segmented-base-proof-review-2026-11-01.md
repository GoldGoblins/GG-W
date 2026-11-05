# DAGoblin: certified epoch bases and exact producer cardinality

Date: 2026-11-01. This review extends the segmented Python engine review.

## Original intent

Preserve the existing CLI/Desktop network while making its underlying behavior
real and independently verifiable. A slower device must be able to catch up
without resetting its owner, signing sequence or transaction nonce. Desktop
must eventually display the same certified account and creator information as
the CLI. This stage supplies a prerequisite for durable segmented operation;
it does not declare the network finished or authorize a public network.

## Findings

The full native SDK store already replays original signed closed segments and
the active tail. A lightweight producer or reader additionally needs the exact
selected epoch base. An inbound account snapshot cannot provide that authority.
Requiring every producer's Python profile to duplicate all global raw history
would also undermine the separation between full nodes and lighter devices.

A concrete decoder inconsistency was reproduced against the previous native
binary using a packet from the actual four-process SDK run: appending a seventh
author to the certified state and its membership contexts was accepted, while
the verified result contained only the first six authors. Python already
rejected this shape. This demonstrated inconsistent interpretation, not a
demonstrated financial theft or ability to forge a seventh owner's signature.

This behavior is consistent with the documented `encoding/json` v1 treatment
of fixed Go arrays. Our protocol has to require exactly six entries itself;
this is not a claim of an undocumented Go vulnerability. See the official
[Go JSON Unmarshal documentation](https://pkg.go.dev/encoding/json#Unmarshal).

## Decisions and implementation

`/gg/dag/base-proof` returns the selected commitment, exact last-cut preimage,
the previous closed-tree frontier, genesis, state height and state root. The
shared native/WASM verifier first checks the pinned SDK certificate and exact
current proof context. For a later epoch it verifies the canonical cut bytes,
their digest, the previous frontier root and the append that produces the
certified current closed root. It then derives the empty epoch base, including
the six account balances/nonces, creator sequences and global offsets. Genesis
uses the explicit source allocation, a literal null cut and an empty frontier.

The previous frontier has exactly 64 slots. The implementation validates unused
slots as well as the occupied peaks. Account totals, account Merkle root,
source, epoch progression, active-size bounds, nondecreasing counters and time,
and author progression are checked before returning a base.

The cached query view retains the immutable cut preimage and old frontier,
not a second old graph or a second copy of archived payloads. Four captured
contexts and four query credits remain bounded. Work runs outside the store
and consensus locks; an evicted context fails instead of returning a newer
epoch. Restart reconstructs the same view from original stored history.

`dagSegmentAuthors.UnmarshalJSON` now requires exactly six entries before
copying into the fixed array. This applies to the public state and nested
proof contexts in native and WASM. Existing valid six-author encoding is
unchanged. Canonical cut comparison also prevents an extra cut account from
being silently discarded by typed decoding.

Python's `verify_epoch_base` invokes the owned native verifier using the pinned
genesis, checks its derived output and returns an owned copy with explicit
scope. `export_dag_base_proof` obtains the proof and certificate from the same
owned SDK state height. Neither operation attaches a signer, imports a
NodeProfile or enables production from an archive view.

## Executed evidence

- 591 native Go test cases passed without failures or skips, with unchanged
  native source throughout the run. All 562 prior cases remain covered.
- Four fresh native targets compiled: Windows amd64, Linux amd64, Linux arm64
  and Android arm64. The shared WASM verifier was freshly compiled too.
  Cross-compilation is not execution on Linux or a mobile device.
- The four-validator SDK experiment ran 17 actual process instances on one
  Windows host. It selected 15,002 unique individually signed transactions,
  five DAG blocks and two cuts. Three validators continued while one was
  absent; that validator caught up. Hard restarts replayed original archives
  and accepted the exact next owner nonce and sequence. All owned children
  were stopped at the end.
- Six packets from that actual SDK experiment verified their epoch bases in
  native and Python. Four independently stored histories exported identical
  portable archives; five archive exports were verified through Python's
  native replay and mandatory file-hash/EOF boundary.
- The same 11 packets (five native-application test-signature vectors and six
  genuine SDK packets) produced identical derived bases in native, WASM and
  Python. Ninety-one negative cases were explicitly rejected by all three,
  including the saved seventh-author counterexample from the previous binary.
- 88 targeted Python/browser checks passed, including eight new adapter cases
  and a loopback viewer using an actual SDK v4 pin. Mocked adapter cases are
  projection tests; they are not counted as SDK consensus evidence.
- Existing separate WASM checks passed four legacy valid cases and 15 negative
  cases, plus five segmented valid case runs and 20 negative cases.
- Ghidra decompiled the actual current `main.derivedSegmentedBase` machine-code
  slice: 6,003 bytes and 1,212 Go-disassembly instructions. This bounded static
  inspection omits referenced function bodies and global data; Go's register
  ABI was not reconstructed. It is not a whole-binary security proof.

## Assumptions, limits and outstanding work

The new proof trusts the pinned SDK committee's selected cut and its committed
preimage. Its exact scope is
`SDK_CERTIFIED_CUT_PREIMAGE_AND_EPOCH_BASE_NOT_FULL_HISTORY_REPLAY`.
It does not assert that a lightweight client replayed every earlier original
signature. Full history replay remains a separate archive operation. The
producer-owned DAG transaction model remains explicitly nonfinancial.

Persistent LAN v5 negotiation, durable producer journals, native full-node and
observer roles, and Desktop bindings to that same authority are not completed
by this change. The archive-restored Python view remains read-only by default.
The disposable RAM producer experiment is explicitly limited to 16 MiB of raw
payloads; that is not a total process-memory or durable-resume claim.

Archive retrieval and storage policy, filesystem power-loss durability,
monetary issuance, fees, mining/pools, the physical-device capacity target,
endurance and public testnet acceptance remain open. A 5,000-transaction block
in these tests is not evidence of hundreds of such blocks per second. No
active Desktop restart, installed-tool replacement, device update, bootstrap
distribution, public-network activation or Git push was performed here.
