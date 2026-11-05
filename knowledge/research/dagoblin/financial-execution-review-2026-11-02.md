# Ordered financial execution: kernel under integration

## Original intent and current boundary

The requested network must execute real payments, preserve unique account/node
ownership and durable history, and show CLI state accurately in Desktop. Signed
traffic, rendering, provisional admission and monetary finality are separate.
The complete network and conditional combined publication remain incomplete.

The existing native GG-NET-TEST ledger has four genesis accounts, six decimal
places, a fixed supply of 1,000,000 tokens and no transfer fees. Its ordinary
block limit is 128 native transfer envelopes. Existing signed DAG test traffic
uses a separate six-producer allocation and is explicitly nonfinancial; it does
not transfer GG-NET-TEST. Its test-state balances must not be called native money.
Mining, subsidy, pool accounting and payouts are not implemented by those counts.

## New implemented kernel

`support/gg-consensus/financial_execution.go` implements ordered execution of
existing native signed payment envelopes and context-bound receipt commitments.
It currently uses the existing four-account test ledger. It is not yet an active
DAG consensus rule, public transfer service, general account store or mainnet
economic model. No legacy genesis or source is silently changed.

* Validate the native genesis and complete incoming account state. Bound inputs
  to 50,000 envelopes, 2 KiB each and 32 MiB total before cryptographic work.
* Strictly validate every accepted envelope's signature, canonical bytes, chain,
  genesis, sender, recipient and amount before applying any payment. Invalid
  authentication or encoding anywhere rejects the whole input without partial
  monetary output. Independent signature work uses bounded joined workers.
* Execute the supplied order sequentially with exact integer balances and sender
  nonces. Applied payments debit/credit and increment the sender nonce once.
  Authentic nonce/funds conflicts receive explicit rejected receipts and leave
  balances/nonces unchanged; subsequent valid payments can still execute.
* Preserve the original state on failure or cancellation. No signature-result
  cache, newly issued tokens, fees or reward schedule is introduced.
* Bind each receipt to the exact signed payment intent, native genesis, source,
  epoch, checkpoint, ordered block identity and transaction position. Seal the
  complete summary, including input transcript, counts and both account roots,
  together with the receipt tree. Duplicate-last Merkle padding alone does not
  authenticate a leaf count; the sealed summary explicitly does.
* Receipt proof checking establishes inclusion against the supplied summary.
  It never independently authenticates that summary or asserts finality. SDK
  state must bind it before any client can treat the result as committed.

## Verification and meaning

Tests execute 5,000 separately signed monetary transfers, verify actual balance
changes and 1,250 nonce advances per sender, conserve supply, and compare serial
and parallel signature admission. Replaying the same bytes cannot debit twice.
Conflict, insufficient-funds, exhausted-nonce, bad-signature, cross-context,
noncanonical-input, cancellation and resource-bound cases are covered.

A separately calculated public Python fixture signs another 5,000 payments and
independently computes integer account changes, receipt hashes, tree and sealed
summary. Go must reproduce its exact accounts and receipt commitment. Seeds are
public synthetic test inputs; user account keys are not used.

The reproducible Python oracle is included as `financial_fixture.py` in the
native source package and CLI source graph. It requires an explicit `--output`
destination and refuses to replace an existing file. Its generated file is the
input to `TestFinancialPythonSignedFixtureAndIndependentReceiptRoot` through
`GG_PUBLIC_FINANCIAL_EXECUTION_FIXTURE`; without that optional fixture, ordinary
Go test runs explicitly skip that one interoperability case.

These are monetary-kernel tests. They do not prove 5,000 payments in a live DAG
block, end-to-end throughput, permissionless security, mining or pool payouts.
The existing full/native/browser regression gates and exact artifact receipts
still need to match the final source revision before release.

## Research implications

ABCI proposal checks may run repeatedly, whereas committed execution must be
deterministic. State writes cannot depend on a proposal check having run during
replay. The kernel therefore returns owned state/results without I/O; future
SDK integration must commit state and durable data through the existing commit
boundary. [CometBFT ABCI concepts](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_basic_concepts.md),
[Cosmos ABCI integration](https://github.com/cosmos/cosmos-sdk/blob/main/docs/architecture/adr-064-abci-2.0.md).

Historical forged-proof and signing-interface incidents motivate binding exact
proof context and signed intent independently of presentation. This is an
engineering inference, not evidence that this kernel has undergone an external
audit. [BNB Chain incident update](https://www.bnbchain.org/en/blog/bnb-chain-ecosystem-update),
[Bybit investigation update](https://www.bybit.com/en/press/post/bybit-confirms-security-integrity-amid-safe-wallet-incident-no-compromise-in-infrastructure-blt9986889e919da8d2).

Pool work messages do not supply durable share obligations, reward allocation,
rounding or payout recovery. Those rules require their own protocol and tests;
none is inferred from participation labels. [Stratum V2 Job Declaration](https://stratumprotocol.org/specification/06-job-declaration-protocol/).

## Remaining integration

Bind the financial model into an explicitly versioned genesis/source. Authenticate
producer payload and canonical DAG order before invoking this kernel. Include
receipt/account commitments in SDK state, persist and independently replay them
across restarts/cuts, provide certified receipt/account reads, and project actual
applied/rejected counts in CLI/Desktop. Keep every existing signed lab identity
and protocol's meaning intact. The general account model, economic incentives,
physical acceptance and sustained performance targets remain open requirements.
