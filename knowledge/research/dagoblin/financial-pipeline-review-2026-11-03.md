# Monetary batching, independent producers and durable pending originals

## Original intent

Keep the native CLI node authoritative. Desktop must represent its certified
account state and actual signed creator identity. A slow producer must work
at its own pace without stopping other producers. Preserve real account and
producer signatures, exclusive ownership, recovery and bounded resource use.
The eventual capacity requirement remains 5,000 actual payments per block at
hundreds of blocks per second. These local checks do not establish that rate.

## Findings

PrepareProposal previously selected one submitted financial package. Independent
creators therefore could not share an SDK checkpoint. A single unresolved own
original also prevented a producer from preparing a bounded chain in advance.
Neither behavior was a consensus requirement: the existing financial batch
format and execution kernel already support multiple original signed blocks.

A newer SDK certificate can include another creator's work while leaving this
creator's signing head intact. Comparing every account and the entire financial
commitment, as in the preceding production review, rejected such independent
progress. The relevant signing boundary is the authenticated source, epoch,
history cut, epoch base rank and this creator's exact committed author row.
The newer certificate still needs independent native verification and remains
the durable observation floor. Monetary balances, account nonces and execution
outcomes are always checked by native execution when selecting the originals.

An epoch cut can select only part of an own pending chain. For example, local
originals 1..8 may exist while only 1 was selected before the cut. The next
epoch then starts at selected sequence 2, not local unselected sequence 9.
The journal must retain both epochs' exact originals and authenticate the
selected sequence using the actual SDK base, without treating signatures as
selection evidence or silently changing an old original.

## Implementation decisions

Native selection has finite package, decoded-byte, output-byte and block
bounds. Each submitted package passes native financial transition checks before
its originals can be considered. Originals are deduplicated and ordered by
their authenticated rank and hash. Conflicting creator sequences and missing
parents cannot mutate the selected trial state. No payment is rescued from a
package containing an invalid account signature. SDK ProcessProposal,
FinalizeBlock and Commit retain their independent verification paths.

An automatic certified history cut is proposed before the active window has
fewer than 128 free records or 32 MiB of free byte capacity. Cuts use the
existing native transition, retain authenticated creator heads and preserve
receipts. This prevents the active-window ceiling from stopping selection;
it does not solve indefinite retained-history growth or stale-epoch liveness.
The existing financial source-v2 and block-v1 formats are unchanged.

The protected local journal atomically persists up to eight pending own
originals before exposing any for transport. Each record retains its real SDK
base and, when needed, references to earlier immutable own originals. These
references are private signing derivations, never public certificates or
selection claims. Retries compare exact payment intent and reuse the exact
signed originals. Cancellation, failed SQL commit and commit-outcome uncertainty
must not expose a partially persisted chain. Cold opening authenticates all
retained original signatures and their derivations. SQLite exclusive ownership
and a data-version guard protect the warm owner against external modification.

A private immutable account-authorization object avoids repeating account
signature verification within one local submission. It binds the exact
canonical original envelopes and genesis. Public JSON cannot inject this
object. It does not cache balances, nonces, finality or execution results;
the independent native SDK still verifies the submitted payments.

Signed transport carries a bounded own-prefix envelope, with original bytes
and source binding. The authority checks sender-to-creator ownership before
discarding already-selected prefix entries and rebroadcasts only the exact
remaining originals. An all-stale response asserts neither selection of those
particular original hashes nor payment execution. The CLI public-file command
accepts an explicit transactions_per_block split. Desktop remains read-only.
Its eligible producer count excludes observer/replica slots, while preserving
the full slot index space needed to label each creator correctly.

## Actual local evidence and its scope

The native kernel fixture combines four independent creators with 5,000 real
account-signed payments each, checks account conservation and nonces, verifies
receipts and cold-replays the resulting committed history. Other fixtures cover
arrival order, creator equivocation, invalid account signatures, missing
parents, exact byte limits, cancellation and automatic history cuts.

The separate owned process integration uses four native validators and one
nonvoting native observer. Eight protected originals carry 5,000 signed
payments each through the CLI file command and signed loopback transport.
One SDK checkpoint applies all 40,000 payments. All three paired client
publications agree on the account state. The producer is closed and cold-opened
and all eight originals are recovered. The receipt selector is checked against
the exact requested block and payment index. These are local Windows processes
with declared Windows/Linux/Termux labels, not physical device acceptance.

CPU profiling covers one genuine four-creator selection and cold replay.
Ed25519 field arithmetic and canonical JSON processing dominate the sampled
work. A one-batch creation-to-selection latency sample is also retained. Neither
measurement is a sustained throughput result or proof of the capacity goal.
No signature check was weakened to improve a benchmark.

Policy tests explicitly mock SDK/RPC boundaries where stated. Their passes
establish routing and journal behavior, not live consensus or cryptographic
certificate evidence. Native execution, native/WASM proof vectors, actual
process integration, Linux process tests and offscreen QML are separate checks.
Candidate compilation does not replace installed tools or restart Desktop.

## Remaining requirements and assumptions

Retained own originals still have an 8,191-record/512-MiB bound. Portable monetary
history export, recovery and retirement are required before indefinite running.
The transport's rate limits and original JSON payload sizes also remain real
capacity constraints. A slow transfer crossing an epoch cut can be rejected
safely; complete slow-producer liveness across cuts is not established here.

The fixed private four-account allocation is not general wallet onboarding.
Fees, issuance, mining rewards, pools, open validator admission and Sybil defense
are not activated by this pipeline. Their economic and public-security gates
remain open. No public testnet/mainnet activation, physical bootstrap or Git
publication is performed by these local component checks. No whole-system or
absolute security guarantee follows from the tests or function-level Ghidra
inspection documented in the preceding production review.
