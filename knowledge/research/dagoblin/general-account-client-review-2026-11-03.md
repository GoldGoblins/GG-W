# General-account Python and observation boundary review

## Original intent

CLI owns real node/account operations. Desktop must present the same verified
facts, identify the actual node/producer, and distinguish account ownership
from other nodes verifying a block. Independent accounts must not inherit
voting power or receive money merely by joining. Preserve existing accepted
formats while completing real signatures, persistent state and recovery.

## Facts and findings

The native account application already supports explicit genesis v6, source
v4, compact authenticated account state, historical membership/absence,
ordered receipts, atomic persistence and replay. This change does not change
that Go protocol or binary graph. Python previously required the four genesis
accounts and source v3, and its observation layer iterated the full account
list. The new public state deliberately has `accounts: null`.

An authenticated absence path can prove an interval containing several absent
addresses. A provider-supplied address, even next to a valid certificate, does
not identify the caller's request. Actual SDK-signed unit fixtures demonstrate
that a different valid absent point can use the same witness. Independent
request binding rejects that substitution.

## Decisions implemented

- Accept native genesis v6 only with source v4 and exact policy v3. Validate
  sorted unique positive allocations, total private test supply, 1..128 initial
  accounts and canonical decimal capacity up to 2^32. Reserve node, validator,
  owner-peer and producer keys. Member account keys and independent wallet
  keys may be financial accounts; neither receives new consensus authority.
- Add explicit signed LAN session v7. Its namespace binds the account policy.
  General mode requires an explicit allocation; ordinary creation still uses
  the existing session v6/source v3. Old v2/v3 session and pin bytes remain
  subject to exact regression comparison. No automatic migration or funding.
- Admit correctly signed version-1 payment envelopes for general addresses.
  Native ordered execution determines nonce, balance and account-cap outcomes;
  Python signature admission claims none of them. Keep the old whitelist for
  legacy mode. Source v4 retains exact old-epoch originals through permanent
  lineage, including own producer journals and retry contexts.
- Verify receipts, producer contexts and requested accounts with the actual
  owned native verifier and a separately pinned genesis. Account verification
  requires the independently requested address to match both request and proof.
- Carry session v7 through the existing financial LAN/runtime/observer routes.
  Account proof requests select a canonical address and a retained state height.
  Owned authority queries that exact height, then verifies the returned proof.
  Transport ACKs still assert no execution or account creation.
- Publish at most 64 locally retained requested account views. The snapshot
  publishes only rows matching the current certified state height and root.
  Decimal nonce/balance text is preserved. `exists: false` represents proven
  absence; its displayed zero does not create an account. Keep state height
  separate from the SDK certificate height. Conflict faults suppress rows.
  Legacy full four-account observations remain unchanged in monetary meaning.
- Desktop explicitly distinguishes a certified absent account from an existing
  account with zero balance. The absent view has no fabricated nonce/balance;
  its tooltip states absence at the verified certificate. A missing proof shows
  waiting. The global account count comes from certified tree metadata rather
  than the number of requested/local account rows. Actual isolated offscreen
  QML checks cover all four presentations, preserving decimal nonce text and
  producer identity labels, without touching the active app or capturing images.

## Verification and limits

The private stage records exact reviewed source versions, protected-profile
regressions, real account/producer signatures, actual native SDK-signed unit
proof checks, Linux checks and source-only CLI package checks. Proof tests
include malformed paths, roots, metadata, votes and independent address pins.
Authority query transport is a policy seam in the unit-proof check, and is not
presented as a running SDK authority. Protected profile fixtures use private
temporary storage and owned loopback listeners; no physical host or public
network claim follows from them.

The full delivery remains open: independent protected account profiles and
explicit CLI review/sign/send, Desktop selection of those
accounts, real general-model four-SDK execution and recovery, physical Linux
and Termux acceptance, measured capacity, reviewed public economics/admission
and independent security acceptance. Public supply, rewards, fees, mining and
pool solvency are not invented or enabled by this private test allocation.

No app restart, installed-tool replacement, physical bootstrap or publication
is part of this change. Existing source v3 live endurance remains historical
evidence, not a general-account v4 live-consensus result.
