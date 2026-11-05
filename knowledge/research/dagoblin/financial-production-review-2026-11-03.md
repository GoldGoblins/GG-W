# Session-bound monetary production and honest observations

## Original intent and scope

Retain DAGoblin's independent producer identities and CLI-owned node operation.
Execute real account-signed payments in the native ledger, retain the original
creator signatures, and let Desktop observe the same account state and block
owners without creating a second wallet, producer, or consensus authority.
This stage is a private-LAN implementation, not public economic activation.

## Findings and decisions

Financial source v1 did not explicitly bind the signed LAN namespace. Source v2
binds the nonce, signed roster, role assignments, coordinator and session label
through its network identifier and native genesis. The original v1 bytes remain
unchanged. Producer keys, account keys, native peer keys and validator vote keys
have separate roles; owning a producer never grants ownership of its validators'
account funds.

The native verifier checks a certified producer context before signing. The
context authenticates the current epoch, creator sequence and actual causal
parent, including an authenticated history witness for an active creator.
The certified cut metadata supplies the parent for an idle creator after a cut.
ABCI query height zero means latest state, so it must not be used as a query for
genesis state. This distinction was found by an actual four-node test.

The protected schema-v5 producer journal atomically retains the exact original
block and its certified signing context before transport. A retry of the same
creator/epoch/sequence returns that original only for the same payment intent.
It rejects conflicting signatures, unknown selected own heads and stale shared
certificate floors. Originals are not replaced by counters or cached snapshots.

Signed LAN transport carries originals to native SDK admission. Queue and
mempool acknowledgments explicitly assert neither selection nor payment
execution. Execution and rejected-payment outcomes come from the SDK-certified
account state and independently verified receipt. Generic count-only stress
cannot manufacture financial payments. A bounded public payment file can carry
more than the ordinary 16-KiB command limit; every account signature and the
network anchor are checked, while the command limit remains unchanged.

Receipt and producer proofs must match the exact requested block/index or
creator index, in addition to passing native proof verification. A valid proof
for another selector is not an answer to the request. The read-only projection
keeps at most 128 verified receipt summaries and fetches at most one new creator
head receipt per observation. It reports creator identity and selected position,
without inventing original payloads or causal graph edges.

CLI/Desktop observations preserve exact counters and uint64 account nonces as
decimal strings. Historical verified certificates do not assert live contact.
Desktop reads the existing same-user CLI publication; it creates no signer or
command channel. Financial accounts are separate from the older producer test
accounts. QML displays applied and rejected payments, own certified account state
and signed roster names. A native full observer has no vote or submission right.

## Verification boundaries

`tests/test_financial_session.py`, `test_financial_wire.py`,
`test_financial_authority.py`, `test_financial_producer.py`,
`test_financial_proof_sync.py` and `test_financial_runtime.py` cover binding,
storage, input authentication and routing boundaries. Tests that mock an SDK
boundary explicitly are not cryptographic or live-consensus evidence.
`test_local_node_observation.py` and `test_financial_dashboard_ui.py` exercise
the actual read-only publication and offscreen QML. No live app capture or
restart is required. Native financial tests exercise the shared native/WASM
kernel; actual SDK process and signed loopback LAN tests are separate evidence.
Candidate Windows, Linux, Linux arm64, Android and WASM builds are distinct
from installed tools and physical device execution.

The actual signed-loopback integration executed 5,000 independently signed
payments through the CLI public-file command, four native validator processes
and a fifth native full observer. All three paired client publications matched
the SDK accounts and exposed the selected creator through verified receipts.
The observer followed that account state with zero voting power and rejected
submission. An actual valid receipt for the wrong requested index was rejected.
The three resulting public observations also passed the actual offscreen QML
fixture. These are local process tests, not physical Linux/Android acceptance
or throughput measurement. A failed first projection attempt is retained: its
receipt helper passed an augmented proof to a core-only certificate-tip check.
The corrected helper extracts the exact core and has a regression test.

A subsequent run exposed an advancing-certificate race before signing. An
empty SDK height can advance the shared floor while payment signatures are
being checked. An older producer context is now usable only when the entire
financial commitment and all four account states match the newer certificate.
The newer certificate is independently verified and remains the durable floor;
the original signing proof is retained unchanged. Changed monetary state or an
unverifiable newer certificate still stops signing. Stale CLI publications also
clear fresh-contact/process assertions while retaining historical certificates.

Ghidra through the existing bounded REA sandbox decompiled the current native
`main.checkFinancialProducerContext` slice: 1,808 bytes and 380 instructions.
The target code was not executed. The source and Go disassembly were compared
for source/epoch binding, creator bounds, allowlist, sequence overflow and
authenticated parent selection. External callees and global data were not
imported; Go register ABI was not reconstructed. This is a function-level
inspection, not a whole-binary audit or security guarantee.

## Primary-source research and applicability

BNB's account of the 6 October 2022 bridge incident describes forged proof
validation and unauthorized issuance. Our inference is to require both a
pinned certified context and the exact requested selector; an authenticated
transport or a generally valid receipt alone is insufficient.
[BNB Chain's incident response](https://www.bnbchain.org/en/blog/bnb-chain-a-decentralized-response).

The current CometBFT advisories include timestamp consistency and malformed
BitArray dimensions. The actual pinned v0.40.0 source includes commit-vote-only
median time and BitArray dimension validation. Two additional tests against
that exact derived SDK passed: unauthenticated nil/absent timestamps cannot
change the computed median, and mismatched bit dimensions are rejected. This
is narrower than claiming that all network DoS or timestamp threats are solved.
[Tachyon advisory](https://github.com/cometbft/cometbft/security/advisories/GHSA-c32p-wcqj-j677),
[BitArray advisory](https://github.com/cometbft/cometbft/security/advisories/GHSA-hrhf-2vcr-ghch).

Stratum V2 separates mining, job declaration and template distribution. Mining
devices, work providers and pool infrastructure have different responsibilities.
Our inference is to preserve explicit roles and avoid presenting the present
BFT validator or DAG producer as a miner or reward-paying pool. Pool accounting
and public rewards need a specified economic and consensus policy first.
[Stratum V2 protocol overview](https://stratumprotocol.org/specification/03-protocol-overview/).

## Remaining release gates and assumptions

The four native accounts have a fixed experimental allocation totaling
1,000,000,000,000 atomic units, with six decimals. This is not a selected public
issuance, fee, mining reward or pool payout policy. There is no mining or pool
reward implementation in this mode. Public financial economics and activation
require their own reviewed contract.

The current own journal permits one unresolved original per creator and has
explicit local record/byte limits. These are implementation limits, not proof
of the requested throughput. Certified client observations do not mean that a
client replayed all original history. Physical Windows/Linux/Termux behavior,
200 blocks/s with 5,000 monetary transactions per block, sustained catch-up,
fault/endurance acceptance and public testnet/mainnet readiness remain gates.
No absolute security guarantee or completed-network claim follows from this
stage. No intermediate Git push or physical bootstrap is its completion gate.
