# Segmented original recovery and authenticated graph window

This stage extends the private nonfinancial LAN candidate. The whole delivery
remains unfinished and unpublished. Target capacity, physical Linux/Android
execution, full closed-history recovery and public monetary rules are not
established by the implementation or the bounded software checks below.

## Original intent

The node and CLI are the source of Desktop data. A selected block must retain
its actual creator and actual parent references in the visual representation.
A display position or a signed transport receipt cannot invent a causal edge,
network selection, local execution replay or another owner of an original.

## Native selected original retrieval

The existing bounded payload-chunk query now supports source2. Its compact
immutable proof views retain only selected body hashes, wire hashes and sizes;
they retain no raw blocks or old execution graphs. Epoch-local index and exact
SDK state select the original descriptor. Prepared, unselected proposals are
not exposed as selected originals.

At most two payload readers hold database snapshots. Snapshot acquisition and
reader registration occur under the store mutex; disk reads, wire hashing,
encoding and the test isolation hook occur after that mutex and the consensus
mutex have been released. A read already pinned before a cut can finish with
its original bytes. A request after the epoch retires returns unavailable:
this active-view endpoint does not claim to traverse a closed archive.

The payload cache has the existing 32 MiB/two-record bounds. The store rejects
new snapshot ingress before waiting for owned readers during close. It clears
the cache after their confirmed release. Corrupt selected original bytes fail
the store closed. A legitimate retired epoch does not poison a healthy store.

## Client authentication and resource ownership

Typed payload selectors pass through the existing authenticated private LAN
proof cache. Handlers serve cached bounded chunks or enqueue bounded work;
they do not call SDK RPC. Each chunk is pinned to the exact requested genesis,
SDK state root, height, body hash, local index and aligned offset. Canonical
base64, full wire descriptor consistency and per-chunk length are required.

A dedicated owned worker downloads to one temporary spool with a maximum
32 MiB declared original. The legacy whole-record/message limit does not set
this source2 original bound. The resource governor controls transfer work and
reserves decoding memory before rereading the stored bytes. Short or failed
writes close the untrusted spool before retry credit can be reused. Status
reads do not start a worker, open node keys or wait for signature validation.

Complete spool bytes must match their wire digest. Publication additionally
requires actual native verification of pinned SDK membership, exact canonical
body hashing and the creator's Ed25519 signature. The selected leaf must occur
in that verified proof, and its creator key must equal the signed source's
producer key. This authenticates display data; it does not claim that the
Python client independently replayed every transaction or all account history.

A newer independently verified proof for the same exact leaf can authorize
continued untrusted reads without rewriting the old proof or certificate. An
epoch/window change may retire an incomplete spool. It never delays validators
or another producer. Full cold recovery outside the bounded window remains a
separate required implementation step.

## Truthful Desktop representation

The graph retains at most 128 independently authenticated original headers.
Rows preserve their original certificate height, epoch, creator, global index,
sequence and actual causal rank. Edges are supplied only when both displayed
endpoints exist and the child original names that parent. Unknown parents
remain explicit missing references; they do not become invented block nodes.

Large ranks/sequences stay exact decimal strings. Separate bounded layout
coordinates preserve rank ordering without narrowing source counters through
JavaScript numbers. Labels, accessibility text and selection details use the
exact source strings. The new certified-original topology distinguishes its
SDK membership and signed-body scope from the older unfinalized local graph.
The public read-only CLI observation channel carries the same graph data.

## Evidence and limitations

The native suite covers a genuine 5000-TX original fetched in 32 KiB chunks,
native membership verification, full restart, staged-proposal rejection,
retirement, invalid selectors, cancellation, bounded reader admission, selected
payload corruption, a cut during a pinned read and close during a pinned read.
Python policy tests explicitly mock SDK-result boundaries and separately check
real creator signatures, spool integrity and exact source/graph projections.
Offscreen Qt tests instantiate the real graph component without restarting or
capturing the active application.

The actual integration driver requires protected shared runtimes and native
validator children, signed remote retrieval of a real 5000-TX original, an
additional SDK-selected causal child, matching graph edges across observers,
cuts, optional-owner restart and a separate read-only observation process.
Source stamps, failing attempts, final run results, fresh native/WASM build
receipts and the bounded Ghidra analysis are retained in the private
`segmented-payload-graph-v1` evidence directory. A compiled cross-target binary
is not an execution test on that physical target. Ghidra's selected-function
analysis is not a whole-binary security or cryptographic correctness proof.

Closed-archive network retrieval, preserved nonempty-v4 profile transition,
native observer membership, permissionless consensus/economics, mining/pool
accounting, sustained target capacity and physical fault/endurance acceptance
remain open. No active-app restart, installed-tool replacement, device update,
Git push or public-network activation belongs to this stage.
