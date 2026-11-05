# DAGoblin: signed segmented LAN session contract

Date: 2026-11-01. Extends the certified epoch-base review.

## Original intent

Keep existing LAN behavior while connecting the segmented native ledger,
persistent producer identity and Desktop to a single verifiable network.
The source must identify actual owners and participation roles. Signatures
must remain confined to the selected network across restarts and cuts.

## Findings and decisions

The legacy LAN identity hashes a complete session containing its public DAG
genesis. A segmented signing domain additionally commits its network identity.
Simply reusing that construction would make the new genesis depend on itself.

The new `gg.lan-dag.session.v5` contract therefore computes a separate namespace
from the signed roster, explicit committee, coordinator, label, new public
session nonce, participation policy and start time. It derives the segmented
source and public DAG genesis afterward. Independent validation repeats that
derivation and requires exact agreement with the transmitted public genesis.
The resulting native v4 genesis includes that source and the same committee.
Its public anchor is the canonical native-genesis digest.

Both roster ownership signatures and the coordinator's session signature are
checked. Owners, their two producer indices, all six producer keys, endpoints,
roles and committee proofs must agree. Changing a context field and merely
resigning the old public genesis fails. Identical inputs, including reordered
input invites, produce an identical canonical contract.

The principle of including network identity in the signed transaction domain
also appears in Ethereum's [EIP-155](https://eips.ethereum.org/EIPS/eip-155).
The GG construction here is our own derivation for its signed roster and
committee; this analogy is not evidence of equivalent security or capacity.

Producer and validator roles remain separate. A DAG replica does not acquire
producer rights. As in the existing membership contract, its owner may own an
explicitly invited validator. A light owner cannot join the validator committee.
No participation label alone grants voting authority.

## Implementation

`backend/gg_dag_segmented_session.py` constructs and verifies the contract without
opening a listener, starting a process, generating a key or installing a session.
`anchor_from_bundle` dispatches this explicit schema to the new validator; its
legacy v4 derivation is unchanged. The new module is included in the reviewed
headless CLI source graph.

The existing LAN runtime deliberately rejects v5 activation until its durable
producer lifecycle and segmented SDK controller are connected. An available
contract codec is not a claim of implemented LAN negotiation or crash-safe
NodeProfile activation. No current session is silently converted.

## Executed evidence

- Eleven session/domain tests passed. They cover deterministic derivation,
  signed role ownership, nonce/label/time/committee domain changes, modified
  and resigned contexts, duplicate identities/endpoints, light/unregistered
  committee owners and rejection of a genuine initial block from another
  session. The existing runtime's rejection before activation is also checked.
- Four actual SDK validator processes consumed the native genesis derived from
  a signed v5 session through membership-bound `gg.consensus.bootstrap.v2`.
  Seventeen process instances ran across hard restarts, selecting 15,002 unique
  individually signed transactions, five DAG blocks and two cuts. Three
  validators continued while the fourth was absent, and the fourth caught up.
- Native and Python verified six epoch-base packets from that actual signed
  committee. Five portable archive exports were replayed; the first four
  independent stores exported identical histories. Python's explicit RAM
  producer experiment continued the exact nonce and sequence after recovery.
- Native, WASM and Python agreed on all eleven base-proof cases: five previous
  native-application test-signature vectors and six new actual signed-committee
  SDK packets. All 91 manipulated/saved counterexample cases were rejected by
  all three. These membership/base proofs do not claim full client replay.
- Native and WASM sources did not change in this stage. Tests used the exact
  previously compiled artifacts, with manifest/file integrity checked. Prior
  native Go and Ghidra results remain evidence for those unchanged native
  sources, rather than being relabelled as fresh builds or a new binary audit.

Initial test failures are preserved separately. One new test incorrectly
assumed replica ownership implied a ban on explicit validator ownership; the
existing role contract was preserved and the test corrected. The first SDK
harness expected the unanchored readiness-v1 message instead of membership
readiness-v2. A browser test also needed its alternative native pin to update
both native and membership chain IDs. Production pin validation stayed strict.

## Assumptions and outstanding work

These process experiments ran on one Windows host with public deterministic
test identities and owned loopback endpoints. They are not physical Linux or
Android execution, throughput at the target rate, power-loss durability or
public-network acceptance. The four SDK validator processes use signed explicit
membership; public Sybil resistance and economic participation are not supplied
by a private invitation system.

Next: connect durable producer signing/admission journals and the owned native
authority across cuts, then activate signed v5 negotiation and bind Desktop to
that same verified account/creator state. Archive retrieval/storage policy,
power-loss testing, monetary/mining/pool rules, physical capacity/endurance and
public acceptance remain open. No active Desktop restart, installed-tool
replacement, physical update, bootstrap distribution or Git push occurred here.
