# Financial DAG: explicit native integration and receipt authentication

The original requirement remains real account-signed payments in producer-owned
DAG blocks, slow independent nodes, durable identities/history and an accurate
CLI/Desktop representation. This review extends the 2026-11-02 monetary kernel;
it does not declare the complete network or public monetary policy ready.

## Facts and implementation

An explicitly selected `gg.native.genesis.v5` binds a financial source and exact
test policy. Native state/commitment use v4. Existing genesis v1–v4, transaction
bytes and nonfinancial DAG rules retain their previous meanings. This is a new
network definition, never a migration of an existing account/history database.

The source owns six distinct prime-order producer keys, separate from the four
native account and validator roles. A producer signs each complete canonical
block containing account-signed native payments. Parent membership, the real
creator head, monotonically increasing creator sequence, source, native anchor,
epoch, rank, payment root and consensus-time bounds are checked. Slow producers
can extend authentic older parents without requiring the fastest current rank.

Payments execute in SDK-selected block/transaction order. Applied payments
debit/credit real integer account balances and advance the sender nonce once.
Authenticated nonce/funds conflicts produce explicit rejection receipts without
spending funds or consuming a new nonce. Malformed authentication rejects the
whole candidate atomically. Proposal/mempool calculations cannot publish money.

Every monetary operation in this new mode must belong to a financial DAG block.
Standalone native transfers are rejected in this mode, so a replay cannot omit
an alternative balance-changing path. Legacy transfer modes remain available
under their existing genesis definitions.

`financial_ledger.go` implements real ABCI CheckTx, PrepareProposal,
ProcessProposal, FinalizeBlock and Commit. Original candidate bytes sync before
proposal acceptance. At most two original candidates are retained; an empty SDK
commit releases their credit. FinalizeBlock stages a result; only synchronous
atomic Commit selects the journal/head, monetary state and receipt metadata.
An uncertain write faults the store rather than publishing a success.

The separate `gg-financial-dag.leveldb` journals every selected SDK height,
including empty heights, original signed batches and cuts. Opening an existing
store requires the complete consecutive journal and re-executes original signed
payments from genesis. Startup compares the resulting balances, commitments,
derived receipts and every summary-tree node with the stored selection. Missing,
changed or extra selected entries fail closed. It never recovers from a saved
balance snapshot alone or recreates a missing database.

Active causal/index memory is bounded to 4,095 blocks and 512 MiB of original
wire data per segment. A cut preserves accounts, real author identities,
sequences, monetary counts, summaries and original journal data. Total durable
history grows with activity; this implementation provides no disk pruning or
snapshot bootstrap. The retained public state query window is 256 SDK heights.

## Findings and verification boundaries

Each sealed payment summary and its actual creator key/index/sequence enter a
global authenticated Merkle accumulator. A compact receipt proves both payment
outcome inclusion in that summary and summary membership in the complete
SDK-certified commitment. The commitment separately authenticates the global
block count; duplicate-last Merkle padding alone is not count authentication.
Closed segment cuts do not erase earlier receipt proofs.

The public native/WASM verifier checks the committee certificate, full state
root, selected receipt path, producer identity, account signature and exact
signed payment intent. The Python wrapper pins an independently owned genesis
before invoking that verifier. A peer-provided `verified` flag or a self-chosen
committee is insufficient. Historical evidence proves an outcome at its stated
height; it never proves current connection or fresh network contact.

Public queries are `/gg/financial-dag/source`, `/gg/financial-dag/commitment`,
`/gg/financial-dag/receipt` and `/gg/financial-dag/cut-transaction`.
`/gg/dag/commitment` also returns the selected financial commitment. Receipt
selectors use `{block,index}`; a single receipt contains neither a full block nor
the journal. Original journal data remains mandatory for receipt reconstruction.

Tests cover 5,000 actual signed payments in one producer-signed block, exact
money/nonces, rejected double spends, Python-independent monetary commitments,
stale branches, a full active segment, cuts, empty heights, cold replay after the
public state window rolls over, uncertain writes, damaged journals/receipt
metadata, compact certified receipts, substituted creators and odd-length
Merkle paths. Broader regression/build and binary inspection evidence must match
the final source before a publication gate can pass.

## Decisions, assumptions and remaining gates

This preserves the existing fixed four-account TEST allocation: 1,000,000 GG at
six decimals, with 250,000 GG initially assigned to each genesis account. There
are no fees, mining subsidies, stake rewards or pool payout obligations in this
mode. A successful block count must never be displayed as earned money.

The node/store is integrated, but automatic financial-source selection,
production payment admission, complete CLI/Desktop receipt flows, portable
financial history export and a general account model remain separate work.
Neither the existing LAN network nor installed tools are replaced by this code
phase. Permissionless Sybil resistance and economic issuance/pool policy remain
unimplemented; a private fixed committee is not a mainnet security model.

No end-to-end 5,000-payment/block throughput at hundreds of blocks/s, physical
Windows/Linux/Termux fault/endurance result, host-key assessment or public launch
approval follows from unit tests, cross-compilation or a static function slice.
Absolute security and permanent freedom from future fixes are not established.

## Research applied

[CometBFT v0.40.0 application requirements](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_app_requirements.md)
require deterministic proposal processing, a read-only committed query view and
durable application selection during Commit. Candidate persistence is kept
separate from selected state; recovery reports the selected committed height.

[Ethereum rewards and penalties](https://ethereum.org/developers/docs/consensus-mechanisms/pos/rewards-and-penalties/)
illustrate that incentives depend on concrete stake and penalty rules. They do
not provide a transferable reward schedule or Sybil defense for this private
test committee. Economic rules must be implemented and audited as actual ledger
transitions before describing mining or pool payouts as available.

The prior security research and monetary-kernel review remain relevant. Their
historical incident dates, proof limits and Ghidra function-only scope must not
be relabeled as a current exchange incident or a full-network security audit.
