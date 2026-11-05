# Native full observer: local code and execution review

## Original intent

CLI owns the real node activity; Desktop must represent that activity and its
actual ownership accurately. A slower optional node must make progress at its
own pace without becoming an extra quorum dependency. Preserve existing
producer ownership, protected identities and history. Finish the coherent code
phase before the combined GG-W/CLI publication and physical-device test.

This review covers native observer identity, admission, execution and restart.
It does not finish the full network, monetary, mining, pool or capacity work.

## Findings

The pinned CometBFT 0.40.0 constructor and RPC paths require a non-nil public
validator interface even for a nonmember. Passing nil would panic. The native
observer therefore supplies an interface containing public bytes only;
SignVote and SignProposal always return an error. The observer's protected
private P2P key is used by the separate P2P transport. No validator or native
account private key is generated for this profile.

Committee-only peer filters previously prevented a genuine optional native
observer from joining. A separate bounded public capability now proves node,
LAN owner and registered producer key possession in distinct signature
domains. Python also verifies the owner/producer/host mapping against the
signed LAN roster. An optional replica's registered reserved producer key can
delegate read-only access without gaining producer eligibility or a vote.

Admission is persisted in the existing protected validator profile before its
public native peer cache is published atomically. A failed cache publication
can be retried from the exact committed metadata. The native filter validates
the whole capability content and permits the immutable committee even when
the optional cache is absent or invalid. Limits remain six grants, one per
registered producer, with distinct node identities and endpoints. There is no
automatic key rotation or public permissionless admission in this policy.

The new observer bootstrap rejects validator seeds, validator indices and
caller-supplied verification flags. One native root marker binds role, P2P
identity and immutable genesis. Validator and observer roots cannot adopt one
another. State sync and external validator signing remain disabled.

The first actual integration attempt also exposed an existing source2 initial
proof problem: CometBFT interprets an ABCI height selector of zero as latest,
not as an immutable genesis snapshot. Exporting a proof for an initial
certificate now returns an explicit initial-wait result before querying that
selector. A positive height must be available. Policy tests cover both the
initial refusal and independently pinned subsequent reads.

## Verified results

- 683 native Go tests passed, with no failed or skipped tests and unchanged
  native sources. The observer-focused subset contains 22 passing cases.
- 71 focused Python policy/profile tests passed, including 24 observer tests
  and the new initial-proof regression. These use actual protected storage;
  controller tests label their mocked SDK boundary explicitly.
- Fresh native candidates compiled for Windows AMD64, Linux AMD64, Linux ARM64
  and Android ARM64. Linux and Android execution was not tested here. The WASM
  verifier was reused only after checking its exact shared-source fingerprint.
- A real isolated source2 committee executed 5,002 signed DAG transactions in
  three blocks across one closed segment. It also executed one actual native
  test-currency transfer of seven atomic units before the observer joined.
- A fresh native observer joined late, executed SDK blocks, and returned the
  same pinned full native account state and state root. Complete original bytes
  for the 5,000-transaction closed block and current blocks were retrieved from
  its own native store and matched the producer's exact originals.
- The committee continued while the observer was stopped. The observer then
  reopened its same protected ciphertext/key and native root, caught up, and
  returned the same subsequently certified state and original bytes.
- The observer had zero voting power, was absent from genesis validators and
  commit signers, and created no validator private-key or signing-state files.
  Six SDK process instances ran in total, at most five simultaneously, on one
  Windows host. All owned children were terminated at the end.
- Eight actual native startup attempts rejected secret/index injection,
  caller verification flags, altered genesis/node identity, invalid owner
  possession, fresh-root reuse and validator adoption of observer history.
  The closed observer native history stayed byte-identical after every case.
- Native and WASM verifiers agreed on two actual SDK certificates and rejected
  ten explicit mutations involving genesis, height, header, quorum or a caller
  verification flag. A certificate alone is not full-history replay evidence.

The successful SDK run retained two earlier failed attempts: the initial
height-zero proof failure and a test harness assertion that incorrectly
expected SUBMITTED instead of the existing MEMPOOL_ACCEPTED response. Both
failed runs terminated all children and preserved their receipts. Mempool
acceptance remained distinct from actual SDK selection in the successful run.

## Static reverse engineering

Ghidra decompiled the current candidate's actual SignVote machine-code slice
under bounded memory/time limits. Go objdump independently showed two loads
of the constant rejection error interface followed by RET, with no call.
The slice is 15 bytes / three instructions. Ghidra did not reconstruct the Go
two-register error ABI or the referenced global data; the source and Go
disassembly were needed to interpret the result. This is limited executable
evidence for that method, not a whole-binary audit or a security proof.

## Decisions and remaining work

Keep separate profile and bootstrap types for validator and full observer.
The observer controller reuses the owned native process, exact listener,
binary receipt, lifecycle and bounded RPC machinery, and refuses transaction
submission through its own RPC API. Certificate floors are saved before
publication. Verified conflicts persist and block restart. Restored
certificates are explicitly historical, with no network-liveness claim.

The new backend ownership and execution path is not yet a user-facing
automatic CLI/Desktop observer feature. Add bounded authenticated LAN grant
enrollment, shared runtime commands/lifecycle/observations and accurate UI
roles next. Test independent process observation without taking ownership or
adding a quorum barrier. Preserve slow-node cancellation and resource bounds.
The current full-history UI flag intentionally stays false; the concrete
pre-start transfer and block replay case does not prove every history shape.

Physical Windows/Linux/Termux execution, deployed legacy-schema inventory,
long-running failures/power loss, complete monetary/mining/pool rules and
measured target capacity remain open. No 200-block/s or mainnet-readiness
claim follows from this small isolated test. No active Desktop restart,
installed-native replacement, physical-device update, bootstrap distribution,
public activation or Git push was performed in this stage.
